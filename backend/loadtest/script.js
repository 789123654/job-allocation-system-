// Load test for the FastAPI backend — run manually only (README.md), against a disposable local/CI
// Postgres + uvicorn instance, never a real deployment. DEPLOYMENT.md's "single environment, no
// staging, this phase" means "deployed" currently means the real pilot firm's live production
// system — firing synthetic load at that would risk real users' latency, Supabase free-tier rate
// limits, and polluting the one real tenant's data. See README.md for the full reasoning.
//
// Reads identities.json (seed.py's output) — one seeded (firm, profile, token, foreign_task_id)
// per virtual user. Weighted toward GET /notifications: ARCHITECTURE.md §8 has the frontend
// polling it every 30-60s from every logged-in user — the one truly continuous query pattern in
// the system, the same reasoning that made ix_notifications_dedup the top-priority index two turns
// of this discussion ago. A uniform round-robin across endpoints wouldn't resemble how the app is
// actually used.
//
// 2026-09-17 — expanded beyond pure throughput measurement, per postgres-multitenant's own
// operations guidance on pooled-connection tenant-context leaks ("a session-level setting set by
// one request can leak into the next" under transaction-mode pooling): the original version only
// ever checked HTTP status codes, never *whose data* came back, and pinned one VU to one tenant
// for its whole run — meaning consecutive requests on the same pooled DB connection were almost
// always the same tenant, which is the one scenario least likely to surface a tenant-context bug.
// This version rotates tenant identity per-request (not per-VU), asserts response bodies actually
// belong to the caller, deliberately probes a known cross-tenant resource id expecting 404, and
// adds negative-auth/wrong-role/write-path lanes. Tenant-isolation checks are tagged
// `isolation: "critical"` and pinned to `rate==1` in `thresholds` below — any single cross-tenant
// leak fails the whole run, not just a quieter check-rate number in the summary.
//
// SonarQube S2245 ("pseudorandom number generators should not be used in security contexts") flags
// every Math.random() call below (8 sites: picking which simulated action to run, which seeded
// task/notification/job-type to poll, which test identity to use, a throwaway UUID digit, and
// randomized think-time). None of them generate a secret, token, or credential — they only choose
// what the load test does next — so this file doesn't need a CSPRNG. Marked Won't Fix/Safe in
// SonarQube rather than replaced with crypto.getRandomValues(); this comment is the reasoning behind
// that exception, kept with the code instead of only living in the SonarQube UI.
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
    // Hard gate, not a soft one: a single tenant-isolation check failing (cross-tenant data in a
    // list response, a foreign resource not 404ing, an authz bypass) fails the whole run outright.
    "checks{isolation:critical}": ["rate==1"],
  },
};

// Cheap pseudo-UUID for Idempotency-Key values — this header has no format requirement beyond
// "a UUID v4 or any other random string with enough entropy" (deps.py's own docstring, Zalando's
// headers-1.0.0.yaml). Math.random() is fine here for the same reason given at the top of this file
// (S2245 note) — k6's sandboxed runtime also has no built-in crypto-UUID without adding an external
// jslib dependency this project doesn't otherwise use.
function pseudoUuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.trunc(Math.random() * 16);
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Each function below is one k6 "roll" branch, pulled out of the old single giant if/else-if chain
// (SonarQube S3776, cognitive complexity) purely for readability — same requests, same checks, same
// isolation:critical tags, no behavior change.

function pollNotifications(headers) {
  const res = http.get(`${BASE_URL}/notifications`, { headers });
  check(res, { "notifications 200": (r) => r.status === 200 });
}

function pollTasks(identity, headers) {
  const res = http.get(`${BASE_URL}/tasks`, { headers });
  check(res, { "tasks list 200": (r) => r.status === 200 });
  const body = res.status === 200 ? res.json() : null;
  // Tenant-ownership assertion, not just a status check: the response must never contain the one
  // task id we know for certain belongs to a different firm (seed.py's foreign_task_id).
  if (Array.isArray(body) && identity.foreign_task_id) {
    const leaked = body.some((t) => t.id === identity.foreign_task_id);
    check(null, { "tasks list never contains another firm's task": () => !leaked }, { isolation: "critical" });
  }
  if (Array.isArray(body) && body.length > 0) {
    const task = body[Math.floor(Math.random() * body.length)];
    const detail = http.get(`${BASE_URL}/tasks/${task.id}`, { headers });
    check(detail, { "task detail 200 or 404": (r) => r.status === 200 || r.status === 404 });
  }
}

function pollJobTypes(headers) {
  const res = http.get(`${BASE_URL}/job-types`, { headers });
  check(res, { "job-types 200": (r) => r.status === 200 });
}

