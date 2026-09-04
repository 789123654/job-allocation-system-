"""DB read/write logic — routes stay thin (fastapi/project-structure.md). Every function here
trusts `session` to already have `app.current_tenant` set (get_current_profile, api/deps.py) — RLS
does the tenant-scoping; nothing here filters by `firm_id` itself, per ARCHITECTURE.md §5's
division of responsibility (RLS = isolation, crud/routes = role-based authorization).
"""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.supabase_admin import admin_auth
from app.models import AuditLog, Issue, JobType, Profile, Task, TaskReview


class DuplicateJobTypeNameError(Exception):
    """Raised when UNIQUE (firm_id, name) is violated — the 'Secondary key' idempotency pattern
    API_SPEC.md names for POST /job-types (same shape as Employees' email-uniqueness dedup).
    """


class InvalidTaskStateError(Exception):
    """Raised when a workflow-state-checked task transition isn't valid from the task's current
    status (API_SPEC.md: submit only from assigned/in_progress, mark-billed only for billing tasks
    that are assigned/in_progress).
    """


class InvalidIssueStateError(Exception):
    """Raised when an issue resolution is attempted on an issue that isn't 'open' (DATA_MODEL.md:
    an issue is raised open, resolved exactly once).
    """


def _generate_password() -> str:
    # secrets.token_urlsafe: CSPRNG, not `random` (ASVS 6.4.1's "securely random"). 16 bytes = 128
    # bits, well past the length policy in ARCHITECTURE.md §4.
    return secrets.token_urlsafe(16)


def _write_audit_log(session: Session, actor: Profile, action: str, target_id: UUID | None) -> None:
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
    if result.user is None:  # pyright: ignore[reportUnnecessaryComparison]
        # supabase_auth's stub types `.user` as non-optional, so pyright strict calls this
        # unreachable — kept anyway: a type stub describes the declared shape, not a runtime
        # guarantee from Supabase's actual HTTP response at this external API boundary.
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


def create_job_type(session: Session, actor: Profile, name: str) -> JobType:
    # Not audit-logged — job_types already carries created_by/created_at, and ARCHITECTURE.md's
    # audit_log scope note is explicit that anything with its own actor/timestamp columns (like
    # task_reviews/issues) isn't duplicated there; job_types follows the same reasoning.
    job_type = JobType(
        firm_id=actor.firm_id, name=name, created_by=actor.id, created_at=datetime.now(UTC)
    )
    session.add(job_type)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobTypeNameError from exc
    session.refresh(job_type)
    return job_type


def list_job_types(session: Session, offset: int, limit: int) -> list[JobType]:
    stmt = select(JobType).offset(offset).limit(limit)
    return list(session.exec(stmt).all())


def get_job_type(session: Session, job_type_id: UUID) -> JobType | None:
    return session.exec(select(JobType).where(JobType.id == job_type_id)).first()


def set_job_type_active(session: Session, job_type: JobType, is_active: bool) -> JobType:
    job_type.is_active = is_active
    session.add(job_type)
    session.commit()
    session.refresh(job_type)
    return job_type


