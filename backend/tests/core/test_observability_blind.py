"""Blind tests for the observability slice (SPEC sections A, B, C) — written against the public
contract only: HTTP behaviour through TestClient, captured stdout (capsys), and the few named
interfaces (`configure_logging`, `bind_identity`, `install_pool_monitor`, `app.core.db.engine`).

Every test docstring names the SPEC clause it verifies. `# ASSUMPTION:` marks where the SPEC was
ambiguous and a reading had to be picked.

Hermetic: no test here reaches a real DB or the network. `/ready` tests substitute
`app.core.db.engine` with SQLite engines; the JWKS lookup is patched so a Bearer token never
triggers a network fetch. Only the SPEC A11 section uses Postgres (skipped without the env vars).
"""

import asyncio
import io
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.pool import QueuePool

from app.api import deps
from app.core import security
from app.core.db import install_pool_monitor
from app.main import app
from app.models import Profile

# Modules this slice adds; `# isort: skip` keeps this file lint-stable whether or not they exist
# yet (ruff classifies a not-yet-existing module as third-party, an existing one as first-party).
from app.core.logging_setup import configure_logging  # isort: skip
from app.core.request_context import bind_identity  # isort: skip

# --------------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "ts",
    "level",
    "logger",
    "message",
    "request_id",
    "tenant_id",
    "actor_id",
    "actor_role",
}
_POOL_KEYS = ("pool_checked_out", "pool_capacity", "threadpool_borrowed", "threadpool_total")
_ACCESS_KEYS = {"method", "route", "status", "duration_ms", *_POOL_KEYS}
# ASSUMPTION: the C1 pool-warning extras (checked_out/capacity/utilization) may legitimately show
# up in the JSON line of an `app.pool` record, so they are tolerated by the A2 allowlist check.
_ALLOWED_KEYS = (
    _REQUIRED_KEYS | _ACCESS_KEYS | {"exc", "event", "checked_out", "capacity", "utilization"}
)
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_UID1 = "00000000-0000-4000-8000-000000000001"

