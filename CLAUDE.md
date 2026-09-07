# CLAUDE.md — CA Firm Practice Management Tool

This file is project-specific instructions, loaded automatically in every session working in this repo. It
exists so the discipline this project was planned under doesn't have to be re-derived, re-explained, or
re-broken by a future session (mine or otherwise) that doesn't have this conversation's history.

## 1. What this project is

A job-allocation system for a Chartered Accountancy (CA) firm, built as an installed desktop application.
Phase 1: single pilot firm, ~10 users, two roles (Owner/Employee). A second pilot firm is imminent — schema
and architecture are deliberately tenant-ready from day one (shared schema + `firm_id` + Postgres RLS) so
onboarding firm 2, 3, 4 needs zero rebuild, even though only one firm is live today.

**Stack**: FastAPI (Python) backend + Supabase (Postgres + Auth) + React/TypeScript frontend inside a Tauri
desktop shell. Hosted on Railway, fronted by Cloudflare. Observability: Railway's own log capture + Sentry
(errors) + UptimeRobot (uptime), all free-tier.

**Status as of this file's writing**: planning phase complete (all six planning docs + a comprehensive
security audit pass), coding not yet started. **No code exists in this repo yet — do not assume any of the
above is implemented; it's all still design.**

## 2. Documentation map — read in this order

1. `docs/PRD.md` — product requirements, source of truth for scope.
2. `docs/ARCHITECTURE.md` — system design, auth flow, multi-tenancy strategy, the consolidated threat model (§14).
3. `docs/DATA_MODEL.md` — schema, conventions, table-by-table design.
4. `docs/API_SPEC.md` — endpoint-by-endpoint spec, idempotency, cross-cutting security requirements.
5. `docs/FRONTEND_ARCHITECTURE.md` — screen inventory, project structure, state management, testing.
6. `docs/DEPLOYMENT.md` — hosting, CI/CD, TLS chain, observability, cost.
7. `docs/CODING_STRUCTURE.md` — **read this before writing any code.** Repo layout, build order (vertical
   slices, not horizontal layers), per-slice checklist.

Every one of these is cross-referenced against the others — a change to one that affects another must update
both, not just the one being edited. §3 below explains why this matters more than it sounds like it should.

## 3. Standing rules — given explicitly by the user, non-negotiable

These are also in the global `~/.claude/CLAUDE.md`, restated here because this project is where they were
learned the hard way and because a project-specific reminder is worth the redundancy.

- **Search the relevant project skill (`~/.claude/skills/`) before stating any technical claim it could
  cover — every time, as a mechanical first step, never a judgment call about whether the claim "feels
  important enough" to check.** Applying a skill's general pattern to this project's specific situation is
  the correct use of a skill; guessing or asserting from memory when a skill directly covers the topic is not.
- **A fixed checklist of domains (auth, session lifecycle, tenant isolation, object-level authz, input
  validation, CORS, secrets, supply chain) is a floor, not a substitute for actually searching.** Run it
  deliberately against any major doc or code revision, regardless of whether the conversation happened to
  raise that topic — reactive checking alone misses whatever never occurred to anyone to ask about.
- **`owasp-cheatsheets` and `owasp-asvs-5` get searched for the actual thing being built, every time,
  alongside whatever language/framework skill also applies (`fastapi`, `react-official`,
  `bulletproof-react`, `postgres-multitenant`, `supabase`, `tauri-official`) — not matched against a
  pre-set topic list.** This applies to writing code, not only planning documents — the same rigor, not a
  relaxed version once real code starts shipping.
- **Ponytail (lazy/minimal-code discipline) is active, full mode**, for the coding phase specifically —
  shortest correct diff, stdlib/native before a dependency, no speculative abstraction. It does **not**
  extend to skipping security checks, input validation, or the tests required by `CODING_STRUCTURE.md` §5 —
  lazy on structure, never lazy on correctness.
- **Don't guess at platform-specific facts** (Railway, Cloudflare, GitHub, Supabase pricing/limits/behavior)
  that aren't in a project skill — verify live (WebFetch/WebSearch) and say plainly that it's live-researched,
  not skill-cited, so the reader knows which claims are pinned to a source and which aren't.

