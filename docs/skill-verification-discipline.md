# Skill verification discipline

**Mandatory rule** — check available project skills (`~/.claude/skills/`) first, always, before stating a
technical claim they cover; never guess or decide from memory when a skill exists that covers the topic.

This file is a repo-local copy of a rule originally recorded only in per-session assistant memory (scoped to
a different project folder than this repo) — copied here so it travels with the repo regardless of which
folder a Claude Code session happens to be rooted in. `CLAUDE.md` §7 references this file by name.

Two categories, kept strictly separate:

1. **Applying a skill's pattern to this project's specific situation is the legitimate use of the skill** —
   deciding billing sub-tasks share the `tasks` table, picking which of two valid RLS options to use,
   choosing React over Svelte for this app's screen shape. This is synthesis a skill can't do on its own;
   it's fine, and it's the actual point of having the skill.
2. **Guessing, omitting, or deciding from memory instead of checking a skill that actually covers the topic
   is not fine — a wrong workflow, not a minor slip** — especially during the foundational planning phase of
   a codebase, since a wrong foundation propagates into everything built on top of it.

**Why this rule exists:** it was learned the hard way, twice, in this project's own planning-doc phase.
First, `ARCHITECTURE.md`'s security mapping cited OWASP ASVS chapter names from general recall ("Access
Control," "Session Management") instead of checking `owasp-asvs-5`'s actual v5 chapter files — those are
ASVS *4.0* names; v5 renamed them (`v8-authorization`, `v9-self-contained-tokens`). Second, `DEPLOYMENT.md`
opened by claiming "nothing here is skill-verified" for the whole document, without ever checking whether
`owasp-cheatsheets` had CI/CD-relevant content — it did (`CI_CD_Security_Cheat_Sheet.md`,
`Secrets_Management_Cheat_Sheet.md`, `Docker_Security_Cheat_Sheet.md`,
`Software_Supply_Chain_Security_Cheat_Sheet.md`), missed entirely. Both were caught by the user asking "is
this verified," not by any self-initiated check.

**How to apply:** before writing any section that touches a skill-covered domain, search the relevant skill
directories first (Glob/Grep for the actual topic) — as a mechanical first step, not a judgment call made
per-claim based on how central the claim feels. Only fall back to general knowledge/memory for what's
genuinely absent from every relevant skill after actually checking, and flag that explicitly in the same
sentence, every time — never silently. (A parallel discipline applies to vetting external/third-party tools
rather than citing internal skills — a separate standard, not reproduced here.)

**Also codified globally**: this rule is written into `~/.claude/CLAUDE.md`, so it applies to every session
in every project folder on the machine it's installed on, not only sessions rooted in this repo. That global
copy is the short, always-loaded enforcement text; this file is the detailed record — the real incidents and
the reasoning behind each failure mode below.

## Failure mode 1 — a rule checked once for its general principle, never re-applied against later output

`DATA_MODEL.md` §1 correctly cited the skill's composite-FK convention; §2's actual table definitions were
never individually checked against the rule stated two paragraphs above. Checking the skill isn't the same
as auditing every downstream instance of the pattern it established.

## Failure mode 2 — a design not stress-tested against its own stated logic

The `firms` table was correctly reasoned as exempt from the standard tenant RLS policy (no `firm_id`
column) — and the follow-up question ("so what *does* protect it?") never got asked, even though the same
document's own opening line already stated the principle that would have caught it. No skill lookup fixes
this; it requires reading your own output adversarially.

## Failure mode 3 — the rule only fires once a claim is about to be stated

CORS was never mentioned across five separate planning documents, not because it was checked shallowly, but
because it never arose as a candidate question. If a whole category of concern never crosses your mind while
writing, "check the skill before claiming" never activates, because no claim was ever made to check.

**The actual fix, proven by a 19-finding full-document audit that surfaced failure modes 1-3 together**:
coverage driven by whatever a conversation happens to narrate forward (batch by batch, question by question)
reliably misses things that never came up. What worked was stopping that narrative mode and running a
**fixed checklist of domains** (auth, session/token lifecycle, tenant isolation, object-level authorization,
input validation, CORS, secrets handling, supply chain) against every document regardless of whether the
conversation had touched that domain yet. A major revision to any architecture/data-model/API/security-
relevant document should get this same fixed-domain sweep applied deliberately, not just a reactive skill
lookup on whatever claim is being written at that moment.

