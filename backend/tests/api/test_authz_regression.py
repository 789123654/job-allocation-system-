"""Authorization regression suite — the object-level and role-level checks that quietly rot as
routes get added or refactored (Authorization_Regression_Testing_Cheat_Sheet.md).

Three patterns from that cheat sheet, driven end to end through the real app + real auth chain
(get_current_profile -> require_password_set -> require_owner) against a real Postgres, the same
way test_schema_fuzz.py / test_deps.py do — never a dependency_override, since the whole point is
that the real middleware/RLS/ownership checks fire:

  - "Multi-User Replay" (horizontal / IDOR): a second account of the same role cannot read or
    mutate the first account's objects by id. Asserted as 404, not 403 — the route's documented
    choice (API_SPEC.md §3) so a prober can't even confirm the id exists.
  - "Role Demotion Check" (vertical): the JWT's `app_metadata.role` claim is not trusted — an
    employee whose token says `role: owner` still gets 403 on owner-only routes, because
    require_owner reads the *DB* profile row, not the claim.
  - "Cross-Tenant Boundary Test": firm B cannot touch firm A's objects by id (RLS,
    already covered structurally in test_rls_isolation.py — here it's re-checked through the HTTP
    surface, which is where a caching/query refactor would actually leak it).

Needs a real Postgres — same reason and same skip pattern as test_deps.py.
"""

import os
import time
from collections.abc import Generator
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core import security
from app.main import app

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

_SKIP_REASON = "needs a real Postgres — TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)"

pytestmark = [
    pytest.mark.authz,
    pytest.mark.skipif(not (_MIGRATIONS_URL and _APP_URL), reason=_SKIP_REASON),
]

# Same set and reasoning as test_schema_fuzz.py — firm-scoped tables wiped before `firms`.
_FIRM_SCOPED_TABLES = (
    "notifications",
    "access_denials",
    "audit_log",
    "task_reviews",
    "issues",
    "idempotency_keys",
    "tasks",
    "job_types",
    "profiles",
)

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

_FUTURE_DEADLINE = "2099-01-01T00:00:00Z"


def _make_token(sub: str, firm_id: str, role: str = "owner") -> str:
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "iss": security.settings.JWT_ISSUER,
        "exp": int(time.time()) + 3600,
        "app_metadata": {"firm_id": firm_id, "role": role},
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _mock_jwks(  # pyright: ignore[reportUnusedFunction] — autouse pytest fixture, run by pytest
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same as test_deps.py / test_schema_fuzz.py — swap the JWKS network call for a fixed key.
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=_PUBLIC_KEY),
    )


@dataclass
class _Seeded:
    firm_a: UUID
    firm_b: UUID
    owner_a: UUID
    emp_a1: UUID
    emp_a2: UUID
    task_a1: UUID  # assigned to emp_a1
    job_type_a: UUID
    issue_a1: UUID  # on task_a1, raised by emp_a1
    notif_a: UUID  # recipient owner_a
    token_owner_b: str
    token_emp_a2: str
    token_owner_a: str
    token_emp_a1: str
    token_emp_a1_claiming_owner: str  # DB role employee, JWT claim says owner


def _profile_insert(conn: object, firm_id: UUID, profile_id: UUID, role: str) -> None:
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO profiles "
            "(id, firm_id, role, full_name, email, is_active, must_change_password) "
            "VALUES (:pid, :fid, :role, 'x', :email, true, false)"
        ),
        {"pid": profile_id, "fid": firm_id, "role": role, "email": f"{profile_id}@example.com"},
    )


