# CA Firm Practice Management Tool — Deployment & Distribution

> Follows `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`. Still no code — this document plans how what gets built eventually reaches a real machine.

**Unlike the previous two documents, most of this isn't skill-verified — but a correction to that claim: the security practices around it are.** *Which* platforms to use (Docker, Railway, Cloudflare) isn't covered by any skill in this project's library — operational/product knowledge, not the kind of reference material this project's skills were built for. But *how to secure* a CI/CD pipeline, secrets, and containers genuinely is — see §9. Everything else below is general knowledge plus live research done in-conversation (Railway and code-signing pricing were both looked up directly, not recalled). Check platform-choice details against the platform's own current docs before relying on them for real money or a real deploy; the security requirements in §9 are cited against an actual file in this repo.

## 1. Backend Containerization

**Docker, with an explicit Dockerfile** — not Railway's Nixpacks auto-detection. Reasoning, restated from earlier: a Dockerfile is portable. If this ever moves off Railway (Fly.io, Render, AWS), the build definition travels with the repo instead of living in Railway's UI config — cheap to decide now, same logic applied to `firm_id`/RLS.

Shape of the Dockerfile (not written yet — this is planning, not the file itself), **verified against `fastapi/guide/deployment/docker.md`, not memory**: Python base image → install dependencies via `uv` (§ tooling, decided earlier this session) → copy `app/` → expose the port → run via `CMD ["fastapi", "run", "app/main.py", "--port", "80"]` — the `fastapi` CLI's own `run` command, not raw `uvicorn` or `gunicorn`+`uvicorn`. **Correction to what this section said before verification:** I'd written "gunicorn managing uvicorn workers" from general recall — FastAPI's own docs state that pattern (the old `tiangolo/uvicorn-gunicorn-fastapi` image) is now explicitly deprecated, since Uvicorn itself can now manage and restart dead workers without Gunicorn's help. If multiple workers are ever needed (not a Phase 1 concern at 10 users, and per the same doc, not needed at all if Railway ever runs this behind its own multi-container/cluster scaling instead of one fat container), the current mechanism is `fastapi run app/main.py --port 80 --workers 4` — a flag on the same command, no second process manager.

**Added 2026-09-04 — `--forwarded-allow-ips` is required on this same command, checked against
`fastapi/guide/advanced/behind-a-proxy.md`.** By default FastAPI/Uvicorn won't trust `X-Forwarded-Proto`/
`X-Forwarded-For` from anyone — correctly, since it has no way to know who actually sent them. Left unset,
the app can't tell it's being reached over HTTPS at all (everything looks like plain HTTP internally), which
matters for anything that depends on knowing the real scheme. **Honestly more nuanced for Railway
specifically than "look up its IP range and trust it"** — this is Railway platform behavior, not covered by
any skill here, checked live rather than left as a guess: Railway's edge runs Envoy and forwards the real
client IP via its own `X-Envoy-External-Address` header, not a fixed, publishable proxy IP `--forwarded-allow-
ips` can be pointed at directly. The container has no ingress path except through Railway's own routing layer
(nothing else can reach it directly), which is exactly the condition FastAPI's own docs describe for when
trusting the proxy broadly (`--forwarded-allow-ips '*'`) is reasonable rather than reckless — the risk that
flag exists to prevent (an arbitrary client spoofing these headers directly) doesn't apply when the container
genuinely has no direct-internet path. Recorded as the current best answer, not a settled fact: **re-verify
against Railway's own current docs at actual deploy time** — same platform-research caveat this whole
document already carries, not a new one.

## 2. Hosting — Railway

Railway's GitHub integration builds from the Dockerfile on every push to `main` and deploys automatically — no custom deploy step needed in CI (§4).

**Actual current pricing, checked directly, not assumed:** Hobby plan is **$5/month**, which functions as a usage credit rather than a flat fee — if actual resource usage (CPU/RAM/egress) comes in under $5 worth, that's all you pay; usage beyond that is metered ($20/vCPU-month, $10/GB RAM-month, $0.05/GB egress, $0.15/GB-month volume storage). For a 10-user internal tool with light request volume, realistic usage should sit at or very near that $5 floor — this isn't a real budget line at Phase 1 scale.

Environment variables (Supabase connection string, JWKS/JWT config) live in Railway's environment variable UI, never committed to the repo.

**Connection string requirement, carried over from `ARCHITECTURE.md` §5's resolved finding:** the connection string here must authenticate as the dedicated `fastapi_app` Postgres role, never the project's default `postgres` role — `postgres` carries `BYPASSRLS` on Supabase, which would silently defeat this project's entire RLS-based tenant isolation.

