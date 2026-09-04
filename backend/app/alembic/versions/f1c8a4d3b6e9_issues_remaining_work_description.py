"""issues.remaining_work_description

PRD.md §3.3: an employee must see "the owner's changes and remaining-work description clearly,
whether the reassignment came from a submission review... or from an issue resolution... Both
are distinct triggers and both must surface." `task_reviews` already carries this field;
`issues` didn't, so an issue-triggered reassignment could only ever populate
`tasks.last_reassignment_notes`, never `tasks.last_reassignment_remaining_work` — a real gap
against the PRD, not a stylistic one. Caught 2026-09-04, fixed same day, one migration after
`issues` was first created rather than folded in, since the table was already live in a prior
commit's CI run.

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Revision ID: f1c8a4d3b6e9
Revises: a3f5c9e21d07
Create Date: 2026-09-04 12:20:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c8a4d3b6e9"
down_revision: str | Sequence[str] | None = "a3f5c9e21d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE issues ADD COLUMN remaining_work_description text")


def downgrade() -> None:
    op.execute("ALTER TABLE issues DROP COLUMN IF EXISTS remaining_work_description")
