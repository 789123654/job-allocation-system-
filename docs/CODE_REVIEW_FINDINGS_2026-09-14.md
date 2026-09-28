# Full-Codebase Code Review — Findings and Root-Cause Analysis (2026-09-14)

## Context

A full-codebase (not diff-based) `/code-review` pass, split into 8 independent scan lanes run as
separate agents (2 in parallel initially, then 6 sequentially one-at-a-time after the first parallel
batch exhausted the session's token budget and 6 of 8 were killed mid-run). Base: whole repo as of PR
#57's merge (`28f61c4`). 21 findings total. This document exists because "we followed the hard rules
and still shipped these" is itself the interesting fact — each entry below states not just what's
wrong, but *why it got past* `skill-verification-discipline.md`'s rules, the OWASP
cheatsheets/ASVS-5/WSTG/TCASVS skills, and the test suite.

**Review lanes and what each covered:**

| # | Lane | Findings |
|---|---|---|
| 1 | Backend `crud.py`/models/db correctness | 5 |
| 2 | Reuse/simplification/efficiency cleanup | 5 |
| 3 | Multi-tenancy and security invariants | 1 |
| 4 | Frontend↔backend contract tracing | 1 |
| 5 | Backend routes/auth/idempotency correctness | 3 |
| 6 | Frontend components correctness | 2 |
| 7 | Frontend api/hooks correctness | 2 |
| 8 | Conventions / `CLAUDE.md` compliance | 2 |

---

## Root-cause taxonomy

Before the individual entries, the recurring patterns across all 21 findings — most findings are an
instance of one of these six, not a one-off:

- **(A) Fix-at-one-site, never-propagated.** A bug was found and correctly fixed at the call site where
  it was noticed, but the surrounding pattern was copy-pasted rather than shared, so sibling call sites
  kept the old, buggy version. The project's own comments repeatedly document this happening (e.g.
  `list_job_types`'s ordering fix explicitly cites "same pattern as `list_notifications`" — a claim that
  was already false when written).
- **(B) Two individually-correct subsystems, uncorrected interaction.** Each piece was reviewed and
  tested on its own and is locally correct; the bug is only visible when both are combined (a DB
  transaction + an external API call; a TTL expiry policy + a no-cleanup-job decision + a
  conflict-recovery query).
- **(C) Missing negative-path/edge-case test.** A happy-path test exists and passes; no test exercises
  the specific adverse input (a slow external call, a malformed-but-present JWT claim, a multi-host DSN,
  a >24h-old reused key, a timezone other than UTC).
- **(D) Deliberate architectural trade-off with a known, accepted gap.** The team consciously chose one
  isolation/consistency model and explicitly decided not to add a redundant second layer — sound
  engineering judgment, but the accepted gap is exactly where a regression elsewhere becomes silently
  dangerous.
- **(E) No lint/type-level enforcement for the convention.** The rule exists as a comment/convention,
  not as something a linter or type system enforces, so nothing stops a new call site from silently
  deviating.
- **(F) Documentation not re-verified as the code evolved.** A doc claim was true when written; nothing
  ties it to the code it describes, so it went stale as the code moved past it.

---

## Lane 1+2 — Backend `crud.py`/models correctness, and reuse/cleanup (10 findings)

### 1. Stale `pendingTaskCount` — cache-invalidation fix not propagated to 4 sibling hooks
**Files:** `frontend/src/features/tasks/api/create-task.ts`, `submit-task.ts`, `mark-task-billed.ts`,
`create-task-review.ts` (missing) vs. `resolve-issue.ts` (has it).
**Root cause: (A) fix-at-one-site, never-propagated.** All 5 hooks hand-roll an identical `useMutation`
shape instead of sharing one. When the stale-count bug was found and fixed, it was fixed where it was
*noticed* — inside `resolve-issue.ts` — and the fix's own comment documents it as a known bug, but
nothing forced a check of the other 4 near-identical files.
**Why tests didn't catch it:** each mutation hook likely has its own unit test asserting *its own*
`invalidateQueries` calls happen — which they do, correctly, for the keys each hook does invalidate.
No test asserts the *complete set* of keys a task-mutating action should invalidate against a single
shared source of truth, so 4 tests can all pass while each is independently incomplete the same way.

