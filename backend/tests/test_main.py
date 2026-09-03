"""Global error-handling behavior (Error_Handling_Cheat_Sheet.md) — a genuine bug must never fall
through to a raw framework 500; it should still come back as the app's own problem+json shape.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.models import Profile


@pytest.fixture
def client() -> Generator[TestClient]:
    app.dependency_overrides[deps.require_owner] = lambda: Profile(
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
    broken_session.exec.side_effect = RuntimeError("boom — simulated unexpected bug")
    app.dependency_overrides[deps.get_session] = lambda: broken_session
    # TestClient re-raises server exceptions by default (useful for debugging tests, not for
    # testing the handler itself) — disable that so the real HTTP response is what's asserted.
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_unhandled_exception_returns_problem_json_not_a_raw_500(client: TestClient) -> None:
    response = client.get("/employees")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["detail"] == "An unexpected error occurred"
    assert "boom" not in body["detail"]  # the real exception message must never reach the client
