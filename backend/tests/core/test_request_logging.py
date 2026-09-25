"""Access log + request id + identity context, end to end (app/core/request_logging.py).

Two apps: a small controllable one for the middleware's own properties, and the real `app.main.app`
for the wiring (500 handler, security headers, /health). Never touches a database or the network.
"""

import json
import logging
import sys
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import deps
from app.core import request_context, runtime_stats
from app.core.logging_setup import configure_logging
from app.core.request_logging import RequestLoggingMiddleware
from app.main import app as real_app
from app.models import Profile

configure_logging()
_app_logger = logging.getLogger("app")


def _ok() -> dict[str, str]:
    return {"status": "ok"}


def _item(item_id: str) -> dict[str, str]:
    return {"id": item_id}


async def _echo(request: Request) -> dict[str, int]:
    return {"bytes": len(await request.body())}


def _whoami(tenant: str, actor: str, role: str = "employee") -> dict[str, str]:
    # A plain sync def, like get_current_profile: runs in a worker thread on a copied context.
    request_context.bind_identity(tenant_id=tenant, actor_id=actor, actor_role=role)
    _app_logger.warning("inside handler")
    return {"ok": "1"}


def _boom() -> None:
    raise RuntimeError("secret-internal-detail")


def _mini_app() -> FastAPI:
    mini = FastAPI()
    mini.add_middleware(RequestLoggingMiddleware)
    mini.add_api_route("/ok", _ok, methods=["GET"])
    mini.add_api_route("/items/{item_id}", _item, methods=["GET"])
    mini.add_api_route("/echo", _echo, methods=["POST"])
    mini.add_api_route("/whoami", _whoami, methods=["GET"])
    mini.add_api_route("/boom", _boom, methods=["GET"])
    return mini


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(_mini_app(), raise_server_exceptions=False) as c:
        yield c


def _records(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]  # every stdout line must be valid JSON


def _access(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["logger"] == "app.access"]