**Found 2026-09-05, while writing the Phase 1 migration — a second, distinct connection is actually needed.**
The app's own runtime queries and Alembic's migrations were both implicitly assumed to share `DATABASE_URL`
(the `fastapi_app` connection above), but the first migration itself needs privileges `fastapi_app`
deliberately doesn't have and shouldn't be granted: `CREATE ROLE fastapi_app` (a role can't create itself —
this needs `CREATEROLE`/superuser), and the `on_auth_user_created` trigger on `auth.users`
(`ARCHITECTURE.md` §4 provisioning section) — Supabase restricts writes to the `auth` schema to its own
`postgres`/`supabase_admin` roles, not any ordinary application role. **Two separate connection strings,
both env vars, neither ever the same value**: `DATABASE_URL` (`fastapi_app`, what the running app uses,
least-privilege, no `BYPASSRLS`) and `MIGRATIONS_DATABASE_URL` (Supabase's own `postgres` connection, used
**only** by `alembic upgrade` — in CI's disposable `postgres:17` container this is just that container's own
superuser, no distinction needed there; against the real Supabase project it's the project's default
connection string from its dashboard). Neither is committed to the repo, both live in Railway's/CI's
environment variable store like every other secret here.

**Pooling mode — resolved 2026-09-03: Supavisor session mode** (`ARCHITECTURE.md` §5, host:port
`aws-[region].pooler.supabase.com:5432`, free tier). Not a direct connection: Railway (this section) has no
default outbound IPv6, and Supabase's free-tier direct connection is IPv6-only — confirmed by web search of
Railway's own support threads, not a project skill (Railway itself isn't covered by any skill here). Not
transaction mode either: that's Supavisor's serverless/edge-function mode, and this is one persistent Docker
container, not a fleet of transient functions — session mode is the pattern Supabase's own docs name for
exactly this shape (`supabase/database/connecting-to-postgres.md`).

**Single environment, no staging, this phase** — consistent with the single-firm-pilot framing throughout this project. Revisit once there's more than one firm depending on uptime.

**Added 2026-09-04 — Supabase free-tier auto-pause, checked directly against Supabase's current pricing page
(not recalled): "Free projects are paused after 1 week of inactivity."** Real, not hypothetical, and shared
across every firm at once — this project deliberately uses **one Supabase project for all tenants** (§6, the
pooled model), so a week with zero activity from *any* pilot firm pauses the database for all of them
simultaneously, not per-firm. Low-probability once 2+ firms are independently active (unlikely all of them go
silent the same week), but worth naming before it's discovered as an outage during a demo rather than as a
line in this doc. No fix needed at this scale — just tracked as a known risk; a trivial keep-alive ping
becomes worth adding only if it's ever actually tripped, or before real customers depend on uptime (same
trigger point already named above for staging).

## 3. Edge / Security Layer — Cloudflare

Sits in front of the **FastAPI API domain specifically**, not a public website — worth restating since there's no browser-facing frontend to protect (the Tauri app is the client, per `ARCHITECTURE.md`). The API is still a real network-facing service regardless of how the client is distributed, so this still matters.

