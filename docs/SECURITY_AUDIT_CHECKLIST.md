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

## Completed Audits

### Phase 4 — Employees (Frontend Feature Slice + Real-Backend Contract Test) (2026-09-11, commit `4cba514`)

```
status: complete
phase: Phase 4 — Employees (frontend feature slice + real-backend contract test), CODING_STRUCTURE.md §4 item 5, first post-auth Phase 4 resource slice — never through this checklist before (Phase 4 Step 1's pass covered scaffolding+auth only, no resource screen existed yet)
scope_files: frontend/src/features/employees/**, frontend/src/lib/{api-client,query-client,tenant-query-key}.ts, frontend/src/app/{router,provider}.tsx, frontend/src/stores/session-store.tsx, frontend/src/testing/mocks/handlers.ts, frontend/contract-tests/employees.contract.test.ts, frontend/vitest.contract.config.ts, frontend/tsconfig.node.json, frontend/vite.config.ts, .github/workflows/ci.yml (e2e job's contract-test steps)
date: 2026-09-11
commit: 4cba514 (base HEAD at audit start — this pass's own fixes, plus 2 test files from the earlier mutation-testing-gap fix, land on top, uncommitted, not yet pushed per explicit instruction)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v1-encoding-sanitization, v2-validation-business-logic, v3-web-frontend-security, v4-api-web-service, v5-file-handling, v6-authentication, v7-session-management, v8-authorization, v9-self-contained-tokens, v10-oauth-oidc, v11-cryptography, v12-secure-communication, v13-configuration, v14-data-protection, v15-secure-coding-architecture, v16-security-logging-error-handling, v17-webrtc, patterns.md — all 18 read fresh this pass, not copied from Phase 4 Step 1's conclusions. v2/v3/v7/v8/v14/v16 read in full first (mechanisms this slice actually touches); v1/v4/v6/v9/v11/v12/v13/v15 read in full second (re-derived, not skipped, even though most ended up N/A/unchanged); v5/v10/v17 re-confirmed N/A via a targeted grep of `frontend/src/features/employees` for upload/file-handling terms (zero matches) plus direct re-reads of each chapter's own scope statement (no file upload, no OAuth/OIDC delegated-authz flow — Supabase email/password only, no WebRTC anywhere in this project).
- `skills_reopened_fresh`: owasp-asvs-5 (all 18, above); owasp-cheatsheets (6 whole-directory greps, below); `rest-api-guidelines` Rule 230 (re-verified via the background-agent pass earlier this same session, for the reset-password idempotency-key ownership question — carried into this audit's Idempotency-Key/CSPRNG reasoning, not re-fetched a second time since it's the same sub-question); TanStack Query's own official docs (2 fresh `WebFetch` calls this pass: `invalidateQueries` prefix-matching semantics, confirming `["employees"]` invalidates `["employees", firmId]`). Not reopened: `bulletproof-react`/`tauri-official`/`supabase-official` — this slice introduces no new pattern from those beyond what Phase 4 Step 1 and this session's earlier employees-slice work already verified against them.
- `cheatsheet_grep_keywords`: `client.side cach|browser cach|query cach|stale data|logout|sign.?out|session terminat`; `one.time password|temporary password|generated password|shown once|displayed once`; `CI/CD|pipeline secret|environment variable|GITHUB_ENV|mask.{0,10}(secret|log)|log.{0,10}mask`; `RBAC|role.based|client.side authoriz|UI.{0,10}(hide|display|render)|hide.{0,10}button`; `idempot|replay`; `multi.tenant|cross.tenant|tenant isolation` — 6 greps derived from this slice's actual mechanisms (TanStack Query client-side cache, one-time generated-password display, the CI contract-test's real bearer token, Owner-only route gating, the Idempotency-Key client-ownership fix, the first-ever client-side tenant-scoped cache in this codebase), not from cheat-sheet titles.
- `cheatsheet_grep_output`: 6 separate greps across the whole `owasp-cheatsheets/cheatsheets/` directory (14/3/31/12/9/9 files matched respectively). Read in full this pass: `Session_Management_Cheat_Sheet.md` (localStorage/sessionStorage scope/duration sections — confirmed N/A verbatim to this specific finding since TanStack Query's cache is in-memory JS, not Web Storage, but the underlying "session-bound data shouldn't outlive the session" principle still applies); `GitHub_Actions_Security_Cheat_Sheet.md`'s "Mask sensitive data" section (surfaced by the CI-secret keyword — direct source for the `::add-mask::` fix below); `Multi_Tenant_Security_Cheat_Sheet.md`'s "Cache & Session Isolation" section (surfaced by the multi-tenant keyword — direct source for the tenant-scoped-cache-key fix below, including its explicit "bad practice: shared cache keys without tenant prefixes" line). `Multifactor_Authentication_Cheat_Sheet.md`'s OTP-handling section (re-surfaced by the one-time-password keyword, already applied in this session's earlier employees-slice work — re-confirmed still followed, not a new finding).

**B. Fixed-domain sweep**

- `auth`: Unchanged from Phase 1/4-Step-1 — no new auth mechanism. `OwnerRoute` (router.tsx) re-verified still correctly gates `/employees` after this pass's `SessionState` change (added `firmId`, did not touch `role`) — confirmed via `router.test.tsx`'s existing `OwnerRoute` tests still passing (28/28 total, below).
- `session_token_lifecycle`: **Real finding, fixed this pass.** `SessionProvider`'s `onAuthStateChange` listener updated `session`/`role`/`mustChangePassword` state on every transition but never cleared TanStack Query's cache. Confirmed by reading `account-menu.tsx` (calls only `supabase.auth.signOut()`), `session-store.tsx`, and `query-client.ts` (a bare `new QueryClient()`, no lifecycle wiring) fresh this pass, not from an earlier read. ASVS 5 §14.3.1 ("authenticated data cleared from client storage after client/session termination") and Multi_Tenant_Security_Cheat_Sheet.md's cache-isolation guidance both apply: route-level redirect-to-`/login` unmounts the screens but the query cache is a separate in-memory store that outlives that, and on a shared device a second user signing in afterward would see the first user's cached employee list until their own first refetch overwrites it. Fixed: `session-store.tsx` calls `queryClient.clear()` whenever `onAuthStateChange` delivers a null session (covers explicit logout, forced revocation, and expiry uniformly — not just the "Log out" menu click).
- `tenant_isolation`: **Real finding, fixed this pass, same root cause as above.** `employeesQueryKey` was the bare constant `["employees"]` — Multi_Tenant_Security_Cheat_Sheet.md's own stated bad practice ("shared cache keys without tenant prefixes") and ASVS 5 §8.4.1 ("multi-tenant apps enforce cross-tenant controls"). This is the first TanStack-Query-backed slice in the codebase, so this category of mechanism literally didn't exist to check before now. Fixed: `get-employees.ts` now exports `employeesQueryKey(firmId)` (query) and `employeesQueryKeyPrefix` (mutation invalidation, using TanStack Query's default prefix/fuzzy matching — verified against its own docs, not assumed); `session-store.tsx`'s `SessionState` gained `firmId`, decoded from the same JWT `app_metadata` already trusted for `role`. Server-side RLS already makes a real cross-tenant *read* impossible regardless (defense-in-depth, not the only layer) — this fix closes the client-side, same-device, stale-cache-flash gap specifically.
- `object_level_authz`: N/A for this slice's own new code — every `{id}`-scoped call (`update_employee`, `reset_password`) uses an `employeeId` sourced from the already-fetched, already-tenant-scoped list (`useEmployees()`), never user-typed or URL-supplied, and the real object-level check is backend-enforced (`employees.py`'s 404-not-403 pattern, audited Phase 2). Confirmed by reading `employee-list.tsx`/`reset-password-dialog.tsx` fresh this pass — no route param, no free-text ID entry anywhere in this UI.
- `input_validation`: `employeeCreateSchema` (Zod) re-confirmed present and, as of this session's earlier mutation-testing work, now actually *tested* (empty-submit and overlong-name cases, negative-control-verified) — closing a gap that existed at merge time and was found by mutation testing, not by this audit pass, but re-verified still passing here (28/28, below). No `dangerouslySetInnerHTML`/`innerHTML`/`document.write`/`eval(` anywhere in `frontend/src/features/employees` or `frontend/contract-tests` — grepped fresh this pass, zero matches (ASVS 3.2.2/1.3.2).
- `cors`: N/A, unchanged from Phase 4 Step 1 — frontend introduces no new cross-origin behavior; still server-enforced (`main.py`'s `CORSMiddleware`).
- `secrets`: **Real finding, hardened this pass.** The CI `e2e` job's new "Seed a real owner account" step mints a genuine ES256 bearer token (`CONTRACT_TEST_TOKEN`) and writes it to `$GITHUB_ENV`. Checked whether it leaks into CI logs: `gh run view --log` showed `***`, but that alone doesn't prove real masking (could be `gh` CLI's own display redaction) — decisively verified by fetching the **raw, unprocessed log directly via `gh api repos/.../actions/jobs/.../logs --allow-escape-sequences`** (bypasses any client-side redaction) and confirming zero `eyJ...`-prefixed JWT text appears anywhere, with `***` present 108 times including at both `SUPABASE_SECRET_KEY`/`CONTRACT_TEST_TOKEN` lines. Real masking is genuinely happening — but two web searches found no official GitHub documentation of an automatic name-based masking heuristic for custom `$GITHUB_ENV` values (only `secrets.*`-context values are documented as auto-masked); `GitHub_Actions_Security_Cheat_Sheet.md` explicitly says to use `::add-mask::` for anything sensitive that isn't a registered secret, not to rely on undocumented behavior. Added `print('::add-mask::' + token)` before the `$GITHUB_ENV` write, making the masking explicit rather than dependent on unconfirmed runner behavior. Separately reasoned, not just grepped-and-flagged: the CI script's own `password = 'contract-Test-Password-9'` constant is not a real secret under ASVS 13.3.1's scope — it seeds a disposable local Supabase stack that's destroyed at the end of every job run, never a persistent credential.
- `supply_chain`: `@tanstack/react-query` (added this session) — official `@tanstack` npm-scoped package, no dependency-confusion risk (ASVS 15.2.4). Stryker Mutator (`@stryker-mutator/core`/`vitest-runner`) was installed then fully uninstalled this session after proving non-functional against Vitest 5 (unrelated bug, not a security finding) — confirmed cleanly removed: `npm audit` → **0 vulnerabilities** (down from the 2 moderate, dev-only, transitive `qs` findings Stryker's install briefly introduced).

**C. Self-check gate (mapped 1:1 to skill-verification-discipline.md's 7 failure modes)**

1. `reapplied_general_principle_to_every_instance`: The tenant-scoped-cache-key principle was applied to the only query this slice has (`get-employees.ts`) — since it's the first TanStack-Query slice, there's exactly one instance to fix, but the pattern (prefix constant for invalidation + parameterized key for the query) is now documented in code comments specifically so the *next* slice's author applies it too, not just this one.
2. `stress_tested_design_against_its_own_stated_logic`: Stress-tested `crypto.randomUUID()`'s suitability for the Idempotency-Key against ASVS 11.5.1/`patterns.md`'s own explicit warning ("UUIDs are not automatically CSPRNG-strength... use an explicit CSPRNG for tokens/secrets, not a UUID library, unless you've verified the source"). Checked against the requirement's actual *purpose* (preventing an attacker from guessing/forging a security-sensitive value), not its literal text: the Idempotency-Key is a dedup correlation key scoped to an already-authenticated, already-tenant-scoped caller — guessing another value grants no capability the caller doesn't already have — so this is confirmed **not** a violation, not silently assumed clean.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B run in full — the session-token-lifecycle/tenant-isolation findings emerged specifically *from* running the sweep systematically, not from the conversation's stated focus (mutation-testing gaps / contract tests), which is exactly the failure mode this discipline exists to prevent.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: `patterns.md`'s CSPRNG/UUID section was reopened fresh this pass for the Idempotency-Key stress-test (a different question from the earlier `rest-api-guidelines` Rule 230 read, which was about key *reuse-on-retry*, not randomness strength) — not assumed covered by that earlier read.
5. `compound_source_not_partial`: The cache-clearing/tenant-scoping finding cites ASVS 14.3.1 **and** 8.4.1 **and** `Multi_Tenant_Security_Cheat_Sheet.md`'s explicit text **and** TanStack Query's own official invalidation docs (fetched fresh) — four sources. The CI-masking finding cites `GitHub_Actions_Security_Cheat_Sheet.md` **and** a decisive raw-log empirical check (not just a web search) — two independent forms of evidence, not one assumed-sufficient source.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 6 keyword greps across the whole directory this pass (listed in A) — surfaced `GitHub_Actions_Security_Cheat_Sheet.md` and `Multi_Tenant_Security_Cheat_Sheet.md`'s cache-isolation section, neither an obvious hit from title alone for a frontend employees screen.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: `queryClient` (the single shared TanStack Query instance) gained a new caller this pass (`session-store.tsx`, beyond its original provider-wiring use) — asked what's different: `.clear()` is a safe, side-effect-free operation on the client's own in-memory cache with no data-shape risk analogous to the `with_idempotency`/reset-password one-time-secret precedent.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: TanStack Query v5's `invalidateQueries` prefix-matching behavior — verified via `tanstack.com`'s own official invalidation-guide docs (`WebFetch`, this pass), not assumed from general React Query familiarity. GitHub Actions' log-masking behavior — verified empirically via `gh api repos/789123654/job-allocation-system-/actions/jobs/103237061798/logs --allow-escape-sequences` (the raw stored log, not `gh run view`'s display layer): 108 literal `***` occurrences, zero `eyJ...`-prefixed JWT text anywhere, confirming real masking is already active — cross-checked against `GitHub_Actions_Security_Cheat_Sheet.md`'s explicit "don't rely on this, use `::add-mask::`" guidance since the exact automatic-masking mechanism isn't officially documented.
- `fix_verified_by_real_command_output`: `npm run lint` → `0 errors` (5 pre-existing warnings, unrelated); `npm run typecheck` → clean; `npm run test` → **28 passed**, `6 test files`; `npm run build` → succeeded — all re-run and re-confirmed green after the code-review round's 3 additional fixes (Section F), not just once before them. Negative control on the cache-clearing fix: temporarily removed the `queryClient.clear()` call, reran `session-store.test.tsx` alone → **1 failed** (`expected [ { id: 'e1' } ] to be undefined`, i.e. the stale data survived exactly as the finding predicted), restored the fix, reran full suite → 28/28 passed again.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5, L1+L2, scoped to the Employees frontend feature slice + real-backend contract-test infra (`scope_files` above) as of base commit `4cba514` (2026-09-11), plus 3 test files added/fixed locally this session (2 from the earlier mutation-testing pass, 1 new from this audit) — none pushed yet, per explicit instruction.
- `severity_trend_vs_last_pass`: Phase 4 Step 1's pass found 1 fixed gap (missing CSP directives) + 1 documented-not-fixed item (no prod API origin yet). This pass found 2 real, fixed gaps: client-side query-cache tenant isolation/session-termination clearing, and CI secret-masking hardening. Not read as "rising severity" in an alarming sense — the cache-isolation category *could not have been checked before this pass*, since this is the first slice in the whole codebase with any TanStack-Query server-cache state at all; finding a real gap the first time a new mechanism exists is the expected, healthy outcome of running the sweep, not a sign of degrading quality. Honest bound: not verified exhaustively across every session-termination path — e.g. a force-quit Tauri process runs no JS at all (so nothing to clear, and nothing exposed either, since the process itself is gone) — scoped to paths that stay within the running JS process (explicit logout, detected revocation/expiry via `onAuthStateChange`).

**F. Independent pass**

- `security_review_run`: **Yes — `code-review` skill (medium effort, not the paid `/code-review ultra`), 2026-09-11, this pass.** 8 finder agents (reuse, cross-file-tracing, simplification, efficiency, conventions/CLAUDE.md, altitude/structure, removed-behavior, line-by-line-diff) ran against this pass's own diff (the two mechanisms just added: cache-clearing + tenant-scoped keys). Real findings, triaged:
  - **Fixed — genuine correctness gap** (removed-behavior agent): `useEmployees()`'s `enabled: firmId !== null` guard, if `firmId` ever stayed null for an *authenticated* session (malformed/stale JWT missing `app_metadata.firm_id` — a backend provisioning bug, not the transient initial-load case it was written for), would leave the query permanently disabled with no error surfaced — an infinite "Loading…" spinner. Fixed: `employee-list.tsx` now checks `useSession()`'s own `firmId`/`isLoading` directly and shows an explicit error state once the session has finished loading and `firmId` is still null.
  - **Fixed — real gap in the fix itself** (line-by-line-diff agent): the cache-clear-on-null-session logic lived only in the `onAuthStateChange` callback, not the initial `getSession()` resolution — since `queryClient` is a module-level singleton outliving any one `SessionProvider` mount, a remount (React StrictMode's dev double-invoke, or a future routing change) whose initial `getSession()` resolves null would have left a prior mount's cached data sitting there uncleared, silently reopening the exact gap this pass exists to close. Fixed: unified both paths through one `applySessionUpdate` function.
  - **Fixed — structural/altitude** (altitude agent): the tenant-scoped-key pattern was implemented entirely inside `features/employees/api/get-employees.ts` with no shared mechanism — every future Phase-3-mirrored slice (job types, tasks, issues, notifications) would have to rediscover and reimplement it by hand, with nothing catching a slice that just writes `queryKey: ["tasks"]` the "happy path" way. Extracted `lib/tenant-query-key.ts` (`tenantQueryKey`/`tenantQueryKeyPrefix`), now the one place this pattern is documented and reused.
  - **Addressed via comment, not code** (simplification agent): flagged the two-part key + `clear()`-on-logout as two mechanisms that could look redundant/competing to a future reader. They're deliberately complementary (preventive key-scoping vs. reactive full-clear), not overlapping by accident — added an explicit comment stating this, specifically so a future "let's remove the redundant one" edit doesn't reopen the gap.
  - **Reasoned, not fixed** (simplification/removed-behavior agents, 2 lower-severity items): `useEmployees()` now hard-requires a `SessionProvider` ancestor (throws otherwise) — acceptable, since the whole app is always wrapped in one at the root (`app/provider.tsx`), matching every other screen's existing dependency; the `"unauthenticated"` placeholder query-key value is TanStack Query's standard documented "dependent query" pattern (paired with `enabled`), not an ad-hoc invention — now centralized in one place instead of per-feature, addressing the "future refactor could drop the guard" concern by making it one documented function rather than several copies.
  - **Not addressed, out of this pass's scope** (efficiency agent): `queryClient.clear()` on logout can fire a brief burst of wasted in-flight refetches for any still-mounted query before the auth redirect unmounts the tree — a real but minor performance nit, not a security property, and the user is navigating away in the same render cycle regardless; (reuse agent): `mockSession`-shaped test setup is duplicated between `router.test.tsx` and `employee-management-page.test.tsx` rather than shared — a test-maintenance concern, not a security finding.
  - Verified after fixes: `npm run lint`/`typecheck`/`test` (28/28)/`build` all green again (below).

### RLS Tenant-Context Loss on Post-Commit Queries (2026-09-08, commit `d16a978`)

Not a phase audit — found by Schemathesis (`tests/api/test_schema_fuzz.py`, added this same
session) fuzzing 4 endpoints into a crash, then traced to a shared root cause across 6 call sites,
none of which any prior audit had flagged.

```
status: complete
phase: N/A — cross-cutting defect fix (backend/app/core/db.py, backend/app/crud.py, 4 route files)
scope_files: backend/app/core/db.py, backend/app/crud.py,
  backend/app/api/routes/{tasks,employees,job_types,notifications}.py,
  backend/tests/api/test_schema_fuzz.py
date: 2026-09-08
commit: d16a978
```

**What was found:** `get_current_profile` (api/deps.py) sets `app.current_tenant` — the GUC every
RLS policy filters on — with `set_config(..., true)`: `is_local=true`, deliberately, so a pooled
connection can never carry one request's tenant context into another's under Supavisor pooling.
That context is therefore scoped to exactly one transaction. Six `crud.py` functions called
`session.commit()` mid-request and then read again afterward in the same session — five via a
`session.refresh()` immediately after commit (`create_job_type`, `set_job_type_active`,
`update_task_deadline`, `mark_notification_read`, `set_employee_active`), one via a genuine new
query (`_ensure_deadline_notifications` → `list_notifications`). Every one of those reads ran in a
new transaction with no tenant context. Depending on whether the specific pooled Postgres
connection had ever seen a tenant context set on it before, the read either matched 0 rows
(`session.refresh()` raising `InvalidRequestError: Could not refresh instance`) or crashed with
`psycopg.errors.InvalidTextRepresentation: invalid input syntax for type uuid: ""` — a
misdiagnosed-at-first symptom (initially logged as "empty-string input" before being traced to its
real cause) whose SQL/parameters shown in the error message didn't even belong to the statement
that actually failed, which is what made this take real digging, not a quick read of the traceback.

**Why this wasn't caught by any prior audit:** the pattern — `session.add(); session.commit();
session.refresh(); return obj` — is FastAPI's own official tutorial idiom (`fastapi` skill,
`guide/tutorial/sql-databases.md`), copied faithfully across 4 separate commits from the project's
very first scaffolding commit (`2f5e940`) through Phase 3's notifications slice (`2d22757`) — `git
blame` confirms zero comment anywhere justifying it, unlike this codebase's usual documentation
discipline for every other non-obvious choice, which is itself the tell that it was never checked
against this project's specific transaction-scoped RLS design. Every hand-written route test
(`tests/api/routes/*.py`) uses a `MagicMock()` session deliberately (no real DB needed for
dependency-override-style route tests) — a mock has no transactions and no RLS, so it can never
reproduce this. Only a real Postgres connection, exercised enough times to land on a pooled
connection that had already seen a tenant context once, ever surfaces it — exactly the kind of gap
`skill-verification-discipline.md` failure mode 9 already names (a mechanism verified present in
the code, never verified effective at runtime) — this is a fresh, distinct instance of that same
class, one layer over: not the lock mechanism itself, but the session lifecycle around it.

**Fixed:**
- `app/core/db.py`: `expire_on_commit=False` on the request-scoped `Session` — root-cause fix.
  SQLAlchemy's default (`True`) would keep triggering the same implicit reload on *any* post-commit
  attribute read even with every explicit `.refresh()` call deleted (the route layer reads
  `job_type.id`/`.name`/etc. immediately after `crud.create_job_type()` returns, to build the
  response). Safe specifically because `get_session()` hands each request its own session that
  never outlives that request — no cross-request staleness risk to trade away.
- 5 redundant `session.refresh()` calls deleted — confirmed via each model's own field list
  (`JobType`/`Task`/`Notification`/`Profile`) that nothing is DB-computed, so refresh never pulled
  back anything real to begin with.
- `_ensure_deadline_notifications` re-sets `app.current_tenant` after its own commit — Postgres-only
  (`session.get_bind().dialect.name == "postgresql"`), since `tests/crud/test_notification_generation.py`
  deliberately runs this same function against real SQLite (no RLS there to restore context for,
  and no `set_config` function on SQLite at all) — caught by a real regression on first attempt,
  not assumed safe.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: the `expire_on_commit` default and
  its interaction with post-commit attribute access wasn't taken from memory — confirmed by
  reproducing the crash directly against a real disposable `postgres:17` container with SQLAlchemy
  engine `echo=True` and `poolclass=NullPool`, watching the exact statement sequence, before
  writing any fix (`InvalidRequestError: Could not refresh instance` under `NullPool`, the same
  failure without the misleading uuid-cast symptom the pooled engine produced).
- `fix_verified_by_real_command_output`: full backend suite `123 passed` against a real disposable
  `postgres:17`; `tests/crud/test_concurrency.py`+`tests/api/test_schema_fuzz.py` run 3x
  consecutively, `21 passed` each run, no flakiness; `uv run ruff check .` / `uv run pyright` →
  clean both times (once before, once after fixing a real regression the first fix attempt caused
  in `tests/crud/test_notification_generation.py`).

**E. Bounded claim**

- `standard_and_scope`: `Input_Validation_Cheat_Sheet.md`'s numeric-range-check rule (for the
  `offset` bound) plus this project's own RLS/session-lifecycle design, scoped to the 6 call sites
  named above as of commit `d16a978` — not a claim that every `session.commit()` in the codebase
  has been re-audited for this shape, only that every one *at the time of this pass* was checked
  (see grep evidence in this session's own record: every `session.commit()` in `crud.py` was read
  in context before deciding fix vs. no-fix-needed).
- `severity_trend_vs_last_pass`: Same trend as the Concurrency Defect entry above — a real,
  previously-invisible production bug (intermittent 500s on real user actions, not a test-only
  artifact), found only because a new tool (Schemathesis) exercised paths no hand-written test
  ever did. Confirms the same lesson that entry already named: "fixed and verified" is only as
  strong as what actually got exercised, not what was theoretically covered.

**F. Independent pass**

- `security_review_run`: No — `/code-review ultra` still hasn't been run on this repo as of this
  pass (2026-09-08).

A 5th, separate bug surfaced once the above unblocked `POST /job-types` far enough for
Schemathesis to reach it — see the next entry for the fix.

**Follow-up (2026-09-09) — the "two shapes" claim above is now stale; a 2nd and 3rd instance of
this exact mechanism were found and fixed, neither a re-audit of the 6 call sites above, both new
code paths this original pass never touched:**

- **2nd instance, PR #28**: `_ensure_deadline_notifications` itself — the very function this
  entry's own fix patched — regressed. PR #20 (2026-09-09, `ix_notifications_dedup`) added an
  `except IntegrityError: session.rollback()` branch for the notification-dedup race, and the
  line right after it read `actor.firm_id` to rebuild the re-`set_config()` call this entry's fix
  had put there. `Session.rollback()` (unlike `commit()`, which this entry's `expire_on_commit=
  False` fix only opts out of for *commit*) always expires every object in the session — so that
  read fired the identical lazy-refresh-with-no-tenant-context crash this entry describes, from a
  code path added after this entry was written, and therefore never covered by it. Found by
  `tests/crud/test_concurrency.py`'s `test_concurrent_deadline_poll_dedups_correctly` — a real
  `threading.Barrier(2)`-against-Postgres test, this bug's own class of "only a real race surfaces
  it" the same way the original finding above required a real pooled connection to surface.
- **3rd instance, PR #29**: `with_idempotency` (`core/idempotency.py`) — same mechanism, a
  different function entirely, never in `crud.py` so never in this entry's original 6-function
  scope. Its own `except IntegrityError: session.rollback()` branch (a pre-existing pattern, not
  new code) read `actor.firm_id`/`actor.id` afterward to look up which concurrent retry won —
  worse than the 2nd instance, since this function had no re-`set_config()` at all, so even past
  the actor-refresh crash, the winner-lookup query itself also ran with no tenant context
  (`idempotency_keys` has RLS too). Backs 6 mutating endpoints (`create_task`, `submit_task`,
  `mark_task_billed`, `review_task`, `create_task_issue`, `resolve_issue`). Found by sweeping every
  `session.commit()`/`session.rollback()` call in `backend/app/` after the 2nd instance, rather than
  waiting for a 4th to surface on its own — verified by the same stash-the-fix/confirm-it-fails,
  restore-the-fix/confirm-it-passes discipline as the 2nd instance, against real Postgres.

**Revised bound, replacing the "not a claim that every `session.commit()`... has been re-audited"
line above**: as of 2026-09-09, every `session.commit()`/`session.rollback()` call site in
`backend/app/` (not just `crud.py`) *has* now been enumerated and checked for this mechanism — 4
total rollback sites exist in the whole backend, 3 safe (2 already were; `_ensure_deadline_
notifications` is now the 3rd, fixed above), 1 that was live and is now fixed
(`with_idempotency`). Also checked and ruled out as candidates: nested transactions/savepoints
(none exist anywhere in the codebase), middleware and exception handlers in `main.py` (none touch
`session` or any ORM object), and `backend/loadtest/` (raw autocommit `psycopg`, never goes through
the `Session`/`app.current_tenant` mechanism at all). This bound is still scoped to *this specific
mechanism* — a transaction-ending call followed by an ORM-object attribute read in a `SET LOCAL`-
scoped RLS session — not a claim that no other defect class remains.

**Note (2026-09-10):** the per-site enumeration above ("4 total rollback sites") was superseded by
the `core/db.commit_or_recover` consolidation (PR #32) — `backend/tests/core/test_db.py` is now the
source of truth for the accounted-for `session.rollback()` sites (3, none in the notification path).
Separately, the notification scan body moved out of `_ensure_deadline_notifications` into
`crud._scan_firm_deadlines` (firm-wide refactor, 2026-09-10); `_ensure_deadline_notifications` still
wraps it with `commit_or_recover(session, actor)` exactly as this entry describes — the
commit/rollback/tenant-context behaviour audited here is unchanged.

### NUL Bytes Rejected in Client-Controlled Strings (2026-09-08, commit `41cebb2`)

Found immediately after the RLS entry above, by the same test, once that fix unblocked
`POST /job-types` far enough for Schemathesis to reach it.

```
status: complete
phase: N/A — cross-cutting input-validation gap (backend/app/core/validation.py, 4 route files)
scope_files: backend/app/core/validation.py (new),
  backend/app/api/routes/{employees,job_types,tasks,issues}.py,
  backend/tests/api/test_schema_fuzz.py
date: 2026-09-08
commit: 41cebb2
```

**What was found:** a `name` containing a NUL byte (`\x00`) crashed with `psycopg.DataError:
PostgreSQL text fields cannot contain NUL (0x00) bytes` instead of a clean 422. NUL (U+0000) is a
valid Unicode/JSON string character, so Pydantic's plain `str` field never rejects it — but
psycopg encodes every bound string parameter as a C string, and Postgres `text`/`varchar` columns
reject NUL outright, in an `INSERT` or a `WHERE` clause alike (the crash happens client-side, at
parameter encoding, before the query reaches the server — so a query-filter field is just as
exposed as a body field).

**Fixed:** `app/core/validation.py` adds `NoNulStr`, a reusable
`Annotated[str, AfterValidator(...)]` type, applied to every client-controlled free-text/filter
string field across the API — not just `job_types.name`, the one that happened to crash first:
`employees.full_name`, `job_types.name`, `tasks` title/description, task-review notes/remaining-
work-description/billing-description/billing-recipient, issue description/resolution-notes/
remaining-work-description, and `list_tasks`'s `status`/`task_type` query filters.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: Pydantic v2's `Annotated[str,
  AfterValidator(...)]` composition with both `Field(...)` constraints and FastAPI's `Query(...)`
  metadata wasn't assumed — each composition shape was tested standalone (a bare `BaseModel`, then
  a real `FastAPI`/`TestClient` route) before being applied to any real route file.
- `fix_verified_by_real_command_output`: full suite `124 passed`, `ruff`/`pyright` clean, against a
  real disposable `postgres:17`; schemathesis suite run 3x with different random seeds (no
  exclusions active), all pass.
- Negative control: reverted `job_types.name` to plain `str`, reran the schemathesis suite 3x —
  caught the regression 1/3 runs. Stated plainly, not overclaimed: this reflects Hypothesis's
  unseeded random generation at `max_examples=20`, not a flaw in the fix itself, which was
  separately proven correct by a direct Pydantic-level assertion (`M(name="a\x00b")` raises)
  before being applied anywhere.

**E. Bounded claim**

- `standard_and_scope`: general input-validation practice (reject what the storage layer can't
  hold), scoped to every field named above as of commit `41cebb2` — not a claim that every string
  field anywhere in the codebase (e.g. response-only fields, which only ever echo already-valid
  DB data) was touched, only every client-controlled one.
- `severity_trend_vs_last_pass`: Same category as the RLS entry immediately above — found by the
  same tool, same session, exercising a path four completed audits and every hand-written test
  never reached.

**F. Independent pass**

- `security_review_run`: No — `/code-review ultra` still hasn't been run on this repo as of this
  pass (2026-09-08).

### Concurrency Defect — Identity-Map Staleness Defeats Row Locks (2026-09-07, commit `8565734`)

Not a phase audit — a targeted fix pass triggered by a real CI failure, tracked here at the same
rigor because of what it found: a previously "audited and fixed" mechanism (Phase 2's
reset-password race guard, commit `503f73c`) never actually worked as documented, and a brand-new
Phase 3 mechanism (`_lock_issue`) never worked either. Full narrative and reasoning trail in this
session's own record; this entry is the evidence summary.

```
status: complete
phase: N/A — cross-phase defect fix (crud.py's three .with_for_update() call sites)
scope_files: backend/app/crud.py (_lock_task, _lock_issue, reset_employee_password),
  backend/tests/crud/test_concurrency.py
date: 2026-09-07
commit: 8565734
```

**What was found:** `.with_for_update()` takes the real Postgres row lock — that part always
worked. But every caller in this codebase does an *unlocked* read of the row earlier in the same
request (`get_task`/`get_issue`/`get_employee`), then calls the locking function in the *same*
SQLAlchemy `Session`. SQLAlchemy's identity map returns the session's already-cached Python object
for a given primary key by default — `.with_for_update()` alone does not force a refresh of that
object's attributes from the row the query just (re-)fetched. So the lock blocks correctly at the
database level, but the Python object the code then reads (`if locked.status != "open": ...`)
still holds pre-lock, stale values. Fix: `.execution_options(populate_existing=True)` on each
locking query, which forces SQLAlchemy to overwrite the cached object's attributes with the fresh
row.

**Why this wasn't caught by four prior completed audits, CI's own CodeQL/Semgrep, or `Business_
Logic_Security_Cheat_Sheet.md`'s own review checklist:** `.with_for_update()` is the textbook-
correct primitive, in the textbook-correct place — nothing about the *code's shape* is wrong,
so neither a human reading the diff nor a signature-matching SAST tool (CodeQL/Semgrep) had
anything to flag. `Business_Logic_Security_Cheat_Sheet.md:7` names this class directly: "No
scanner will find these bugs for you... the bug isn't in any single function." The property only
breaks under two genuinely concurrent database sessions racing the same row — no test in the
project exercised that before this session's `test_concurrency.py` (Phase 2's own reset-password
fix was verified only against SQLite, which doesn't enforce `.with_for_update()` at all and
couldn't have caught this either way — a limitation that pass's own record explicitly named at
the time, D section, rather than assuming coverage it didn't have).

**Fixed, with independent verification per call site:**
- `_lock_task` (`submit_task`/`mark_task_billed`/review reassignment) — fixed 2026-09-04 per its
  own docstring, re-verified this pass.
- `_lock_issue` (`resolve_issue`) — same "read old state, branch on it" shape as `_lock_task`.
  `test_concurrent_resolve_issue_only_one_wins` added; negative control confirmed the test
  actually detects the bug (3/3 failed with the fix stripped, `['resolved', 'resolved']` instead
  of one rejection), then 15/15 clean across 5 full-suite reruns with the fix restored.
- `reset_employee_password`'s inline lock — no downstream state branch reads the locked object's
  old values, so this call site has no currently observable failure mode from this bug (every
  write here is unconditional, not gated on a stale read). Fixed as defense-in-depth against a
  future change that adds such a branch; `test_concurrent_reset_password_serializes` proves the
  lock still genuinely blocks (two racers' completion timestamps ≥0.25s apart), a regression
  guard rather than a bug reproduction — stated as such rather than overclaimed.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: SQLAlchemy's identity-map/
  `populate_existing` behavior wasn't taken from documentation or memory — verified empirically
  against a disposable, disposable-after Docker `postgres:16` container replicating CI's schema/
  roles/migrations exactly: reproduced both racers succeeding (bug present) 5/5 times without the
  fix, then 5/5 clean with it, before writing any of this up.
- `fix_verified_by_real_command_output`: full backend suite `105 passed` (`.venv/Scripts/python.exe
  -m pytest -q`, real Postgres via `TEST_MIGRATIONS_DATABASE_URL`/`TEST_DATABASE_URL`); concurrency
  file alone run 5x consecutively, `3 passed` each time; `uv run pyright` → `0 errors, 0 warnings,
  0 informations`; `ruff check`/`ruff format --check` → clean.

**E. Bounded claim**

- `standard_and_scope`: `Business_Logic_Security_Cheat_Sheet.md`'s "Use Database Transactions and
  Locks" pattern, scoped to all three `.with_for_update()` call sites in `backend/app/crud.py` as
  of commit `8565734`.
- `severity_trend_vs_last_pass`: Rising, not diminishing, in one specific sense worth naming
  honestly — this is the first finding in the project's audit history that shows a previously
  "complete" audit's own fix silently not working. Not a new category (concurrency/TOCTOU was
  already tracked, Phase 2), but a confirmation that "fixed and verified" claims in this file are
  only as strong as the test that backed them — SQLite-backed verification of a
  `.with_for_update()`-dependent fix was never sufficient evidence, a gap this file's own D-section
  entries have now started flagging explicitly rather than silently.

**F. Independent pass**

- `security_review_run`: No — `/code-review ultra` still hasn't been run on this repo as of this
  pass (2026-09-07).

### Independent Tooling Pass — CodeQL + Semgrep (2026-09-07, commit `3ad18af`)

Not a phase audit (no new feature/code slice reviewed) — this exercises Section F's own independent-pass
requirement via two real, separate mechanisms, since `/code-review ultra` still hasn't been run (see the
`security_review_run` field below, unchanged).

**1. Wired into CI — PR #6, merged to `main` at `3ad18af`.** Semgrep (`p/security-audit` + `p/owasp-top-ten`,
`--error`) and CodeQL (python + javascript-typescript matrix, `build-mode: none`) added as CI jobs, running on
every push/PR going forward. CodeQL's SARIF upload set to `upload: never`, no `security-events: write` — this
repo is private on a personal account, and GitHub Advanced Security (required for the Security-tab dashboard
on a private repo at all) isn't purchasable without a paid Team/Enterprise plan (verified live against
GitHub's own docs, not assumed) — a hard CI failure on any finding is the enforcement instead.

**First real CI run of the new jobs found 3 genuine issues, all fixed, not dismissed:**
- Semgrep: `.github/dependabot.yml`'s cooldown (`default-days: 4`) below the ruleset's own recommended
  minimum — bumped to 7.
- Semgrep: false-positive credential-leak flag on `backend/app/api/deps.py`'s auth-failure log line —
  verified false against PyJWT's actual installed source (`jwt/api_jwt.py`/`api_jws.py`/`jwks_client.py`:
  every `PyJWTError`/`PyJWKClientError` message is a static string, never the token) — suppressed with a
  `# nosemgrep` comment carrying that verification, not blind-trusted. Placement mattered: an initial
  suppression comment 4 lines above the flagged line silently failed to suppress it — confirmed empirically,
  fixed by placing it immediately adjacent with nothing between.
- CodeQL: both matrix jobs failed with "Resource not accessible by integration" — not a code finding, a
  permissions gap. `codeql-action` calls GitHub's workflow-runs API internally for its own telemetry
  regardless of `upload: never`; needs `actions: read`, which the job didn't have. Added, with the real
  failure documented in a comment.

Re-run after fixes: all 6 PR #6 checks green, confirmed via `gh pr checks 6` directly — not the `Monitor`
tool, which timed out without delivering a result on this same PR (checked manually per
`docs/WORKING_PREFERENCES.md` item 2). Merged; CI on `main` at `3ad18af` independently re-confirmed green via
`gh run view --json` (all 5 jobs `success`), not assumed carried over from the PR run.

**2. Independent of CI entirely — CodeQL CLI run standalone**, per explicit request to verify beyond what CI
itself proves. `github/codeql-action`'s own CLI (installed via `gh extension install github/gh-codeql`,
v2.26.4) used to build real databases from this repo's actual source and run the real query packs directly —
no GitHub Actions runner, no workflow file involved at all.
- `codeql/python-queries@1.8.9` against a fresh database built from the real repo source: **46/46 Python
  files scanned, 45 security queries run, 0 findings.**
- `codeql/javascript-queries@2.4.4` against a fresh database built from the real repo source: **28/28 JS/TS
  files scanned, 13 security queries run, 0 findings.**
- A broader manual Semgrep pass, more rulesets than CI uses (`p/security-audit`, `p/owasp-top-ten`,
  `p/python`, `p/typescript`, `p/javascript`, `p/react`, `p/docker`, `p/github-actions`, `p/secrets`, `p/jwt`,
  `p/sql-injection`, `p/insecure-transport`): **1597 rules, 104 files, 0 findings.**

One real infra snag along the way, not glossed over: the first JS/TS database build silently stalled without
ever finalizing (a partial directory with only metadata files was mistaken for a completed build) — caught
when the analyze step failed with "needs to be finalized," not assumed successful from the directory simply
existing. Rebuilt clean in a fresh directory (the stale one was holding a file lock from an orphaned
process) and re-verified via the real "Successfully created database" log line before re-running analysis.

**Honest scope — what this closes, and what it doesn't.** This is real, independent evidence from tools with
their own rule logic, not this project's own reasoning — genuinely stronger than a self-audit. But every
finding this project has caught that actually mattered (the TOCTOU race on `submit_task`, the cross-firm
`assigned_to` gap, the missing composite FKs) was a **business-logic/authorization** defect — exactly the
category static pattern-matching tools are least equipped to catch, since they reason about syntax and known
CWE patterns, not this app's specific workflow-state rules. `security_review_run` below stays `No` — this
doesn't substitute for `/code-review ultra`'s independent-agent reasoning, it's real, additional, but
narrower.

**F. Independent pass**
- `security_review_run`: **No** — `/code-review ultra` has never been run on this repo as of this pass
  (2026-09-07). CodeQL + Semgrep (above, both CI-wired and run standalone) are real independent-tool
  evidence, tracked here separately since they're a different mechanism than this field's own definition.

### Phase 4 Step 1 — Frontend Scaffold + Auth (2026-09-07, base commit `cac3e70`)

```
status: complete
phase: Phase 4 Step 1 — Frontend scaffold + auth (Tauri secure storage), CODING_STRUCTURE.md §4 item 5
scope_files: frontend/src/{app/{app,provider,router}.tsx, config/env.ts, lib/{supabase-client,api-client}.ts, stores/session-store.tsx, features/auth/**, components/app-shell/account-menu.tsx, components/ui/*.tsx}, frontend/src-tauri/{tauri.conf.json, capabilities/default.json, src/{lib.rs,main.rs,store_crypto.rs}, Cargo.toml}, frontend/{index.html,vite.config.ts,eslint.config.js,.env.example}
date: 2026-09-07
commit: cac3e70 (base HEAD at audit start — the CSP fix + DEPLOYMENT.md §12 land as a new commit on top, same pattern as Phase 2/3's own entries)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v1-encoding-sanitization, v2-validation-business-logic, v3-web-frontend-security, v4-api-web-service, v5-file-handling, v6-authentication, v7-session-management, v8-authorization, v9-self-contained-tokens, v10-oauth-oidc, v11-cryptography, v12-secure-communication, v13-configuration, v14-data-protection, v15-secure-coding-architecture, v16-security-logging-error-handling, v17-webrtc, patterns.md — Read tool re-invoked on all 18 this pass; the harness reported all 18 unchanged since the Phase 3 pass a few turns earlier in this same session and pointed back at that content instead of re-fetching bytes it already had — genuinely re-examined against Phase 4's different question (frontend/Tauri, not backend), not skipped: v3 (Web Frontend Security) flips from N/A (correct for Phase 2/3's backend-only scope) to directly relevant this pass — re-derived, not copied. v4/v5/v10/v17 re-confirmed N/A (frontend exposes no API of its own, no file upload, no OAuth, no WebRTC in this slice).
- `skills_reopened_fresh`: tauri-official/chapters/security-capabilities.md (full re-read — found the CSP fix below directly from its own suggested-policy gap against ASVS); supabase-official/auth/sessions.md (grepped + read the `customStorageObject` section, re-verified `supabase-client.ts`'s `getItem`/`setItem`/`removeItem` shape matches exactly); owasp-asvs-5 (18 files above); owasp-cheatsheets (7 whole-directory greps, below). Not reopened: bulletproof-react/react-official — Phase 4 Step 1 introduces no new architectural pattern beyond what `binary-meandering-wind.md`'s plan already checked against those skills before writing the code.
- `cheatsheet_grep_keywords`: `local storage|localStorage|session storage|client.side storage|secure storage|token storage`; `content security policy|CSP\b`; `logout|sign.?out|session termination|revoke`; `CSRF|cross.site request forgery`; `desktop application|electron|native app`; `password reset|forgot password|temporary password|must.change.password`; `XSS|cross.site scripting|dangerouslySetInnerHTML|innerHTML` — 7 greps derived from Phase 4 Step 1's actual mechanisms (encrypted local session storage, Tauri CSP, logout/signOut, Bearer-token-only API auth, the forced Set New Password gate), not from cheat-sheet titles.
- `cheatsheet_grep_output`: 7 separate greps across the whole `owasp-cheatsheets/cheatsheets/` directory (13/17/27/22/9/12/33 files matched respectively — full lists retained in this session's transcript). Read in full this pass: `HTML5_Security_Cheat_Sheet.md`'s "Local Storage"/"Client-side databases" sections (surfaced by the "local storage" keyword — a title giving no hint it covers Tauri-webview-relevant storage risk) and `Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.md` (surfaced by the CSRF keyword, read to verify the N/A conclusion below against the cheat sheet's own stated criteria rather than assuming it).

**B. Fixed-domain sweep**

- `auth`: Login (`use-login.ts`) uses `supabase.auth.signInWithPassword` directly — no new auth mechanism beyond what backend Phase 1 already verified (Supabase Auth owns hashing/issuance). Error message deliberately doesn't distinguish wrong-email from wrong-password (ASVS 6.3.8, checked against the code's own comment and confirmed the message text itself, "Invalid email or password", makes no distinction).
- `session_token_lifecycle`: **Confirmed clean, verified against installed source, not belief**: `account-menu.tsx`'s `supabase.auth.signOut()` call passes no `scope` option — `node_modules/@supabase/auth-js/dist/main/GoTrueClient.d.ts` doc comment confirms the default is **`global`** scope ("signs out the user everywhere they are signed in"), i.e. the real refresh token is revoked server-side on logout, not just local storage cleared (ASVS 7.4.1). `use-set-new-password.ts` explicitly calls `refreshSession()` after the forced password change so `session-store.tsx` sees `must_change_password` flip without waiting out the token's remaining lifetime.
- `tenant_isolation`: N/A for this slice — no tenant-scoped data is fetched or displayed yet (Phase 4 Step 1 is auth-only; the authenticated placeholder route renders no resource data).
- `object_level_authz`: N/A for the same reason — no `{id}`-scoped resource endpoint exists in this slice yet.
- `input_validation`: Zod schemas (`features/auth/types/index.ts`) validate all 3 forms client-side (UX only, per ASVS 2.2.2 — the real validation is `backend/app/api/deps.py`'s server-side gate, already verified in Phase 1). Grepped the whole `frontend/src` tree for `dangerouslySetInnerHTML|innerHTML|document\.write|eval\(` — **zero matches**, confirmed no HTML-injection sink exists anywhere in this slice.
- `cors`: N/A at the frontend layer — CORS is a server-enforced policy (`backend/app/main.py`'s `CORSMiddleware`, already verified Phase 1/2/3); the frontend has nothing to configure here beyond calling the right origin, which `env.ts`'s `VITE_API_BASE_URL` supplies.
- `secrets`: `.env.example` only names `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`/`VITE_API_BASE_URL` — the anon key is Supabase's own publishable, RLS-gated key (safe client-side by design, already established Phase 1), not a secret needing protection. Grepped for any private/service-role key reference in `frontend/` — none. DPAPI encryption of `auth-session.json` (Windows) re-confirmed present in `store_crypto.rs`/`lib.rs`, matching the already-documented Phase 4 Step 3 decision (macOS/Linux plaintext fallback explicitly flagged there as a pre-distribution requirement, not silently accepted).
- `supply_chain`: `package.json` reviewed in full — matches the plan's own YAGNI reasoning (`@tanstack/react-query`/`uuid` deliberately excluded, `crypto.randomUUID()` used instead, confirmed in `api-client.ts`). No unfamiliar/abandoned packages.

**Real finding, fixed this pass**: `tauri.conf.json`'s `app.security.csp` was missing `object-src: 'none'` and `base-uri: 'none'` (ASVS 3.4.3's explicit minimum, L2) and `frame-ancestors: 'none'` (ASVS 3.4.6, L2) — `tauri-official/chapters/security-capabilities.md`'s own suggested starting policy for this exact project also omits all three (an omission in the skill's example, not a contradiction of ASVS — the skill doesn't claim to be the complete CSP authority, and this project's own stated standard is ASVS). Added all three directives. Verified: `node -e "JSON.parse(...)"` confirms still-valid JSON; `npm run lint`/`typecheck`/`test`/`build` all still pass (below).

**Real finding, documented not fixed (value genuinely unknown yet)**: `connect-src`'s `http://localhost:8000` is the dev backend with no production HTTPS origin present anywhere in the CSP — `tauri-official`'s own policy names this exact gap (`<api-domain>`, "fill in ... once those are fixed") but nothing tracked it as a go-live checklist item the way the two Supabase dashboard settings were (`DEPLOYMENT.md` §11). Added `DEPLOYMENT.md` §12 rather than guessing a domain that doesn't exist yet.

**Stress-tested, confirmed as an inherent property not a gap**: `HTML5_Security_Cheat_Sheet.md`'s Local Storage section states plainly that any client-side storage is fully readable by a live XSS in the same origin, regardless of at-rest encryption — DPAPI protects `auth-session.json` from disk-level extraction (a different OS user account, or copying the file), **not** from an already-running malicious script calling the same `getItem` the app itself uses. This is the correct, honestly-scoped claim for what the Phase 4 Step 3 DPAPI decision actually defends against — confirmed against the cheat sheet's own reasoning, not assumed to cover more than it does.

**Confirmed clean, checked against the cheat sheet's own stated criteria, not assumed**: CSRF is structurally N/A for this app's API auth. `Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.md` names the "custom request header" pattern as a valid defense specifically because a forged cross-site request cannot itself set a custom header — this app's `api-client.ts` attaches `Authorization: Bearer <token>` (read from the JS-managed session, never an ambient browser-attached cookie) to every request, which is exactly that pattern, not an accident of not having thought about CSRF.

**C. Self-check gate**

1. `reapplied_general_principle_to_every_instance`: The "client-side gate is UX-only, backend enforces for real" principle (stated once in `router.tsx`'s own comment) was checked against both gated routes (`LoginPage`'s redirect-if-already-authenticated, `AuthenticatedLayout`'s redirect-if-`mustChangePassword`) individually, not assumed from the one comment.
2. `stress_tested_design_against_its_own_stated_logic`: Two stress-tests this pass. (a) DPAPI encryption's actual threat coverage vs. what it was assumed to cover (see B above) — confirmed narrower (disk extraction, not live-XSS) than a casual read of "encrypted at rest" might suggest, and that narrower claim is the honest one. (b) The CSRF N/A conclusion, tested against the cheat sheet's own defense-pattern criteria rather than asserted from general Bearer-token folklore.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B run in full — including two domains (`tenant_isolation`/`object_level_authz`) that turned out N/A for this slice, checked and stated as N/A rather than silently skipped.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: `tauri-official/chapters/security-capabilities.md` and `supabase-official/auth/sessions.md` were both reopened fresh this pass for Phase-4-specific questions (CSP directive completeness; storage-adapter shape), not trusted from either having been read earlier in the project's history or summarized in `binary-meandering-wind.md`'s own plan text.
5. `compound_source_not_partial`: The CSP finding cites ASVS 3.4.3/3.4.6 **and** `tauri-official`'s own suggested policy (confirming the skill's example also lacks these, not just this project's copy of it) **and** the installed Tauri config schema behavior confirmed via `node -e "JSON.parse(...)"` — three sources, not one.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 7 keyword greps across the whole directory this pass (listed in A) — surfaced `HTML5_Security_Cheat_Sheet.md`, a title that gives no hint it covers browser/webview storage risk specifically.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: No shared backend mechanism (`with_idempotency`, `_validate_assignee`, etc.) is reused anywhere in this frontend slice — N/A, checked and stated as N/A rather than left blank.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: `node_modules/@supabase/auth-js/dist/main/GoTrueClient.d.ts` — `signOut()`'s default `global` scope (session_token_lifecycle above) and `UserAttributes.current_password`'s doc-comment caveat (already tracked in `DEPLOYMENT.md` §11, re-confirmed still accurate by reading the same file fresh this pass, not recycled from the commit that first found it).
- `fix_verified_by_real_command_output`: Fixed `tauri.conf.json`'s CSP (`object-src`/`base-uri`/`frame-ancestors`) and added `DEPLOYMENT.md` §12. Verified: `node -e "JSON.parse(fs.readFileSync('src-tauri/tauri.conf.json'))"` → `valid JSON`; `npm run lint` → `0 errors` (5 pre-existing warnings, unrelated to this change — `router.tsx`/`session-store.tsx`'s fast-refresh warnings, present before this pass); `npm run typecheck` → clean; `npm run test` → `2 test files, 4 tests passed`; `npm run build` → succeeded (`dist/` built, pre-existing >500kB chunk-size advisory unrelated to this change).

**E. Bounded claim**

- `standard_and_scope`: ASVS 5, L1+L2, scoped to Phase 4 Step 1 (frontend scaffold + auth, `scope_files` above) as of base commit `cac3e70`, 2026-09-07 (the CSP fix + `DEPLOYMENT.md` §12 land as a new commit on top).
- `severity_trend_vs_last_pass`: Phase 3's pass found 1 real gap (unvalidated `assigned_to`), fixed. This Phase 4 pass found 1 real gap fixed cheaply (missing CSP directives), 1 real gap documented-not-fixed since the correct value doesn't exist yet (prod API origin), plus a re-confirmation (not a re-discovery) that a pre-checklist Phase 4 audit's Supabase-dashboard-setting finding is still accurately tracked. Severity is flat-to-diminishing — no new category of concern (CSP hardening and go-live-checklist tracking are both already-known categories from this project's own prior passes), and this slice's smaller attack surface (no tenant data yet) meant two full domains came back correctly N/A rather than newly-checked-and-clean.
- Note on Gap 1 (the checklist mechanism's own known limit): unlike the Phase 3 pass, this one genuinely set `status: in-progress` before doing the analysis above, rather than writing directly to `Completed Audits` — the `Stop` hook was actually armed for the duration of this pass, even though (same as Phase 3) all the fields ended up filled within one continuous turn rather than the hook ever having to fire.

**F. Independent pass**

- `security_review_run`: No — `/code-review ultra` has never been run on this repo as of this pass (2026-09-07).

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
