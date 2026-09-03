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


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"  # type: ignore[assignment]  # known SQLModel/pyright interaction

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    firm_id: UUID = Field(primary_key=True, foreign_key="firms.id")
    actor_id: UUID
    action: str
    target_id: UUID | None = None
    created_at: datetime
