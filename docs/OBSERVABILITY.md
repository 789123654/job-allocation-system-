# Observability — what is logged, what is watched, and who finds out

Phase 1 of the observability work, built 2026-09-19. It exists because the k6 PATCH run on
2026-09-18 went from healthy to `QueuePool limit ... reached` (15% of requests failed, p95 60 s)
with **nothing warning beforehand**. The goal is to see a failure coming — per tenant, per
dependency — before a firm does.

Decisions that predate this file (Railway stdout logs, Sentry, UptimeRobot; what is deliberately
*not* built) are in `DEPLOYMENT.md` §6, revised 2026-09-19. This file is the operational side: the
log inventory (ASVS 16.1.1), the alert matrix, the runbooks, and an honest list of what is still
missing. Rules in the style of `SECURITY_AUDIT_CHECKLIST.md` apply: nothing here is a claim that a
control works unless a test or a captured output says so, and where something is a plan it says so.

## 1. What exists (Phase 1)

| # | Piece | Where | Status |
|---|---|---|---|
| 1 | Structured, tenant-tagged JSON request logs | `app/core/request_logging.py`, `logging_setup.py`, `request_context.py` | built, tested |
| 2 | `/ready` — a health check that actually checks the database | `app/core/health.py`, `main.py` | built, tested |
| 3 | DB pool + thread-pool saturation signals | `app/core/db.py` (pool warning), `runtime_stats.py` (fields on every request line) | built, tested |
| 4 | Sentry tenant/release/environment tags — backend and desktop client — and what Sentry may receive | `app/core/sentry_config.py`, `frontend/src/lib/sentry-context.ts` | built, tested |
| 5 | Scheduled read-only database health check, least-privilege role | `backend/ops/db_check.py`, migration `66bc34819e6a`, `.github/workflows/ops-db-check.yml` | built, tested locally; **not scheduled, role not on the live database** |
| 6 | Tenant-isolation canary | `backend/ops/canary.py`, `.github/workflows/isolation-canary.yml` | built, tested against the real API + real Postgres; **not scheduled, no deployment to probe** |
| — | Log hygiene found while verifying the above: SQL parameters and Postgres-echoed values, Sentry request bodies / frame variables / bearer token | `app/core/redaction.py`, `db.py` (`hide_parameters`), `sentry_config.py` | fixed, tested (§3) |

## 2. Log inventory (ASVS 16.1.1)

ASVS 5 §16.1.1 asks for an inventory at every layer: what is logged, format, location, use, access
control, retention. Retention numbers were read from the vendors' own docs on 2026-09-19.

