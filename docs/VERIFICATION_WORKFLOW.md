# Verification workflow — process finalized 2026-09-27 (§10), enforcement hooks NOT YET BUILT

Agreed in discussion on 2026-09-20 after the independent review of Observability Phase 1. **Nothing
below is implemented.** Where a sentence says "the script" or "the hook" it describes a design, not
something that exists. Sits next to `skill-verification-discipline.md` (the failure modes) and
`WORKING_PREFERENCES.md` §5 (the known limit of the audit-checklist mechanism); it does not replace either.

## 1. Why this exists

On 2026-09-19 four read-only reviewers, run one at a time, found real defects in Observability Phase 1 code
that was written while consulting ASVS 5, TCASVS and the cheat sheets. Four were reproduced by the author:

1. the redactor stopped at a blank line inside a DETAIL/CONTEXT value, so the rest of the value leaked;
2. ExceptionGroup tracebacks (`    | ` line prefix) bypassed it;
3. its regex was quadratic on hostile input (16 KB took 17.7 s) and ran before the size clip;
4. the frontend breadcrumb regex missed attribute values containing `"`.

The skills were read. The defects still shipped because:

- **Nothing made the search fire.** `skill-verification-discipline.md` failure mode 6 says to grep the whole
  cheat-sheet directory by the mechanism's keywords, and `Input_Validation_Cheat_Sheet.md:75` warns about
  ReDoS. The work was framed as "logging and Sentry", so a regex never registered as a mechanism to search.
- **"Verified" meant the author believed it.** The tests were written by the same pass and covered the shapes it
  imagined. The 66 negative controls prove the tests notice a code change; they say nothing about inputs no
  test contains. Only the canary had an independent test author (failure mode 10.2).
- **The design left unknown shapes to leak.** A pattern list that deletes known-bad shapes loses to any shape
  not on the list. Keeping only safe fields removes that class.

## 2. The workflow

0. **Does it apply?** Decided by the mechanical trigger in §3, not by the author's sense of "substantial".
1. **Start scan.** Scan the task text and the files about to change for mechanism keywords (regex, SQL, secrets,
   subprocess, parsers, caches, logging…). For each hit, grep the skill directories by that mechanism and print the
   matching lines.
2. **Build the checklist** (§4, §5): requirement, source, applies or N/A with a reason, evidence.
3. **Blind test or not?** Decided at this moment, not in advance. Recommended by rule for code that guards a data
   boundary (scrubbers, authorization, parsers, secret handling); optional otherwise; the owner approves. If yes,
   an independent author receives only the checklist, the relevant `owasp-wstg` chapter and the function's
   signature — not the implementation — and writes the tests first, told to break the thing, not confirm it.
4. **Write the code** carrying the same checklist and the same attack intent, blind test or not.
5. **End scan on the actual diff.** Anything new (a regex that only appeared while writing) becomes a checklist line.
6. **Evidence check.** A line is ticked only with evidence: a test name, a command's output, or a rule that ran.
   "I believe it is done" is not evidence, and an unevidenced line stays open. Boundary code needs at least one
   hostile-input test (unique marker string, bounded time).
7. **Run everything** (blind tests, the suite, negative controls). The report says which inputs were tested, not
   "verified".

## 3. Trigger rule (mechanical)

Applies when the change touches a boundary path (below), or adds a dependency, or the diff contains a
risky-mechanism token. Skipped for layout-only, copy and small fixes with no such token, like the earlier Tauri
UI slices. The path list was agreed on 2026-09-20 from the repo's real layout and grows whenever a bug is found
outside it.

