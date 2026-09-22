"""uvicorn's own loggers under the REAL uvicorn logging config (round 2 of batch 1).

Found by an independent attacker pass and then reproduced on the real app under real uvicorn:

  * Starlette re-raises an unhandled exception after the app's 500 handler has run
    (starlette/middleware/errors.py), and uvicorn logs it on `uvicorn.error` with its OWN handler:
    a second, unredacted traceback (the database-echoed client value included) next to the app's
    redacted JSON line.
  * `configure_logging` disables `uvicorn.access` at import time, but uvicorn applies its own
    dictConfig when the server starts, which turned it back on. The older test only checked the
    in-process flag, so it passed while the claim (no raw path or query string in a log line) was
    false. Failure mode 9: test the real thing, in the real order.

The fix runs in the app's lifespan, which uvicorn starts AFTER its own logging config.
"""

from __future__ import annotations

import copy
import json
import logging
import logging.config
import os
import re
import socket
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn.config
from fastapi.testclient import TestClient

from app.main import app

_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")
_BACKEND = Path(__file__).resolve().parents[2]


def _secret() -> str:
    return "UVSE" + "CRET" + os.urandom(3).hex()  # built at runtime: never a literal in a traceback


def _db_error(secret: str) -> RuntimeError:
    return RuntimeError(
        'duplicate key value violates unique constraint "k"\n'
        f"DETAIL:  Key (val)=({secret}) already exists."
    )


@pytest.fixture
def uvicorn_started(capsys: pytest.CaptureFixture[str]) -> Iterator[None]:
    """The order uvicorn uses: its own logging config first, then the app's lifespan."""
    root = logging.getLogger()
    saved_root = list(root.handlers)
    saved = {
        n: (list(lg.handlers), lg.propagate, lg.disabled, lg.level)
        for n in _NAMES
        for lg in [logging.getLogger(n)]
    }
    logging.config.dictConfig(copy.deepcopy(uvicorn.config.LOGGING_CONFIG))
    try:
        with TestClient(app):
            capsys.readouterr()  # drop anything printed while starting
            yield
    finally:
        root.handlers[:] = saved_root
        for name, (handlers, propagate, disabled, level) in saved.items():
            lg = logging.getLogger(name)
            lg.handlers[:] = handlers
            lg.propagate = propagate
            lg.disabled = disabled
            lg.setLevel(level)


def test_a_traceback_logged_by_uvicorn_is_redacted_and_is_one_json_line(
    uvicorn_started: None, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = _secret()
    try:
        raise _db_error(secret)
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    out, err = capsys.readouterr()
    assert secret not in out + err, (
        "the database-echoed value reached a log stream through uvicorn.error"
    )
    assert err == "", f"uvicorn's own handler still prints to stderr: {err[:120]!r}"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one JSON line, got {len(lines)}"
    record = json.loads(lines[0])
    assert record["message"] == "Exception in ASGI application"
    assert "DETAIL:  [redacted]" in record["exc"]
    assert "RuntimeError" in record["exc"], "the exception class must stay visible"


def test_uvicorns_access_line_stays_disabled_after_uvicorn_applies_its_own_config(
    uvicorn_started: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The access line has the raw path AND query string (ASVS 14.2.1); app.access has the route."""
    secret = _secret()
    # codeql[py/clear-text-logging-sensitive-data] deliberate: assert below proves no leak
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", f"/tasks?q={secret}", "1.1", 200
    )
    out, err = capsys.readouterr()
    assert secret not in out + err
    assert logging.getLogger("uvicorn.access").disabled is True


def test_uvicorn_startup_lines_also_use_the_json_formatter(
    uvicorn_started: None, capsys: pytest.CaptureFixture[str]
) -> None:
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    out, err = capsys.readouterr()
    assert err == ""
    assert json.loads(out.strip().splitlines()[-1])["message"] == "Application startup complete."


_SERVER_SCRIPT = textwrap.dedent(
    """
    import os, sys, threading, time, urllib.error, urllib.request
    import uvicorn
    from app.main import app

    PORT = int(os.environ["PROBE_PORT"])

    @app.get("/__probe_boom")
    def boom() -> None:
        value = "UVSE" + "CRET" + os.environ["PROBE_SUFFIX"]
        head = 'duplicate key value violates unique constraint "k"\\nDETAIL:  Key (val)=('
        raise RuntimeError(head + value + ") already exists.")

    def hit() -> None:
        time.sleep(3)
        try:
            url = f"http://127.0.0.1:{PORT}/__probe_boom?q=QUERYSECRET"
            urllib.request.urlopen(url, timeout=10)
        except urllib.error.HTTPError as e:
            print("CLIENT GOT", e.code, flush=True)
        time.sleep(1)
        os._exit(0)

    threading.Thread(target=hit, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT)  # uvicorn's DEFAULT logging config
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_real_app_under_real_uvicorn_prints_no_raw_traceback_and_no_access_line() -> None:
    suffix = os.urandom(3).hex()
    secret = "UVSECRET" + suffix
    env = {
        **os.environ,
        "PROBE_PORT": str(_free_port()),
        "PROBE_SUFFIX": suffix,
        # the parent's import path, so the child sees the same packages however pytest was started
        "PYTHONPATH": os.pathsep.join([str(_BACKEND), *filter(None, sys.path)]),
    }
    # S603: the command is this interpreter and a constant script; no input is interpolated
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _SERVER_SCRIPT],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    output = done.stdout + done.stderr
    # non-vacuity: the request really failed with a 500, and the app's own redacted line is there
    assert "CLIENT GOT 500" in output, output[-600:]
    assert "Unhandled exception on /__probe_boom" in output, output[-600:]
    assert "DETAIL:  [redacted]" in output
    # the point
    assert secret not in output, "a raw, unredacted traceback reached stdout/stderr"
    assert "QUERYSECRET" not in output, "uvicorn's access line printed the raw query string"
    assert not re.search(r'"GET /\S* HTTP/1\.1" \d{3}', output), "uvicorn's access line is enabled"
