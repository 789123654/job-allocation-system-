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
            task_rows.append(
                {
                    "fid": firm_id,
                    "title": "Load test task",
                    "assigned_to": assigned_to,
                    "deadline": deadline,
                    "status": status,
                    "created_by": owner_id,
                }
            )

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
                "(firm_id, title, assigned_to, deadline, status, created_by, "
                "created_at, updated_at) "
                "VALUES (:fid, :title, :assigned_to, :deadline, :status, :created_by, "
                "now(), now())"
            ),
            task_rows,
        )
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