| Area | Boundary paths |
|---|---|
| Backend code | `backend/app/api/` (routes, `deps.py`), `backend/app/crud.py`, `backend/app/models.py`, `backend/app/core/`, `backend/app/alembic/`, `backend/ops/`, `backend/loadtest/` |
| Backend runtime and supply chain | `backend/certs/`, `backend/Dockerfile`, `backend/alembic.ini`, `backend/pyproject.toml`, `backend/uv.lock` |
| Frontend | `frontend/src/lib/`, `frontend/src/stores/`, `frontend/src/config/`, `frontend/src/app/router.tsx`, `frontend/src/features/auth/`, `frontend/src/features/*/api/`, `frontend/package.json` and its lockfile |
| Desktop | `frontend/src-tauri/` (`tauri.conf.json`, `tauri.e2e.conf.json`, `capabilities/`, `src/`, `Cargo.toml`, `build.rs`) |
| CI and local stack | `.github/workflows/`, `supabase/config.toml` |
| Security tooling and policy | `.gitleaks.toml`, `.semgrep/`, `.trivyignore`, `SECURITY.md` |

Not on the list: `features/*/components`, styling, `docs/`, tests — these trigger only if the token scan finds
something. Config-only files in the last row get a lighter check ("was a rule or exclusion weakened?") and not
the full workflow.

## 4. Keeping the skill hits relevant

- A map from mechanism to *specific* sections, limited to our stack (FastAPI, Postgres/RLS, Supabase, Tauri,
  React). Skills for other stacks are never searched.
- Only requirement-strength hits (MUST/required) become checklist lines; "consider" hits are notes.
- Each hit is marked applies or `N/A: <reason>`. The reason is visible to the owner. A recurring N/A becomes a
  suppression in the map with a review date, so it stops recurring without being silently hidden.
- Keep the list short. A long checklist gets ticked without being checked.

## 5. Where the checklist lives

Working copy in the session scratchpad; the final ticked version, with evidence, goes into the slice's entry in
`SECURITY_AUDIT_CHECKLIST.md`, replacing loose "verified" sentences. See open decision 8 for how this interacts
with the existing Stop hook.

## 6. What has to be built, in order

1. Mechanism map and checklist template (documents only).
2. Attack-input library and one shared test helper, seeded from the four bugs in §1. Every bug found later adds an
   entry, the way `.semgrep/custom-rules.yml` grew from an earlier bug.
3. The diff-scan script (start and end modes).
4. Hook wiring.
5. Blind-test brief template.
6. End-of-work evidence check, by extending `~/.claude/hooks/audit-checklist-guard.js`.
7. Pilot on batch 1 of the review fixes, then tune.

## 7. Limits, stated plainly

- Detection is keyword-based. A new kind of mistake with no keyword in the map is not caught; the first time a new
  kind of boundary appears it still needs one independent test author.
- A filled evidence field is not a true one. The existing hook only checks non-blank (`WORKING_PREFERENCES.md`
  §5, whose decision to skip transcript cross-checks and LLM-judge steps stands). The blind test and owner
  spot-checks are the real backstops.
- Estimate, not measured: applied to the four bugs in §1, the scan alone would have caught the ReDoS; the other
  three needed an attacker or an attack list that did not exist until that day.
- Too many triggers cause checklist fatigue; the trigger rule and the relevance filter exist to prevent that.
- Cost: the scan is free; tokens go to reading hits and to blind tests, which are only run when decided.

## 8. Open decisions for the diff-scan script

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Form | Node script (same runtime as the existing hooks) · Python script (repo tooling) · Semgrep rules | A small script, because Semgrep can flag code but cannot search the skill directories. Semgrep stays for enforceable rules that come from the library. |
| 2 | Detection | Token regex on added lines · AST | Regex on added lines, comment lines ignored. False hits are acceptable because every hit passes the applies/N-A filter. The scanner's own regexes must be linear. |
| 3 | When it runs | Start: on prompt submit. End: Stop hook. Later: pre-commit/CI | Start plus end. Whether the prompt-submit hook receives the prompt text is **not yet verified** and must be checked against the current Claude Code hooks docs before building. |
| 4 | Blocking or advisory | Block the turn end · warn only | Advisory for the pilot; blocking afterwards, only when the trigger matched and a line lacks evidence, with bounded retries like the existing Stop hook. |
| 5 | Output | File names only · exact matching lines | Exact `file:line` plus the sentence, top few per mechanism. |
| 6 | Where the map lives | In the repo · in `~/.claude` | In the repo: versioned, reviewable, project-specific. The script's location follows it; the hook calls it. |
| 7 | Trigger paths | See §3 | Owner confirms the list. |
| 8 | Checklist location | Scratchpad then audit entry (chosen) · in the "Current Audit" block | The existing Stop hook only enforces the `Current Audit` block while it is `in-progress`. Decide whether the working checklist should live there so the hook already covers it. |

