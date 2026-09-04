"""SQLModel table definitions. Schema/constraints/RLS live in the Alembic migrations (app/alembic/)
— these classes are for querying, not the source of truth for DDL (DATA_MODEL.md is that).
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

_FIRMS_FK = "firms.id"  # every tenant table's firm_id references this — named once, not repeated


class Firm(SQLModel, table=True):
    __tablename__ = "firms"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    plan: str
    status: str
    created_at: datetime


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(primary_key=True)  # = auth.users.id, no default — set at provisioning
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    role: str
    full_name: str
    email: str
    is_active: bool = True
    must_change_password: bool = True
    last_reset_by: UUID | None = None
    last_reset_at: datetime | None = None
    created_at: datetime


class JobType(SQLModel, table=True):
    __tablename__ = "job_types"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    # DATA_MODEL.md §2 lists only `created_at` here (no `updated_at`) — matches the existing
    # precedent on Firm/Profile, which also lack it despite the doc's own general convention
    # (line 15: "created_at/updated_at on every table"). Flagged, not silently resolved either
    # way: fixing it means retrofitting tables already built, out of scope for this slice.
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    name: str
    is_active: bool = True
    created_by: UUID
    created_at: datetime


class Task(SQLModel, table=True):
    __tablename__ = "tasks"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    job_type_id: UUID | None = None
    task_type: str = "standard"
    parent_task_id: UUID | None = None
    title: str
    description: str | None = None
    assigned_to: UUID | None = None
    deadline: datetime | None = None
    status: str = "created"
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    last_reassignment_notes: str | None = None
    last_reassignment_remaining_work: str | None = None
    last_reassignment_source: str | None = None
    last_reassignment_at: datetime | None = None
    billing_amount: float | None = None
    billing_recipient: str | None = None


class IdempotencyKey(SQLModel, table=True):
    __tablename__ = "idempotency_keys"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    # rest-api-guidelines Rule 230 — composite PK doubles as the natural uniqueness constraint
    # (same client, same key, same endpoint can only ever map to one cached response).
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    actor_id: UUID = Field(primary_key=True)
    idempotency_key: str = Field(primary_key=True)
    endpoint: str = Field(primary_key=True)
    request_hash: str
    response_status: int
    response_body: dict[str, Any] = Field(sa_column=Column(JSON))
    created_at: datetime


class TaskReview(SQLModel, table=True):
    __tablename__ = "task_reviews"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    task_id: UUID
    reviewed_by: UUID
    outcome: str
    notes: str | None = None
    remaining_work_description: str | None = None
    resulting_billing_task_id: UUID | None = None
    created_at: datetime


class Issue(SQLModel, table=True):
    __tablename__ = "issues"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    task_id: UUID
    raised_by: UUID
    description: str
    status: str = "open"
    resolution_type: str | None = None
    resolution_notes: str | None = None
    remaining_work_description: str | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    recipient_id: UUID
    type: str
    task_id: UUID | None = None
    issue_id: UUID | None = None
    is_read: bool = False
    created_at: datetime


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key=_FIRMS_FK)
    actor_id: UUID
    action: str
    target_id: UUID | None = None
    created_at: datetime
