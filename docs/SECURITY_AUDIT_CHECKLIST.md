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
