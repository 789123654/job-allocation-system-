"""add issue_resolved to notifications type check

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Reported gap, 2026-09-18: resolve_issue (crud.py) previously only notified the issue's raiser when
resolution_type="reassigned" (via _reassign_task's own "task_reassigned" notify) — "clarified" and
"deadline_adjusted" left them with zero signal at all, not even a stale one, since there was no
issue_resolved value to fire in the first place. Widens the DB-level enum (notifications_type_check,
verified live via `SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid =
'public.notifications'::regclass AND contype = 'c'` before writing this — the constraint's real,
unnamed-in-SQLModel auto-generated name and its current 8-value list) from 8 to 9 values. Not added
to `ix_notifications_dedup`'s partial UNIQUE index (824d532c93a2) — that index only covers the 4
recurring time-based types; `issue_resolved` fires at most once per issue, same category as
`issue_raised`/`task_assigned`/`task_reassigned`, already guaranteed by resolve_issue's own
`if locked.status != "open": raise InvalidIssueStateError` guard plus the route's `with_idempotency`
wrapper, not by a DB constraint.

Revision ID: 0563652c7653
Revises: 0128fa263257
Create Date: 2026-09-18 15:16:17.201035

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0563652c7653"
down_revision: str | Sequence[str] | None = "0128fa263257"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = (
    "task_submitted",
    "task_overdue",
    "task_deadline_1_day",
    "issue_raised",
    "task_assigned",
    "task_reassigned",
    "task_deadline_approaching",
    "task_overdue_own",
)
_NEW_TYPES = (*_OLD_TYPES, "issue_resolved")


def _quoted_list(types: tuple[str, ...]) -> str:
    return ", ".join("'" + t + "'" for t in types)


def upgrade() -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(
        "ALTER TABLE notifications ADD CONSTRAINT notifications_type_check "
        f"CHECK (type IN ({_quoted_list(_NEW_TYPES)}))"
    )


def downgrade() -> None:
    # Same order Postgres requires either direction: drop before add, one CHECK per column at a
    # time. A downgrade with any existing issue_resolved row present will fail the ADD CONSTRAINT
    # (matches this project's other downgrade paths — never silently drops data to make a
    # downgrade succeed).
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(
        "ALTER TABLE notifications ADD CONSTRAINT notifications_type_check "
        f"CHECK (type IN ({_quoted_list(_OLD_TYPES)}))"
    )
