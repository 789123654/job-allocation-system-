"""Supabase Auth Admin API — `supabase_auth` (the standalone, officially-maintained auth-only
client; deliberately not the full `supabase` package, which bundles postgrest/storage/realtime
this project never uses). Endpoint shapes verified against the installed library's own source,
not docs — `create_user`/`update_user_by_id` hit `POST/PUT admin/users[/{uid}]`.

Used only by `POST /employees` and `POST /employees/{id}/reset-password` — every other endpoint
never touches this. `SUPABASE_SECRET_KEY` bypasses RLS; never passed to anything but this client.
"""

from supabase_auth._sync.gotrue_admin_api import SyncGoTrueAdminAPI

from app.core.config import settings

admin_auth = SyncGoTrueAdminAPI(
    url=f"{settings.SUPABASE_URL}/auth/v1",
    headers={
        "apikey": settings.SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
    },
)
