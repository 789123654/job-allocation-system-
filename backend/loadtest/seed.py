"""Seeds N firms (each 1 owner + K employees, M tasks with a mixed status/deadline spread) directly
via MIGRATIONS_DATABASE_URL — bypasses RLS, same admin-engine pattern as
tests/api/test_schema_fuzz.py's owner_token fixture — then mints one JWT per seeded profile, signed
with generate_keys.py's private key, and writes identities.json for script.js to read.

Unlike owner_token, nothing here tears down: this data is meant to persist for the whole load-test
run. Rerunning against the same disposable Postgres without dropping/recreating it first creates
duplicate firms — fine for a throwaway loadtest container, never point MIGRATIONS_DATABASE_URL at
anything else.

must_change_password=false is set explicitly on every seeded profile, same as owner_token — the DB
column defaults to true (models.py), and require_password_set (api/deps.py) 403s every other
request while it's true; leaving it at the default would make every load-test request fail at the
auth gate before reaching any of the code actually under test.

Each identity also gets a `foreign_task_id` (2026-09-17 addition) — a real task id belonging to a
DIFFERENT firm, so script.js can assert cross-tenant access actually 404s under real concurrency,
not just measure latency on each caller's own data.

2026-09-18 addition: one `job_types` row and one `notifications` row seeded per firm — PATCH
/job-types/{id} and PATCH /notifications/{id}/read need a real write target, unlike the read-only
endpoints above. `foreign_job_type_id`/`foreign_notification_id` per identity, same
rejection-sampling pattern as `foreign_task_id`.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

_HERE = Path(__file__).parent
_KID = "loadtest-key-1"  # must match generate_keys.py's _KID exactly — see that file's comment.

_TASK_STATUSES = ("created", "assigned", "in_progress", "submitted", "completed", "billed")


def _seed(conn: Connection, firms: int, employees_per_firm: int, tasks_per_firm: int) -> list[dict]:
    identities: list[dict] = []
    firm_rows: list[dict] = []
    profile_rows: list[dict] = []
    task_rows: list[dict] = []
    job_type_rows: list[dict] = []
    notification_rows: list[dict] = []
    # firm_id -> [task_id, ...], client-generated below (not DB-returned) so script.js's
    # cross-tenant probe (2026-09-17 addition) has a real task id it KNOWS belongs to a different
    # firm than the requester, without an extra round-trip or RETURNING clause.
    tasks_by_firm: dict[object, list[object]] = {}
    # One-per-firm (not lists — PATCH /job-types/{id} and PATCH /notifications/{id}/read only need
    # a single real write target each, unlike tasks_by_firm above).
    job_type_by_firm: dict[object, object] = {}
    notification_by_firm: dict[object, object] = {}
    now = datetime.now(UTC)

    for _ in range(firms):
        firm_id = uuid4()
        firm_rows.append({"id": firm_id})

        owner_id = uuid4()
        profile_rows.append(
            {
                "id": owner_id,
                "fid": firm_id,
                "role": "owner",
                "email": f"{owner_id}@loadtest.example",
            }
        )
        identities.append(
            {"firm_id": str(firm_id), "profile_id": str(owner_id), "role": "owner"}
        )

        employee_ids: list[object] = []
        for _ in range(employees_per_firm):
            emp_id = uuid4()
            profile_rows.append(
                {
                    "id": emp_id,
                    "fid": firm_id,
                    "role": "employee",
                    "email": f"{emp_id}@loadtest.example",
                }
            )
            employee_ids.append(emp_id)
            identities.append(
                {"firm_id": str(firm_id), "profile_id": str(emp_id), "role": "employee"}
            )

        firm_task_ids: list[object] = []
        for _ in range(tasks_per_firm):
            # Mixed spread so _ensure_owner_deadline_notifications/_ensure_employee_deadline_
            # notifications (crud.py) have real overdue/urgent/approaching/far-future/none cases to
            # generate notifications from on each seeded user's first poll — the exact lazy-
            # generation path GET /notifications exercises in real usage (crud.py:747-761).
            deadline = None
            roll = random.random()
            if roll < 0.2:
                deadline = now - timedelta(days=random.randint(1, 5))  # overdue
            elif roll < 0.4:
                deadline = now + timedelta(hours=random.randint(1, 20))  # urgent (<1 day)
            elif roll < 0.6:
                deadline = now + timedelta(days=random.randint(1, 3))  # approaching
            elif roll < 0.8:
                deadline = now + timedelta(days=random.randint(10, 30))  # far future
            # else: no deadline (20%)
            status = random.choice(_TASK_STATUSES)
            assigned_to = (
                random.choice(employee_ids) if employee_ids and status != "created" else None
            )
            task_id = uuid4()
            firm_task_ids.append(task_id)
            task_rows.append(
                {
                    "id": task_id,
                    "fid": firm_id,
                    "title": "Load test task",
                    "assigned_to": assigned_to,
                    "deadline": deadline,
                    "status": status,
                    "created_by": owner_id,
                }
            )
        tasks_by_firm[firm_id] = firm_task_ids

        job_type_id = uuid4()
        job_type_rows.append(
            {
                "id": job_type_id,
                "fid": firm_id,
                "name": "Load test job type",
                "created_by": owner_id,
            }
        )
        job_type_by_firm[firm_id] = job_type_id

        notification_id = uuid4()
        notification_rows.append(
            {"id": notification_id, "fid": firm_id, "recipient": owner_id}
        )
        notification_by_firm[firm_id] = notification_id

    if firm_rows:
        conn.execute(
            text(
                "INSERT INTO firms (id, name, plan, status) "
                "VALUES (:id, 'Load Test Firm', 'free', 'active')"
            ),
            firm_rows,
        )
    if profile_rows:
        conn.execute(
            text(
                "INSERT INTO profiles "
                "(id, firm_id, role, full_name, email, is_active, must_change_password) "
                "VALUES (:id, :fid, :role, 'Load Test User', :email, true, false)"
            ),
            profile_rows,
        )
    if task_rows:
        conn.execute(
            text(
                "INSERT INTO tasks "
                "(id, firm_id, title, assigned_to, deadline, status, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :fid, :title, :assigned_to, :deadline, :status, :created_by, "
                "now(), now())"
            ),
            task_rows,
        )
    if job_type_rows:
        conn.execute(
            text(
                "INSERT INTO job_types (id, firm_id, name, is_active, created_by, created_at) "
                "VALUES (:id, :fid, :name, true, :created_by, now())"
            ),
            job_type_rows,
        )
    if notification_rows:
        conn.execute(
            text(
                "INSERT INTO notifications "
                "(id, firm_id, recipient_id, type, task_id, is_read, created_at) "
                "VALUES (:id, :fid, :recipient, 'task_deadline_approaching', NULL, false, now())"
            ),
            notification_rows,
        )

    # Cross-tenant probe target (script.js, 2026-09-17): each identity gets one real task id known
    # to belong to a DIFFERENT firm, so the load test can assert GET /tasks/{id} 404s for it under
    # real concurrency — not just check status codes on the caller's own data. Rejection sampling,
    # not a filtered list comprehension per identity: at the real target scale (2,000 firms /
    # ~10,000 identities) an O(firms) filter per identity is O(firms x identities); picking a
    # random firm and retrying only on the (1/firms) chance of a self-match is O(1) amortized.
    firm_ids = [fid for fid, tids in tasks_by_firm.items() if tids]
    for identity in identities:
        if len(firm_ids) < 2:
            identity["foreign_task_id"] = None  # nothing foreign exists to pick
            continue
        while True:
            other_firm = random.choice(firm_ids)
            if str(other_firm) != identity["firm_id"]:
                break
        identity["foreign_task_id"] = str(random.choice(tasks_by_firm[other_firm]))

    # Same rejection-sampling pattern, one per firm this time so no random.choice over a list is
    # needed (job_type_by_firm/notification_by_firm each map firm_id -> a single id already).
    job_type_firm_ids = list(job_type_by_firm.keys())
    notification_firm_ids = list(notification_by_firm.keys())
    for identity in identities:
        if len(job_type_firm_ids) < 2:
            identity["foreign_job_type_id"] = None
        else:
            while True:
                other = random.choice(job_type_firm_ids)
                if str(other) != identity["firm_id"]:
                    break
            identity["foreign_job_type_id"] = str(job_type_by_firm[other])

        if len(notification_firm_ids) < 2:
            identity["foreign_notification_id"] = None
        else:
            while True:
                other = random.choice(notification_firm_ids)
                if str(other) != identity["firm_id"]:
                    break
            identity["foreign_notification_id"] = str(notification_by_firm[other])

    return identities


def _mint_tokens(identities: list[dict], private_key: object, issuer: str) -> None:
    # Generous fixed expiry — minted once before the whole run starts, must outlive it entirely.
    exp = int(time.time()) + 4 * 3600
    for identity in identities:
        claims = {
            "sub": identity["profile_id"],
            "aud": "authenticated",
            "iss": issuer,
            "exp": exp,
            "app_metadata": {"firm_id": identity["firm_id"], "role": identity["role"]},
        }
        identity["token"] = jwt.encode(
            claims, private_key, algorithm="RS256", headers={"kid": _KID}
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firms", type=int, default=20)
    parser.add_argument("--employees-per-firm", type=int, default=10)
    parser.add_argument("--tasks-per-firm", type=int, default=40)
    args = parser.parse_args()

    db_url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not db_url:
        sys.exit("MIGRATIONS_DATABASE_URL must be set (same var tests/CI already use)")
    # Must be the exact SUPABASE_URL the target uvicorn process was started with — JWT_ISSUER
    # (config.py) is computed from it, and verify_access_token (security.py) rejects a token
    # whose `iss` doesn't match.
    supabase_url = os.environ.get("SUPABASE_URL", "http://localhost:9999")
    issuer = f"{supabase_url}/auth/v1"

    private_key_path = _HERE / "private_key.pem"
    if not private_key_path.exists():
        sys.exit(f"{private_key_path} not found — run generate_keys.py first")
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)

    engine = create_engine(db_url)
    with engine.begin() as conn:
        identities = _seed(conn, args.firms, args.employees_per_firm, args.tasks_per_firm)
    engine.dispose()

    _mint_tokens(identities, private_key, issuer)

    out_path = _HERE / "identities.json"
    out_path.write_text(json.dumps(identities))
    print(
        f"Seeded {args.firms} firms, {len(identities)} profiles, "
        f"~{args.firms * args.tasks_per_firm} tasks. Wrote {out_path}"
    )


if __name__ == "__main__":
    main()
