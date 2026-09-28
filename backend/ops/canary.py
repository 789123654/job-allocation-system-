"""Tenant-isolation canary: a black-box probe of a deployed API using synthetic tenants.

Implements the three regression patterns from Authorization_Regression_Testing_Cheat_Sheet.md
against the LIVE API, on a schedule (Multi_Tenant_Security_Cheat_Sheet.md §8: "monitor for
cross-tenant access attempts / alert on tenant isolation violations"):
  - Cross-Tenant Boundary: firm X's credentials must never read or change firm Y's objects, and a
    list endpoint must never contain one of Y's ids ("even a single leaked record identifier
    constitutes a critical failure").
  - Multi-User Replay (horizontal): an employee cannot read a same-firm task assigned to someone
    else.
  - Role Demotion (vertical): an employee cannot use owner-only endpoints; a tampered token is 401.

FAIL CLOSED, by design: a canary that cannot reach the API, sends fewer probes than it should, or
executes nothing is a FAILURE, never a pass. A k6 load run on 2026-09-18 reported "clean" while
executing ZERO isolation checks (wrong git ref) — `ok` therefore also requires that the number of
probes actually run equals the number the config implies, computed independently of the probe list.

Secrets: tokens appear only in request headers. Errors record the exception CLASS only (an httpx
message can echo the Authorization header), and nothing here prints or logs a credential.
"""

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx

_TOKEN_FIELDS = ("owner_token", "employee_token")
_ID_FIELDS = ("task_id", "other_employee_task_id", "job_type_id", "notification_id")
_TAMPER_SUFFIX = "AAAAAAAA"
_TIMEOUT_SECONDS = 15.0
_LOCAL_HOSTS = ("http://localhost", "http://127.0.0.1")
_EXIT_OK, _EXIT_VIOLATIONS, _EXIT_USAGE = 0, 1, 2


@dataclass(frozen=True)
class Violation:
    check: str
    expected: str
    actual: str


@dataclass
class CanaryReport:
    expected_checks: int
    checks_run: int = 0
    violations: list[Violation] = field(default_factory=list[Violation])
    errors: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return (
            self.expected_checks > 0
            and self.checks_run == self.expected_checks
            and not self.violations
            and not self.errors
        )


@dataclass(frozen=True)
class _Probe:
    check: str
    method: str
    path: str
    token: str
    expected_status: int
    body: dict[str, object] | None = None
    # Set only on the list probe: the OTHER firm's task id that must not appear in the response.
    forbidden_task_id: str | None = None


