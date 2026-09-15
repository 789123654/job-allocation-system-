"""Schema-driven contract/crash fuzzing (Schemathesis) — drives every route straight from the
app's own OpenAPI schema with Hypothesis-generated inputs, independent of any hand-written request
in tests/api/routes/*.py. Catches what those miss: an undeclared 500, a response that doesn't match
its own documented schema, a crash on malformed/edge-case input
(Authorization_Regression_Testing_Cheat_Sheet.md names Schemathesis for exactly this).

Runs authenticated as one real seeded owner via the real auth dependency chain (get_current_profile
→ require_password_set → require_owner), not a dependency_override — the whole point is exercising
real request handling, including the set_config() tenant-context call and real RLS-scoped queries,
the same way tests/api/test_deps.py does. This is contract/crash-fuzzing for one fixed role, not
authorization-boundary testing (a separate, already-flagged, still-open task) — every case is sent
as an owner, so a wrong-role 403 path is never what's being checked here.

Needs a real Postgres — same reason and same skip pattern as tests/api/test_deps.py.
"""

import os
import time
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import jwt
import pytest
import schemathesis
from cryptography.hazmat.primitives.asymmetric import rsa
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings
from schemathesis.checks import not_a_server_error
from sqlalchemy import create_engine, text

from app.core import security
from app.core.supabase_admin import admin_auth
from app.main import app

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (_MIGRATIONS_URL and _APP_URL),
    reason="needs a real Postgres — set TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
)

# firm-scoped tables only (every one has a real DB-level firm_id -> firms.id FK per models.py;
# none of task_id/job_type_id/etc. carry a DB FK, so deletion order between these doesn't matter —
# only "before firms" does).
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


def _make_token(sub: str, firm_id: str) -> str:
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "iss": security.settings.JWT_ISSUER,
        "exp": int(time.time()) + 3600,
        "app_metadata": {"firm_id": firm_id, "role": "owner"},
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _mock_jwks(  # pyright: ignore[reportUnusedFunction] — autouse pytest fixture, run by pytest
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same approach as tests/api/test_deps.py — swap the real JWKS network call for a fixed key.
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=_PUBLIC_KEY),
    )


@pytest.fixture(autouse=True)
def _mock_supabase_admin(  # pyright: ignore[reportUnusedFunction] — autouse pytest fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /employees (crud.create_employee) calls the real Supabase Admin API — SUPABASE_URL is
    a placeholder domain in this test env (no real project exists yet, same as CI), so a real call
    fails with a DNS ConnectError, not an application bug. Faked at the same `admin_auth` object
    tests/api/routes/test_employees.py's own route tests never needed to touch (they monkeypatch
    crud.create_employee wholesale instead) — this test wants the real DB-writing half of
    create_employee to actually run, only the external network call faked.

    The fake also inserts a real `profiles` row for the new id — on a real Supabase project, the
    Admin API's auth.users insert fires ARCHITECTURE.md's provisioning trigger, which is what
    normally creates that row; skipping the network call means skipping the trigger too, and
    create_employee's very next step (an audit_log insert with target_id = new id) has a real FK
    to profiles — first discovered as a ForeignKeyViolation from this exact fixture (2026-09-08).
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above

    def _fake_create_user(data: dict[str, object], **kw: object) -> SimpleNamespace:
        new_id = uuid4()
        # firm_id/role in app_metadata, full_name in user_metadata (code review finding #11,
        # 2026-09-14) — mirrors handle_new_user()'s real post-fix source split (migration
        # c0f23284b2fd), same reasoning as this fixture's own docstring above: fake only the
        # network call, keep the DB-write shape identical to what the real trigger would do.
        app_metadata = data["app_metadata"]
        user_metadata = data["user_metadata"]
        assert isinstance(app_metadata, dict)
        assert isinstance(user_metadata, dict)
        admin_engine = create_engine(_MIGRATIONS_URL)  # type: ignore[arg-type]
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO profiles (id, firm_id, role, full_name, email, is_active) "
                    "VALUES (:id, :fid, 'employee', :name, :email, true)"
                ),
                {
                    "id": new_id,
                    "fid": app_metadata["firm_id"],
                    "name": user_metadata["full_name"],
                    "email": data["email"],
                },
            )
        admin_engine.dispose()
        return SimpleNamespace(user=SimpleNamespace(id=str(new_id)))

    monkeypatch.setattr(admin_auth, "create_user", _fake_create_user)