## Failure mode 4 — a skill already read in this same conversation still wasn't re-checked

`fastapi/project-structure.md` was read in full while scoping `Settings(BaseSettings)`. Its own text already
named the exact fix for a `DATABASE_URL` scheme mismatch (`@field_validator` rewriting `postgres://` to
`postgresql+psycopg://`). Turns later, writing a validator for precisely that scenario, it was built from
general Pydantic knowledge instead of re-opening the already-read file. The miss was treating "read once, for
a different sub-task" as equivalent to "checked for this one." Applying the skill's pattern with a stated,
deliberate reason for the project's situation is good process (diverging from the skill's exact approach,
with a real stated reason, is fine); *not checking before writing is not* — it can ship wrong code by default
rather than by an actual decision.

## Failure mode 5 — partial compliance treated as full compliance (four ways in one session)

During CI/CD hardening work: (1) explained GitHub branch protection by grepping a project doc's own
paraphrase of a cheat sheet, not the raw skill file — a doc summarizing a skill is not the same source as the
skill, even when accurate; (2) audited the CI pipeline against `owasp-cheatsheets` only, silently skipping
`owasp-asvs-5` — the rule names both together as one compound requirement; checking one and stopping is not
partial credit, it's an unchecked half reported as checked; (3) asserted a tool's runtime behavior from
general belief without checking its own docs, in the same batch as correctly doing that exact kind of check
for a different tool; (4) all four were only caught because the user asked directly each time — none were
self-caught. **How to apply:** when a rule names multiple sources together, check off each one by name before
answering. When citing "the skill," open the skill file itself for that exact claim, not a project doc that
once summarized it. When one claim in a batch gets a real check, every other claim in that batch needs the
same treatment.

## Failure mode 6 — checking *some* files in a directory treated as having checked the directory

While building a workflow-state-checked write (`submit_task`/`mark_task_billed`), `Error_Handling_Cheat_
Sheet.md`, `JSON_Web_Token_Cheat_Sheet.md`, `Multi_Tenant_Security_Cheat_Sheet.md`, and `Authorization_Cheat_
Sheet.md` were checked — a reasonable-looking set — but never `Business_Logic_Security_Cheat_Sheet.md`,
which directly names both the idempotency pattern that *was* built correctly and, in the very next section
("Use Database Transactions and Locks"), the exact bug shipped: a plain read-then-write status check is a
textbook TOCTOU race between two concurrent requests that don't share an Idempotency-Key. A real defect in
shipped, CI-green, merged code — caught only because the user asked "is the rules followed?" a second time on
the same slice, forcing an actual fresh grep instead of relying on which files had already been decided as
"the relevant ones." **How to apply:** "search the cheat sheets" means grep the whole `owasp-cheatsheets`
directory for the mechanism's actual keywords (here: `idempoten`, but also the underlying concept — race
condition / concurrent / TOCTOU / transaction), not open the 3-4 files whose names sound most relevant from
memory and stop there. A cheat sheet's title is not a reliable index of what it covers.

## Failure mode 7 — a shared, already-vetted mechanism reused on a new call site without re-checking that site's own data

