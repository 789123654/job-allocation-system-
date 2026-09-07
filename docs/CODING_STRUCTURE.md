# CA Firm Practice Management Tool — Coding Structure & Build Order

> Follows all six prior docs. Nothing here changes a decision already made — this is how those decisions
> become a codebase without becoming a mess. Checked directly against `fastapi/project-structure.md`,
> `bulletproof-react/docs/{project-structure,project-standards,api-layer,error-handling}.md` — re-read in full
> for this file, not recycled from earlier chat summaries.

## 1. Repo Layout — one repo, not split

```
job-allocation-system-/
├── docs/
├── backend/            # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── api/{main.py, deps.py, routes/}
│   │   ├── core/{config.py, db.py, security.py}
│   │   ├── models.py, crud.py, alembic/
│   ├── tests/{api/routes/, crud/}
│   └── Dockerfile
├── frontend/           # React
│   └── src/{app, features, components, hooks, lib, stores, types, utils, testing}
├── src-tauri/
└── .github/workflows/
```

One repo → one branch-protection gate covering both sides (`DEPLOYMENT.md` §4), matches the single-team,
single-pilot scale. Splitting into separate repos would be infrastructure for a coordination problem
(multiple teams shipping independently) this project doesn't have.

## 2. Backend Structure

`fastapi/project-structure.md`'s layout, verbatim shape, with one correction to its default assumption named
explicitly: the template's `core/security.py` normally does password hashing + JWT *issuance* — **this
project's `core/security.py` only does JWT *verification*** (JWKS-based, `ARCHITECTURE.md` §4), since Supabase
Auth owns hashing/issuance entirely. Copying the template's security.py role uncritically would reintroduce
password handling this project deliberately never touches.

**The organizing rule, stated by the skill directly**: *"routes stay thin... business logic and query
construction live in `crud.py`, not scattered across route functions."* A route that queries the DB directly
instead of calling `crud.py` is the first thread that unravels this — treat it as a review-blocking issue, not
a style nit.

**`api/deps.py`**, per the skill's own mapping onto a schema shaped like this project's:
- `SessionDep` — DB session, `yield`-based (`fastapi/guide/tutorial/dependencies/dependencies-with-yield.md`).
- `CurrentProfile` — decodes the verified JWT, **re-fetches `is_active` live** (the deactivation-lag fix,
  `ARCHITECTURE.md` §4), sets `SET LOCAL app.current_tenant` for RLS (`ARCHITECTURE.md` §5). One dependency,
  reused everywhere — never re-implemented per route.
- `require_owner` — layers on top of `CurrentProfile` the same way the template layers
  `get_current_active_superuser` on `get_current_user`. Every Owner-only route imports this, never checks
  `role` inline.

**Migrations**: Alembic, one migration per schema change, never hand-edited after merge — `DATA_MODEL.md`'s
tables land as a sequence of migrations, not one giant initial file, so history stays reviewable.

**Testing — resolved 2026-09-05, this was still genuinely open.** `pytest` + FastAPI's `TestClient`
(confirmed directly against `fastapi/guide/tutorial/testing.md`) is the explicit standard, not just implied
by the `tests/` folder existing. The harder question — **how do the RLS-dependent tests actually run** — has
a real answer: **a real, disposable Postgres instance, not a mock.** RLS policies are enforced by Postgres
itself; there is no meaningful way to unit-test `BYPASSRLS`/tenant-isolation behavior against a mocked
session, since the thing under test *is* the database engine's own enforcement. Concretely: a plain
`postgres:17` service container in GitHub Actions (a built-in feature, no extra infra) that runs the actual
Alembic migrations — including the RLS policies and the `fastapi_app` role — before the test suite executes.
This is a local, disposable instance, never the live Supabase project — CI shouldn't depend on, rate-limit
against, or leave test data in production infrastructure. This is where the tenant-isolation and `BYPASSRLS`
tests (`ARCHITECTURE.md` §5) and the authorization-matrix suite (`API_SPEC.md` §4) actually execute, as
required status checks (`DEPLOYMENT.md` §4).

No hard coverage-percentage gate for Phase 1 — a coverage threshold enforced by a number invites tests
written to satisfy the number rather than to actually verify behavior, and this project doesn't have the
scale to need that guardrail yet. The real bar is the per-slice checklist in §5 below: every slice ships with
its negative-case tests, checked in review, not by a coverage script.

## 3. Frontend Structure

`bulletproof-react/docs/project-structure.md`'s layout, already the basis for `FRONTEND_ARCHITECTURE.md` §2 —
confirmed unchanged on a full re-read:

```
src/{app, assets, components, config, features, hooks, lib, stores, testing, types, utils}
```

Each `features/<name>/` holds only the subfolders it needs (`api`, `components`, `hooks`, `types`) — not all
of them by default, per the same source.

**Unidirectional flow, enforced by ESLint `import/no-restricted-paths`** (exact rule confirmed in the skill,
not paraphrased): `shared → features → app`; features cannot import each other; `app` can import `features`
but not the reverse. `features/billing` cannot reach into `features/tasks` even though a billing task is a
`tasks` row — they compose only at the route/app level (`FRONTEND_ARCHITECTURE.md` §2).

