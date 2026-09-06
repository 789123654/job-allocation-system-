# Security Audit Checklist

How a phase-by-phase security audit is run and verified in this project, and how it's kept from being a
self-graded pass. Each field below is **evidence**, not a checkbox — paste the actual grep output, list the
actual filenames opened, paste the actual command output. A line that just says "done" or "yes" isn't
evidence and doesn't count, whether or not a hook is enforcing that.

Set `status: in-progress` before starting a real pass. While it's `in-progress`, a `Stop` hook
(`~/.claude/hooks/audit-checklist-guard.js`) blocks the turn from ending if any field below is still empty —
see that file for exactly what it checks and its limits (it can confirm a field isn't blank; it cannot judge
whether the content is actually true). Set `status: complete` once every field is filled, move this block
into "Completed Audits" below, and reset "Current Audit" to `status: idle` before starting the next phase.

## Current Audit

```
status: idle   <!-- idle | in-progress | complete -->
phase:
scope_files:
date:
commit:
```

### A. Fixed enumeration

- `asvs_chapters_opened`: <!-- list all 17 filenames (v1..v17) actually opened this pass, plus patterns.md -->
- `skills_reopened_fresh`: <!-- every project skill file reopened THIS pass — not cited from an earlier read -->
- `cheatsheet_grep_keywords`: <!-- the actual keyword regex used, derived from this phase's mechanisms, not from cheat-sheet titles -->
- `cheatsheet_grep_output`: <!-- paste the real Grep tool output: filenames + matching lines -->

### B. Fixed-domain sweep

- `auth`:
- `session_token_lifecycle`:
- `tenant_isolation`:
- `object_level_authz`:
- `input_validation`:
- `cors`:
- `secrets`:
- `supply_chain`:

### C. Self-check gate (mapped 1:1 to skill-verification-discipline.md's 7 failure modes)

1. `reapplied_general_principle_to_every_instance`:
2. `stress_tested_design_against_its_own_stated_logic`:
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`:
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`:
5. `compound_source_not_partial` <!-- raw skill + ASVS + cheat sheet, not just one -->:
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`:
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`:

### D. Verification-of-verification

- `library_behavior_claims_checked_against_installed_source` <!-- file + line, not belief -->:
- `fix_verified_by_real_command_output` <!-- paste actual test/lint output -->:

### E. Bounded claim

- `standard_and_scope` <!-- e.g. "ASVS 5 L1+L2" -->:
- `severity_trend_vs_last_pass` <!-- diminishing severity = stop signal; new category/rising severity = keep going -->:

### F. Independent pass

- `security_review_run` <!-- yes/no + date; /code-review ultra has not yet been run on this repo as of the last check -->:

## Completed Audits

### Phase 3 — Job Types / Tasks / Reviews / Issues / Notifications (2026-09-07, base commit `389856e5ca876faa19d65e6093269952a34117a4`)