### 2. Supabase Admin API call not covered by DB transaction rollback
**File:** `backend/app/crud.py:236` (`reset_employee_password`), `:133` (`create_employee`).
**Root cause: (B) two individually-correct subsystems, uncorrected interaction.** The DB transaction
pattern (`commit_or_recover`) is correct and tested. The Supabase Admin API call is correct and tested
in isolation (mocked). Nobody asked "what if the network call succeeds but the *surrounding* DB
transaction later fails" — a distributed-transaction question that neither subsystem's own review
would surface, since each looks locally sound.
**Why tests didn't catch it:** the project's test suite mocks `admin_auth` for the happy path and
verifies the DB-error path (e.g. duplicate email) separately — but no test forces a commit failure
*after* a successful external call to assert the two stay consistent. This is exactly the kind of gap
`Business_Logic_Security_Cheat_Sheet.md`'s TOCTOU/race-condition material would flag if searched by the
concept ("distributed side effect not covered by local rollback"), not by filename — the same failure
mode the project's own memory already names as a prior root cause (idempotency-key caching a one-time
password) that recurred here in a new shape.

### 3. `list_notifications` missing deterministic-ordering tiebreaker
**File:** `backend/app/crud.py:859`.
**Root cause: (A) fix-at-one-site, never-propagated — the clearest instance in the whole review.**
`list_tasks` and `list_job_types` both have `.order_by(created_at.desc(), id)` and their own comments
*explicitly claim* to be copying `list_notifications`'s pattern. `list_notifications` itself doesn't
have it. The fix was applied to the copies, not the original it was supposedly copied from.
**Why tests didn't catch it:** `test_task_ordering.py` and `test_employee_and_job_type_ordering.py`
exist and pass (for `list_tasks`/`list_job_types`/`list_employees`) — there is no
`test_notification_ordering.py`. The pattern was tested everywhere it was correctly applied and
untested exactly where it was missing.

### 4. Row lock held across an unbounded external HTTP call
**File:** `backend/app/crud.py:261` (`reset_employee_password`).
**Root cause: (C) missing negative-path test**, compounded by **(D)** — holding the lock across the
call is a *deliberate* choice (documented: "serializes racers"), but the accompanying assumption that
the external call returns quickly was never stated or enforced.
**Why tests didn't catch it:** the test suite's Supabase Admin client is mocked to return instantly;
nothing in CI simulates a slow/hung upstream response, so the lock-duration risk is invisible to every
existing test by construction.

### 5. TLS-enforcement validator only checks the first host in a multi-host DSN
**File:** `backend/app/core/config.py:63`.
**Root cause: (C) missing negative-path test.** The validator's own stated goal ("regardless of network
location") is broader than what `v.hosts()[0]` actually checks — a real gap between intent and
implementation that a single-host-DSN test suite can't reveal.
**Why tests didn't catch it:** Supabase issues single-host connection URLs, so every config test in CI
uses a single-host DSN. The multi-host case was never a scenario anyone had reason to construct a test
for, even though the validator's own docstring claims to handle it.

### 6. Tenant isolation relies solely on RLS with no code-level backstop
**File:** `backend/app/crud.py` (all plain getters/listers).
**Root cause: (D) deliberate architectural trade-off with a known, accepted gap.** This is explicitly
"RLS is the single source of truth" by design — stated in the file's own header docstring — not a
missed check. `postgres-multitenant` documents defense-in-depth as *a* valid pattern, not *the*
mandatory one; the team chose single-layer isolation for these paths and added the second layer only
where a function does a state-changing check-then-act (`_lock_task`, `_validate_assignee`).
**Why tests didn't catch it:** `test_rls_isolation.py::test_fastapi_app_does_not_bypass_rls` and
`test_cross_tenant_*` verify RLS *is currently working* — by design, no test exists for "what happens
if RLS itself regresses," because that would require deliberately breaking the primary control to test
the (deliberately absent) backup one. This is a real, accepted risk surface, not a test gap.