**Free tier — confirmed sufficient for this phase**, discussed earlier: DDoS protection is unmetered and always-on at every tier (Cloudflare's core product, not paywalled), plus free TLS, DNS, and a small allotment of custom WAF/rate-limit rules. Revisit tier only once real tenant traffic actually approaches those free-tier rule-count limits — not a Phase 1 concern.

**Added 2026-09-04 — the TLS chain end to end, checked against `owasp-asvs-5/chapters/v12-secure-communication.md`
before this got specified, not assumed:** "Cloudflare gives free TLS" only covers the client-facing leg.
Three legs actually exist:
- **Tauri app → Cloudflare**: TLS at Cloudflare's edge — covered by the line above.
- **Cloudflare → Railway (the origin)**: **must be set to `Full (strict)`, never `Flexible`.** Checked against
  Cloudflare's own docs directly: `Flexible` mode terminates TLS at Cloudflare and forwards to the origin over
  plain HTTP — a direct violation of ASVS 12.3.1/12.3.3 ("TLS for all inbound/outbound connections... no
  fallback to cleartext"), and `Flexible` is a real default some Cloudflare zones start on, not a hypothetical
  misconfiguration. Railway's own domains carry valid TLS certs by default, so `Full (strict)` (encrypts *and*
  validates the origin cert) has no blocker — this is a dashboard setting to check, not new infrastructure.
- **Railway (FastAPI) → Supabase Postgres**: the connection string must include `sslmode=verify-full` —
  Supabase's own documented `psql` connection example uses exactly this (`supabase/database/psql.md`), and
  ASVS 12.3.2 requires the client actually validate the certificate, not just encrypt opportunistically.
  **Enforced 2026-09-11, not just documented:** `Settings._require_tls_to_remote_db`
  (`backend/app/core/config.py`) rejects a `DATABASE_URL` / `MIGRATIONS_DATABASE_URL` whose host is not
  loopback and whose query string is not exactly `sslmode=verify-full` — `Settings()` runs at import, so a
  misconfigured deploy fails to boot rather than silently connecting without cert validation. Loopback hosts
  (local dev, the CI postgres service) are exempt: that connection never crosses a network. Tested in
  `backend/tests/core/test_config.py`.

(The fourth leg, frontend → Supabase Auth directly, is HTTPS by construction via the Supabase SDK's own URL —
nothing to configure.)

## 4. CI — GitHub Actions, checks only, not deployment

- On every push/PR: lint + type-check the backend (`ruff` + **`pyright`**, not `mypy` — corrected earlier this session specifically so the CI check matches what Pylance shows locally, avoiding a mismatch between what the editor says and what the gate enforces) and the frontend (`eslint` + `tsc`).
- Tests run once any exist. **Made concrete 2026-09-04**: this specifically includes the tests already
  *required* elsewhere in this project's docs — the tenant-isolation cross-read/update/delete test and the
  `fastapi_app` `BYPASSRLS` assertion (`ARCHITECTURE.md` §5), and the authorization-matrix suite
  (`API_SPEC.md` §4) — these become required status checks the moment they're written, not folded into a
  generic "tests, eventually."
- **Two backend test jobs (2026-09-11).** `backend` runs against a bare `postgres:17` service container with
  `auth.users` and the Supabase roles hand-stubbed — fast, covers RLS / tenant isolation / crud / the auth
  dependency chain (with a forged RS256 token + mocked JWKS). `e2e` runs against a **real disposable local
  Supabase stack** (`supabase/setup-cli` → `supabase start`, db + auth + api only, per `supabase/config.toml`)
  with `alembic upgrade head` applied on top: this is the only place the `handle_new_user` provisioning
  trigger, the `custom_access_token_hook` claim injector, the Auth Admin API, and real ES256-token
  verification against a real local JWKS endpoint actually run (`backend/tests/e2e/`, `pytest -m e2e`, gated
  on `E2E=1`). Still not the live project — a container stack, thrown away after the job. Locally: `supabase
  start` then `E2E=1 uv run pytest -m e2e`. `supabase/config.toml` also version-controls the auth settings
  the real project must be given by hand (`minimum_password_length`, `secure_password_change`, the hook
  registration) — see §2's TLS-chain note and the password-policy note below.
- **Gate merges to `main` on these passing — made concrete 2026-09-04, checked against
  `owasp-cheatsheets/GitHub_Actions_Security_Cheat_Sheet.md` (not cited in this document before now).** "Gate"
  wasn't previously specified as a real mechanism — the intended one is **GitHub branch protection on `main`**:
  required status checks so the merge button stays locked until they're green.
  - The cheat sheet's full recommendation also includes required PR reviews, `CODEOWNERS` approval, and signed
    commits — deliberately not pursued at all right now: those three defend against a second contributor's
    changes (an unreviewed PR, an unowned path, a commit impersonating someone else), and there is no second
    contributor yet.
  - **Real platform gap, hit and confirmed 2026-09-04, not a config mistake:** both the classic
    branch-protection API and the newer Rulesets API were tried against this actual repo and both returned
    `403 — "Upgrade to GitHub Pro or make this repository public to enable this feature."` Branch protection is
    a paid-plan feature for private repos on GitHub Free; public repos get it free regardless of plan. Explicitly
    not worked around by paying for Pro or making the repo public (this is commercial source — visibility loss
    isn't a security trade-off here, it's giving away the product) at pilot scale, solo-dev.
  - **Temporary stand-in while that gap stands, decided 2026-09-04 — a procedural gate, not a platform one, and
    explicitly a stopgap for the current phase only.** Right now every push to `main` goes through this
    same working process: the project owner and Claude, together, on every push — nobody pushes directly and
    walks away. Every push's CI run gets checked before the work is considered done; a red run is treated
    exactly like a locked merge button — patched and re-pushed before moving on, never left standing. Stated
    plainly so the difference is never assumed away: this is enforcement by discipline and a single shared
    process, not a technical control — it has no effect the moment a second contributor pushes on their own.
    **A second contributor joining is therefore the hard trigger to stop relying on this and either pay for
    GitHub Pro or otherwise get a real platform-enforced gate** — not a nice-to-have revisit.
- **Three more items from the same cheat sheet, none previously in this document:**
  - **Restrict the default `GITHUB_TOKEN` permissions to read-only** at the repo-settings level; grant write
    explicitly per-workflow only where a specific job actually needs it (none of the jobs above do).
  - **Pin any third-party GitHub Action to a commit SHA, not a version tag** (`@a1b2c3d...`, not `@v4`) — a
    tag can be silently repointed to different code later; a pinned SHA can't.
  - **Secret scanning — checked, with a real cost wrinkle, not silently assumed free.** GitHub's own
    push-protection secret scanning is free only on *public* repositories (verified via web search, not a
    project skill); a private repo needs paid GitHub Advanced Security, not worth it at pilot scale — same
    call already made on Supabase's breached-password check. Free equivalent: **gitleaks**, open-source, runs
    as a plain CI step regardless of plan or repo visibility — wired into a dedicated `security` job
    2026-09-04 (was decided here first, sat undone until checked against the actual workflow file).
  - **Static analysis on the workflow file itself, not just the app code — added 2026-09-04, same `security`
    job.** `zizmor` (`uvx zizmor --format=github .github/workflows/`), free and open-source regardless of repo
    visibility, unlike CodeQL's Actions scanning which hits the same private-repo paid wall as branch
    protection. Catches the workflow-level risks this cheat sheet describes (dangerous triggers, impostor
    commits) that ruff/pyright/eslint never look at, since those only see application code.
  - **`.github/dependabot.yml` — added 2026-09-04.** Pinned commit SHAs (previous bullet) don't update
    themselves; Dependabot is what notices a new release of `actions/checkout`/`setup-uv`/etc. exists and opens
    the PR to bump the pin. Weekly, with a 4-day cooldown so a freshly-published release isn't pulled in before
    the community has had a chance to flag it as broken or compromised. This is also what satisfies
    `owasp-asvs-5` **15.1.1** below — a running mechanism, not just a stated intention.
  - **`actions/checkout` now sets `persist-credentials: false` — added 2026-09-04.** None of these jobs push
    back to the repo, so there's no reason for a git credential capable of doing so to sit in the runner's
    workspace for the job's duration.
- **Dependency remediation timeframe — `owasp-asvs-5` 15.1.1 (Level 1), checked 2026-09-04 and previously
  absent from this document.** Stated plainly, not left implicit: a critical/high-severity CVE in a direct
  dependency gets patched within 7 days of the fix being available; routine version bumps (the Dependabot PRs
  above) are reviewed weekly, not left to accumulate. This is a policy statement, not a tool — the tool is
  Dependabot itself, which is what actually surfaces the "a dependency needs attention" signal in the first
  place.
- **Deployment is not this pipeline's job** — Railway's own GitHub integration (§2) handles the actual build-and-deploy on green. Building a duplicate deploy step in Actions would just re-implement what the platform already does.

## 5. Desktop App Distribution — Tauri

Installer built via the Tauri CLI, **delivered directly to the pilot firm** — not through an app store, not a public download link. This is the single-firm-trial distribution model discussed earlier, and it shapes two decisions below the same way.

### Code-signing — deferred for the pilot, decision already made

Restating the earlier call plainly, now that it's in the actual planning doc rather than just chat: **bypassed for this single-firm trial**, because the trust chain is you personally handing the installer to a known firm on known machines, not an anonymous download. Users will see Windows SmartScreen ("More info" → "Run anyway") or macOS Gatekeeper friction — mitigated with a short plain-language note accompanying the installer so non-technical staff don't mistake the warning for something being wrong.

**Hard boundary, stated so it can't quietly slip:** required before any rollout beyond this one firm. Real cost when that time comes, checked directly earlier this session:

| Platform | Option | Cost |
|---|---|---|
| Windows | Azure Trusted Signing (recommended over a traditional EV cert — EV no longer clears SmartScreen any faster than OV, so the premium buys nothing here) | ~$9.99/month (~$120/year) |
| macOS | Apple Developer Program | $99/year flat, includes notarization |
| **Combined, when needed** | | **≈ $220/year** |

### Update mechanism — applying the same pilot-scale reasoning, made explicit here

Not previously resolved — worth deciding now rather than leaving it open. Two options: build Tauri's updater plugin (auto-update from a hosted manifest) now, or handle it manually for the pilot (you personally rebuild and resend the installer on the rare update, same 10 people reinstall by hand).

**Decision: manual redistribution for the pilot**, same reasoning as code-signing — you're already the one delivering installers directly to a known, small group, so a manual update is a text message and a re-download, not a real burden at this scale. Building the auto-update plugin now would be infrastructure for a distribution model (public/unattended updates) that doesn't exist yet.

**Same hard boundary as code-signing:** required before any rollout beyond this one firm — at that point, nobody can be manually walked through a reinstall, and shipping a security fix without an update mechanism would be a real gap, not a convenience gap.

## 6. Observability — resolved 2026-09-05, previously completely open

Nothing about logging, error tracking, or uptime alerting existed anywhere in this project's docs before now
— not under-specified, genuinely absent. Checked `owasp-cheatsheets/Logging_Cheat_Sheet.md` and
`owasp-asvs-5/chapters/v16-security-logging-error-handling.md` directly, plus live-verified the actual free-
tier numbers for the tools involved (same discipline as Railway/Cloudflare elsewhere in this document).

**Application logs — Railway's own capture, no new infrastructure.** Verified directly against Railway's
docs: anything written to stdout/stderr is automatically captured, searchable, 7-day retention on the Hobby
plan. Structured logging (Python stdlib `logging` with a JSON formatter — no new dependency) is enough to make
that searchable output actually useful, per the Logging Cheat Sheet's "when, where, who, what" attribute
guidance. **What actually gets logged, applied proportionately rather than as a blind checklist** (the cheat
sheet's own explicit warning against "alarm fog"): authentication successes/failures, authorization
failures (403/404s), workflow-state-violation attempts (409s — the exact "out-of-order execution" case
`API_SPEC.md` §1 already names), and unhandled exceptions. Admin actions already have a home
(`audit_log`, `DATA_MODEL.md`) — not duplicated here.

**Reconciled 2026-09-05, after `access_denials` (`DATA_MODEL.md`) was built without cross-checking
this section first — a real process gap, caught on self-audit, not a design conflict once checked.**
Same relationship as `audit_log` above, not a duplication: this section's "authorization failures
(403/404s)" line still stands as-is for Railway/Sentry — it's the real-time, catch-all layer, and it
covers cases `access_denials` structurally can't (genuine 404s with no denial to log, 401s, anything
not tied to an authenticated actor). `access_denials` is the narrower, durable, tenant-scoped,
permanently-retained counterpart for one specific subset of that same category — same-tenant IDOR and
role/ownership denials only (its own "structural limit" note explains why cross-tenant attempts stay
outside even that). Both should exist; neither makes the other redundant.

**Error tracking — Sentry, free Developer plan.** Verified directly: 5,000 errors/month, 1 user, free
forever — comfortably covers pilot-scale volume. The 1-user limit is fine while you're the one monitoring
this; revisit once the firm itself needs its own visibility. This is also where ASVS 16.5.1 actually gets
satisfied end to end: the client-facing error stays generic (`problem+json`, `API_SPEC.md` §1), but the real
stack trace still has to land somewhere for debugging — Sentry is that somewhere, not "discarded."

**Implemented both sides (2026-09-13):** backend (`app/main.py`'s `sentry_sdk.init`, guarded on
`SENTRY_DSN`) was wired first; frontend (`@sentry/react`, guarded on `VITE_SENTRY_DSN`, wired into
the scoped `ErrorBoundary`'s `componentDidCatch` via `Sentry.captureReactException`, per ASVS
16.5.4's "last resort handler... preserves error details for logs") closed the remaining gap. Both
deliberately leave PII collection at its default-off setting (`send_default_pii` unset on the
backend, `sendDefaultPii`/`dataCollection` unset on the frontend) — a new third-party destination
gets its own check, not inherited trust from the mechanism's docs-example defaults
(skill-verification-discipline.md failure mode 7). CSP's `connect-src` (`tauri.conf.json`) allows
`https://*.ingest.sentry.io` accordingly.

**Corrected 2026-09-19 — "default-off" was not enough.** The paragraph above says leaving
`send_default_pii` unset keeps request bodies and headers out of Sentry. Capturing a real event from a
FastAPI app with the SDK's defaults (sentry-sdk 2.68.1) showed otherwise: the request body was in
`request.data`, and every stack frame's local variables were attached — including the raw
`Authorization: Bearer` header inside the ASGI scope. `include_local_variables=False`,
`max_request_body_size="never"` and a `before_send` scrubber (`backend/app/core/sentry_config.py`) now
close that; the trade-off (no variable snapshot on an event) is in `OBSERVABILITY.md` §3. The
"structured JSON logs" promised above are implemented (same date): tenant-tagged, injection-safe,
allowlisted fields, database-echoed values redacted.

**Uptime alerting — a real gap Railway itself admits to.** Its own docs state plainly: no built-in alerting;
forward to a third-party tool for that. **UptimeRobot's free tier** (verified: generous free monitor count,
5-minute check interval) pings the API and emails on downtime — the free, minimal
answer to "if the pilot's API goes down at 2am, does anyone find out." Not real-time, not enterprise-grade,
proportionate to a 10-40 user pilot. **Point it at `/ready`, not `/health` (revised 2026-09-19):** `/health`
is liveness only and stays green while Postgres is down; `/ready` runs a bounded, fail-closed database probe
(`OBSERVABILITY.md` §4).

**Added 2026-09-19 (Observability Phase 1, `OBSERVABILITY.md`):** two scheduled GitHub Actions checks, both
off until a repo variable enables them — a least-privilege read-only database health check
(`ops-db-check.yml`, catches connection headroom, stuck/slow/blocked work, vacuum lag, table growth) and a
tenant-isolation canary (`isolation-canary.yml`, synthetic firms probing the deployed API). Neither needs new
infrastructure or a paid service; a failed run is the notification. The log inventory (ASVS 16.1.1), the
alert matrix with what is *not* yet watched, and the runbooks are in that file.

**Explicitly not built this phase**: no APM/tracing (Datadog, New Relic-style), no log aggregation platform,
no on-call rotation/paging. All infrastructure for a scale and team size this project doesn't have yet — the
three items above (structured stdout logs, Sentry, UptimeRobot) are the proportionate floor, not a partial
version of a bigger system being deferred piece by piece.

## 7. Pipeline, end to end

```
push to GitHub → Actions runs lint + pyright/tsc + tests (gate) → merge to main
  → Railway detects push, builds Dockerfile, deploys
  → Cloudflare sits in front of the resulting API domain
  → Tauri installer built and delivered separately (not part of this pipeline — a manual step, per §5)
```

## 8. Explicitly Deferred — stated as decisions, not gaps

Same discipline as `ARCHITECTURE.md` §10 (caching/async) — each of these has a stated trigger, not left to be silently forgotten:

| Deferred | Trigger to revisit |
|---|---|
| Staging environment | More than one firm, or real customers depending on uptime |
| Tauri auto-update mechanism | Any rollout beyond this one firm |
| Code-signing | Any rollout beyond this one firm |
| Elevated Cloudflare tier | Real tenant traffic approaching free-tier rule limits |
| APM/tracing, log aggregation, on-call paging (§6) | Team/scale grows past what Sentry + Railway logs + UptimeRobot can cover |

## 9. Cost Summary — Phase 1 (pilot)

| Item | Cost |
|---|---|
| Railway (Hobby, realistic usage) | ~$5/month |
| Cloudflare | $0 (free tier) |
| Sentry (Developer plan) | $0 (free tier, §6) |
| UptimeRobot | $0 (free tier, §6) |
| Code-signing | $0 (deferred, §5) |
| **Total, Phase 1** | **~$5/month** |

Real cost jumps only when rolling out beyond the pilot firm: add code-signing (~$220/year, §5) and whatever Railway usage actually grows to at real tenant volume — not estimated here, since that depends on tenant count and usage patterns that don't exist yet to measure.

## 10. Security Requirements Applied

Per the standing instruction to check every component against the OWASP skills — this pipeline genuinely has coverage, unlike the platform-choice sections above:

| Area | Cheat sheet | What it requires here |
|---|---|---|
| CI/CD pipeline hardening | `CI_CD_Security_Cheat_Sheet.md` | Least-privilege access (contributors run pipelines, don't administer them); pipeline output must never leak secrets into logs; only an approved, reviewed process can create/modify pipeline config |
| GitHub Actions specifically | `GitHub_Actions_Security_Cheat_Sheet.md` — **added 2026-09-04** | Branch protection as the actual merge gate (§4); `GITHUB_TOKEN` restricted to read-only by default; third-party Actions pinned to a commit SHA, never a mutable tag; gitleaks for secret scanning (GitHub's own push protection is paid-only on private repos) |
| Secrets (Supabase connection string, JWKS config) | `Secrets_Management_Cheat_Sheet.md` | Stored in the CI/CD platform's own encrypted secrets store (GitHub Actions' built-in encrypted secrets for CI; Railway's environment variable UI for runtime, §2) — never committed to code, consistent with what §2 already said, now extended explicitly to CI itself, not just runtime. **Made concrete 2026-09-03**: §5.1 of that cheat sheet, quoted directly — *"secrets themselves should never be hardcoded using docker `ENV` or docker `ARG` commands, as these can easily leak with the container definitions."* Railway's env-var-UI approach (§2) already avoids this by construction (injected at container runtime, not build time) — but the Dockerfile itself (§1) must never declare the secret via `ARG`/`--build-arg` either, only ever read it from the process environment at runtime (`Settings(BaseSettings)`, already the planned pattern) — worth stating as a constraint on the Dockerfile's own shape, not just on where the value is stored |
| Dockerfile | `Docker_Security_Cheat_Sheet.md` | Non-root user inside the container, minimal base image — a real requirement for when the Dockerfile actually gets written, not implementation yet |
| Dependencies (`uv`, npm) | `Software_Supply_Chain_Security_Cheat_Sheet.md` | Pinned versions, integrity verification — applies once `pyproject.toml`/`package.json` exist. **Made concrete 2026-09-03**: the skill's actual baseline mechanism is a committed lockfile (`uv.lock`, `package-lock.json`) — both must be committed to the repo, not gitignored, and CI (§4) installs from the lockfile exactly (`uv sync --frozen`, `npm ci` not `npm install`) rather than letting either resolve fresh versions on every run. Free, zero-infrastructure addition worth naming now: enable GitHub's built-in Dependabot alerts on the repo — no new tooling, just a setting |

---

Reminder, stated once more since it applies to this whole document outside §9: nothing above is a skill citation. It's current-as-of-today research (Railway and code-signing pricing pulled directly this session) plus general infrastructure reasoning — worth an independent check against Railway's/Cloudflare's/Apple's/Microsoft's own current pricing pages before this becomes a real bill, since none of that is pinned to a source document the way `ARCHITECTURE.md`/`DATA_MODEL.md` are.

## 11. Supabase Auth Dashboard Settings — Required Before Go-Live

Found 2026-09-06 during a Phase 4 audit pass, by reading the installed `@supabase/auth-js` type
definitions directly rather than trusting the frontend code's own comments: two of the password
controls `ARCHITECTURE.md`'s password-policy section (§ "Password policy... checked against
`owasp-asvs-5/chapters/v6-authentication.md` §6.2") already decided on are **dashboard/project-level
settings, not something the frontend code enforces by itself** — easy to assume "done" once the
client code compiles and ships, when in fact nothing enforces either one until a human flips a
setting in the real Supabase project (which doesn't exist yet — this is a required step for
whenever it's created, not a currently-missed one):

- **Minimum password length (ASVS 6.2.1).** `ARCHITECTURE.md` already states Supabase's own default
  is lower than the required 8 chars and "must be set explicitly in the dashboard" — Authentication →
  Policies → Password minimum length. No code path enforces this; it's purely a project setting.
- **"Require current password when changing password" (ASVS 6.2.3).** The frontend passes
  `current_password` on every `updateUser()` call (`use-set-new-password.ts`, `use-change-password.ts`)
  expecting Supabase to verify it before allowing the change. Confirmed directly in
  `node_modules/@supabase/auth-js/dist/module/lib/types.d.ts`'s `UserAttributes.current_password`
  doc comment: *"This is only ever present when the user is resetting their password and
  `GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_CURRENT_PASSWORD` is true."* — i.e. **if that GoTrue
  config flag is left at its default, Supabase silently ignores the field and allows the password
  change with no current-password check at all**, even though the frontend code looks like it's
  enforcing one. Must be set (Authentication → Providers/Policies, or `auth.security.update_password_
  require_reauthentication` if managed via `supabase/config.toml` once the CLI is in use) the moment
  the real project is created — otherwise ASVS 6.2.3 is silently unmet despite the code suggesting
  otherwise.

Verify both are actually set (not just assumed) as part of whatever manual smoke-test happens the
first time `npm run tauri dev` runs against the real project (`binary-meandering-wind.md`'s own
Step 3 verification checklist) — try changing a password with the wrong current password and confirm
it's rejected, not just that the happy path works.

- **JWT signing algorithm — choose ES256, not RS256, when creating the real project.** Found
  2026-09-06 auditing Phase 1: `owasp-asvs-5/patterns.md`'s approved-algorithm table marks
  RSASSA-PKCS1-v1.5 (RS256) **Disallowed** outright (ECDSA/ES256 is Approved); separately, even where
  RSA is allowed, ASVS 11.2.3's ≥128-bit-security-level bar needs a 3072-bit RSA key — the patterns.md
  key-size table puts 2048-bit RSA at only ~112-bit security. (Supabase's own docs weren't checked for
  which RSA key size they'd actually generate if RS256 were chosen — confirm this against the real
  project's JWKS directly if RS256 is ever considered, rather than assuming 2048-bit.) Supabase's
  own docs recommend ES256 over RSA for exactly this reason ("faster... while providing comparable
  security... we recommend using the P-256 elliptic curve instead") and let the signing algorithm be
  chosen per-project in the dashboard — nothing forces a default either way. `backend/app/core/
  security.py`'s `_ALGORITHMS` currently allowlists both `RS256` and `ES256` for verification, kept
  broad because no real project has existed yet to confirm which one it actually issues. Once the
  real project is created and set to ES256, narrow `_ALGORITHMS` to `["ES256"]` only (and update
  `tests/core/test_security.py`'s token fixture, which currently signs with a 2048-bit RSA key/RS256,
  to an EC key/ES256 to match) — do this as a real, verified follow-up once the project exists, not a
  guess made now that could otherwise silently break every login if the real project ends up on RS256.

## 12. Tauri CSP `connect-src` — Real API Origin Required Before a Production Build

Found 2026-09-07 during a Phase 4 checklist-backed audit pass: `frontend/src-tauri/tauri.conf.json`'s
`app.security.csp.connect-src` currently reads `'self' ipc: http://ipc.localhost http://localhost:8000
https://*.supabase.co` — the `http://localhost:8000` entry is the local dev FastAPI backend
(`tauri-official/chapters/security-capabilities.md`'s own suggested policy for this project names it
as `https://<api-domain>`, explicitly flagged there as "fill in ... once those are fixed"). §2 above
already places the real backend on Railway behind Cloudflare (`Full (strict)` TLS) — an HTTPS origin
that doesn't exist in this CSP at all yet, since no real deployment has happened.

**Not a live security hole today** (this is a desktop app not yet built for release, and
`http://localhost:8000` can only ever resolve to something on the same machine running the app — no
remote attacker gains anything from it being present), but a real availability gap if missed: shipping
a production build with this CSP unedited would have every API call silently blocked by the webview's
own CSP enforcement, discovered only after distribution, not caught by any existing check (`npm run
build` compiles fine regardless — CSP violations are a runtime browser/webview behavior, not a build
error).

**Required before the first production build** (Phase 6, Distribution, per `CODING_STRUCTURE.md` §4
item 7): replace `http://localhost:8000` in `connect-src` with the real Railway/Cloudflare HTTPS origin
once it exists. Verify by an actual failed-then-fixed request in a production-configured build, not by
inspection alone — a CSP violation is silent (no thrown error the app code can catch), so "the API call
just doesn't work" is the only symptom without an explicit check.

## 13. Connecting the Real Supabase Project — Runbook

Written 2026-09-10, before actually doing this — a plan to execute next session, not a record of
something already done. §11's "doesn't exist yet" framing is now stale: a project ref was found
embedded in a misconfigured local MCP server entry the same session this runbook was written —
confirm this is actually the intended pilot-firm project (not a stale/test one) as this runbook's
first step, rather than assuming. **Scrubbed from this doc 2026-09-14** (repo went public that day):
the ref that was here was checked and is dead (`DNS_PROBE_FINISHED_NXDOMAIN`), so it was never the
real project — but a real ref shouldn't be committed to a public repo regardless, hence a placeholder
below instead of the actual value.

**Ordered steps:**

1. **Confirm the project.** Verify `<project-ref>` (whichever project ref is actually current — get it
   from the Supabase dashboard, don't assume one found lying around elsewhere) is the real, intended
   one before touching it with a migration.
2. **Get `MIGRATIONS_DATABASE_URL`** from that project's dashboard — Project Settings → Database →
   Connection string, the `postgres` superuser role (same shape CI's disposable container uses, §4).
   Handed over as an env var, never committed to the repo — same handling as every other secret here.
3. **Run `uv run alembic upgrade head` directly against it** — the same command this session ran
   repeatedly against local/CI disposable Postgres instances, just pointed at the real project.
   **Deliberately not via the Supabase MCP server's own `database`/`development` tools**, even once
   that connection exists: this repo's migration history lives in `backend/app/alembic/versions/*.py`
   and is meant to run through exactly one path (`CODING_STRUCTURE.md`: "one migration per schema
   change, never hand-edited after merge") — running schema changes through a second, MCP-driven
   mechanism would be a real, undocumented deviation from that, not a shortcut.
4. **Flip the required dashboard settings** — §11 above already names 3 (password minimum length,
   require-current-password, ES256 vs RS256 signing). A 4th, not previously collected anywhere in this
   file: **enable the Custom Access Token Auth Hook** (Authentication → Hooks → Custom Access Token),
   pointed at `public.custom_access_token_hook(event jsonb)` — the function migration `a8e6def15927`
   already creates. The migration only creates the function; nothing enables it. Without this step,
   `app_metadata.role`/`firm_id`/`must_change_password` never reach the JWT and every
   `get_current_profile`/`require_owner`/`require_password_set` gate in `backend/app/api/deps.py`
   silently breaks — this is the single most load-bearing dashboard setting in this whole runbook, more
   so than any item already listed in §11. A 5th, added 2026-09-14 after code review finding #11:
   **confirm Authentication → Sign In / Providers → "Allow new users to sign up" stays disabled** —
   `supabase/config.toml`'s `enable_signup = false` comment already claimed this runbook required it,
   but nothing here ever actually did until now. This is now defense-in-depth rather than the only
   thing standing in the way: `handle_new_user()` (migration `c0f23284b2fd`) reads `firm_id`/`role`
   from `app_metadata`, which self-signup can never set regardless of this toggle — but leaving public
   signup enabled with no invite/approval flow in front of it is still its own problem (unvetted
   accounts, one firm per deployment assumption broken), so verify it explicitly, don't rely on the
   structural fix alone to make the toggle's state not matter.
5. **Decide the breached-password-protection gap explicitly**, don't silently skip it — `ARCHITECTURE.md`
   §14 already named this: accept the ASVS 6.2.4/6.2.12 gap for the free-tier pilot, revisit by flipping
   Supabase's native leaked-password toggle once/if the project moves to the Pro plan.
6. **Set the real env vars** — `frontend/.env` (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`,
   `VITE_API_BASE_URL`) and the backend's `SUPABASE_URL`/`SUPABASE_SECRET_KEY`/`CORS_ORIGINS`, matching
   `.env.example`'s shape in each. Git-ignored, never committed.
7. **Run the Firm + Owner provisioning script** (`ARCHITECTURE.md`'s Firm + Owner Provisioning section)
   against the real project to create the first real Owner account — the one prerequisite every later
   manual test in this runbook needs.
8. **Fix the local Supabase MCP connection for ongoing read-only use.** The current entry
   (`supbase_mcp_server` in the local Claude Code config) is broken because its `url` field holds the
   entire `claude mcp add` shell command instead of a URL — that command needs to actually be *run*, in
   an interactive terminal, not pasted into config by hand:
   ```
   claude mcp add --scope project --transport http supabase "https://mcp.supabase.com/mcp?project_ref=<ref>&read_only=true&features=docs%2Caccount%2Cdatabase%2Cdebugging%2Cdevelopment%2Cfunctions%2Cbranching"
   ```
   `read_only=true` is already part of the intended config — keep it; this connection is for inspecting/
   debugging the real project afterward, never for running migrations (step 3 already covers that
   through the repo's own path). Newly-added MCP servers take effect starting the *next* session, not
   the one that ran `claude mcp add` — confirmed session behavior, not a misconfiguration if it doesn't
   show up immediately.
9. **Run the actual manual smoke test** — `binary-meandering-wind.md`'s Step 3 verification checklist,
   already referenced by §11 above but never yet executed against a real project: `npm run tauri dev`,
   log in with the provisioned Owner's generated temporary password, confirm the forced Set New Password
   gate, change the password, close and reopen the app to confirm the session survives via the Tauri
   storage plugin (not just in-memory), and deliberately try the wrong current password on a change to
   confirm step 4's hook and §11's "require current password" setting are both actually enforced — not
   assumed correct because the code looks right.
10. **Update this file and `ARCHITECTURE.md`'s stale "doesn't exist yet" language** once the above is
    actually done — don't leave a completed-reality doc still describing a not-yet-real state.