| Layer | What | Format | Where it goes | Used for | Who can read it | Retention |
|---|---|---|---|---|---|---|
| API request log (`app.access`) | one line per request: `method`, route **template**, `status`, `duration_ms`, `pool_checked_out/capacity`, `threadpool_borrowed/total`, plus `request_id`, `tenant_id`, `actor_id`, `actor_role`, UTC `ts` | one JSON object per line, stdout | Railway's log store | latency/error investigation by tenant; correlating a report to one request | Railway project members | 7 days on Trial/Hobby, 30 on Pro (Railway docs) |
| API app logs (`app.auth`, `app.pool`, `app.health`, `app`, `crud`, `employees`) | auth failures (the JWT library's reason, never the token), pool ≥70% warning, readiness probe failure (exception **class** only), unhandled-exception traceback (`exc`, redacted), Supabase admin failures (class, HTTP status and Supabase error code only) | same JSON, same fields | Railway | leading indicators, crash diagnosis | same | same |
| `access_denials` table | same-tenant authorization denials (durable, tenant-scoped) | Postgres rows under RLS | Supabase Postgres | audit; not for real-time | the firm's owner via the app; DB admins | permanent (`DATA_MODEL.md`) |
| `audit_log` table | admin actions | Postgres rows under RLS | Supabase Postgres | audit | as above | permanent |
| Sentry (backend) | unhandled exceptions + traces; tags `tenant_id`, `release`, `environment` | Sentry events | Sentry (third party) | crash triage, performance | Sentry project members (1 seat on the free plan) | 30-day lookback on the free Developer plan (Sentry pricing page) |
| Sentry (desktop client) | render errors + traces; tags `tenant_id`, `release`, `environment`; scrubbed breadcrumbs | Sentry events | Sentry | crash triage | same | same |
| GitHub Actions run logs | `db_check` aggregates (counts, query ids, table names) and `canary` verdicts (check ids) — never SQL text, tokens, tenant ids or row data | plain text | GitHub | scheduled-check results | repo collaborators | 90 days default (GitHub docs) |
| Tauri client, local | none. `tauri_plugin_log` is registered only when `cfg!(debug_assertions)` (`src-tauri/src/lib.rs`), so a release build writes no local log file | — | — | — | — | — |
| Supabase platform (Auth, Postgres, API logs) | platform-managed | — | Supabase dashboard | Auth events, DB errors | Supabase org members | **not verified here** — check the plan's retention at go-live |
| Cloudflare edge | platform-managed | — | Cloudflare dashboard | edge/WAF events | Cloudflare account | **not verified here** — free-plan analytics are limited; check at go-live |

Log lines never contain (and tests assert it): tokens, request or response bodies, query strings,
raw request paths, emails, names, or SQL parameter values. Only opaque UUIDs identify a tenant or
actor. The list of fields is a **structural allowlist** (`ALLOWED_EXTRA_FIELDS` in `logging_setup.py`):
a new field cannot appear without a code change and a test. Control characters are escaped by
`json.dumps`, so a hostile header or path cannot forge or split a line (ASVS 16.4.1).

Access logs record `/health` and `/ready` requests too, on purpose: the Logging Cheat Sheet says
never to exclude events from "known" callers such as uptime monitors.

## 3. What may leave the process (verified, not assumed)

Six leaks were found by looking at real output rather than trusting defaults. Each has a test that
fails without its fix (`SECURITY_AUDIT_CHECKLIST.md`, Observability Phase 1 entry).

1. **SQLAlchemy appended `[parameters: {...}]` to every failed statement's message.** Any failed
   INSERT/UPDATE would have put a firm's task title/description into Railway and Sentry.
   `create_engine(..., hide_parameters=True)` (SQLAlchemy 2.0 engines docs).
2. **PostgreSQL's own error text echoes the value** — `invalid input syntax for type uuid: "<value>"`,
   `DETAIL: Key (name)=(<value>) already exists.`, and for NOT NULL/CHECK failures
   `DETAIL: Failing row contains (<the whole row>)`. `app/core/redaction.py` removes these from the
   JSON log line (`message`, `exc`) and from Sentry events, including chained causes, ExceptionGroup
   members and SQLAlchemy-wrapped errors (the `[SQL: …]` statement and the Background line are kept;
   `[parameters: …]` is replaced). It is a second layer, not permission to log data, and it has
   three stated properties:
   - **It fails closed.** If the redactor itself raises, or is handed something that is not text, the
     output is `[exception text withheld: redaction failed]`, never the raw text (ASVS 16.5.3).
   - **Its cost is bounded.** Input is cut at 64 KB and the work is linear (ASVS 1.3.12). The first
     version was quadratic (16 KB took 17 s), found by an independent review and now covered by a
     scaling test.
   - **It has one known limit.** It works on text, and text cannot tell a client value that
     reproduces a *whole* genuine terminator (a chain marker, a blank line and a `Traceback` line)
     from the real one, so such a value can end redaction early and the rest of it leaks. It is
     recorded as a strict expected-failure test
     (`test_a_value_that_forges_a_complete_chain_marker_is_the_known_limit`), so it cannot be
     forgotten or quietly changed. The complete fix is to render exceptions from the exception
     object instead of from text; not done yet.
   - **It recognises the shapes this app can produce, not every Postgres message.** Labels
     (`DETAIL`, `CONTEXT`, `HINT`, `QUERY`, `LINE n`, `[parameters: …]`), the `Class: message "<v>"`
     head, and a list of Postgres message templates for label-less messages (`invalid input syntax
     for type …`, `time zone "<v>" not recognized`, constraint violations). Translated
     (`lc_messages`) messages and other echo shapes such as `syntax error at or near` are not
     covered: Supabase runs in English and this app never builds SQL text from a client value. A
     message an application author writes (`RAISE EXCEPTION 'bad %', v` in PL/pgSQL) is not a
     Postgres template and is not recognised; the app's own SQL has no such call. The `QUERY` label
     is defence in depth: every real Postgres 17 shape provoked puts it under a `LINE n:` line whose
     skip already covers it (a mutation run showed no real-shape test needed it), and a hand-built
     test pins that it works alone.
   - **The ExceptionGroup layout is read from the text's own first line, never from a substring.**
     An independent review forged the layout with two lines inside a value and leaked the
     neighbouring columns; a value can never be the first line. A group that follows a chain is not
     recognised, so it is over-redacted, never under-redacted.
3. **The Sentry Python SDK's defaults send more than `send_default_pii` controls.** Captured from a
   real event (sentry-sdk 2.68.1, project's exact settings): the request body was in
   `request.data`, and every stack frame's local variables were attached — including the ASGI
   `scope`/`request`, i.e. the raw `Authorization: Bearer <JWT>` header, although
   `request.headers.authorization` itself read `[Filtered]`. Fixed with `include_local_variables=False`
   and `max_request_body_size="never"` (Sentry options docs) plus the `before_send` scrubber.
   **Cost, stated:** a Sentry event no longer has a variable snapshot or the failing request body; to
   reproduce, use `request_id` + route + `tenant_id` from the JSON logs. Stack trace, source
   context, tags, release and environment are unchanged.
4. **Supabase Auth errors can echo the email address** being created (`Email address "x@y" is
   invalid`). The two places that logged that text (`POST /employees`, `POST
   /employees/{id}/reset-password`) now log `describe_auth_error(exc)`: the class, the HTTP status
   and Supabase's own error code, and only when the code is one the library knows. A structural test
   (`test_no_logger_call_in_the_app_passes_a_bare_exception`) fails if any logger call in `app/`
   passes an exception object, `str()`/`repr()`/`ascii()`/`format()` of one, its `.args`, or an
   f-string or `%` expression containing one, unless it is on a short allowlist with a written
   reason (today only `app/api/deps.py`, whose JWT library messages never contain the token). The
   detector is itself tested against snippets that must and must not be flagged.
5. **uvicorn printed a second, raw traceback, and its own access line was back on.** Found by running
   the real app under real uvicorn (an earlier test never started uvicorn, so it passed while the
   claim was false). uvicorn applies its own logging config when the server starts, after
   `app.main` was imported: that re-enables `uvicorn.access` (raw path and query string, ASVS
   14.2.1) and gives `uvicorn`/`uvicorn.error` a private stderr handler with `propagate=False`.
   Starlette re-raises an unhandled exception after the app's 500 handler, so uvicorn logged the
   whole traceback (with the client's value) unredacted. Fix: `configure_logging()` runs again in the
   app's `lifespan` (FastAPI events docs), which runs after uvicorn's config; it drops those handlers
   and re-disables the access logger. **Stated consequence:** every unhandled exception now appears
   twice, once from the app and once as `uvicorn.error`, both redacted (probe: 0 raw values, 2
   redacted lines). uvicorn's first two startup lines ("Started server process", "Waiting for
   application startup") are printed before the lifespan and stay in uvicorn's plain format; they
   carry no request data. `test_uvicorn_logging.py` starts a real uvicorn subprocess to prove it.
6. **A malformed log call made the stdlib print the raw record.** `Handler.handleError` writes
   `Message:` and `Arguments:` (the raw values) to stderr when formatting fails (a programmer's
   placeholder mismatch is enough). The app's handler overrides it and writes one fixed JSON note
   (the failing logger and the exception class, nothing else).

The desktop client: default click breadcrumbs describe an element by its `title`, `aria-label`,
`alt` and `name` values (read from the installed `@sentry/core`), and this app renders task
descriptions in `<td title=…>`. `beforeBreadcrumb` therefore **fails closed**: every `ui.*`
breadcrumb keeps its category and timestamp but its message is replaced by a fixed string and its
`data` is removed, and `console` breadcrumbs are dropped (the category is compared case-insensitively).
It does not try to recognise attribute values, because a regex over client text can always be
walked around (the first version was, by an attribute value containing a double quote). **Cost, stated:** a Sentry
event no longer says *which* button or cell was clicked, only that a UI click happened. The tenant tag
is validated as a UUID before it can be sent and is cleared on logout
(single choke point in `session-store.tsx`). Browser tracing propagates `sentry-trace`/`baggage`
only to the same origin by default (Sentry docs), so the API's CORS `allow_headers` needs no change;
if `tracePropagationTargets` is ever widened to the API, add both headers there first.

## 4. Health: `/health` vs `/ready`

- `/health` — liveness. Always 200 if the process is up. It stays green while Postgres is down, so
  an uptime monitor pointed at it tells you nothing about the database.
- `/ready` — readiness. `SELECT 1` through the real pool. 200 `{"status":"ok"}` or 503
  `{"status":"unavailable"}`; nothing else is ever returned (no host, pool numbers or exception
  text — ASVS 13.4.5, 16.5.1). Fails closed on any error (ASVS 16.5.3). Bounded work: result cached 5 s,
  at most one probe in flight, 2 s timeout, on its own daemon thread (so a hung database cannot pile
  up blocked worker threads), and a saturated pool is reported at once instead of queueing.
  Unauthenticated by necessity; intentionally exempt in `tests/api/test_schema_fuzz.py` alongside `/health`.

**Point UptimeRobot at `/ready`, not `/health`** (DEPLOYMENT.md §6 amended).

## 5. Alert matrix — which signals have someone watching

"Closes the loop" means a human is notified without anyone having to look. Be honest about the
column: a log line nobody reads is not an alert.

| Signal | Source | Threshold | Notification | Closes the loop today? |
|---|---|---|---|---|
| API or database unreachable | UptimeRobot → `/ready` | non-200 (5-min interval, free tier per `DEPLOYMENT.md` §6) | email | **Only once a deployment exists and the monitor is created** |
| Connection pool saturated | `/ready` fast-fail (503) | pool fully checked out | as above | as above |
| Unhandled 500s | Sentry (backend) | any new issue | Sentry issue-alert email | **Only once `SENTRY_DSN` is set and an alert rule exists**; free plan quota: 5,000 errors/month |
| Desktop client render errors | Sentry (client) | any new issue | as above | as above; needs `VITE_SENTRY_DSN` |
| Pool ≥ 70% used (leading indicator) | `app.pool` warning, ≤ 1 per 30 s | `DB_POOL_WARN_RATIO` (0.7) | **none** — a log line in Railway | **NO** — Railway has no log drain (docs); alerting on it needs a forwarder (Vector/Fluent Bit) or a Sentry log integration. Open. |
| DB connections ≥ 70% of `max_connections`, idle-in-transaction > 60 s, active > 30 s, lock wait > 10 s, slow statements (> 500 ms mean, ≥ 50 calls), dead tuples > 20% and > 10k, table growth vs limits | `ops/db_check.py`, hourly | see `Thresholds` in the file — **placeholders sized for 2,000 firms, not measured** | a failed GitHub Actions run → email to whoever last edited the cron line | **Only once enabled** (repo variable `OPS_MONITORING_ENABLED=true`, role has a password, environment secret set). Fails closed: unreachable DB or refused query is a failure. |
| Tenant isolation break, tampered token accepted, employee reaches owner-only route | `ops/canary.py`, every 30 min | any violation, any error, or fewer probes than expected | failed run → email | **Only once enabled** and synthetic firms exist. Treat any failure as an incident, not flakiness. |
| Auth-failure or 4xx spike per tenant | access logs (`status`, `tenant_id`) | — | **none** | **NO.** Query by hand in Railway (`@status:401`, `@tenant_id:<uuid>`; JSON attribute filters are documented). |
| Logging itself stopped | — | — | **none** | **NO.** The Logging Cheat Sheet asks for this; the uptime pings and the canary produce access lines at least every 30 min, so a gap is *detectable*, but nothing checks for it. |
| Sentry quota exhausted | Sentry | 5,000 errors / 5M spans per month | Sentry email | events are dropped after that |
| Logs dropped by Railway's rate limit | — | 500 lines/s per replica (Railway docs) | none | one line per request; the k6 300-VU run averaged ~140 req/s, so ~3.5× margin |

GitHub notes that verify the two scheduled jobs (GitHub docs, 2026-09-19): `schedule` runs only from
the default branch; it can be delayed at the start of every hour (hence `:07/:37` and `:17`); the
failure notice goes to whoever last modified the cron syntax; scheduled workflows in a **public**
repo are disabled after 60 days of inactivity.

## 6. Baselines (from real runs, quoted not remembered)

k6 in GitHub Actions against the app + a disposable Postgres container on the same runner (so
**not** the production network shape — no hop to Supabase). Use them as relative baselines only.

| Run | Load | Result |
|---|---|---|
| 2026-09-09 (`RESULTS.md`) | 50 VUs | avg 7.21 ms, p95 15.23 ms, 0% failed |
| 2026-09-18, run 35342907608 | 300 VUs, 200 firms × 10 employees, GET + isolation probes | 140 req/s; avg 55.2 ms, median 36.2 ms, p90 129 ms, **p95 161 ms**, max 732 ms; 0% failed; 42,975 checks, 100% pass |
| 2026-09-18, run 35345082189 | 300 VUs, PATCH mix | 37.5 req/s; **15.47% failed, p95 60 s**; `QueuePool limit of size 5 overflow 10 reached` |

Working SLO candidates for the pilot (to be tuned, not promises): p95 < 500 ms for reads and < 1 s
for writes at expected load; `/ready` 99.5%; zero isolation violations (canary).

## 7. Capacity: pool size vs Postgres `max_connections`

- Live project: `max_connections = 60` (read 2026-09-19); `pg_stat_statements` 1.11 is installed and
  preloaded, so `db_check`'s slow-statement check works there.
- Per API process the pool is `DB_POOL_SIZE + DB_MAX_OVERFLOW` (defaults 5 + 10 = 15).
  Supabase's connection-management guide: commit at most **80%** of `max_connections` to app pools
  (40% if you lean heavily on the PostgREST API), leaving room for Auth and other services. 80% of
  60 is 48 across *every* client — API workers, `ops_monitor` (limit 2), dashboards, migrations.
- So: 1 process ≈ 15 (25%), 2 ≈ 30 (50%), 3 ≈ 45 (75%). The shared pooler is in **session** mode
  (`DEPLOYMENT.md` §2; port 5432 per Supabase's docs), so each pooled client connection holds a
  server connection.
- **The values and the worker count are still a decision** (owner: you, at deployment). The
  2026-09-18 PATCH failure shows 15 connections is not enough for ~300 concurrent writers on one
  process; that is a load the pilot (2–4 firms, ~30 users) is nowhere near, but scaling toward
  hundreds of firms needs either a bigger compute tier (higher `max_connections`) or an async/short-
  transaction redesign — measure first with the canary + `db_check` running.
- Tune with `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_WARN_RATIO` (env vars, `core/config.py`).

## 8. Runbooks

### 8.1 Turn on the scheduled database check

1. Apply the migration with `MIGRATIONS_DATABASE_URL` (`alembic upgrade head`). It creates the
   `ops_monitor` role: `LOGIN`, `pg_monitor`, **no table privileges**, `NOBYPASSRLS`, connection
   limit 2, read-only role defaults. `pg_monitor` is used (not `pg_read_all_stats`) because the
   Supabase `postgres` role can only grant the former (checked in `pg_auth_members`). Consequence:
   the role can *see* other sessions' query text; `db_check` never selects it and a test pins the
   exact queries. (The live database is at `178722372dba`; this migration is not applied there yet.)
2. Set its password **out-of-band** from a password manager, in a `psql` session on the migrations
   connection: `ALTER ROLE ops_monitor WITH PASSWORD '…'`. Never in a file, a commit, or a shell history.
3. Build the URL: `postgresql://ops_monitor.<project-ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=verify-full`
   (host/region from the app's own `DATABASE_URL`; through the shared pooler a custom role's username
   is `[ROLE].[PROJECT-REF]` — Supabase docs). The tool refuses a remote host without
   `sslmode=verify-full` (exit 2).
4. GitHub → Settings → Environments → create `ops-monitoring` (**no required reviewers** — a scheduled
   run would wait for a human forever) → environment secret `OPS_MONITOR_DATABASE_URL`.
5. `verify-full` needs a CA file; the workflow sets `PGSSLROOTCERT=certs/supabase-ca.crt`
   (libpq's default is `~/.postgresql/root.crt`, PostgreSQL 17 docs). Checked 2026-09-19 with a
   handshake-only `openssl s_client` (no credentials sent): the repo's CA verifies
   `*.pooler.supabase.com` including the hostname.
6. Run the workflow once with **Run workflow**; expect `ops db-check: OK`. Then set the repository
   variable `OPS_MONITORING_ENABLED=true` to start the hourly schedule. Exit codes: 0 healthy,
   1 findings or could-not-check, 2 misconfigured.
7. Rotate the password like any other secret: `ALTER ROLE` + update the environment secret.

### 8.2 Turn on the isolation canary

1. Create **two or more synthetic firms** (owner + at least two employees each) through the same
   provisioning path real firms use, plus for each: one task assigned to employee 1, one task
   assigned to employee 2, one job type, one notification addressed to the owner. They live in the
   production database (single environment) — name them so nobody mistakes them for a client, and
   remember they will appear in any per-tenant statistic. The canary makes denied requests, which
   may write `access_denials` rows — inside the synthetic firms only.
2. Config JSON (a secret): `api_base_url` (https), `supabase` (`url`, `publishable_key`) when using
   credentials, and `firms`: `{label: {owner: {email,password} | owner_token, employee: {…} |
   employee_token, task_id, other_employee_task_id, job_type_id, notification_id}}`. The ids must be
   UUIDs (validated — an id goes into a URL path).
3. `base64 -w0 canary.json` → environment secret `CANARY_CONFIG_B64` on `ops-monitoring`. Delete the
   local file. The workflow decodes it to a `0600` file in `RUNNER_TEMP`, runs, and deletes it.
4. Run the workflow manually; expect `canary: 20/20 checks, 0 violations, 0 errors -> OK`
   (2 firms; `6·N·(N−1) + 4·N` checks for N firms). Then enable the schedule with
   `OPS_MONITORING_ENABLED=true`.

### 8.3 Uptime monitor, Sentry, release tags

- UptimeRobot: HTTP monitor on `https://<api-domain>/ready`, expect 200; email alert.
- Sentry: set `SENTRY_DSN`, `SENTRY_RELEASE` (e.g. the git SHA), `SENTRY_ENVIRONMENT=production` on
  Railway; `VITE_SENTRY_DSN` and `VITE_SENTRY_RELEASE` at the Tauri build. The desktop CSP allows
  only `https://*.ingest.sentry.io` (`tauri.conf.json`): if the DSN's ingest host is not under that
  pattern, add it to `connect-src` **before** the build (`DEPLOYMENT.md` §12). Create an issue alert
  (new issue → email) in the Sentry UI; the SDK cannot do that.

## 9. Known gaps — stated, not hidden

1. **No deployment yet.** Nothing here has run against production. The two workflows are dormant by
   design; the canary and `db_check` were validated against the real application and a real
   Postgres 17 in tests, not against Supabase.
2. **Nobody is paged for pool pressure or auth-failure spikes** (§5). Railway has no log drain; the
   documented options are a forwarder (Vector, Fluent Bit) or an SDK.
3. **Logging-stopped detection** is missing (§5).
4. **ASVS 16.4.3** (logs sent to a *logically separate* system): Railway's store is separate from the
   process, but it is not an independent tamper-evident system, and 7-day retention (Hobby) is short
   for forensics. Accepted for the pilot; moving to the Pro plan (30 days) or forwarding is a cost
   decision for you.
5. **`X-Request-ID`** is returned on every response but is not in CORS `expose_headers`, so the
   desktop client cannot read it to show in an error dialog. One line to add when wanted.
6. **Redaction covers Postgres/psycopg/SQLAlchemy message shapes only** (the list and its boundary are
   in §3 item 2), plus one stated limit (a value that reproduces a whole genuine terminator). The two
   Supabase admin sinks are fixed (§3 item 4), as are uvicorn's second traceback and the stdlib's
   `handleError` print (§3 items 5 and 6). Still open, from the 2026-09-19 review (batches 2 and 3): Pydantic
   `ResponseValidationError` / `input_value` text, the `logentry.params`, `extra` and breadcrumb `data`
   fields of a Sentry event, chained `AuthError` values inside a Sentry exception, and
   `before_send_transaction`. Any other library's exception text is unredacted unless it reaches the
   redactor's choke point, which is what the structural test in §3 item 4 is there to watch.
7. **`ops_monitor` can read query text** in `pg_stat_activity` (`pg_monitor`); mitigated by code and
   tests, not by the database. `default_transaction_read_only` on the role is defense in depth (a
   session may override it); the boundary is that the role has **no** table privileges — a test asserts
   that at the catalog level.
8. **Thresholds are placeholders** until real baselines exist.
9. **Pool size / worker count undecided** (§7).
10. **Supabase advisors, 2026-09-19** (read live): security — `auth_leaked_password_protection`
    disabled (WARN; see `DEPLOYMENT.md` §11), `alembic_version` has RLS with no policy (INFO, harmless);
    performance — `auth_rls_initplan` on all 10 `tenant_isolation` policies (WARN: `current_setting()`
    re-evaluated per row; the documented fix is wrapping it in `(select …)`), 14 composite foreign keys
    without a covering index (INFO), 4 unused indexes (INFO, expected at this data volume). Not changed
    here: the RLS rewrite touches the tenant-isolation policy itself and deserves its own audited slice.
11. **The app's own `verify-full` needs the same CA file** (`PGSSLROOTCERT` or `sslrootcert=`); the repo
    has `certs/supabase-ca.crt` but `DEPLOYMENT.md` §2/§13 do not say how the Railway container gets
    it. Add that to the deployment runbook.
12. `tracesSampleRate = 1.0` (both sides) is fine at pilot volume; each `/ready` ping and each canary
    run creates transactions too. Lower it if the 5M-span free quota is approached.

## 10. Where the evidence is

`docs/SECURITY_AUDIT_CHECKLIST.md` → "Observability Phase 1" (negative controls, blind-test outcome,
severity trend). Tests: `backend/tests/core/` (`test_request_logging`, `test_logging_setup`,
`test_health`, `test_pool_monitor`, `test_redaction`, `test_db_parameter_hiding`,
`test_sentry_config`, `test_observability_blind`, and the attack-shaped `test_redaction_hostile`
and `test_log_sinks_hostile`), `backend/tests/ops/` (`test_db_check`, `test_canary_*`),
`backend/tests/api/test_notifications_real_db.py`, and `frontend/src/lib/sentry-context.test.ts`,
`frontend/src/lib/sentry-context.hostile.test.ts`, `frontend/src/stores/session-store.test.tsx`.
The hostile tests provoke real Postgres errors (`TEST_MIGRATIONS_DATABASE_URL`; they skip without
it) and were each shown to fail on the unfixed code and against deliberate breakages of the fix
(mutants); the numbers are in the audit entry.