function crossTenantTaskProbe(identity, headers) {
  // Cross-tenant object-access probe (BOLA/IDOR under real concurrency) — the actual point of
  // this addition. A task id we know belongs to a DIFFERENT firm must 404, matching this
  // project's own "404 not 403" convention (never confirm another tenant's row exists).
  if (!identity.foreign_task_id) {
    sleep(1);
    return;
  }
  const res = http.get(`${BASE_URL}/tasks/${identity.foreign_task_id}`, {
    headers,
    responseCallback: http.expectedStatuses(404),
  });
  check(res, { "cross-tenant task fetch 404s": (r) => r.status === 404 }, { isolation: "critical" });
}

function tamperedTokenProbe(identity) {
  // Negative-auth probe: corrupt this otherwise-valid token's signature (flip the last 8 chars)
  // and confirm auth still rejects it under load — not just in the light single-request test
  // suite. Still tagged isolation:critical: an auth bypass under load is exactly the same class
  // of failure as a tenant-isolation leak.
  const tampered = identity.token.slice(0, -8) + "AAAAAAAA";
  const res = http.get(`${BASE_URL}/notifications`, {
    headers: { Authorization: `Bearer ${tampered}` },
    responseCallback: http.expectedStatuses(401),
  });
  check(res, { "tampered token rejected (401)": (r) => r.status === 401 }, { isolation: "critical" });
}

function wrongRoleTaskCreateProbe(identity, headers) {
  // Wrong-role probe: an Employee identity hitting an Owner-only endpoint must 403 under load —
  // RequireOwnerDep's own gate, not just its single-request pytest coverage.
  if (identity.role !== "employee") {
    pollNotifications(headers);
    return;
  }
  const res = http.post(
    `${BASE_URL}/tasks`,
    JSON.stringify({ title: "should be rejected" }),
    {
      headers: { ...headers, "Content-Type": "application/json", "Idempotency-Key": pseudoUuid() },
      responseCallback: http.expectedStatuses(403),
    },
  );
  check(res, { "employee creating a task is rejected (403)": (r) => r.status === 403 }, { isolation: "critical" });
}

function ownerTaskCreateProbe(identity, headers) {
  // Owner-only write path — deliberately a small slice (5%): this seeds real rows into a
  // disposable database on every run (README.md's own framing), not something to run heavier
  // without reason. Exercises the create path's own RLS/tenant-context write, not just reads.
  if (identity.role !== "owner") {
    pollNotifications(headers);
    return;
  }
  const res = http.post(
    `${BASE_URL}/tasks`,
    JSON.stringify({ title: "Load test created task" }),
    { headers: { ...headers, "Content-Type": "application/json", "Idempotency-Key": pseudoUuid() } },
  );
  check(res, { "owner task creation 201": (r) => r.status === 201 });
}

function notificationReadProbe(identity, headers) {
  // 2026-09-18 — PATCH /notifications/{id}/read. get_notification checks recipient_id but has no
  // explicit firm_id filter in its query (crud.py) — it leans on RLS alone for tenant scoping, so
  // this cross-tenant probe exercises that RLS boundary directly, not just an app-layer check.
  const list = http.get(`${BASE_URL}/notifications`, { headers });
  const own = list.status === 200 ? list.json() : null;
  if (Array.isArray(own) && own.length > 0) {
    const n = own[Math.floor(Math.random() * own.length)];
    const res = http.patch(`${BASE_URL}/notifications/${n.id}/read`, null, { headers });
    check(res, { "notification marked read 200": (r) => r.status === 200 });
  }
  if (identity.foreign_notification_id) {
    const cross = http.patch(
      `${BASE_URL}/notifications/${identity.foreign_notification_id}/read`,
      null,
      { headers, responseCallback: http.expectedStatuses(404) },
    );
    check(
      cross,
      { "cross-tenant notification PATCH 404s": (r) => r.status === 404 },
      { isolation: "critical" },
    );
  }
}

