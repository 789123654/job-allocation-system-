"""Blind tests for PATCH /tasks/{task_id}: a title-only edit must not depend on the assignee's
current active status. Written from the contract only (scratchpad
edit-unchanged-assignee-contract.md).
The implementation was not read. Helpers are copied from test_task_edit_blind.py (not modified).
Real Postgres required; no skips.
"""

import os
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

# ---------------------------------------------------------------------------
# infrastructure helpers (copied from test_task_edit_blind.py)
# ---------------------------------------------------------------------------


def _admin() -> Engine:
    return create_engine(os.environ["TEST_MIGRATIONS_DATABASE_URL"])


def _client() -> Any:
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


_PROFILE_META: dict[UUID, tuple[UUID, str]] = {}
_key_cache: Any = None


def _signing_key() -> Any:
    from cryptography.hazmat.primitives.asymmetric import rsa

    global _key_cache
    if _key_cache is None:
        _key_cache = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _key_cache


@pytest.fixture(autouse=True)
def _mock_jwks(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    from app.core import security

    key = _signing_key()
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=key.public_key()),
    )


def _bearer(profile_id: UUID) -> dict[str, str]:
    import jwt

    from app.core import security

    firm_id, role = _PROFILE_META[profile_id]
    token = jwt.encode(
        {
            "sub": str(profile_id),
            "aud": "authenticated",
            "iss": security.settings.JWT_ISSUER,
            "exp": int(time.time()) + 3600,
            "app_metadata": {"firm_id": str(firm_id), "role": role},
        },
        _signing_key(),
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _insert_firm(conn: Any) -> UUID:
    firm_id = uuid4()
    conn.execute(
        text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
        {"id": firm_id},
    )
    return firm_id


def _insert_profile(conn: Any, firm_id: UUID, role: str, active: bool = True) -> UUID:
    pid = uuid4()
    conn.execute(
        text(
            "INSERT INTO profiles "
            "(id, firm_id, role, full_name, email, is_active, must_change_password) "
            "VALUES (:id, :fid, :role, 'x', :email, :active, false)"
        ),
        {"id": pid, "fid": firm_id, "role": role, "email": f"{pid}@example.com", "active": active},
    )
    _PROFILE_META[pid] = (firm_id, role)
    return pid


def _insert_task(
    conn: Any,
    firm_id: UUID,
    owner_id: UUID,
    assignee_id: UUID,
    status: str,
    title: str = "Original",
    description: str = "Original desc",
) -> UUID:
    task_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO tasks (id, firm_id, title, description, assigned_to, status, created_by) "
            "VALUES (:id, :fid, :title, :desc, :assignee, :status, :owner)"
        ),
        {
            "id": task_id,
            "fid": firm_id,
            "title": title,
            "desc": description,
            "assignee": assignee_id,
            "status": status,
            "owner": owner_id,
        },
    )
    return task_id


def _row(admin: Engine, task_id: UUID) -> dict[str, Any]:
    with admin.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM tasks WHERE id = :t"), {"t": task_id}).mappings().one()
        )


def _history(admin: Engine, task_id: UUID) -> list[dict[str, Any]]:
    with admin.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT * FROM task_edits WHERE task_id = :t ORDER BY created_at"),
                {"t": task_id},
            ).mappings()
        ]


def _wipe(admin: Engine, firm_ids: list[UUID]) -> None:
    with admin.begin() as conn:
        for fid in firm_ids:
            for stmt in (
                "DELETE FROM notifications WHERE firm_id = :fid",
                "DELETE FROM task_edits WHERE firm_id = :fid",
                "DELETE FROM task_reviews WHERE firm_id = :fid",
                "DELETE FROM issues WHERE firm_id = :fid",
                "DELETE FROM idempotency_keys WHERE firm_id = :fid",
                "DELETE FROM access_denials WHERE firm_id = :fid",
                "DELETE FROM audit_log WHERE firm_id = :fid",
                "DELETE FROM job_types WHERE firm_id = :fid",
            ):
                conn.execute(text(stmt), {"fid": fid})
            conn.execute(text("DELETE FROM tasks WHERE firm_id = :fid"), {"fid": fid})
            conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": fid})
            conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": fid})
    admin.dispose()


@pytest.fixture
def world() -> Iterator[SimpleNamespace]:
    admin = _admin()
    with admin.begin() as conn:
        firm_a = _insert_firm(conn)
        owner_a = _insert_profile(conn, firm_a, "owner")
        employee_a = _insert_profile(conn, firm_a, "employee")
    w = SimpleNamespace(admin=admin, firm_a=firm_a, owner_a=owner_a, employee_a=employee_a)
    yield w
    _wipe(admin, [firm_a])


def _plant_assigned(world: SimpleNamespace) -> UUID:
    with world.admin.begin() as conn:
        return _insert_task(
            conn, world.firm_a, world.owner_a, world.employee_a, "assigned"
        )


def _deactivate(world: SimpleNamespace, profile_id: UUID) -> None:
    # the real deactivation flag: is_active = false, same column the harness inserts
    with world.admin.begin() as conn:
        conn.execute(
            text("UPDATE profiles SET is_active = false WHERE id = :id AND firm_id = :fid"),
            {"id": profile_id, "fid": world.firm_a},
        )


# ---------------------------------------------------------------------------
# contract item 1: title-only edit with a deactivated assignee succeeds
# ---------------------------------------------------------------------------


def test_title_only_edit_with_deactivated_assignee_succeeds(world: SimpleNamespace) -> None:
    task_id = _plant_assigned(world)
    _deactivate(world, world.employee_a)

    r = _client().patch(
        f"/tasks/{task_id}", json={"title": "New title"}, headers=_bearer(world.owner_a)
    )

    assert r.status_code == 200, r.text
    row = _row(world.admin, task_id)
    assert row["title"] == "New title"
    assert row["assigned_to"] == world.employee_a, "assignee changed on a title-only edit"
    assert row["status"] == "assigned", "status changed on a title-only edit"

    history = _history(world.admin, task_id)
    assert len(history) == 1, f"expected exactly one history row, got {len(history)}"
    changed = history[0]["changed_fields"]
    assert "title" in changed, f"title missing from changed_fields: {changed!r}"
    assert "assigned_to" not in changed, f"assigned_to leaked into changed_fields: {changed!r}"


# ---------------------------------------------------------------------------
# contract item 2: explicitly naming the deactivated assignee is still refused
# ---------------------------------------------------------------------------


def test_naming_deactivated_assignee_again_is_422_and_unchanged(world: SimpleNamespace) -> None:
    task_id = _plant_assigned(world)
    _deactivate(world, world.employee_a)
    before = _row(world.admin, task_id)

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"assigned_to": str(world.employee_a)},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 422, f"status {r.status_code}: {r.text}"
    assert _row(world.admin, task_id) == before, "row changed despite 422"
    assert _history(world.admin, task_id) == [], "history row written despite 422"


# ---------------------------------------------------------------------------
# contract item 3: empty body is refused
# ---------------------------------------------------------------------------


def test_empty_body_is_422_and_unchanged(world: SimpleNamespace) -> None:
    task_id = _plant_assigned(world)
    before = _row(world.admin, task_id)

    r = _client().patch(f"/tasks/{task_id}", json={}, headers=_bearer(world.owner_a))

    assert r.status_code == 422, f"status {r.status_code}: {r.text}"
    assert _row(world.admin, task_id) == before, "row changed despite 422"
    assert _history(world.admin, task_id) == [], "history row written despite 422"