### 7. Response DTOs hand-built field-by-field at 7+ call sites
**Files:** `backend/app/api/routes/tasks.py:67,164`, `employees.py`, `job_types.py`, `notifications.py`.
**Root cause: (E) no lint/type-level enforcement.** Nothing prevents a new route from hand-building its
response model instead of using `Model.model_validate(orm_obj, from_attributes=True)`. This is likely
the original scaffold pattern from early Phase 3, and nothing forced revisiting it as more routes were
added — nobody's "hard rule" was broken, because no rule was ever written down for this specific choice.
**Why tests didn't catch it:** each hand-built DTO is tested for the fields it currently sets, correctly
— the risk is a *future* field added to the ORM model and missed in one of the 7+ constructors, which
by definition no test written *before* that omission could catch.

### 8. Pagination tail duplicated across 4 `list_*` CRUD functions
**File:** `backend/app/crud.py:406` and siblings.
**Root cause: (A) fix-at-one-site, never-propagated** — this is the *mechanism* that produced finding
#3 above. Listed separately here because the reuse-scan lane flagged the duplication itself as the
root defect, independent of whether a specific instance had already drifted.
**Why tests didn't catch it:** same as #3 — tests exist per-function, not per-policy, so duplication of
the underlying pattern isn't something any single function's test suite is positioned to notice.

### 9. One-time secret-reveal UI duplicated across two dialogs
**Files:** `frontend/src/features/employees/components/create-employee-dialog.tsx`,
`reset-password-dialog.tsx`.
**Root cause: (E) no enforcement mechanism** — a security-relevant UI pattern (single-use, cleared on
close) implemented twice by hand instead of once as a shared component. Not a rule violation; there was
never a written rule requiring extraction, only the OWASP-driven behavior requirement itself, which both
copies do correctly satisfy.
**Why tests didn't catch it:** each dialog's own test suite verifies its own single-use/clear-on-close
behavior correctly — the duplication is a maintainability risk (a future third copy, or one copy
drifting from the other on a future fix), not a currently-failing behavior, so no test failure signals
it.

### 10. Pagination `Query` bounds duplicated across 4 route files
**Files:** `tasks.py:233`, `employees.py:77`, `job_types.py:45`, `notifications.py:29`.
**Root cause: (E) no enforcement mechanism**, same shape as #9 but for a numeric policy (offset ≤
1,000,000, limit ≤ 100) instead of a UI pattern. The explanatory comment about the Postgres bigint
overflow was itself copy-pasted correctly to all 4 sites — so the *knowledge* propagated, but the
*single source of truth* didn't.
**Why tests didn't catch it:** each route's bounds are independently tested and correct today; a future
change to the bound is the risk, and it's a change nobody has made yet, so no existing test exercises it.

---

## Lane 3 — Multi-tenancy and security invariants (1 finding)

### 11. Signup trigger trusts client-supplied `firm_id`/`role` — cross-tenant privilege escalation
**Files:** `backend/app/alembic/versions/cb67cdb7538a_....py:77-98` (`handle_new_user()`),
`supabase/config.toml:46-49`, `docs/DEPLOYMENT.md` §13.
**Root cause: two compounding gaps.**
1. **(D)-adjacent, but not a deliberate trade-off — a genuine skill-search miss.** The multi-tenancy and
   RLS review this project has done repeatedly (per its own audit history) has focused on the
   *query-time* boundary (RLS policies, `app.current_tenant`) — the exact area
   `postgres-multitenant`/`owasp-asvs-5` V8 (Authorization) get searched for. The *signup-time*
   boundary — a `SECURITY DEFINER` trigger consuming attacker-controlled `raw_user_meta_data` — is a
   **registration/account-provisioning** concern, which lives in
   `Authentication_Cheat_Sheet.md`'s registration section and `owasp-wstg`'s WSTG-IDNT-02/03 (User
   Registration / Account Provisioning Process) chapter, not the authorization/RLS material that kept
   getting checked. This is the same failure mode the project's own memory already names for a past
   incident (checking the "obviously relevant" cheat sheets and missing
   `Business_Logic_Security_Cheat_Sheet.md`) — a cheat sheet's/chapter's title not being a reliable index
   of what's actually relevant, recurring in a new subsystem.
