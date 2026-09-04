from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select
from sqlmodel import text as sql_text

from app.core.db import get_session
from app.core.security import InvalidTokenError, verify_access_token
from app.models import Profile

SessionDep = Annotated[Session, Depends(get_session)]
_bearer_scheme = HTTPBearer()


def get_current_profile(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> Profile:
    """The verified caller for this request. `firm_id`/`role` come from the JWT (they never change
    post-creation, ARCHITECTURE.md §4); `is_active` is re-read from the DB below on every request —
    the JWT alone can't reflect a deactivation until it expires (ARCHITECTURE.md §4 finding).

    Returns a plain `Profile`, not a subclass — a `table=True` SQLModel subclassed for a "this is
    the verified caller" marker type breaks SQLAlchemy's attribute instrumentation on some
    construction paths (caught by tests/api/routes/test_employees.py, 2026-09-05). Not worth the
    fragility for a purely documentary distinction.
    """
    try:
        claims = verify_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from None

    app_metadata = claims.get("app_metadata", {})
    firm_id = app_metadata.get("firm_id")
    user_id = claims.get("sub")
    if not firm_id or not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing required claims")

    # Parameterized, not string-interpolated — set_config() is a normal SQL function, unlike the
    # bare `SET LOCAL` statement, so the firm_id value is bound safely. `is_local=true` makes it
    # transaction-scoped exactly like `SET LOCAL` (ARCHITECTURE.md §5) — reset at commit/rollback
    # regardless of connection reuse under Supavisor pooling.
    session.execute(  # pyright: ignore[reportDeprecated]
        # SQLModel's exec() doesn't accept a raw TextClause (only Select/SelectOfScalar/UpdateBase
        # per its overloads, checked 2026-09-04) — execute() is the only API that actually works
        # for a bare `SELECT set_config(...)` call whose return value we don't use.
        sql_text("SELECT set_config('app.current_tenant', :firm_id, true)"),
        {"firm_id": str(firm_id)},
    )

    profile = session.exec(select(Profile).where(Profile.id == UUID(user_id))).first()
    if profile is None or not profile.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account inactive or not found")

    return profile


CurrentProfileDep = Annotated[Profile, Depends(get_current_profile)]


def require_password_set(profile: CurrentProfileDep) -> Profile:
    """Every route except the frontend's direct-to-Supabase Set New Password call (never routed
    through FastAPI, API_SPEC.md §3) uses `ActiveProfileDep`, not raw `CurrentProfileDep` — this
    dependency is the real server-side gate the forced Set New Password screen is backed by.
    """
    if profile.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    return profile


ActiveProfileDep = Annotated[Profile, Depends(require_password_set)]


def require_owner(profile: ActiveProfileDep) -> Profile:
    if profile.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return profile


RequireOwnerDep = Annotated[Profile, Depends(require_owner)]
