# CA Firm Practice Management Tool — Frontend Architecture

> Follows `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/DEPLOYMENT.md`, `docs/API_SPEC.md`. Searched `bulletproof-react` and `react-official` directly before writing each section below, per the standing verification rule, not from memory. `ARCHITECTURE.md` §7 already decided **React + TypeScript**; this document is everything below that choice — where code lives, which tool owns which kind of state, how forms/testing/tooling work. It does not re-litigate anything `ARCHITECTURE.md`, `API_SPEC.md`, or `DATA_MODEL.md` already settled.

## 1. Screen Inventory

Derived directly from the PRD, nothing speculative added — this is also the input the `design` skill needs for visual mockups, so it's written once here rather than re-derived later.

| Screen | PRD source | Role |
|---|---|---|
| Login | §5 | Both |
| Set New Password (forced, one-time — see below) | — (added 2026-09-02) | Both |
| Owner Dashboard (firm-wide task overview, workload counts, filterable All Tasks table — see below, **Awaiting Review and Issues Raised panels — see below**) | §2.3/§2.4/§2.5 | Owner |
| Create Task (a console screen, opened via a **+ New Task** button on the Dashboard) | §2.3 | Owner |
| Task Detail & Review (Approve / Reassign / Billing) | §2.6 | Owner |
| Billing Task Creation (assignee, deadline, description, amount, recipient) | §2.8 | Owner |
| Employee Management (list, deactivate) | §2.1 | Owner |
| Job Type Template Management | §1.1/§2.2 | Owner |
| Issue Resolution (clarify / adjust deadline / reassign) | §2.7 | Owner |
| My Tasks (own pending + reassigned work) | §3.2 | Employee |
| Task Detail & Submit (billing-type tasks: Mark Billed instead of Mark Completed — see below) | §3.3/§4.2 | Employee |
| Raise Issue | §3.3 | Employee |
| Notifications (both roles, own list per `API_SPEC.md` `GET /notifications`) | §2.5/§3.4 | Both |
| Change Password (self-service, any time — see below) | — (added 2026-09-02) | Both |

11 product screens plus Login, Set New Password, and Change Password. Matches `ARCHITECTURE.md` §7's "CRUD-dashboard-shaped" framing — no screen here needs anything beyond lists, forms, and detail views.

**Corrected 2026-09-02, same pattern as the earlier Task List merge — found while grounding the Employee loop before drawing it:** this table originally listed "Mark Billing Task Billed" as its own screen. Checked PRD §4.2 directly: *"billing task appears in that employee's normal task list → Employee marks it Billed (no review step)."* That's the same task list and the same task-opening flow as any other task — Task Detail & Submit — just a different terminal action button depending on `task_type`, not a second screen. Folded in above; screen count corrected 12 → 11 (product screens).

