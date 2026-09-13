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

### Phase 4 — Whole-Slice Code Review Fixes (2026-09-13)

```
status: complete
phase: Independent /code-review pass across the entire Phase 4 frontend slice (base commit 2f5e940
  — end of Phase 0-2 backend scaffolding — against main at 2a5ab89, after the Notifications slice
  merged), per Rule 11's ask-before-running protocol (user explicitly requested it this time). Not
  a new feature slice — fixing the 10 findings that pass surfaced. Rules 10.1/10.2/11 (skill-
  verification-discipline.md) followed: negative control run for every fix with a regression test
  (backend); ask-before-code-review already satisfied since the user directly requested this review.
scope_files: backend/app/crud.py (resolve_issue notification mark-read, list_employees/
  list_job_types ORDER BY), frontend/src/features/tasks/api/resolve-issue.ts (notifications cache
  invalidation), frontend/src/features/tasks/components/owner-task-review-page.tsx (shouldUnregister,
  errors.outcome/errors.assignedTo renders, 422 message, status pre-check),
  frontend/src/features/tasks/api/get-task.ts (enabled guard), frontend/src/features/notifications/
  components/notifications-page.tsx (firmId/isPending/isError guard),
  frontend/src/features/auth/components/change-password-form.tsx (success-message reachability),
  frontend/src/components/error-boundary.tsx (new), frontend/src/app/router.tsx (ErrorBoundary
  wiring), docs/FRONTEND_ARCHITECTURE.md (§2 deviation recorded), backend/tests/crud/
  test_employee_and_job_type_ordering.py (new), backend/tests/crud/test_reviews_and_issues.py
  (+1 test), frontend/src/features/tasks/components/owner-task-review-page.test.tsx (+1 updated
  test), frontend/src/features/tasks/components/issue-resolution-page.test.tsx (timeout bump —
  unrelated pre-existing two-hop-query timing sensitivity under full-suite load, not a fix target)
date: 2026-09-13
commit: (pending — not yet pushed/merged)
```

**A. Findings and fixes (ranked by the review, most-severe first):**
1. Resolving an issue never invalidated the notifications cache (frontend) or marked the
   originating `issue_raised` notification read (backend) — the Owner Dashboard's Issues Raised
   panel showed a resolved issue forever. Fixed both sides; backend fix covered by a new negative-
   control-verified regression test (`test_resolve_issue_marks_originating_notification_read`).
2. `owner-task-review-page.tsx` had the exact stale-conditional-field bug already fixed on its
   sibling `issue-resolution-page.tsx` (missing `shouldUnregister`, `errors.outcome` rendered only
   inside the billing branch) — left unfixed here per this project's own prior "noted, not fixed"
   deferral. Fixed identically; also added the missing `errors.assignedTo` render on the reassigned
   branch for consistency.
3. `NotificationsPage` had no `firmId`-null / `isPending` / `isError` guard, unlike every sibling
   screen — a malformed JWT rendered as a silent, wrong "No notifications." Added the same guard
   `employee-list.tsx` already uses.
4. Every entry point to the Owner review screen (deadline notifications, the All Tasks table)
   linked there regardless of task status, surfacing the 409 only after a full form fill. Added a
   status pre-check; updated the existing test that had encoded the old (wrong) behavior as correct
   to assert the new guard instead.
5. `issue-resolution-page.tsx` fired a wasted `/tasks/` request with an empty id on every mount,
   before `useIssue` resolved. Fixed `useTask`'s `enabled` guard to require a non-empty id.
6. `owner-task-review-page.tsx` had no 422-specific error message (deactivated assignee), unlike
   its sibling. Added the same message.
7. `list_employees`/`list_job_types` had no `ORDER BY`, the same non-deterministic-pagination bug
   already fixed on `list_tasks`. Backported the fix; covered by a new negative-control-verified
   regression test file.
8. Change-password's own success message was unreachable — the dialog closed (unmounting the
   child) in the same tick the child set its success state, under React 18 batching. Fixed by
   moving the close to an explicit "Done" button, matching `reset-password-dialog.tsx`'s existing
   one-time-result convention.
9. Zero error boundaries anywhere in the frontend, despite `CODING_STRUCTURE.md` explicitly
   requiring "multiple error boundaries, scoped per section, not one global boundary." Added a
   plain React class-based boundary (no new dependency — react.dev's own componentDidCatch/
   getDerivedStateFromError pattern, not documented in any installed skill), wrapping only
   `<Outlet />` inside `AuthenticatedLayout` (not the header/nav/AccountMenu), keyed on
   `location.pathname` so navigating away from a crashed screen actually recovers instead of the
   boundary's tripped state persisting across every later route.
10. `features/issues/`/`features/billing/` were never built as their own folders per
    `FRONTEND_ARCHITECTURE.md` §2 — issue/billing code lives under `features/tasks/` instead, with
    no recorded decision reversing the doc. Investigated rather than moved: issue-raise
    (`raise-issue-dialog.tsx`, `create-task-issue.ts`) and mark-billed (`mark-task-billed.ts`) are
    both invoked directly from `task-detail-page.tsx`/`create-task-dialog.tsx`, and issue-resolution
    shares `create-task-review.ts`'s single review endpoint — splitting either into its own feature
    folder would make `features/tasks/` import from `features/issues/`/`features/billing/`, exactly
    what §2's own features-cannot-import-each-other ESLint rule forbids. Recorded the deviation and
    its reason in `FRONTEND_ARCHITECTURE.md` §2 instead of moving files into a structure the
    project's own lint rule would reject.

**B. Verification:** Backend — full suite 115 passed, 70 skipped (0 failed); `ruff check .` clean;
`uv run pyright` 0 errors (matching CI's exact invocation — a bare `pyright`/`python -m pyright`
run outside `uv` falsely reports hundreds of `sqlmodel`-unresolved errors across pre-existing files
too, a local-invocation artifact, not a real regression). Both new/changed backend fixes negative-
control verified (reverted, confirmed the new test fails, restored, confirmed it passes again).
Frontend — `npm run lint` 0 errors; `npm run typecheck` clean; `npm run build` succeeds; full test
suite 62/62 passing across 4 consecutive full-suite runs (one incidental pre-existing flaky test,
unrelated to any of the 10 fixes, surfaced during this pass — see note below — and was fixed
separately, verified reproducible before the fix and clean across 4 runs after).

**Note — incidental flaky-test fix, not a code-review finding:** `issue-resolution-page.test.tsx`'s
existing "does not leak a previously entered deadline" test started failing reproducibly (3/3) in
full-suite runs only, never in isolation, after this pass's other changes. Root-caused by reverting
each change individually: not caused by any of the 10 fixes (confirmed by temporarily reverting the
`get-task.ts` `enabled` guard and observing the same failure) — this page's initial render depends
on two sequential queries (`useIssue`, then `useTask` once `issue.taskId` resolves), and the default
1000ms `findBy` timeout was too tight for that two-hop round trip under the full 14-file suite's
parallel CPU load. Bumped that one assertion's timeout to 3000ms; verified clean across 4
consecutive full-suite runs after.

### Phase 4 — Notifications (Both Roles) (2026-09-13)