2. **(F) documentation drift with real consequence.** `supabase/config.toml`'s own comment asserts the
   production posture is covered by `DEPLOYMENT.md` §13 — but §13's actual 8-step runbook and §11's
   "Required Before Go-Live" list were both written (or last revised) without this specific setting in
   mind, so the comment's claim was never true, or stopped being true, and nothing re-verified it.
**Why tests didn't catch it:** `test_rls_isolation.py` and `test_authz_regression.py` both test the
*query-time* boundary with profiles that already exist — none constructs a profile via the actual
`handle_new_user()` trigger path with attacker-supplied metadata, because the trigger is Postgres-side
Supabase infrastructure, not FastAPI code, and sits slightly outside where the backend test suite's
"insert a profile directly" fixtures look. Also not currently exploitable in CI specifically because
`supabase/config.toml` sets `enable_signup=false` there — so even a test that tried this attack would
pass in CI while the production gap (dependent on a manual dashboard toggle) remains open.

---

## Lane 4 — Frontend↔backend contract (1 finding)

### 12. Date-only input parsed as UTC midnight — deadlines shift by hours to a full day
**Files:** `create-task-dialog.tsx:143`, `owner-task-review-page.tsx:188`,
`issue-resolution-page.tsx:119` (frontend); `backend/app/crud.py:729-759` `_as_aware_utc` (backend).
**Root cause: (B) two individually-correct subsystems, uncorrected interaction**, specifically a
**silent contract gap**: the backend's convention ("naive datetime → treat as UTC") is internally
consistent and correct given its own input. The frontend's `<input type="date">` is also a correct,
standard HTML control. Neither side is "wrong" in isolation — no contract was ever written stating
*which* timezone convention a bare date string should imply, so each side made an independent,
reasonable-looking assumption that don't match.
**Why tests didn't catch it:** backend datetime tests construct `datetime` objects directly in Python
(already timezone-aware or explicitly UTC) rather than round-tripping through the actual wire format a
date-only HTML input produces; frontend component tests assert the *string value* a date input holds,
not what that string means once interpreted by the real backend convention. No end-to-end test exists
that picks a date in a non-UTC-equivalent timezone and asserts the resulting overdue-flag timing — this
is exactly the class of bug an E2E tier (documented in `FRONTEND_ARCHITECTURE.md` §9 as "not yet built")
would be positioned to catch and the current unit/integration tiers structurally cannot.

---

## Lane 5 — Backend routes/auth/idempotency correctness (3 findings)

### 13. Idempotency-key reuse after TTL silently discards new writes
**File:** `backend/app/core/idempotency.py:105` (lookup, filters by TTL) vs. `:141` `_recover_winner`
(no TTL filter).
**Root cause: (B) two individually-correct subsystems, uncorrected interaction — the sharpest instance
in this whole review.** Three separate decisions are each defensible alone: (a) filter expired rows out
of the *lookup* so a key can be logically reused after 24h — correct; (b) never run a cleanup job for
expired rows, reasoning (per the migration's own comment) that "a lookup filters them out by
`created_at` regardless, so correctness doesn't depend on deletion" — true for the lookup path,
silently false for the conflict-recovery path; (c) `_recover_winner`'s conflict-resolution query,
written for the *true-concurrency* case (two simultaneous requests, no prior row — which it handles
correctly), was never revisited for the *expired-stale-row* case once TTL-based reuse was designed
in. Each of the three was correct for the scenario its author had in mind; nobody checked all three
against each other's edge case at once.
**Why tests didn't catch it:** `test_idempotency.py` covers within-TTL replay and reject-on-conflicting-
body; `test_idempotency_concurrency.py` covers true simultaneous requests — genuinely correct, verified
by this same review. Neither test constructs "an expired row already exists, then the same key is
reused" — the exact scenario that requires two separate test setups (create a row, backdate its
`created_at` past 24h, then issue a new request with the same key) that nobody had written yet.

