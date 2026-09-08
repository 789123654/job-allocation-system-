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

# 7. Run k6 (install from https://k6.io if needed)
cd loadtest
VUS=50 RAMP_UP=1m HOLD=2m RAMP_DOWN=30s API_BASE_URL=http://localhost:8000 k6 run script.js
```

Scaling toward the real 2k-tenant/10k-user target is just bigger `--firms`/`--employees-per-firm`
numbers in step 6 and a bigger `VUS` in step 7 — nothing else in this design changes.

## Running it in CI

`.github/workflows/loadtest.yml`, triggered manually from the Actions tab (`workflow_dispatch`) —
same steps as above, automated, with `vus`/`hold_duration` as workflow inputs.

## What's not built (deliberately, not an oversight)

- **Writes** (create/submit/review) — this first pass is read-only, matching the emphasis on
  `GET /notifications`' continuous-polling load. Add write scenarios once read-path latency has a
  real baseline to compare against.
- **A real-deployment run** — needs actual Supabase-issued tokens for real synthetic test users
  (not this JWKS-stub trick), and a staging environment to target — both explicitly out of scope
  until `DEPLOYMENT.md`'s own deferred trigger is hit.