**API layer** (`bulletproof-react/docs/api-layer.md`, re-checked): one preconfigured client instance
(`lib/api-client.ts`), and every endpoint gets its own declaration file exporting three things together —
request/response types, a fetcher, and the TanStack Query hook built on it. One file per endpoint, traceable
directly to a row in `API_SPEC.md` §3.

**Error handling** (`bulletproof-react/docs/error-handling.md` — **not previously cited in any doc, checked
now**):
- An API-client interceptor handles cross-cutting response errors — 401 triggers logout, not a per-call
  try/catch repeated everywhere.
- **Multiple error boundaries, scoped per section, not one global boundary** — a crash in the task list
  shouldn't take down the notification bell next to it.
- **Error tracking — resolved 2026-09-05: Sentry, free Developer plan.** Checked directly (not assumed):
  5,000 errors/month, 1 user, free forever — comfortably covers a 10-40 user pilot's realistic error volume;
  the 1-user limit is fine while you're the one monitoring this, and is the named trigger to revisit once the
  firm itself needs its own visibility. Both backend (FastAPI SDK) and frontend (React SDK) report into the
  same project. This is also what satisfies ASVS 16.5.1 properly — the client-facing `problem+json` response
  stays generic (`API_SPEC.md` §1), but the real stack trace still needs to land *somewhere* for debugging;
  Sentry is that somewhere, not "logged nowhere."

**Conventions** (`bulletproof-react/docs/project-standards.md`, re-checked): absolute imports (`@/*`, already
in `FRONTEND_ARCHITECTURE.md` §10), kebab-case files enforced via `check-file` ESLint rules, Husky pre-commit
running lint+format — all confirmed against the skill's actual config examples, not just named in passing.

## 4. Build Order — the actual discipline against becoming a mess

**Rule: cross-cutting scaffolding once, then one full vertical slice at a time.** Never all models, then all
routes, then all tests as separate horizontal passes — that leaves five layers half-built simultaneously and
nothing reviewable until all of them finish. A vertical slice (one resource, top to bottom, tests included)
is mergeable on its own and matches the branch-protection gate already built (`DEPLOYMENT.md` §4).

1. **Phase 0 — Scaffolding.** Folder structure above, tooling configs (`ruff`/`pyright`, `eslint`/`tsc`,
   `uv`/`package.json` with lockfiles per `DEPLOYMENT.md` §10), the CI workflow file, empty `Dockerfile`.
   Nothing functional yet.
2. **Phase 1 — Backend core, built once.** `Settings(BaseSettings)`, DB session + RLS session-variable
   wiring, JWT verification, `CurrentProfile`, `require_owner`, the `problem+json` error handler, CORS
   (`API_SPEC.md` §1), the `fastapi_app` role + `firms`/`profiles` migration and provisioning trigger. Every
   later resource depends on this being right once.
3. **Phase 2 — First vertical slice: Employees.** Model → migration → `crud.py` → routes → tests — including
   the tenant-isolation and `BYPASSRLS` tests required by `ARCHITECTURE.md` §5, since this is the first slice
   touching multi-tenant data at all.
4. **Phase 3 — Remaining backend resources, one slice at a time**: job types → tasks → reviews/issues →
   notifications → audit log. Each fully done, tests included, before the next starts.
5. **Phase 4 — Frontend, same logic.** Scaffolding + auth (Tauri secure storage, `ARCHITECTURE.md` §4 /
   `FRONTEND_ARCHITECTURE.md` §6) first — nothing else works without login — then one feature slice per
   backend resource, same order as Phase 3.
6. **Phase 5 — Hardening pass.** Semgrep/CodeQL/Trivy wired into CI, Dockerfile non-root user
   (`DEPLOYMENT.md` §10), CSP (`tauri-official/chapters/security-capabilities.md`), the full
   authorization-matrix suite (`API_SPEC.md` §4) run across everything built so far, the error-tracking
   decision flagged in §3 above.
7. **Phase 6 — E2E** (WebdriverIO + `@wdio/tauri-service`, `FRONTEND_ARCHITECTURE.md` §9), once enough of the
   app exists to exercise a real flow end to end.

## 5. Per-Slice Checklist — applied every time, not just at the audit stage

Before a vertical slice is considered done, not after:
- Route calls `crud.py` only — no inline queries.
- Object-level check present on every `{id}`-scoped endpoint (`API_SPEC.md` §4) — a valid JWT proves *who*,
  not that they may touch *this* object.
- Workflow-state validated server-side for any status-changing endpoint (`API_SPEC.md` §1).
- The relevant OWASP cheat sheet + ASVS chapter checked for *this specific* endpoint/mechanism — not assumed
  covered by a prior similar-looking slice (per the standing session rule, now extended explicitly into code).
- Test exists for the slice, including the negative case (wrong firm, wrong role, wrong object) — not just
  the happy path.

---

Skills re-verified for this document, not recycled from earlier conversation: `fastapi/project-structure.md`,
`bulletproof-react/docs/project-structure.md`, `bulletproof-react/docs/project-standards.md`,
`bulletproof-react/docs/api-layer.md`, `bulletproof-react/docs/error-handling.md`.