**Set New Password, added 2026-09-02:** exists because provisioning switched from an email-invite link to an admin-issued temporary password (`ARCHITECTURE.md` §4's provisioning section) — every newly provisioned account (first Owner and every employee alike) logs in once with a password someone else generated and handed them, and this screen is the one-time gate that replaces it before anything else in the app is reachable. Not optional UI polish: `API_SPEC.md`'s `POST /auth/set-new-password` is enforced server-side too — `CurrentProfile` rejects every other endpoint while `profiles.must_change_password` is still `true`, so this screen backs a real gate, not just a client-side redirect a user could skip by hitting the API directly.

**Change Password, added 2026-09-02:** the ongoing, self-service counterpart to Set New Password above — ASVS 5 6.2.2 (L1) expects users can change their password at will, not just under the forced first-login flow (`ARCHITECTURE.md` §4, decided in scope). Reachable from a persistent account/profile affordance both roles have, not gated by `must_change_password`. Same fields as Set New Password (current password + new password) and the same direct-to-Supabase call (`updateUser({ current_password, password })`) — no FastAPI endpoint, matching how login itself bypasses the backend.

**Corrected 2026-09-02, found while grounding the next design batch against the approved mockup:** this table originally listed a separate "Task List (firm-wide, filterable — including by employee)" screen. Checked the approved `Main.dc.html` mockup directly — its "All Tasks" section already is that screen: same Status/Employee filters, same columns, reachable without navigating anywhere else. There was never a second destination drawn or needed; listing it separately overcounted the screen inventory by one. Folded into the Dashboard row above. At real task volume the All Tasks section will need pagination or a scroll region — an implementation detail of that section, not a reason to reintroduce a separate screen.

**Revised twice during mockup review, landing back at a console screen:** Create Task briefly moved onto the Owner Dashboard as an inline composer, then moved back to its own screen (opened via a **+ New Task** button) once reviewed against the layout as a whole — the Dashboard reads better carrying its own job (overview, review queue, issues) than also carrying task creation. What survived from that detour: the composer *interaction* itself (single description box, job type/assignee/deadline as pills, not a stacked form) — that part tested well and stayed, it just lives on its own screen instead of inline. Same `POST /tasks` body either way, per §7.

**Also added during the same review, both checked against real backend facts before being drawn, not guessed:** the Dashboard's Awaiting Review and Issues Raised panels map directly to the `task_submitted`/`issue_raised` notification types `DATA_MODEL.md` §5 already defines — no new data, just a second, more direct view onto notifications that already exist. The employee filter on the task list required one real addition: `API_SPEC.md`'s `GET /tasks` had never documented its query parameters at all — added there (`?status=`, `?assigned_to=`, `?job_type_id=`, `?task_type=`), all against indexes `DATA_MODEL.md` §2 already has.

## 2. Project Structure

**Feature-based, per `bulletproof-react/docs/project-structure.md`** — checked directly, not assumed. `src/features/` holds one folder per resource this project already has a backend concept for, matching `API_SPEC.md`'s resource grouping exactly so a route in the frontend and an endpoint in the API share a name:

```
src/
├── app/            # routes, app.tsx, provider.tsx, router.tsx
├── components/     # shared components used across features
├── features/
│   ├── auth/       # login, session
│   ├── tasks/      # list, detail, review, create — the largest feature
│   ├── billing/    # billing task creation + mark-billed (task_type='billing' slice)
│   ├── employees/  # Owner-only management
│   ├── job-types/  # Owner-only management
│   ├── issues/     # raise + resolve
│   └── notifications/
├── hooks/          # shared hooks
├── lib/            # api-client, auth config — preconfigured, reused everywhere
├── stores/         # global client state (see §3)
├── types/          # shared TS types
└── utils/
```

Each feature folder holds only the subfolders it needs (`api`, `components`, `hooks`, `types`) — not all of them, per the same source.

**Deviation, recorded (2026-09-13, code-review finding, whole-Phase-4 sweep):** `issues/` and
`billing/` were never actually built as their own folders — raise/resolve-issue and mark-billed
code lives under `features/tasks/` instead. Not an oversight left unflagged until now: issue-raise
(`raise-issue-dialog.tsx`, `create-task-issue.ts`) and mark-billed (`mark-task-billed.ts`) are both
invoked directly from `task-detail-page.tsx`/`create-task-dialog.tsx`, and issue-resolution shares
`create-task-review.ts`'s single review endpoint (outcome=billing is the same call, not a second
one) — splitting either into its own feature folder would make `features/tasks/` import from
`features/issues/`/`features/billing/`, exactly what §2's own features-cannot-import-each-other
ESLint rule forbids. Kept under `features/tasks/` deliberately; this plan's original folder list
predates that rule actually being enforced.

**Unidirectional flow, enforced by ESLint** (`import/no-restricted-paths`, the exact rule in `project-structure.md`): `shared → features → app`, and **features cannot import each other**. Concretely: `features/billing` cannot reach into `features/tasks` even though a billing task is a `tasks` row with `task_type='billing'` — the two features compose only at the route/app level. This is the rule that actually keeps Owner-side and Employee-side code from tangling into each other as the app grows, not just a style preference.

## 3. State Management

`bulletproof-react/docs/state-management.md`'s five-category split, mapped onto this app's actual data — most of what this app has is **server cache state**, not client state, which shapes the tool choice below more than anything else:

| Category | This app's data | Tool |
|---|---|---|
| Server cache state | Task lists, task detail, employees, job types, issues, **notifications** | **TanStack Query** (react-query) — chosen over SWR/Apollo/RTK Query because `ARCHITECTURE.md` §8 already committed to REST + polling, and TanStack Query's `refetchInterval` is a direct, built-in fit for a 30–60s poll — no custom polling code needed (see §5) |
| Application state | Decoded JWT role (routing only, not a security decision — `ARCHITECTURE.md` §4 already says this), active modal/dialog state | React Context — this app's global state surface is small (one role flag, some UI toggles), so Redux/Zustand/Jotai would be unrequested weight for what it actually needs |
| Form state | Create Task, Review outcome, Billing Task Creation, Raise/Resolve Issue | React Hook Form + Zod (validation) — matches `API_SPEC.md`'s request bodies field-for-field, so the same Zod schema can validate client-side and double as the TS type for the API call |
| URL state | Task list filters (status, assignee, `?task_type=billing` — the exact query param `API_SPEC.md` §5 already specified for the consolidated billing view) | React Router's search params — no separate state needed, the URL *is* the filter state |
| Component state | Local form field focus, expand/collapse in a detail view | `useState`, per `react-official`'s `learn/state-a-components-memory.md` |

