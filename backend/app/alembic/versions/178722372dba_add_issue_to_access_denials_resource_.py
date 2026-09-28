"""add issue to access_denials resource_type check

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Reported gap, 2026-09-18: GET /issues/{id} was Owner-only (RequireOwnerDep) — an issue's own raiser
had no way to ever read it, including the Owner's resolution_notes once resolved. Widened to any
authenticated actor (ActiveProfileDep, issues.py), narrowed back to least-privilege inside
crud.get_issue (Owner sees any issue in their firm, unchanged; Employee only their own, 404 not
403) — which now calls record_access_denial(session, actor, "issue", ...) on a denied access,
same pattern as get_task/get_notification. Widens the DB-level enum
(access_denials_resource_type_check, verified live via `SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid = 'public.access_denials'::regclass AND contype = 'c'` before
writing this — current 2-value list) from 2 to 3 values. `reason`'s own CHECK
(access_denials_reason_check) already includes 'wrong_owner', also verified live — no change
needed there, this call reuses that existing value, same as get_task's.

Revision ID: 178722372dba
Revises: 0563652c7653
Create Date: 2026-09-18 16:09:28.833881

"""

from collections.abc import Sequence

from alembic import op

revision: str = "178722372dba"
down_revision: str | Sequence[str] | None = "0563652c7653"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = ("task", "notification")
_NEW_TYPES = (*_OLD_TYPES, "issue")


def _quoted_list(types: tuple[str, ...]) -> str:
    return ", ".join("'" + t + "'" for t in types)


def upgrade() -> None:
    op.execute("ALTER TABLE access_denials DROP CONSTRAINT access_denials_resource_type_check")
    op.execute(
        "ALTER TABLE access_denials ADD CONSTRAINT access_denials_resource_type_check "
        f"CHECK (resource_type IN ({_quoted_list(_NEW_TYPES)}))"
    )


def downgrade() -> None:
    # Same order Postgres requires either direction: drop before add. A downgrade with any
    # existing resource_type='issue' row present will fail the ADD CONSTRAINT (matches this
    # project's other downgrade paths — never silently drops data to make a downgrade succeed).
    op.execute("ALTER TABLE access_denials DROP CONSTRAINT access_denials_resource_type_check")
    op.execute(
        "ALTER TABLE access_denials ADD CONSTRAINT access_denials_resource_type_check "
        f"CHECK (resource_type IN ({_quoted_list(_OLD_TYPES)}))"
    )
