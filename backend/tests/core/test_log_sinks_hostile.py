"""Log sinks that carry the text of a NON-database exception (batch 1, root causes A and E).

The redactor only knows database-error shapes. The sweep of every place exception text can leave
the process found two more sinks that log the raw text of a Supabase Auth error, and Supabase can
echo the email address being created into that message (client PII, ASVS 16.2.5, TCASVS 3.2.3).
Rather than teach the redactor a second vendor's message shapes, those sinks no longer log the text
at all: they log class, HTTP status and Supabase's own error code.

  * describe_auth_error is attacked with hostile messages, codes and statuses.
  * A structural test (root cause E: a convention with no enforcement) fails if ANY logger call in
    app/ passes a bare exception object, `str()`/`repr()`/`ascii()`/`format()` of one, its `.args`,
    or an f-string or `%` expression containing one, so a new sink cannot quietly reintroduce the
    leak. The detector is itself tested against snippets that must and must not be flagged.
  * Round 2: the stdlib prints the raw record and its arguments to stderr when a log call is
    malformed (`Handler.handleError`); the app's handler must not.
"""

from __future__ import annotations

import ast
import logging
import uuid
from pathlib import Path

import pytest
from supabase_auth.errors import AuthApiError, AuthError, AuthUnknownError, AuthWeakPasswordError

from app.core.logging_setup import (
    JsonFormatter,
    _LiveStdoutHandler,  # pyright: ignore[reportPrivateUsage]
)
from app.core.supabase_admin import describe_auth_error

_HOSTILE_MESSAGES = {
    "email": 'Email address "{m}@client.test" is invalid',
    "newline": "line1\n{m}\nline3",
    "blank_line": "para1\n\n{m}",
    "crlf": "a\r\n{m}\r\n",
    "quotes": "a\"b'c{m}",
    "u2028": "a\u2028{m}",
    "structure": "DETAIL:  {m}\n[SQL: {m}]\nTraceback (most recent call last):",
    "long": "{m}" + "x" * 100_000,
    "format_lookalike": "%s %d {m} {{0}}",
}
_HOSTILE_CODES = [
    None,
    "",
    "x\nDETAIL:  {m}",
    "{m}",
    123,
    ["{m}"],
    "email_exists\n{m}",
    "EMAIL_EXISTS",
]
_HOSTILE_STATUSES = [None, "400 {m}", -1, 10**30, 4.5, "{m}"]


def _marker() -> str:
    return "MRK" + uuid.uuid4().hex[:12]


@pytest.mark.parametrize("mname", sorted(_HOSTILE_MESSAGES))
@pytest.mark.parametrize("cindex", range(len(_HOSTILE_CODES)))
def test_a_hostile_supabase_message_or_code_never_reaches_the_log_line(
    mname: str, cindex: int
) -> None:
    m = _marker()
    message = _HOSTILE_MESSAGES[mname].replace("{m}", m)
    raw_code = _HOSTILE_CODES[cindex]
    code = raw_code.replace("{m}", m) if isinstance(raw_code, str) else raw_code
    for exc in (
        AuthApiError(message, 422, code),  # type: ignore[arg-type]
        AuthError(message, code),  # type: ignore[arg-type]
        AuthUnknownError(message, ValueError(message)),
        AuthWeakPasswordError(message, 422, [message]),
    ):
        described = describe_auth_error(exc)
        assert m not in described, (
            f"{type(exc).__name__}: client text reached the log line: {described[:200]!r}"
        )
        assert "\n" not in described
        assert "\r" not in described
        assert "\u2028" not in described
        assert described.startswith(type(exc).__name__), (
            "the class name is what makes the failure debuggable"
        )


@pytest.mark.parametrize("status", _HOSTILE_STATUSES)
def test_a_hostile_status_is_not_echoed(status: object) -> None:
    m = _marker()
    shown = status.replace("{m}", m) if isinstance(status, str) else status
    exc = AuthApiError("boom", 500, None)
    exc.status = shown  # type: ignore[assignment]
    described = describe_auth_error(exc)
    assert m not in described
    if not isinstance(shown, int):
        assert "status=None" in described


def test_a_known_supabase_code_and_status_are_kept_because_they_make_the_failure_debuggable() -> (
    None
):
    described = describe_auth_error(AuthApiError("Email address is invalid", 422, "email_exists"))
    assert described == "AuthApiError status=422 code=email_exists"


def test_an_unknown_code_is_reported_as_other() -> None:
    described = describe_auth_error(AuthApiError("x", 500, "brand_new_code"))  # type: ignore[arg-type]
    assert described == "AuthApiError status=500 code=other"


# --------------------------------------------------- root cause E: enforce it structurally
_LOGGER_NAMES = {"logger", "_logger", "_pool_logger", "log"}
_ROOT = Path(__file__).resolve().parents[2]
# (file, variable) pairs that are allowed to reach a log line, each with the evidence that it is
# safe. Adding to this list needs a written reason; that friction is the point.
_ALLOWED = {
    ("app/api/deps.py", "exc"): (
        "PyJWT's PyJWTError / PyJWKClientError messages are static strings that never "
        "interpolate the token; verified against the installed jwt/api_jwt.py, "
        "jwt/api_jws.py and jwt/jwks_client.py (see deps.py)."
    ),
}


def _bound_exception_names(tree: ast.AST) -> set[str]:
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name}