**Why TanStack Query over a manual `fetch`+`useEffect` polling loop:** `react-official/learn/you-might-not-need-an-effect.md` (checked directly) warns against exactly this pattern — fetching in an `Effect` for data a component needs to render is one of its named "you might not need an Effect" cases. TanStack Query owns the fetch, cache, and interval in one place instead of every screen re-implementing its own polling `Effect`.

## 4. API Layer

`bulletproof-react/docs/api-layer.md`'s pattern, checked directly: **one preconfigured API client instance** (`lib/api-client.ts`, an `axios` or `fetch` wrapper with the JWT attached per `ARCHITECTURE.md` §4 step 3) plus **per-feature typed request declarations** — each one exports its types, a fetcher, and a TanStack Query hook built on the fetcher. Example shape for one endpoint (`features/tasks/api/submit-task.ts`): request/response types generated from `API_SPEC.md`'s documented shape, a fetcher calling `POST /tasks/{id}/submit`, and a `useSubmitTask` mutation hook. This keeps every endpoint this project's `API_SPEC.md` already documents traceable to exactly one file on the frontend side.

**Idempotency headers** (`API_SPEC.md` §1/§3 — `Idempotency-Key` on task creation, submit, review, mark-billed, issue resolution): `apiRequest()` (the single client instance) attaches whatever key it's given, in one place — but it does not generate that key itself.

**Corrected 2026-09-11, building the employees slice's `reset-password` call — its first real caller.** Originally written as "generated client-side per request (a UUID) and attached in the API client wrapper" — checked directly against `rest-api-guidelines` Rule 230 while building that call and found this was wrong: the rule requires the *same* key to survive every retry of one logical operation, so the server's dedup cache can match a retried request against the original. Generating a fresh `crypto.randomUUID()` *inside* `apiRequest()` on every HTTP call (what `lib/api-client.ts` originally did) means a retry never matches — the mechanism silently didn't do what its own name promised. Fixed: `apiRequest()`'s `idempotencyKey` option takes a caller-supplied string; the **calling mutation hook or component owns the key's lifetime** — generated once per logical attempt (e.g. `useState(() => crypto.randomUUID())`, reset only when that attempt is deliberately abandoned, such as closing a confirmation dialog), reused across every retry of that same attempt. `features/employees/components/reset-password-dialog.tsx` is the reference implementation — every later `Idempotency-Key` caller (tasks, issues) should follow the same ownership split, not regenerate the key per HTTP call.

## 5. Notification Polling — concrete mechanism

`ARCHITECTURE.md` §8 committed to polling but left the frontend mechanism unspecified. Closing that now: `useNotifications` (a TanStack Query hook, `features/notifications/api/get-notifications.ts`) with `refetchInterval: 30_000` to `60_000`, `refetchIntervalInBackground: false` (Tauri window is the only "background" case that matters here — no need to poll while the window isn't focused). No websocket, no manual `setInterval`, no custom polling `Effect` — the library owns it entirely, per §3's TanStack Query decision above.

## 6. Auth on the Frontend

**Corrected 2026-09-03 — this contradicted two other documents, not just under-specified.** Originally
written as "Supabase's own SDK's job, not this project's... nothing here should override that default." That
default is the Supabase JS SDK's own browser storage (effectively the webview's `localStorage` in a Tauri
context) — but `ARCHITECTURE.md` §4 step 3 already says the token is stored in **"Tauri secure storage,"**
and `tauri-official/chapters/security-capabilities.md` names this project's capability surface explicitly as
*"the store/stronghold plugin for token storage."* Both predate this section and were never reconciled with
it — leaving §6 as written would have silently downgraded an already-decided design the moment someone
actually wired up the Supabase client with its defaults left alone.