Retrofitted an already-vetted cache-and-replay idempotency helper (checked against OWASP for ordinary-JSON
task endpoints) onto a password-reset endpoint without re-asking the question. Shipped, reported done, CI
green. It was a real, live security regression: the helper persists the response body for 24h to support
retries — fine for a task's JSON, wrong for this endpoint, whose response body is a one-time plaintext
credential the project's own spec already documented as "never retrievable again." The retrofit silently made
it retrievable again for 24h. Caught only on a third unprompted "did you follow the rules" question, by
re-reading the project's own already-written spec line next to the new code — not by any skill lookup. **The
mechanism-level check ("is this helper OWASP-sound") is not the same question as the call-site check ("does
*this* response body have a property — a secret, a one-time value — that makes reusing the mechanism wrong
even though the mechanism itself is sound").** **How to apply:** before wiring an existing shared security
mechanism onto a new call site, ask what's different about that site's actual data — does it contain a
secret, a one-time token, PII, anything with its own "must not persist / must not be re-shown" rule — before
assuming the mechanism's prior vetting still covers it.

## Failure mode 8 — a comprehensiveness claim made without ever engaging the mechanism built to back it

After repeated "is the audit comprehensive?" questions each surfacing one more real finding, this project
built `docs/SECURITY_AUDIT_CHECKLIST.md` (evidence fields, not checkboxes) plus a `Stop` hook
(`~/.claude/hooks/audit-checklist-guard.js`) blocking turn-end while the checklist's `status: in-progress`
and any evidence field is still empty. Reviewing the finished hook surfaced its own honest limit: **nothing
forces `status: in-progress` to ever get set in the first place** — the hook only enforces evidence once an
audit is already active; it cannot stop a "this is comprehensive" claim made while never touching the
checklist at all. Same shape as failure mode 5 one level up: treating "I looked at the relevant files" as
equivalent to "I ran the process built specifically to check that." **How to apply:** the trigger is language
of the form "comprehensive" / "covers everything" / "no more gaps" / "is complete" about a phase or slice, in
a project where `docs/SECURITY_AUDIT_CHECKLIST.md` exists. Before finishing a response containing that claim,
check whether the checklist's Current Audit was ever set to `in-progress` for this phase and its evidence
fields genuinely filled — by actually opening the file, not from memory of having "done a thorough pass" in
conversation. If it wasn't engaged, that omission *is* the finding.

**Honestly, this one is weaker than the other seven, on purpose:** unlike the Stop hook, which mechanically
cannot be skipped once an audit is active, this rule depends on the same self-recall discipline that failed
seven separate times elsewhere in this file before being caught — by the user asking, not by self-catching.
Deliberately left un-hook-enforced (the false-positive/false-negative cost of scanning free-form claim
language across every future project was judged worse than the gap it would close). If this one fails too,
it gets caught the same way every prior one did: the user asking directly whether the checklist was actually
touched.

## Failure mode 9 — a lock verified as present in the code was never verified as effective at runtime

`_lock_task`, `_lock_issue`, and `reset_employee_password`'s inline lock all call `.with_for_update()` — the
correct primitive, in the correct place, exactly matching `Business_Logic_Security_Cheat_Sheet.md`'s own
first-listed "Use Database Transactions and Locks" pattern. It genuinely takes the Postgres row lock. What
every prior check missed — Phase 2's own audit (commit `503f73c`, which believed it had fixed a concurrent
password-reset race), CodeQL, Semgrep, and every code review in between — is that SQLAlchemy's identity map
returns the session's already-cached Python object for a primary key that was read earlier in the *same*
session, rather than the fresh row the locked query just fetched. The database lock genuinely blocks the
second racer; the Python object it then reads (`if locked.status != "open": ...`) is still the stale,
pre-lock one. Two racers that were supposed to produce one success and one rejection both silently
succeeded. Real defect in code every prior pass believed was fixed and verified — found only when a
real-Postgres, two-thread concurrency test (`backend/tests/crud/test_concurrency.py`, built to prove a
different property) failed when it should have passed, then fixed with `.execution_options(populate_
existing=True)` (commit `8565734`) and confirmed by deliberately stripping the fix back out and watching the
same test fail 3/3, then restoring it and watching 15/15 pass.

Same underlying shape as failure mode 6 — a textbook-correct primitive present in a textbook-correct place
gives a human reviewer and a signature-matching scanner alike nothing to flag, because nothing about the
code's *shape* is wrong. The defect is a fact about runtime session state (does this session already hold a
cached copy of this row?), not a fact visible in source. Phase 2's own audit even wrote down that its
verification only ran against SQLite — which silently ignores `.with_for_update()` entirely — but treated
that as an acceptable, unavoidable limitation rather than as "this fix was never actually verified,"
because at the time no real-Postgres concurrency test existed to notice the difference.

**How to apply:** any function that reads a row unlocked, then later re-reads the same primary key with
`.with_for_update()` (or any pessimistic lock) *in the same ORM session*, needs a real test that races two
actual threads/connections against a real instance of the actual production database engine — not SQLite,
not a single-threaded call, not "the lock statement executed without raising" — and asserts on the genuine
outcome (one success, one rejection; or, if nothing branches on the locked value yet, that the two racers
are provably serialized). "The lock is in the code" and "the lock actually protects this decision" are
different claims; only the second one is the one that matters, and only a concurrent execution — never a
read of the source — can verify it.