Record = dict[str, Any]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_schema(rec: Record) -> None:
    """SPEC A2: required keys always present, allowlisted keys only, sane types."""
    assert set(rec) >= _REQUIRED_KEYS, f"missing keys: {_REQUIRED_KEYS - set(rec)}"
    assert set(rec) <= _ALLOWED_KEYS, f"non-allowlisted keys emitted: {set(rec) - _ALLOWED_KEYS}"
    parsed = datetime.fromisoformat(rec["ts"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    assert rec["level"] in _LEVELS
    assert isinstance(rec["logger"], str)
    assert isinstance(rec["message"], str)
    for key in ("request_id", "tenant_id", "actor_id", "actor_role"):
        assert rec[key] is None or isinstance(rec[key], str)
    if "exc" in rec:
        assert isinstance(rec["exc"], str)


def _records(out: str) -> list[Record]:
    """SPEC A1/A6: every stdout line is exactly one JSON object.

    Split on "\\n" only (not str.splitlines, which would also split on U+2028 and friends and
    hide a raw separator inside a line).
    """
    if not out:
        return []
    assert out.endswith("\n"), "last log line is not newline-terminated"
    parsed: list[Record] = []
    for line in out.split("\n")[:-1]:
        assert line != "", "blank line in log output"
        obj = json.loads(line)
        assert isinstance(obj, dict)
        _check_schema(obj)
        parsed.append(obj)
    return parsed


def _access(records: list[Record]) -> list[Record]:
    return [r for r in records if r["logger"] == "app.access"]


def _assert_uuid4(value: object) -> None:
    assert isinstance(value, str)
    parsed = uuid.UUID(value)
    assert parsed.version == 4
    assert str(parsed) == value


def _assert_access_shape(rec: Record) -> None:
    """SPEC A3 field contract."""
    assert rec["level"] == "INFO"
    assert rec["message"] == "request"
    assert isinstance(rec["method"], str)
    assert rec["method"]
    assert isinstance(rec["route"], str)
    assert _is_int(rec["status"])
    duration = rec["duration_ms"]
    assert isinstance(duration, int | float)
    assert not isinstance(duration, bool)
    assert duration >= 0
    for key in _POOL_KEYS:
        assert key in rec
        assert rec[key] is None or _is_int(rec[key])
    if _is_int(rec["threadpool_borrowed"]) and _is_int(rec["threadpool_total"]):
        assert 0 <= rec["threadpool_borrowed"] <= rec["threadpool_total"]


def _try(client: TestClient, method: str, url: str, **kwargs: Any) -> httpx.Response | None:
    """Send a hostile request; None if the *client library* refused to build it."""
    try:
        return client.request(method, url, **kwargs)
    except (httpx.InvalidURL, httpx.LocalProtocolError, ValueError, UnicodeError):
        return None


class _Payload(BaseModel):
    count: int


def _register_whoami_routes(target: FastAPI) -> None:
    """Test-only routes (SPEC A7's `/__blind_whoami` idea: bind, log a warning, return)."""

    def whoami(
        tenant: str | None = None,
        actor: str | None = None,
        role: str | None = None,
        delay: float = 0.0,
        fail: int | None = None,
    ) -> dict[str, bool]:
        bind_identity(tenant_id=tenant, actor_id=actor, actor_role=role)
        if delay:
            time.sleep(delay)
        logging.getLogger("app").warning("blind-marker")
        if fail:
            raise HTTPException(fail, "blind failure")
        return {"ok": True}

    async def whoami_async(
        tenant: str | None = None,
        actor: str | None = None,
        role: str | None = None,
        delay: float = 0.0,
    ) -> dict[str, bool]:
        bind_identity(tenant_id=tenant, actor_id=actor, actor_role=role)
        await asyncio.sleep(delay)
        logging.getLogger("app").warning("blind-marker")
        return {"ok": True}

    def binder(
        tenant: str | None = None, actor: str | None = None, role: str | None = None
    ) -> None:
        # Mirrors the real auth dependency: a sync dependency (own worker thread) that binds.
        bind_identity(tenant_id=tenant, actor_id=actor, actor_role=role)

    def whoami_dep(delay: float = 0.0) -> dict[str, bool]:
        time.sleep(delay)
        logging.getLogger("app").warning("blind-marker")
        return {"ok": True}

    async def whoami_dep_async(delay: float = 0.0) -> dict[str, bool]:
        await asyncio.sleep(delay)
        logging.getLogger("app").warning("blind-marker")
        return {"ok": True}

    binder_dep = [Depends(binder)]
    target.add_api_route("/__blind_whoami", whoami, methods=["GET"])
    target.add_api_route("/__blind_whoami_async", whoami_async, methods=["GET"])
    target.add_api_route(
        "/__blind_whoami_dep", whoami_dep, methods=["GET"], dependencies=binder_dep
    )
    target.add_api_route(
        "/__blind_whoami_dep_async", whoami_dep_async, methods=["GET"], dependencies=binder_dep
    )


def _register_failure_routes(target: FastAPI) -> None:
    """Test-only routes that raise (500), fail validation (422) or try to forge log context."""

    def boom(tag: str, tenant: str | None = None) -> dict[str, bool]:
        bind_identity(tenant_id=tenant)
        raise RuntimeError("SECRET_EXC_TEXT")

    async def boom_async(tag: str, tenant: str | None = None) -> dict[str, bool]:
        bind_identity(tenant_id=tenant)
        raise RuntimeError("SECRET_EXC_TEXT")

    def echo(payload: _Payload, n: int = 0) -> dict[str, bool]:
        return {"ok": True}

    def forge() -> dict[str, bool]:
        logging.getLogger("app").warning(
            "forge",
            extra={
                "request_id": "forged-rid",
                "tenant_id": "forged-tenant",
                "actor_id": "forged-actor",
                "actor_role": "forged-role",
                "PASSWORD_SENTINEL": "hunter2-sentinel",
            },
        )
        return {"ok": True}

    target.add_api_route("/__blind_boom/{tag}", boom, methods=["GET"])
    target.add_api_route("/__blind_boom_async/{tag}", boom_async, methods=["GET"])
    target.add_api_route("/__blind_echo", echo, methods=["POST"])
    target.add_api_route("/__blind_forge", forge, methods=["GET"])


@pytest.fixture(scope="module", autouse=True)
def _blind_routes() -> Generator[None]:  # pyright: ignore[reportUnusedFunction]
    before = list(app.router.routes)
    _register_whoami_routes(app)
    _register_failure_routes(app)
    app.openapi_schema = None
    yield
    app.router.routes[:] = before
    app.openapi_schema = None


@pytest.fixture(autouse=True)
def _no_jwks_network(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JWT-shaped Bearer token would otherwise make PyJWKClient fetch the JWKS remotely."""

    def _fail(token: str) -> object:
        raise jwt.PyJWTError("signature verification failed")

    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        _fail,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------------------------
# A1 / A2 — output channel, idempotence, record schema
# --------------------------------------------------------------------------------------------


def test_record_outside_request_has_full_schema_and_null_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A1+A2: one JSON line on stdout; all context keys present and null outside a request."""
    before = datetime.now(UTC)
    logging.getLogger("blind.outside").warning("hello %s", "world")
    captured = capsys.readouterr()

    recs = _records(captured.out)
    assert len(recs) == 1
    rec = recs[0]
    assert set(rec) == _REQUIRED_KEYS  # no exc/event/access keys on a plain record
    assert rec["level"] == "WARNING"
    assert rec["logger"] == "blind.outside"
    assert rec["message"] == "hello world"
    assert rec["request_id"] is None
    assert rec["tenant_id"] is None
    assert rec["actor_id"] is None
    assert rec["actor_role"] is None
    ts = datetime.fromisoformat(rec["ts"])
    assert abs((ts - before).total_seconds()) < 60
    assert '"blind.outside"' not in captured.err  # not duplicated onto stderr


def test_configure_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    """A1: calling configure_logging() again must not duplicate lines."""
    configure_logging()
    configure_logging()
    configure_logging()
    logging.getLogger("blind.idem").warning("once")
    assert len(_records(capsys.readouterr().out)) == 1


# ADJUSTED after integration (recorded in docs/SECURITY_AUDIT_CHECKLIST.md): the blind author's
# list included "uvicorn.access". The implementation deliberately DISABLES that logger — it logs the
# raw path AND query string (ASVS 14.2.1) and would duplicate app.access — a decision the written
# spec did not cover. It is pinned separately by tests/core/test_logging_setup.py::
# test_uvicorns_own_access_log_is_disabled.
@pytest.mark.parametrize(
    "name",
    ["uvicorn", "uvicorn.error", "sqlalchemy.engine", "httpx", "some.third.lib"],
)
def test_third_party_loggers_emit_exactly_one_json_line(
    capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """A1: 'any logger, including third-party' goes through the same single JSON channel."""
    logging.getLogger(name).warning("third-party %s", "line")
    recs = _records(capsys.readouterr().out)
    assert len(recs) == 1
    assert recs[0]["logger"] == name
    assert recs[0]["message"] == "third-party line"


def test_stdout_is_resolved_at_emit_time(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1: sys.stdout is looked up per emit, not captured once at configure time."""
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    logging.getLogger("blind.emit").warning("to-the-swapped-stream")
    assert len(_records(buf.getvalue())) == 1
    assert capsys.readouterr().out == ""


def test_hostile_message_content_stays_one_valid_line(capsys: pytest.CaptureFixture[str]) -> None:
    """A1+A6: newlines/CR/quotes/braces/U+2028 inside a message or its args cannot forge lines."""
    forged = '{"level":"CRITICAL","logger":"x","message":"forged"}'
    logger = logging.getLogger("blind.hostile")
    logger.warning('a\nb\r\nc \u2028 "q" }{ %s', "arg\nwith\nnewlines " + forged)
    logger.warning("second")
    out = capsys.readouterr().out

    recs = _records(out)
    assert len(recs) == 2
    assert all(r["level"] == "WARNING" for r in recs)  # the forged CRITICAL never became a record
    assert recs[1]["message"] == "second"
    assert "\r" not in out
    assert out.count("\n") == 2
    # No consumer using str.splitlines() may see extra lines either.
    assert len(out.splitlines()) == 2


def test_exc_field_only_present_with_exception_info(capsys: pytest.CaptureFixture[str]) -> None:
    """A2: `exc` (string) exists only when the record carries exception info."""
    logger = logging.getLogger("blind.exc")
    logger.warning("plain")
    try:
        raise ValueError("kaboom-sentinel")
    except ValueError:
        logger.exception("with-exc")
    plain, with_exc = _records(capsys.readouterr().out)

    assert "exc" not in plain
    assert with_exc["level"] == "ERROR"
    assert "ValueError" in with_exc["exc"]


def test_unknown_extras_are_not_emitted_but_event_is(capsys: pytest.CaptureFixture[str]) -> None:
    """A2: extras are allowlisted; `event` is the optional caller-provided key."""
    logging.getLogger("blind.extra").warning(
        "x",
        extra={"event": "my_event", "password": "hunter2-sentinel", "authorization": "Bearer zzz"},
    )
    out = capsys.readouterr().out
    (rec,) = _records(out)
    assert rec["event"] == "my_event"
    assert "password" not in rec
    assert "authorization" not in rec
    assert "hunter2-sentinel" not in out


def test_logging_call_with_bad_arguments_never_raises(capsys: pytest.CaptureFixture[str]) -> None:
    """A1/A10 spirit: a malformed format string or exotic extra must not raise into the caller
    and must not poison later records.
    """
    # ADJUSTED after integration: pytest's own LogCaptureHandler deliberately RE-RAISES a bad
    # logging call (its handleError) so tests catch them — that's pytest, not the app's handler,
    # whose emit() swallows it. Detach pytest's handlers so this exercises only the app's channel.
    logger = logging.getLogger("blind.robust")
    root = logging.getLogger()
    pytest_handlers = [h for h in root.handlers if type(h).__module__.startswith("_pytest")]
    for handler in pytest_handlers:
        root.removeHandler(handler)
    try:
        logger.warning("needs two %s %s", 1)
        logger.warning("weird extra", extra={"event": object()})
        logger.warning("fine")
    finally:
        for handler in pytest_handlers:
            root.addHandler(handler)
    out = capsys.readouterr().out
    lines = [line for line in out.split("\n") if line.startswith("{")]
    parsed = [json.loads(line) for line in lines]  # every JSON-looking line must still parse
    assert parsed[-1]["message"] == "fine"


# --------------------------------------------------------------------------------------------
# A3 / A4 — access record and request id
# --------------------------------------------------------------------------------------------

_ROUTE_CASES: list[tuple[str, str, dict[str, Any], str, int | None]] = [
    ("GET", "/health", {}, "/health", 200),
    ("GET", "/tasks", {}, "/tasks", None),
    ("GET", f"/tasks/{_UID1}", {}, "/tasks/{task_id}", None),
    (
        "PATCH",
        f"/tasks/{_UID1}/deadline",
        {"json": {"deadline": "2030-01-01T00:00:00Z"}},
        "/tasks/{task_id}/deadline",
        None,
    ),
    ("POST", "/tasks", {"json": {"title": "x"}}, "/tasks", None),
    ("GET", "/definitely/not/a/route", {}, "<unmatched>", 404),
    ("POST", "/__blind_echo", {"json": {"count": "not-an-int"}}, "/__blind_echo", 422),
    ("GET", "/__blind_boom/t", {}, "/__blind_boom/{tag}", 500),
    ("GET", "/__blind_boom_async/t", {}, "/__blind_boom_async/{tag}", 500),
    ("GET", "/tasks", {"headers": {"Authorization": "Bearer a.b.c"}}, "/tasks", 401),
]


@pytest.mark.parametrize(("method", "url", "kwargs", "route", "status"), _ROUTE_CASES)
def test_every_request_gets_exactly_one_access_record(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    method: str,
    url: str,
    kwargs: dict[str, Any],
    route: str,
    status: int | None,
) -> None:
    """A3+A4: one `app.access` INFO record per request, route template not raw path, status equals
    the status actually returned, and the response header carries the same request id.
    """
    resp = client.request(method, url, **kwargs)
    recs = _records(capsys.readouterr().out)

    access = _access(recs)
    assert len(access) == 1
    rec = access[0]
    _assert_access_shape(rec)
    assert rec["method"] == method
    assert rec["route"] == route
    assert rec["status"] == resp.status_code
    if status is not None:
        assert resp.status_code == status
    _assert_uuid4(rec["request_id"])
    assert resp.headers["x-request-id"] == rec["request_id"]
    if resp.status_code in (401, 403, 404, 422):
        assert rec["actor_id"] is None  # nothing was authenticated


def test_duration_ms_is_milliseconds_of_real_elapsed_time(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A3: duration_ms >= 0 and (sanity) reflects the handler's 0.3s sleep, in milliseconds.

    # ASSUMPTION: duration covers handler execution, so >= ~200 ms and well under 30 s.
    """
    client.get("/__blind_whoami", params={"delay": 0.3})
    (rec,) = _access(_records(capsys.readouterr().out))
    assert 200 <= rec["duration_ms"] < 30_000


def test_request_ids_are_unique_uuid4_and_match_records(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A4: server-generated UUID4, unique per request, header == record id (incl. 404/500)."""
    urls = ["/health", "/nope", "/__blind_boom/x", "/tasks", "/__blind_whoami"] * 5
    header_ids = [client.get(u).headers["x-request-id"] for u in urls]
    access = _access(_records(capsys.readouterr().out))

    for rid in header_ids:
        _assert_uuid4(rid)
    assert len(set(header_ids)) == len(urls)
    assert [r["request_id"] for r in access] == header_ids


@pytest.mark.parametrize("path", ["/health", "/__blind_boom/x", "/nope", "/tasks"])
@pytest.mark.parametrize(
    "supplied",
    ["client-supplied-id-SENTINEL", "11111111-2222-4333-8444-555555555555", ""],
)
def test_client_supplied_request_id_is_ignored(
    client: TestClient, capsys: pytest.CaptureFixture[str], path: str, supplied: str
) -> None:
    """A4: a client X-Request-ID is never echoed, never logged, never used (also on 500)."""
    resp = client.get(path, headers={"X-Request-ID": supplied})
    out = capsys.readouterr().out
    (rec,) = _access(_records(out))

    assert resp.headers["x-request-id"] != supplied
    assert rec["request_id"] != supplied
    _assert_uuid4(rec["request_id"])
    assert resp.headers["x-request-id"] == rec["request_id"]
    if supplied:
        assert supplied not in out
        assert supplied not in "".join(resp.headers.values())


def test_options_preflight_gets_one_access_record(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A3: 'EVERY HTTP request the app handles'. # ASSUMPTION: a CORS preflight answered by the
    CORS middleware still counts as a request the app handled.
    """
    resp = client.options(
        "/tasks",
        headers={"Origin": "http://localhost", "Access-Control-Request-Method": "GET"},
    )
    (rec,) = _access(_records(capsys.readouterr().out))
    assert rec["status"] == resp.status_code


def test_unsupported_method_gets_one_access_record_matching_status(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A3: 405 (path exists, method does not) is still exactly one record with the real status.
    # ASSUMPTION: `route` for a 405 is unspecified (matched vs "<unmatched>"), so only its type is
    checked.
    """
    resp = client.request("DELETE", "/health")
    (rec,) = _access(_records(capsys.readouterr().out))
    assert resp.status_code == 405
    assert rec["status"] == 405
    assert isinstance(rec["route"], str)


# --------------------------------------------------------------------------------------------
# A5 — things that must never be logged
# --------------------------------------------------------------------------------------------

_JWT_HEADER = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
_JWT_PAYLOAD = "eyJzdWIiOiJTRU5USU5FTF9TVUJKRUNUIiwiZmlybSI6IlNFTlRJTkVMX0ZJUk0ifQ"
_JWT_SIG = "SENTINEL_SIGNATURE_abcdefghijklmnopqrstuvwxyz0123456789"
_SENTINEL_JWT = f"{_JWT_HEADER}.{_JWT_PAYLOAD}.{_JWT_SIG}"


def test_secrets_query_body_and_raw_path_never_reach_stdout(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A5: Authorization value/JWT, request body, query string and raw path are never logged --
    across 401, 422, 404 and 500 paths (the 500 handler used to log the raw path).
    """
    bearer = {"Authorization": f"Bearer {_SENTINEL_JWT}"}
    forbidden = [
        _SENTINEL_JWT,
        _JWT_PAYLOAD,
        _JWT_SIG,
        "SENTINEL_QUERY_VALUE",
        "SENTINEL_QUERY_KEY",
        "SENTINEL_BODY_VALUE",
        "SENTINEL_PATH_VALUE",
        "SENTINEL_PATH_UNMATCHED",
        _UID1,
    ]
    responses = [
        client.get("/tasks", headers=bearer, params={"SENTINEL_QUERY_KEY": "SENTINEL_QUERY_VALUE"}),
        client.get(f"/tasks/{_UID1}", headers=bearer),
        client.post(
            "/__blind_echo",
            params={"n": "SENTINEL_QUERY_VALUE"},
            json={"count": "SENTINEL_BODY_VALUE"},
            headers=bearer,
        ),
        client.post("/tasks", json={"title": "SENTINEL_BODY_VALUE"}, headers=bearer),
        client.get("/SENTINEL_PATH_UNMATCHED", headers=bearer),
        client.get(
            "/__blind_boom/SENTINEL_PATH_VALUE",
            params={"q": "SENTINEL_QUERY_VALUE"},
            headers=bearer,
        ),
    ]
    out = capsys.readouterr().out
    recs = _records(out)

    assert len(_access(recs)) == len(responses)
    for needle in forbidden:
        assert needle not in out, f"{needle!r} leaked into the log output"
    assert any(r["level"] == "ERROR" for r in recs)  # the 500 path really did log something


# --------------------------------------------------------------------------------------------
# A6 — log injection resistance
# --------------------------------------------------------------------------------------------

_FORGED = (
    '{"ts":"2020-01-01T00:00:00Z","level":"CRITICAL","logger":"app.access","message":"request",'
    '"status":200,"FORGED_MARKER":1}'
)
_EVIL = "x\r\nX-Forged: 1\n" + _FORGED + "\u2028\u2029\x00\x1b[31m\"}{'\\"


def test_hostile_bytes_in_path_query_headers_body_method_cannot_forge_lines(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A6: every stdout line still parses as JSON; access-record count == requests sent; no
    forged record; the attacker text is not logged at all.
    """
    evil_q = quote(_EVIL, safe="")
    role = 'ow\r\nner\u2028"}{'  # role is legitimately logged when bound, so no marker in it
    attempts: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", f"/health/{evil_q}", {}),
        ("GET", f"/tasks/{evil_q}", {}),
        ("GET", f"/__blind_boom/{evil_q}", {}),
        ("GET", f"/health?q={evil_q}", {}),
        ("GET", "/health", {"params": {"q": _EVIL}}),
        ("GET", "/health", {"headers": {"X-Evil": _EVIL, "User-Agent": _EVIL, "Referer": _EVIL}}),
        ("GET", "/health", {"headers": {"Cookie": _EVIL, "X-Request-ID": _EVIL}}),
        ("GET", "/tasks", {"headers": {"Authorization": "Bearer " + _EVIL}}),
        (
            "POST",
            "/__blind_echo",
            {"content": _EVIL.encode(), "headers": {"Content-Type": "application/json"}},
        ),
        ("POST", "/tasks", {"json": {"title": _EVIL}}),
        ("GET", "/__blind_whoami", {"params": {"tenant": _EVIL, "actor": _EVIL, "role": role}}),
        ("GET\r\nX-Forged: 1", "/health", {}),
        ('G"ET{', "/health", {}),
    ]
    sent = [r for r in (_try(client, m, u, **kw) for m, u, kw in attempts) if r is not None]
    out = capsys.readouterr().out
    recs = _records(out)  # asserts every line is one valid JSON object

    assert len(sent) >= len(attempts) - 3  # the client library must have sent nearly all of them
    assert len(_access(recs)) == len(sent)
    assert "FORGED_MARKER" not in out
    assert all(r["level"] != "CRITICAL" for r in recs)
    assert len(out.splitlines()) == len(out.split("\n")) - 1  # no raw U+2028/0x85/... separators


def test_very_long_inputs_are_truncated_and_lines_stay_small(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A6: a 1 MB header/body/token or ~60 KB path/query never yields a huge log line.

    # ASSUMPTION: httpx rejects URLs > 65536 chars client-side, so the path/query are 60 KB, not
    1 MB; the 1 MB vector is carried by a header, a Bearer token and a body.
    """
    big = "Q" * 1_000_000
    attempts: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", "/health", {"headers": {"X-Big": big}}),
        ("GET", "/health", {"headers": {"X-Request-ID": big}}),
        ("GET", "/tasks", {"headers": {"Authorization": "Bearer " + big}}),
        ("GET", "/" + "Q" * 60_000, {}),
        ("GET", f"/tasks/{'Q' * 60_000}", {}),
        ("GET", "/health", {"params": {"q": "Q" * 50_000}}),
        ("POST", "/__blind_echo", {"content": big.encode(), "headers": {"Content-Type": "text/x"}}),
        ("GET", "/__blind_whoami", {"params": {"tenant": "Q" * 50_000, "role": "Q" * 50_000}}),
    ]
    sent = [r for r in (_try(client, m, u, **kw) for m, u, kw in attempts) if r is not None]
    out = capsys.readouterr().out
    recs = _records(out)

    assert len(sent) >= 6
    assert len(_access(recs)) == len(sent)
    for line in out.split("\n")[:-1]:
        assert len(line.encode("utf-8")) < 20_000
    assert "Q" * 1000 not in out  # never a full-length echo of attacker input


# --------------------------------------------------------------------------------------------
# A7 / A8 — identity binding and isolation between requests
# --------------------------------------------------------------------------------------------

_WHOAMI_VARIANTS = [
    "/__blind_whoami",
    "/__blind_whoami_async",
    "/__blind_whoami_dep",
    "/__blind_whoami_dep_async",
]


def test_bind_identity_outside_a_request_is_a_harmless_noop(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A7: no raise outside a request, and nothing bound there leaks into later requests/logs."""
    bind_identity()
    bind_identity(tenant_id=str(uuid.uuid4()), actor_id=str(uuid.uuid4()), actor_role="owner")
    bind_identity(tenant_id="garbage")
    logging.getLogger("blind.after_bind").warning("outside")
    client.get("/health")
    recs = _records(capsys.readouterr().out)

    assert len(recs) == 2
    for rec in recs:
        assert (rec["tenant_id"], rec["actor_id"], rec["actor_role"]) == (None, None, None)


@pytest.mark.parametrize("path", _WHOAMI_VARIANTS)
def test_bound_identity_is_on_every_record_of_the_request(
    client: TestClient, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    """A7: after binding (sync/async handler, sync dependency), the handler's own log line AND
    the access record carry tenant/actor/role and the request id.
    """
    tenant, actor = str(uuid.uuid4()), str(uuid.uuid4())
    resp = client.get(path, params={"tenant": tenant, "actor": actor, "role": "owner"})
    recs = _records(capsys.readouterr().out)

    assert resp.status_code == 200
    rid = resp.headers["x-request-id"]
    marker = [r for r in recs if r["message"] == "blind-marker"]
    access = _access(recs)
    assert len(marker) == 1
    assert len(access) == 1
    for rec in (*marker, *access):
        assert rec["request_id"] == rid
        assert rec["tenant_id"] == tenant
        assert rec["actor_id"] == actor
        assert rec["actor_role"] == "owner"


def test_bound_identity_survives_an_error_status(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A7+A3: a 404 raised by the handler after binding still logs the bound identity."""
    tenant, actor = str(uuid.uuid4()), str(uuid.uuid4())
    params = {"tenant": tenant, "actor": actor, "role": "employee", "fail": 404}
    resp = client.get("/__blind_whoami", params=params)
    (rec,) = _access(_records(capsys.readouterr().out))
    assert resp.status_code == 404
    assert rec["status"] == 404
    assert (rec["tenant_id"], rec["actor_id"], rec["actor_role"]) == (tenant, actor, "employee")


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-uuid",
        "",
        " ",
        "1' OR '1'='1",
        "00000000-0000-4000-8000-00000000000g",
        "00000000-0000-4000-8000-0000000000011",
        "SENTINEL_BAD_ID\n" + _FORGED,
        "Q" * 30_000,  # ADJUSTED from 100_000: httpx rejects URLs over 65_536 chars (2 params)
        "../../etc/passwd",
    ],
    # ADJUSTED after integration: without short ids pytest uses the huge value as the test id and
    # sets it in PYTEST_CURRENT_TEST, which exceeds Windows' 32,767-char env-var limit.
    ids=[
        "not-a-uuid",
        "empty",
        "space",
        "sql-quote",
        "bad-hex-char",
        "too-long-uuid",
        "forged-newline",
        "huge-30k",
        "path-traversal",
    ],
)
def test_non_uuid_identity_values_are_dropped_never_logged_raw(
    client: TestClient, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    """A7: invalid tenant_id/actor_id become null and the raw value is never written."""
    resp = client.get("/__blind_whoami", params={"tenant": bad, "actor": bad})
    out = capsys.readouterr().out
    recs = _records(out)

    assert resp.status_code == 200
    assert len(recs) == 2
    for rec in recs:
        assert rec["tenant_id"] is None
        assert rec["actor_id"] is None
    if bad.strip():
        assert bad not in out
    assert "SENTINEL_BAD_ID" not in out
    assert "FORGED_MARKER" not in out


def test_uppercase_uuid_is_accepted_or_normalised_but_never_mangled(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A7: a valid UUID in a different case is either kept or normalised; it must be the same UUID.
    # ASSUMPTION: case-normalisation is allowed; dropping a valid UUID is not.
    """
    tenant = uuid.uuid4()
    client.get("/__blind_whoami", params={"tenant": str(tenant).upper()})
    (rec,) = _access(_records(capsys.readouterr().out))
    assert rec["tenant_id"] is not None
    assert uuid.UUID(rec["tenant_id"]) == tenant


def test_partial_binding_leaves_the_other_fields_null(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A7: binding only tenant_id leaves actor_id/actor_role null."""
    tenant = str(uuid.uuid4())
    client.get("/__blind_whoami", params={"tenant": tenant})
    for rec in _records(capsys.readouterr().out):
        assert rec["tenant_id"] == tenant
        assert rec["actor_id"] is None
        assert rec["actor_role"] is None


def test_hostile_role_string_cannot_break_the_json_line(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A7+A6: actor_role is a free-form string; whatever it holds, the line stays valid JSON.
    # ASSUMPTION: the role may be logged verbatim or sanitised, but never break the line.
    """
    client.get("/__blind_whoami", params={"role": 'x\n{"level":"CRITICAL"}\r\u2028'})
    out = capsys.readouterr().out
    recs = _records(out)
    assert len(recs) == 2
    assert all(r["level"] != "CRITICAL" for r in recs)
    assert len(out.splitlines()) == 2


def test_no_identity_bleeds_into_the_next_request(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A8: request 1 binds T1; the next request on the same client, which binds nothing, has null
    tenant/actor/role in ALL its records.
    """
    t1, a1 = str(uuid.uuid4()), str(uuid.uuid4())
    for path in _WHOAMI_VARIANTS:
        client.get(path, params={"tenant": t1, "actor": a1, "role": "owner"})
        capsys.readouterr()
        r_health = client.get("/health")
        r_anon = client.get(path, params={"delay": 0})
        recs = _records(capsys.readouterr().out)
        assert len(_access(recs)) == 2
        assert {r["request_id"] for r in recs} == {
            r_health.headers["x-request-id"],
            r_anon.headers["x-request-id"],
        }
        for rec in recs:
            assert (rec["tenant_id"], rec["actor_id"], rec["actor_role"]) == (None, None, None)


def test_no_identity_bleed_under_concurrency(capsys: pytest.CaptureFixture[str]) -> None:
    """A8: 64 overlapping requests over the thread pool (sync, async, dependency-bound, and
    unauthenticated /health mixed in): every record's identity equals its own request's binding.
    """
    total = 64
    variants = ["/__blind_whoami", "/__blind_whoami_async", "/__blind_whoami_dep_async"]

    def one(i: int, c: TestClient) -> tuple[str, str | None, str | None]:
        if i % 4 == 3:
            return c.get("/health").headers["x-request-id"], None, None
        tenant, actor = str(uuid.uuid4()), str(uuid.uuid4())
        resp = c.get(
            variants[i % 3],
            params={"tenant": tenant, "actor": actor, "role": "owner", "delay": 0.15},
        )
        assert resp.status_code == 200
        return resp.headers["x-request-id"], tenant, actor

    with (
        TestClient(app, raise_server_exceptions=False) as shared,
        ThreadPoolExecutor(max_workers=48) as pool,
    ):
        results = list(pool.map(lambda i: one(i, shared), range(total)))
    recs = _records(capsys.readouterr().out)

    assert len({rid for rid, _, _ in results}) == total
    by_rid: dict[str, list[Record]] = {}
    for rec in recs:
        by_rid.setdefault(str(rec["request_id"]), []).append(rec)
    mismatches: list[tuple[str, Record]] = []
    for rid, tenant, actor in results:
        mine = by_rid[rid]
        assert len(_access(mine)) == 1
        for rec in mine:
            if (rec["tenant_id"], rec["actor_id"]) != (tenant, actor):
                mismatches.append((rid, rec))
            if tenant is not None and rec["actor_role"] != "owner":
                mismatches.append((rid, rec))
    assert mismatches == []


def test_caller_extras_cannot_override_context_fields(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A2+A7: a log call passing extra={"request_id": ..., "tenant_id": ...} does not forge the
    context, and unknown extras are not emitted.
    # ASSUMPTION: the server-side request context always wins over caller-supplied extras.
    """
    resp = client.get("/__blind_forge")
    out = capsys.readouterr().out
    (rec,) = [r for r in _records(out) if r["message"] == "forge"]

    assert rec["request_id"] == resp.headers["x-request-id"]
    assert rec["tenant_id"] is None
    assert rec["actor_id"] is None
    assert rec["actor_role"] is None
    assert "forged" not in out
    assert "hunter2-sentinel" not in out


# --------------------------------------------------------------------------------------------
# A9 — unhandled exceptions
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/__blind_boom/tag", "/__blind_boom_async/tag"])
def test_unhandled_exception_yields_problem_json_access_and_error_records(
    client: TestClient, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    """A9+A4: 500 problem+json (no exception text), request-id header, ONE access record with
    status 500, ONE ERROR record from logger `app` with the same request id, tenant and `exc`.
    """
    tenant = str(uuid.uuid4())
    resp = client.get(path, params={"tenant": tenant})
    recs = _records(capsys.readouterr().out)

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["detail"] == "An unexpected error occurred"
    assert "SECRET_EXC_TEXT" not in resp.text
    assert "SECRET_EXC_TEXT" not in "".join(resp.headers.values())
    rid = resp.headers["x-request-id"]
    _assert_uuid4(rid)

    (access,) = _access(recs)
    assert access["status"] == 500
    assert access["request_id"] == rid
    assert access["tenant_id"] == tenant
    assert access["route"] == path.rsplit("/", 1)[0] + "/{tag}"
    errors = [r for r in recs if r["level"] == "ERROR" and r["logger"] == "app"]
    assert len(errors) == 1
    assert errors[0]["request_id"] == rid
    assert errors[0]["tenant_id"] == tenant
    assert isinstance(errors[0]["exc"], str)
    assert "RuntimeError" in errors[0]["exc"]


def test_two_unhandled_exceptions_do_not_share_request_ids(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """A9+A4: each 500 has its own request id on header, access record and ERROR record."""
    rids = [client.get("/__blind_boom/a").headers["x-request-id"] for _ in range(3)]
    recs = _records(capsys.readouterr().out)
    errors = [r for r in recs if r["level"] == "ERROR" and r["logger"] == "app"]
    assert len(set(rids)) == 3
    assert [r["request_id"] for r in errors] == rids
    assert [r["request_id"] for r in _access(recs)] == rids


def test_unhandled_exception_on_a_real_route_is_logged_with_its_template(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A9+A3: same shape as tests/test_main.py's broken-session setup, against a real route."""
    app.dependency_overrides[deps.require_owner] = lambda: Profile(
        id=uuid.uuid4(),
        firm_id=uuid.uuid4(),
        role="owner",
        full_name="Owner",
        email="owner@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )
    broken = MagicMock()
    broken.exec.side_effect = RuntimeError("boom — simulated unexpected bug")
    app.dependency_overrides[deps.get_session] = lambda: broken
    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/employees")
    finally:
        app.dependency_overrides.pop(deps.require_owner, None)
        app.dependency_overrides.pop(deps.get_session, None)
    recs = _records(capsys.readouterr().out)

    assert resp.status_code == 500
    (access,) = _access(recs)
    assert (access["status"], access["route"]) == (500, "/employees")
    assert access["request_id"] == resp.headers["x-request-id"]
    errors = [r for r in recs if r["level"] == "ERROR" and r["logger"] == "app"]
    assert len(errors) == 1
    assert errors[0]["request_id"] == access["request_id"]
    assert "boom" not in resp.text


# --------------------------------------------------------------------------------------------
# A10 — logging failure must never affect the HTTP response
# --------------------------------------------------------------------------------------------


class _BrokenStdout:
    def __init__(self, exc_type: type[Exception]) -> None:
        self._exc_type = exc_type

    def write(self, _data: str) -> int:
        raise self._exc_type("stdout is broken")

    def flush(self) -> None:
        raise self._exc_type("stdout is broken")


_A10_REQUESTS: list[tuple[str, str]] = [
    ("GET", "/health"),
    ("GET", "/nope"),
    ("GET", "/tasks"),
    ("GET", "/__blind_boom/x"),
    ("GET", "/__blind_whoami?tenant=" + _UID1),
]


@pytest.mark.parametrize("exc_type", [OSError, BrokenPipeError, ValueError])
def test_stdout_failure_does_not_change_any_response(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    exc_type: type[Exception],
) -> None:
    """A10: with sys.stdout.write raising, status + body of every response (incl. 500) are
    identical to the healthy baseline, and the X-Request-ID header is still present.
    # ASSUMPTION: ValueError (write to a closed file) is treated like OSError.
    """
    baseline = [client.request(m, u) for m, u in _A10_REQUESTS]
    capsys.readouterr()

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", _BrokenStdout(exc_type))
        degraded = [client.request(m, u) for m, u in _A10_REQUESTS]

    for good, bad in zip(baseline, degraded, strict=True):
        assert bad.status_code == good.status_code
        assert bad.headers["content-type"] == good.headers["content-type"]
        assert bad.json() == good.json()
        _assert_uuid4(bad.headers["x-request-id"])
    assert degraded[-2].status_code == 500

    # ASSUMPTION: a transient stdout failure does not permanently disable logging.
    capsys.readouterr()
    client.get("/health")
    assert len(_access(_records(capsys.readouterr().out))) == 1


def test_logging_call_does_not_raise_when_stdout_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A10: application code calling logger.warning() must not get the OSError."""
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", _BrokenStdout(OSError))
        logging.getLogger("app").warning("still fine")
        logging.getLogger("blind.third").error("still fine too")


# --------------------------------------------------------------------------------------------
# A11 — end-to-end identity through the real auth chain (real Postgres, like authz regression)
# --------------------------------------------------------------------------------------------

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")
_needs_pg = pytest.mark.skipif(
    not (_MIGRATIONS_URL and _APP_URL),
    reason="needs a real Postgres — TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
)
_FIRM_SCOPED_TABLES = (
    "notifications",
    "access_denials",
    "audit_log",
    "task_reviews",
    "issues",
    "idempotency_keys",
    "tasks",
    "job_types",
    "profiles",
)


@dataclass
class _Pg:
    firm_a: uuid.UUID
    firm_b: uuid.UUID
    owner_a: uuid.UUID
    emp_a: uuid.UUID
    owner_b: uuid.UUID
    key: Any


@pytest.fixture
def pg(monkeypatch: pytest.MonkeyPatch) -> Generator[_Pg]:
    assert _MIGRATIONS_URL is not None  # guaranteed by _needs_pg
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=private.public_key()),
    )
    admin = create_engine(_MIGRATIONS_URL)
    seeded = _Pg(
        firm_a=uuid.uuid4(),
        firm_b=uuid.uuid4(),
        owner_a=uuid.uuid4(),
        emp_a=uuid.uuid4(),
        owner_b=uuid.uuid4(),
        key=private,
    )
    with admin.begin() as conn:
        for firm in (seeded.firm_a, seeded.firm_b):
            conn.execute(
                text(
                    "INSERT INTO firms (id, name, plan, status) VALUES (:i, 'x', 'free', 'active')"
                ),
                {"i": firm},
            )
        for pid, firm, role in (
            (seeded.owner_a, seeded.firm_a, "owner"),
            (seeded.emp_a, seeded.firm_a, "employee"),
            (seeded.owner_b, seeded.firm_b, "owner"),
        ):
            conn.execute(
                text(
                    "INSERT INTO profiles (id, firm_id, role, full_name, email, is_active, "
                    "must_change_password) VALUES (:p, :f, :r, 'x', :e, true, false)"
                ),
                {"p": pid, "f": firm, "r": role, "e": f"{pid}@example.com"},
            )
    yield seeded
    with admin.begin() as conn:
        for firm in (seeded.firm_a, seeded.firm_b):
            for table in _FIRM_SCOPED_TABLES:
                conn.execute(text(f"DELETE FROM {table} WHERE firm_id = :f"), {"f": firm})  # noqa: S608
            conn.execute(text("DELETE FROM firms WHERE id = :f"), {"f": firm})
    admin.dispose()


def _token(
    seeded: _Pg, sub: uuid.UUID, firm: uuid.UUID, claim_role: str, exp_in: int = 3600
) -> str:
    claims = {
        "sub": str(sub),
        "aud": "authenticated",
        "iss": security.settings.JWT_ISSUER,
        "exp": int(time.time()) + exp_in,
        "app_metadata": {"firm_id": str(firm), "role": claim_role},
    }
    return jwt.encode(claims, seeded.key, algorithm="RS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@_needs_pg
@pytest.mark.authz
def test_real_auth_binds_tenant_actor_and_db_role_not_jwt_claim(
    pg: _Pg, capsys: pytest.CaptureFixture[str]
) -> None:
    """A11: tenant == firm, actor == profile, actor_role == DB role even if the JWT claim lies."""
    cases = [
        (pg.emp_a, pg.firm_a, "owner", "employee"),  # employee whose token claims owner
        (pg.owner_a, pg.firm_a, "owner", "owner"),
        (pg.owner_b, pg.firm_b, "owner", "owner"),
    ]
    with TestClient(app) as c:
        for actor, firm, claim, db_role in cases:
            resp = c.get("/tasks", headers=_auth(_token(pg, actor, firm, claim)))
            assert resp.status_code == 200
            recs = _records(capsys.readouterr().out)
            (rec,) = [r for r in _access(recs) if r["route"] == "/tasks"]
            assert rec["status"] == 200
            assert rec["request_id"] == resp.headers["x-request-id"]
            assert rec["tenant_id"] == str(firm)
            assert rec["actor_id"] == str(actor)
            assert rec["actor_role"] == db_role
        # the next, unauthenticated request carries nothing from the previous ones
        c.get("/health")
        (rec,) = _access(_records(capsys.readouterr().out))
        assert (rec["tenant_id"], rec["actor_id"], rec["actor_role"]) == (None, None, None)


@_needs_pg
@pytest.mark.authz
def test_real_auth_failures_log_401_without_any_identity(
    pg: _Pg, capsys: pytest.CaptureFixture[str]
) -> None:
    """A11: tampered / expired / garbage tokens -> 401 and an access record with actor_id null
    (# ASSUMPTION: tenant_id is null too, since nothing was verified).
    """
    good = _token(pg, pg.owner_a, pg.firm_a, "owner")
    swap = "AAAA" if not good.endswith("AAAA") else "BBBB"
    bad_tokens = [
        good[:-4] + swap,
        _token(pg, pg.owner_a, pg.firm_a, "owner", exp_in=-3600),
        "not.a.jwt",
    ]
    with TestClient(app) as c:
        for token in bad_tokens:
            resp = c.get("/tasks", headers=_auth(token))
            assert resp.status_code == 401
            out = capsys.readouterr().out
            (rec,) = _access(_records(out))
            assert rec["status"] == 401
            assert rec["actor_id"] is None
            assert rec["tenant_id"] is None
            assert token not in out


# --------------------------------------------------------------------------------------------
# B — readiness endpoint
# --------------------------------------------------------------------------------------------

_CACHE_WAIT = 5.5  # spec: results cached "at most ~5 seconds"; wait this long for a cold window
_FORBIDDEN_IN_READY = [
    "SENTINEL_DSN",
    "SENTINEL_HOST",
    "SENTINEL_PW",
    "SENTINEL_QUERY_ERR",
    "sqlalchemy",
    "psycopg",
    "sqlite",
    "postgres",
    "traceback",
    "exception",
    "pool",
]


class _Clock:
    last_ready_call: float | None = None


def _cold_window() -> None:
    """Sleep until any cached /ready result from an earlier test must have expired."""
    if _Clock.last_ready_call is None:
        time.sleep(_CACHE_WAIT)
    else:
        remaining = _CACHE_WAIT - (time.monotonic() - _Clock.last_ready_call)
        if remaining > 0:
            time.sleep(remaining)


def _ready(client: TestClient, **kwargs: Any) -> httpx.Response:
    _Clock.last_ready_call = time.monotonic()
    try:
        return client.get("/ready", **kwargs)
    finally:
        _Clock.last_ready_call = time.monotonic()


def _sqlite_engine(tmp_path: Path, **kwargs: Any) -> Engine:
    return create_engine(
        f"sqlite:///{tmp_path}/ready.db",
        poolclass=QueuePool,
        connect_args={"check_same_thread": False},
        **kwargs,
    )


class _Counter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.connects = 0
        self.queries = 0

    def bump_connect(self) -> None:
        with self._lock:
            self.connects += 1

    def bump_query(self, statement: str) -> None:
        if "select 1" in statement.lower():
            with self._lock:
                self.queries += 1


def _instrument(
    engine: Engine,
    *,
    connect: Callable[[], None] | None = None,
    query: Callable[[], None] | None = None,
) -> _Counter:
    """Count (and optionally sabotage) connects / `SELECT 1` executions on a real SA engine."""
    counter = _Counter()

    @event.listens_for(engine, "do_connect")
    def _on_connect(  # pyright: ignore[reportUnusedFunction]
        dialect: object, conn_rec: object, cargs: object, cparams: object
    ) -> None:
        counter.bump_connect()
        if connect is not None:
            connect()

    @event.listens_for(engine, "before_cursor_execute")
    def _on_execute(  # pyright: ignore[reportUnusedFunction]
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        counter.bump_query(statement)
        if query is not None and "select 1" in statement.lower():
            query()

    return counter


def _assert_ready_body_is_opaque(resp: httpx.Response) -> None:
    haystack = (resp.text + repr(dict(resp.headers))).lower()
    for needle in _FORBIDDEN_IN_READY:
        assert needle.lower() not in haystack, f"/ready disclosed {needle!r}"


def test_health_is_unchanged_and_never_touches_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B1: /health is always 200 {"status": "ok"} even when the DB engine is unusable."""

    def _boom() -> None:
        raise RuntimeError("SENTINEL_DSN db must not be touched")

    engine = _sqlite_engine(tmp_path)
    counter = _instrument(engine, connect=_boom, query=_boom)
    monkeypatch.setattr("app.core.db.engine", engine)
    for _ in range(5):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    assert (counter.connects, counter.queries) == (0, 0)
    engine.dispose()


def test_ready_ok_is_opaque_cached_and_request_identified(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B2+B3+B4+B5: healthy DB -> 200 exactly {"status": "ok"} with no auth; 20 rapid calls cause
    at most one query; the response carries X-Request-ID and one access record per call.
    """
    engine = _sqlite_engine(tmp_path)
    counter = _instrument(engine)
    monkeypatch.setattr("app.core.db.engine", engine)
    _cold_window()

    first = _ready(client)
    assert first.status_code == 200
    assert first.json() == {"status": "ok"}
    _assert_ready_body_is_opaque(first)
    # no credentials needed, and a junk Authorization header must not matter (or leak)
    junk = _ready(client, headers={"Authorization": "Bearer junk"})
    assert junk.status_code == 200
    rest = [_ready(client) for _ in range(20)]

    assert all(r.status_code == 200 and r.json() == {"status": "ok"} for r in rest)
    assert counter.queries <= 1
    recs = _records(capsys.readouterr().out)
    access = _access(recs)
    assert len(access) == 22
    assert all(r["route"] == "/ready" and r["status"] == 200 for r in access)
    _assert_uuid4(first.headers["x-request-id"])
    assert access[0]["request_id"] == first.headers["x-request-id"]
    assert len({r["request_id"] for r in access}) == 22
    engine.dispose()


def _raise_connect() -> None:
    # Assembled from pieces so the fake credential isn't a literal DSN (Sonar S6698 false positive).
    raise RuntimeError("SENTINEL_DSN postgresql://user:" + "SENTINEL_PW" + "@SENTINEL_HOST:5432/db")


def _raise_query() -> None:
    raise KeyError("SENTINEL_QUERY_ERR psycopg SENTINEL_HOST")


def test_ready_fails_closed_when_connect_raises_then_recovers(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B2+B3+B4+B5: connect error -> 503 exactly {"status": "unavailable"}, no disclosure,
    request id + access record with status 503; rapid retries make at most one attempt; once the
    cache window passes and the DB is healthy again the endpoint returns 200 (no latched failure).
    """
    bad = _sqlite_engine(tmp_path)
    counter = _instrument(bad, connect=_raise_connect)
    monkeypatch.setattr("app.core.db.engine", bad)
    _cold_window()

    resp = _ready(client)
    burst = [_ready(client) for _ in range(10)]
    for r in (resp, *burst):
        assert r.status_code == 503
        assert r.json() == {"status": "unavailable"}
        _assert_ready_body_is_opaque(r)
    assert counter.connects <= 1
    access = _access(_records(capsys.readouterr().out))
    assert [a["status"] for a in access] == [503] * 11
    assert access[0]["request_id"] == resp.headers["x-request-id"]

    good = _sqlite_engine(tmp_path)
    monkeypatch.setattr("app.core.db.engine", good)
    _cold_window()
    recovered = _ready(client)
    assert recovered.status_code == 200
    assert recovered.json() == {"status": "ok"}
    bad.dispose()
    good.dispose()


def test_ready_fails_closed_on_a_non_sqlalchemy_query_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B2+B3: ANY exception type from the query (here KeyError, not a DBAPI error) -> 503.
    # ASSUMPTION: the probe goes through SQLAlchemy's cursor path, so before_cursor_execute fires.
    """
    engine = _sqlite_engine(tmp_path)
    _instrument(engine, query=_raise_query)
    monkeypatch.setattr("app.core.db.engine", engine)
    _cold_window()

    resp = _ready(client)
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
    _assert_ready_body_is_opaque(resp)
    engine.dispose()


def test_ready_fails_closed_when_the_engine_itself_is_broken(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B2: the engine lookup/use is inside the fail-closed boundary (503, never 200 or 500)."""
    monkeypatch.setattr("app.core.db.engine", None)
    _cold_window()
    resp = _ready(client)
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}


def test_ready_reports_unavailable_when_the_pool_is_fully_saturated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B2: every pooled connection checked out -> 503 promptly (not a 30 s pool wait)."""
    engine = _sqlite_engine(tmp_path, pool_size=1, max_overflow=0, pool_timeout=5)
    monkeypatch.setattr("app.core.db.engine", engine)
    held = engine.connect()
    _cold_window()
    try:
        started = time.monotonic()
        resp = _ready(client)
        elapsed = time.monotonic() - started
    finally:
        held.close()
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
    _assert_ready_body_is_opaque(resp)
    assert elapsed < 4.0
    _Clock.last_ready_call = time.monotonic()
    engine.dispose()


@pytest.mark.parametrize("where", ["connect", "query"])
def test_ready_is_bounded_when_the_database_hangs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str
) -> None:
    """B4: with a DB that blocks forever (on connect / on the query), 20 simultaneous /ready
    calls all return 503 within a few seconds, and at most ONE blocked attempt is ever started.
    A blocked handler must not stall the event loop either (a shared loop serves all 20).
    """
    release = threading.Event()

    def _hang() -> None:
        release.wait(timeout=60)

    engine = _sqlite_engine(tmp_path)
    counter = _instrument(
        engine,
        connect=_hang if where == "connect" else None,
        query=_hang if where == "query" else None,
    )
    monkeypatch.setattr("app.core.db.engine", engine)
    _cold_window()
    barrier = threading.Barrier(20)

    def call(shared: TestClient) -> tuple[int, dict[str, str], float]:
        barrier.wait(timeout=10)
        began = time.monotonic()
        resp = shared.get("/ready")
        return resp.status_code, resp.json(), time.monotonic() - began

    # `release` is set before the client (event loop) shuts down, else a blocked probe thread
    # would make the shutdown wait for the full 60 s hang timeout.
    with TestClient(app, raise_server_exceptions=False) as shared:
        try:
            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(pool.map(lambda _i: call(shared), range(20)))
            attempts = counter.connects if where == "connect" else counter.queries
        finally:
            release.set()
    _Clock.last_ready_call = time.monotonic()
    engine.dispose()
    assert attempts <= 1

    assert [r[0] for r in results] == [503] * 20
    assert all(r[1] == {"status": "unavailable"} for r in results)
    assert max(r[2] for r in results) < 5.0  # spec: ~3 s bound for the hung attempt


# --------------------------------------------------------------------------------------------
# C — pool saturation monitor
# --------------------------------------------------------------------------------------------


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def pool_engine(tmp_path: Path) -> Generator[Engine]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/p.db", poolclass=QueuePool, pool_size=2, max_overflow=1
    )
    yield engine
    engine.dispose()


@pytest.fixture
def pool_records() -> Generator[list[logging.LogRecord]]:
    logger = logging.getLogger("app.pool")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def _checkout_n(engine: Engine, n: int) -> list[Any]:
    return [engine.connect() for _ in range(n)]


def test_pool_monitor_is_silent_below_the_threshold(
    pool_engine: Engine, pool_records: list[logging.LogRecord]
) -> None:
    """C1: capacity 3, default ratio 0.7 -> 1 and 2 checked out (0.33, 0.67) emit nothing, and
    repeated open/close cycles never emit.
    """
    install_pool_monitor(pool_engine, capacity=3)
    for _ in range(25):
        with pool_engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
    held = _checkout_n(pool_engine, 2)
    for conn in held:
        conn.close()
    assert pool_records == []


def test_pool_monitor_warns_once_at_the_threshold_with_documented_fields(
    pool_engine: Engine, pool_records: list[logging.LogRecord]
) -> None:
    """C1: the third checkout (3/3 >= 0.7) emits exactly one WARNING from app.pool."""
    install_pool_monitor(pool_engine, capacity=3)
    held = _checkout_n(pool_engine, 3)
    try:
        assert len(pool_records) == 1
        rec = pool_records[0]
        assert rec.levelno == logging.WARNING
        assert rec.name == "app.pool"
        extras = rec.__dict__
        assert extras["event"] == "pool_high_utilization"
        assert extras["checked_out"] == 3
        assert isinstance(extras["checked_out"], int)
        assert extras["capacity"] == 3
        utilization = extras["utilization"]
        assert isinstance(utilization, float)
        assert 0.0 <= utilization <= 1.0
        assert utilization == pytest.approx(1.0)
    finally:
        for conn in held:
            conn.close()


@pytest.mark.parametrize(
    ("warn_ratio", "silent_until", "first_warn_at"),
    [(1.0, 2, 3), (2 / 3, 1, 2), (0.5, 1, 2), (0.0, 0, 1)],
)
def test_pool_monitor_threshold_boundary_is_inclusive(
    pool_engine: Engine,
    pool_records: list[logging.LogRecord],
    warn_ratio: float,
    silent_until: int,
    first_warn_at: int,
) -> None:
    """C1: warns when checkedout/capacity >= warn_ratio (equality counts)."""
    install_pool_monitor(pool_engine, capacity=3, warn_ratio=warn_ratio, min_interval_seconds=0)
    held: list[Any] = []
    try:
        for i in range(1, first_warn_at + 1):
            before = len(pool_records)
            held.append(pool_engine.connect())
            if i <= silent_until:
                assert len(pool_records) == before, f"unexpected warning at {i} checked out"
            else:
                assert len(pool_records) == before + 1
        assert pool_records[-1].__dict__["checked_out"] == first_warn_at
    finally:
        for conn in held:
            conn.close()


def test_pool_monitor_rate_limits_inside_the_interval(
    pool_engine: Engine, pool_records: list[logging.LogRecord]
) -> None:
    """C1: with a 30 s interval only ONE record is emitted however many checkouts qualify."""
    install_pool_monitor(pool_engine, capacity=3, warn_ratio=0.5, min_interval_seconds=30.0)
    held = _checkout_n(pool_engine, 3)  # 2nd and 3rd both qualify
    held.pop().close()
    held.append(pool_engine.connect())  # qualifies again
    for conn in held:
        conn.close()
    assert len(pool_records) == 1


def test_pool_monitor_without_rate_limit_emits_per_qualifying_checkout(
    pool_engine: Engine, pool_records: list[logging.LogRecord]
) -> None:
    """C1: min_interval_seconds=0 disables rate limiting."""
    install_pool_monitor(pool_engine, capacity=3, warn_ratio=0.5, min_interval_seconds=0)
    held = _checkout_n(pool_engine, 3)
    for conn in held:
        conn.close()
    assert len(pool_records) == 2


def test_pool_monitor_emits_again_after_the_interval(
    pool_engine: Engine, pool_records: list[logging.LogRecord]
) -> None:
    """C1: the rate limit is a time window, not a one-shot latch."""
    install_pool_monitor(pool_engine, capacity=3, warn_ratio=0.5, min_interval_seconds=0.3)
    held = _checkout_n(pool_engine, 2)
    assert len(pool_records) == 1
    time.sleep(0.6)
    held.append(pool_engine.connect())
    for conn in held:
        conn.close()
    assert len(pool_records) == 2


def test_pool_monitor_rate_limit_is_per_engine(
    tmp_path: Path, pool_records: list[logging.LogRecord]
) -> None:
    """C1: 'per engine' -- a warning on engine A does not consume engine B's budget."""
    engines = [
        create_engine(
            f"sqlite:///{tmp_path}/{n}.db", poolclass=QueuePool, pool_size=2, max_overflow=1
        )
        for n in ("a", "b")
    ]
    held: list[Any] = []
    try:
        for eng in engines:
            install_pool_monitor(eng, capacity=3, warn_ratio=0.5, min_interval_seconds=30.0)
        for eng in engines:
            held.extend(_checkout_n(eng, 3))
        assert len(pool_records) == 2
    finally:
        for conn in held:
            conn.close()
        for eng in engines:
            eng.dispose()


def test_pool_warning_reaches_stdout_as_json_with_event(
    pool_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    """C1+A2: through the real logging config the record is one WARNING line from app.pool with
    `event` == "pool_high_utilization".
    """
    install_pool_monitor(pool_engine, capacity=3, min_interval_seconds=0)
    held = _checkout_n(pool_engine, 3)
    for conn in held:
        conn.close()
    recs = [r for r in _records(capsys.readouterr().out) if r["logger"] == "app.pool"]
    assert len(recs) == 1
    assert recs[0]["level"] == "WARNING"
    assert recs[0]["event"] == "pool_high_utilization"


def test_a_failing_monitor_never_breaks_the_checkout(pool_engine: Engine) -> None:
    """C1: if the listener itself raises (forced here via a raising log filter on app.pool), the
    application's own checkout and query still succeed.
    """

    def _explode(_record: logging.LogRecord) -> bool:
        raise RuntimeError("monitor boom")

    logger = logging.getLogger("app.pool")
    install_pool_monitor(pool_engine, capacity=3, warn_ratio=0.0, min_interval_seconds=0)
    logger.addFilter(_explode)
    try:
        for _ in range(3):
            with pool_engine.connect() as conn:
                assert conn.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        logger.removeFilter(_explode)


def test_zero_capacity_never_breaks_the_checkout(pool_engine: Engine) -> None:
    """C1: capacity=0 (division by zero) is rejected at install with ValueError or tolerated at
    checkout -- never an application-visible failure on a working pool.
    # ASSUMPTION: ValueError at install time is an acceptable way to reject it.
    """
    try:
        install_pool_monitor(pool_engine, capacity=0)
    except ValueError:
        return
    with pool_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