**Fix:** the Supabase client is created with a **custom `storage` adapter**, not left on its default —
Supabase's own documented pattern for this (`supabase/auth/sessions.md`'s `customStorageObject`:
`getItem`/`setItem`/`removeItem`, normally shown there for server-side cookie storage, generalizes directly
to any custom backend) backed by the Tauri store/stronghold plugin instead of a cookie jar. `bulletproof-react/
docs/security.md`'s localStorage-vs-cookie discussion still doesn't apply here (neither option is what's
actually used), but "nothing to do here" was the wrong conclusion — there's exactly one thing to do, and it's
what the other two documents already committed to.

**RBAC for UI display only — checked against `security.md`'s RBAC/PBAC section, and explicitly not a substitute for the server-side check.** The Owner-only "Billing" review outcome, employee management, and job-type management screens are conditionally rendered based on the decoded `role` claim. This is UX only: `API_SPEC.md` §4 already requires every Owner-gated endpoint to independently authorize server-side regardless of what the frontend shows or hides — both layers are required, hiding a button is not a security control.

**Route-level role gating**: `app/router.tsx` splits Owner routes and Employee routes at the router level (not per-component checks scattered through the tree) — an Employee hitting an Owner route by URL redirects, same principle as `API_SPEC.md`'s `404`-not-`403` object-access pattern applied one layer up, at the route rather than the resource.

**Added 2026-09-03, fixed 2026-09-04 — was a coverage gap in the skill itself, now closed.**
`owasp-asvs-5/chapters/v3-web-frontend-security.md` 3.4.3 (Level 2) recommends a `Content-Security-Policy`
limiting execution of untrusted content; `tauri-official`'s security-capabilities chapter had no CSP coverage
at all when this was first flagged. Fetched Tauri's own CSP docs directly and added a full CSP section to
that skill (off-by-default behavior, config shape, auto-injected nonces/hashes for bundled code) plus a
starting policy scoped to this project's actual external origins (FastAPI API, Supabase Auth, Google Fonts —
no CDN scripts, no `'unsafe-inline'` on `script-src`). Still low urgency in the sense that no screen in §1
renders untrusted content as HTML, but the value to set in `tauri.conf.json` is no longer undocumented — see
`tauri-official/chapters/security-capabilities.md`'s CSP section when that config file is actually written.

## 7. Forms

React Hook Form + Zod, per `bulletproof-react/docs/state-management.md`'s Form State section. Applied to every mutating screen in §1's inventory: Create Task, Task Review, Billing Task Creation, Raise Issue, Resolve Issue. Each form's Zod schema mirrors its `API_SPEC.md` request body directly — client-side validation and the TypeScript request type come from the same schema, not maintained twice.

## 8. Component Library & Styling — resolved 2026-09-03

Deferred until mockups existed (below is the original reasoning for that sequencing); all 15 screens are now
built, so the decision is made against what they actually need, not guessed at.

**Decision: Tailwind CSS + Radix UI primitives, using the shadcn/ui pattern — copied into the repo as owned
code, not installed as a styled package.**

Checked against `bulletproof-react/docs/components-and-styling.md` (the only skill covering this):

