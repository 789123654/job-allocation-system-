"""Canary config validation the blind tests don't reach (found by negative control C8, 2026-09-19:
removing the UUID check left all 289 blind tests green). An id from the config is interpolated into
a request path, so a non-UUID value is a path-injection vector into an authenticated probe.
"""

import uuid
from typing import Any

import httpx
import pytest

from ops import canary


def _firm(n: int) -> dict[str, str]:
    return {
        "owner_token": f"tok-owner-{n}",
        "employee_token": f"tok-employee-{n}",
        "task_id": str(uuid.UUID(int=n * 10 + 1)),
        "other_employee_task_id": str(uuid.UUID(int=n * 10 + 2)),
        "job_type_id": str(uuid.UUID(int=n * 10 + 3)),
        "notification_id": str(uuid.UUID(int=n * 10 + 4)),
    }


def _config_dict() -> dict[str, Any]:
    return {"firms": {"a": _firm(1), "b": _firm(2)}}


def _client(sent: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://canary.test")


@pytest.mark.parametrize(
    "field", ["task_id", "other_employee_task_id", "job_type_id", "notification_id"]
)
@pytest.mark.parametrize("bad", ["../../admin", "abc", "1; DROP TABLE tasks", "a/b", "?x=1"])
def test_a_non_uuid_id_is_rejected_before_any_request_is_sent(field: str, bad: str) -> None:
    config = _config_dict()
    config["firms"]["b"][field] = bad
    sent: list[httpx.Request] = []
    with pytest.raises(ValueError, match="UUID") as caught:
        canary.run_canary(_client(sent), config)
    assert sent == []
    assert field in str(caught.value)
    assert bad not in str(caught.value)  # names the field, never the value


@pytest.mark.parametrize(("firms", "expected"), [(2, 20), (3, 48), (4, 88)])
def test_expected_check_count_is_pinned_independently_of_the_probe_list(
    firms: int, expected: int
) -> None:
    assert canary._expected_check_count(firms) == expected  # pyright: ignore[reportPrivateUsage]


def test_a_dropped_probe_makes_the_run_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard against a probe silently disappearing: fewer probes must never read as "all passed".
    real = canary._same_tenant  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(canary, "_same_tenant", lambda x, fx: real(x, fx)[:-1])
    report = canary.run_canary(_client([]), _config_dict())
    assert report.expected_checks == 20
    assert report.checks_run == 18
    assert not report.ok