def _as_dict(value: object) -> dict[str, Any] | None:
    """JSON gives untyped values; narrow once here instead of at every access."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _expected_check_count(firms: int) -> int:
    # Independent of the probe list on purpose: if a probe is ever dropped from the builder, the
    # run stops being `ok` instead of quietly checking less.
    return 6 * firms * (firms - 1) + 4 * firms


def _validate(config: object) -> dict[str, dict[str, str]]:
    """ValueError (never a partial run) unless >=2 firms, each with every field a non-empty string
    and every id field a valid UUID (an id is put in a URL path, so this also blocks injection).
    Messages name the firm label and field, never a value.
    """
    top = _as_dict(config)
    raw = _as_dict(top.get("firms")) if top is not None else None
    if raw is None:
        raise ValueError("config must be an object with a 'firms' object")
    if len(raw) < 2:
        raise ValueError("at least two firms are required to test isolation")
    return {label: _validate_firm(label, firm_obj) for label, firm_obj in raw.items()}


def _validate_firm(label: str, firm_obj: object) -> dict[str, str]:
    firm = _as_dict(firm_obj)
    if firm is None:
        raise ValueError(f"firm {label!r} must be an object")
    checked: dict[str, str] = {}
    for key in (*_TOKEN_FIELDS, *_ID_FIELDS):
        value = firm.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"firm {label!r}: {key!r} must be a non-empty string")
        checked[key] = value
    for key in _ID_FIELDS:
        try:
            uuid.UUID(checked[key])
        except ValueError:
            raise ValueError(f"firm {label!r}: {key!r} must be a UUID") from None
    return checked


def _cross_tenant(x: str, fx: dict[str, str], y: str, fy: dict[str, str]) -> list[_Probe]:
    arrow = f"{x}->{y}"
    owner, employee = fx["owner_token"], fx["employee_token"]
    task = fy["task_id"]
    return [
        _Probe(f"cross_tenant_task_read:{arrow}", "GET", f"/tasks/{task}", owner, 404),
        _Probe(f"cross_tenant_task_read_employee:{arrow}", "GET", f"/tasks/{task}", employee, 404),
        _Probe(
            f"cross_tenant_task_list_leak:{arrow}",
            "GET",
            "/tasks",
            owner,
            200,
            forbidden_task_id=task,
        ),
        _Probe(
            f"cross_tenant_task_deadline_patch:{arrow}",
            "PATCH",
            f"/tasks/{task}/deadline",
            owner,
            404,
            {"deadline": "2030-01-01T00:00:00Z"},
        ),
        _Probe(
            f"cross_tenant_job_type_patch:{arrow}",
            "PATCH",
            f"/job-types/{fy['job_type_id']}",
            owner,
            404,
            {"is_active": True},
        ),
        _Probe(
            f"cross_tenant_notification_patch:{arrow}",
            "PATCH",
            f"/notifications/{fy['notification_id']}/read",
            owner,
            404,
        ),
    ]


def _same_tenant(x: str, fx: dict[str, str]) -> list[_Probe]:
    employee = fx["employee_token"]
    return [
        _Probe(
            f"same_tenant_other_employee_task:{x}",
            "GET",
            f"/tasks/{fx['other_employee_task_id']}",
            employee,
            404,
        ),
        _Probe(
            f"employee_create_task_forbidden:{x}",
            "POST",
            "/tasks",
            employee,
            403,
            {"title": "canary-probe"},
        ),
        _Probe(
            f"employee_job_type_patch_forbidden:{x}",
            "PATCH",
            f"/job-types/{fx['job_type_id']}",
            employee,
            403,
            {"is_active": True},
        ),
        _Probe(
            f"tampered_token_rejected:{x}",
            "GET",
            "/notifications",
            employee[: -len(_TAMPER_SUFFIX)] + _TAMPER_SUFFIX,
            401,
        ),
    ]


def _build_request(client: httpx.Client, probe: _Probe) -> httpx.Request:
    headers = {"Authorization": f"Bearer {probe.token}"}
    if probe.method == "POST":
        headers["Idempotency-Key"] = str(uuid.uuid4())  # fresh per probe: a reused key could replay
    request = client.build_request(probe.method, probe.path, headers=headers, json=probe.body)
    # A response cookie must never carry one identity into another's probe: each is authenticated
    # by its own Bearer header alone.
    request.headers.pop("cookie", None)
    return request


def _check_list(probe: _Probe, response: httpx.Response, report: CanaryReport) -> None:
    expected = "200 list without the other firm's task"
    if response.status_code != probe.expected_status:
        report.violations.append(Violation(probe.check, expected, str(response.status_code)))
        return
    try:
        body: object = response.json()
    except ValueError:
        report.violations.append(Violation(probe.check, expected, "200 with a non-JSON body"))
        return
    if not isinstance(body, list):
        report.violations.append(Violation(probe.check, expected, "200 with a non-list body"))
        return
    for item in cast("list[object]", body):
        entry = _as_dict(item)
        if entry is not None and entry.get("id") == probe.forbidden_task_id:
            report.violations.append(
                Violation(probe.check, expected, "200 leaking the other firm's task")
            )
            return


def _run_probe(client: httpx.Client, probe: _Probe, report: CanaryReport) -> None:
    report.checks_run += 1
    try:
        response = client.send(_build_request(client, probe))
    except Exception as exc:
        # Class name only: an httpx error message can echo the Authorization header verbatim.
        report.errors.append(f"{probe.check}: {type(exc).__name__}")
        return
    if probe.forbidden_task_id is not None:
        _check_list(probe, response, report)
    elif response.status_code != probe.expected_status:
        report.violations.append(
            Violation(probe.check, str(probe.expected_status), str(response.status_code))
        )


def run_canary(client: httpx.Client, config: dict[str, Any]) -> CanaryReport:
    firms = _validate(config)
    probes: list[_Probe] = []
    for x, fx in firms.items():
        for y, fy in firms.items():
            if x != y:
                probes += _cross_tenant(x, fx, y, fy)
        probes += _same_tenant(x, fx)
    report = CanaryReport(expected_checks=_expected_check_count(len(firms)))
    for probe in probes:
        _run_probe(client, probe, report)
    return report


# --- command line: reads a config, logs the synthetic accounts in, runs, reports -----------------


class _LoginError(Exception):
    pass


def _login(client: httpx.Client, supabase: dict[str, str], email: str, password: str) -> str:
    # Same call the CI e2e suite makes against a real local Supabase stack (tests/e2e).
    response = client.post(
        f"{supabase['url']}/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": email, "password": password},
        headers={"apikey": supabase["publishable_key"]},
    )
    data = _as_dict(response.json()) if response.status_code == 200 else None
    token = data.get("access_token") if data is not None else None
    if not isinstance(token, str) or not token:
        raise _LoginError(f"HTTP {response.status_code}")
    return token


def _nonempty(obj: object, key: str) -> bool:
    fields = _as_dict(obj)
    return fields is not None and isinstance(fields.get(key), str) and bool(fields[key])


def _firm_needs_login(label: str, firm_obj: object) -> bool:
    """True if this firm supplies credentials rather than ready tokens; ValueError if it supplies
    neither for some role."""
    firm = _as_dict(firm_obj)
    if firm is None:
        raise ValueError(f"firm {label!r} must be an object")
    needs_login = False
    for role in ("owner", "employee"):
        if _nonempty(firm, f"{role}_token"):
            continue
        creds = firm.get(role)
        if not (_nonempty(creds, "email") and _nonempty(creds, "password")):
            raise ValueError(f"firm {label!r}: needs {role}_token or {role} credentials")
        needs_login = True
    return needs_login


def _validate_shape(config: object) -> None:
    """Everything checkable WITHOUT a network call, so a bad config never triggers a login."""
    top = _as_dict(config)
    if top is None:
        raise ValueError("config must be an object")
    base = top.get("api_base_url")
    if not isinstance(base, str) or not base.startswith(("https://", *_LOCAL_HOSTS)):
        raise ValueError("api_base_url must be an https:// URL")
    firms = _as_dict(top.get("firms"))
    if firms is None or len(firms) < 2:
        raise ValueError("at least two firms are required")
    # A list, not a generator: every firm must be validated, even after the first needs a login.
    needs_login = any([_firm_needs_login(label, firm) for label, firm in firms.items()])
    supabase = top.get("supabase")
    if needs_login and not (_nonempty(supabase, "url") and _nonempty(supabase, "publishable_key")):
        raise ValueError("credentials given but no supabase url/publishable_key")


def _with_tokens(config: dict[str, Any], client: httpx.Client) -> dict[str, Any]:
    firms: dict[str, dict[str, Any]] = {}
    for label, firm in config["firms"].items():
        filled = dict(firm)
        for role in ("owner", "employee"):
            if not _nonempty(filled, f"{role}_token"):
                creds = filled[role]
                filled[f"{role}_token"] = _login(
                    client, config["supabase"], creds["email"], creds["password"]
                )
        firms[label] = filled
    return {"firms": firms}


def _write(text: str) -> None:
    sys.stdout.write(text + "\n")


def _print_report(report: CanaryReport) -> None:
    verdict = "OK" if report.ok else "FAILED"
    _write(
        f"canary: {report.checks_run}/{report.expected_checks} checks, "
        f"{len(report.violations)} violations, {len(report.errors)} errors -> {verdict}"
    )
    for v in report.violations:
        _write(f"VIOLATION {v.check}: expected {v.expected}, got {v.actual}")
    for error in report.errors:
        _write(f"ERROR {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ops.canary", description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="JSON config (a secret)")
    args = parser.parse_args(argv)  # a usage error exits 2 via argparse itself
    try:
        config: Any = json.loads(args.config.read_text(encoding="utf-8"))
        _validate_shape(config)
    except (OSError, ValueError):
        # No detail on purpose: a malformed secret file's exception text could echo its content.
        sys.stderr.write("canary: config missing, unreadable or invalid\n")
        return _EXIT_USAGE
    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as auth_client:
            full = _with_tokens(config, auth_client)
        with httpx.Client(base_url=config["api_base_url"], timeout=_TIMEOUT_SECONDS) as api:
            report = run_canary(api, full)
    except (_LoginError, httpx.HTTPError, ValueError) as exc:
        sys.stderr.write(f"canary: could not run ({type(exc).__name__})\n")
        return _EXIT_VIOLATIONS
    _print_report(report)
    return _EXIT_OK if report.ok else _EXIT_VIOLATIONS


if __name__ == "__main__":
    sys.exit(main())