## 9. Scope and rollout (added 2026-09-20; sections 1–8 above are unchanged)

**Owner's position (clarified 2026-09-20):** this workflow is for building **future new features** — it adds
rigor to how new work is built. It is not a retrofit: existing code is not re-audited under it, and the workflow
above stays as agreed. **For now**, the suggested order below is followed for the review-fix batches 1–3 of
Observability Phase 1, with batch 1 as the pilot; what batch 1's findings show decides what is built next.

**Assistant's view, recorded as a view and not as a decision:**

- The parts most likely to help are the attack-style tests written by someone who has not seen the code (for
  boundary code), one evidence line per requirement, and re-running the scan on the finished diff. The script and
  hooks are the largest build and the least proven; the existing hooks only check that a field is non-blank.
- Suggested build order: (1) the checklist rows and the `trigger`, `blind_test` and `hostile_inputs_tested`
  fields in the audit-checklist template; (2) fix batch 1 as the pilot, with the attack-input helper and a blind
  test author, and see whether the process helps or only weighs; (3) decide on the scan script from what the
  pilot showed, not from guesses.
- Proportionality: there is no deployment yet and the pilot is small. Apply the workflow to boundary code; do not
  slow ordinary work with it.
- The limit in §7 stays: this lowers the odds of a repeat, it does not promise a new kind of mistake cannot ship.