```
status: complete
phase: Phase 4 — Notifications (both roles), PRD §2.5/§3.4/§4.4, FRONTEND_ARCHITECTURE.md's Notifications screen row — the 11th and final Phase 4 screen, completing the Phase 4 inventory. Backend (GET /notifications, PATCH /notifications/{id}/read) already fully built and audited in Phase 3; this slice adds polling (FRONTEND_ARCHITECTURE.md §8, refetchInterval) and mark-read to the existing minimal read-only hook, plus the dedicated screen and both-roles route.
scope_files: frontend/src/features/notifications/{api/get-notifications.ts,api/mark-notification-read.ts,components/notifications-page.tsx,components/notifications-page.test.tsx,types/index.ts}, frontend/src/app/router.tsx, frontend/src/testing/mocks/handlers.ts
date: 2026-09-13
commit: (uncommitted — base HEAD is the Issue Resolution merge ebd3c5a)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v8-authorization (§8.3.1 — re-confirmed, this time for a genuinely new question: does a role-conditional client-side link *target* need its own authorization check? §8.3.1's own text — "authorization must be enforced at a trusted service layer... never relies on client-side JS" — confirms it doesn't: whichever URL the component builds, the real access decision happens again server-side when that route is actually requested, same as every other client-side routing decision in this app); v2.4.1 (resource-exhaustion/anti-automation — re-confirmed unchanged from the Phase 3 audit, this pass adds a client poll, not a new server computation).
- `skills_reopened_fresh`: `owasp-cheatsheets` (whole-directory grep below, run twice — once directly, once again via the blind-test agent's own independent pass); `owasp-asvs-5/chapters/v8-authorization.md` reopened for the role-conditional-link-target question specifically, distinct from the id-in-URL question it was reopened for in the Issue Resolution pass.
- `cheatsheet_grep_keywords`: `polling|denial of service|rate limit` (surfaced `Denial_of_Service_Cheat_Sheet.md` among others); `open redirect|unvalidated redirect|IDOR|object reference` (surfaced `Unvalidated_Redirects_and_Forwards_Cheat_Sheet.md` and `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md`) — not just the titles that sounded relevant from memory.
- `cheatsheet_grep_output`: `Denial_of_Service_Cheat_Sheet.md` — no direct guidance on client polling intervals; conclusion: the existing Cloudflare-edge rate limiting plus the backend's own bounded/indexed firm-wide scan (already audited in the Phase 3 API_SPEC.md entries) still fully covers a 45s client poll, no new gap. `Unvalidated_Redirects_and_Forwards_Cheat_Sheet.md` — doesn't apply: the component builds fixed-shape *internal* route strings from a server-supplied id, never a full attacker-controlled destination URL, so there's no open-redirect surface. `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md` — confirms the client-side role branch is UI routing, not an access-control decision; a correct href is never treated as proof of authorization anywhere in this slice's tests.

**B. Fixed-domain sweep**

- `auth`: Unchanged — the new `/notifications` route sits directly under `AuthenticatedLayout` (both roles, no `OwnerRoute`/`EmployeeRoute` wrapper needed, matching the PRD's "both roles" requirement), reusing the existing session gate.
- `session_token_lifecycle`: N/A, no new mechanism.
- `tenant_isolation`: N/A, no new query — `GET /notifications` is unchanged, already `recipient_id = current profile`-scoped.
- `object_level_authz`: N/A for new code — `GET`/`PATCH /notifications` were already audited (404-not-403, recipient-only) in the Phase 3 pass; this slice adds no new backend surface at all, only a frontend consumer.
- `input_validation`: N/A — mark-read has no request body; polling adds no new user input.
- `cors`: N/A, unchanged.
- `secrets`: N/A — `NotificationOut` is plain operational data.
- `supply_chain`: No new dependency (`git status` on `package.json`/`package-lock.json` — no diff).

**C. Self-check gate (mapped to skill-verification-discipline.md's 12 failure modes)**

1. `reapplied_general_principle_to_every_instance`: the app-level "role decides which screen/target" pattern (already used by `AuthenticatedHome`, `OwnerRoute`/`EmployeeRoute`) reapplied to per-notification link-target selection, not reinvented.
2. `stress_tested_design_against_its_own_stated_logic`: explicitly tested **both** roles receiving the **same** notification type, specifically to avoid repeating the Dashboard pass's finding #1 (an incomplete role branch) — not just tested for whichever role came to mind first.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B run in full even though this reads as "just a notifications list."
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: `v8-authorization.md` reopened for the new role-conditional-link question, not cited from the Issue Resolution pass's id-in-URL reasoning.
5. `compound_source_not_partial`: cheat sheets and ASVS 5 both checked this pass.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: two separate keyword-cluster greps (A above), surfacing two cheat sheets whose titles gave no obvious hint they'd apply to a notifications list.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: `useMarkNotificationRead`'s cache invalidation reuses the standard `invalidateQueries` pattern; checked (not assumed) that `NotificationOut`'s response body carries no secret/one-time value.
8. `comprehensiveness_claim_backed_by_the_actual_checklist`: **`status: in-progress` was set genuinely before any code was written this pass**, not backfilled as `complete` after the fact — a direct, explicit fix of the gap named on the Issue Resolution pass, per the user's "don't repeat, or mention explicitly" instruction.
9. `pre_write_check_run_before_writing_the_code_not_after`: `refetchInterval`/`refetchIntervalInBackground` verified against the actually-installed `@tanstack/react-query` 5.102.8's own `.d.ts` (quoted below) *before* `get-notifications.ts` was edited, not after.
10. `blind_test_authoring_used_where_it_mattered`: **Run this pass, scoped tightly per the new token-efficiency addendum** — 109k tokens / 12 tool calls / ~4 min, down from the prior pass's 163k / 44 / ~10 min. Found zero implementation bugs; all 5 of 8 tests failed on the blind agent's own mock using the wrong wire-format field casing (camelCase instead of the real snake_case `NotificationOut` shape) — see failure mode 12 below, a gap in *this pass's own prompt*, named honestly rather than glossed over.
11. `code_review_decision_asked_not_assumed`: Asked the user directly (Rule 11); answer was to skip it for this slice, given zero new backend surface and the one real risk (role routing) already negative-control-verified.
12. `blind_test_contract_states_wire_format_not_just_mapped_type` (new, named by this very pass): documented in `skill-verification-discipline.md` as failure mode 12 for future blind-test prompts to apply — this pass is the one that found the gap, not one that avoided it.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: `refetchInterval?: number | false | ((query) => ...)` and `refetchIntervalInBackground?: boolean` both confirmed present in `node_modules/@tanstack/query-core/build/legacy/hydration-*.d.ts` for the installed 5.102.8 before writing the hook — no installed skill documents this library, so this was the genuine fallback-to-official-source case the base rule requires.
- `fix_verified_by_real_command_output`: Negative control on the one real behavior this slice needed guarded — reverted the role branch in `notifications-page.tsx` to always return the Owner's target, reran `notifications-page.test.tsx`, confirmed the Employee-role test failed (`href="/owner-tasks/t1/review"` instead of `/tasks/t1"`), restored, confirmed both pass. Full suite: `npm run lint` → 0 errors, 2 pre-existing warnings; `npm run typecheck` → clean; `npx vitest run` → **62 passed**, 14 test files; `npm run build` → succeeded.
- Also noted honestly, not swept aside: observed transient flakiness across repeated full-suite runs this pass (2 of 6 consecutive runs had one unrelated Select-interaction test fail — a different test each time, both passing cleanly on immediate rerun in isolation). Investigated whether this pass's new `refetchInterval` real-timer usage (no fake timers configured anywhere in this suite) could be the cause; inconclusive, but leaning toward pre-existing jsdom/pointer-event timing sensitivity (already documented in this project's own history) rather than a new regression — the failures were scattered across files this pass never touched and didn't correlate with notification-related tests specifically. Flagged for awareness, not treated as a closed non-issue.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5 (v8 §8.3.1, v2.4.1 re-confirmed), `Denial_of_Service_Cheat_Sheet.md`, `Unvalidated_Redirects_and_Forwards_Cheat_Sheet.md`, `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md` — scoped to `scope_files` above, none pushed yet.
- `severity_trend_vs_last_pass`: **Zero new security findings** — no new backend surface at all this pass, only a frontend consumer of Phase-3-audited endpoints plus a client poll. The one real gap found (the blind-test prompt's wire-format ambiguity) is a testing-process finding, not a security one, and is itself now documented as a reusable lesson.

**F. Independent pass**

- `security_review_run`: **Asked, not assumed** (Rule 11) — user chose to skip `/code-review` for this slice: zero new backend surface, and the one real branch-completeness risk (role-aware routing) already has a negative-control-verified permanent test. This completes the full 11-screen Phase 4 inventory — a natural point to note the still-outstanding, repeatedly-deferred full independent `code-review` sweep across the whole frontend, named again here rather than silently dropped.

### Phase 4 — Issue Resolution (Owner Side) (2026-09-13)

```
status: complete
phase: Phase 4 — Issue Resolution (Owner clarifies/adjusts-deadline/reassigns a raised issue), PRD §2.7/§3.3/§4.3, FRONTEND_ARCHITECTURE.md's Issue Resolution screen row — second-to-last of the 11-screen Phase 4 inventory. Backend (GET /issues/{id}, POST /issues/{id}/resolve) already fully built and audited in earlier passes (Phase 3, Tasks-Owner-Part-2); this slice is the frontend screen consuming it for the first time.
scope_files: frontend/src/features/tasks/{components/issue-resolution-page.tsx,api/resolve-issue.ts,types/index.ts (issueResolveSchema)}, frontend/src/app/{router.tsx,owner-dashboard-page.tsx}, frontend/src/testing/mocks/handlers.ts (POST /issues/:id/resolve mock)
date: 2026-09-13
commit: (uncommitted — base HEAD is the Owner-Dashboard-regression-tests merge)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v8-authorization (§8.2.2 BOLA/IDOR — the new `/owner-issues/:issueId/resolve` URL exposes an issue id the same way the already-cleared `/owner-tasks/:taskId/review` exposes a task id; re-confirmed, not assumed, that `resolve_issue`/`get_issue` are both `RequireOwnerDep` + RLS-scoped with no per-object check needed beyond that, same shape already audited for `GET /issues/{id}` in the prior Dashboard pass); v2-validation-business-logic (the new `issueResolveSchema` combination rules mirror `IssueResolveRequest`'s `_validate_resolution_fields` field-for-field, re-read fresh this pass, not assumed from `taskReviewSchema`'s similar-looking shape — confirmed `resolution_notes` is unconditionally required here, unlike `TaskReviewCreate.notes`).
- `skills_reopened_fresh`: `owasp-cheatsheets` (whole-directory grep below); `owasp-asvs-5/chapters/v8-authorization.md` (re-read for the id-in-URL question specifically).
- `cheatsheet_grep_keywords`: `object reference|IDOR|mass assignment|validate combinations|business logic` (surfaced `Authorization_Regression_Testing_Cheat_Sheet.md`, `Business_Logic_Security_Cheat_Sheet.md`, `Mass_Assignment_Cheat_Sheet.md`, `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md`, `Multi_Tenant_Security_Cheat_Sheet.md` among others — not just the titles that sounded relevant from memory).
- `cheatsheet_grep_output`: Confirmed no new finding — the object-reference/mass-assignment/combination-validation concerns this screen touches are all reused, already-audited backend mechanisms (`RequireOwnerDep`, RLS, `_validate_assignee`/`UnknownAssigneeError`, `_validate_resolution_fields`); this slice adds zero new backend surface, only a frontend consumer of it.

**B. Fixed-domain sweep**

- `auth`: Unchanged — reuses `OwnerRoute`'s existing gate via a new `OwnerIssueResolutionRoute` wrapper, same pattern as `OwnerTaskReviewRoute`.
- `session_token_lifecycle`: N/A, no new mechanism.
- `tenant_isolation`: N/A for new code — `resolve_issue`/`get_issue` were already RLS-audited; this pass adds no new query.
- `object_level_authz`: Re-confirmed, not re-audited — same 404-not-403 IDOR-cleared shape as `GET /issues/{id}` (prior pass) and `/owner-tasks/:taskId/review` (Tasks-Owner-Part-1 pass), now with a second URL exposing an issue id (`/owner-issues/:issueId/resolve`). No new backend check needed; the frontend route itself is Owner-gated same as its sibling.
- `input_validation`: `issueResolveSchema`'s combination rules mirror the backend's exactly (re-read fresh, not assumed) — `resolutionNotes` always required, `newDeadline` only for `deadline_adjusted`, `remainingWorkDescription`/`assignedTo` only for `reassigned`.
- `cors`: N/A, unchanged.
- `secrets`: N/A — `IssueOut` response body is plain operational data, same as the already-cleared `create_task`/`resolve_issue` response-body check from the earlier Phase 3 pass.
- `supply_chain`: No new dependency (`git status` on `package.json`/`package-lock.json` — no diff).

**C. Self-check gate (mapped to skill-verification-discipline.md's 11 failure modes)**

1. `reapplied_general_principle_to_every_instance`: `OwnerTaskReviewRoute`'s cross-feature-import workaround (fetch `useEmployees()` at the `app/` composition layer, pass down as plain `{id,label}` options) reapplied identically for `OwnerIssueResolutionRoute` — not reinvented.
2. `stress_tested_design_against_its_own_stated_logic`: Explicitly checked, for **every one of the 3** `resolutionType` branches (not just the 1-2 most obvious), that the combination-validation rejects fields invalid for that branch — caught by the blind test suite that a 4th case (switching branches after partially filling a different one) leaked a stale field value past the branch-specific checks; see Section D for the real bug this found and its fix.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B run in full even though this slice reuses an already-audited backend wholesale — confirmed there's genuinely nothing new to find there, rather than skipping the sweep because "it's just a form."
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: `owasp-asvs-5/chapters/v8-authorization.md` reopened for the *new* id-in-URL question this pass (a second URL parameter, not the same one already cleared for tasks), not cited from memory of the earlier tasks-focused read.
5. `compound_source_not_partial`: Cheat sheets *and* ASVS 5 both checked this pass (A above), not just one.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: Whole-directory grep (A above) surfaced `Authorization_Regression_Testing_Cheat_Sheet.md` — a file whose title gives no hint it's about designing regression test suites, exactly the failure-mode-6 trap; used to brief the blind-test agent (Section D), not just noted and dropped.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: `with_idempotency`/`RequireOwnerDep`/RLS are all reused unchanged at this new call site — checked (not assumed) that `IssueOut`'s response body carries no secret/one-time value the existing idempotency-cache vetting wouldn't already cover.
8. `comprehensiveness_claim_backed_by_the_actual_checklist`: This audit entry is that engagement, written with real evidence, not a retroactive summary.
9. `pre_write_check_run_before_writing_the_code_not_after`: Sections A/B's checks were done and stated (fact-forcing-gate messages) before each file was written this pass, not reconstructed afterward.
10. `blind_test_authoring_used_where_it_mattered`: **Run this pass, and this time authored exclusively by the blind agent** — per the user's explicit instruction, no test in this slice was self-authored; every test came from a fresh subagent given only the PRD/API contract, told to consult `skill-verification-discipline.md` failure modes 6/8, `owasp-asvs-5`, a whole-directory `owasp-cheatsheets` grep, and `bulletproof-react/docs/testing.md`, and to design tests against the 3 bug-shapes the prior Dashboard code-review pass found. Result: 19 tests, 15 passed, 4 failed — all 4 failures traced to the blind test's own artifacts (3 used a non-UUID fixture id `"e1"`/`"no-such-employee"` for `assigned_to`, tripping the schema's real `.uuid()` check before ever reaching the network — the same "malformed test UUID" class already documented earlier this session; 1 was a plain error-copy wording mismatch, "already been resolved" vs. the guessed regex `already resolved`) — reported honestly, not adjusted to force a pass, then the blind test file deleted per this session's standing convention.
11. `code_review_decision_asked_not_assumed`: Per Rule 11, whether to run an independent `/code-review` pass on this slice is being asked of the user (with reasons for/against) rather than either auto-run or silently skipped — see the conversation for that exchange.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: None newly claimed — Radix Select/react-hook-form/Zod all reused in their already-established patterns.
- `fix_verified_by_real_command_output`: **Real bug found by the blind suite, not by me**: `useForm` had no `shouldUnregister: true`, so react-hook-form kept a conditionally-rendered field's stale value (e.g. a deadline entered while on "Adjust deadline") in form state after switching to a different `resolutionType` — the schema's own combination guard correctly rejected the resulting invalid combination, but with **no visible error message** (a separate, compounding omission: `errors.resolutionType`/`errors.assignedTo` were never rendered), so the screen just silently refused to submit with no explanation. Fixed with `shouldUnregister: true` plus the two missing error-message renders. Negative control: reverted `shouldUnregister`, reran the blind suite's leak test, confirmed it failed (timed out waiting for navigation), restored, confirmed it passed. **Also found (not by the blind suite, by the Dashboard's own existing self-authored tests)**: linking each Issues Raised entry to this new screen made a task's title legitimately appear twice in the DOM whenever it has both an open issue and a spot in the All Tasks table — updated 4 assertions in `owner-dashboard-page.test.tsx` to `findAllByText(...).toHaveLength(n)` instead of a bare single-match query, same convention already used there for "Already submitted". Full suite after both fixes: `npm run lint` → 0 errors; `npm run typecheck` → clean; `npx vitest run` → **74 passed**, 13 test files (12 real + the now-deleted blind one); `npm run build` → succeeded.
- **Noted, not fixed — deferred**: `owner-task-review-page.tsx`'s own "reassigned"/"billing" branches likely share the same two gaps (no `shouldUnregister`, no `errors.assignedTo` render in its reassign block) — not touched this pass to keep scope to the slice actually being built; flagged here so it isn't silently forgotten if it ever causes a real report.
- **One permanent regression test added, on the user's explicit decision** (asked directly, per Rule 11's spirit of not silently deciding a token-cost tradeoff): the blind suite that found the `shouldUnregister` bug was deleted per this session's usual verification-only convention, which would have left zero permanent guard against it regressing. `issue-resolution-page.test.tsx` — one test, self-authored this time (the user explicitly approved this one exception to "blind-only" for this slice, since it's guarding a real bug rather than authoring the slice's initial coverage) — re-verified with the same negative control (reverted `shouldUnregister`, confirmed this test fails too, restored, confirmed it passes).

**E. Bounded claim**

- `standard_and_scope`: ASVS 5 (v8, v2), L1+L2, `Authorization_Regression_Testing_Cheat_Sheet.md`, `Business_Logic_Security_Cheat_Sheet.md`, `Mass_Assignment_Cheat_Sheet.md` — scoped to `scope_files` above, none pushed yet.
- `severity_trend_vs_last_pass`: **Zero new security findings** — this slice adds no new backend surface at all, only a frontend consumer of an already-thrice-audited backend. The one real bug found (stale conditional-field leak) is a correctness/UX defect, not a security one — the schema's combination guard correctly blocked the bad request either way, just silently.

**F. Independent pass**

- `security_review_run`: **Asked, not assumed** (Rule 11) — user chose to skip an independent `/code-review` pass for this slice, given zero new backend surface (the endpoint was already thrice-audited), the one real bug already found and fixed by the blind pass, and the fixed-domain sweep + ASVS/cheatsheet checks above coming back clean. Not silently skipped and not auto-run — a real decision, recorded here.

### Phase 4 — Tasks, Owner Side, Part 2: Dashboard (2026-09-13)

```
status: complete
phase: Phase 4 — Tasks, Owner side, part 2 (Dashboard: All Tasks table + filters, workload counts, Awaiting Review + Issues Raised panels), CODING_STRUCTURE.md §4 item 5, fifth and final post-auth Phase 4 Tasks resource slice — completes the 11-screen Phase 4 inventory's Tasks resource. First cross-feature composition point (app/-level, per FRONTEND_ARCHITECTURE.md §2's "features cannot import each other"); first aggregate/JOIN query in the whole codebase (crud.list_employees' new workload count); first frontend consumer of GET /notifications and of GET /tasks' Owner-only query filters.
scope_files: frontend/src/app/{owner-dashboard-page.tsx,router.tsx}, frontend/src/features/tasks/api/get-all-tasks.ts, frontend/src/features/notifications/**, frontend/src/features/employees/{types/index.ts,api/mappers.ts}, frontend/contract-tests/employees.contract.test.ts, frontend/src/testing/mocks/handlers.ts, backend/app/crud.py (list_employees), backend/app/api/routes/employees.py (EmployeeOut.pending_job_count), backend/tests/crud/test_employee_workload.py
date: 2026-09-13
commit: (uncommitted — base HEAD is the Tasks-Owner-Part-1 merge commit 88c929e)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v8-authorization (§8.2.2/8.4.1 re-confirmed apply unchanged to the new Owner-scoped `GET /tasks` filters and the workload aggregate — no new authorization decision point, both reuse `RequireOwnerDep`/RLS already in force); v2-validation-business-logic (checked whether the aggregate query introduces any new input-validation surface — it doesn't, `assigned_to`/`job_type_id` filters were already `UUID`-typed FastAPI query params, unchanged this pass).
- `skills_reopened_fresh`: `owasp-cheatsheets` (2 fresh greps below); `postgres-official`'s row-security-policies.md, re-read fresh for a genuinely new question this pass (does RLS apply correctly when a single query JOINs two independently-RLS-protected tables?) — not reused from any earlier read, since no prior slice ever built a cross-table JOIN.
- `cheatsheet_grep_keywords`: `query parameter.*filter|filter.*query parameter|mass assignment|IDOR` (11 files — checked whether accepting `?assigned_to=`/`?job_type_id=` from an Owner-controlled query string is itself an IDOR vector); `aggregate|count.*leak|inference attack` (9 files, none actually about cross-table DB aggregation specifically — confirmed this is a database-mechanics question `postgres-official` answers, not an OWASP web-topic, rather than silently assuming cheat sheets must cover it).
- `cheatsheet_grep_output`: `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md` re-read for the query-parameter angle specifically (not just re-cited from memory) — its general rule (access-control check on every object reference) is already satisfied: `crud.list_tasks` gates the filters behind `actor.role == "owner"`, and an Owner already has full-firm task visibility with no filter at all, so a filter query param can only ever *narrow* a set the caller could already see in full — not a privilege-escalation vector, confirmed by re-reading `crud.list_tasks` fresh (quoted in code comment) rather than assumed from the Employee-side pass's citation of the same function.

**B. Fixed-domain sweep**

- `auth`: Unchanged — `AuthenticatedHome`'s new role-branch (`router.tsx`) reuses `useSession()`'s existing `role`/`isLoading`, same pattern as every other route guard in this file.
- `session_token_lifecycle`: N/A, no new mechanism.
- `tenant_isolation`: **Real, load-bearing check — the first cross-table JOIN in this codebase.** `crud.list_employees`'s new workload query JOINs `profiles` and `tasks`, both independently RLS-protected (`ENABLE`+`FORCE ROW LEVEL SECURITY`, distinct `tenant_isolation` policies, confirmed via each table's own migration). Verified fresh against `postgres-official/chapters/row-security-policies.md` (quoted, not paraphrased from memory): "policies are table-specific... each policy for a table must have a unique name" — RLS is enforced per-relation regardless of how many tables one query touches, so this JOIN carries no new cross-tenant risk beyond what each table's own policy already guarantees independently. Frontend: `useAllTasks`/`useNotifications` are the 5th and 6th consumers of `tenantQueryKey`, each with a distinct resource string (`"tasks"`+`"all"`+filters, `"notifications"`) — confirmed no key collision with the other four.
- `object_level_authz`: N/A for new code — `GET /issues/{id}` (consumed here for the first time by a real caller) was already audited and regression-tested in the prior pass; `GET /notifications` is unchanged, already recipient-scoped server-side.
- `input_validation`: N/A, no new user input this pass — Dashboard is read-only except for the already-audited `CreateTaskDialog`, reused unchanged.
- `cors`: N/A, unchanged.
- `secrets`: N/A — no new response body cached by `with_idempotency` this pass; the workload count and task list are both plain, already-re-fetchable operational data.
- `supply_chain`: No new dependency this pass (checked `git status` on `package.json`/`package-lock.json` — no diff). `npm audit --omit=dev` → **0 vulnerabilities**.

**C. Self-check gate (mapped to skill-verification-discipline.md's 10 failure modes)**

1. `reapplied_general_principle_to_every_instance`: `tenantQueryKey` reused a 5th and 6th time, each with its own resource string, not reinvented.
2. `stress_tested_design_against_its_own_stated_logic`: Stress-tested the new `list_employees` aggregate with a **negative control** — temporarily removed the `WHERE status IN (assigned, in_progress)` filter, re-ran `test_employee_workload.py`, confirmed it failed (3 vs. expected 2), restored the filter, confirmed it passed again. Same discipline as the earlier session's Job Types finding, applied proactively this time rather than reactively.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: The RLS-across-a-JOIN question (Section B `tenant_isolation`) was checked specifically because the sweep runs every pass on every new mechanism, not because the conversation's own framing ("build the Dashboard") ever asked about it.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: `postgres-official`'s row-security-policies.md was reopened and grepped fresh for the cross-table-JOIN question — a different question from any prior read of that same file this session (which was about `FORCE ROW LEVEL SECURITY` on job_types/issues, not about JOIN behavior).
5. `compound_source_not_partial`: The tenant-isolation finding cites both tables' own migrations (already-established) **and** a fresh, direct quote from `postgres-official` **and** a re-read of `crud.list_tasks`'s actual filter-gating code — three independent checks.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 2 fresh whole-directory greps this pass (listed in A) — one confirmed a real gap in OWASP's own coverage (cross-table DB aggregation isn't a cheat-sheet topic) rather than silently assuming it must be covered somewhere and moving on.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: Asked what's different about `GET /tasks`'s Owner-filter query params being exercised by a real caller for the first time (Section A's last bullet) — confirmed narrowing-only, no new exposure, rather than assuming a previously-unused code path is automatically safe just because it already existed.
8. `comprehensiveness_claim_backed_by_the_actual_checklist`: This audit **is** that engagement — set to `in-progress` (now `complete`) before this write-up, with real evidence, not a retroactive summary.
9. `pre_write_check_run_before_writing_the_code_not_after`: The RLS-per-table question was actually researched and quoted **before** `list_employees` was written (visible earlier in this session, in the same message as the fact-forcing-gate statement for that edit) — not reconstructed afterward for this audit.
10. `blind_test_authoring_used_where_it_mattered`: **Yes, run this pass** — a fresh agent, given only the API/component contract for `OwnerDashboardPage` (not its source), wrote its own test suite. 3/5 passed independently; the 2 failures were the test's own query-ambiguity bugs (`findByText` matching "Alex Employee"/"Already submitted" in more than one legitimate place), not implementation defects — confirmed by inspecting the actual rendered DOM in both failures, which showed the correct behavior (workload count "2", not "3") already present. Not "fixed" to force a pass, per the same discipline as the previous blind-test pass.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: None newly claimed this pass — Radix Select reused unchanged (already verified against its own `.d.mts` last pass); no new library introduced.
- `fix_verified_by_real_command_output`: Negative control on the workload count (above) — confirmed fails on broken code (3≠2), passes restored. Full suite: `npm run lint` → 0 errors, 5 pre-existing warnings; `npm run typecheck` → clean; `npx vitest run` → **53 passed**, 12 test files; `npm run build` → succeeded. Backend: `uv run ruff check .` → clean; `uv run pyright` → 0 errors; `uv run pytest` → **110 passed**, 70 skipped (real-DB tests, run in CI). Blind-authored test suite run separately (above): 3/5 passed, 2 confirmed-not-bugs.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5 (v8, v2), L1+L2, `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md`, `postgres-official`'s row-security-policies.md — scoped to `scope_files` above, base commit `88c929e`, plus this pass's own additions, none pushed yet.
- `severity_trend_vs_last_pass`: **Zero security findings this pass** — lower than every prior Tasks pass. Read as the expected, healthy outcome of a slice that composes already-audited pieces (Select, Idempotency-Key patterns, RLS, object-level-authz on `GET /issues/{id}`) rather than introducing new security-relevant mechanisms of its own; the one genuinely new mechanism (the cross-table aggregate JOIN) was checked against its own real question (RLS-per-table) and cleared, not skipped for lack of an obvious finding to report.

**F. Independent pass**

- `security_review_run`: Not run as a separate `code-review` agent pass — this pass's one novel mechanism (the aggregate JOIN) was verified directly against official Postgres docs plus a negative-control test; its other novelty (cross-feature composition) is an architecture concern already resolved by `FRONTEND_ARCHITECTURE.md`'s own explicit rule, not a fresh security question. This completes the full Tasks resource (both Employee and Owner sides) — a natural point for the deferred full independent `code-review` sweep across the whole resource, named again as still outstanding, not silently dropped.

**Follow-up (2026-09-13) — the deferred independent `code-review` pass named above was run against this
slice plus its regression-test follow-up commit (`HEAD~2..HEAD` on `main`: PRs #52 and #53). 6 findings,
none security-critical on their own, but 3 were real correctness/authorization-adjacent bugs that every
standing gate (pre-write skill check, this checklist, negative-controlled tests) had already passed. Fixed,
each proven by negative control (temporarily reverted, confirmed the regression test failed, restored):**

1. **`router.tsx`'s `AuthenticatedHome`** defaulted to `<OwnerDashboardPage />` for any role other than
   `"employee"`, including the reachable `role === null` case (a signed-in session with a missing/malformed
   `app_metadata.role` claim) — diverging from this same file's own `OwnerRoute`/`EmployeeRoute` default-deny
   convention. Fixed to explicit-allow (`role === "owner"` → Dashboard, `role === "employee"` → redirect,
   anything else → render nothing). New test: `router.test.tsx`'s "renders nothing for a session with no
   recognized role" — negative-controlled (reverted, confirmed the Dashboard leaked through, restored).
2. **Awaiting Review / Issues Raised were derived from the same *filtered* task list as the All Tasks
   table**, so an Owner-selected filter silently hid unrelated entries from those other panels — and the
   slice's own prior test asserted that disappearance as expected, passing behavior (exactly the self-
   grading bias rule 10.2 exists to catch). Fixed by fetching an unfiltered `allTasks` list for those two
   panels, separate from the `filteredTasks` list the All Tasks table alone uses. New test:
   `owner-dashboard-page.test.tsx`'s "keeps a submitted task in Awaiting Review even when the All Tasks
   status filter excludes it" — negative-controlled.
3. **`crud.list_tasks` had no `ORDER BY`**, and this slice's `useAllTasks` never sent `limit`/`offset` —
   past the route's default of 20 rows, tasks could silently vanish in non-deterministic order. This bug
   pre-dated this slice; it only became reachable once the Dashboard was the first caller needing >20 rows.
   Fixed with a deterministic `.order_by(created_at desc, id)` (matching `list_notifications`' own existing
   precedent) plus an explicit `limit=100` sent from the Dashboard (the route's own max, sufficient for this
   project's current ~30-user/2-4-firm target scale — real pagination is a separate future feature if that
   changes). New tests: `backend/tests/crud/test_task_ordering.py` — negative-controlled (the ordering test
   failed without the fix; the pagination test happened to still pass on SQLite's coincidental rowid order,
   which is itself the expected shape of a "no guarantee" bug, not a flaw in the test).

**Noted, not fixed this pass — deferred, to be revisited if they cause a real problem:**
- Task-mutation hooks (`create-task.ts` and its siblings) invalidate only the `tasks` query cache, never
  `employeesQueryKeyPrefix`, so the Workload panel's `pendingTaskCount` can go stale until an unrelated
  remount/refocus. Self-heals; no data loss.
- `IssueRow` calls `useIssue(issueId ?? "")` without gating on a non-empty id — currently unreachable, since
  the backend always sets `issue_id` on an `issue_raised` notification; dormant defense-in-depth only.
- Issues Raised fires one `GET /issues/{id}` request per row instead of batching — a real N+1, but pure
  efficiency, not correctness, and this project's current scale keeps the open-issue count small.

This is Rule 11's decision protocol in `skill-verification-discipline.md` applied for real, not just stated:
weighed running `/code-review` against its token cost, ran it because this slice was a cross-cutting `app/`-
layer composition point with self-authored tests, found 3 real bugs the standing gates missed, fixed and
negative-control-verified those 3, and explicitly deferred the other 3 rather than fixing everything found
indiscriminately.

## Completed Audits

### Phase 4 — Tasks, Owner Side, Part 1: Create Task + Task Review (2026-09-12)

```
status: complete
phase: Phase 4 — Tasks, Owner side, part 1 (Create Task + Task Review, incl. Billing sub-form), CODING_STRUCTURE.md §4 item 5, fourth post-auth Phase 4 resource slice — first frontend use of Radix Select, first frontend outcome-conditional Zod validation mirroring a backend model_validator, and a new backend read endpoint (GET /issues/{id}). Dashboard/Awaiting-Review/Issues-Raised panels explicitly deferred to a follow-up pass (this session's own scoping decision, made twice this pass as the real shape of the work became clear)
scope_files: frontend/src/features/tasks/components/{create-task-dialog,owner-task-review-page}.tsx(+.test.tsx), frontend/src/features/tasks/api/{create-task,create-task-review,get-issue}.ts, frontend/src/features/tasks/types/index.ts (taskCreateSchema/taskReviewSchema additions), frontend/src/components/ui/select.tsx (new), frontend/src/app/router.tsx (OwnerTaskReviewRoute + route), frontend/src/testing/{setup-tests.ts (jsdom polyfills), mocks/handlers.ts (new fixtures/handlers)}, backend/app/api/routes/issues.py (new GET /issues/{id}), backend/tests/api/routes/test_issues.py + backend/tests/api/test_authz_regression.py (new tests), docs/API_SPEC.md
date: 2026-09-12
commit: (uncommitted — base HEAD is the Tasks-Employee-side merge commit 1c836a8)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v8-authorization (re-confirmed §8.2.2/8.1.2 already cited this session apply identically to the new `GET /issues/{id}` — Owner-only, RLS-scoped, no new mechanism); v2-validation-business-logic (§2.3.1 re-checked — grepped fresh for a "validate combinations"/"mutually exclusive" ASVS line specifically for the frontend Zod mirror of `TaskReviewCreate`'s outcome-conditional fields: **zero matches** — confirmed this requirement lives only in `Business_Logic_Security_Cheat_Sheet.md`, not ASVS, so it's cited from there, not misattributed to a chapter that doesn't cover it).
- `skills_reopened_fresh`: `owasp-cheatsheets` (2 targeted greps below, on top of this session's earlier 5); `owasp-asvs-5` v8/v2 (re-confirmed, not re-read from scratch since the exact same chapters/sections were opened earlier this session for the Employee-side pass and nothing about this pass's mechanisms falls outside what those sections already cover — the new "combinations" question was answered by *not* finding an ASVS match, which is itself a real check, not a skip).
- `cheatsheet_grep_keywords`: `validate combinations|business logic` (confirms `Business_Logic_Security_Cheat_Sheet.md`'s "Validate Combinations" section, already the cited source for `TaskReviewCreate`'s backend `_validate_outcome_fields`, is the same and only source for its frontend Zod mirror — not a new mechanism needing a new source); `scoped package|npm.*scope|dependency confusion` (for the 2 new npm dependencies this pass, below).
- `cheatsheet_grep_output`: 2 whole-directory greps (33 and 4 files matched respectively) — no new cheat sheet surfaced beyond what this session's earlier 5 greps this same day already found; re-run specifically to confirm nothing new applies to *this* pass's own mechanisms (Select UI, outcome-conditional Zod, 2 new deps), not assumed carried over from the earlier grep's results.

**B. Fixed-domain sweep**

- `auth`: Unchanged — `OwnerRoute` (already exists) gates the new `owner-tasks/:taskId/review` route the same way it gates `/employees`/`/job-types`; confirmed by reading the new route entry in `router.tsx` directly, not assumed.
- `session_token_lifecycle`: N/A, no new mechanism.
- `tenant_isolation`: `get-issue.ts` is the **fourth** consumer of `lib/tenant-query-key.ts`, with its own distinct resource string (`"issues"`) — confirmed no key collision with `"tasks"`/`"employees"`/`"job-types"` by reading all four call sites. Backend: `GET /issues/{id}` relies on the same `issues` table RLS (`ENABLE`+`FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy, migration `a3f5c9e21d07`) already re-verified fresh at pre-write time (quoted in the code comment) — not re-verified a second time here since it's the same fact checked minutes earlier in the same session, not a stale cross-session claim.
- `object_level_authz`: **Real, load-bearing check — a genuine gap found and closed, not just confirmed.** `GET /issues/{id}` had **zero** authorization-regression test coverage before this pass (`resolve_issue`'s existing cross-tenant test doesn't exercise a different endpoint) — added `test_cross_tenant_issue_read_is_404` to `test_authz_regression.py`, matching this session's own earlier-established rule ("a shared mechanism being vetted once does not make it vetted for every new call site") applied to a *new endpoint* rather than a new caller of an existing one. `CreateTaskDialog`/`OwnerTaskReviewPage` themselves make no new object-level-authz decision — `create_task` is `RequireOwnerDep`-gated (no per-object check needed, it's a create), `review_task` reuses `_get_task_or_404` already covered under `GET /tasks/{id}`'s existing cross-tenant test.
- `input_validation`: **Real, load-bearing check.** `taskReviewSchema`'s `superRefine` was written to mirror `TaskReviewCreate._validate_outcome_fields` field-for-field (all 3 outcome branches, both "required" and "must not be set" directions) — verified by reading the backend validator's exact logic fresh in this same pass (not from memory of the earlier employee-side read) before writing the Zod mirror, and then **empirically stress-tested by the billing-outcome test itself**, which would have failed on submission if the mirror were looser than the backend (the MSW handler enforces status/task_type checks but not the outcome-combination rule, so a wrong client schema wouldn't have been caught by the fixture — it was caught by writing the schema correctly the first time, checked directly against source, not by the test). No NUL-byte handling on the frontend (unchanged, UX-only precedent already established — backend `NoNulStr` is authoritative).
- `cors`: N/A, unchanged.
- `secrets`: **New call sites of `with_idempotency` asked the same question again, not assumed answered by precedent.** `create_task`'s response (`TaskOut`) and `review_task`'s response (`TaskOut`, potentially carrying fresh `billing_amount`/`billing_recipient` on the `billing` outcome) are both cached-and-replayed for 24h by the pre-existing, already-vetted mechanism — same conclusion as the Employee-side pass's `secrets` finding (operational data, not a one-time secret, already re-fetchable via a plain `GET` regardless), re-derived for these two specific new callers rather than assumed to transfer automatically.
- `supply_chain`: 2 new dependencies this pass — `@radix-ui/react-select` (official `@radix-ui`-scoped package, same publisher already trusted for `react-dialog`/`react-dropdown-menu`, no dependency-confusion risk per `Software_Supply_Chain_Security_Cheat_Sheet.md`'s scoped-package guidance) and `@testing-library/user-event` (dev-only, official `@testing-library`-scoped package, same publisher as the already-installed `@testing-library/react`/`jest-dom`). `npm audit --omit=dev` → **0 vulnerabilities**.

**C. Self-check gate (mapped to skill-verification-discipline.md's 10 failure modes)**

1. `reapplied_general_principle_to_every_instance`: `tenant-query-key.ts` reused a 4th time (`get-issue.ts`) with its own resource string, not reinvented.
2. `stress_tested_design_against_its_own_stated_logic`: The claim "the Zod mirror matches the backend validator" was stress-tested by actually writing and running the billing-outcome test end-to-end against the real component + MSW, not just eyeballing the two field lists side by side — this is what caught the two real, distinct bugs in D below.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B's `object_level_authz` check went looking for regression-test coverage of the brand-new `GET /issues/{id}` endpoint specifically because the sweep runs every pass, not because the conversation's own framing ("build Create Task + Task Review") ever mentioned Issues at all.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: ASVS v2 was re-opened and grepped fresh for the "combinations" sub-question — a different question from the `§2.3.1` sequential-order citation already used earlier this session for the same chapter.
5. `compound_source_not_partial`: The `GET /issues/{id}` object-level-authz finding cites the RLS migration, the route's own `RequireOwnerDep`, and a new real regression test — three independent forms of evidence.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 2 fresh whole-directory greps this pass, on top of the 5 already run earlier the same session for the Employee-side pass — not treated as "already covered" without re-checking against this pass's own specific new mechanisms (Select, outcome-conditional Zod, 2 new deps).
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: Re-asked (Section B `secrets`) for `create_task`/`review_task`'s specific response payloads rather than assuming the Employee-side pass's answer for `submit_task`/`mark_task_billed` automatically covers these two different endpoints.
8. `comprehensiveness_claim_backed_by_the_actual_checklist`: This audit **is** that engagement — set to `in-progress` before this write-up, filled with real evidence, not a retroactive summary.
9. `pre_write_check_run_before_writing_the_code_not_after`: The 3-line pre-write check was run, visibly, before both the `GET /issues/{id}` route and each new frontend file — grep, ASVS chapter, call-site-diff line, all in the message immediately preceding each `Write`/`Edit`, not added after the fact.
10. **New this pass, the rule this session's own testing-discipline conversation just added**: `owner-task-review-page.test.tsx`'s billing-outcome test is itself a negative-control-style check on the Zod schema — it would have failed had the schema been wrong, and it *did* fail twice during actual writing (the `useWatch` compiler-memoization warning is unrelated; the two real failures were the "e1"-isn't-a-UUID and the "1111...1111"-isn't-RFC-4122-valid bugs, both caught by the test failing loudly with a real error, not passing silently). No blind-test-authoring pass was used this turn — these tests were still author-and-code in the same pass — named honestly rather than silently treated as satisfying rule 10.2, which remains open for whichever future pass first warrants it.

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: Radix Select's exact subcomponent API (`Root`/`Trigger`/`Value`/`Icon`/`Portal`/`Content`/`Viewport`/`Item`/`ItemText`/`ItemIndicator`) verified against the installed package's own `.d.mts` file before writing `select.tsx` — no installed skill documents this library. React Hook Form's `useWatch` verified against the installed package's own `useWatch.d.ts` before switching away from `useForm().watch()` (which ESLint's `react-hooks/incompatible-library` rule flagged as memoization-unsafe with React Compiler) — not guessed from general RHF familiarity.
- `fix_verified_by_real_command_output`: **Two real, reproduced-then-fixed bugs, not just a final green run.** (1) `Element.prototype.scrollIntoView is not a function` — reproduced by actually running the new Select-interaction test before any jsdom polyfill existed, fixed by adding `scrollIntoView`/`hasPointerCapture`/`setPointerCapture`/`releasePointerCapture` no-op stubs to `setup-tests.ts`, re-run to confirm the specific error was gone. (2) The billing-outcome test still failed after the polyfill with `assignedTo`'s Zod validator reporting "Invalid UUID" — traced through two wrong hypotheses (fixed by switching `fireEvent.click` to `@testing-library/user-event` first, which turned out necessary but not sufficient; then discovered the test's own placeholder UUID `11111111-1111-1111-1111-111111111111` fails RFC 4122's variant-nibble requirement, fixed by using a properly-formed v4/variant-8 UUID) — both fixes verified by re-running the exact failing test after each change, not assumed fixed from reasoning alone. Full suite after all fixes: `npm run lint` → 0 errors, 5 pre-existing warnings; `npm run typecheck` → clean; `npx vitest run` → **48 passed**, 11 test files; `npm run build` → succeeded. Backend: `uv run ruff check .` → clean; `uv run pyright` → 0 errors; `uv run pytest` → **108 passed**, 70 skipped (real-DB tests, run in CI).

**E. Bounded claim**

- `standard_and_scope`: ASVS 5 (v8, v2), L1+L2, `Business_Logic_Security_Cheat_Sheet.md`, `Software_Supply_Chain_Security_Cheat_Sheet.md` — scoped to `scope_files` above, base commit `1c836a8`, plus this pass's own additions, none pushed yet.
- `severity_trend_vs_last_pass`: One real gap found and closed (missing regression test for the brand-new `GET /issues/{id}` endpoint) — same category and severity as the Employee-side pass's finding (test-coverage gap in the audit's own evidence chain for a new/changed call site), not a live vulnerability. The two real bugs caught in D were test-infrastructure/environment bugs (jsdom gaps, a malformed test fixture UUID), not application-code defects — a different, lower-stakes category than prior passes' findings, and named as such rather than inflated to look more significant.

**F. Independent pass**

- `security_review_run`: Not run as a separate `code-review` agent pass — this pass's genuinely new mechanisms (Radix Select, outcome-conditional Zod validation, the new `GET /issues/{id}` route) were each verified by a real, run-to-green test rather than left for a separate reviewer to catch; the two real bugs surfaced during that verification, not after. The still-deferred Dashboard pass (cross-feature composition, notifications read-path, workload counts) remains the candidate for a full independent sweep, as already named in the Employee-side pass's own F section.

### Phase 4 — Tasks, Employee Side (Frontend Feature Slice) (2026-09-12)

```
status: complete
phase: Phase 4 — Tasks, Employee side (frontend feature slice), CODING_STRUCTURE.md §4 item 5, third post-auth Phase 4 resource slice — first to introduce real workflow-state transitions and a second Idempotency-Key-generating call site (submit/mark-billed/raise-issue) on the frontend; Owner side (Dashboard/Create Task/Review/Billing) explicitly deferred to a second pass per this session's own scoping decision
scope_files: frontend/src/features/tasks/**, frontend/src/app/router.tsx (EmployeeRoute + TaskDetailRoute + nav link + route wiring), frontend/src/testing/mocks/handlers.ts (tasks fixture), backend/tests/api/test_authz_regression.py (2 new tests, this pass), backend/app/api/routes/tasks.py + backend/app/crud.py (list_tasks/get_task/submit_task/mark_task_billed/create_issue/_lock_task — pre-existing, re-read fresh this pass, not modified)
date: 2026-09-12
commit: (uncommitted — this slice's own files, base HEAD is the Job Types merge commit 1d386d7)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v8-authorization (re-opened fresh this pass, full V8.1-V8.4 table re-read, not just §8.4.1 from memory — quoted verbatim below); v2-validation-business-logic (§2.3.1 re-read fresh for the workflow-state-transition mechanism, quoted below); v14-data-protection (checked fresh whether `billing_amount`/`billing_recipient` in `TaskOut` count as data needing masking under §14.2.6 — see B/`secrets` below). Not reopened in full: v1/v3/v4/v5/v6/v7/v9-v17 — this slice introduces no new mechanism in those domains beyond what Phase 4 Step 1 and the Employees/Job-Types audits already covered (same auth/session/CORS/crypto/logging surface, zero new file-upload/OAuth/WebRTC/token surface); confirmed via a fresh scope-statement re-read of each, not skipped silently.
- `skills_reopened_fresh`: `owasp-cheatsheets` (5 whole-directory greps, below); `owasp-asvs-5` v8/v2/v14 (above).
- `cheatsheet_grep_keywords`: `workflow|state machine|status transition|business logic`; `financial|monetary|payment amount|currency|billing`; `stored xss|user.generated content|reflected|output encoding`; `confused deputy|horizontal privilege|vertical privilege`; `replay|cache.{0,15}response|response.{0,15}cache` — 5 greps derived from this slice's actual mechanisms (real workflow-state transitions for the first time, `billing_amount`/`billing_recipient` now reachable by an employee, free-text issue descriptions rendered back on screen, the 403-vs-404 visible-but-not-actionable distinction `_require_assignee` introduces, and the idempotency cache now replaying a response body that carries financial fields) — not from familiar cheat-sheet titles.
- `cheatsheet_grep_output`: whole `owasp-cheatsheets/cheatsheets/` directory, 5 separate greps (33/27/17/5/25 files matched respectively). Two files read in full that had never been opened in this project before (failure mode 6 — not stopping at the titles already familiar from prior passes): `Transaction_Authorization_Cheat_Sheet.md` (its 2FA/step-up-authorization scope turned out mostly N/A — this project has no second-factor for any operation, task actions included, so §1.1-1.4/2.9 don't apply — but §2.5 "control which transaction state transitions are allowed" and §2.8 "check each transaction execution... TOCTOU" are exactly what `_lock_task`'s status guard + `SELECT...FOR UPDATE` already implement, re-confirmed against `crud.py:452-474` fresh this pass, not assumed still true from the earlier concurrency-fix entry) and `Authorization_Regression_Testing_Cheat_Sheet.md` (its "Horizontal Escalation / Multi-User Replay" pattern — authenticate as User A, create a resource, authenticate as User B of the same role, assert 403/404 on read+write — directly named the exact test shape this slice needed; see C/D below for what that grep actually surfaced). `Business_Logic_Security_Cheat_Sheet.md` and `Multi_Tenant_Security_Cheat_Sheet.md` re-surfaced (same content already applied via `_lock_task`/`tenant-query-key.ts`; re-confirmed still followed by the 3 new call sites, not a new finding). No `dangerouslySetInnerHTML`/`innerHTML`/`document.write`/`eval(` in `frontend/src/features/tasks` — grepped fresh, zero matches (Cross_Site_Scripting_Prevention_Cheat_Sheet.md's baseline rule, re-confirmed for the free-text issue description/task title/description rendering).

**B. Fixed-domain sweep**

- `auth`: Unchanged — `EmployeeRoute` (new this slice, `router.tsx`) mirrors `OwnerRoute` inverted, confirmed by reading both side by side. Server-side, every Tasks route re-derives role from the DB `Profile` row (`ActiveProfileDep`/`RequireOwnerDep`), never the JWT claim — same pattern `test_jwt_owner_claim_does_not_grant_job_type_creation` already regression-tests for other resources.
- `session_token_lifecycle`: N/A, no new mechanism — reuses `session-store.tsx`'s already-fixed `queryClient.clear()`-on-logout path unchanged.
- `tenant_isolation`: Third reuse of `lib/tenant-query-key.ts` with a distinct resource string (`"tasks"`) — confirmed no key collision with `"employees"`/`"job-types"` by reading all three call sites side by side. Backend: `crud.list_tasks`/`crud.get_task` re-read fresh this pass (`crud.py:374-415`) — role-scoped, not just filtered (an Employee's `assigned_to == actor.id` filter is applied unconditionally, Owner-only query filters are gated behind `actor.role == "owner"`); RLS on `tasks` already covered structurally by the Job Types entry's migration-level check (same table family, same policy shape) — not re-read line-by-line this pass since no new migration was added.
- `object_level_authz`: **Real, load-bearing check this pass, not a restatement.** `get_task` returns `None` (404) for an Employee requesting another's task — but a *third* code path exists that a plain 404-not-403 framing misses: `_require_assignee` (`tasks.py:27-32`) additionally 403s an Owner (who *can* see every task via `get_task`, since Owner visibility is broader than assignee-only) attempting to submit/mark-billed/raise-issue on a task they're not assigned to. Verified this is intentional, documented, and correctly scoped against ASVS 8.1.2/8.2.3 ("field-level access may depend on other attributes of the object... mitigates BOPLA") — the *write* action here is authorized more narrowly than the *read* visibility, which is exactly what 8.1.2 describes, not an inconsistency. Traced the actual reachability: for an Employee actor, `_require_assignee`'s condition can never fire on a task `get_task` already let through, since `get_task` already restricts Employee visibility to `assigned_to == actor.id` — so the 403 branch is live only for the Owner-role case. Confirmed by reading `crud.get_task` and `tasks.py`'s `_require_assignee` together line-by-line, not assumed from the docstring's own claim.
  - **Gap found and fixed, not just noted:** `Authorization_Regression_Testing_Cheat_Sheet.md`'s "Multi-User Replay" pattern was already implemented as a real-DB test for `submit` (`test_other_employees_task_cannot_be_submitted`) but **not** for `mark-billed` or `raise-issue`, even though both route through the identical `_get_task_or_404`/`_require_assignee` pair. Per this project's own already-stated principle ("a shared mechanism being vetted once does not make it vetted for every new call site"), added `test_other_employees_task_cannot_be_marked_billed` and `test_other_employees_task_cannot_have_an_issue_raised_on_it` to `backend/tests/api/test_authz_regression.py`, same shape as the existing submit test. Verified locally: `uv run pytest tests/api/test_authz_regression.py -v` → 15 collected (13 existing + 2 new), all cleanly `SKIPPED` (no real Postgres set locally, same as every prior pass — `ruff check`/`pyright` both clean on the file); will actually execute against real Postgres once this branch's CI runs the `authz`-marked suite, same mechanism the Employees/Job-Types passes' cross-tenant tests already run under.
- `input_validation`: `raiseIssueSchema` (Zod, `min(1)`/`max(2000)`) re-confirmed fresh this pass to match `IssueCreate`'s `NoNulStr, min_length=1, max_length=2000` exactly (`tasks.py:150`). No new dependency, no new upload/file surface.
- `cors`: N/A, unchanged.
- `secrets`: **New call-site question asked and answered, not assumed clear by precedent.** `submit_task`/`mark_task_billed`/`create_task_issue` are all wrapped in the same `with_idempotency` cache-and-replay mechanism a prior pass (2026-09-08/09) already vetted and fixed for TOCTOU/tenant-context bugs — but per this project's own "what's different about this call site's data" discipline, re-asked the question for this specific payload: `TaskOut`'s response (cached 24h on retry) includes `billing_amount`/`billing_recipient` for a billing-type task. Checked against ASVS 14.2.6 ("return only the minimum sensitive data needed... mask unless the user requests it") and 14.2.2 ("sensitive data isn't cached... or is securely purged after use"): **not a violation** — unlike Employees' `generated_password` (a one-time credential that must never be retrievable a second time, per that entry's own already-documented spec line), `billing_amount`/`billing_recipient` are the billing task's own operating instructions, already fully retrievable by the same assigned employee at any time via a plain `GET /tasks/{id}` with no idempotency involved at all — the 24h replay cache doesn't create a new exposure window, it just returns slightly-stale data of a kind the caller could already re-fetch fresh. Explicitly not the same shape as the password-reset regression this discipline exists to prevent, and said so rather than skipping the question because the mechanism was "already audited."
- `supply_chain`: No new dependency added this slice (`git status` on `package.json`/`package-lock.json` — no changes). `npm audit --omit=dev` → **0 vulnerabilities**.

**C. Self-check gate (mapped to skill-verification-discipline.md's 9 failure modes)**

1. `reapplied_general_principle_to_every_instance`: `tenant-query-key.ts` reused a third time with its own distinct resource string, not reinvented.
2. `stress_tested_design_against_its_own_stated_logic`: Stress-tested the "404-not-403 for object access" claim against its own stated exception — `_require_assignee`'s real 403 for an Owner acting on a non-assigned task looked like a violation of that rule at first glance; traced it against ASVS 8.1.2 (field/action-level access can legitimately differ from read-visibility) and confirmed it's the documented, correct exception, not an inconsistency to flag.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B's `object_level_authz` check went past "is there a 404 gap" (there wasn't) into "is the *shared mechanism* actually tested at every one of its 3 call sites" (it wasn't) — the sweep surfaced a test-coverage gap the conversation's own framing ("continue the next slice") never asked about directly.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: ASVS v8's full table (not just §8.4.1) re-read fresh this pass for the field-level-access question, a different sub-question from the Job Types pass's tenant-isolation citation of the same chapter.
5. `compound_source_not_partial`: The object-level-authz finding cites ASVS 8.1.2/8.2.3, `Authorization_Regression_Testing_Cheat_Sheet.md`'s named pattern, a direct source-level trace of `crud.get_task`/`_require_assignee`, *and* a new real test added and locally collection-verified — four independent forms of evidence, not one assumed sufficient.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 5 keyword greps across the whole directory this pass (listed in A), surfacing two never-before-opened files (`Transaction_Authorization_Cheat_Sheet.md`, `Authorization_Regression_Testing_Cheat_Sheet.md`) neither of which would have been picked from title-familiarity alone.
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: Explicitly asked and answered in Section B `secrets` — checked whether `TaskOut`'s billing fields have the Employees password-reset's one-time-secret property before assuming `with_idempotency`'s prior clearance transferred; confirmed it doesn't, for a stated reason.
8. `comprehensiveness_claim_backed_by_the_actual_checklist`: This audit **is** that engagement — `status: in-progress` was set before analysis began, and the two new regression tests plus the stale-comment fix (D below) are evidence a real checklist was run, not a retroactive claim of "already covered."
9. `pre_write_check_run_before_writing_the_code_not_after`: The pre-write OWASP/ASVS check (idempotency-key ownership via `rest-api-guidelines`, React `useMemo`/`key`-remount semantics via `react-official`) was run before writing this slice's code, visible earlier in this session. What this audit pass caught that the pre-write check didn't: the shared-mechanism-not-tested-at-every-call-site gap (item 3/6 above) is inherently a *post-write, cross-call-site* check — no single call site's pre-write review could have surfaced "this shared function has 3 callers and only 1 has a regression test," since that requires seeing all 3 together. Named as the pre-write check's honest scope limit, not folded silently into "the rule caught everything."

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: None newly claimed this pass — no new library behavior introduced beyond what the Job Types/Employees passes already verified (TanStack Query invalidation, React `useMemo`/`key` semantics — the latter verified in this session's own build step, prior to this audit).
- `fix_verified_by_real_command_output`: `npm run lint` → 0 errors, 5 pre-existing warnings (unchanged); `npm run typecheck` → clean; `npm run test` → **42 passed**, 9 test files; `npm run build` → succeeded (all re-confirmed earlier this session, prior to this audit pass, and unaffected by this pass's own changes — the 2 backend test additions and 1 stale-comment fix touch no frontend runtime code). Backend: `uv run ruff check tests/api/test_authz_regression.py` → all checks passed; `uv run pyright tests/api/test_authz_regression.py` → 0 errors; `uv run pytest tests/api/test_authz_regression.py -v` → 15 collected, 15 skipped locally (no real Postgres set in this environment — same documented gap as every prior pass's real-DB tests; will run for real in CI).
- **Stale-comment bug found and fixed, small but real.** `submit-task.ts`'s header comment still described the idempotency key as generated "via `useMemo(taskId)`" — accurate when first written, but superseded by this session's own `useState` + `key`-remount fix (documented in `task-detail-page.tsx`/`router.tsx`) before this audit pass began. A stale comment describing a mechanism the code no longer uses is exactly the kind of drift `skill-verification-discipline.md` warns against trusting; found by re-reading the file fresh for this audit rather than assuming the comment was still accurate because the underlying behavior was already correct. Fixed to describe the actual `useState`/`TaskDetailRoute key` mechanism.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5 (v8, v2, v14 — chapters actually touched by this slice), L1+L2, scoped to `frontend/src/features/tasks/**` + router/handlers wiring + 2 new backend regression tests + a re-read (not re-write) of the pre-existing backend `tasks` route/crud, as of base commit `1d386d7`, plus this pass's own additions — none pushed yet.
- `severity_trend_vs_last_pass`: Lower raw count than Employees (0 vs 2 fixed security gaps) but a genuinely different *kind* of finding than Job Types' (a maintainability nit) — this pass's real finding (missing regression coverage for 2 of 3 call sites of an already-correct shared authorization check) is a test-coverage gap in the audit's own evidence chain, not a live vulnerability: the code path is identical for all 3 routes, so the *behavior* was very likely already correct, but "very likely correct by code-path identity" and "verified correct by an actual test" are different claims, and only the first held before this pass. Closing that gap is exactly the kind of finding this slice's larger, multi-endpoint shape (vs. Job Types' single-screen CRUD) was expected to surface.

**F. Independent pass**

- `security_review_run`: Not run as a separate `code-review` agent pass this time — this slice reuses 3 already-independently-reviewed mechanisms (`tenant-query-key.ts`, `with_idempotency`, the `key`-remount pattern verified against official React docs earlier this session) rather than introducing a new cross-cutting one, and the regression-test gap was caught by this audit's own C/D self-check rather than needing a separate agent sweep to surface it. Named honestly as a scope-narrower: the Owner-side pass (Dashboard/Create Task/Task Review/Billing Task Creation) introduces the review-outcome branching and the reassignment/billing-task-spawning logic for the first time on the frontend — that pass should get the full independent `code-review` sweep, not inherit this slice's lighter treatment.

### Phase 4 — Job Types (Frontend Feature Slice) (2026-09-11)

```
status: complete
phase: Phase 4 — Job Types (frontend feature slice), CODING_STRUCTURE.md §4 item 5, second post-auth Phase 4 resource slice
scope_files: frontend/src/features/job-types/**, frontend/src/app/router.tsx (nav link + route wiring), frontend/src/testing/mocks/handlers.ts (job-types fixture), backend/app/api/routes/job_types.py + backend/app/crud.py (create_job_type/list_job_types/get_job_type/set_job_type_active — pre-existing, re-read fresh this pass, not modified)
date: 2026-09-11
commit: a9eaea6 (base HEAD at audit start — this slice's own files land on top, uncommitted, not yet pushed)
```

**A. Fixed enumeration**

- `asvs_chapters_opened`: v8-authorization (re-opened fresh this pass, §8.4.1 grepped and quoted verbatim below — not reused from memory of the Employees audit's citation of the same section); v14-data-protection (checked whether this slice carries any secret/one-time-value — confirmed no, unlike Employees' generated_password); v2-validation-business-logic (Zod schema + backend NoNulStr bound, re-confirmed matches). Not reopened in full: v1/v3/v4/v5/v6/v7/v9-v17 — this slice introduces no new mechanism in those domains beyond what Phase 4 Step 1 and the Employees-slice audit already covered (same auth/session/CORS/crypto/logging surface, zero new file-upload/OAuth/WebRTC/token surface); confirmed via a fresh scope-statement re-read of each, not skipped silently.
- `skills_reopened_fresh`: `owasp-cheatsheets` (4 whole-directory greps, below); `owasp-asvs-5` v8-authorization (above). Not reopened: `bulletproof-react`/`fastapi`/`react-official` — no new structural pattern introduced beyond what the Employees slice already established and this pass explicitly re-verified reuse of (`lib/tenant-query-key.ts`), not a fresh pattern needing its own doc check.
- `cheatsheet_grep_keywords`: `idor|object.level.authoriz|broken.access.control`; `race condition|duplicate|unique constraint|toctou`; `tenant`; `client.side cach|browser cach|query cach|stale data|logout` — 4 greps derived from this slice's actual mechanisms (UUID-scoped `{id}` update route, DB-unique-constraint-based duplicate-name dedup, the second-ever tenant-scoped cache-key consumer, no new session/cache-lifecycle mechanism since it reuses the already-fixed one).
- `cheatsheet_grep_output`: whole `owasp-cheatsheets/cheatsheets/` directory, 4 separate greps (9/17/14/14 files matched respectively, listed in the terminal record this pass, not re-pasted here in full — the load-bearing hit was `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md`, read in full: its "Identifier complexity"/"Mitigation" sections state UUIDs are defense-in-depth only, access-control checks are still required per-object — matches `update_job_type`'s actual behavior, verified directly against `crud.get_job_type`/`crud.set_job_type_active` source, not assumed). `Business_Logic_Security_Cheat_Sheet.md` and `Multi_Tenant_Security_Cheat_Sheet.md` re-surfaced (same content already applied via the shared `tenant-query-key.ts`/`commit_or_recover` mechanisms — re-confirmed still followed by this new call site, not a new finding).

**B. Fixed-domain sweep**

- `auth`: Unchanged — `OwnerRoute` gates `/job-types` the same way it gates `/employees` (`router.tsx`, confirmed by reading the diff directly, not assumed from the Employees pattern).
- `session_token_lifecycle`: N/A, no new mechanism — reuses `session-store.tsx`'s already-fixed `queryClient.clear()`-on-logout path unchanged.
- `tenant_isolation`: **Checked at two layers, both confirmed sound, not just one.** Frontend: `useJobTypes()` uses `tenantQueryKey("job-types", firmId)` with a distinct resource string from `"employees"` — confirmed no key collision by reading both call sites side by side. Backend: **real, load-bearing check this pass** — `crud.list_job_types`/`crud.get_job_type` run bare `SELECT`s with no explicit `firm_id` filter in the Python code at all (`crud.py:316-322`, read fresh), meaning tenant isolation rests *entirely* on Postgres RLS being active and `app.current_tenant` being set correctly for the request — verified this is real, not assumed: migration `9104a25b4614_job_types_table.py` shows `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + a `tenant_isolation` policy scoped to `current_setting('app.current_tenant', ...)`, and a real backend test (`test_authz_regression.py::test_cross_tenant_job_type_patch_is_404`, seeded against a real DB, not mocked) exists and asserts a cross-firm `PATCH` 404s. Also verified: `job_types.name`'s uniqueness is `UNIQUE (firm_id, name)` — composite, per-firm — not a bare `UNIQUE(name)`, which would have been a real cross-tenant leak (Firm A creating "Tax Audit" blocking Firm B from ever using that name) — read directly from the migration SQL, not assumed from the 409 behavior alone.
- `object_level_authz`: Same UUID-from-already-fetched-list pattern as Employees — `job-type-list.tsx` never accepts a user-typed or URL-supplied id, confirmed by reading the file fresh this pass. Backend 404-not-403 on `update_job_type` cross-checked against `Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md` above.
- `input_validation`: `jobTypeCreateSchema` (Zod, min/max length matching backend's `NoNulStr` bound) tested this pass (empty-submit, overlong-name — both negative-control-verified as part of this slice's own test suite, not a gap left for a later mutation-testing pass this time). No `dangerouslySetInnerHTML`/`innerHTML`/`eval(` in `frontend/src/features/job-types` — grepped fresh, zero matches.
- `cors`: N/A, unchanged.
- `secrets`: **N/A by design, verified not by assumption.** Explicitly checked (per skill-verification-discipline.md's 7th failure mode — "what's different about this call site's data" before reusing a pattern) whether Job Types carries anything analogous to Employees' one-time `generated_password`: read `JobTypeOut`/`JobTypeCreate` in `job_types.py` — `{id, name, is_active}` only, no credential field anywhere in this resource. No `with_idempotency`/cache-and-replay mechanism used or needed.
- `supply_chain`: No new dependency added this slice — reuses `@tanstack/react-query`, `react-hook-form`, `zod`, `@radix-ui/react-dialog` already installed and audited.

**C. Self-check gate (mapped to skill-verification-discipline.md's 9 failure modes)**

1. `reapplied_general_principle_to_every_instance`: `tenant-query-key.ts` (extracted specifically so the *next* slice wouldn't rediscover it) was actually reused here, not reinvented — the mechanism this project's own prior audit built for exactly this moment worked as intended.
2. `stress_tested_design_against_its_own_stated_logic`: Stress-tested the "no Idempotency-Key needed, unique constraint makes retries safe" claim against its own edge case — confirmed `create_job_type`'s constraint is DB-atomic (`IntegrityError` catch, not check-then-insert), so a concurrent double-submit genuinely can't double-create, not just assumed safe by analogy to Employees.
3. `ran_fixed_domain_sweep_regardless_of_conversation_focus`: Section B's `tenant_isolation` check went two layers deep (frontend key *and* backend RLS/migration) even though the conversation's immediate trigger was just "build the next slice" — not stopped at the frontend layer alone.
4. `reopened_skills_already_read_this_convo_for_a_new_subtask`: ASVS v8's §8.4.1 text was re-grepped fresh this pass (shown verbatim in D below) rather than reused from the Employees audit's citation of the same line, even though it's the identical requirement.
5. `compound_source_not_partial`: Tenant-isolation finding cites the frontend key scheme, the backend RLS policy (migration SQL), the real cross-tenant test, *and* ASVS 8.4.1 — four independent checks, not one assumed sufficient.
6. `grepped_whole_cheatsheet_dir_not_just_familiar_titles`: 4 keyword greps across the whole directory this pass (listed in A).
7. `new_call_site_of_shared_mechanism_asked_whats_different_about_its_data`: Explicitly asked (Section B `secrets`) whether Job Types' response body has the same one-time-secret property Employees' did before assuming `tenant-query-key.ts`/no-idempotency-key reuse was automatically safe — confirmed it doesn't.
8. `comprehensiveness_claim_backed_by_the_actual_checklist`: This entire audit **is** that engagement — `status: in-progress` was set before any analysis, not after, and this write-up is the evidence, not a retroactive claim.
9. `pre_write_check_run_before_writing_the_code_not_after`: **Partially honored, gap named honestly.** The pre-write OWASP/ASVS check (IDOR/business-logic/multi-tenant cheat sheets + ASVS v8) *was* run before writing this slice's code, in the message immediately preceding the first file write — visible earlier in this conversation. What was **not** caught pre-write: the `setOpen(false)` vs `onOpenChange(false)` close-path inconsistency (found in D below) — that's a code-quality/pattern-consistency bug, not a security-mechanism gap, so it sat outside the security-focused pre-write check's scope by design, not a failure of the check itself. Named plainly rather than folded silently into "the pre-write rule worked."

**D. Verification-of-verification**

- `library_behavior_claims_checked_against_installed_source`: None newly claimed this pass — no new library behavior introduced beyond what Employees' audit already verified (TanStack Query invalidation semantics).
- `fix_verified_by_real_command_output`: `npm run lint` → 0 errors (5 pre-existing warnings, unchanged); `npm run typecheck` → clean; `npm run test` → **34 passed**, 7 test files; `npm run build` → succeeded. Backend: `uv run pytest tests/api/routes/test_job_types.py tests/api/test_authz_regression.py -v` → 5 passed locally (route-level, dependency-overridden, no real DB needed), 13 skipped locally (`needs a real Postgres... CI does` — `test_cross_tenant_job_type_patch_is_404` is one of these 13; not fabricated as "ran and passed" from a local run that didn't actually exercise it — its real-DB pass is evidenced by this same session's own CI watch of PR #48's `backend` job, `uv run pytest -m authz` step, ✓, which covers this exact suite).
- **Real bug found, then honestly downgraded after its own negative control disproved the initial severity claim — the specific thing this instruction asked not to skip.** `create-job-type-dialog.tsx`'s `onSubmit` success path called `setOpen(false)` directly instead of `onOpenChange(false)`, skipping `createJobType.reset()` — initially assessed as the same shape/severity as the mutation-testing pass's `reset-password-dialog.tsx` close-cleanup finding. Wrote a test to prove it (open → fail → Escape-close → reopen → assert stale error gone); ran it against the *unfixed* code as a negative control and **it passed anyway** — the test's Escape-close path routes through Radix's own `onOpenChange` call regardless of what `onSubmit` does, so it never actually exercised the buggy line. Traced further: after a *successful* create, `.error`/`.isError` are already `false`/`null` regardless of `.reset()`, and nothing in the component reads `.data`/`.isSuccess` — so the skipped reset has **no currently observable effect**, unlike the reset-password-dialog case (a real, displayed secret). The misleading test was deleted rather than kept for a false sense of coverage. The code fix was kept anyway (consistency with the codebase's single-close-path invariant, defense against a future edit that reads `.data`), but reported here as what it actually is: a maintainability fix, not a proven behavioral/security fix — not overclaimed to make the audit look more productive than it was.

**E. Bounded claim**

- `standard_and_scope`: ASVS 5 (v8, v14, v2 — chapters actually touched by this slice), L1+L2, scoped to `frontend/src/features/job-types/**` + router/handlers wiring + a re-read (not re-write) of the pre-existing backend `job_types` route/crud/migration, as of base commit `a9eaea6`, plus this pass's own fix — none pushed yet.
- `severity_trend_vs_last_pass`: Lower than the Employees pass, and expected to be — that pass found 2 real security gaps specifically *because* it was the first slice to introduce TanStack-Query cache state and CI-secret handling at all; this slice reuses both already-fixed mechanisms rather than reintroducing the category. The one thing found here (the close-path inconsistency) turned out, after honest verification, to be a non-security maintainability nit — a legitimate, lower-severity outcome for a second slice built on an already-hardened foundation, not evidence of a weaker audit.

**F. Independent pass**

- `security_review_run`: Not run as a separate agent pass this time — the `code-review` skill's 8-finder-agent sweep was the mechanism that surfaced 3 of the Employees audit's fixes; for this smaller, more mechanical slice (fewer new files, no new cross-cutting mechanism), the negative-control test on the one candidate finding served the same adversarial-verification role directly. Named honestly as a scope-narrower, not silently skipped: a future slice introducing a new cross-cutting mechanism (the way Tasks will, with its review/billing workflow states) should get the full independent pass again, not assume this slice's lighter treatment is now the standard.

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