@pytest.fixture
def seeded() -> Generator[_Seeded]:
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_a, firm_b = uuid4(), uuid4()
    owner_a, emp_a1, emp_a2, owner_b = uuid4(), uuid4(), uuid4(), uuid4()

    with admin_engine.begin() as conn:
        for firm_id in (firm_a, firm_b):
            conn.execute(
                text(
                    "INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"
                ),
                {"id": firm_id},
            )
        _profile_insert(conn, firm_a, owner_a, "owner")
        _profile_insert(conn, firm_a, emp_a1, "employee")
        _profile_insert(conn, firm_a, emp_a2, "employee")
        _profile_insert(conn, firm_b, owner_b, "owner")

        task_a1 = conn.execute(
            text(
                "INSERT INTO tasks (firm_id, title, status, created_by, assigned_to) "
                "VALUES (:fid, 'T', 'assigned', :owner, :emp) RETURNING id"
            ),
            {"fid": firm_a, "owner": owner_a, "emp": emp_a1},
        ).scalar_one()
        job_type_a = conn.execute(
            text(
                "INSERT INTO job_types (firm_id, name, created_by) "
                "VALUES (:fid, 'GST', :owner) RETURNING id"
            ),
            {"fid": firm_a, "owner": owner_a},
        ).scalar_one()
        issue_a1 = conn.execute(
            text(
                "INSERT INTO issues (firm_id, task_id, raised_by, description) "
                "VALUES (:fid, :tid, :emp, 'blocked') RETURNING id"
            ),
            {"fid": firm_a, "tid": task_a1, "emp": emp_a1},
        ).scalar_one()
        notif_a = conn.execute(
            text(
                "INSERT INTO notifications (firm_id, recipient_id, type, task_id) "
                "VALUES (:fid, :owner, 'task_submitted', :tid) RETURNING id"
            ),
            {"fid": firm_a, "owner": owner_a, "tid": task_a1},
        ).scalar_one()

    yield _Seeded(
        firm_a=firm_a,
        firm_b=firm_b,
        owner_a=owner_a,
        emp_a1=emp_a1,
        emp_a2=emp_a2,
        task_a1=task_a1,
        job_type_a=job_type_a,
        issue_a1=issue_a1,
        notif_a=notif_a,
        token_owner_b=_make_token(str(owner_b), str(firm_b)),
        token_emp_a2=_make_token(str(emp_a2), str(firm_a), role="employee"),
        token_owner_a=_make_token(str(owner_a), str(firm_a)),
        token_emp_a1=_make_token(str(emp_a1), str(firm_a), role="employee"),
        token_emp_a1_claiming_owner=_make_token(str(emp_a1), str(firm_a), role="owner"),
    )

    with admin_engine.begin() as conn:
        for firm_id in (firm_a, firm_b):
            for table in _FIRM_SCOPED_TABLES:
                conn.execute(text(f"DELETE FROM {table} WHERE firm_id = :fid"), {"fid": firm_id})  # noqa: S608
            conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _auth_idem(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


# --- Cross-tenant boundary (firm B -> firm A objects) — all 404 -----------------------------------


def test_cross_tenant_task_read_is_404(client: TestClient, seeded: _Seeded) -> None:
    r = client.get(f"/tasks/{seeded.task_a1}", headers=_auth(seeded.token_owner_b))
    assert r.status_code == 404


def test_cross_tenant_task_deadline_patch_is_404(client: TestClient, seeded: _Seeded) -> None:
    r = client.patch(
        f"/tasks/{seeded.task_a1}/deadline",
        headers=_auth(seeded.token_owner_b),
        json={"deadline": _FUTURE_DEADLINE},
    )
    assert r.status_code == 404


def test_cross_tenant_employee_patch_is_404(client: TestClient, seeded: _Seeded) -> None:
    r = client.patch(
        f"/employees/{seeded.emp_a1}",
        headers=_auth(seeded.token_owner_b),
        json={"is_active": False},
    )
    assert r.status_code == 404


def test_cross_tenant_job_type_patch_is_404(client: TestClient, seeded: _Seeded) -> None:
    r = client.patch(
        f"/job-types/{seeded.job_type_a}",
        headers=_auth(seeded.token_owner_b),
        json={"is_active": False},
    )
    assert r.status_code == 404


def test_cross_tenant_issue_resolve_is_404(client: TestClient, seeded: _Seeded) -> None:
    r = client.post(
        f"/issues/{seeded.issue_a1}/resolve",
        headers=_auth_idem(seeded.token_owner_b),
        json={"resolution_type": "clarified", "resolution_notes": "x"},
    )
    assert r.status_code == 404


def test_cross_tenant_notification_read_is_404(client: TestClient, seeded: _Seeded) -> None:
    r = client.patch(f"/notifications/{seeded.notif_a}/read", headers=_auth(seeded.token_owner_b))
    assert r.status_code == 404


# --- Multi-user replay (firm A employee -> another firm-A account's objects) ----------------------


def test_other_employees_task_is_not_visible(client: TestClient, seeded: _Seeded) -> None:
    # emp_a2 is a real employee of the same firm, but not the assignee of task_a1.
    r = client.get(f"/tasks/{seeded.task_a1}", headers=_auth(seeded.token_emp_a2))
    assert r.status_code == 404


def test_other_employees_task_cannot_be_submitted(client: TestClient, seeded: _Seeded) -> None:
    r = client.post(f"/tasks/{seeded.task_a1}/submit", headers=_auth_idem(seeded.token_emp_a2))
    assert r.status_code == 404


def test_owner_is_not_the_assignee_and_cannot_submit(client: TestClient, seeded: _Seeded) -> None:
    # The owner *can* see every task (get_task passes), so this one is a real 403 from
    # _require_assignee, not a 404 — the task's existence is legitimately known here.
    r = client.post(f"/tasks/{seeded.task_a1}/submit", headers=_auth_idem(seeded.token_owner_a))
    assert r.status_code == 403


# submit/mark-billed/issues all route through the same _get_task_or_404 + _require_assignee pair
# (tasks.py), so this is the same code path as test_other_employees_task_cannot_be_submitted above,
# not a different mechanism — added anyway per Authorization_Regression_Testing_Cheat_Sheet.md
# (2026-09-12 Tasks-Employee-side audit): a shared check being correct at one call site is not
# evidence it's wired the same way at every call site until a test actually exercises each one.
def test_other_employees_task_cannot_be_marked_billed(
    client: TestClient, seeded: _Seeded
) -> None:
    r = client.post(
        f"/tasks/{seeded.task_a1}/mark-billed", headers=_auth_idem(seeded.token_emp_a2)
    )
    assert r.status_code == 404


def test_other_employees_task_cannot_have_an_issue_raised_on_it(
    client: TestClient, seeded: _Seeded
) -> None:
    r = client.post(
        f"/tasks/{seeded.task_a1}/issues",
        headers=_auth_idem(seeded.token_emp_a2),
        json={"description": "Blocked"},
    )
    assert r.status_code == 404


def test_employee_cannot_read_another_accounts_notification(
    client: TestClient, seeded: _Seeded
) -> None:
    # notif_a's recipient is owner_a; emp_a1 is in the same firm but not the recipient.
    r = client.patch(f"/notifications/{seeded.notif_a}/read", headers=_auth(seeded.token_emp_a1))
    assert r.status_code == 404


# --- Role demotion check: the JWT role claim is not trusted, the DB row is -----------------------


def test_jwt_owner_claim_does_not_grant_job_type_creation(
    client: TestClient, seeded: _Seeded
) -> None:
    # Token's app_metadata.role == "owner"; the DB profile for emp_a1 is role "employee".
    r = client.post(
        "/job-types",
        headers=_auth(seeded.token_emp_a1_claiming_owner),
        json={"name": "Fraudulent"},
    )
    assert r.status_code == 403


def test_jwt_owner_claim_does_not_grant_employee_listing(
    client: TestClient, seeded: _Seeded
) -> None:
    r = client.get("/employees", headers=_auth(seeded.token_emp_a1_claiming_owner))
    assert r.status_code == 403


# --- No credentials at all ----------------------------------------------------------------------


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    # No seeded data needed — HTTPBearer rejects before any DB-touching dependency runs.
    r = client.get("/tasks")
    assert r.status_code in (401, 403)
