"""Batch 2 attack tests for `scrub_event`'s new fields (query_string, breadcrumb.data,
logentry.params, extra) — derived from a real sentry-sdk 2.68.1 runtime probe (session scratchpad
`sentry_probe_b2.py`), not from the shape of `scrub_event`'s own code. Every payload here is proven
to fail on the pre-fix code first (rule 10.1) before being trusted as a real regression check.

See docs/SECURITY_AUDIT_CHECKLIST.md Current Audit block (BATCH 2 slice 1) for the checklist this
test file evidences: req_01 (query_string), req_02 (breadcrumb.data), req_03 (logentry.params),
req_04 (before_send_transaction), req_05 (extra).
"""

from __future__ import annotations

from typing import Any

from app.core.sentry_config import scrub_event

_SECRET = "TOPSECRETVALUE123"


def _db_echo(secret: str) -> str:
    return (
        f'duplicate key value violates unique constraint "k"\n'
        f"DETAIL:  Key (v)=({secret}) already exists."
    )


def _error_event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "exception": {"values": [{"value": "boom"}]},
        "breadcrumbs": {"values": []},
        "request": {"method": "GET", "url": "http://x/probe"},
        "extra": {},
    }
    base.update(overrides)
    return base


def _transaction_event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "transaction",
        "request": {"method": "GET", "url": "http://x/probe"},
        "spans": [],
        "extra": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# req_01: event["request"]["query_string"]
# ---------------------------------------------------------------------------


