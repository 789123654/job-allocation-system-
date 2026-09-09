# API latency load test

k6-based load test against a **disposable local/CI Postgres + uvicorn instance only — never a real
deployment.** `DEPLOYMENT.md` §2 states "single environment, no staging, this phase," which means
"deployed" currently means the real pilot firm's live production system. Firing synthetic load at
that would risk real users' latency, Supabase free-tier rate limits, and polluting the one real
tenant's actual data. Revisit once a staging environment exists (`DEPLOYMENT.md`'s own deferred
trigger: "more than one firm, or real customers depending on uptime").

Runs manually only (`.github/workflows/loadtest.yml`, `workflow_dispatch`) — not on every PR like
`ci.yml`. A load test is slow and resource-heavy; it doesn't belong in the fast per-push gate.

## Why this exists

From a Phase-4 session discussing whether this project's multi-tenant foundation (shared-schema +
RLS, `postgres-multitenant`) actually holds at the real target scale (2k tenants / 10k users) rather
than just the current pilot (30 users / 2-4 tenants). `GET /notifications`' dedup query
(`ix_notifications_dedup`, added the same session) was the first concrete finding from that
discussion; this is the tool to check the rest — real p50/p95/p99 latency under real concurrency,
not a guess.

## Why it needs its own JWKS stub, not the pytest monkeypatch trick

`tests/api/test_schema_fuzz.py` fakes JWT verification by **monkeypatching**
`security._jwks_client` — that only works because the test and the app run in the same Python
process (`schemathesis.openapi.from_asgi`). k6 is an **external** HTTP load generator hitting a real
running `uvicorn` process — there's no Python process to monkeypatch. So instead: `generate_keys.py`
writes a real RSA keypair to disk and a real JWKS-format JSON file to `www/`; `python -m http.server`
serves that directory; the target server's `SUPABASE_URL` env var points at wherever that's running
(`config.py`'s `JWKS_URL`/`JWT_ISSUER` are both `computed_field`s derived from `SUPABASE_URL`, so
this needs no code change — the same mechanism CI already relies on with its own placeholder
`SUPABASE_URL`). `seed.py` signs tokens with the matching private key.

## Running it locally

```bash
cd backend

# 1. Real disposable Postgres (same image CI uses)
docker run -d --name loadtest-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:17

# 2. Migrate — same bootstrap ci.yml does for the auth schema/roles vanilla postgres:17 doesn't have
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://postgres:postgres@localhost:5432/postgres', autocommit=True)
conn.execute('CREATE SCHEMA IF NOT EXISTS auth')
conn.execute('CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text, raw_user_meta_data jsonb)')
conn.execute('CREATE ROLE supabase_auth_admin')
conn.execute('CREATE ROLE authenticated')
conn.execute('CREATE ROLE anon')
"
MIGRATIONS_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres uv run alembic upgrade head
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://postgres:postgres@localhost:5432/postgres', autocommit=True)
conn.execute(\"ALTER ROLE fastapi_app WITH PASSWORD 'loadtest_password'\")
"

# 3. Generate the throwaway keypair + JWKS response
uv run python loadtest/generate_keys.py

# 4. Serve it (leave running in its own terminal)
cd loadtest/www && python -m http.server 9999

# 5. Start the app under test, pointed at the JWKS stub (new terminal)
cd backend
export DATABASE_URL=postgresql+psycopg://fastapi_app:loadtest_password@localhost:5432/postgres
export MIGRATIONS_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres
export SUPABASE_URL=http://localhost:9999
export SUPABASE_SECRET_KEY=sb_secret_loadtest_placeholder
export CORS_ORIGINS='["http://localhost"]'
uv run uvicorn app.main:app

# 6. Seed data + mint tokens (new terminal) — defaults: 20 firms, 10 employees/firm, 40 tasks/firm
MIGRATIONS_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres \
SUPABASE_URL=http://localhost:9999 \
uv run python loadtest/seed.py --firms 20 --employees-per-firm 10 --tasks-per-firm 40

# 7. Run k6 (install from https://k6.io if needed) — --out csv writes a timestamped row per
#    metric observation (k6's own `vus` metric included), not just the one end-of-run aggregate
#    --summary-export gives you.
cd loadtest
VUS=50 RAMP_UP=1m HOLD=2m RAMP_DOWN=30s API_BASE_URL=http://localhost:8000 \
  k6 run --out csv=timeseries.csv script.js

# 8. See how latency actually changed as concurrency ramped, not just one flat aggregate number
uv run python analyze_timeseries.py timeseries.csv
```

Scaling toward the real 2k-tenant/10k-user target is just bigger `--firms`/`--employees-per-firm`
numbers in step 6 and a bigger `VUS` in step 7 — nothing else in this design changes.

## Running it in CI

`.github/workflows/loadtest.yml`, triggered manually from the Actions tab (`workflow_dispatch`) —
same steps as above, automated, with `vus`/`hold_duration` as workflow inputs. `timeseries.csv` and
`summary.json` both upload as the `k6-summary` artifact, and `analyze_timeseries.py`'s
latency-by-concurrency table prints directly in the run's own log (a step that runs `if: always()`,
so it prints even if a threshold fails).

## Running a real capacity-validating test (not the defaults)

The `20`/`10`/`40`/`50` defaults (firms / employees-per-firm / tasks-per-firm / vus) are a **smoke
test** — do the pieces work at all (auth, seeding, k6 connecting) — not a real answer to "does the
2k-tenant/10k-user foundation actually hold." Total request count isn't even the metric that
matters for that question; two other numbers are, and both defaults sit at ~1-2% of the real
target:

- **Seeded data volume** — `20` firms is 1% of the 2,000-firm target; `~220` profiles is 2.2% of
  the 10,000-user target. Composite indexes (`ix_notifications_dedup`,
  `ix_tasks_firm_status_deadline`, etc.) only matter at real row counts — Postgres's planner
  happily sequential-scans a table small enough that an index saves nothing, so a small-volume run
  can't actually tell you whether those indexes are pulling their weight.
- **Peak concurrency** (`vus`) — `50` doesn't stress connection pooling, RLS lock contention, or
  concurrent index scans the way real concurrent usage would.

**For an actual capacity run**, use inputs close to the real target:
```
firms: 2000
employees_per_firm: 5      # ≈10,000 users total, matching the stated target
tasks_per_firm: 40         # ≈80,000 task rows
vus: 500                   # see the caveat below before going higher
hold_duration: 5m          # longer hold — stable p95/p99 needs more samples at this scale
```
Seeding this is cheap with how `seed.py` is already built — it batches every firm/profile/task
into three total bulk `INSERT`s (not per-firm round-trips), so 2,000 firms isn't meaningfully
slower to seed than 20.

**Two things not to gloss over when picking `vus` here:**
1. **This project has never stated what fraction of 10,000 total users would be concurrently
   active at once** — that's a real, unrecorded assumption, not a settled number. A conservative
   5%-active assumption gives ~500 peak VUs; a more realistic one for an internal tool used
   actively during business hours could be 10-20% (1,000-2,000). Pick a number and *say* it's an
   assumption when reporting results — don't let it read as measured.
2. **k6, uvicorn, and Postgres all share the same GitHub-hosted runner** (2 vCPU / 7GB RAM,
   standard tier) — push `vus` into the low thousands and k6 itself starts competing with the app
   for CPU, at which point results measure runner contention, not real API latency. A genuinely
   large-scale run needs a bigger/dedicated runner or a separate load-generation host — not what's
   built here.

**Read this before ever running `vus: 2000`-class inputs — `--out csv=timeseries.csv` needs
trimming at that scale, and there's no built-in way to do it:** checked live against Grafana's own
k6 CSV-output docs — the only configuration options are `saveInterval` (how often buffered rows get
*flushed to disk*, default `1s`), `timeFormat`, and `fileName`. **Nothing filters which metrics or
how many rows get written.** k6 writes a timestamped row for *every* built-in metric on *every*
request/iteration by default — not just `vus`/`http_req_duration`, also `http_req_blocked`,
`http_req_connecting`, `http_req_tls_handshaking`, `http_req_sending`, `http_req_waiting`,
`http_req_receiving`, `iteration_duration`, `data_sent`, `data_received`, `checks`, and more, each
its own row. At `vus=50` over 3.5 minutes this was small and harmless (the 2026-09-09 run below).
At `vus=2000` over `hold_duration: 5m`, row count scales directly with request volume — this will
be a large file, and there's no k6 flag to shrink it before it's written. Three real options, none
built yet:
1. Accept the larger artifact — GitHub Actions artifact storage tolerates it, it's just a bigger
   download to analyze locally.
2. Post-filter after the run (a `grep '^(vus|http_req_duration),' timeseries.csv >
   trimmed.csv`-shaped step, or teach `analyze_timeseries.py` to stream-filter while reading rather
   than loading every row) — reduces the *artifact/analysis* cost, not k6's own CPU/memory
   overhead while generating it, so it doesn't help caveat 2 above.
3. For a genuinely large run, k6 also supports streaming output to a real metrics backend
   (InfluxDB/Prometheus remote-write) instead of a flat file — the actual right tool at that scale,
   but real new infrastructure, out of scope for what's built here.
Read this section again before actually running the 2000-VU input set — don't rediscover it mid-run.

See `RESULTS.md` in this directory for the dated log of actual runs and what each one's findings
do and don't support.

## What's not built (deliberately, not an oversight)

- **Writes** (create/submit/review) — this first pass is read-only, matching the emphasis on
  `GET /notifications`' continuous-polling load. Add write scenarios once read-path latency has a
  real baseline to compare against.
- **A real-deployment run** — needs actual Supabase-issued tokens for real synthetic test users
  (not this JWKS-stub trick), and a staging environment to target — both explicitly out of scope
  until `DEPLOYMENT.md`'s own deferred trigger is hit.
- **`script.js` only exercises 4 of the API's 17 real endpoints** (grepped every `@router.get/
  post/patch` across `app/api/routes/`, 2026-09-09) — `GET /notifications`, `GET /tasks`,
  `GET /tasks/{id}`, `GET /job-types`. Not touched at all: every `employees` endpoint (list *and*
  every mutation), every `issues` endpoint, `PATCH /notifications/{id}/read`, and every `tasks`
  mutation (create/deadline/submit/mark-billed/review/raise-issue). Deliberate for this first pass
  — matches the "read-only, polling-weighted" scope above — but worth naming precisely rather than
  leaving "this tests the API" as a vaguer claim than what's actually true. Add `employees`/`issues`
  reads before writes, since they're the same low-risk shape as what's already here.
- **`RAMP_UP`/`RAMP_DOWN` aren't exposed as `workflow_dispatch` inputs** — `script.js` reads them
  from env (defaults `1m`/`30s`), and the workflow only wires through `vus`/`hold_duration`, so
  ramp shape is fixed unless run locally with `k6 run -e RAMP_UP=... -e RAMP_DOWN=...` directly.
  Add both as workflow inputs, same shape as the existing ones, when ramp shape itself needs
  tuning per run rather than just peak concurrency and hold time.
