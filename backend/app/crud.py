"""DB read/write logic — routes stay thin (fastapi/project-structure.md). Every function here
trusts `session` to already have `app.current_tenant` set (get_current_profile, api/deps.py) — RLS
does the tenant-scoping; nothing here filters by `firm_id` itself, per ARCHITECTURE.md §5's
division of responsibility (RLS = isolation, crud/routes = role-based authorization).
"""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, select

from app.core.supabase_admin import admin_auth
from app.models import AuditLog, Profile


def _generate_password() -> str:
    # secrets.token_urlsafe: CSPRNG, not `random` (ASVS 6.4.1's "securely random"). 16 bytes = 128
    # bits, well past the length policy in ARCHITECTURE.md §4.
    return secrets.token_urlsafe(16)


def _write_audit_log(
    session: Session, actor: Profile, action: str, target_id: UUID | None
) -> None:
    session.add(
        AuditLog(
            firm_id=actor.firm_id,
            actor_id=actor.id,
            action=action,
            target_id=target_id,
            created_at=datetime.now(UTC),
        )
    )


def create_employee(
    session: Session, actor: Profile, full_name: str, email: str
) -> tuple[UUID, str]:
    """Returns (new employee's profile id, generated password — transmitted exactly once)."""
    password = _generate_password()
    result = admin_auth.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "firm_id": str(actor.firm_id),
                "role": "employee",
                "full_name": full_name,
            },
        }
    )
    if result.user is None:
        # create_user raises AuthApiError on a real failure — a None user here would mean
        # Supabase's own API contract changed, not a normal client-facing error.
        raise RuntimeError("Supabase admin.create_user returned no user")
    new_id = UUID(result.user.id)

    _write_audit_log(session, actor, action="employee_created", target_id=new_id)
    session.commit()
    return new_id, password


def list_employees(session: Session, offset: int, limit: int) -> list[Profile]:
    stmt = select(Profile).where(Profile.role == "employee").offset(offset).limit(limit)
    return list(session.exec(stmt).all())


def get_employee(session: Session, employee_id: UUID) -> Profile | None:
    return session.exec(
        select(Profile).where(Profile.id == employee_id, Profile.role == "employee")
    ).first()


def set_employee_active(
    session: Session, actor: Profile, employee: Profile, is_active: bool
) -> Profile:
    employee.is_active = is_active
    session.add(employee)
    action = "employee_reactivated" if is_active else "employee_deactivated"
    _write_audit_log(session, actor, action=action, target_id=employee.id)
    session.commit()
    session.refresh(employee)
    return employee


def reset_employee_password(session: Session, actor: Profile, employee: Profile) -> str:
    """Generates a new password via the Admin API and marks it one-time-use, same as
    create_employee — `must_change_password` lives only in `profiles`, so it's a plain update
    here, not another Admin API call (ARCHITECTURE.md §4).
    """
    password = _generate_password()
    admin_auth.update_user_by_id(str(employee.id), {"password": password})

    now = datetime.now(UTC)
    employee.must_change_password = True
    employee.last_reset_by = actor.id
    employee.last_reset_at = now
    session.add(employee)
    _write_audit_log(session, actor, action="password_reset", target_id=employee.id)
    session.commit()
    return password