_TEXT_MAKERS = {"str", "repr", "ascii", "format"}


def _leaks_exception(arg: ast.expr, names: set[str]) -> str | None:
    """The bound exception name whose text or arguments this expression puts into a log line."""
    if isinstance(arg, ast.Name) and arg.id in names:
        return arg.id
    if (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Name)
        and arg.func.id in _TEXT_MAKERS
        and arg.args
    ):
        return _leaks_exception(arg.args[0], names)
    if isinstance(arg, ast.Attribute) and arg.attr == "args":  # exc.args carries the raw message
        return _leaks_exception(arg.value, names)
    if isinstance(arg, ast.Subscript):  # exc.args[0]
        return _leaks_exception(arg.value, names)
    parts: list[ast.expr] = []
    if isinstance(arg, ast.JoinedStr):
        parts = [p.value for p in arg.values if isinstance(p, ast.FormattedValue)]
    elif isinstance(arg, ast.BinOp):  # "text %s" % exc, "text" + str(exc)
        parts = [arg.left, arg.right]
    elif isinstance(arg, ast.Tuple):
        parts = list(arg.elts)
    for part in parts:
        found = _leaks_exception(part, names)
        if found:
            return found
    return None


def _logger_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id in _LOGGER_NAMES
        and n.func.attr in {"debug", "info", "warning", "error", "critical", "exception"}
    ]


def test_no_logger_call_in_the_app_passes_a_bare_exception() -> None:
    offenders = []
    for path in sorted((_ROOT / "app").rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _bound_exception_names(tree)
        for call in _logger_calls(tree):
            for arg in call.args:
                leaked = _leaks_exception(arg, names)
                if leaked and (rel, leaked) not in _ALLOWED:
                    method = call.func.attr if isinstance(call.func, ast.Attribute) else "?"
                    offenders.append(f"{rel}:{call.lineno}: logger.{method}(... {leaked} ...)")
    assert not offenders, (
        "an exception object (or an f-string of one) is passed to a log call, so its text (which "
        "may echo client data) leaves the process. Log a class/code description instead (see "
        "describe_auth_error), or add a written justification to _ALLOWED:\n" + "\n".join(offenders)
    )


def test_the_allowlist_is_not_stale() -> None:
    """An allowlist entry whose call site is gone would silently allow a future regression there."""
    for rel, name in _ALLOWED:
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        names = _bound_exception_names(tree)
        used = any(
            _leaks_exception(arg, names) == name
            for call in _logger_calls(tree)
            for arg in call.args
        )
        assert used, (
            f"{rel}: '{name}' is allowlisted but no logger call passes it any more; remove it"
        )


# ---------------------------------- the detector itself is attacked (it must not be vacuous)
_HANDLER = "try:\n    work()\nexcept Exception as exc:\n    {call}\n"


def _flagged(call: str) -> list[str]:
    tree = ast.parse(_HANDLER.format(call=call))
    names = _bound_exception_names(tree)
    return [
        found
        for c in _logger_calls(tree)
        for arg in c.args
        if (found := _leaks_exception(arg, names))
    ]


@pytest.mark.parametrize(
    "call",
    [
        'logger.error("x %s", exc)',
        'logger.error("x %r", exc)',
        'logger.error("x %s", str(exc))',
        'logger.error("x %s", repr(exc))',
        'logger.error("x %s", ascii(exc))',
        'logger.error("x %s", format(exc))',
        'logger.error("x %s", exc.args)',
        'logger.error("x %s", exc.args[0])',
        'logger.error(f"x {exc}")',
        'logger.error(f"x {exc!r}")',
        'logger.error("x %s" % exc)',
        'logger.error("x %s" % (exc,))',
        'logger.error("x " + str(exc))',
        'logger.warning("x %s", (exc,))',
    ],
)
def test_the_detector_flags_every_way_to_put_exception_text_in_a_log_call(call: str) -> None:
    assert _flagged(call) == ["exc"], f"not flagged: {call}"


@pytest.mark.parametrize(
    "call",
    [
        'logger.error("x %s", type(exc).__name__)',
        'logger.error("x %s", describe_auth_error(exc))',
        'logger.exception("x")',
        'logger.error("x %s", exc.status_code)',
        'logger.error("x %s", other)',
    ],
)
def test_the_detector_does_not_flag_safe_log_calls(call: str) -> None:
    assert _flagged(call) == [], f"wrongly flagged: {call}"


# ------------------------------- round 2: a malformed log call must not print its record to stderr
def test_a_logging_error_never_prints_the_record_or_its_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stdlib's handleError prints `Message:` and `Arguments:` (the raw values) to stderr."""
    # The app's real handler class, driven directly: pytest's own log-capture handler re-raises a
    # formatting error before this one would run, which would hide the behaviour under test.
    handler = _LiveStdoutHandler()
    handler.setFormatter(JsonFormatter())
    secret = "MRK" + uuid.uuid4().hex[:12]
    record = logging.LogRecord(
        "app", logging.INFO, __file__, 1, "two placeholders %s %s", (secret,), None
    )  # a programmer's mismatch: one argument for two placeholders
    handler.handle(record)
    out, err = capsys.readouterr()
    assert "could not be formatted" in err, (
        "the failure should still be visible, without the values"
    )
    assert secret not in out + err, f"the raw argument was printed: {(out + err)[:200]!r}"