def test_query_string_is_stripped_from_error_event_request() -> None:
    event = _error_event(
        request={"method": "GET", "url": "http://x/probe", "query_string": f"token={_SECRET}"}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["request"]["query_string"]


def test_query_string_is_stripped_from_transaction_event_request() -> None:
    """req_04: before_send does not see transaction events -- this proves scrub_event ALSO works
    when called as before_send_transaction (the exact call `sentry_init_kwargs` now wires)."""
    event = _transaction_event(
        request={"method": "GET", "url": "http://x/probe", "query_string": f"tok={_SECRET}"}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["request"]["query_string"]


def test_query_string_embedded_inline_in_the_url_is_also_stripped() -> None:
    """A query string can be inline in `url` without a separate `query_string` key (confirmed as a
    real SDK-populated shape for some integrations) -- the url's own query/fragment must be cut."""
    event = _error_event(request={"method": "GET", "url": f"http://x/probe?token={_SECRET}#frag"})
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["request"]["url"]
    assert out["request"]["url"] == "http://x"


def test_a_query_string_on_a_bare_host_with_no_path_is_also_stripped() -> None:
    """Mutation-testing finding (2026-09-22): every prior url-stripping test had a non-empty PATH,
    so a mutant that only checked path+fragment (dropping the query check) still survived -- a bare
    host with just a query string (no path segment at all) is a real, distinct shape."""
    event = _error_event(request={"method": "GET", "url": f"http://x?token={_SECRET}"})
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["request"]["url"]
    assert out["request"]["url"] == "http://x"


def test_a_fragment_on_a_bare_host_with_no_path_or_query_is_also_stripped() -> None:
    """Mutation-testing finding (2026-09-22): every prior test with a non-empty fragment also had a
    non-empty path, so a mutant that inverted the fragment check alone still survived -- a bare host
    with ONLY a fragment (no path, no query) is a real, distinct shape."""
    event = _error_event(request={"method": "GET", "url": f"http://x#{_SECRET}"})
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["request"]["url"]
    assert out["request"]["url"] == "http://x"


def test_a_secret_path_segment_with_no_query_string_is_also_stripped() -> None:
    """Blind-test finding (2026-09-22), confirmed live: a parameterized route's event["transaction"]
    is safely templated (e.g. "/reset/{token}"), but request["url"] independently carries the
    literal matched path -- no query string involved, so a query-only strip misses it."""
    event = _error_event(request={"method": "GET", "url": f"http://x/reset/{_SECRET}"})
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["request"]["url"]


def test_a_clean_scheme_and_host_only_url_is_left_exactly_alone() -> None:
    """Non-vacuity: the strip must not mangle a URL that already has nothing to strip."""
    event = _error_event(request={"method": "GET", "url": "http://x"})
    out = scrub_event(event, {})
    assert out is not None
    assert out["request"]["url"] == "http://x"


def test_the_safe_route_template_in_transaction_field_is_never_touched() -> None:
    """Non-vacuity: event["transaction"] (the safe, already-templated route name) must survive
    untouched -- the debugging value the url-path strip relies on staying available."""
    event = _error_event(
        transaction="/reset/{token}", request={"method": "GET", "url": f"http://x/reset/{_SECRET}"}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["transaction"] == "/reset/{token}"


def test_missing_request_field_does_not_crash() -> None:
    event = {"exception": {"values": []}}
    assert scrub_event(event, {}) is not None


def test_fragment_field_is_also_stripped_from_request() -> None:
    """Coverage gap: only query_string/url were exercised, never fragment. Asserts the replacement
    is a real string, not just "!= the original" -- a mutation-testing pass (2026-09-22) found
    `!=` alone lets a `None` replacement survive undetected."""
    event = _error_event(
        request={"method": "GET", "url": "http://x/probe", "fragment": "section-name"}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert isinstance(out["request"]["fragment"], str)
    assert out["request"]["fragment"] != "section-name"


def test_request_with_no_url_key_does_not_crash() -> None:
    """Coverage gap: every prior test's request dict had a url key."""
    event = _error_event(request={"method": "GET", "query_string": f"tok={_SECRET}"})
    out = scrub_event(event, {})
    assert out is not None
    assert "url" not in out["request"]
    assert _SECRET not in out["request"]["query_string"]


# ---------------------------------------------------------------------------
# req_02: breadcrumbs[].data
# ---------------------------------------------------------------------------


def test_breadcrumb_data_query_string_is_stripped() -> None:
    event = _error_event(
        breadcrumbs={
            "values": [
                {
                    "category": "http",
                    "type": "http",
                    "data": {"url": "https://x/y", "query_string": f"tok={_SECRET}"},
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in str(out["breadcrumbs"]["values"][0]["data"])


def test_breadcrumb_data_url_with_inline_query_is_stripped() -> None:
    event = _error_event(
        breadcrumbs={
            "values": [
                {"category": "http", "type": "http", "data": {"url": f"https://x/y?tok={_SECRET}"}}
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["breadcrumbs"]["values"][0]["data"]["url"]


def test_breadcrumb_message_still_redacted_alongside_data() -> None:
    """Non-regression: the existing message scrub (batch 1) still runs, not replaced."""
    event = _error_event(
        breadcrumbs={
            "values": [
                {
                    "category": "custom",
                    "message": _db_echo(_SECRET),
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["breadcrumbs"]["values"][0]["message"]
    assert "DETAIL:  [redacted]" in out["breadcrumbs"]["values"][0]["message"]


def test_breadcrumb_with_no_data_field_does_not_crash() -> None:
    event = _error_event(breadcrumbs={"values": [{"category": "custom", "message": "hi"}]})
    assert scrub_event(event, {}) is not None


def test_breadcrumbs_as_a_bare_list_does_not_crash() -> None:
    """Blind-test finding (2026-09-22): event["breadcrumbs"] as a bare list (not {"values": [...]})
    raised AttributeError inside scrub_event itself -- a crash inside before_send/
    before_send_transaction is worse than a leak (ASVS 16.5.3, no fail-open on internal errors)."""
    event = _error_event(breadcrumbs=[{"category": "http", "message": "hi", "data": {}}])
    out = scrub_event(event, {})
    assert out is not None


def test_breadcrumbs_non_dict_entry_in_the_list_does_not_crash() -> None:
    event = _error_event(breadcrumbs={"values": ["not-a-dict", {"category": "x", "message": "hi"}]})
    out = scrub_event(event, {})
    assert out is not None


def test_breadcrumbs_after_a_non_dict_entry_are_still_scrubbed() -> None:
    """Mutation-testing finding (2026-09-22): the non-dict entry must be SKIPPED (continue), not
    treated as a reason to stop processing the rest of the list (break) -- the prior test's dict
    entry after the bad one had nothing sensitive, so it couldn't tell the two apart."""
    event = _error_event(
        breadcrumbs={"values": ["not-a-dict", {"category": "custom", "message": _db_echo(_SECRET)}]}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["breadcrumbs"]["values"][1]["message"]
    assert "DETAIL:  [redacted]" in out["breadcrumbs"]["values"][1]["message"]


def test_breadcrumbs_dict_with_no_values_key_does_not_crash() -> None:
    """Coverage gap: every prior dict-shaped breadcrumbs test had a values key."""
    event = _error_event(breadcrumbs={})
    out = scrub_event(event, {})
    assert out is not None


# ---------------------------------------------------------------------------
# req_03: logentry.params
# ---------------------------------------------------------------------------


def test_logentry_params_with_a_db_echoed_value_are_redacted() -> None:
    event = _error_event(
        logentry={
            "message": "Auth failed for %s: %s",
            "formatted": f"Auth failed for user-1: {_SECRET}",
            "params": [
                "user-1",
                _db_echo(_SECRET),
            ],
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in str(out["logentry"]["params"])
    assert out["logentry"]["params"][0] == "user-1"  # non-vacuity: a safe param is untouched


def test_logentry_message_and_formatted_with_a_db_echoed_value_are_redacted() -> None:
    """Mutation-testing finding (2026-09-22): no test previously put a redactable value directly in
    logentry.message/formatted -- only in params -- so a mutant that stopped touching either key
    (or looked it up under the wrong dict, or on the wrong container) survived undetected.
    `redact_db_values` only recognises Postgres-shaped text (batch-1 finding), so a plain bare
    secret is not enough here -- must use the same real Postgres-echo shape as the params test."""
    event = _error_event(
        logentry={
            "message": "Query failed: %s",
            "formatted": f"Query failed: {_db_echo(_SECRET)}",
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["logentry"]["formatted"]
    assert "DETAIL:  [redacted]" in out["logentry"]["formatted"]
    assert out["logentry"]["message"] == "Query failed: %s"  # non-vacuity: no DB shape here


def test_logentry_message_alone_with_a_db_echoed_value_is_redacted() -> None:
    """Mutation-testing finding (2026-09-22): the test above only ever put a redactable value in
    `formatted` -- a mutant that broke the "message" key specifically (wrong literal, wrong dict)
    still survived because `formatted`'s own lookup was untouched by that mutation."""
    event = _error_event(logentry={"message": _db_echo(_SECRET), "formatted": "unrelated"})
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["logentry"]["message"]
    assert "DETAIL:  [redacted]" in out["logentry"]["message"]


def test_top_level_event_message_with_a_db_echoed_value_is_redacted() -> None:
    """Mutation-testing finding (2026-09-22): event["message"] (distinct from logentry.message) had
    no test that put a redactable value there at all."""
    event = _error_event(message=_db_echo(_SECRET))
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["message"]
    assert "DETAIL:  [redacted]" in out["message"]


def test_logentry_params_non_string_element_is_left_alone() -> None:
    event = _error_event(
        logentry={"message": "x %s", "formatted": "x 1", "params": [1, None, True]}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["logentry"]["params"] == [1, None, True]


def test_missing_logentry_does_not_crash() -> None:
    event = _error_event()
    assert scrub_event(event, {}) is not None


def test_logentry_with_no_params_key_does_not_crash() -> None:
    """Coverage gap: every prior logentry test included a params key."""
    event = _error_event(logentry={"message": "x", "formatted": "x"})
    out = scrub_event(event, {})
    assert out is not None
    assert "params" not in out["logentry"]


# ---------------------------------------------------------------------------
# req_05: event["extra"]
# ---------------------------------------------------------------------------


def test_extra_is_fail_closed_not_selectively_redacted() -> None:
    """Blind-test finding (2026-09-22): extra has no fixed shape or depth (arbitrary keys to
    arbitrary values), so a shallow per-value redact misses a value nested in a dict-of-list, a
    list-of-strings value, and a plain secret under an innocuous-sounding key. The whole field is
    stripped instead, same reasoning as query_string."""
    event = _error_event(
        extra={
            "note": _db_echo(_SECRET),
            "nested": {"inner": {"tokens": [_SECRET]}},
            "a_list": ["a=1", f"secret={_SECRET}"],
            "innocuous_key_name": _SECRET,
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    # Exact shape, not just "secret absent" -- a mutation-testing pass (2026-09-22) found
    # `_SECRET not in str(...)` also passes trivially if the field were replaced with None, and the
    # exact key name ("_stripped") was never checked either.
    assert isinstance(out["extra"], dict)
    assert "_stripped" in out["extra"]
    assert _SECRET not in str(out["extra"])


def test_extra_empty_dict_is_left_as_empty() -> None:
    """Non-vacuity: nothing to strip shouldn't be turned into noise."""
    event = _error_event(extra={})
    out = scrub_event(event, {})
    assert out is not None
    assert out["extra"] == {}


def test_extra_missing_entirely_does_not_crash() -> None:
    event = {"exception": {"values": []}}
    assert scrub_event(event, {}) is not None


# ---------------------------------------------------------------------------
# req_04: before_send_transaction wiring
# ---------------------------------------------------------------------------


def test_scrub_event_is_wired_as_both_before_send_and_before_send_transaction() -> None:
    from app.core.sentry_config import sentry_init_kwargs

    kwargs = sentry_init_kwargs(
        dsn="https://public@example.invalid/1", release=None, environment=None
    )
    assert kwargs["before_send"] is scrub_event
    assert kwargs["before_send_transaction"] is scrub_event


def test_sentry_init_kwargs_returns_every_expected_option_with_its_correct_value() -> None:
    """Mutation-testing finding (2026-09-22): the wiring test above only ever checked before_send/
    before_send_transaction -- every other returned key (dsn, release, environment, the two PII-
    adjacent options, before_send_transaction's own key name) had zero assertions, so a mutant
    swapping any of them to a wrong literal or a wrong dict key survived undetected."""
    from app.core.sentry_config import sentry_init_kwargs

    kwargs = sentry_init_kwargs(
        dsn="https://public@example.invalid/1", release="v1.2.3", environment="staging"
    )
    assert kwargs["dsn"] == "https://public@example.invalid/1"
    assert kwargs["release"] == "v1.2.3"
    assert kwargs["environment"] == "staging"
    assert kwargs["traces_sample_rate"] == 1.0
    assert kwargs["include_local_variables"] is False
    assert kwargs["max_request_body_size"] == "never"
    assert set(kwargs.keys()) == {
        "dsn",
        "release",
        "environment",
        "traces_sample_rate",
        "include_local_variables",
        "max_request_body_size",
        "before_send",
        "before_send_transaction",
    }


# ---------------------------------------------------------------------------
# Slice 2: chained Supabase Auth exceptions (employees.py's `raise ... from exc`)
# ---------------------------------------------------------------------------
# Payload shapes confirmed live against this app's REAL sentry_init_kwargs (session scratchpad
# `sentry_probe_authchain.py`): a chained `AuthApiError` put its own entry, with a real `module`
# field, into event["exception"]["values"] -- not derived from scrub_event's own code shape.

_AUTH_EMAIL_MESSAGE = 'Email address "victim-reveal-me@example.com" is invalid'


def test_auth_error_chain_message_is_stripped() -> None:
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "AuthApiError",
                    "module": "supabase_auth.errors",
                    "value": _AUTH_EMAIL_MESSAGE,
                },
                {
                    "type": "HTTPException",
                    "module": "fastapi.exceptions",
                    "value": "safe app message",
                },
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    # Exact replacement, not just "secret absent" -- a mutation-testing pass (2026-09-22) found
    # `not in str(...)` also passes trivially if the field were replaced with None.
    assert isinstance(out["exception"]["values"][0]["value"], str)
    assert "victim-reveal-me@example.com" not in str(out["exception"])


def test_auth_error_chain_type_field_is_left_visible_for_debugging() -> None:
    """Non-vacuity: only `value` is replaced -- `type`/`module` stay so the class is still visible
    in Sentry, matching the level of detail describe_auth_error already gives the log line."""
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "AuthApiError",
                    "module": "supabase_auth.errors",
                    "value": _AUTH_EMAIL_MESSAGE,
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["exception"]["values"][0]["type"] == "AuthApiError"
    assert out["exception"]["values"][0]["module"] == "supabase_auth.errors"


def test_the_outer_non_auth_exception_in_the_chain_is_left_alone() -> None:
    """Non-vacuity: the app's own safe top-level message (HTTPException) is never touched, only the
    chained AuthApiError cause."""
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "AuthApiError",
                    "module": "supabase_auth.errors",
                    "value": _AUTH_EMAIL_MESSAGE,
                },
                {
                    "type": "HTTPException",
                    "module": "fastapi.exceptions",
                    "value": "safe app message",
                },
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["exception"]["values"][1]["value"] == "safe app message"


def test_a_different_auth_error_subclass_is_also_stripped_by_module_not_class_name() -> None:
    """Matched by module, not a hardcoded class-name list -- covers every AuthError subclass."""
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "AuthWeakPasswordError",
                    "module": "supabase_auth.errors",
                    "value": f"Password too similar to {_SECRET}",
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert isinstance(out["exception"]["values"][0]["value"], str)
    assert _SECRET not in str(out["exception"])


def test_ordinary_exceptions_are_still_redacted_by_shape_not_fail_closed() -> None:
    """Non-regression: an unrelated exception (any module) still goes through redact_db_values, not
    the auth fail-closed path -- this slice must not weaken the original DB-echo redaction."""
    event = _error_event(
        exception={"values": [{"type": "RuntimeError", "value": _db_echo(_SECRET)}]}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in out["exception"]["values"][0]["value"]
    assert "DETAIL:  [redacted]" in out["exception"]["values"][0]["value"]


def test_a_plain_safe_exception_message_is_left_exactly_alone() -> None:
    """Non-vacuity: this slice must not turn into a blanket strip of every exception message."""
    event = _error_event(
        exception={"values": [{"type": "ZeroDivisionError", "value": "division by zero"}]}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["exception"]["values"][0]["value"] == "division by zero"


def test_exception_field_as_a_non_dict_does_not_crash() -> None:
    event = _error_event(exception="boom")
    out = scrub_event(event, {})
    assert out is not None


def test_exception_dict_with_no_values_key_does_not_crash() -> None:
    event = _error_event(exception={})
    out = scrub_event(event, {})
    assert out is not None


def test_exception_values_containing_a_non_dict_entry_does_not_crash() -> None:
    event = _error_event(exception={"values": ["not-a-dict", {"type": "X", "value": "boom"}]})
    out = scrub_event(event, {})
    assert out is not None


def test_auth_error_entry_with_no_value_key_does_not_crash() -> None:
    """Coverage gap: every prior auth-error entry had a value key."""
    event = _error_event(
        exception={"values": [{"type": "AuthApiError", "module": "supabase_auth.errors"}]}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert "value" not in out["exception"]["values"][0]


# ---------------------------------------------------------------------------
# BATCH 3: FastAPI ResponseValidationError/RequestValidationError/
# WebSocketRequestValidationError embed the raw offending value(s) in their own __str__ via
# Pydantic error dicts. Shape confirmed live against this app's REAL sentry_init_kwargs (session
# scratchpad `probe_batch3_response_validation.py`): a route whose return value fails its
# response_model produces exactly this event["exception"]["values"] entry, `module` and all -- not
# derived from scrub_event's own code shape.
# ---------------------------------------------------------------------------

_VALIDATION_ERROR_MESSAGE = (
    "1 validation error:\n  {'type': 'int_parsing', 'loc': ('response', 'ssn'), "
    "'msg': 'Input should be a valid integer, unable to parse string as an integer', "
    f"'input': '{_SECRET}'}}"
)


def test_response_validation_error_message_is_stripped() -> None:
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "ResponseValidationError",
                    "module": "fastapi.exceptions",
                    "value": _VALIDATION_ERROR_MESSAGE,
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert isinstance(out["exception"]["values"][0]["value"], str)
    assert _SECRET not in str(out["exception"])


def test_response_validation_error_type_field_is_left_visible_for_debugging() -> None:
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "ResponseValidationError",
                    "module": "fastapi.exceptions",
                    "value": _VALIDATION_ERROR_MESSAGE,
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["exception"]["values"][0]["type"] == "ResponseValidationError"
    assert out["exception"]["values"][0]["module"] == "fastapi.exceptions"


def test_request_validation_error_is_also_stripped() -> None:
    """Defense in depth: checked live and found NOT to reach Sentry today (FastAPI resolves it
    inside dependency injection, before the ASGI boundary Sentry hooks), but matched anyway in
    case FastAPI's internals change -- see sentry_config.py's module docstring."""
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "RequestValidationError",
                    "module": "fastapi.exceptions",
                    "value": f"1 validation error:\n  {{'input': '{_SECRET}'}}",
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in str(out["exception"])


def test_websocket_request_validation_error_is_also_stripped() -> None:
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "WebSocketRequestValidationError",
                    "module": "fastapi.exceptions",
                    "value": f"1 validation error:\n  {{'input': '{_SECRET}'}}",
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in str(out["exception"])


def test_http_exception_in_the_same_module_is_not_stripped() -> None:
    """The crux of this slice's design decision: fastapi.exceptions ALSO defines HTTPException,
    whose `detail` is developer-written, safe text this app relies on for real error messages
    (`raise HTTPException(404, "Task not found")`). Matching by module alone (like the AuthError
    fix) would wrongly strip it too -- this must match by module AND a specific type set."""
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "HTTPException",
                    "module": "fastapi.exceptions",
                    "value": "Task not found",
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["exception"]["values"][0]["value"] == "Task not found"


def test_a_different_fastapi_exceptions_class_not_in_the_validation_set_is_left_alone() -> None:
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "FastAPIError",
                    "module": "fastapi.exceptions",
                    "value": "some internal FastAPI error, not a validation error",
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert out["exception"]["values"][0]["value"] == (
        "some internal FastAPI error, not a validation error"
    )


def test_the_shared_validation_exception_base_class_is_also_stripped() -> None:
    """Blind-test finding (2026-09-22): the first version only matched the three named subclasses,
    missing the shared `ValidationException` base itself -- grepped, no current fastapi version
    raises it directly, but the log-formatter side already covers it via isinstance(), and this
    file's own docstring already named a future subclass as this match's stated boundary. Costs
    nothing to close."""
    event = _error_event(
        exception={
            "values": [
                {
                    "type": "ValidationException",
                    "module": "fastapi.exceptions",
                    "value": f"raw errors: {_SECRET}",
                }
            ]
        }
    )
    out = scrub_event(event, {})
    assert out is not None
    assert _SECRET not in str(out["exception"])


def test_validation_error_entry_with_no_value_key_does_not_crash() -> None:
    event = _error_event(
        exception={"values": [{"type": "ResponseValidationError", "module": "fastapi.exceptions"}]}
    )
    out = scrub_event(event, {})
    assert out is not None
    assert "value" not in out["exception"]["values"][0]