**Audit-checklist template changes proposed in discussion**: `trigger`, `blind_test`, and
`hostile_inputs_tested` fields **were added** to the Current Audit template (found already present,
2026-09-27, while writing §10 — this line had gone stale without being updated, itself an instance of the
exact doc-vs-code drift Phase 8's "claims checker" pass exists to catch). `independent_review` was added
2026-09-27 alongside them, for §10 Phase 8. Not yet done: replacing the prose in sections A–C with one row
per requirement (requirement, skill `file:line`, applies or `N/A: reason`, evidence, status); writing
"tested against these inputs" instead of "verified" throughout F and the summary.

## 10. Finalized workflow, agreed 2026-09-27 — supersedes §2 for all future work

Sections 1–9 above are kept as the historical record of how this workflow was designed and piloted
(Observability Phase 1, Batch 1). This section is the actual, current version to follow going
forward. **Still true from the header above: the enforcement hooks described at the end of this
section are NOT built yet** — only the process itself is finalized.

**Phase 0 — Does this need the full treatment?**
Decided against the real boundary-path list in §3 above, not by feel. Small/contained changes get a
lighter version of Phases 1 and 8; only genuinely new or high-risk mechanisms get the full weight —
this is a deliberate dial, not skipped rigor (running the full pipeline on every one-line change
causes checklist fatigue and gets rubber-stamped instead of actually checked).

**Phase 1 — Independent scoping, before I touch anything.**
A fresh agent, given only the task and the files it touches (not my plan), builds the first-draft
checklist and keyword list. It must apply three specific checks from
`skill-verification-discipline.md` and show its work, not just assert it:
- grepped the *whole* relevant skill directory by real keywords, not just familiar filenames
  (failure mode 6);
- for any reused/shared mechanism, explicitly asked what's different about this new call site's data
  (failure mode 7);
- did not claim "comprehensive" without showing the actual grep output as proof (failure mode 8).

**Phase 2 — Search the real skills using that checklist.**
Beyond `owasp-cheatsheets` + `owasp-asvs-5` (always both, never just one): also search
`owasp-tcasvs` (thick-client/desktop) and the multi-tenant architecture skills
(`saas-multitenant-architecture`, `postgres-multitenant`) whenever the change touches the Tauri
client or firm/tenant isolation. Plus whichever framework skill applies (FastAPI, Postgres,
Supabase, React).

**Phase 3 — Build one real checklist.** One line per requirement: what it is → source → applies or
`N/A: reason` → what would count as proof. Kept short on purpose.

**Phase 4 — Write the test before the code, using `owasp-wstg` for real attack technique.**
The decision of whether this needs a genuinely blind test author is **never made unilaterally, even
in auto mode — always reasoned through with the user first.** If a blind author is used, the test's
actual content must stay structurally hidden from the pass that writes the code — if I can see the
test before writing the code, the entire point is defeated, so this can't be "I'll just not peek,"
it has to be kept out of my context until after the code is submitted.

**Phase 5 — Write the code with a hacking mindset.**
Not "write code, then test until it passes." The whole time, the goal is to actively try to break
what's being built — aiming to make it fail, not confirming it succeeds.

**Phase 6 — Re-scan the actual diff.** Anything new that showed up while writing (an unplanned
regex, an unplanned dependency) becomes a new checklist line, not a silent addition.

**Phase 7 — Fill the checklist with real evidence.** A line is ticked only with a test name or real
command output — never "I believe it's done." **Once filled in, the whole checklist is shown to the
user, and we verify it together, item by item — implemented, not just ticked on paper.**

**Phase 8 — Independent review.** For fixing/reviewing existing code: 3 fresh, separate passes
(attacker on code only → test critic on code+tests → claims checker on docs vs. code), every finding
reproduced for real before trusted. For a genuinely new, high-stakes mechanism: full blind-authored
tests instead, scoped to one file at a time. **If Phase 4 decided no blind test was needed, this
phase becomes mandatory — at least one of the two outside checks always runs, never neither.** Same
as Phase 4's decision: never picked unilaterally, always reasoned through with the user first —
combine both asks into one conversation right after Phase 1's checklist comes back, not two separate
interruptions. Any agent run for this (blind-test author or review passes) runs wrapped in the
memory-guard tooling (`gpt.sh`/`memguard.py`) — this is what was missing the one time a full
blind-authored pass crashed the laptop (2026-09-20).

**Phase 9 — One last fresh read for concurrency/security/money code.** Re-read the finished thing
once, cold, asking "what's the other path nobody tested?" — a test written by the same pass that
wrote the code shares its blind spots.

**Phase 10 — Report honestly.** State plainly what was proven by a real run vs. reasoned through.
"Tests pass" alone never stands in for that distinction.

**Phase 11 — Ship it.** Branch → commit with real evidence → push → PR → wait for every check to
actually finish → merge → independently re-check `main` itself is green after, not just the branch.

**Phase 12 — If a bug turns up, sweep for its twin.** Grep the whole codebase for the same mistake
shape before closing it out — not just the one reported spot.

**Also carried forward from §2-9 above, still true:** the fixed-domain sweep (auth, sessions,
tenant isolation, object-level authorization, input validation, CORS, secrets, supply chain) still
runs as my own cheap backstop even after Phase 1's independent pass — costs nothing extra, and
catches it if the independent agent itself has a blind spot. Phase 0's boundary-path list stays the
literal one in §3, not a fresh judgment call each time.

**What would actually fix the "nothing forces this to fire" limit (§7 above), not yet built:**
1. A `PreToolUse` gate on Edit/Write, scoped to §3's boundary paths, blocking the first edit until
   Phases 1/2/4's answers are stated — the same mechanism `~/.claude/hooks` already uses elsewhere
   in this setup for "state facts before editing," just scoped to this workflow's specific questions.
2. Extending the existing `audit-checklist-guard.js` Stop hook so it also requires Phase 8's review
   result filled in (which pass ran, or a stated reason none did) before a boundary-touching task can
   be marked closed.
3. **Honest ceiling that stays even if both are built**: a hook can force something to be *written*
   in the field. It cannot verify that what's written is *true*. That layer still depends on the
   user's own spot-checks (Phase 7's joint verification above) — building the hooks closes the "did
   you even try" gap, not the "was your answer honest" gap.
