"""Blind tests: a task assigned after creation must become status "assigned".

Written from the written contract only (assign-status-contract.md). The implementation was never
read. Helpers are copied from test_task_edit_blind.py (not changed). Each test builds its own
world via the `world` fixture, which wipes its firms afterwards, so tests are independent.

ASSUMPTION (not stated in the contract): the create route is POST /tasks taking title, description
and an optional assigned_to. If that route or payload is wrong, the create tests fail as a
harness/setup problem, not a behavior finding.
"""

import os
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

# ---------------------------------------------------------------------------
# infrastructure helpers (copied from test_task_edit_blind.py, unchanged)
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
    import time

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
    assignee_id: UUID | None,
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


def _plant(world: SimpleNamespace, status: str, assignee: UUID | None = None) -> UUID:
    with world.admin.begin() as conn:
        return _insert_task(conn, world.firm_a, world.owner_a, assignee or world.employee_a, status)


def _plant_unassigned(world: SimpleNamespace, status: str = "created") -> UUID:
    # assigned_to NULL: _plant() always sets an assignee, so this builds the unassigned case
    with world.admin.begin() as conn:
        return _insert_task(conn, world.firm_a, world.owner_a, None, status)


def _row(admin: Engine, task_id: UUID) -> dict[str, Any]:
    with admin.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM tasks WHERE id = :t"), {"t": task_id}).mappings().one()
        )


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
        firm_b = _insert_firm(conn)
        owner_a = _insert_profile(conn, firm_a, "owner")
        employee_a = _insert_profile(conn, firm_a, "employee")
        employee_a2 = _insert_profile(conn, firm_a, "employee")
        inactive_a = _insert_profile(conn, firm_a, "employee", active=False)
        owner_b = _insert_profile(conn, firm_b, "owner")
        employee_b = _insert_profile(conn, firm_b, "employee")
    w = SimpleNamespace(
        admin=admin,
        firm_a=firm_a,
        firm_b=firm_b,
        owner_a=owner_a,
        employee_a=employee_a,
        employee_a2=employee_a2,
        inactive_a=inactive_a,
        owner_b=owner_b,
        employee_b=employee_b,
    )
    yield w
    _wipe(admin, [firm_a, firm_b])


# ---------------------------------------------------------------------------
# create_task: initial status depends on whether an assignee is given
# ---------------------------------------------------------------------------


def test_create_with_assignee_starts_assigned(world: SimpleNamespace) -> None:
    r = _client().post(
        "/tasks",
        json={
            "title": "Created with assignee",
            "description": "d",
            "assigned_to": str(world.employee_a),
        },
        headers={**_bearer(world.owner_a), "Idempotency-Key": str(uuid4())},
    )

    assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text}"
    task_id = UUID(r.json()["id"])
    row = _row(world.admin, task_id)
    assert row["assigned_to"] == world.employee_a
    assert row["status"] == "assigned"


def test_create_without_assignee_starts_created(world: SimpleNamespace) -> None:
    r = _client().post(
        "/tasks",
        json={"title": "Created unassigned", "description": "d"},
        headers={**_bearer(world.owner_a), "Idempotency-Key": str(uuid4())},
    )

    assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text}"
    task_id = UUID(r.json()["id"])
    row = _row(world.admin, task_id)
    assert row["assigned_to"] is None
    assert row["status"] == "created"


# ---------------------------------------------------------------------------
# owner assigns a created task via PATCH
# ---------------------------------------------------------------------------


def test_owner_assigning_created_task_sets_assigned_status_and_updated_at(
    world: SimpleNamespace,
) -> None:
    task_id = _plant_unassigned(world, "created")
    before = _row(world.admin, task_id)

    r = _client().patch(
        f"/tasks/{task_id}",
        json={"assigned_to": str(world.employee_a)},
        headers=_bearer(world.owner_a),
    )

    assert r.status_code == 200, f"patch failed: {r.status_code} {r.text}"
    after = _row(world.admin, task_id)
    assert after["assigned_to"] == world.employee_a
    assert after["status"] == "assigned"
    assert after["updated_at"] != before["updated_at"]


def test_assigned_task_can_be_submitted_by_new_assignee_with_idempotency_key(
    world: SimpleNamespace,
) -> None:
    task_id = _plant_unassigned(world, "created")
    client = _client()

    assign = client.patch(
        f"/tasks/{task_id}",
        json={"assigned_to": str(world.employee_a2)},
        headers=_bearer(world.owner_a),
    )
    assert assign.status_code == 200, f"assign failed: {assign.status_code} {assign.text}"

    r = client.post(
        f"/tasks/{task_id}/submit",
        headers={**_bearer(world.employee_a2), "Idempotency-Key": str(uuid4())},
    )

    assert r.status_code == 200, f"submit failed: {r.status_code} {r.text}"
    assert _row(world.admin, task_id)["status"] == "submitted"


# ---------------------------------------------------------------------------
# edits that must NOT change status
# ---------------------------------------------------------------------------


def test_edit_created_task_without_assignee_keeps_created(world: SimpleNamespace) -> None:
    task_id = _plant_unassigned(world, "created")

    r = _client().patch(
        f"/tasks/{task_id}", json={"title": "Renamed"}, headers=_bearer(world.owner_a)
    )

    assert r.status_code == 200, f"patch failed: {r.status_code} {r.text}"
    row = _row(world.admin, task_id)
    assert row["title"] == "Renamed"
    assert row["status"] == "created"


@pytest.mark.parametrize("body", [{"title": "New title"}, {"description": "New description"}])
def test_title_or_description_edit_on_assigned_task_keeps_assigned(
    world: SimpleNamespace, body: dict[str, str]
) -> None:
    task_id = _plant(world, "assigned")

    r = _client().patch(f"/tasks/{task_id}", json=body, headers=_bearer(world.owner_a))

    assert r.status_code == 200, f"patch failed: {r.status_code} {r.text}"
    assert _row(world.admin, task_id)["status"] == "assigned"
