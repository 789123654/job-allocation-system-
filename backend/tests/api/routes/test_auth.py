"""Route-level test — dependency-overridden, no real DB, same convention as test_job_types.py."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.models import Profile

_FIRM_ID = uuid4()
_OWNER_ID = uuid4()


@pytest.fixture
def pending_owner() -> Profile:
    return Profile(
        id=_OWNER_ID,
        firm_id=_FIRM_ID,
        role="owner",
        full_name="Owner",
        email="owner@example.com",
        is_active=True,
        must_change_password=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def client(pending_owner: Profile) -> Generator[TestClient]:
    # Deliberately overrides get_current_profile, not require_password_set — this route's whole
    # point (API_SPEC.md §3) is to be reachable via CurrentProfileDep while must_change_password
    # is still true; ActiveProfileDep would 403 it before it ever ran.
    app.dependency_overrides[deps.get_current_profile] = lambda: pending_owner
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_confirm_password_changed_clears_the_flag_and_returns_204(
    client: TestClient, pending_owner: Profile
) -> None:
    response = client.post("/auth/confirm-password-changed")

    assert response.status_code == 204
    assert pending_owner.must_change_password is False