function jobTypeUpdateProbe(identity, headers) {
  // 2026-09-18 — PATCH /job-types/{id}, Owner-only (RequireOwnerDep + firm-scoped get_job_type,
  // 404-not-403). Owner exercises the real write + cross-tenant probe; Employee exercises the
  // role gate itself, same shape as the wrong-role POST /tasks probe above.
  if (identity.role !== "owner") {
    const res = http.patch(
      `${BASE_URL}/job-types/${identity.foreign_job_type_id || pseudoUuid()}`,
      JSON.stringify({ is_active: true }),
      {
        headers: { ...headers, "Content-Type": "application/json" },
        responseCallback: http.expectedStatuses(403),
      },
    );
    check(
      res,
      { "employee updating a job type is rejected (403)": (r) => r.status === 403 },
      { isolation: "critical" },
    );
    return;
  }
  const list = http.get(`${BASE_URL}/job-types`, { headers });
  const own = list.status === 200 ? list.json() : null;
  if (Array.isArray(own) && own.length > 0) {
    const jt = own[Math.floor(Math.random() * own.length)];
    const res = http.patch(
      `${BASE_URL}/job-types/${jt.id}`,
      JSON.stringify({ is_active: jt.is_active }),
      { headers: { ...headers, "Content-Type": "application/json" } },
    );
    check(res, { "job type update 200": (r) => r.status === 200 });
  }
  if (identity.foreign_job_type_id) {
    const cross = http.patch(
      `${BASE_URL}/job-types/${identity.foreign_job_type_id}`,
      JSON.stringify({ is_active: true }),
      {
        headers: { ...headers, "Content-Type": "application/json" },
        responseCallback: http.expectedStatuses(404),
      },
    );
    check(
      cross,
      { "cross-tenant job type PATCH 404s": (r) => r.status === 404 },
      { isolation: "critical" },
    );
  }
}

function taskDeadlineProbe(identity, headers) {
  // 2026-09-18 — PATCH /tasks/{id}/deadline, Owner-only, same shape as job-types above.
  if (identity.role !== "owner") {
    const res = http.patch(
      `${BASE_URL}/tasks/${identity.foreign_task_id || pseudoUuid()}/deadline`,
      JSON.stringify({ deadline: new Date(Date.now() + 86400000).toISOString() }),
      {
        headers: { ...headers, "Content-Type": "application/json" },
        responseCallback: http.expectedStatuses(403),
      },
    );
    check(
      res,
      { "employee updating a task deadline is rejected (403)": (r) => r.status === 403 },
      { isolation: "critical" },
    );
    return;
  }
  const list = http.get(`${BASE_URL}/tasks`, { headers });
  const own = list.status === 200 ? list.json() : null;
  if (Array.isArray(own) && own.length > 0) {
    const t = own[Math.floor(Math.random() * own.length)];
    const res = http.patch(
      `${BASE_URL}/tasks/${t.id}/deadline`,
      JSON.stringify({ deadline: new Date(Date.now() + 86400000).toISOString() }),
      { headers: { ...headers, "Content-Type": "application/json" } },
    );
    check(res, { "task deadline update 200": (r) => r.status === 200 });
  }
  if (identity.foreign_task_id) {
    const cross = http.patch(
      `${BASE_URL}/tasks/${identity.foreign_task_id}/deadline`,
      JSON.stringify({ deadline: new Date(Date.now() + 86400000).toISOString() }),
      {
        headers: { ...headers, "Content-Type": "application/json" },
        responseCallback: http.expectedStatuses(404),
      },
    );
    check(
      cross,
      { "cross-tenant task deadline PATCH 404s": (r) => r.status === 404 },
      { isolation: "critical" },
    );
  }
}

export default function vuIteration() {
  if (identities.length === 0) {
    throw new Error("identities.json is empty — run seed.py first");
  }
  // Random per ITERATION, not `identities[__VU % identities.length]` (the original, pinned-per-VU
  // version): a fixed VU->identity mapping means one VU's requests are always the same tenant, so
  // consecutive requests on a shared pooled DB connection are almost never two different tenants —
  // exactly the case least likely to catch a tenant-context leak under connection pooling. Random
  // selection every iteration maximizes how often adjacent requests on the same connection belong
  // to different firms.
  const identity = identities[Math.floor(Math.random() * identities.length)];
  const headers = { Authorization: `Bearer ${identity.token}` };

  // TEMPORARY — write-only (POST + PATCH) stress variant, re-run at 300 VUs specifically to test
  // whether VU count (not just write-heavy traffic) is what reproduces the 2026-09-18 QueuePool-
  // exhaustion failure (that run was 300 VUs; the first write-only retest here was only 100 VUs and
  // passed clean). Revert right after this run — not the new baseline. Same isolation:critical
  // security checks, same thresholds.
  const roll = Math.random();
  if (roll < 0.2) {
    wrongRoleTaskCreateProbe(identity, headers);
  } else if (roll < 0.4) {
    ownerTaskCreateProbe(identity, headers);
  } else if (roll < 0.6) {
    notificationReadProbe(identity, headers);
  } else if (roll < 0.8) {
    jobTypeUpdateProbe(identity, headers);
  } else {
    taskDeadlineProbe(identity, headers);
  }

  sleep(1 + Math.random() * 2); // between-poll think time, not a tight request loop
}
