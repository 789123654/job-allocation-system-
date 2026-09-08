"""notifications dedup and profiles role indexes

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Revision ID: 824d532c93a2
Revises: a8e6def15927
Create Date: 2026-09-09 01:32:34.631368

"""

from collections.abc import Sequence

from alembic import op

revision: str = "824d532c93a2"
down_revision: str | Sequence[str] | None = "a8e6def15927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # crud.py's _create_notification_if_missing runs `WHERE firm_id, recipient_id, type, task_id`
    # on every GET /notifications call (ARCHITECTURE.md §8: polled every 30-60s by every logged-in
    # user) — the only existing notifications index (firm_id, recipient_id, is_read, created_at)
    # doesn't cover `type`/`task_id`, so this is currently a scan-and-filter over a whole
    # recipient's history, not an index hit.
    #
    # Partial, not table-wide: the docstring's dedup invariant ("each task fires each type at most
    # once per recipient, ever") only actually holds for the 4 time-based types
    # _ensure_owner_deadline_notifications/_ensure_employee_deadline_notifications generate.
    # task_assigned/task_submitted/task_reassigned/issue_raised are legitimately re-fired for the
    # same (recipient, task_id) — e.g. submit_task fires task_submitted again on every resubmission
    # after a task_reviews "reassigned" outcome (crud.py's own _reassign_task sets status back to
    # in_progress specifically so it can be resubmitted). A table-wide UNIQUE would reject that
    # second legitimate submit_task notification with a raw IntegrityError. WHERE-scoping to just
    # the 4 dedup-checked types makes the constraint match the invariant it's actually enforcing.
    op.execute(
        "CREATE UNIQUE INDEX ix_notifications_dedup "
        "ON notifications (firm_id, recipient_id, type, task_id) "
        "WHERE type IN "
        "('task_overdue', 'task_deadline_1_day', 'task_deadline_approaching', 'task_overdue_own')"
    )

    # crud.py's list_employees (`WHERE role = 'employee'`) and _notify_owners (`WHERE role =
    # 'owner'`, called on every submit_task/create_issue) — neither is covered by anything but the
    # (firm_id, id) primary key today.
    op.execute("CREATE INDEX ix_profiles_firm_role ON profiles (firm_id, role)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_profiles_firm_role")
    op.execute("DROP INDEX IF EXISTS ix_notifications_dedup")
