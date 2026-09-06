# Working preferences — how this user wants sessions run

Repo-local (not folder-scoped memory, not appended into `CLAUDE.md`) so it travels with the repo and stays a
separate, purpose-named file rather than bloating a shared entrypoint — per the user's own explicit
preference (see item 4 below, which is itself demonstrated by this file existing at all).

These are demonstrated, repeated preferences from actual session behavior — not restatements of the global
`~/.claude/CLAUDE.md` rules (verify-before-claiming, fixed-domain sweep, OWASP search discipline, ponytail),
which already apply everywhere and don't need repeating here.

## 1. State the plan/answer first, get explicit confirmation before executing

Especially for file edits, git operations (push/PR/merge vs. commit-only), or anything non-trivial: describe
what's about to happen and wait for an explicit go-ahead, rather than acting on the first reasonable reading
of a request. Demonstrated repeatedly — "tell me which thing... before doing", "just tell me possible or not
for now", the deliberate commit-only vs. push/PR/merge distinction on the same set of fixes at different
times. Not a one-off request; treat it as the standing default for this user.

## 2. A status/"watching"/"done" claim must be backed by re-checked real evidence, not by the act of having claimed it

When asked "did X actually happen" or "did that pass," pull the real artifact (a CI job log, actual grep
output, an actual test run) rather than re-asserting from a proxy signal (a green checkmark, a
completed-sounding tool call). Say plainly when an earlier claim didn't actually deliver what it implied,
rather than defending it. Demonstrated concretely: the `Monitor` tool timed out twice while "watching" CI
without ever delivering a completion signal, and the actual confirmation came only from manually running
`gh pr checks`/`gh run view --log` afterward — this was reported honestly rather than papered over. Also
demonstrated by the repeated direct question "u said u r watching?" after a claim that didn't hold up on
inspection.

## 3. When a message is garbled or ambiguous, ask — don't guess

Particularly when the possible interpretations include a real code or process change. Use `AskUserQuestion`
with the candidate interpretations rather than picking one and proceeding. Demonstrated with a garbled
message ("ibuild the 4 a 8 for u mentioned") that could plausibly have meant a real hook/code change —
resolved by asking rather than guessing.

## 4. New process/discipline content gets its own dedicated file, not appended into a shared high-traffic entrypoint

`CLAUDE.md` and `MEMORY.md`-style index files stay short pointers; the actual content (a discipline's full
reasoning, a preferences list like this one) goes in its own file, linked from the entrypoint. Demonstrated
twice: `docs/skill-verification-discipline.md` was written as its own file rather than folded into
`CLAUDE.md`, and this file itself — the user explicitly asked for a separate file rather than an append to
`CLAUDE.md`.

## 5. The audit-checklist mechanism's own known limit, and the decision on how far to close it

A hook enforcing that an evidence field isn't blank (`~/.claude/hooks/audit-checklist-guard.js`) is not the
same as verifying the content is true — a fully-filled, hook-satisfied audit pass can still be shallow or
even fabricated, since the hook only checks non-blank fields. Four options were weighed for narrowing that
gap: (1) cross-referencing the session transcript to confirm claimed tool activity actually happened, (2) an
LLM-judge step inside the hook, (3) `docs/SECURITY_AUDIT_CHECKLIST.md`'s own Section F (`/code-review ultra`,
an independent multi-agent review), (4) human spot-checking. **Decision: skip (1) and (2)** — real
engineering cost, still gameable, and no actual fabrication incident in this project's history justifies
building them (matches the same cost/benefit call already made once before, in `third-party-tool-vetting-
standard.md`'s declined free-form-claim-scanner). **Adopted going forward: (4) always** — flag the least
independently-verified claim in each completed audit entry — **and (3) periodically**, not every phase, since
it's already built and simply never exercised yet.

## 6. Third-party tool vetting: real legitimacy is a separate question from proportionate fit

`claude-mem` (github.com/thedotmack/claude-mem) was vetted against `third-party-tool-vetting-standard.md`
after being raised as a possible fix for cross-session context portability. Verdict: **legitimate** (old,
real maintainer account; genuine multi-year npm publish history; star/fork counts confirmed real via the
GitHub API directly, not a WebFetch artifact) but **rejected as disproportionate** — its runtime footprint
(SQLite + a Chroma vector DB + a background Bun HTTP server + an AI-provider API key for its compression
step + optional cloud sync to a third party) is far heavier than the actual problem needed solving. The
actual fix that shipped instead: three plain repo-tracked files (`CLAUDE.md` §7,
`docs/skill-verification-discipline.md`, this file) — free, no new dependency, no background process, no
external service. A tool being real and well-built doesn't mean its footprint fits the problem at hand;
check both, separately, every time (same lesson this project already applied once before to `gstack`).