### 14. `Idempotency-Key` header has no length ceiling
**File:** `backend/app/api/deps.py:22`.
**Root cause: (E) no lint/type-level enforcement — specifically, an inconsistency between two different
FastAPI declaration idioms.** Every `Pydantic Field()`-declared string in this codebase has an explicit
`max_length`, each with a comment citing the Input Validation Cheat Sheet. `Header(alias=...)` is a
different declaration mechanism (`fastapi.Header`, not a model field), and the length-ceiling convention
— clearly applied as a rule everywhere it was a `Field()` — was never explicitly re-asked for the
`Header()` case, because it doesn't visually/structurally resemble the pattern the rule was originally
written against.
**Why tests didn't catch it:** existing idempotency tests use realistic (short) key values throughout;
nothing sends an oversized header, so there's no failing assertion to trip.

### 15. Unguarded `UUID(user_id)` parse returns 500 instead of 401
**File:** `backend/app/api/deps.py:84`.
**Root cause: (C) missing negative-path test**, in a function that otherwise systematically catches
every malformed-token shape — the *pattern* (catch-and-401) is followed everywhere else in the same
function; this one line is the single case where it wasn't applied, most plausibly because a `sub`
claim from a trusted, already-signature-verified JWT "shouldn't" be malformed, so it read as
unreachable at the time it was written.
**Why tests didn't catch it:** every existing bad-token test constructs tokens with a missing claim, a
bad signature, or an expired timestamp — none constructs a validly-signed token with a syntactically
wrong `sub` value, since doing so requires deliberately crafting a bad claim inside an otherwise-valid
token, which isn't the "natural" mutation a test author reaches for.

---

## Lane 6 — Frontend components correctness (2 findings)

### 16. `issue-resolution-page.tsx` missing the status guard its sibling page has
**File:** `frontend/src/features/tasks/components/issue-resolution-page.tsx`.
**Root cause: (A) fix-at-one-site, never-propagated.** `owner-task-review-page.tsx`'s equivalent guard
was added specifically in response to a previously-found bug (letting a non-actionable task's form
render and only failing at submit) — documented in that file's own comment. The sibling page,
structurally almost identical and vulnerable to the exact same class of bug, was never revisited once
the fix was made on the other page.
**Why tests didn't catch it:** `owner-task-review-page.test.tsx` has a test specifically covering the
guard (renamed during the Phase 4 code-review pass to assert the pre-check renders and no submit button
exists). No equivalent test was ever added for `issue-resolution-page.tsx`, because the bug the guard
prevents was never independently discovered there — it was only ever found and fixed once, on the other
page.

### 17. Billing-outcome fields validate but never render their error message
**File:** `frontend/src/features/tasks/components/owner-task-review-page.tsx:186-207`.
**Root cause: (C) missing negative-path test** combined with an easy-to-miss omission: `assignedTo` in
the same branch *does* render `errors.assignedTo`, so the pattern was known and partially applied —
just not copied to all 4 billing-specific fields when that branch was written.
**Why tests didn't catch it:** the existing review-form tests almost certainly submit either fully valid
billing data or fully empty billing data (tripping the `superRefine` "required fields" check, which
*is* rendered via `errors.outcome`) — the specific case of "present but individually invalid" (e.g. a
501-character description) sits in the gap between those two tested scenarios and was never exercised.

---

## Lane 7 — Frontend api/hooks correctness (2 findings)

