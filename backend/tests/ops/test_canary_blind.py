"""Blind tests for the tenant-isolation canary (SPEC section D): `ops.canary.run_canary` /
`ops.canary.main`, exercised only through fake APIs built on `httpx.MockTransport`.

The fake API is the oracle: it recognises each canary probe by (method, path, bearer token) and
answers according to the SPEC D2 table, optionally sabotaged per check id. Nothing here touches the
network (a socket-level guard enforces it) or reads real config.
"""

import copy
import json
import logging
import socket
import uuid
from collections.abc import Callable
from itertools import product
from pathlib import Path
from typing import Any

import httpx
import pytest

# `ops` is a new package: `# isort: skip` keeps this file lint-stable whether or not it exists yet.
from ops.canary import CanaryReport, main, run_canary  # isort: skip

Config = dict[str, Any]
Override = Callable[[str, httpx.Request], httpx.Response | None]

_TAMPER = "AAAAAAAA"
_BASE_URL = "http://canary.test"
_FIELDS = (
    "owner_token",
    "employee_token",
    "task_id",
    "other_employee_task_id",
    "job_type_id",
    "notification_id",
)
_EXPECTED_STATUS = {
    "cross_tenant_task_read": 404,
    "cross_tenant_task_read_employee": 404,
    "cross_tenant_task_list_leak": 200,
    "cross_tenant_task_deadline_patch": 404,
    "cross_tenant_job_type_patch": 404,
    "cross_tenant_notification_patch": 404,
    "same_tenant_other_employee_task": 404,
    "employee_create_task_forbidden": 403,
    "employee_job_type_patch_forbidden": 403,
    "tampered_token_rejected": 401,
}