- **Fully-styled libraries (Chakra/AntD/MUI/Mantine) are ruled out by the mockups themselves.** Every screen
  already has a specific, deliberate visual identity — the "Royal Ledger" palette (`oklch()` colors), a
  three-font pairing (Newsreader serif for headings, Public Sans for body, IBM Plex Mono for
  numbers/labels), 1px hairline borders, 2px border-radius, tabular-nums throughout. The skill's own text
  names this exact conflict for AntD ("might be a bit difficult to change the styles in order to adapt them
  to a custom design") — true of all four fully-styled options here, not just AntD. Adapting a library's
  opinionated defaults (Material Design, Ant Design's rounded cards) to match a design that already exists
  costs more than building from unstyled primitives.
- **So: headless component library for behavior/accessibility (no visual opinion to fight), Tailwind for the
  actual look.** Of the headless options listed (Radix UI, Base UI, Headless UI, react-aria, Ark UI,
  Reakit), **Radix UI** — most widely adopted, covers every primitive the mockups actually use: `Dialog` (Create
  Employee, Change Password — both drawn as modals), `DropdownMenu` (the notification bell on Dashboard/My
  Tasks, the avatar menu), `Select` (job-type picker in Create Task).
- **Tailwind over CSS Modules/vanilla-extract/styled-components/emotion** because the mockups' exact tokens
  (the `oklch()` palette, font stack, spacing/radius scale) drop directly into `tailwind.config`'s theme
  extension rather than needing to be reverse-engineered into a different system later — and it's the
  styling solution the shadcn/ui pattern below is built around.
- **Concretely: the shadcn/ui pattern, not the shadcn package.** Copy Radix-based component source into
  `components/ui/` (Dialog, DropdownMenu, Select, Button, etc.), then restyle each with Tailwind classes
  matching the Royal Ledger tokens already fixed by the mockups. This gets accessible, correctly-behaved
  primitives (focus trapping, keyboard nav, ARIA) without hand-building them — `bulletproof-react`'s own
  "abstract shared components into a component library" guidance (§ above) applied to code you own outright,
  not a dependency whose defaults would need fighting.

**Original sequencing reasoning, preserved:** picking a library before any screen had an actual visual
design risked locking a component shape the mockups would then have to work around — visual mockups came
first (the `design` skill), the component-library choice made against what they actually needed, not guessed
at up front.

## 9. Testing

`bulletproof-react/docs/testing.md`'s three-tier strategy, checked directly — this is what closes the frontend-testing gap flagged earlier in this project's planning:

- **Unit/Integration — Vitest + Testing Library.** Testing Library's stated philosophy (test what renders, not internal state) fits this app well: if the state-management tool in §3 ever changes, the tests shouldn't need to.
- **E2E — corrected 2026-09-03, checked against the new `tauri-official` skill directly: WebdriverIO + `@wdio/tauri-service`, not Playwright.** Playwright isn't officially supported by Tauri at all — its CDP-based automation only works through WebView2 (Windows); Tauri uses WKWebView on macOS and WebKitGTK on Linux, neither of which speaks CDP. `@wdio/tauri-service` works on Windows, Linux, and macOS via its embedded WebDriver provider, and adds Tauri-specific hooks (`browser.tauri.execute()`, IPC/command mocking, frontend+backend log capture) a generic WebDriver setup wouldn't have. Headless-capable in CI (ties into `DEPLOYMENT.md` §4's lint/typecheck gate — this would be a new step there, not yet added to that document).
- **API mocking — MSW** for HTTP calls to FastAPI, developing frontend screens against `API_SPEC.md`'s documented shapes before the real endpoints exist. Separately, **`@tauri-apps/api/mocks`** (`tauri-official/chapters/testing.md`) covers mocking the Tauri-side `invoke()`/event layer itself in unit tests — a different mocking surface than MSW, needed only for tests that touch Tauri commands directly (e.g. the secure-token-storage wrapper in §6), not for ordinary API-calling components.

**Resolved 2026-09-03.** The original "Playwright vs. `tauri-driver`" framing was itself the wrong question — checked directly against Tauri's own docs (now the `tauri-official` skill, built specifically to close this gap): the current official recommendation is WebdriverIO, which neither original option was.

**Not yet built (2026-09-09), named so neither gets rediscovered from scratch later:**
- **`supabase-client.ts`'s storage adapter has no test.** Would need `@tauri-apps/api/mocks`
  (`mockIPC`) added as a dev dependency first — not installed yet — to intercept the `invoke()`
  calls `LazyStore`'s `get`/`set`/`save`/`delete` make under the hood, since jsdom (the Unit/
  Integration tier's environment) has no real Tauri runtime to talk to. Deliberately deprioritized,
  not forgotten: even with the mock installed, such a test only proves the JS-side plumbing is
  wired correctly (right IPC command, right args) — it can't reach the actual security property
  this file exists for, since the DPAPI encryption (`src-tauri/src/store_crypto.rs`) runs entirely
  in Rust, invisible to a JS-side IPC mock. That property still needs the manual/E2E check the
  Verification section of the Phase 4 Step 1 plan already named (log in, restart the app, confirm
  the session survives via real Windows DPAPI) — a JS mock test would add coverage without
  touching the actual risk.
- **The E2E tier — installed 2026-09-15 (Phase 6 Step 1), CI-green and confirmed.**
  `@wdio/tauri-service` + `@wdio/cli`/`@wdio/local-runner`/`@wdio/mocha-framework`/`@wdio/globals`
  (frontend devDependencies) and `tauri-plugin-wdio-webdriver` (Rust, embedded WebDriver provider,
  cross-platform) now exist, plus `frontend/wdio.conf.ts` and one harness-proving spec,
  `frontend/e2e/specs/login-flow.spec.ts` — driving the real packaged app through a real login
  against `.github/workflows/ci.yml`'s existing real local Supabase + FastAPI `e2e` job stack, not
  MSW. Deliberately scoped to proving the harness only (see `docs/CODE_REVIEW_FINDINGS_2026-09-14.md`
  finding #12, the on-record motivating case for this tier, and the plan's own "explicit checkpoint" —
  further business-logic E2E coverage is a separate next slice, not bundled into this one).
  Getting the boot sequence green under headless Linux CI (WebKitGTK + Xvfb + Tauri's WebDriver
  bridge) took six distinct fixes, most notably a CSP `connect-src` that didn't allowlist the CI
  job's local Supabase origin — masked by `use-login.ts`'s deliberate generic "Invalid email or
  password" message (§ below on that hook), which made a network-layer block look identical to a
  credentials error until the actual page source was inspected. A negative control (2026-09-15) —
  deliberately wrong credentials pushed to this same CI job — confirmed the harness fails red for a
  real regression (`h1=Dashboard` timeout, not a hang or infra flake) before this was trusted.
  **Security note**: `tauri-plugin-wdio-webdriver` stands up a live, remotely-drivable WebDriver
  server — per its own README ("never include it in production builds") and owasp-tcasvs V2.1.3
  ("production builds exclude... test utilities"), it's an optional Cargo dependency behind a new
  `e2e-testing` feature (`src-tauri/Cargo.toml`), never enabled by the real release build command,
  with its capability/permission (`wdio-webdriver:default`) inlined only in `tauri.e2e.conf.json` —
  confirmed empirically that a standalone file under `capabilities/` would have broken the default
  build's own permission validation regardless of `tauri.conf.json`'s capabilities allowlist, so it
  is deliberately not a separate file there.

## 10. Tooling & Linting

`bulletproof-react/docs/project-standards.md`, checked directly: ESLint + Prettier + TypeScript (already the plan per `DEPLOYMENT.md` §4's `eslint`+`tsc` CI gate), plus two additions that document didn't yet specify:
- **Absolute imports** (`@/*` path alias) — avoids `../../../features/tasks` chains as the feature folders in §2 grow.
- **Husky pre-commit hooks** running lint + format, catching issues before they reach the CI gate rather than only at it.

Kebab-case file naming, enforced via the same `check-file` ESLint plugin the source documents — matches this project's existing naming convention in the backend docs (`snake_case` DB columns, `kebab-case` here is the frontend-file-specific convention, not a conflict).

## 11. Open Questions Carried Forward

- ~~**Component library / styling**~~ — **Decided 2026-09-03: Tailwind + Radix UI, shadcn/ui pattern** (see §8).
- ~~**Playwright vs. `tauri-driver` for E2E**~~ — **Decided 2026-09-03: WebdriverIO + `@wdio/tauri-service`** (see §9, `tauri-official/chapters/testing.md`). Neither original option was actually Tauri's recommendation.
- ~~**Employee performance metric**~~ — **corrected 2026-09-03, this line was stale**: `ARCHITECTURE.md` §13 already decided this (out of scope for Phase 1, revisit in Phase 2) before this section was last touched, and the two docs had drifted out of sync. No frontend screen here was ever blocked by it regardless — whichever definition eventually lands, it's a data column and a dashboard tile, not a structural decision.
- **Form error messages aren't linked to their inputs for assistive tech — deferred to Phase 2.**
  Found 2026-09-15 while fixing code-review finding #17 (billing fields validate but never render
  their error): every `errors.X && <p>...</p>` error render across every form in this codebase
  (`owner-task-review-page.tsx`, `issue-resolution-page.tsx`, and by the same shape presumably every
  other form) is a plain, unlinked `<p>` — no `aria-invalid` on the input, no `aria-describedby`
  pointing at the error's `id`, no `role="alert"` on the error itself. `frontend-a11y` skill (its own
  Before-Submitting checklist) requires all three. Impact: a sighted user sees the error fine; a
  screen-reader user gets no signal an error appeared at all. Not fixed as part of #17 — retrofitting
  only the 4 billing fields would leave the same file inconsistent (some inputs wired, most not), and
  no code-review finding named the gap itself, only its two symptoms. Revisit in Phase 2 as one pass
  across every form component, not per-field patches.

---

Reference patterns pulled from this project's own skill library, searched before writing, not from memory: `bulletproof-react` (project structure, state-management categories, API layer, forms, security/RBAC-for-UI, testing, project standards), `react-official` (`you-might-not-need-an-effect.md` for the polling-mechanism reasoning), `ARCHITECTURE.md` §4/§7/§8, `API_SPEC.md` (endpoint/resource naming, idempotency, query-param billing view, object-access pattern).