## 4. Mistakes actually made during this project's planning phase — read before repeating them

This is not a confession for its own sake — every item below is something that actually happened, was
caught (usually by the user asking a direct question), and cost real rework. Recorded here so the next
session doesn't rediscover the same failure mode from scratch.

1. **Cited OWASP ASVS chapter names from memory instead of checking the actual files** — used ASVS 4.0 names
   ("Access Control," "Session Management") when v5 had renamed them (`v8-authorization`,
   `v9-self-contained-tokens`). Caught by the user asking "is this verified," not self-caught.
2. **Declared an entire document "not skill-verified" without checking whether it actually was.**
   `DEPLOYMENT.md` was written off as outside any skill's coverage; `owasp-cheatsheets` in fact had four
   directly relevant cheat sheets (CI/CD, Secrets Management, Docker, Supply Chain) that were never searched
   for until asked.
3. **Treated a narrow, failed keyword search as proof a topic wasn't covered.** Searched
   `owasp-cheatsheets` for the literal phrase "temporary password," found nothing, and concluded the topic
   wasn't covered — instead of escalating to ASVS's dedicated authentication chapter, which had the exact
   requirement (6.4.1) under different wording.
4. **Carried over "already checked" from a stale version of a design.** After the account-provisioning
   mechanism changed (email invite → admin-issued password), the new mechanism's genuinely new security
   surface (temporary-password handling) wasn't re-verified — it inherited a "this was already checked"
   feeling from before the redesign.
5. **Added a citation/architectural claim without checking the relevant skill first, after being told to** —
   required the user to explicitly reject the edit and ask again before the actual lookup happened.
6. **Proposed and half-implemented my own design idea instead of properly evaluating the user's already-
   stated alternative first** — the user's own proposed provisioning mechanism turned out to be strictly
   better (solved two problems at once) and had to be substituted in after the fact, rather than being
   evaluated on its merits from the start.