@pytest.fixture
def owner_token() -> Generator[str]:
    """Seeds one real firm+owner (bypasses RLS via the migrations/admin role, same reasoning as
    test_deps.py's `profile` fixture), yields a Bearer token for it, and wipes everything Hypothesis
    may have created under this firm during the test.
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_id, profile_id = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
            {"id": firm_id},
        )
        conn.execute(
            text(
                "INSERT INTO profiles "
                "(id, firm_id, role, full_name, email, is_active, must_change_password) "
                "VALUES (:pid, :fid, 'owner', 'x', :email, true, false)"
            ),
            {"pid": profile_id, "fid": firm_id, "email": f"{profile_id}@example.com"},
        )
    yield _make_token(sub=str(profile_id), firm_id=str(firm_id))
    with admin_engine.begin() as conn:
        for table in _FIRM_SCOPED_TABLES:
            conn.execute(text(f"DELETE FROM {table} WHERE firm_id = :fid"), {"fid": firm_id})  # noqa: S608
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


schema = schemathesis.openapi.from_asgi("/openapi.json", app)
# 5 real, pre-existing crashes this test has found so far (2026-09-08), full history in
# docs/SECURITY_AUDIT_CHECKLIST.md — all fixed, no exclusions currently active:
# - POST /job-types, GET /notifications, POST /tasks, GET /tasks: one shared RLS/session-lifecycle
#   root cause (get_session's expire_on_commit=False, crud.py's post-commit refresh/query fixes)
#   plus two narrower ones (crud._validate_job_type, offset bounds on every list endpoint).
# - A 5th, found only once the above unblocked POST /job-types far enough to reach it: a NUL byte
#   (\x00) in a string field crashed Postgres text-column encoding instead of a clean 422 — fixed
#   via app/core/validation.NoNulStr, applied to every client-controlled free-text/filter field
#   across the API, not just job_types.name.


@schema.parametrize()  # pyright: ignore[reportUntypedFunctionDecorator] — schemathesis itself is untyped here
@hypothesis_settings(
    max_examples=20,
    deadline=None,
    # owner_token seeds one firm/profile per endpoint and is meant to be reused across every
    # Hypothesis example for that endpoint, not reset per-example — a deliberate choice, not the
    # accidental DB-state-reuse this health check normally guards against.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_api_contract(case: "schemathesis.Case[Any]", owner_token: str) -> None:
    # Scoped to crash-detection only (not_a_server_error), not full status-code/schema
    # conformance: every route's `responses={...}` currently documents only its happy-path status
    # codes (API_SPEC.md), so the default check set fails almost every operation on an undeclared
    # 401/403 rather than a real bug — a pre-existing OpenAPI-spec-completeness gap across the
    # whole API, not something to paper over here. Confirmed real by running once with the default
    # checks (2026-09-08): every failure was "Undocumented HTTP status code" for 401/403, zero
    # were actual crashes. Tightening `responses={}` everywhere is its own, separate task.
    case.call_and_validate(
        headers={"Authorization": f"Bearer {owner_token}"},
        checks=[not_a_server_error],  # pyright: ignore[reportArgumentType] — schemathesis's own
        # @check decorator types not_a_server_error as CheckClass | CheckFunction, a real ambiguity
        # in the library's stubs, not a wrong call here (confirmed: it's the exact object
        # schemathesis's own tutorial docs pass to this same parameter).
    )


@pytest.mark.authz
@schema.parametrize()  # pyright: ignore[reportUntypedFunctionDecorator] — schemathesis itself is untyped here
@hypothesis_settings(max_examples=5, deadline=None)
def test_every_operation_rejects_a_missing_token(case: "schemathesis.Case[Any]") -> None:
    """Contract-driven authz negative (Authorization_Regression_Testing_Cheat_Sheet.md — "generate
    negative test cases ... requests without tokens ... to ensure the API fails securely"). Driven
    straight from the OpenAPI schema, so it also covers routes no hand-written test touches.

    An unauthenticated call must never be *processed* and must never crash: the property is a
    plain 4xx rejection — never a 2xx (would mean it ran) and never a 5xx (would mean it started
    running and blew up). In practice this is 401/403 from the auth dependency, plus the odd 404/
    405/422 from schemathesis's negative phase mutating the method or a path param; a documented
    method wrongly rejected would be caught by test_api_contract's positive run above.
    `/health` is the one intentionally public route.
    """
    if case.path == "/health":
        pytest.skip("intentionally public")
    response = case.call()  # no Authorization header
    assert 400 <= response.status_code < 500, (
        f"{case.method} {case.path} returned {response.status_code} without a token"
    )