@pytest.fixture(autouse=True)
def _no_network(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hermetic: any real socket connection attempt fails the test."""

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted in a hermetic test")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --------------------------------------------------------------------------------------------
# Config + fake API
# --------------------------------------------------------------------------------------------


def _config(labels: tuple[str, ...] = ("alpha", "beta")) -> Config:
    firms: dict[str, dict[str, str]] = {}
    for n, label in enumerate(labels, start=1):
        firms[label] = {
            "owner_token": f"SECRETTOKEN-{label}-owner-0123456789Zq",
            "employee_token": f"SECRETTOKEN-{label}-employee-9876543210Zq",
            "task_id": str(uuid.UUID(int=n * 100 + 1)),
            "other_employee_task_id": str(uuid.UUID(int=n * 100 + 2)),
            "job_type_id": str(uuid.UUID(int=n * 100 + 3)),
            "notification_id": str(uuid.UUID(int=n * 100 + 4)),
        }
    return {"firms": firms}


def _all_tokens(cfg: Config) -> list[str]:
    return [f[k] for f in cfg["firms"].values() for k in ("owner_token", "employee_token")]


def _check_ids(labels: tuple[str, ...] = ("alpha", "beta")) -> list[str]:
    ids: list[str] = []
    for x, y in product(labels, labels):
        if x != y:
            ids += [
                f"{kind}:{x}->{y}"
                for kind in (
                    "cross_tenant_task_read",
                    "cross_tenant_task_read_employee",
                    "cross_tenant_task_list_leak",
                    "cross_tenant_task_deadline_patch",
                    "cross_tenant_job_type_patch",
                    "cross_tenant_notification_patch",
                )
            ]
    for x in labels:
        ids += [
            f"{kind}:{x}"
            for kind in (
                "same_tenant_other_employee_task",
                "employee_create_task_forbidden",
                "employee_job_type_patch_forbidden",
                "tampered_token_rejected",
            )
        ]
    return ids


def _kind(cid: str) -> str:
    return cid.split(":")[0]


def _expected_status(cid: str) -> int:
    return _EXPECTED_STATUS[_kind(cid)]


def _probe_table(cfg: Config) -> dict[tuple[str, str, str], list[str]]:
    """(method, path, bearer token) -> check ids that this request can belong to (SPEC D2)."""
    table: dict[tuple[str, str, str], list[str]] = {}

    def add(method: str, path: str, token: str, cid: str) -> None:
        table.setdefault((method, path, token), []).append(cid)

    firms: dict[str, dict[str, str]] = cfg["firms"]
    for x, fx in firms.items():
        for y, fy in firms.items():
            if x == y:
                continue
            t = f"{x}->{y}"
            add("GET", f"/tasks/{fy['task_id']}", fx["owner_token"], f"cross_tenant_task_read:{t}")
            add(
                "GET",
                f"/tasks/{fy['task_id']}",
                fx["employee_token"],
                f"cross_tenant_task_read_employee:{t}",
            )
            add("GET", "/tasks", fx["owner_token"], f"cross_tenant_task_list_leak:{t}")
            add(
                "PATCH",
                f"/tasks/{fy['task_id']}/deadline",
                fx["owner_token"],
                f"cross_tenant_task_deadline_patch:{t}",
            )
            add(
                "PATCH",
                f"/job-types/{fy['job_type_id']}",
                fx["owner_token"],
                f"cross_tenant_job_type_patch:{t}",
            )
            add(
                "PATCH",
                f"/notifications/{fy['notification_id']}/read",
                fx["owner_token"],
                f"cross_tenant_notification_patch:{t}",
            )
        emp = fx["employee_token"]
        add(
            "GET",
            f"/tasks/{fx['other_employee_task_id']}",
            emp,
            f"same_tenant_other_employee_task:{x}",
        )
        add("POST", "/tasks", emp, f"employee_create_task_forbidden:{x}")
        add(
            "PATCH",
            f"/job-types/{fx['job_type_id']}",
            emp,
            f"employee_job_type_patch_forbidden:{x}",
        )
        add("GET", "/notifications", emp[:-8] + _TAMPER, f"tampered_token_rejected:{x}")
    return table


def _bearer(request: httpx.Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[len("Bearer ") :] if auth.startswith("Bearer ") else ""


def _resp(status: int, body: object = None, **kwargs: Any) -> httpx.Response:
    if body is None:
        return httpx.Response(status, **kwargs)
    return httpx.Response(status, json=body, **kwargs)


class _Fake:
    """Callable MockTransport handler: correct by default, sabotageable per check id."""

    def __init__(
        self,
        cfg: Config,
        override: Override | None = None,
        *,
        echo: bool = False,
        plain_bodies: bool = False,
    ) -> None:
        self.cfg = cfg
        self.table = _probe_table(cfg)
        self.override = override
        self.echo = echo
        self.plain_bodies = plain_bodies
        self.requests: list[httpx.Request] = []
        self.cids: list[str | None] = []

    def _default(self, cid: str) -> httpx.Response:
        if _kind(cid) == "cross_tenant_task_list_leak":
            own = self.cfg["firms"][cid.split(":")[1].split("->")[0]]
            return _resp(200, [{"id": own["task_id"]}, {"id": own["other_employee_task_id"]}])
        status = _expected_status(cid)
        if self.plain_bodies:
            return httpx.Response(status, text="<html>no json here</html>")
        return _resp(status, {"detail": "denied"})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        ids = self.table.get((request.method, request.url.path, _bearer(request)))
        if ids is None:
            self.cids.append(None)
            return _resp(500, {"detail": "unexpected canary request"})
        cid = ids[0]
        self.cids.append(cid)
        response = self.override(cid, request) if self.override else None
        if response is None:
            response = self._default(cid)
        if self.echo:  # a hostile API that reflects the caller's credential back at us
            auth = request.headers.get("authorization", "")
            response.headers["x-echo-authorization"] = auth
            response.headers["set-cookie"] = f"session={_bearer(request)}"
        return response


def _run(fake: _Fake, cfg: Config | None = None) -> CanaryReport:
    with httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(fake)) as client:
        return run_canary(client, cfg if cfg is not None else fake.cfg)


def _violation_ids(report: CanaryReport) -> set[str]:
    return {v.check for v in report.violations}


def _foreign_task_id(cfg: Config, cid: str) -> str:
    victim = cid.split(":")[1].split("->")[1]
    return str(cfg["firms"][victim]["task_id"])


def _leak_response(cfg: Config, cid: str) -> httpx.Response:
    """A response that is a genuine isolation failure for the given check."""
    kind = _kind(cid)
    if kind == "cross_tenant_task_list_leak":
        return _resp(200, [{"id": "mine"}, {"id": _foreign_task_id(cfg, cid)}])
    if kind == "employee_create_task_forbidden":
        return _resp(201, {"id": "created-by-employee"})
    if kind == "tampered_token_rejected":
        return _resp(200, [])
    return _resp(200, {"id": "foreign-object"})


def _only(cid: str, make: Callable[[], httpx.Response]) -> Override:
    return lambda got, _request: make() if got == cid else None


def _texts(report: CanaryReport) -> list[str]:
    return [
        repr(report),
        str(report),
        repr(report.violations),
        *(repr(v) for v in report.violations),
        *(str(v) for v in report.violations),
        *report.errors,
    ]


# --------------------------------------------------------------------------------------------
# D7 (correct API) + D2 coverage
# --------------------------------------------------------------------------------------------


def test_correct_api_passes_all_20_checks_and_covers_every_probe() -> None:
    """D7+D2+D3+D5: a correct API -> ok True, 20/20 checks, no violations/errors; the canary
    sent exactly the SPEC's probes (each identified by method + path + token) and nothing else.
    """
    fake = _Fake(_config())
    report = _run(fake)

    assert report.ok is True
    assert report.checks_run == 20
    assert report.expected_checks == 20
    assert report.violations == []
    assert report.errors == []
    assert None not in fake.cids, "canary sent a request outside the SPEC's probe table"
    assert set(fake.cids) == set(_check_ids())
    assert len(set(_check_ids())) == 20
    for request in fake.requests:
        assert (request.url.scheme, request.url.host) == ("http", "canary.test")
        assert request.headers["authorization"].startswith("Bearer ")


def test_three_firms_run_every_ordered_pair() -> None:
    """D2: total checks = 6*N*(N-1) + 4*N (48 for N=3); every ordered pair probed."""
    labels = ("alpha", "beta", "gamma")
    fake = _Fake(_config(labels))
    report = _run(fake)

    assert report.expected_checks == 6 * 3 * 2 + 4 * 3 == 48
    assert report.checks_run == 48
    assert report.ok is True
    assert None not in fake.cids
    observed = set(fake.cids)
    # ASSUMPTION: for N>2 the identical GET /tasks probe of firm X is shared by X->Y and X->Z in
    # the fake's table, so only the first id is attributable; every other id must still appear.
    unattributable = {c for c in _check_ids(labels) if _kind(c) == "cross_tenant_task_list_leak"}
    assert set(_check_ids(labels)) - unattributable <= observed
    assert {"cross_tenant_task_read:gamma->alpha", "cross_tenant_task_read:beta->gamma"} <= observed


def test_probe_payloads_and_headers_match_the_spec() -> None:
    """D2: bodies for the PATCH probes, and POST /tasks carries a UUID Idempotency-Key + title."""
    fake = _Fake(_config())
    _run(fake)
    seen: dict[str, list[httpx.Request]] = {}
    for cid, request in zip(fake.cids, fake.requests, strict=True):
        assert cid is not None
        seen.setdefault(_kind(cid), []).append(request)

    for request in seen["cross_tenant_task_deadline_patch"]:
        assert json.loads(request.content) == {"deadline": "2030-01-01T00:00:00Z"}
    for kind in ("cross_tenant_job_type_patch", "employee_job_type_patch_forbidden"):
        for request in seen[kind]:
            assert json.loads(request.content) == {"is_active": True}
    for request in seen["employee_create_task_forbidden"]:
        assert json.loads(request.content) == {"title": "canary-probe"}
        uuid.UUID(request.headers["idempotency-key"])
    cfg = _config()
    for request in seen["tampered_token_rejected"]:
        token = _bearer(request)
        assert token.endswith(_TAMPER)
        assert token[:-8] in {t[:-8] for t in _all_tokens(cfg)}
        assert token not in _all_tokens(cfg)


def test_canary_never_sends_cookies_or_mutates_the_shared_client() -> None:
    """D5: responses that set cookies / reflect credentials must not bleed into later probes as
    another identity, and the caller's client is left exactly as it was.
    # ASSUMPTION: any Cookie header (or client-level default auth) counts as an undocumented
    auth form, i.e. a request that is not authenticated purely by its own Bearer header.
    """
    fake = _Fake(_config(), echo=True)
    with httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(fake)) as client:
        before = dict(client.headers)
        run_canary(client, fake.cfg)
        assert dict(client.headers) == before
        assert "authorization" not in client.headers
    assert all("cookie" not in r.headers for r in fake.requests)


# --------------------------------------------------------------------------------------------
# D1 — config validation fails closed, before any request
# --------------------------------------------------------------------------------------------


def _bad_configs() -> list[tuple[str, Any]]:
    cases: list[tuple[str, Any]] = [
        ("empty", {}),
        ("no_firms", {"firms": {}}),
        ("firms_none", {"firms": None}),
        ("firms_list", {"firms": [_config()["firms"]["alpha"], _config()["firms"]["beta"]]}),
        ("one_firm", {"firms": {"alpha": _config()["firms"]["alpha"]}}),
        ("firm_not_dict", {"firms": {"alpha": _config()["firms"]["alpha"], "beta": "oops"}}),
        ("firm_none", {"firms": {"alpha": _config()["firms"]["alpha"], "beta": None}}),
    ]
    for key, bad in product(_FIELDS, (None, 123, "", ["x"], True)):
        cfg = _config()
        cfg["firms"]["beta"][key] = bad
        cases.append((f"beta_{key}_{bad!r}", cfg))
    for key in _FIELDS:
        cfg = _config()
        del cfg["firms"]["alpha"][key]
        cases.append((f"alpha_missing_{key}", cfg))
    three = _config(("alpha", "beta", "gamma"))  # good, good, bad: never a partial run
    del three["firms"]["gamma"]["notification_id"]
    cases.append(("third_firm_missing_key", three))
    return cases


@pytest.mark.parametrize(("name", "cfg"), _bad_configs(), ids=[c[0] for c in _bad_configs()])
def test_invalid_config_raises_value_error_before_any_request(name: str, cfg: Any) -> None:
    """D1: <2 firms / missing key / non-string / empty value -> ValueError, zero requests, and the
    message never carries a token (D4).
    """
    fake = _Fake(_config())
    with (
        httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(fake)) as client,
        pytest.raises(ValueError) as excinfo,
    ):
        run_canary(client, cfg)

    assert fake.requests == [], f"{name}: requests were sent before validation failed"
    for token in _all_tokens(_config(("alpha", "beta", "gamma"))):
        assert token not in str(excinfo.value)


# --------------------------------------------------------------------------------------------
# D2/D3/D7 — every single check must be able to fail, and only that check
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("cid", _check_ids())
def test_each_check_flags_its_own_leak_and_nothing_else(cid: str) -> None:
    """D2+D3+D7: sabotaging exactly one probe with a real isolation failure yields ok False and a
    violation naming exactly that check id (so no check is vacuous, swapped or unasserted).
    """
    cfg = _config()
    fake = _Fake(cfg, _only(cid, lambda: _leak_response(cfg, cid)))
    report = _run(fake)

    assert report.ok is False
    assert _violation_ids(report) == {cid}
    assert report.checks_run == 20  # the run continued past the violation
    assert report.expected_checks == 20
    assert report.errors == []
    (violation,) = report.violations
    assert isinstance(violation.expected, str)
    assert isinstance(violation.actual, str)


_WRONG_STATUSES = (200, 201, 204, 302, 401, 403, 404, 405, 422, 500, 503)
_STATUS_CASES = [
    (cid, status)
    for cid in _check_ids()
    for status in _WRONG_STATUSES
    if status != _expected_status(cid)
]


@pytest.mark.parametrize(("cid", "status"), _STATUS_CASES)
def test_deny_checks_pass_only_on_the_exact_expected_status(cid: str, status: int) -> None:
    """D2: 'Deny-checks pass only on the EXACT expected status' -- any other status, including 200,
    201, 403-for-404 and 500, is a violation naming that check.
    """
    fake = _Fake(_config(), _only(cid, lambda: _resp(status)))
    report = _run(fake)

    assert report.ok is False
    assert _violation_ids(report) == {cid}
    (violation,) = report.violations
    # ASSUMPTION: `actual` states the observed status code.
    assert str(status) in violation.actual
    # ASSUMPTION: `expected` states the expected status code too.
    assert str(_expected_status(cid)) in violation.expected


# --------------------------------------------------------------------------------------------
# D7 — named leaky fakes
# --------------------------------------------------------------------------------------------


def _by_kind(kinds: set[str], make: Callable[[str], httpx.Response]) -> Override:
    return lambda cid, _request: make(cid) if _kind(cid) in kinds else None


def test_leaky_api_returning_foreign_tasks_on_cross_tenant_reads_is_detected() -> None:
    """D7(a): 200 + the foreign task for cross-tenant reads (owner and employee)."""
    cfg = _config()
    fake = _Fake(
        cfg,
        _by_kind(
            {"cross_tenant_task_read", "cross_tenant_task_read_employee"},
            lambda cid: _resp(200, {"id": _foreign_task_id(cfg, cid)}),
        ),
    )
    report = _run(fake)
    assert report.ok is False
    assert _violation_ids(report) == {
        "cross_tenant_task_read:alpha->beta",
        "cross_tenant_task_read:beta->alpha",
        "cross_tenant_task_read_employee:alpha->beta",
        "cross_tenant_task_read_employee:beta->alpha",
    }


def test_leaky_api_with_foreign_task_hidden_inside_the_list_is_detected() -> None:
    """D7(b): the foreign id is one element (the last of many) of an otherwise fine 200 list."""
    cfg = _config()
    fake = _Fake(
        cfg,
        _by_kind(
            {"cross_tenant_task_list_leak"},
            lambda cid: _resp(
                200, [{"id": f"own-{i}"} for i in range(10)] + [{"id": _foreign_task_id(cfg, cid)}]
            ),
        ),
    )
    report = _run(fake)
    assert report.ok is False
    assert _violation_ids(report) == {
        "cross_tenant_task_list_leak:alpha->beta",
        "cross_tenant_task_list_leak:beta->alpha",
    }


def test_leaky_api_allowing_employee_task_creation_is_detected() -> None:
    """D7(c): employee POST /tasks answered 201."""
    fake = _Fake(
        _config(),
        _by_kind({"employee_create_task_forbidden"}, lambda _c: _resp(201, {"id": "t"})),
    )
    report = _run(fake)
    assert report.ok is False
    assert _violation_ids(report) == {
        "employee_create_task_forbidden:alpha",
        "employee_create_task_forbidden:beta",
    }


def test_leaky_api_accepting_a_tampered_token_is_detected() -> None:
    """D7(d): tampered token answered 200."""
    fake = _Fake(_config(), _by_kind({"tampered_token_rejected"}, lambda _c: _resp(200, [])))
    report = _run(fake)
    assert report.ok is False
    assert _violation_ids(report) == {
        "tampered_token_rejected:alpha",
        "tampered_token_rejected:beta",
    }


def test_api_that_errors_on_a_single_probe_is_a_violation_not_a_pass() -> None:
    """D7(e): correct denials everywhere except one probe that returns 500."""
    cid = "cross_tenant_notification_patch:alpha->beta"
    report = _run(_Fake(_config(), _only(cid, lambda: _resp(500, {"detail": "boom"}))))
    assert report.ok is False
    assert _violation_ids(report) == {cid}
    assert "500" in report.violations[0].actual


def test_api_answering_404_to_everything_fails_exactly_the_non_404_checks() -> None:
    """D7(e)+D2: a blanket 404 is right for the 404-checks but wrong for the 200 list check and
    the 403/401 checks (deny checks are exact-status).
    """
    fake = _Fake(_config(), lambda _cid, _request: _resp(404, {"detail": "nope"}))
    report = _run(fake)
    expected = {
        c
        for c in _check_ids()
        if _kind(c)
        in {
            "cross_tenant_task_list_leak",
            "employee_create_task_forbidden",
            "employee_job_type_patch_forbidden",
            "tampered_token_rejected",
        }
    }
    assert report.ok is False
    assert _violation_ids(report) == expected


def test_list_probe_answered_with_a_dict_body_is_a_violation() -> None:
    """D7(f)+D2.3: a 200 whose JSON body is a dict (even one embedding the foreign id) is not a
    list, so it is a violation.
    """
    cfg = _config()
    fake = _Fake(
        cfg,
        _by_kind(
            {"cross_tenant_task_list_leak"},
            lambda cid: _resp(200, {"items": [{"id": _foreign_task_id(cfg, cid)}]}),
        ),
    )
    report = _run(fake)
    assert report.ok is False
    assert _violation_ids(report) == {
        "cross_tenant_task_list_leak:alpha->beta",
        "cross_tenant_task_list_leak:beta->alpha",
    }


def test_deny_checks_do_not_depend_on_the_response_body_format() -> None:
    """D2: only the status matters for deny checks -- HTML/empty error bodies must still pass."""
    report = _run(_Fake(_config(), plain_bodies=True))
    assert report.ok is True
    assert report.checks_run == 20


def test_list_probe_with_unparseable_or_odd_bodies_fails_closed_without_crashing() -> None:
    """D2.3: a 200 that is not JSON is a non-list body -> violation (or an error), never a crash
    and never a pass. # ASSUMPTION: recording it in `errors` instead of `violations` is also fine.
    """
    cid = "cross_tenant_task_list_leak:alpha->beta"
    report = _run(_Fake(_config(), _only(cid, lambda: httpx.Response(200, text="<html>x</html>"))))
    assert report.ok is False
    assert cid in _violation_ids(report) or report.errors

    odd = [None, 5, "x", {"id": None}, {"no_id": 1}, [1, 2]]
    report = _run(_Fake(_config(), _only(cid, lambda: _resp(200, odd))))
    assert report.expected_checks == 20  # returned a report; no AttributeError/TypeError escaped


# --------------------------------------------------------------------------------------------
# D3 — transport failures are errors, never passes
# --------------------------------------------------------------------------------------------

_ECHO = "Authorization: Bearer {tokens}"
_EXC_FACTORIES: list[Callable[[str, httpx.Request], Exception]] = [
    lambda m, r: httpx.ConnectError(m, request=r),
    lambda m, r: httpx.ReadTimeout(m, request=r),
    lambda m, r: httpx.ConnectTimeout(m, request=r),
    lambda m, r: httpx.RemoteProtocolError(m, request=r),
    lambda m, r: httpx.HTTPError(m),
]


@pytest.mark.parametrize("make_exc", _EXC_FACTORIES)
def test_transport_error_on_one_probe_is_recorded_and_fails_closed(
    make_exc: Callable[[str, httpx.Request], Exception],
) -> None:
    """D3+D4: an httpx error mid-run lands in `errors`, `ok` is False, and neither the exception's
    header-echoing message nor any token is copied into the report.
    """
    cfg = _config()
    message = _ECHO.format(tokens=" ".join(_all_tokens(cfg)))
    target = "cross_tenant_task_read:alpha->beta"
    inner = _Fake(cfg)

    def handler(request: httpx.Request) -> httpx.Response:
        response = inner(request)
        if inner.cids[-1] == target:
            raise make_exc(message, request)
        return response

    with httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(handler)) as client:
        report = run_canary(client, cfg)

    assert report.ok is False
    assert len(report.errors) >= 1
    assert report.expected_checks == 20
    for text in _texts(report):
        assert message not in text
        for token in _all_tokens(cfg):
            assert token[:-8] not in text


def test_total_outage_is_never_ok() -> None:
    """D3: every request failing at transport level (zero completed checks) must not be ok."""
    cfg = _config()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(handler)) as client:
        report = run_canary(client, cfg)

    assert report.ok is False
    assert report.errors


# --------------------------------------------------------------------------------------------
# D4 — secrets never leak
# --------------------------------------------------------------------------------------------


def test_no_token_appears_in_report_streams_or_logs(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """D4: across a passing run, a leaky run whose API reflects credentials, and an erroring run,
    no token (nor the tampered token's shared prefix) shows up in repr/str(report), violation or
    error text, stdout/stderr, or log records.
    """
    caplog.set_level(logging.DEBUG)
    cfg = _config()
    reports: list[CanaryReport] = [
        _run(_Fake(cfg)),
        _run(_Fake(cfg, lambda cid, _r: _leak_response(cfg, cid), echo=True)),
    ]

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom {request.headers['authorization']}", request=request)

    with httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(failing)) as client:
        reports.append(run_canary(client, cfg))

    assert [r.ok for r in reports] == [True, False, False]
    captured = capsys.readouterr()
    haystacks = [
        *(t for r in reports for t in _texts(r)),
        captured.out,
        captured.err,
        caplog.text,
        *(rec.getMessage() for rec in caplog.records),
    ]
    for token in _all_tokens(cfg):
        for text in haystacks:
            assert token[:-8] not in text, "a token (or the tampered probe) leaked"


# --------------------------------------------------------------------------------------------
# D5 — statelessness
# --------------------------------------------------------------------------------------------


def _summary(report: CanaryReport) -> tuple[Any, ...]:
    return (
        report.ok,
        report.checks_run,
        report.expected_checks,
        [(v.check, v.expected, v.actual) for v in report.violations],
        list(report.errors),
    )


@pytest.mark.parametrize("leaky", [False, True])
def test_two_runs_against_the_same_api_give_identical_reports(leaky: bool) -> None:
    """D5: no state carried between runs (correct API and leaky API), the config is not mutated,
    and each POST /tasks uses a fresh Idempotency-Key.
    # ASSUMPTION: idempotency keys must not repeat across probes or runs (a reused key could make
    a real API replay an earlier response instead of evaluating the probe).
    """
    cfg = _config()
    snapshot = copy.deepcopy(cfg)
    override: Override | None = (lambda cid, _r: _leak_response(cfg, cid)) if leaky else None
    fake = _Fake(cfg, override)
    with httpx.Client(base_url=_BASE_URL, transport=httpx.MockTransport(fake)) as client:
        first = run_canary(client, cfg)
        n_first = len(fake.requests)
        second = run_canary(client, cfg)

    assert _summary(first) == _summary(second)
    assert len(fake.requests) == 2 * n_first
    assert cfg == snapshot
    keys = [r.headers["idempotency-key"] for r in fake.requests if r.method == "POST"]
    assert len(keys) == 4
    assert len(set(keys)) == 4


# --------------------------------------------------------------------------------------------
# D6 — main(): exit code 2 on bad config, no requests, no secrets printed
# --------------------------------------------------------------------------------------------


def _run_main(argv: list[str]) -> int:
    """# ASSUMPTION: an argparse-style SystemExit(2) counts as returning 2."""
    try:
        return main(argv)
    except SystemExit as exit_:
        assert isinstance(exit_.code, int)
        return exit_.code


def _write_config_files(tmp_path: Path) -> list[tuple[str, Path]]:
    good = _config()
    one_firm = {"firms": {"alpha": good["firms"]["alpha"]}}
    no_key = copy.deepcopy(good)
    del no_key["firms"]["beta"]["owner_token"]
    non_str = copy.deepcopy(good)
    non_str["firms"]["beta"]["task_id"] = 5
    variants: list[tuple[str, bytes]] = [
        ("empty", b""),
        ("not_json", b"this is not json SECRETTOKEN-oops"),
        ("truncated", b'{"firms": {"alpha": {"owner_token": "SECRETTOKEN-alpha-owner-01234'),
        ("json_list", b'["SECRETTOKEN-list"]'),
        ("json_null", b"null"),
        ("json_string", b'"SECRETTOKEN-string"'),
        ("binary", bytes(range(128, 256)) + b"SECRETTOKEN"),
        ("one_firm", json.dumps(one_firm).encode()),
        ("no_firms_key", json.dumps({"tokens": good["firms"]}).encode()),
        ("missing_field", json.dumps(no_key).encode()),
        ("non_string_field", json.dumps(non_str).encode()),
    ]
    files: list[tuple[str, Path]] = []
    for name, content in variants:
        path = tmp_path / f"{name}.json"
        path.write_bytes(content)
        files.append((name, path))
    return files


@pytest.fixture
def no_http(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record (and refuse) any HTTP send made by main()'s own client."""
    sent: list[object] = []

    def _record(*args: object, **_kwargs: object) -> None:
        sent.append(args)
        raise AssertionError("main() sent an HTTP request despite a bad config")

    monkeypatch.setattr(httpx.Client, "send", _record)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _record)
    return sent


def test_main_returns_2_for_every_kind_of_bad_config_without_sending_or_printing_secrets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_http: list[object]
) -> None:
    """D6+D4: missing/unreadable/invalid --config -> exit 2, no HTTP, no secret on any stream."""
    cases = _write_config_files(tmp_path)
    cases.append(("missing_file", tmp_path / "does-not-exist.json"))
    cases.append(("directory", tmp_path))
    for name, path in cases:
        assert _run_main(["--config", str(path)]) == 2, name
        captured = capsys.readouterr()
        assert "SECRETTOKEN" not in captured.out + captured.err, name
    assert no_http == []


@pytest.mark.parametrize("argv", [[], ["--config"]])
def test_main_without_a_usable_config_argument_exits_2(
    argv: list[str], no_http: list[object]
) -> None:
    """D6: no --config at all (or one without a value) is a usage error -> 2, no requests."""
    assert _run_main(argv) == 2
    assert no_http == []
