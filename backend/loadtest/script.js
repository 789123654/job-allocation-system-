// Load test for the FastAPI backend — run manually only (README.md), against a disposable local/CI
// Postgres + uvicorn instance, never a real deployment. DEPLOYMENT.md's "single environment, no
// staging, this phase" means "deployed" currently means the real pilot firm's live production
// system — firing synthetic load at that would risk real users' latency, Supabase free-tier rate
// limits, and polluting the one real tenant's data. See README.md for the full reasoning.
//
// Reads identities.json (seed.py's output) — one seeded (firm, profile, token) per virtual user.
// Weighted toward GET /notifications: ARCHITECTURE.md §8 has the frontend polling it every 30-60s
// from every logged-in user — the one truly continuous query pattern in the system, the same
// reasoning that made ix_notifications_dedup the top-priority index two turns of this discussion
// ago. A uniform round-robin across endpoints wouldn't resemble how the app is actually used.
import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";

const BASE_URL = __ENV.API_BASE_URL || "http://localhost:8000";

// SharedArray loads identities.json once and shares it read-only across all VUs, instead of every
// VU parsing its own copy — matters once this scales toward the real 2k-tenant/10k-user target.
const identities = new SharedArray("identities", function () {
  return JSON.parse(open("./identities.json"));
});

export const options = {
  scenarios: {
    poll: {
      executor: "ramping-vus",
      startVUs: 0,
      // Ramp, not an instant jump to full load — shows where latency starts degrading rather than
      // just pass/fail at one fixed concurrency. Override via env vars per run.
      stages: [
        { duration: __ENV.RAMP_UP || "1m", target: Number(__ENV.VUS) || 50 },
        { duration: __ENV.HOLD || "2m", target: Number(__ENV.VUS) || 50 },
        { duration: __ENV.RAMP_DOWN || "30s", target: 0 },
      ],
    },
  },
  thresholds: {
    // Placeholder — no real recorded baseline exists yet (DATA_MODEL.md §6). Tighten once one does;
    // the point of a first run is to establish that baseline, not to already know the right number.
    http_req_duration: ["p(95)<1000"],
    http_req_failed: ["rate<0.01"],
  },
};

export default function () {
  if (identities.length === 0) {
    throw new Error("identities.json is empty — run seed.py first");
  }
  const identity = identities[__VU % identities.length];
  const headers = { Authorization: `Bearer ${identity.token}` };

  const roll = Math.random();
  if (roll < 0.6) {
    const res = http.get(`${BASE_URL}/notifications`, { headers });
    check(res, { "notifications 200": (r) => r.status === 200 });
  } else if (roll < 0.85) {
    const res = http.get(`${BASE_URL}/tasks`, { headers });
    check(res, { "tasks list 200": (r) => r.status === 200 });
    const body = res.status === 200 ? res.json() : null;
    if (Array.isArray(body) && body.length > 0) {
      const task = body[Math.floor(Math.random() * body.length)];
      const detail = http.get(`${BASE_URL}/tasks/${task.id}`, { headers });
      check(detail, { "task detail 200 or 404": (r) => r.status === 200 || r.status === 404 });
    }
  } else {
    const res = http.get(`${BASE_URL}/job-types`, { headers });
    check(res, { "job-types 200": (r) => r.status === 200 });
  }

  sleep(1 + Math.random() * 2); // between-poll think time, not a tight request loop
}