```
status: complete
phase: Phase 3 — Remaining backend resources (CODING_STRUCTURE.md §4 item 4): job_types, tasks, task_reviews, issues, notifications, access_denials
scope_files: backend/app/api/routes/{job_types,tasks,issues,notifications}.py, backend/app/crud.py (job_type/task/review/issue/notification-scoped fns), backend/app/models.py (JobType, Task, IdempotencyKey, TaskReview, Issue, Notification, AccessDenial), backend/app/core/idempotency.py, backend/app/alembic/versions/{9104a25b4614,dd9b07e031bf,a3f5c9e21d07,f1c8a4d3b6e9,c72e9a1f4b83,dc5f39cce3f9}_*.py, backend/tests/{api/routes,crud}/test_{job_types,tasks,issues,notifications,task_transitions,reviews_and_issues,notification_generation,access_denials}.py
date: 2026-09-07
commit: 389856e5ca876faa19d65e6093269952a34117a4 (base HEAD at audit start — the assigned_to fix below + this entry land as a new commit on top, same pattern as Phase 2's own entry)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v1-encoding-sanitization, v2-validation-business-logic, v3-web-frontend-security, v4-api-web-service, v5-file-handling, v6-authentication, v7-session-management, v8-authorization, v9-self-contained-tokens, v10-oauth-oidc, v11-cryptography, v12-secure-communication, v13-configuration, v14-data-protection, v15-secure-coding-architecture, v16-security-logging-error-handling, v17-webrtc, patterns.md — all 17 + patterns read in full fresh this pass (not cited from Phase 1/2 memory). v3/v5/v10/v17 re-confirmed N/A for the same reason as Phase 2 (no frontend/file-upload/OAuth/WebRTC surface in this backend-only slice) — re-checked, not assumed to still hold.
- `skills_reopened_fresh`: owasp-asvs-5 (all 17 chapters + patterns.md, listed above); owasp-cheatsheets (9 whole-directory greps, list below) — `Mass_Assignment_Cheat_Sheet.md` and `Business_Logic_Security_Cheat_Sheet.md` read in full fresh this pass (not recycled from Phase 2's read of the latter). Not reopened: rest-api-guidelines/fastapi/postgres-official/supabase-official — Phase 3 introduces no new mechanism from those beyond what Phase 1/2 already verified (idempotency pattern reused unchanged, no new DB-session pattern, no new Supabase Auth API call).
- `cheatsheet_grep_keywords`: `race condition|TOCTOU|concurrent|check-then-act|time.of.check`; `mass assignment|over.?posting|foreign key|referential`; `stored XSS|reflected|sanitiz|encode.{0,15}output|rich text|freeform`; `notification|broadcast|push notification`; `workflow|business logic|state machine|sequential step`; `IDOR|BOLA|insecure direct object|object.level authorization`; `unbounded|resource exhaustion|denial of service|pagination|rate limit`; `idempot|replay`; `log injection|logging|audit log|CRLF injection` — 9 greps derived from Phase 3's actual mechanisms (task/issue workflow-state transitions, task/issue `assigned_to` fields, notification generation, job-type dedup, audit/access-denial logging), not from cheat-sheet titles.
- `cheatsheet_grep_output`: 9 separate greps across the whole `owasp-cheatsheets/cheatsheets/` directory (12/5/42/13/32/7/36/20/54 files matched respectively — full lists retained in this session's transcript). Read in full this pass: `Mass_Assignment_Cheat_Sheet.md`, `Business_Logic_Security_Cheat_Sheet.md` — the "mass assignment" keyword grep is what surfaced `Mass_Assignment_Cheat_Sheet.md`, whose title alone gives no hint it would matter for a `assigned_to: UUID` field (not a form-bound object), and `Business_Logic_Security_Cheat_Sheet.md`'s own "Identity and Role" section is the direct source for the real finding below.

**B. Fixed-domain sweep**

- `auth`: Unchanged from Phase 1/2 — Phase 3 adds no new auth mechanism, only consumes `ActiveProfileDep`/`RequireOwnerDep` unchanged. Confirmed by reading all 4 route files in full this pass — no route bypasses these deps.
- `session_token_lifecycle`: Unchanged — no new token type introduced.
- `tenant_isolation`: All 6 new/touched tables (`job_types`, `tasks`, `idempotency_keys`, `task_reviews`, `issues`, `notifications`, `access_denials`) have `ENABLE`+`FORCE ROW LEVEL SECURITY` and an identical `tenant_isolation` policy — verified directly by reading all 6 migration files this pass, not assumed from Phase 2's pattern. `test_rls_isolation.py` exercises the shared policy mechanism against `profiles` only, not per-table — judged sufficient since Postgres RLS enforcement is the thing under test and every table above uses the byte-identical policy definition (`USING/WITH CHECK firm_id = current_setting('app.current_tenant', true)::uuid`), confirmed by direct comparison across all 6 files, not by title-matching them.
- `object_level_authz`: 404-not-403 IDOR pattern re-checked against every `{id}`-scoped Phase 3 endpoint: `job_types` PATCH (404 via RLS-filtered `get_job_type`), `tasks` GET/PATCH-deadline/submit/mark-billed/review (`_get_task_or_404`), `issues` resolve (404). Real 403 (not 404) used only where existence is already legitimately known to that role (`_require_assignee`) — matches Authorization_Cheat_Sheet.md/Multi_Tenant_Security_Cheat_Sheet.md's own distinction, re-verified this pass, not just cited from Phase 2's check.
- `input_validation`: Length ceilings present on every new free-text field (`JobTypeCreate.name`, `TaskCreate.title/description`, `TaskReviewCreate.notes/remaining_work_description/billing_description/billing_recipient`, `IssueCreate.description`, `IssueResolveRequest.resolution_notes/remaining_work_description`) — re-confirmed present by reading `job_types.py`/`tasks.py`/`issues.py` in full, not assumed from the pattern's first application. `TaskReviewCreate`/`IssueResolveRequest`'s `model_validator` "Validate Combinations" checks (Business_Logic_Security_Cheat_Sheet.md's own named pattern) re-verified line-by-line against the cheat sheet's actual wording, not just the code's own citation of it. **Real finding, fixed this pass**: `assigned_to` (accepted on `TaskCreate`, `TaskReviewCreate`, `IssueResolveRequest`) was validated only by the DB's own composite `(firm_id, assigned_to) REFERENCES profiles` FK — real tenant-boundary enforcement, but a raw `IntegrityError` on violation surfaces as a generic 500 (not a clean 4xx), and the FK alone never checked the target is an active `employee` (not a fellow Owner or a deactivated account). `Business_Logic_Security_Cheat_Sheet.md`'s "Identity and Role" section, read fresh this pass: *"Never accept a user ID... from the request body unless the request is explicitly an administrative action by a privileged caller, and even then the value has to be validated against what the caller is allowed to manage."* Fixed via a new `crud._validate_assignee`/`UnknownAssigneeError` (ASVS 15.3.3 mass-assignment, 2.3.1 business-logic sequencing) wired into `create_task`/`create_task_review`/`resolve_issue`, mapped to a 422 in all three routes.
- `cors`: Unchanged from Phase 1 — Phase 3's new PATCH routes (`job_types`, `notifications`) already fit the existing `allow_methods=["GET","POST","PATCH","DELETE"]` list (confirmed by reading `main.py` fresh this pass). Noted, not fixed (ASVS 4.1.4, L3, out of this project's stated L1+L2 scope): `DELETE` is CORS-allowlisted but no route anywhere uses it — Starlette's own routing (not CORS) already blocks any actual `DELETE` request with a 405, so this is unused-allowlist hygiene, not a live gap.
- `secrets`: Unchanged from Phase 2 — Phase 3 introduces no new secret. Confirmed by reading all 4 route files + `crud.py` in full — no logging of any Phase 3 field, verified by grepping every `logger.` call in `app/` (5 total, all in `main.py`/`deps.py`, none touching task/issue/notification content) — no log-injection surface (V16.4.1) introduced.
- `supply_chain`: `git log --oneline -- backend/pyproject.toml` → only 2 commits total, both predating every Phase 3 commit (initial scaffolding + a pyright-strict-mode-only config change) — confirmed by direct history read, not assumed. Zero new third-party dependencies from Phase 3.

**C. Self-check gate**

1. `reapplied_general_principle_to_every_instance`: The 404-not-403 pattern and the `record_access_denial`-before-403/404 pattern were checked against every Phase 3 `{id}`-scoped endpoint individually (see `object_level_authz` above), not assumed from Phase 2's one example.
2. `stress_tested_design_against_its_own_stated_logic`: Two stress-tests this pass. (a) `assigned_to`'s claimed safety (DB FK) against Business_Logic_Security_Cheat_Sheet.md's own stated rule → real gap found, fixed (see `input_validation` above). (b) Whether `TaskOut` exposing `billing_amount`/`billing_recipient` to the assigned Employee is a BOPLA gap (ASVS 8.2.3) → checked against `PRD.md` §2.8/§4.2 directly (grepped fresh), which states the billing task "follows the employee's normal task flow" with amount/recipient "set by owner" and the employee expected to act on them — confirmed intended, not a gap.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B run in full regardless of the `assigned_to` fix being the conversation's first focus.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: `Business_Logic_Security_Cheat_Sheet.md` was reopened fresh this pass (already read in Phase 2's pass, for a different question — reset-password locking) specifically for the "Identity and Role" section, not trusted from memory of having read the file before.
5. `compound_source_not_partial`: The `assigned_to` finding cites Business_Logic_Security_Cheat_Sheet.md (verbatim quote) + ASVS 15.3.3/2.3.1 + the actual installed migration's FK definition (`dd9b07e031bf`, read directly) — three sources, not one.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 9 keyword greps across the whole directory this pass (listed in A) — this is what surfaced `Mass_Assignment_Cheat_Sheet.md`, a title that gives no hint it covers a non-form `assigned_to: UUID` field.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: `with_idempotency` is reused unchanged across all 5 new Phase 3 call sites (`create_task`, `submit_task`, `mark_task_billed`, `create_task_review`, `create_issue`, `resolve_issue`) — checked each response body shape (`TaskOut`/`IssueOut`) for a one-time-secret property like reset-password's had; none carry one, so the mechanism's existing (non-secret-JSON) vetting genuinely extends here, confirmed by reading each response model, not assumed from the pattern's name.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: No new external-library behavior claim in Phase 3 beyond what Phase 1/2 already verified against installed source (`.with_for_update()`'s SQLAlchemy semantics, `supabase_auth`'s admin API shape) — Phase 3 calls no new external API.
- `fix_verified_by_real_command_output`: Fixed `assigned_to` validation (backend/app/crud.py, backend/app/api/routes/{tasks,issues}.py) plus updated 3 pre-existing tests that had been asserting behavior against a nonexistent assignee (now correctly rejected) and added 6 new tests (4 for `create_task`, 2 for `create_task_review`/`resolve_issue`'s reassignment paths). Verified via the actual CI-equivalent commands: `uv run pyright` → `0 errors, 0 warnings, 0 informations`; `uv run pytest -q` → `94 passed, 6 skipped, 2 warnings` (up from the pre-fix run's `3 failed, 89 passed, 6 skipped` — the 3 failures were the pre-existing tests correctly catching the new check working, fixed by giving them real employee rows); `uv run ruff check app/ tests/` → `All checks passed!`.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5, L1+L2, scoped to Phase 3's job_types/tasks/task_reviews/issues/notifications/access_denials slice (files listed in `scope_files` above) as of base commit `389856e5ca876faa19d65e6093269952a34117a4`, 2026-09-07 (the `assigned_to` fix lands as a new commit on top of this).
- `severity_trend_vs_last_pass`: Phase 2's pass found 1 real gap (reset-password race), fixed. This Phase 3 pass found 1 real gap (unvalidated `assigned_to`), fixed, plus several confirmed-clean checks (BOPLA billing-field exposure, TOCTOU coverage on every check-then-act task/issue write, RLS present+identical across all 6 new tables, no log-injection surface, zero new supply-chain risk). Severity is flat, not rising — one real, cheaply-fixable gap per pass, same order of magnitude as Phase 2, no new category of concern (this finding maps to the same "business-logic/authorization-adjacent input validation" category Phase 2's IDOR/secrets findings also mapped to, not a novel domain nobody had checked before).

**F. Independent pass**

- `security_review_run`: No — `/code-review ultra` has never been run on this repo as of this pass (2026-09-07).

---

### Phase 2 — Employees (2026-09-06, commit `beec50c89b420b3fa6f1b0440073a02ea6cb95bf`)

```
status: complete
phase: Phase 2 — Employees (first vertical slice, CODING_STRUCTURE.md §4 item 3)
scope_files: backend/app/api/routes/employees.py, backend/app/crud.py (employee-scoped fns: create_employee, list_employees, get_employee, set_employee_active, reset_employee_password, _generate_password, _write_audit_log), backend/app/models.py (Profile, AuditLog), backend/app/core/idempotency.py, backend/app/core/supabase_admin.py, backend/app/api/deps.py (RequireOwnerDep/IdempotencyKeyHeader — Phase 1 covered CurrentProfile/require_owner already, re-checked here only for what's new), backend/app/alembic/versions/4cf3e294633d_audit_log_table.py, backend/tests/api/routes/test_employees.py, backend/tests/crud/test_rls_isolation.py
date: 2026-09-06
commit: beec50c89b420b3fa6f1b0440073a02ea6cb95bf
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v1-encoding-sanitization, v2-validation-business-logic, v3-web-frontend-security, v4-api-web-service, v5-file-handling, v6-authentication, v7-session-management, v8-authorization, v9-self-contained-tokens, v10-oauth-oidc, v11-cryptography, v12-secure-communication, v13-configuration, v14-data-protection, v15-secure-coding-architecture, v16-security-logging-error-handling, v17-webrtc, patterns.md — all 17 + patterns read in full this pass (v3/v5/v10/v17 confirmed N/A: no frontend/file-upload/OAuth-exposing/WebRTC surface in this backend-only slice).
- `skills_reopened_fresh`: rest-api-guidelines (http-headers.md, http-requests.md — re-verified Rule 229/230/231 text directly against the file, not trusted from the code's own citations); owasp-asvs-5 (all 17 chapters, listed above); owasp-cheatsheets (list below). Not re-opened: fastapi/postgres-official/supabase-official — Phase 2 introduces no new mechanism from those three beyond what Phase 1 already verified (no new DB-session pattern, no new Supabase Auth API beyond admin_auth, already covered by `supabase_auth`'s own installed source check in D below).
- `cheatsheet_grep_keywords`: `idempot|replay|race condition|TOCTOU|concurrent`; `one-time password|temporary password|initial password|admin.{0,20}reset`; `service.role|admin api|privileged.{0,10}key|service.account`; `audit log|security log|log injection`; `IDOR|object.level|BOLA|insecure direct object`; `mass assignment`; `CSPRNG|secure random|secrets\.token|cryptograph.{0,15}random`; `rate limit|anti.automation|brute.force|account lockout`; `deactivat|account lockout|session revoc|disabled account` — derived from Phase 2's actual mechanisms (idempotency dedup, admin-API password generation, audit_log writes, get_employee's 404-not-403, EmployeeCreate/Update's field sets, `_generate_password`, no rate limiting visible on create/reset), not from cheat-sheet titles.
- `cheatsheet_grep_output`: 8 separate greps across the whole `owasp-cheatsheets/cheatsheets/` directory, ~30/3/4/21/10/4/12/36/6 files matched respectively (full file lists retained in this session's transcript). Read in full: Forgot_Password_Cheat_Sheet.md, Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md, Mass_Assignment_Cheat_Sheet.md, Secrets_Management_Cheat_Sheet.md, Business_Logic_Security_Cheat_Sheet.md, Authorization_Cheat_Sheet.md, Multi_Tenant_Security_Cheat_Sheet.md.

**B. Fixed-domain sweep**

- `auth`: Unchanged from Phase 1 (RequireOwnerDep/CurrentProfile) — Phase 2 adds no new auth mechanism, only consumes the existing one. Confirmed by reading deps.py in full this pass — RequireOwnerDep/IdempotencyKeyHeader are the only new symbols, both thin wrappers over Phase 1's primitives.
- `session_token_lifecycle`: Unchanged from Phase 1 — no new token type or lifecycle introduced.
- `tenant_isolation`: `profiles` and `audit_log` both have `ENABLE`+`FORCE ROW LEVEL SECURITY` and a `tenant_isolation` policy (verified directly in cb67cdb7538a/4cf3e294633d migrations). `test_rls_isolation.py`'s cross-tenant read/update tests exercise `profiles` directly — this is the Phase-2-required test per CODING_STRUCTURE.md item 3, confirmed present.
- `object_level_authz`: `get_employee`'s 404-not-403 pattern (routes/employees.py `update_employee`/`reset_password`) matches both Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md's and Multi_Tenant_Security_Cheat_Sheet.md's own recommended pattern exactly ("Don't reveal if it exists for other tenant").
- `input_validation`: `EmployeeCreate.full_name` has an explicit `max_length=200` ceiling (Input_Validation_Cheat_Sheet.md's "every string needs a real length ceiling" rule, already cited in the code's own comment — re-confirmed present, not just claimed); `email: EmailStr` gets Pydantic's format validation.
- `cors`: Unchanged from Phase 1 — Phase 2 adds no new route registered outside the existing CORS middleware scope.
- `secrets`: `SUPABASE_SECRET_KEY` (core/supabase_admin.py) — confirmed by reading employees.py/crud.py in full that it's never logged, never included in any response model, never reaches a log call anywhere in Phase 2's own code.
- `supply_chain`: Checked `pyproject.toml`'s git history (`git log --oneline -- pyproject.toml`) — only 2 commits ever, `supabase-auth>=2.31.0` was already present in the very first commit alongside Phase 1's own code. Phase 2 introduces zero new third-party dependencies.

**C. Self-check gate**

1. `reapplied_general_principle_to_every_instance`: The "404 not 403 for cross-tenant/cross-role object access" principle (stated once in employees.py's own comment) was checked against every `{id}`-scoped Phase 2 endpoint (`update_employee`, `reset_password`) — both follow it, confirmed by reading each handler, not assumed from the one comment.
2. `stress_tested_design_against_its_own_stated_logic`: `reset_employee_password` claimed safety via its own Idempotency-Key dedup check, but that check is keyed on `(firm_id, actor_id, idempotency_key, endpoint)` — not on the target `employee_id`. Stress-tested this against "what if two *different* Idempotency-Keys hit reset-password for the *same* employee concurrently": no row lock existed (unlike `_lock_task`/`_lock_issue`'s established pattern for the same class of risk elsewhere in this file). Real finding — fixed this pass (see D below), not just documented, since the project's own existing pattern made the fix cheap and low-risk.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B above run in full regardless of which mechanism the conversation happened to focus on first.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: rest-api-guidelines' http-headers.md/http-requests.md were re-opened fresh this pass specifically to verify Rule 229/230/231's exact wording against employees.py/idempotency.py's own citations, rather than trusting those citations because the skill was read earlier in the project's history.
5. `compound_source_not_partial`: Every finding cites the ASVS requirement ID *and* a cheat sheet *and*, where relevant, installed library source — e.g. the CSPRNG finding cites ASVS 11.5.1 + patterns.md's RNG table + `secrets.token_urlsafe`'s actual bit count, not just one of the three.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 8 keyword greps across the whole `owasp-cheatsheets/cheatsheets/` directory (not the 4-5 titles that sound relevant from memory) — this is what surfaced `Mass_Assignment_Cheat_Sheet.md` and `Secrets_Management_Cheat_Sheet.md` for keywords neither title suggests on its own.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: `reject_if_idempotency_key_used`/`record_idempotency_key` (core/idempotency.py) were built as a *new*, deliberately separate mechanism from the existing `with_idempotency` helper specifically because reset-password's response contains a one-time secret `with_idempotency`'s cache-and-replay design would have persisted for 24h (already documented in the code's own comment, re-confirmed accurate this pass by reading `with_idempotency`'s actual caching behavior directly).

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: `backend/.venv/Lib/site-packages/supabase_auth/_sync/gotrue_admin_api.py:120-132` (`create_user` → `POST admin/users`) and `:165-180` (`update_user_by_id` → `PUT admin/users/{uid}`) — read directly this pass, matches `core/supabase_admin.py`'s own comment claim exactly, not trusted from the comment alone.
- `fix_verified_by_real_command_output`: Fixed `reset_employee_password` (backend/app/crud.py) to row-lock the profile via `.with_for_update()` before calling the Admin API, matching `_lock_task`/`_lock_issue`'s established pattern. Verified via the actual CI-equivalent commands, not assumed: `uv run pyright` → `0 errors, 0 warnings, 0 informations`; `uv run pytest -q` → `88 passed, 6 skipped, 2 warnings` (identical pass count to the pre-fix baseline — no regression); `ruff check app/crud.py` → `All checks passed!`. The pre-existing `test_reset_password_writes_audit_log` (tests/crud/test_employee_audit_log.py) already calls the real (non-mocked) `crud.reset_employee_password` against a real SQLite session, so it already exercises the new lock query's single-caller correctness — its continuing to pass is real evidence the lock query itself is correct, not just that nothing crashed. True concurrent-race behavior is a Postgres-only property (SQLite ignores `.with_for_update()`), same documented limitation the project already states for `_lock_task` in test_task_transitions.py — no new test file added, consistent with that existing convention.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5, L1+L2, scoped to Phase 2's Employees vertical slice (files listed in `scope_files` above) as of commit `beec50c89b420b3fa6f1b0440073a02ea6cb95bf`, 2026-09-06 (row-lock fix lands as a new commit on top of this).
- `severity_trend_vs_last_pass`: Phase 1's pass found 3 fixed gaps (charset, auth-failure logging, TLS sslmode) plus 2 documented-not-fixed items (missing FK, RS256). This Phase 2 pass found 1 real gap, fixed this pass (reset-password race), plus several confirmed-clean checks and two ASVS-L3/out-of-scope observations (6.4.6 admin-learns-password, 13.2.1 static admin API key — both inherited platform constraints, not new). Severity is diminishing, not rising — no new category of concern surfaced (everything found maps to already-known categories: concurrency, secrets, IDOR — all previously covered ground, not a new domain nobody had checked before).

**F. Independent pass**

- `security_review_run`: No — `/code-review ultra` has never been run on this repo as of this pass (2026-09-06). Phase 1's own audit predates this checklist file's existence, so it has no separate entry here — only this Phase 2 pass and onward are tracked in this file.