def create_task(
    session: Session,
    actor: Profile,
    title: str,
    description: str | None,
    job_type_id: UUID | None,
    assigned_to: UUID | None,
    deadline: datetime | None,
) -> Task:
    """No `session.commit()` here — the caller wraps this in `with_idempotency`, which commits
    once for both this row and the idempotency-cache row (one atomic transaction, rest-api-
    guidelines Rule 230's "hard transaction semantics" requirement).
    """
    now = datetime.now(UTC)
    task = Task(
        firm_id=actor.firm_id,
        job_type_id=job_type_id,
        title=title,
        description=description,
        assigned_to=assigned_to,
        deadline=deadline,
        # PRD §4.1: Created and Assigned are distinct lifecycle steps — only skip straight to
        # 'assigned' if the Owner assigned it at creation time.
        status="assigned" if assigned_to else "created",
        created_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    return task


def list_tasks(
    session: Session,
    actor: Profile,
    offset: int,
    limit: int,
    status_filter: str | None,
    assigned_to_filter: UUID | None,
    job_type_id_filter: UUID | None,
    task_type_filter: str | None,
) -> list[Task]:
    """Role-scoped, not just filtered (API_SPEC.md): an Employee's results are always their own
    regardless of what they pass — the query filters below only apply for an Owner, since an
    Employee's results are already scoped to themselves (the same filters would be redundant).
    """
    stmt = select(Task)
    if actor.role == "owner":
        if status_filter is not None:
            stmt = stmt.where(Task.status == status_filter)
        if assigned_to_filter is not None:
            stmt = stmt.where(Task.assigned_to == assigned_to_filter)
        if job_type_id_filter is not None:
            stmt = stmt.where(Task.job_type_id == job_type_id_filter)
        if task_type_filter is not None:
            stmt = stmt.where(Task.task_type == task_type_filter)
    else:
        stmt = stmt.where(Task.assigned_to == actor.id)
    stmt = stmt.offset(offset).limit(limit)
    return list(session.exec(stmt).all())


def get_task(session: Session, actor: Profile, task_id: UUID) -> Task | None:
    """Employee access restricted to their own assigned tasks — returning None (not the row) for
    someone else's task is what makes the route's existing 404-not-403 pattern work unchanged
    (API_SPEC.md: an Employee requesting another's task by ID must 404, not 403).
    """
    task = session.exec(select(Task).where(Task.id == task_id)).first()
    if task is None:
        return None
    if actor.role != "owner" and task.assigned_to != actor.id:
        return None
    return task


def update_task_deadline(session: Session, task: Task, deadline: datetime) -> Task:
    task.deadline = deadline
    task.updated_at = datetime.now(UTC)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def _lock_task(session: Session, firm_id: UUID, task_id: UUID) -> Task:
    """Business_Logic_Security_Cheat_Sheet.md "Use Database Transactions and Locks" — checked
    directly 2026-09-04, not assumed covered by the Idempotency-Key mechanism (that only dedupes
    an identical retried key, not two genuinely concurrent requests with different keys, e.g. two
    tabs both clicking submit). `SELECT ... FOR UPDATE` — the cheat sheet's own first-listed
    pattern — makes the second racer block until the first commits, so it re-reads the *already
    updated* status instead of the stale value the route's earlier `get_task` fetched.
    """
    return session.exec(
        select(Task).where(Task.firm_id == firm_id, Task.id == task_id).with_for_update()
    ).one()


def submit_task(session: Session, task: Task) -> Task:
    """No `session.commit()` — wrapped in `with_idempotency` by the route, same reasoning as
    create_task.
    """
    locked = _lock_task(session, task.firm_id, task.id)
    if locked.status not in ("assigned", "in_progress"):
        raise InvalidTaskStateError
    locked.status = "submitted"
    locked.updated_at = datetime.now(UTC)
    session.add(locked)
    return locked


def mark_task_billed(session: Session, task: Task) -> Task:
    """No `session.commit()` — wrapped in `with_idempotency` by the route."""
    locked = _lock_task(session, task.firm_id, task.id)
    if locked.task_type != "billing" or locked.status not in ("assigned", "in_progress"):
        raise InvalidTaskStateError
    locked.status = "billed"
    locked.updated_at = datetime.now(UTC)
    session.add(locked)
    return locked


def _reassign_task(
    task: Task,
    source: str,
    notes: str | None,
    remaining_work: str | None,
    assigned_to: UUID | None,
) -> None:
    """DATA_MODEL.md's explicit convergence: a review-triggered reassignment and an issue-
    resolution reassignment update `tasks` through this one path (the same four
    `last_reassignment_*` columns) — what makes PRD's 'two distinct triggers, same employee
    notification' requirement (§3.3/§4.3) fall out of one code path instead of two.
    """
    now = datetime.now(UTC)
    task.status = "in_progress"
    task.last_reassignment_notes = notes
    task.last_reassignment_remaining_work = remaining_work
    task.last_reassignment_source = source
    task.last_reassignment_at = now
    task.updated_at = now
    if assigned_to is not None:
        task.assigned_to = assigned_to


def create_task_review(
    session: Session,
    actor: Profile,
    task: Task,
    outcome: str,
    notes: str | None,
    remaining_work_description: str | None,
    assigned_to: UUID | None,
    billing_deadline: datetime | None,
    billing_description: str | None,
    billing_amount: float | None,
    billing_recipient: str | None,
) -> tuple[TaskReview, Task]:
    """No `session.commit()` — wrapped in `with_idempotency` by the route. Row-locks the reviewed
    task (Business_Logic_Security_Cheat_Sheet.md, same reasoning as submit_task/mark_task_billed)
    so two concurrent reviews of the same submission can't both succeed. Outcome-specific field
    requirements (e.g. `remaining_work_description` required for 'reassigned') are enforced by the
    request body's own validator (routes/tasks.py) — cheat sheet's "Validate Combinations": fields
    individually valid but only meaningful together per outcome.
    """
    locked = _lock_task(session, task.firm_id, task.id)
    if locked.status != "submitted":
        raise InvalidTaskStateError

    now = datetime.now(UTC)
    review = TaskReview(
        firm_id=actor.firm_id,
        task_id=locked.id,
        reviewed_by=actor.id,
        outcome=outcome,
        notes=notes,
        created_at=now,
    )

    if outcome == "approved":
        locked.status = "completed"
        locked.updated_at = now
    elif outcome == "reassigned":
        review.remaining_work_description = remaining_work_description
        _reassign_task(locked, "review", notes, remaining_work_description, assigned_to)
    else:  # billing
        locked.status = "completed"
        locked.updated_at = now
        billing_task = Task(
            firm_id=actor.firm_id,
            job_type_id=locked.job_type_id,
            task_type="billing",
            parent_task_id=locked.id,
            title=f"Billing — {locked.title}",
            description=billing_description,
            assigned_to=assigned_to,
            deadline=billing_deadline,
            status="assigned",
            created_by=actor.id,
            created_at=now,
            updated_at=now,
            billing_amount=billing_amount,
            billing_recipient=billing_recipient,
        )
        session.add(billing_task)
        session.flush()  # assigns billing_task.id within the still-open transaction
        review.resulting_billing_task_id = billing_task.id

    session.add(locked)
    session.add(review)
    return review, locked


def create_issue(session: Session, actor: Profile, task: Task, description: str) -> Issue:
    """No `session.commit()` — wrapped in `with_idempotency` by the route. Not row-locked: raising
    an issue doesn't mutate `tasks` (PRD §2.7/§4.3), so there's no check-then-act write for a
    concurrent submit/review to race against — worst case is an issue landing a moment either side
    of a submission, which isn't an invalid state, just an ordering choice.
    """
    if task.status not in ("assigned", "in_progress"):
        raise InvalidTaskStateError
    issue = Issue(
        firm_id=actor.firm_id,
        task_id=task.id,
        raised_by=actor.id,
        description=description,
        status="open",
        created_at=datetime.now(UTC),
    )
    session.add(issue)
    return issue


def get_issue(session: Session, issue_id: UUID) -> Issue | None:
    return session.exec(select(Issue).where(Issue.id == issue_id)).first()


def _lock_issue(session: Session, firm_id: UUID, issue_id: UUID) -> Issue:
    """Same reasoning as `_lock_task` — two concurrent resolutions of the same issue must not
    both succeed.
    """
    return session.exec(
        select(Issue).where(Issue.firm_id == firm_id, Issue.id == issue_id).with_for_update()
    ).one()


def resolve_issue(
    session: Session,
    actor: Profile,
    issue: Issue,
    resolution_type: str,
    resolution_notes: str,
    new_deadline: datetime | None,
    assigned_to: UUID | None,
) -> Issue:
    """No `session.commit()` — wrapped in `with_idempotency` by the route.
    ponytail: `issues` has no `remaining_work_description` column (DATA_MODEL.md) — an issue-
    triggered reassignment sets `tasks.last_reassignment_remaining_work` to None, unlike a review-
    triggered one. Add the column if/when this proves to be a real gap in practice, not
    speculatively now.
    """
    locked = _lock_issue(session, issue.firm_id, issue.id)
    if locked.status != "open":
        raise InvalidIssueStateError

    now = datetime.now(UTC)
    locked.status = "resolved"
    locked.resolution_type = resolution_type
    locked.resolution_notes = resolution_notes
    locked.resolved_by = actor.id
    locked.resolved_at = now

    if resolution_type in ("deadline_adjusted", "reassigned"):
        task = _lock_task(session, locked.firm_id, locked.task_id)
        if resolution_type == "deadline_adjusted":
            task.deadline = new_deadline
            task.updated_at = now
        else:  # reassigned — DATA_MODEL.md's convergence: same path as a review reassignment
            _reassign_task(task, "issue", resolution_notes, None, assigned_to)
        session.add(task)

    session.add(locked)
    return locked
