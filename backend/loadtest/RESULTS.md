# Load test run log

Dated entries for actual runs of `loadtest.yml` — real command/log output, not narrated summaries.
Each entry states plainly what the run does and does not support concluding, per this project's own
evidentiary discipline (`docs/SECURITY_AUDIT_CHECKLIST.md`'s "bounded claim" requirement, applied
here too).

## 2026-09-09 — first real run, smoke-test defaults (commit `dc9f573`)

**Run**: [`34284825711`](https://github.com/789123654/job-allocation-system-/actions/runs/34284825711),
triggered manually against `main`, all inputs left at their defaults.

**Inputs**: `firms=20`, `employees_per_firm=10`, `tasks_per_firm=40`, `vus=50`, `hold_duration=2m`
(ramp-up 1m, ramp-down 30s — fixed, not yet a workflow input, per `README.md`'s "What's not built").

**Seeded** (`seed.py`'s own printed output): 20 firms, 220 profiles, ~800 tasks.

**k6 result** (`checks_total`/`http_req_duration` etc., quoted directly from the run's own log, not
retyped from memory):
```
THRESHOLDS
  http_req_duration
  ✓ 'p(95)<1000' p(95)=15.23ms
  http_req_failed
  ✓ 'rate<0.01' rate=0.00%

TOTAL RESULTS
  checks_total.......: 5140    24.328144/s
  checks_succeeded...: 100.00% 5140 out of 5140
  checks_failed......: 0.00%   0 out of 5140

  HTTP
  http_req_duration: avg=7.21ms min=3.38ms med=6.29ms max=94.27ms p(90)=11.65ms p(95)=15.23ms
  http_req_failed..: 0.00%  0 out of 5140
  http_reqs........: 5140   24.328144/s

  EXECUTION
  iterations.......: 4131   19.552444/s
  vus_max..........: 50
```

**What this run actually found:** zero errors across 5,140 requests (auth, RLS, the notification
lazy-generation path on every seeded user's first poll, the composite indexes from PR #20 — all
exercised, nothing crashed), and a clean latency floor at this scale: 7.21ms average, 15.23ms p95,
94.27ms worst-case single request. The mechanism built this session — JWKS stub, seeding, k6 scenario,
CI wiring — works end to end for real, not just in isolated lint/typecheck/syntax checks.

**How many tenants does this show the system holds up at, in the real 2k-tenant/10k-user sense?
Honestly: none — this doesn't answer that question, and it was never designed to.** 20 firms / 220
profiles / 50 VUs is ~1% of the stated firm target and ~2% of the user target (`README.md`'s "Running
a real capacity-validating test" section names this explicitly). A clean pass at 1% scale doesn't
imply a clean pass at 100% scale — the whole reason the composite indexes matter is that Postgres's
planner won't even use them on a table this small, so this run couldn't have exercised whether they're
carrying their weight even if it wanted to. What this run *is* good for: a latency **floor** — a
reference point every future, larger-scale run's numbers can be compared against to see how much
latency actually grows as data volume and concurrency increase toward the real target. The capacity
question itself is still open, and still needs the `firms=2000`/`vus=500+` run `README.md` describes,
not yet executed.

## 2026-09-09 — second run, same defaults, now with latency-by-concurrency (commit `80e3bfc`)

**Run**: [`34342653536`](https://github.com/789123654/job-allocation-system-/actions/runs/34342653536),
same inputs as the first entry — the only change is `--out csv=timeseries.csv` (PR #26) now
capturing k6's `vus` metric alongside every `http_req_duration` sample.

**Aggregate result** (same shape as the first run, small run-to-run variance):
```
http_req_duration: avg=8.47ms min=3.48ms med=7.37ms max=130.68ms p(90)=13.42ms p(95)=18.53ms
http_req_failed:   0.00%  0 out of 5141
checks_total:      5141, 100% succeeded
```

**Latency bucketed by concurrent VUs** (`analyze_timeseries.py timeseries.csv`, printed directly in
the run's own log):
```
 VUs (bucketed)   requests     avg ms     p95 ms
              0         18       9.40      34.12
             10         97       7.77      15.71
             20        256       7.34      14.40
             30        305       8.06      18.22
             40        442       8.14      19.78
             50       4023       8.63      18.67
```

**What this actually shows:** latency stayed flat — avg 7-9ms, p95 14-20ms — across the *entire*
0-to-50-VU range tested, including the ~4,000 requests served during the 2-minute hold at full
concurrency. No degradation trend as VUs ramped up, at this scale. The `0`-bucket row's higher
p95 (34.12ms on only 18 requests) is almost certainly cold-start noise (first connections, JIT/cache
warmup), not a real signal, given the sample size.

**Same bounded-claim caveat as the first entry, worth repeating rather than letting the clean table
imply otherwise:** this is "no degradation from 0 to 50 concurrent users," not "no degradation up to
the real target." Whether latency stays this flat at 500-2,000 VUs — the scale that would actually
stress connection pooling and lock contention — is exactly what's still unmeasured, and stays that
way until the real-capacity run in `README.md` actually happens.