7. **Ran one lossy, summarized tool result (a WebFetch pass on Tauri's CSP docs) that itself said "no
   information found" on two named config fields, and wrote a skill file anyway instead of fetching a more
   targeted source.** The skill was later found to have the wrong JSON path for the CSP config entirely
   (`app.security.csp`, not a flat `csp` key) plus two missing sibling fields
   (`dangerousDisableAssetCspModification`, `freezePrototype`). A tool's own "I couldn't find this" is
   weaker evidence than a clean miss, not stronger — treat it as a trigger to dig further, not a stopping point.
8. **The big one — a full-document security audit (prompted directly by the user after repeated smaller
   misses) found 19 real issues across five documents in one pass, including two that directly undermined
   the project's core multi-tenancy guarantee:**
   - Every foreign key from any table to `profiles` (nine columns across six tables) was a plain FK, not the
     composite `(firm_id, x) → profiles(firm_id, id)` pattern this project's own stated convention required
     everywhere else — meaning nothing in the database stopped a task in Firm A being assigned to an employee
     in Firm B.
   - The `firms` table itself had **no RLS policy at all** — correctly excluded from the standard per-tenant
     pattern (it has no `firm_id` column) but that exclusion was never replaced with an equivalent
     self-referential policy, so any query against it returned every firm's data.
   - Deactivating an employee didn't actually revoke their access — their JWT stayed valid, and nothing
     re-checked `is_active` against live data anywhere in the request path.
   - CORS was never mentioned in any of five separate documents — not a shallow check, a total blind spot.
   These weren't found by checking a skill more carefully on a known question — they were found by running a
   **fixed domain sweep** instead of only answering questions as they came up in conversation. That's the
   actual lesson, not "check more thoroughly" in the abstract.
9. **Asserted a clean narrative ("this project targets ASVS Level 1 baseline with select Level 2 items")
   that wasn't actually a real, deliberate decision** — when asked how that decision was made, the honest
   answer was that it never was one; individual requirements had been evaluated case by case against cost
   and scale, with at least one genuine Level 1 item knowingly left unmet (the breached-password check) and
   several Level 2 items adopted anyway. Retroactively imposing a tidy story on a messier real history is its
   own kind of unverified claim.
10. **A real contradiction between three documents went undetected until the full audit**:
    `FRONTEND_ARCHITECTURE.md` said to leave session-token storage on the Supabase SDK's own default, while
    `ARCHITECTURE.md` and the `tauri-official` skill had both already committed to Tauri's secure
    store/stronghold plugin. Each document was individually "checked" against a skill at some point; nobody
    checked the three against each other.

## 5. Process rules adopted because of the above — apply these without being re-told

- **Reactive lookup ("check the skill when a claim comes up") is necessary but not sufficient.** It only
  fires once a claim is already being made — it does nothing to guarantee the right question ever gets asked
  in the first place. Run the fixed-domain sweep (§3) on any major doc or code revision as a deliberate step,
  not just as claims get made in passing.
- **A tool result that itself flags missing information is a signal to dig further, not a stopping point.**
  Applies to WebFetch/WebSearch summaries exactly as it applies to a narrow grep miss — both are weaker
  evidence of "not covered" than they look.
- **Stress-test a stated design principle against its own edge cases.** If a document claims "X always
  holds," check the parts that felt like exceptions too — that's exactly where the `firms`-table RLS gap
  hid.
- **Re-audit a stated convention against every place it was applied, not just where it was first written.**
  Checking a skill once for the general rule (composite FKs) isn't the same as verifying every column that
  should follow it.
- **Cross-check documents against each other, not only against skills.** A claim can be individually
  well-cited and still contradict a decision already made two documents earlier — the token-storage
  contradiction was caught this way, not by a skill lookup.
- **Don't retroactively narrate a cleaner decision history than actually happened.** If a pattern of calls
  was case-by-case rather than a deliberate policy, say that plainly rather than inventing a tidier
  after-the-fact justification.

## 6. Before writing any code

Read `docs/CODING_STRUCTURE.md` in full. It has the repo layout, the phase-by-phase build order (cross-
cutting scaffolding once, then one full vertical slice per resource — never horizontal layers across
everything at once), and the per-slice checklist that folds §3/§5 above directly into the coding workflow.

## 7. Security audit discipline — checklist + hook mechanism

Every phase's security audit (Phase 1 onward) runs through a single evidence-based mechanism, not ad hoc
review. **Before claiming a phase's security audit is done, read and follow
`docs/SECURITY_AUDIT_CHECKLIST.md` in full** — it defines the required sections (scope, what was checked,
findings, fixes, what's documented-not-fixed and why) and states plainly that "a line that just says 'done'
or 'yes' isn't evidence and doesn't count."

- A global `Stop` hook (`~/.claude/hooks/audit-checklist-guard.js`) enforces the checklist's `Current Audit`
  block is non-blank before a turn can end while an audit is `status: in-progress`. It only catches an
  interrupted or premature stop — it cannot and does not judge whether a filled-in field is actually true.
  Treat a filled field as "investigation happened," not "conclusion verified" (the checklist file says this
  about itself; it's not this file editorializing).
- Set `status: in-progress` with real `phase`/`scope_files`/`date`/`commit` *before* starting analysis, not
  after — genuinely engage the in-progress state, don't write directly to Completed Audits. (A hook-complete
  audit can still be shallow; the hook is a safety net against stopping early, not a substitute for the work.)
- Apply `docs/skill-verification-discipline.md`'s failure modes 6, 8, and 9 on every audit: grep the whole
  `owasp-cheatsheets`/`owasp-asvs-5` directories by the mechanism's real keywords, not just the files whose
  titles sound relevant; actually produce evidence (real command output, real grep hits, real test results)
  rather than narrating about having checked something; and for any function that reads a row unlocked then
  later re-locks the same primary key in the same ORM session, require a real two-thread test against a real
  instance of the production database engine, not a read of the source, before treating the lock as verified.
- `docs/SECURITY_AUDIT_CHECKLIST.md`'s own Section F (`/code-review ultra`, a separate multi-agent cloud
  review) is a periodic independent check on this same discipline, not a replacement for it — run it every
  few phases, not every phase.
