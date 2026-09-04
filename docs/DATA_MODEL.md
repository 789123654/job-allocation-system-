# CA Firm Practice Management Tool — Data Model

> Follows `docs/PRD.md` (v2) and `docs/ARCHITECTURE.md` (§5 Multi-Tenancy Strategy in particular — every convention below is that section's decision applied to real tables). No code or migrations yet.

## 1. Conventions

Verified directly against `postgres-multitenant/schema-design.md` before being adopted here (exact lines cited so you can check the source yourself, not just my summary):

- **Tenant column named `firm_id` everywhere** — a deliberate rename of the skill's generic `tenant_id` to match this project's own vocabulary (PRD talks about "firms," not "tenants"). This is *my* naming choice, not the skill's — the skill uses `tenant_id` throughout; only the name changed, not the pattern.
- **Composite primary key `(firm_id, id)`**, not `id` alone — schema-design.md:83-87: "consider `(tenant_id, id)` as a composite primary key... especially if you anticipate ever partitioning by `tenant_id` — Postgres requires the partition key to be part of any unique/primary key on a partitioned table." We're not partitioning now (see §6), but this keeps that door open structurally, same logic as the RLS-from-day-one decision in `ARCHITECTURE.md` §5.
- **Composite foreign keys `(firm_id, parent_id) → (firm_id, id)`** on every parent reference — schema-design.md:88-94: turns a cross-tenant reference bug (a row in firm A pointing at a parent row in firm B) into a constraint violation Postgres itself rejects, rather than a silent inconsistency RLS won't catch on its own ("RLS filters *visibility*, it doesn't validate that a foreign key value belongs to the same tenant" — direct quote). **Correction 2026-09-03:** this was applied inconsistently below — every reference to `profiles` (`created_by`, `assigned_to`, `reviewed_by`, `raised_by`, `resolved_by`, `recipient_id`, `actor_id`, `target_id`, `last_reset_by`) was written as a plain `FK → profiles.id`, exempting exactly the reference that matters most (who can act on whose data) from the rule everything else follows. The skill states "on every parent reference," no carve-out — fixed throughout §2 below. No new unique constraint needed: `profiles`'s existing composite PK `(firm_id, id)` already provides the `UNIQUE (firm_id, id)` a composite FK references.
- **Child tables carry `firm_id` directly**, denormalized from the parent, not just inferred via join — schema-design.md:15-19, so RLS and indexes work standalone on child tables like `issues` and `task_reviews` without a join back to `tasks` just to know which firm owns them.
- **Tenant-scoped uniqueness only** — schema-design.md:96-105, e.g. `UNIQUE (firm_id, email)`, never a bare global unique. Directly relevant here: Supabase's own `auth.users.email` is globally unique across the whole Supabase *project* (not per-firm) — a Supabase-level constraint, not something our own schema controls. **Elevated 2026-09-04 from a future footnote to a real operational constraint**, now that 2-4 firms is the near-term plan rather than a hypothetical: if two different pilot firms try to onboard an employee using the same email address, the second `admin.createUser()` call fails outright, not silently — Supabase rejects the duplicate at the project level. Whoever runs onboarding (§ `ARCHITECTURE.md` §4) needs to know this before onboarding firm #2, not discover it as a failed API call with no schema-level explanation — this project's own tables never see it as a constraint violation, since the rejection happens one layer up, in `auth.users`.
- **Composite indexes lead with `firm_id`** — schema-design.md:79-82: `(firm_id, created_at)`, `(firm_id, status, created_at)`, etc., so a firm-scoped query is a single efficient index range scan, not a global scan filtered afterward.
- `created_at`/`updated_at` timestamptz on every table; `is_active` soft-delete where history must be preserved — this last part is *not* from the skill, it's directly from PRD §2.1's own requirement ("deactivate employees... preserves history").
- **Added 2026-09-03 — UUID generation must be `gen_random_uuid()`, never a sequential/time-ordered scheme.** Not stated anywhere before now: every `uuid` PK below is typed `uuid` but never says *how* it's generated. Checked against `owasp-cheatsheets/Multi_Tenant_Security_Cheat_Sheet.md`: *"Use cryptographically secure, non-guessable tenant identifiers... avoid exposing sequential or guessable IDs"* — a real requirement, not a style preference, since a guessable `id` on any tenant-scoped table would let one firm probe for another firm's row IDs even with RLS blocking the actual read. `gen_random_uuid()` (PostgreSQL 13+ built-in, UUIDv4) on every PK's default — never `uuid_generate_v1()` or a UUIDv7-style scheme, both of which embed a timestamp and are more guessable by design; this project has no insert-locality performance need at 10-user scale to justify that tradeoff.
- RLS policy: the exact pattern from `ARCHITECTURE.md` §5, applied identically to every table below except `firms` itself.

## 2. Table List

Derived directly from the PRD, nothing speculative added beyond what §2.3 below explicitly flags and reasons about.

### `firms` — tenant root
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `name` | text | |
| `plan` | text | not used functionally yet (single firm, no billing tiers) — present so the column doesn't need adding later |
| `status` | text | |
| `created_at` | timestamptz | |

No `firm_id` self-column, not under the `tenant_isolation` RLS policy pattern — it's the table every other `firm_id` points at.

**Fixed 2026-09-03 (`ARCHITECTURE.md` §5 finding):** "not under the standard pattern" had quietly become "no RLS at all" — a query against `firms` returned every firm's row to any caller, the one place the "RLS holds even if FastAPI has a bug" guarantee didn't apply. `firms` gets its own `ENABLE`/`FORCE ROW LEVEL SECURITY` and a self-referential policy instead: `USING (id = current_setting('app.current_tenant', true)::uuid)`.

### `profiles` — both roles, one table
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | = `auth.users.id` |
| `firm_id` | uuid, composite PK w/ id, FK → `firms.id` | |
| `role` | text, `check in ('owner','employee')` | |
| `full_name` | text | |
| `email` | text | globally unique via Supabase `auth.users`, see §1 note |
| `is_active` | boolean, default true | PRD §2.1 deactivation requirement |
| `must_change_password` | boolean, default true | **Added 2026-09-02** — set `true` by the provisioning trigger below, cleared by the app once the user completes the forced Set New Password screen (`ARCHITECTURE.md` §4's provisioning section). Exists because provisioning switched from an email-invite link to an admin-issued temporary password — this is the mechanism that makes the password one-time, not just a policy |
| `last_reset_by` | uuid, nullable, composite self-FK `(firm_id, last_reset_by) → profiles(firm_id, id)` | **Added 2026-09-03** — set on every `POST /employees/{id}/reset-password` call to the calling Owner's id. Answers "who reset this password" without a join to a log table for the one piece of it that's asked most often |
| `last_reset_at` | timestamptz, nullable | **Added 2026-09-03** — paired with `last_reset_by`, same call. The full history of every reset (not just the latest) lives in `audit_log` below — these two columns are a cheap answer to the common question, not a replacement for the log |
| `created_at` | timestamptz | |

RLS: `tenant_isolation` pattern on `firm_id`.

**Trigger, not a manual insert:** a Postgres trigger on `auth.users` (`on_auth_user_created`, Supabase's
own recommended pattern) inserts each `profiles` row automatically, reading `firm_id`/`role` out of
`raw_user_meta_data` and setting `must_change_password = true` — the account itself is created by
`ARCHITECTURE.md`'s Firm + Owner Provisioning section (for the first Owner) and `API_SPEC.md`'s
`POST /employees` (for everyone after), both via `admin.createUser()` with a generated password, not an
invite email. The trigger function itself is the only new schema object this adds beyond the column above.

**Made explicit 2026-09-03 — the function must be `SECURITY DEFINER` with `SET search_path = ''`, not just
"a trigger."** Checked against Supabase's own exact example (`supabase/auth/managing-user-data.md`):
`create function public.handle_new_user() ... security definer set search_path = ''`. Both details are
load-bearing, not boilerplate — `SECURITY DEFINER` is required at all (an unprivileged trigger context can't
write to `profiles` otherwise), and the empty `search_path` specifically closes a known Postgres privilege-
escalation vector against `SECURITY DEFINER` functions (a malicious session-level search path could otherwise
shadow an unqualified table/function reference inside the function body). Naming both now so whoever writes
this trigger doesn't have to rediscover them.

### `job_types` — owner-managed templates (PRD §1.1/§2.2)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | |
| `name` | text | `UNIQUE (firm_id, name)` |
| `is_active` | boolean | soft-delete, not hard-delete, since existing tasks may reference a retired template |
| `created_by` | uuid, composite FK `(firm_id, created_by) → profiles(firm_id, id)` | |
| `created_at` | timestamptz | |

**Explicit scope call, my own judgment applied to the PRD, not a skill-derived decision:** PRD §1.1 says templates could carry "any fields the firm wants to track per job type," but nothing else in the PRD (task creation, dashboards, notifications) actually exercises such per-template custom fields. Building a dynamic `jsonb` custom-fields system now would be speculative — recommend the fixed `name` column only, flag dynamic fields as deferred rather than built. This is the same YAGNI reasoning applied throughout this project, not new.

### `tasks` — standard tasks and billing sub-tasks, one table (reasoning in §5)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | |
| `job_type_id` | uuid, nullable, composite FK → `job_types` | nullable because a billing sub-task may not need its own template tag — it's inherently tied to its parent |
| `task_type` | text, `check in ('standard','billing')`, default `'standard'` | |
| `parent_task_id` | uuid, nullable, composite self-FK `(firm_id, parent_task_id) → tasks(firm_id, id)` | set only for billing tasks, pointing at the original task |
| `title` | text | |
| `description` | text | |
| `assigned_to` | uuid, nullable, composite FK `(firm_id, assigned_to) → profiles(firm_id, id)` | nullable — PRD §4.1 lists Created before Assigned as distinct lifecycle steps |
| `deadline` | timestamptz, nullable | nullable until assigned |
| `status` | text, `check in ('created','assigned','in_progress','submitted','completed','billed')` | see §4 state machine |
| `created_by` | uuid, composite FK `(firm_id, created_by) → profiles(firm_id, id)` | |
| `created_at` / `updated_at` | timestamptz | |
| `last_reassignment_notes` | text, nullable | PRD §3.3: employee must see reassigned work explicitly |
| `last_reassignment_remaining_work` | text, nullable | |
| `last_reassignment_source` | text, nullable, `check in ('review','issue')` | the two distinct trigger paths from PRD §3.3/§4.3 |
| `last_reassignment_at` | timestamptz, nullable | |
| `billing_amount` | numeric, nullable | populated only when `task_type='billing'` |
| `billing_recipient` | text, nullable | populated only when `task_type='billing'` |

Indexes (leading with `firm_id`, per §1): `(firm_id, assigned_to, status)`, `(firm_id, status, deadline)`, `(firm_id, task_type, status)` — this last one is what supports the consolidated billing view from `ARCHITECTURE.md` §13's open question, whichever way that gets decided.

RLS: `tenant_isolation` pattern.

**Why the reassignment fields live directly on `tasks` instead of only in a history table:** PRD §3.3 needs the employee to see reassigned work *without* a join to history on every task-list render — these four columns are updated in place on reassignment; the full audit trail lives in `task_reviews`/`issues` instead (below), not lost.

### `task_reviews` — audit trail of the 3-way review outcome
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | |
| `task_id` | uuid, composite FK → `tasks` | |
| `reviewed_by` | uuid, composite FK `(firm_id, reviewed_by) → profiles(firm_id, id)` | |
| `outcome` | text, `check in ('approved','reassigned','billing')` | |
| `notes` | text, nullable | |
| `remaining_work_description` | text, nullable | populated when `outcome='reassigned'` |
| `resulting_billing_task_id` | uuid, nullable, composite FK → `tasks` | populated when `outcome='billing'` |
| `created_at` | timestamptz | |

Kept separate from `tasks.status` specifically so history survives a task cycling back to `in_progress` (PRD §4.1) — without this table, a second reassignment would silently overwrite the first one's record.

RLS: `tenant_isolation` pattern.

### `issues` — employee-raised issues (PRD §2.7/§4.3)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | |
| `task_id` | uuid, composite FK → `tasks` | |
| `raised_by` | uuid, composite FK `(firm_id, raised_by) → profiles(firm_id, id)` | |
| `description` | text | |
| `status` | text, `check in ('open','resolved')` | |
| `resolution_type` | text, nullable, `check in ('clarified','deadline_adjusted','reassigned')` | |
| `resolution_notes` | text, nullable | |
| `remaining_work_description` | text, nullable | **Added 2026-09-04, real gap not a stylistic one**: PRD §3.3 requires the employee to see "the owner's changes *and* remaining-work description" for *both* trigger paths — without this column, an issue-triggered reassignment could only ever populate `tasks.last_reassignment_notes`, never `tasks.last_reassignment_remaining_work`, half-failing the explicit "both must surface" requirement. Populated only when `resolution_type='reassigned'` — same rule as `task_reviews.remaining_work_description` |
| `resolved_by` | uuid, nullable, composite FK `(firm_id, resolved_by) → profiles(firm_id, id)` | |
| `resolved_at` | timestamptz, nullable | |
| `created_at` | timestamptz | |

**Explicit convergence, stated plainly so it doesn't need re-deriving later:** when `resolution_type='reassigned'`, this updates `tasks` through the *same* path as a review-triggered reassignment (same four `last_reassignment_*` columns, sourced from `resolution_notes`/`remaining_work_description` exactly as `task_reviews` sources them from `notes`/`remaining_work_description`). This is what makes PRD's "two distinct triggers, same employee notification" requirement (§3.3/§4.3) fall out naturally from one code path instead of needing two.

RLS: `tenant_isolation` pattern.

### `notifications` — per-user targeted, never broadcast
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | |
| `recipient_id` | uuid, composite FK `(firm_id, recipient_id) → profiles(firm_id, id)` | always a single profile — enforces "never broadcast" at the schema level, no multi-recipient row exists |
| `type` | text, `check in (...)` — the 8 values in §5's table | **Made explicit 2026-09-03** — every other enum-like column in this doc (`role`, `task_type`, `status`, `outcome`, `resolution_type`) has an inline `CHECK`; this one only pointed to §5's list in prose, which isn't itself a DB-level constraint. ASVS 2.2.1: input driving business decisions gets validated against a positive allowlist — the app layer choosing correctly isn't enough on its own |
| `task_id` | uuid, nullable, composite FK → `tasks` | context |
| `issue_id` | uuid, nullable, composite FK → `issues` | context |
| `is_read` | boolean, default false | |
| `created_at` | timestamptz | |

Index: `(firm_id, recipient_id, is_read, created_at)` — the exact query `ARCHITECTURE.md` §8's polling endpoint runs.

RLS: `tenant_isolation` pattern.

### `audit_log` — lifecycle/admin actions, append-only (PRD has no requirement for this; added 2026-09-03)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | |
| `actor_id` | uuid, composite FK `(firm_id, actor_id) → profiles(firm_id, id)` | who performed the action |
| `action` | text, `check in ('employee_created','employee_deactivated','employee_reactivated','password_reset')` | Phase 1 values, now a real `CHECK` rather than only stated in prose — same ASVS 2.2.1 reasoning as `notifications.type` above |
| `target_id` | uuid, nullable, composite FK `(firm_id, target_id) → profiles(firm_id, id)` | the profile the action was performed on — nullable only because a future firm-level action (e.g. `firm_deactivated`) wouldn't have one |
| `created_at` | timestamptz | |

No `updated_at`, no soft-delete — rows are never modified or removed once written. Index: `(firm_id, created_at)`.

RLS: `tenant_isolation` pattern, same as every other table — a firm sees only its own log, no exceptions.

**Scope, stated plainly so this doesn't grow into general app logging:** this table exists to answer "who did this admin action, and when" for the handful of actions above — not to log every request, every task update, or every read. `task_reviews` and `issues` already carry their own actor/timestamp columns for business-logic history (§ their own table definitions); this table is only for the admin-action layer they don't cover.

**Why now instead of Phase 2, reversing the earlier call:** originally deferred (`ARCHITECTURE.md` §4) on the reasoning that a single, manually-onboarded firm has no lifecycle events worth logging yet. That reasoning breaks the moment a second firm is imminent, not once it actually lands — the cheapest time to add a table is before there's data in the tables around it, and waiting would mean either building it under pressure or missing the second firm's own onboarding, which is itself the first real event worth having in this log. Still deliberately narrow: no firm-lifecycle actions (`firm_deactivated`, `firm_deleted`) yet, because `firms.status` itself has no defined values yet (`ARCHITECTURE.md` §4 offboarding note) — those get added together, when offboarding is actually built, not speculatively now.

### `access_denials` — failed authorization attempts, append-only (added 2026-09-05)
| Column | Type | Notes |
|---|---|---|
| `id` | uuid, composite PK w/ firm_id | |
| `firm_id` | uuid, FK → `firms.id` | the *actor's* own firm — same convention as every other table, not the target's firm |
| `actor_id` | uuid, composite FK `(firm_id, actor_id) → profiles(firm_id, id)` | who was denied |
| `resource_type` | text, nullable, `check in ('task','notification')` | null for a pure role check with no specific resource in play (`require_owner`) |
| `resource_id` | uuid, nullable, **deliberately not an FK** | the resource the actor tried to reach — no FK because the whole point is it may be something the actor can't see or that fails other constraints; an enforced FK here would defeat the reason the column exists |
| `reason` | text, `check in ('wrong_role','not_assignee','wrong_owner')` | `wrong_role` = failed a role gate (e.g. Employee hitting an Owner-only route); `not_assignee` = visible to the actor but not theirs to act on (e.g. Owner can see a task but isn't its assignee for submit/mark-billed); `wrong_owner` = not even visible — same-tenant IDOR (e.g. an Employee requesting another's task/notification by id) |
| `created_at` | timestamptz | |

No `updated_at`, no soft-delete. Index: `(firm_id, created_at)`.

RLS: `tenant_isolation` pattern, same as every other table.

**Structural limit, stated so it isn't assumed to cover more than it does:** a true *cross-tenant* access attempt is invisible at this layer. `get_task`/`get_notification` query with no `firm_id` filter at all — RLS itself silently scopes the result to the actor's own tenant, so a task ID belonging to a different firm produces the exact same "not found" as an ID that never existed; the app code has no way to tell the two apart, and this table only receives what the app code can see. This table therefore records same-tenant IDOR and role-check denials, not cross-tenant probing — that case stays covered by RLS alone (`ARCHITECTURE.md` §5's defense-in-depth boundary), with no app-level record. Making cross-tenant attempts visible would require a privileged, RLS-bypassing lookup purely for detection — a materially different, more sensitive feature, not built here.

**Deliberately excluded:** `require_password_set`'s 403 (`deps.py`) — a forced Set-New-Password gate every new employee hits on first login, not a violation attempt. Logging it would be noise, not signal (`Authorization_Cheat_Sheet.md`'s own caution against over-logging: CWE-778/CWE-779, both too little and too much logging are named weaknesses).

**Why a separate table instead of extending `audit_log`, decided 2026-09-05:** `audit_log.target_id` is a composite FK scoped to `(firm_id, target_id) → profiles(firm_id, id)` — it can only reference a profile, and only within the same firm as the log row. A denial can target a non-profile resource (a task) and, structurally, could involve a target outside the actor's own firm — both break that FK outright. Forcing this in would mean either dropping the FK (weakening the guarantee on `audit_log`'s existing four actions too) or bolting on a second, unconstrained column — at which point it isn't really the same table. `audit_log`'s own stated scope ("who did this admin action" — a *success* record) is also a different semantic category from a denial record; mixing them means every future reader has to remember which kind of row they're looking at. Confirmed against `Multi_Tenant_Security_Cheat_Sheet.md` §8 ("Monitor for cross-tenant access attempts... tenant-isolated audit trails") and ASVS 16.3.2 (L2, failed authorization attempts logged) before building — both describe this as its own concern, not a rider on general audit logging.

## 3. Task Lifecycle State Machine

```
created → assigned → in_progress → submitted →
  ├─ completed        (outcome: approved)
  ├─ in_progress       (outcome: reassigned — task_reviews row logged)
  └─ completed + new billing task row created  (outcome: billing — task_reviews row logged)

Billing tasks: assigned → in_progress → billed
  (no unassigned "created" state — owner creates it pre-assigned;
   no "submitted"/review step — matches PRD's simpler, trust-based completion)
```

Stated plainly: **`status` never holds a `reassigned` value.** Reassignment is an event recorded in `task_reviews`/`issues`, not a resting state — the task always lands back on `in_progress`, matching PRD §2.6's own wording ("back to In Progress").

## 4. Billing Sub-Task Modeling — Decision and Reasoning

**Same `tasks` table** (`task_type` discriminator + `parent_task_id` self-reference), not a separate `billing_tasks` table. This is my own schema-design judgment applying the PRD's own words, not a skill citation:

PRD §2.8 states billing tasks "follow the employee's normal task flow" verbatim — same assignment, same task lists, same notification types, same dashboards. A separate table would force either duplicated list/notification/dashboard query logic across two tables, or constant `UNION`s to show one unified task list. The two extra billing-only fields (`billing_amount`, `billing_recipient`) are small enough to be nullable columns on the shared table rather than justifying a second table.

**Stated ceiling, so this doesn't silently become the wrong call later:** if billing-specific fields grow substantially (e.g., multi-line invoice items, tax fields, payment status tracking — none of which are in scope now), split into a satellite `billing_details` table keyed by `task_id` at that point. Not needed for Phase 1.

## 5. Notification Type Enumeration

Maps every `notifications.type` value 1:1 to the exact PRD bullet it implements, so the API spec doc has zero ambiguity about what triggers what:

| `type` value | PRD source | Recipient |
|---|---|---|
| `task_submitted` | §2.5 | Owner |
| `task_overdue` | §2.5 | Owner |
| `task_deadline_1_day` | §2.5 (highlighted, distinct from approaching) | Owner |
| `issue_raised` | §2.5 | Owner |
| `task_assigned` | §3.4 | Employee (individually targeted) |
| `task_reassigned` | §3.4 (both trigger paths, §3.3) | Employee |
| `task_deadline_approaching` | §3.4 | Employee |
| `task_overdue_own` | §3.4 (new vs. original PRD) | Employee |

## 6. Schema-Level Open Questions

Neither of these needs a schema change either way — stated explicitly so `DATA_MODEL.md` isn't blocked on decisions that belong elsewhere:

- **Consolidated billing queue view vs. filtered task list** (`ARCHITECTURE.md` §13) — the `(firm_id, task_type, status)` index on `tasks` already supports both implementations equally.
- **Reassignment target: owner's choice vs. always-same-employee** — `tasks.assigned_to` is just overwritten either way; `task_reviews`/`issues` already log the prior assignee, so no schema impact.

**Deferred to Phase 2, deliberately — not a silent gap:** a `submitted_at` timestamp on `tasks` (nullable, set when status moves to `submitted`), so the Owner's review screen can show how long a task has been waiting. Surfaced during frontend mockup review — neither `updated_at` (drifts on any later change) nor `task_reviews.created_at` (only exists after the review happens, not during the wait) actually captures this today. Small, single-column addition when it's time — no other schema impact.

**Carried forward from `PRD.md`'s audit, not a schema question:** ASVS 2.3.1 (L1, "no step-skipping") and
2.3.3 (L2, transactional business-logic operations) apply to the task lifecycle and the Billing dual-write
respectively. The `status`/`task_type` `CHECK` constraints above enforce which *values* are valid, not which
*transitions* between them are — that enforcement belongs in `API_SPEC.md`'s endpoint logic (checking current
status before accepting a transition), not a DB trigger here. Stated so it isn't assumed solved by the
`CHECK` constraints alone; verifying it's actually addressed is `API_SPEC.md`'s job when that file is audited.

**One thing genuinely worth deciding before this doc is "done," not a schema question:** per `schema-design.md:107-118`, declarative partitioning by `firm_id` is explicitly framed as "an operational scaling lever, not a day-one requirement — adopt it when a specific table's size... actually becomes a measured problem." Nothing to build now; the composite-PK convention in §1 is what keeps that door open when the time comes, same logic as the RLS-from-day-one decision. Flagging it here so it's a stated deferral, not a forgotten one — matching the discipline used for caching/async in `ARCHITECTURE.md` §10.

---

Reference patterns pulled from `postgres-multitenant/schema-design.md`, verified against the actual file (exact line numbers cited above) before being written here — not from memory. Table-specific field choices are this project's own application of those patterns to the PRD's actual requirements, not skill citations themselves.
