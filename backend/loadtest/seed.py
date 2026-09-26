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

2026-09-27 additions (blind attack-suite support, see script.js):
- `foreign_employee_id` per identity — same rejection-sampling pattern as the three above, for
  PATCH /employees/{id}'s cross-tenant probe. Picks a firm's first employee, falling back to its
  owner if `employees_per_firm=0`, since any real profile row in another firm serves the same
  "does this object 404 across tenants" purpose.
- `mismatched_claim_firm_id` / `mismatched_claim_token` per identity, and `escalated_role_token`
  for employee identities — tokens with a VALID signature (minted with the same private key as
  `token`) but claims that disagree with what this profile's real seeded row actually is: a real
  `sub` paired with a different firm's `firm_id`, or a real employee's `sub` paired with
  `role: "owner"`. k6 has no signing key, so these can't be forged client-side in script.js — only
  seed.py (holding `private_key.pem`) can mint them. This is what lets script.js test "does the
  server ever honor a client-supplied claim it shouldn't" (Multi_Tenant_Security_Cheat_Sheet.md /
  ASVS 8.4.1) as opposed to just "is a bad signature rejected" (already covered by `token` +
  tampering in script.js).
- A single deterministic **race scenario**, not per-firm: one extra task (`race_task_id`), seeded
  directly into `assigned` status for one real employee (`race_employee_id` in firm #0), with a
  fixed `race_idempotency_key` and that employee's own `race_token` — identical values copied onto
  *every* identity so that whichever random VU iterations land on the race probe branch, across the
  whole run, all hit the exact same request, the only way k6's independent VUs can be made to
  genuinely collide on the same row without adding a coordination mechanism this project doesn't
  otherwise need (`Business_Logic_Security_Cheat_Sheet.md`'s "Prevent Race Conditions on Sensitive
  Operations" / "Use Idempotency Keys" sections).
- **`foreign_issue_id`, added 2026-09-27 (fast-follow to the blind pass above)** — one `issues` row
  seeded per firm (schema read directly from the `a3f5c9e21d07` migration, not guessed), same
  one-per-firm rejection-sampling pattern as `foreign_job_type_id`/`foreign_notification_id`.
  Skipped only for a firm with zero seeded tasks (`issues.task_id` is `NOT NULL`, FK'd to
  `tasks (firm_id, id)`) — same "no foreign object exists" fallback as the other `foreign_*_id`
  fields when `tasks_per_firm=0`.
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


def _seed(
    conn: Connection, firms: int, employees_per_firm: int, tasks_per_firm: int
) -> tuple[list[dict], dict]:
    identities: list[dict] = []
    firm_rows: list[dict] = []
    profile_rows: list[dict] = []
    task_rows: list[dict] = []
    job_type_rows: list[dict] = []
    notification_rows: list[dict] = []
    issue_rows: list[dict] = []
    # firm_id -> [task_id, ...], client-generated below (not DB-returned) so script.js's
    # cross-tenant probe (2026-09-17 addition) has a real task id it KNOWS belongs to a different
    # firm than the requester, without an extra round-trip or RETURNING clause.
    tasks_by_firm: dict[object, list[object]] = {}
    # One-per-firm (not lists — PATCH /job-types/{id} and PATCH /notifications/{id}/read only need
    # a single real write target each, unlike tasks_by_firm above).
    job_type_by_firm: dict[object, object] = {}
    notification_by_firm: dict[object, object] = {}
    issue_by_firm: dict[object, object] = {}
    # 2026-09-27 addition — same one-per-firm shape, for PATCH /employees/{id}'s cross-tenant probe.
    employee_by_firm: dict[object, object] = {}
    now = datetime.now(UTC)

    # 2026-09-27 addition — the one deterministic race-condition target (script.js's
    # businessLogicRaceProbe), captured from firm #0 specifically so it exists exactly once
    # regardless of `firms`, not one per firm (a single genuinely-contested row is the point).
    race_firm_id: object | None = None
    race_owner_id: object | None = None
    race_employee_id: object | None = None

    for i in range(firms):
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

        # Falls back to the owner when employees_per_firm=0 — any real profile row in this firm
        # proves the same thing to the cross-tenant probe (a different firm's object 404s), same
        # reasoning as job_type_by_firm/notification_by_firm's one-per-firm shape.
        employee_by_firm[firm_id] = employee_ids[0] if employee_ids else owner_id

        if i == 0:
            race_firm_id = firm_id
            race_owner_id = owner_id
            race_employee_id = employee_ids[0] if employee_ids else None

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

        # 2026-09-27 addition — one issue per firm, for GET /issues/{id}'s cross-tenant probe
        # (crossTenantIssueProbe, script.js). issues.task_id is NOT NULL (FK'd to tasks), so this
        # only exists for a firm that actually seeded at least one task, same fallback shape as
        # employee_by_firm falling back to the owner when employees_per_firm=0.
        if firm_task_ids:
            issue_id = uuid4()
            issue_rows.append(
                {
                    "id": issue_id,
                    "fid": firm_id,
                    "task_id": firm_task_ids[0],
                    "raised_by": owner_id,
                    "description": "Load test issue",
                }
            )
            issue_by_firm[firm_id] = issue_id

    # 2026-09-27 addition — the race-condition target itself, appended once (not per firm) so it
    # goes into the same bulk task INSERT below. Deterministic status/assignee, not the random
    # spread above: businessLogicRaceProbe needs a task that starts life "assigned" and stays a
    # valid /submit target for the whole run, not whatever a random roll happened to produce.
    race_idempotency_key: str | None = None
    race_task_id: object | None = None
    if race_employee_id is not None:
        race_task_id = uuid4()
        race_idempotency_key = str(uuid4())
        task_rows.append(
            {
                "id": race_task_id,
                "fid": race_firm_id,
                "title": "Race probe target — do not remove",
                "assigned_to": race_employee_id,
                "deadline": None,
                "status": "assigned",
                "created_by": race_owner_id,
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
    if issue_rows:
        conn.execute(
            text(
                "INSERT INTO issues (id, firm_id, task_id, raised_by, description, status, created_at) "
                "VALUES (:id, :fid, :task_id, :raised_by, :description, 'open', now())"
            ),
            issue_rows,
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
            identity["mismatched_claim_firm_id"] = None
            continue
        while True:
            other_firm = random.choice(firm_ids)
            if str(other_firm) != identity["firm_id"]:
                break
        identity["foreign_task_id"] = str(random.choice(tasks_by_firm[other_firm]))
        # 2026-09-27 addition — the SAME other_firm already picked above, reused (not a fresh
        # rejection-sampling pass) so claimMismatchProbe's forged-firm token and the real
        # foreign_task_id it targets always point at the same firm: a token honestly signed for
        # this identity's own profile, but claiming to belong to the firm that owns
        # foreign_task_id, then requesting exactly that task — the one request shape that would
        # actually reveal whether firm_id claims are trusted over the profile's real, seeded firm.
        identity["mismatched_claim_firm_id"] = str(other_firm)

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

    # 2026-09-27 addition — same one-per-firm rejection-sampling pattern, for PATCH
    # /employees/{id}'s cross-tenant probe (employeeUpdateProbe, script.js).
    employee_firm_ids = list(employee_by_firm.keys())
    for identity in identities:
        if len(employee_firm_ids) < 2:
            identity["foreign_employee_id"] = None
        else:
            while True:
                other = random.choice(employee_firm_ids)
                if str(other) != identity["firm_id"]:
                    break
            identity["foreign_employee_id"] = str(employee_by_firm[other])

    # 2026-09-27 addition — same one-per-firm rejection-sampling pattern, for GET /issues/{id}'s
    # cross-tenant probe (crossTenantIssueProbe, script.js). issue_by_firm only has entries for
    # firms that seeded at least one task, so this can be < firm_ids's own length.
    issue_firm_ids = list(issue_by_firm.keys())
    for identity in identities:
        if len(issue_firm_ids) < 2:
            identity["foreign_issue_id"] = None
        else:
            while True:
                other = random.choice(issue_firm_ids)
                if str(other) != identity["firm_id"]:
                    break
            identity["foreign_issue_id"] = str(issue_by_firm[other])

    return identities, {
        "task_id": str(race_task_id) if race_task_id else None,
        "employee_id": str(race_employee_id) if race_employee_id else None,
        "firm_id": str(race_firm_id) if race_firm_id else None,
        "idempotency_key": race_idempotency_key,
    }


def _mint_tokens(
    identities: list[dict], private_key: object, issuer: str, race_info: dict
) -> None:
    # Generous fixed expiry — minted once before the whole run starts, must outlive it entirely.
    exp = int(time.time()) + 4 * 3600
    expired = int(time.time()) - 3600  # already-expired, for forgedTokenVariantProbe

    def _mint(sub: str, firm_id: str, role: str, **overrides) -> str:
        claims = {
            "sub": sub,
            "aud": "authenticated",
            "iss": issuer,
            "exp": exp,
            "app_metadata": {"firm_id": firm_id, "role": role},
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})

    for identity in identities:
        identity["token"] = _mint(identity["profile_id"], identity["firm_id"], identity["role"])
        # 2026-09-27 additions — all four below carry a VALID signature (this is the whole point:
        # k6 can't forge a signature without the private key, only seed.py can) but a claim that
        # disagrees with either the token spec (ARCHITECTURE.md §4's exp/iss/aud checklist) or with
        # this profile's own real, seeded row — checked directly against
        # `owasp-cheatsheets/JSON_Web_Token_Cheat_Sheet.md`'s exp/iss/aud table and
        # `Multi_Tenant_Security_Cheat_Sheet.md`'s "never trust client-supplied tenant ID" guidance.
        identity["expired_token"] = _mint(
            identity["profile_id"], identity["firm_id"], identity["role"], exp=expired
        )
        identity["bad_iss_token"] = _mint(
            identity["profile_id"], identity["firm_id"], identity["role"], iss=issuer + "-wrong"
        )
        # "anon" is Supabase's own other real audience value (generate_keys.py/ARCHITECTURE.md §4
        # note that "authenticated" is the only correct one here) — a plausible-looking wrong
        # value, not an arbitrary string, matching how a real confused-audience token would look.
        identity["bad_aud_token"] = _mint(
            identity["profile_id"], identity["firm_id"], identity["role"], aud="anon"
        )
        if identity.get("mismatched_claim_firm_id"):
            identity["mismatched_claim_token"] = _mint(
                identity["profile_id"], identity["mismatched_claim_firm_id"], identity["role"]
            )
        else:
            identity["mismatched_claim_token"] = None
        if identity["role"] == "employee":
            identity["escalated_role_token"] = _mint(
                identity["profile_id"], identity["firm_id"], "owner"
            )
        else:
            identity["escalated_role_token"] = None

    # Race scenario: one shared token for one real employee, copied onto every identity (see the
    # module docstring) so script.js's businessLogicRaceProbe always targets the same row/key
    # regardless of which identity a given VU iteration randomly drew.
    if race_info["employee_id"]:
        race_token = _mint(race_info["employee_id"], race_info["firm_id"], "employee")
        for identity in identities:
            identity["race_task_id"] = race_info["task_id"]
            identity["race_idempotency_key"] = race_info["idempotency_key"]
            identity["race_token"] = race_token
    else:
        for identity in identities:
            identity["race_task_id"] = None
            identity["race_idempotency_key"] = None
            identity["race_token"] = None


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
        identities, race_info = _seed(conn, args.firms, args.employees_per_firm, args.tasks_per_firm)
    engine.dispose()

    _mint_tokens(identities, private_key, issuer, race_info)

    out_path = _HERE / "identities.json"
    out_path.write_text(json.dumps(identities))
    print(
        f"Seeded {args.firms} firms, {len(identities)} profiles, "
        f"~{args.firms * args.tasks_per_firm} tasks. Wrote {out_path}"
    )


if __name__ == "__main__":
    main()
