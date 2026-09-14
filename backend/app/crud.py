"""DB read/write logic — routes stay thin (fastapi/project-structure.md). Every function here
trusts `session` to already have `app.current_tenant` set (get_current_profile, api/deps.py) — RLS
is the primary tenant-isolation guarantee. Every plain getter/lister *also* filters by
`actor.firm_id` explicitly, belt-and-suspenders (same reasoning `_validate_assignee`/
`_validate_job_type` already used) — not because RLS is distrusted, but because
`Multi_Tenant_Security_Cheat_Sheet.md` ("implement authorization checks at the data access layer,
not just API layer") and `postgres-multitenant/schema-design.md` ("RLS is not a substitute for
application-level checks"; pooled-connection session-variable leakage on a forgotten/skipped `SET`
is "the single most common way RLS setups fail in production") both treat single-layer isolation as
a documented anti-pattern, not a valid trade-off. Policy changed 2026-09-14 (code review finding
#6) — the prior version of this docstring deliberately called RLS "the single source of truth";
that trade-off is no longer the project's stance.

That trust holds only within the one transaction get_current_profile's `set_config(..., true)` set
it in — `true` (is_local) means it's transaction-scoped, deliberately, so a pooled connection can
never carry one request's tenant context into another's. A function that calls `session.commit()`
mid-request and then queries again afterward runs that later query with no tenant context at all
(found via Schemathesis, 2026-09-08, docs/SECURITY_AUDIT_CHECKLIST.md) — either 0 rows or a raw
uuid-cast crash, depending on whether the pooled connection had seen a tenant context before. Fixed
at the two shapes this takes: a stale post-commit `session.refresh()` (delete it — see
`get_session`'s `expire_on_commit=False`, app/core/db.py) or a real post-commit query that needs the
tenant context regenerated explicitly after a conflict rollback — `core.db.commit_or_recover`,
consolidated there 2026-09-10 after this exact recovery shape was independently reimplemented
(minus the fix) by a 2nd call site (`core/idempotency.py`). Use that helper, don't hand-roll this
again — see its own docstring.
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.db import commit_or_recover
from app.core.supabase_admin import admin_auth
from app.models import (
    AccessDenial,
    AuditLog,
    Issue,
    JobType,
    Notification,
    Profile,
    Task,
    TaskReview,
)

logger = logging.getLogger(__name__)


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


class UnknownAssigneeError(Exception):
    """Raised when a request-body `assigned_to` doesn't resolve to an active employee of the
    caller's own firm — Business_Logic_Security_Cheat_Sheet.md's "Never accept a user ID... from
    the request body unless the request is explicitly an administrative action by a privileged
    caller, and even then the value has to be validated against what the caller is allowed to
    manage" (checked fresh this pass, Phase 3 audit). Previously this was left entirely to the
    `tasks`/`issues` tables' own `(firm_id, assigned_to) REFERENCES profiles` composite FK — real
    tenant-boundary enforcement, but a raw `IntegrityError` on violation surfaces as a generic 500
    (main.py's catch-all handler), not a clean 4xx, and the FK alone doesn't stop an Owner assigning
    work to a fellow Owner or a deactivated employee, neither of which can ever act on it.
    """


class UnknownJobTypeError(Exception):
    """Raised when a request-body `job_type_id` doesn't resolve to an active job type of the
    caller's own firm — same reasoning as `UnknownAssigneeError` just above, and the same gap:
    previously left entirely to `tasks`'s own `(firm_id, job_type_id) REFERENCES job_types`
    composite FK, so a nonexistent id crashed with a raw `ForeignKeyViolation` (a generic 500 via
    main.py's catch-all handler) instead of a clean 4xx — found by Schemathesis, 2026-09-08,
    docs/SECURITY_AUDIT_CHECKLIST.md.
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


def record_access_denial(
    session: Session,
    actor: Profile,
    resource_type: str | None,
    resource_id: UUID | None,
    reason: str,
) -> None:
    """DATA_MODEL.md `access_denials` — records only what's actually visible to the app: same-
    tenant IDOR (`wrong_owner`) and role-gate (`wrong_role`/`not_assignee`) denials. A true cross-
    tenant attempt never reaches here — RLS filters it out before the caller can even tell the
    resource exists (see the table's own "structural limit" note).

    Commits itself, unlike `_write_audit_log` — every call site here is immediately followed by
    request termination (a 404/403 raised right after), never a larger business-write transaction
    to ride along with, and several call sites (get_task/get_notification) are read-only routes
    that would otherwise never call session.commit() at all before the session closes and the
    uncommitted row is silently rolled back.
    """
    session.add(
        AccessDenial(
            firm_id=actor.firm_id,
            actor_id=actor.id,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()


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
    try:
        session.commit()
    except Exception:
        # The Supabase Auth user above already exists — this local commit isn't in the same
        # transaction as that external call, so its failure can't roll the auth user back.
        # Compensating action (found missing in code review, 2026-09-14 — see
        # Business_Logic_Security_Cheat_Sheet.md's "external non-idempotent call" guidance):
        # delete the now-orphaned auth user rather than leave a Supabase account with no local
        # profile, permanently consuming that email with no way to ever sign in. Best-effort —
        # if the delete itself fails, the orphan is a known, logged trade-off, not a silent one.
        # Exempt from commit_or_recover like create_job_type's rollback below: raises immediately
        # after, no further session read, so no expired-attribute/lost-tenant-context risk.
        session.rollback()  # nosemgrep: hand-rolled-rollback-outside-commit-or-recover
        try:
            admin_auth.delete_user(str(new_id))
        except Exception:
            logger.exception(
                "Failed to compensate for a failed employee-creation commit — "
                "Supabase Auth user %s is now orphaned (no local profile)",
                new_id,
            )
        raise
    return new_id, password


def list_employees(
    session: Session, actor: Profile, offset: int, limit: int
) -> list[tuple[Profile, int]]:
    """Returns (employee, pending_job_count) pairs — PRD §2.4's workload count, deliberately
    omitted when this function was first written (Phase 1, before `tasks` existed — see the
    route's own prior comment, now removed). One query, not N+1: `tests/crud/test_query_counts.py`
    already guards this function at exactly one query regardless of row count, re-verified this
    pass still holds with the added subquery+outerjoin (a single query's own internal join, not an
    extra round-trip). "Pending" = assigned/in_progress, the same two statuses `submit_task`
    treats as the task's active-work window (crud.submit_task's own status check).
    """
    workload = (
        select(
            col(Task.assigned_to).label("employee_id"),  # type: ignore[reportUnknownArgumentType] — known SQLModel/pyright interaction, same as models.py's __tablename__ ignores
            func.count(col(Task.id)).label("pending_count"),
        )
        .where(col(Task.status).in_(("assigned", "in_progress")))
        .group_by(col(Task.assigned_to))
        .subquery()
    )
    stmt = (
        select(Profile, func.coalesce(workload.c.pending_count, 0))
        .where(Profile.role == "employee", Profile.firm_id == actor.firm_id)
        .outerjoin(workload, workload.c.employee_id == col(Profile.id))
        .order_by(col(Profile.created_at).desc(), col(Profile.id))
        .offset(offset)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in session.exec(stmt).all()]


def get_employee(session: Session, actor: Profile, employee_id: UUID) -> Profile | None:
    return session.exec(
        select(Profile).where(
            Profile.id == employee_id,
            Profile.role == "employee",
            Profile.firm_id == actor.firm_id,
        )
    ).first()


def _validate_assignee(session: Session, firm_id: UUID, employee_id: UUID) -> None:
    """See `UnknownAssigneeError`. Scoped to `firm_id` explicitly (not just relying on RLS's
    `app.current_tenant`) since the caller is always the acting Owner's own firm_id here — belt
    and suspenders with the DB's own composite FK, not a replacement for it.
    """
    employee = session.exec(
        select(Profile).where(
            Profile.firm_id == firm_id, Profile.id == employee_id, Profile.role == "employee"
        )
    ).first()
    if employee is None or not employee.is_active:
        raise UnknownAssigneeError


def _validate_job_type(session: Session, firm_id: UUID, job_type_id: UUID) -> None:
    """See `UnknownJobTypeError`. Scoped to `firm_id` explicitly — same belt-and-suspenders
    reasoning as `_validate_assignee` just above.
    """
    job_type = session.exec(
        select(JobType).where(JobType.firm_id == firm_id, JobType.id == job_type_id)
    ).first()
    if job_type is None or not job_type.is_active:
        raise UnknownJobTypeError


def set_employee_active(
    session: Session, actor: Profile, employee: Profile, is_active: bool
) -> Profile:
    employee.is_active = is_active
    session.add(employee)
    action = "employee_reactivated" if is_active else "employee_deactivated"
    _write_audit_log(session, actor, action=action, target_id=employee.id)
    session.commit()
    # No session.refresh() — see create_job_type's comment; same reasoning applies here.
    return employee


def reset_employee_password(session: Session, actor: Profile, employee: Profile) -> str:
    """Generates a new password via the Admin API and marks it one-time-use, same as
    create_employee — `must_change_password` lives only in `profiles`, so it's a plain update
    here, not another Admin API call (ARCHITECTURE.md §4).

    No `session.commit()` — the route (routes/employees.py) checks for an existing
    `IdempotencyKey` row *before* calling this function at all (so a genuine retry never reaches
    `admin_auth.update_user_by_id` a second time), then commits this function's writes together
    with its own redacted `IdempotencyKey` insert in one transaction. Not the shared
    `with_idempotency` helper — that one caches and replays the exact response body, which would
    persist this one-time password past its single intended transmission (API_SPEC.md §3).

    Row-locks `employee` first (`Business_Logic_Security_Cheat_Sheet.md`'s "Use Database
    Transactions and Locks", same reasoning as `_lock_task`/`_lock_issue`) — the Idempotency-Key
    dedup check is keyed on `(firm_id, actor_id, key, endpoint)`, not on `employee_id`, so it
    doesn't stop two *different* keys hitting reset-password for the *same* employee
    concurrently. Locking before the Admin API call, not after, makes the second caller block
    until the first has fully finished (including its own Supabase call and commit) — so
    whichever response comes back always reflects the password that's actually live, instead of
    a caller occasionally receiving a password a second, later-committing call already overwrote.

    `populate_existing=True` on the lock query is required for the same reason as `_lock_task`:
    the route calls `get_employee` (unlocked) before this, so without it SQLAlchemy would return
    the caller's stale cached `Profile` instead of the fresh post-lock row.
    """
    locked = session.exec(
        select(Profile)
        .where(Profile.firm_id == employee.firm_id, Profile.id == employee.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()

    password = _generate_password()
    admin_auth.update_user_by_id(str(locked.id), {"password": password})

    now = datetime.now(UTC)
    locked.must_change_password = True
    locked.last_reset_by = actor.id
    locked.last_reset_at = now
    session.add(locked)
    _write_audit_log(session, actor, action="password_reset", target_id=locked.id)
    return password


def _notify(
    session: Session,
    firm_id: UUID,
    recipient_id: UUID,
    notif_type: str,
    task_id: UUID | None,
    issue_id: UUID | None,
) -> None:
    """DATA_MODEL.md §2: recipient_id is always exactly one profile (never broadcast). No
    `session.commit()` here — every call site adds this alongside its own real write, in the same
    transaction (ASVS 2.3.3), never as a standalone commit.
    """
    session.add(
        Notification(
            firm_id=firm_id,
            recipient_id=recipient_id,
            type=notif_type,
            task_id=task_id,
            issue_id=issue_id,
            is_read=False,
            created_at=datetime.now(UTC),
        )
    )


def _notify_owners(
    session: Session,
    firm_id: UUID,
    notif_type: str,
    task_id: UUID | None,
    issue_id: UUID | None,
) -> None:
    owners = session.exec(
        select(Profile).where(Profile.firm_id == firm_id, Profile.role == "owner")
    ).all()
    for owner in owners:
        _notify(session, firm_id, owner.id, notif_type, task_id, issue_id)


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
        # Safe outside commit_or_recover (core/db.py): raises immediately, never reads the
        # session again — doesn't need tenant context re-established.
        session.rollback()  # nosemgrep: hand-rolled-rollback-outside-commit-or-recover
        raise DuplicateJobTypeNameError from exc
    # No session.refresh() — every field here is set in Python above, nothing is DB-computed, and
    # get_session's expire_on_commit=False means this object's attributes are already the
    # authoritative just-written values (app/core/db.py). A refresh would re-query job_types right
    # after commit ended the transaction that held the RLS tenant context — see that comment.
    return job_type


def list_job_types(session: Session, actor: Profile, offset: int, limit: int) -> list[JobType]:
    # Deterministic pagination — same non-deterministic-offset/limit bug already fixed on
    # list_tasks, backported here (code-review finding, whole-Phase-4 sweep, 2026-09-13).
    stmt = (
        select(JobType)
        .where(JobType.firm_id == actor.firm_id)
        .order_by(col(JobType.created_at).desc(), col(JobType.id))
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def get_job_type(session: Session, actor: Profile, job_type_id: UUID) -> JobType | None:
    return session.exec(
        select(JobType).where(JobType.id == job_type_id, JobType.firm_id == actor.firm_id)
    ).first()


def set_job_type_active(session: Session, job_type: JobType, is_active: bool) -> JobType:
    job_type.is_active = is_active
    session.add(job_type)
    session.commit()
    # No session.refresh() — see create_job_type's comment; same reasoning applies here.
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
    if assigned_to is not None:
        _validate_assignee(session, actor.firm_id, assigned_to)
    if job_type_id is not None:
        _validate_job_type(session, actor.firm_id, job_type_id)
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
    if assigned_to is not None:
        # PRD §3.4 / DATA_MODEL.md §5 `task_assigned` — only fires when assignment happens at
        # creation time; a task created unassigned and assigned later has no PATCH endpoint yet
        # (API_SPEC.md doesn't define one), so that path doesn't exist to notify from.
        _notify(session, actor.firm_id, assigned_to, "task_assigned", task.id, None)
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
    stmt = select(Task).where(Task.firm_id == actor.firm_id)
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
    # Deterministic order, same pattern as list_notifications' own .order_by (crud.py:827) — found
    # by an independent code-review pass (2026-09-13): without this, Postgres has no ordering
    # guarantee at all, so which rows land in a `limit`-bounded page (and in what order) could
    # silently vary between requests. `.id` is the tiebreaker for rows sharing a `created_at`.
    # Deterministic order, same pattern as list_notifications' own .order_by (crud.py:827) — found
    # by an independent code-review pass (2026-09-13): without this, Postgres has no ordering
    # guarantee at all, so which rows land in a `limit`-bounded page (and in what order) could
    # silently vary between requests. `.id` is the tiebreaker for rows sharing a `created_at`.
    stmt = stmt.order_by(col(Task.created_at).desc(), col(Task.id)).offset(offset).limit(limit)
    return list(session.exec(stmt).all())


def get_task(session: Session, actor: Profile, task_id: UUID) -> Task | None:
    """Employee access restricted to their own assigned tasks — returning None (not the row) for
    someone else's task is what makes the route's existing 404-not-403 pattern work unchanged
    (API_SPEC.md: an Employee requesting another's task by ID must 404, not 403).
    """
    task = session.exec(
        select(Task).where(Task.id == task_id, Task.firm_id == actor.firm_id)
    ).first()
    if task is None:
        return None
    if actor.role != "owner" and task.assigned_to != actor.id:
        record_access_denial(session, actor, "task", task.id, "wrong_owner")
        return None
    return task


def update_task_deadline(session: Session, task: Task, deadline: datetime) -> Task:
    task.deadline = deadline
    task.updated_at = datetime.now(UTC)
    session.add(task)
    session.commit()
    # No session.refresh() — see create_job_type's comment; same reasoning applies here.
    return task


def _lock_task(session: Session, firm_id: UUID, task_id: UUID) -> Task:
    """Business_Logic_Security_Cheat_Sheet.md "Use Database Transactions and Locks" — checked
    directly 2026-09-04, not assumed covered by the Idempotency-Key mechanism (that only dedupes
    an identical retried key, not two genuinely concurrent requests with different keys, e.g. two
    tabs both clicking submit). `SELECT ... FOR UPDATE` — the cheat sheet's own first-listed
    pattern — makes the second racer block at the database level until the first commits.

    `populate_existing=True` is required, not optional decoration: the route always calls
    `get_task` (unlocked) before this, so this session's identity map already holds a Python
    `Task` object for this PK. Without this option, SQLAlchemy silently returns that cached,
    stale object instead of the fresh post-lock row this query just fetched — the database lock
    still works, but the Python code making the decision never sees its result. Found
    2026-09-07 via a real-Postgres concurrency test (`tests/crud/test_concurrency.py`) after the
    original version of this function (without this option) let two concurrent submits both
    succeed; verified 5/5 clean runs after adding it. Same fix applied to `_lock_issue` and
    `reset_employee_password`'s inline lock below, which have the identical vulnerable shape.
    """
    return session.exec(
        select(Task)
        .where(Task.firm_id == firm_id, Task.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
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
    _notify_owners(session, locked.firm_id, "task_submitted", locked.id, None)
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
    session: Session,
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
    # Notify whoever the task actually lands on now — the same or a different employee, since
    # PRD §3.3 requires the assignee to see reassigned work regardless of which trigger path.
    if task.assigned_to is not None:
        _notify(session, task.firm_id, task.assigned_to, "task_reassigned", task.id, None)


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
    if assigned_to is not None:
        _validate_assignee(session, actor.firm_id, assigned_to)

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
        _reassign_task(session, locked, "review", notes, remaining_work_description, assigned_to)
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
    _notify_owners(session, actor.firm_id, "issue_raised", task.id, issue.id)
    return issue


def get_issue(session: Session, actor: Profile, issue_id: UUID) -> Issue | None:
    return session.exec(
        select(Issue).where(Issue.id == issue_id, Issue.firm_id == actor.firm_id)
    ).first()


def _lock_issue(session: Session, firm_id: UUID, issue_id: UUID) -> Issue:
    """Same reasoning as `_lock_task` — two concurrent resolutions of the same issue must not
    both succeed. `populate_existing=True` is required, not optional decoration: the route
    always calls `get_issue` (unlocked) before this, so this session's identity map already
    holds a Python `Issue` object for this PK — without this option, SQLAlchemy returns that
    cached object instead of the fresh, post-lock row this query just fetched, silently
    discarding the lock's entire purpose (verified against real Postgres, not assumed;
    see `_lock_task`'s docstring/SECURITY_AUDIT_CHECKLIST.md).
    """
    return session.exec(
        select(Issue)
        .where(Issue.firm_id == firm_id, Issue.id == issue_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def resolve_issue(
    session: Session,
    actor: Profile,
    issue: Issue,
    resolution_type: str,
    resolution_notes: str,
    remaining_work_description: str | None,
    new_deadline: datetime | None,
    assigned_to: UUID | None,
) -> Issue:
    """No `session.commit()` — wrapped in `with_idempotency` by the route. PRD §3.3: an issue-
    triggered reassignment must surface both `last_reassignment_notes` and
    `last_reassignment_remaining_work`, same as a review-triggered one — `remaining_work_
    description` (routes/issues.py's own request-body validator requires it when
    resolution_type='reassigned') is what makes that possible, mirroring task_reviews'.
    """
    locked = _lock_issue(session, issue.firm_id, issue.id)
    if locked.status != "open":
        raise InvalidIssueStateError
    if assigned_to is not None:
        _validate_assignee(session, actor.firm_id, assigned_to)

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
            locked.remaining_work_description = remaining_work_description
            _reassign_task(
                session, task, "issue", resolution_notes, remaining_work_description, assigned_to
            )
        session.add(task)

    session.add(locked)

    # Code-review finding (whole-Phase-4 sweep, 2026-09-13): resolving an issue never marked its
    # originating issue_raised notification read, so the Owner Dashboard's Issues Raised panel
    # (driven by GET /notifications) showed it forever. Bulk mark-read, same transaction as the
    # resolution itself — no separate commit (this function's own docstring rule).
    stale_notifications = session.exec(
        select(Notification).where(
            Notification.issue_id == locked.id,
            Notification.type == "issue_raised",
            col(Notification.is_read).is_(False),
        )
    ).all()
    for stale in stale_notifications:
        stale.is_read = True
        session.add(stale)

    return locked


_ACTIVE_TASK_STATUSES = ("created", "assigned", "in_progress", "submitted")
_APPROACHING_WINDOW = timedelta(days=3)  # PRD §3.4 names no number for "approaching" — judgment
_URGENT_WINDOW = timedelta(days=1)  # PRD §2.5's own explicit "1 day from deadline"
_DEADLINE_NOTIF_TYPES = (
    "task_overdue",
    "task_deadline_1_day",
    "task_deadline_approaching",
    "task_overdue_own",
)


def _as_aware_utc(value: datetime) -> datetime:
    """Postgres' `timestamptz` round-trips as tz-aware via psycopg, but don't trust that blindly —
    SQLite (this project's own test backend) drops tzinfo on round-trip, and a naive-vs-aware
    comparison raises a raw `TypeError`, not a clean 500. Caught by tests/crud/test_notifications.py
    actually running this comparison against a real fetched row, not a mock.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _due_deadline_notifications(
    task: Task, now: datetime, owner_ids: list[UUID]
) -> list[tuple[UUID, str, UUID]]:
    """Every (recipient, type, task_id) this one task warrants right now — owners get
    `task_overdue` / `task_deadline_1_day`, the assignee gets `task_overdue_own` /
    `task_deadline_approaching`. Pure: dedup and persistence are the caller's job.
    """
    if task.deadline is None:  # caller's query already filters this; narrows the type here
        return []
    deadline = _as_aware_utc(task.deadline)
    overdue = deadline < now
    due: list[tuple[UUID, str, UUID]] = []
    for owner_id in owner_ids:
        if overdue:
            due.append((owner_id, "task_overdue", task.id))
        elif deadline <= now + _URGENT_WINDOW:
            due.append((owner_id, "task_deadline_1_day", task.id))
    if task.assigned_to is not None:
        if overdue:
            due.append((task.assigned_to, "task_overdue_own", task.id))
        elif deadline <= now + _APPROACHING_WINDOW:
            due.append((task.assigned_to, "task_deadline_approaching", task.id))
    return due


def _scan_firm_deadlines(session: Session, firm_id: UUID, now: datetime) -> None:
    """Firm-wide deadline scan — generates every time-based notification currently due for this
    firm (see `_due_deadline_notifications` for the per-task rules). Adds rows to the session; the
    caller commits.

    Firm-scoped and actor-independent on purpose. Today `list_notifications` runs it for the
    poller's own firm on every GET (there's no scheduler — ARCHITECTURE.md §8/§10). It is written
    as the exact unit a future scheduled job would call once per firm: when that job exists,
    `GET /notifications` drops this call and becomes a pure read, and the rest-api-guidelines
    Rule 149 deviation goes away with it — no rewrite of this function.

    A consequence of being firm-wide rather than per-poller: an assignee's own-task notifications
    are generated by *any* firm member's poll, not only their own — an employee who hasn't opened
    the app still accrues them (matches PRD §3.4, and matches what the future scheduler would do).

    Dedup key is (recipient, type, task_id): each task fires each type at most once per recipient,
    ever. One bulk SELECT of the already-generated keys up front — not one per (task, recipient),
    so the scan is O(tasks), not O(tasks x owners). `ix_notifications_dedup`'s partial UNIQUE
    index is still the real backstop for two polls racing; the in-memory set only narrows the
    window. ponytail: a deadline change after a type already fired doesn't re-fire it until the
    row is cleared — revisit with a deadline-aware key if that's ever a real complaint.
    """
    tasks = session.exec(
        select(Task).where(
            Task.firm_id == firm_id,
            col(Task.deadline).is_not(None),
            col(Task.status).in_(_ACTIVE_TASK_STATUSES),
        )
    ).all()
    if not tasks:
        return
    owner_ids = [
        owner.id
        for owner in session.exec(
            select(Profile).where(Profile.firm_id == firm_id, Profile.role == "owner")
        ).all()
    ]
    task_ids = [task.id for task in tasks]
    already: set[tuple[UUID, str, UUID]] = {
        (row.recipient_id, row.type, row.task_id)
        for row in session.exec(
            select(Notification).where(
                Notification.firm_id == firm_id,
                col(Notification.task_id).in_(task_ids),
                col(Notification.type).in_(_DEADLINE_NOTIF_TYPES),
            )
        ).all()
        if row.task_id is not None
    }

    for task in tasks:
        for key in _due_deadline_notifications(task, now, owner_ids):
            if key not in already:
                _notify(session, firm_id, key[0], key[1], key[2], None)
                already.add(key)


def _ensure_deadline_notifications(session: Session, actor: Profile) -> None:
    """No scheduler generates the 4 time-based notification types (ARCHITECTURE.md §10 rules out a
    task queue this phase); `GET /notifications` runs `_scan_firm_deadlines` itself on every poll,
    since the frontend already polls every 30-60s (ARCHITECTURE.md §8) — no new infra.

    Deliberate, documented deviation from rest-api-guidelines Rule 149 ("GET must be safe — no
    server-state side effects"): the alternatives (external cron, in-process APScheduler) add
    deployment complexity not justified at the current target (2-4 firms, ~30 users —
    ca-tool-project-scope). `_scan_firm_deadlines` is deliberately shaped so this becomes a pure
    read the day a scheduled job takes the scan over. The write is bounded by the dedup key, so a
    read-only client still can't trigger unbounded writes.

    Checked against Business_Logic_Security_Cheat_Sheet.md "Resource exhaustion" / owasp-asvs-5
    V2.4.1 (anti-automation), confirmed 2026-09-05, still holds: §1's Cloudflare-edge rate limiting
    covers this endpoint, the scan is 3 indexed firm-scoped queries (not per-item-expensive), and
    the dedup key bounds row growth from repeated polls. Not a gap.
    """
    _scan_firm_deadlines(session, actor.firm_id, datetime.now(UTC))
    # Two near-simultaneous polls (ARCHITECTURE.md §8: every 30-60s) can both find the same
    # deadline notification "missing" and both try to insert it — ix_notifications_dedup's partial
    # UNIQUE index (see its migration) is what makes that a real DB conflict (IntegrityError)
    # instead of a silent duplicate row. commit_or_recover (core/db.py) commits, and on that
    # conflict rolls back + re-establishes tenant context for list_notifications' query right after
    # this call returns — no on_conflict callback needed: whichever request loses just accepts the
    # rollback, since the other request's commit already created every notification this one would
    # have, and anything genuinely still missing gets picked up by this same scan on the next poll
    # (losing one cycle changes nothing about correctness).
    commit_or_recover(session, actor)


def list_notifications(
    session: Session, actor: Profile, offset: int, limit: int, unread_only: bool
) -> list[Notification]:
    """Always filtered to the caller's own `recipient_id` (API_SPEC.md — never a client-supplied
    parameter, since that's the schema-level 'never broadcast' guarantee)."""
    _ensure_deadline_notifications(session, actor)
    stmt = select(Notification).where(Notification.recipient_id == actor.id)
    if unread_only:
        stmt = stmt.where(col(Notification.is_read).is_(False))
    # `.id` tiebreaker — same reasoning as list_tasks/list_job_types/list_employees: `created_at`
    # gives no ordering guarantee among rows sharing the same timestamp, so without it a row can be
    # silently skipped or duplicated across pages (found missing here in code review, 2026-09-14 —
    # the siblings' own comments claimed to copy this function's pattern; this one never had it).
    stmt = (
        stmt.order_by(col(Notification.created_at).desc(), col(Notification.id))
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def get_notification(
    session: Session, actor: Profile, notification_id: UUID
) -> Notification | None:
    """Returns None for another recipient's notification — same 404-not-403 pattern as
    get_task/get_job_type (IDOR: don't confirm the id exists to someone it doesn't belong to).
    """
    notification = session.exec(
        select(Notification).where(Notification.id == notification_id)
    ).first()
    if notification is None:
        return None
    if notification.recipient_id != actor.id:
        record_access_denial(session, actor, "notification", notification.id, "wrong_owner")
        return None
    return notification


def mark_notification_read(session: Session, notification: Notification) -> Notification:
    notification.is_read = True
    session.add(notification)
    session.commit()
    # No session.refresh() — see create_job_type's comment; same reasoning applies here.
    return notification
