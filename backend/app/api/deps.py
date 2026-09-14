import logging
from typing import Annotated
from uuid import UUID

import sentry_sdk
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select
from sqlmodel import text as sql_text

from app import crud
from app.core.config import settings
from app.core.db import get_session
from app.core.security import InvalidTokenError, verify_access_token
from app.models import Profile

logger = logging.getLogger("app.auth")

SessionDep = Annotated[Session, Depends(get_session)]
# Shared across every Idempotency-Key route (tasks/issues/employees) — was the literal header
# alias repeated 7 times across three files (SonarQube: define a constant instead of duplicating).
# max_length added (code-review finding #14, 2026-09-14): every Pydantic Field()-declared string
# elsewhere in this codebase has one (Input_Validation_Cheat_Sheet.md — "minimum and maximum length
# check for strings"), but Header() is a different declaration idiom and this one was missed. No
# source specifies a required number: neither Rule 230 (rest-api-guidelines) nor the Idempotency-Key
# header's own schema it points to (Zalando's headers-1.0.0.yaml, fetched directly — `type: string,
# format: uuid`, no length constraint) sets one; it just recommends "a UUID v4 or any other random
# string with enough entropy." 255 is a judgment call, not a cited figure — generous for any
# legitimate UUID (36 chars) or reasonable random token, while still capping an oversized value
# (Header() accepts the same validation kwargs as Query()/Path(), confirmed against
# fastapi/guide/tutorial/header-params.md, not assumed from Query's own docs alone).
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key", max_length=255)]
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
    except InvalidTokenError as exc:
        # ASVS 5 §16.3.1 / Multi_Tenant_Security_Cheat_Sheet.md §8: authentication operations must
        # be logged, success and failure — this was the one gap this app had no logging for at all
        # (grep confirmed the only prior logger call anywhere was main.py's generic 500 handler).
        # No token contents logged, only that verification failed and why (never the token itself).
        # False positive, verified against PyJWT's actual installed source (jwt/api_jwt.py,
        # jwt/api_jws.py, jwt/jwks_client.py): every PyJWTError/PyJWKClientError message is a
        # static string ("Signature has expired", "Invalid audience", ...) — none interpolate the
        # raw token. `exc` here can never contain the token itself, only which check failed.
        # nosemgrep: python-logger-credential-disclosure
        logger.warning("Authentication failed: invalid or expired token (%s)", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from None

    app_metadata = claims.get("app_metadata", {})
    firm_id = app_metadata.get("firm_id")
    user_id = claims.get("sub")
    if not firm_id or not user_id:
        logger.warning("Authentication failed: token missing firm_id/sub claims")
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

    # Tenant tag, set as early as firm_id is known-good — every log line and Sentry event for the
    # rest of this request is then attributable to a tenant without threading firm_id through every
    # call site by hand (saas-multitenant-architecture ch07: "every metric event a service emits
    # should minimally carry tenant identity" — the interception point already exists here, this is
    # the cheap moment to hook it, not a new mechanism). Sentry's FastAPI integration auto-captures
    # any later unhandled exception in this request (main.py's own handler) with this tag already
    # attached, no separate wiring needed. Guarded like main.py's own sentry_sdk.init() call — a
    # no-op in dev/test where SENTRY_DSN is unset, same reasoning as that guard.
    if settings.SENTRY_DSN:
        sentry_sdk.set_tag("tenant_id", str(firm_id))

    try:
        # Code-review finding #15 (2026-09-14): every other malformed-token shape in this function
        # is caught and turned into a clean 401 — this line was the one place that pattern wasn't
        # applied, most likely because a `sub` claim from an already-signature-verified JWT
        # "shouldn't" be malformed. It still isn't trusted input at the type level: nothing stops a
        # legitimately-signed token from carrying a non-UUID `sub` (a misissued token, a JWT signed
        # by a differently-configured Supabase project sharing the same JWKS during a migration,
        # etc.), and Input_Validation_Cheat_Sheet.md's baseline — validate structure, don't assume
        # it from where the data came from — applies to every claim, not just the ones already
        # covered above.
        user_uuid = UUID(user_id)
    except ValueError:
        logger.warning("Authentication failed: token 'sub' claim is not a valid UUID")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing required claims") from None

    profile = session.exec(select(Profile).where(Profile.id == user_uuid)).first()
    if profile is None or not profile.is_active:
        logger.warning(
            "Authentication failed: profile %s inactive or not found (firm %s)", user_id, firm_id
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account inactive or not found")

    logger.debug("Authentication succeeded for profile %s (firm %s)", user_id, firm_id)
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


def require_owner(profile: ActiveProfileDep, session: SessionDep) -> Profile:
    if profile.role != "owner":
        crud.record_access_denial(session, profile, None, None, "wrong_role")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return profile


RequireOwnerDep = Annotated[Profile, Depends(require_owner)]
