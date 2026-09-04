"""SQLModel table definitions. Schema/constraints/RLS live in the Alembic migrations (app/alembic/)
— these classes are for querying, not the source of truth for DDL (DATA_MODEL.md is that).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


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
    firm_id: UUID = Field(primary_key=True, foreign_key="firms.id")
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
    firm_id: UUID = Field(primary_key=True, foreign_key="firms.id")
    name: str
    is_active: bool = True
    created_by: UUID
    created_at: datetime


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key="firms.id")
    actor_id: UUID
    action: str
    target_id: UUID | None = None
    created_at: datetime
