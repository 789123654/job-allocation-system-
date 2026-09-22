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
    """Coverage gap: only query_string/url were exercised, never fragment."""
    event = _error_event(
        request={"method": "GET", "url": "http://x/probe", "fragment": "section-name"}
    )
    out = scrub_event(event, {})
    assert out is not None
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