### 18. `resolve-issue.ts` never invalidates the `issues` query key
**File:** `frontend/src/features/tasks/api/resolve-issue.ts:27-47`.
**Root cause: (A) fix-at-one-site, never-propagated — recurring inside the very file that was the
*source* of the original fix (finding #1).** `resolve-issue.ts` was where the employees-cache
invalidation bug was found and fixed; that same file simply never invalidated its own resource's query
key (`issues`) in the first place. The earlier fix concentrated attention on the *employees* cache
specifically (since that was the reported symptom) rather than auditing the mutation's *complete*
invalidation set against every resource it actually mutates.
**Why tests didn't catch it:** no test asserts the full set of query keys a successful resolve should
invalidate — same gap as finding #1, same missing "assert against a complete list" test shape, just a
second, independent instance of it inside the one file that already had one such bug found and fixed.

### 19. No frontend handling for a backend-issued 401
**File:** `frontend/src/lib/api-client.ts`.
**Root cause: (D) deliberate scope decision with an unexamined edge.** Supabase's own
`autoRefreshToken`/`onAuthStateChange` correctly handles the *common* 401 case (refresh-token expiry) —
this was built and tested. A *cryptographically valid but backend-rejected* token (deactivated user,
deleted firm) is a distinct case that was never separately considered, because from the frontend's
perspective both look identical ("a request got a 401") but require different handling (one is already
covered by Supabase's SDK, the other isn't covered by anything).
**Why tests didn't catch it:** `api-client.test.ts` verifies header attachment and error-body parsing,
including for 401 responses generically — parsing a 401 correctly is not the same as *acting* on one,
and no test asserts a specific UI consequence (redirect, logout, visible message) follows a 401,
because no such consequence was ever built for this specific test to catch the absence of.

---

## Lane 8 — Conventions / `CLAUDE.md` compliance (2 findings)

### 20. `CLAUDE.md` falsely claims no code exists yet
**File:** `CLAUDE.md:18-20`.
**Root cause: (F) documentation not re-verified as the code evolved — the starkest instance.** Written
during the actual planning phase (true at the time), never updated across 5 phases of real
implementation. No mechanism in this project's workflow re-reads `CLAUDE.md` against current repo state;
it's read once per session as background context and otherwise never revisited unless something
specifically prompts a look (like this review).
**Why tests didn't catch it:** documentation staleness isn't something a test suite is positioned to
catch by nature — there's no automated check comparing a status claim in prose against `git log`/file
existence. This is the exact class of thing `skill-verification-discipline.md`'s own guidance on
"having read a file earlier isn't the same as having checked it now" exists to prevent for code — the
same discipline was never applied reflexively to the project's own top-level status doc.

### 21. Test docstring cites `postgres:16`; CI actually runs `:17`
**File:** `backend/tests/crud/test_rls_isolation.py:3`.
**Root cause: (F) documentation not re-verified as the code evolved**, smaller-scale version of #20. CI
was upgraded to `postgres:17` (confirmed consistent across `ci.yml`, `loadtest.yml`,
`CODING_STRUCTURE.md`, `DATA_MODEL.md` — only this one docstring was missed) and the test file's own
comment wasn't part of that upgrade's edit set, since it's a comment, not a version string anything
greps for during a version bump.
**Why tests didn't catch it:** a docstring's factual accuracy has no assertion attached to it by
definition — the test itself passes regardless of what the comment claims about CI's Postgres version,
so there was never a failing signal to surface this.

---

## Cross-cutting observations

- **8 of 21 findings (≈38%) are root-cause category (A) — a correct fix made once, never propagated to
  structurally identical siblings.** This is the single largest pattern in the review, and it's
  specifically the failure mode duplicated/shared code invites: fixing a bug in a copy fixes that copy,
  not the pattern. The reuse-lane's own findings (#7, #8, #9, #10 — hand-built DTOs, duplicated
  pagination, duplicated dialogs, duplicated Query bounds) are the *structural precondition* for several
  of the (A)-category correctness bugs (#1, #3, #16, #18) — extracting shared helpers would not just
  reduce code, it would make this entire class of bug structurally harder to reintroduce.
- **5 of 21 (≈24%) are category (C) — a real edge case with no test ever written for it**, not because a
  rule was skipped, but because nobody constructed the specific adverse input. These are the hardest to
  catch by process discipline alone; they're the strongest case for the project's own stated blind-test
  practice (an agent with no knowledge of the implementation, asked to enumerate adverse inputs from the
  spec) rather than relying on the same author who wrote the code to also imagine its failure modes.
- **Finding #11 (signup trigger) is the one genuine "should have been caught by the hard rules but
  wasn't" case** — not a test gap or a propagation gap, but a skill-search miss on a *sub-mechanism*
  (registration/provisioning) that doesn't share a name with the *mechanism* (authorization/RLS) that
  kept getting checked instead. It's the same shape of miss this project's own process memory already
  documents once before (an idempotency review that found `Multi_Tenant_Security_Cheat_Sheet.md` and
  `Authorization_Cheat_Sheet.md` but not `Business_Logic_Security_Cheat_Sheet.md`) — evidence that
  "search by the mechanism's real keywords across the whole directory, not the files whose titles sound
  relevant" is a discipline that has to be re-applied fresh on every new subsystem, not something that
  generalizes automatically from having been learned once.
