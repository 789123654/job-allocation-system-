"""Supabase Auth Admin API — `supabase_auth` (the standalone, officially-maintained auth-only
client; deliberately not the full `supabase` package, which bundles postgrest/storage/realtime
this project never uses). Endpoint shapes verified against the installed library's own source,
not docs — `create_user`/`update_user_by_id` hit `POST/PUT admin/users[/{uid}]`.

Used only by `POST /employees` and `POST /employees/{id}/reset-password` — every other endpoint
never touches this. `SUPABASE_SECRET_KEY` bypasses RLS; never passed to anything but this client.
"""

from typing import Final, get_args

from supabase_auth._sync.gotrue_admin_api import SyncGoTrueAdminAPI
from supabase_auth.errors import AuthError, ErrorCode

from app.core.config import settings

admin_auth = SyncGoTrueAdminAPI(
    url=f"{settings.SUPABASE_URL}/auth/v1",
    headers={
        "apikey": settings.SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
    },
)

_KNOWN_CODES: Final = frozenset(get_args(ErrorCode))


def describe_auth_error(exc: AuthError) -> str:
    """A log-safe one-line description of a Supabase Auth failure: class, HTTP status, error code.

    Never `str(exc)`: Supabase's message can echo the email address being created
    (`Email address "x@y" is invalid`), which is client PII, and a log line leaves the process
    (Railway, and Sentry's log breadcrumbs). The code is only reported when it is one of the
    library's known ErrorCode values, so a string supplied by the server cannot smuggle text into
    the log line. Logging_Cheat_Sheet.md "Data to exclude", TCASVS 3.2.3, ASVS 16.2.5.
    """
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    safe_status = status if isinstance(status, int) else None
    safe_code = code if isinstance(code, str) and code in _KNOWN_CODES else "other"
    return f"{type(exc).__name__} status={safe_status} code={safe_code}"