def test_one_access_record_per_request_with_the_documented_fields(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    response = client.get("/ok")
    (record,) = _access(_records(capsys))
    assert record["level"] == "INFO"
    assert record["message"] == "request"
    assert record["method"] == "GET"
    assert record["route"] == "/ok"
    assert record["status"] == response.status_code == 200
    assert record["duration_ms"] >= 0
    for key in ("pool_checked_out", "pool_capacity", "threadpool_borrowed", "threadpool_total"):
        assert key in record
    assert record["threadpool_total"] == 40


def test_the_route_template_is_logged_not_the_raw_path(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    secret_id = str(uuid4())
    client.get(f"/items/{secret_id}")
    out = capsys.readouterr().out
    (record,) = _access([json.loads(line) for line in out.splitlines() if line.strip()])
    assert record["route"] == "/items/{item_id}"
    assert secret_id not in out


def test_an_unmatched_path_is_never_echoed_into_the_log(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    client.get("/attacker-controlled-SENTINEL-PATH")
    out = capsys.readouterr().out
    (record,) = _access([json.loads(line) for line in out.splitlines() if line.strip()])
    assert record["route"] == "<unmatched>"
    assert record["status"] == 404
    assert "SENTINEL-PATH" not in out


def test_request_id_is_server_generated_unique_and_client_value_is_ignored(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    first = client.get("/ok", headers={"X-Request-ID": "attacker-chosen-id"})
    second = client.get("/ok")
    records = _access(_records(capsys))
    ids = [first.headers["x-request-id"], second.headers["x-request-id"]]
    assert ids[0] != ids[1]
    assert "attacker-chosen-id" not in ids
    assert all(UUID(i).version == 4 for i in ids)
    assert [r["request_id"] for r in records] == ids


def test_tokens_query_strings_and_bodies_never_reach_the_logs(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logging_Cheat_Sheet.md 'Data to exclude' (access tokens); ASVS 14.2.1; TCASVS 3.2.3."""
    capsys.readouterr()
    client.post(
        "/echo?filter=SENTINEL-QUERY&token=SENTINEL-QTOKEN",
        headers={"Authorization": "Bearer SENTINEL-JWT.PART.SIG", "X-Custom": "SENTINEL-HEADER"},
        content=b"SENTINEL-BODY",
    )
    out = capsys.readouterr().out
    for sentinel in ("SENTINEL-QUERY", "SENTINEL-QTOKEN", "SENTINEL-JWT", "SENTINEL-HEADER"):
        assert sentinel not in out
    assert "SENTINEL-BODY" not in out


def test_hostile_input_cannot_forge_split_or_break_log_lines(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    forged = '{"level":"CRITICAL","message":"forged","logger":"app.access","status":200}'
    # 60_000 chars: httpx itself rejects a URL over 65_536 before it could reach the app.
    hostile = ("/%0a" + forged, "/x?q=%0d%0a" + forged, "/" + "A" * 60_000)
    for path in hostile:
        client.get(path, headers={"X-Big": "B" * 30_000})
    client.post("/echo", content=("\n" + forged + "\r\u2028").encode())

    out = capsys.readouterr().out
    records = [json.loads(line) for line in out.splitlines() if line.strip()]  # all lines valid
    assert len(_access(records)) == len(hostile) + 1  # exactly one per request, no forged extras
    assert all(r["message"] != "forged" for r in records)
    assert max(len(line) for line in out.splitlines()) < 20_000


def test_identity_bound_in_a_sync_handler_reaches_every_record_of_that_request(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    tenant, actor = uuid4(), uuid4()
    response = client.get("/whoami", params={"tenant": str(tenant), "actor": str(actor)})
    request_id = response.headers["x-request-id"]
    mine = [r for r in _records(capsys) if r["request_id"] == request_id]
    assert {r["logger"] for r in mine} == {"app", "app.access"}  # handler line AND access line
    for record in mine:
        assert (record["tenant_id"], record["actor_id"], record["actor_role"]) == (
            str(tenant),
            str(actor),
            "employee",
        )


def test_an_invalid_identity_value_is_dropped_not_logged(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    client.get("/whoami", params={"tenant": "SENTINEL-NOT-A-UUID", "actor": "also-bad"})
    out = capsys.readouterr().out
    assert "SENTINEL-NOT-A-UUID" not in out
    (record,) = _access([json.loads(line) for line in out.splitlines() if line.strip()])
    assert record["tenant_id"] is None
    assert record["actor_id"] is None


def test_identity_never_bleeds_into_the_next_request(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    client.get("/whoami", params={"tenant": str(uuid4()), "actor": str(uuid4())})
    client.get("/ok")  # does not authenticate
    first, second = _access(_records(capsys))
    assert first["tenant_id"] is not None
    assert (second["tenant_id"], second["actor_id"], second["actor_role"]) == (None, None, None)


def test_concurrent_requests_from_different_tenants_never_share_identity(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """The multi-tenancy property: a log line attributed to the wrong tenant is worse than none."""
    capsys.readouterr()

    def call(_: int) -> tuple[str, str, str]:
        tenant, actor = str(uuid4()), str(uuid4())
        response = client.get("/whoami", params={"tenant": tenant, "actor": actor})
        return response.headers["x-request-id"], tenant, actor

    with ThreadPoolExecutor(16) as pool:
        calls = list(pool.map(call, range(96)))

    by_request: dict[str, list[dict[str, Any]]] = {}
    for record in _records(capsys):
        by_request.setdefault(record["request_id"], []).append(record)
    for request_id, tenant, actor in calls:
        records = by_request[request_id]
        assert len(records) == 2  # the handler's own line + the access line
        assert all((r["tenant_id"], r["actor_id"]) == (tenant, actor) for r in records)


def test_an_unhandled_exception_is_logged_as_a_500(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    response = client.get("/boom")
    assert response.status_code == 500
    (record,) = _access(_records(capsys))
    assert (record["status"], record["route"]) == (500, "/boom")


def test_a_failure_while_building_the_access_record_never_surfaces_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suppress in _log_access guards OUR code (stats gathering), which `logging`'s own
    handler-error swallowing does not cover (ASVS 16.5.2). _log_access runs AFTER the response is
    sent, so a leak would not change the body — it would surface as an unhandled ASGI error (a
    traceback per request, possibly a reset connection). A STRICT client is what makes that
    visible: the lenient one swallows post-response errors, which made a first version of this
    test pass on broken code too (caught by the negative control, Rule 10.1).
    """

    def broken() -> tuple[int | None, int | None]:
        raise RuntimeError("stats exploded")

    monkeypatch.setattr(runtime_stats, "threadpool_stats", broken)
    with TestClient(_mini_app(), raise_server_exceptions=True) as strict:
        response = strict.get("/ok")  # raises here if the error escaped the middleware
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_a_failing_log_stream_never_changes_the_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ASVS 16.5.2: logging is best-effort and must not turn a good response into an error."""

    class BrokenStream:
        def write(self, _text: str) -> int:
            raise OSError("stdout closed")

        def flush(self) -> None:
            raise OSError("stdout closed")

    monkeypatch.setattr(sys, "stdout", BrokenStream())
    response = client.get("/ok")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- the real app: wiring the mini app can't prove ---------------------------------------------


@pytest.fixture
def real_client() -> Generator[TestClient]:
    with TestClient(real_app, raise_server_exceptions=False) as c:
        yield c
    real_app.dependency_overrides.clear()


def test_health_is_liveness_only_and_is_logged(
    real_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    response = real_client.get("/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    (record,) = _access(_records(capsys))
    assert record["route"] == "/health"
    assert record["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"  # the security-headers middleware ran


def test_an_unauthenticated_call_is_logged_with_no_identity_and_its_real_status(
    real_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    response = real_client.get("/tasks")
    assert response.status_code in (401, 403)
    (record,) = _access(_records(capsys))
    assert record["route"] == "/tasks"
    assert record["status"] == response.status_code
    assert record["actor_id"] is None


def test_the_500_response_carries_a_request_id_that_matches_its_log_lines(
    real_client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    real_app.dependency_overrides[deps.require_owner] = lambda: Profile(
        id=uuid4(),
        firm_id=uuid4(),
        role="owner",
        full_name="Owner",
        email="owner@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )
    broken_session = MagicMock()
    broken_session.exec.side_effect = RuntimeError("SENTINEL-INTERNAL-FAILURE")
    real_app.dependency_overrides[deps.get_session] = lambda: broken_session

    capsys.readouterr()
    response = real_client.get("/employees")
    request_id = response.headers["x-request-id"]
    records = _records(capsys)

    assert response.status_code == 500
    assert response.json()["detail"] == "An unexpected error occurred"
    assert "SENTINEL-INTERNAL-FAILURE" not in response.text  # never to the client
    (access,) = _access(records)
    assert (access["status"], access["request_id"]) == (500, request_id)
    (error,) = [r for r in records if r["level"] == "ERROR"]
    assert error["request_id"] == request_id
    assert "SENTINEL-INTERNAL-FAILURE" in error["exc"]  # ...but the server-side log has it
