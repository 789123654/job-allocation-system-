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
import encoding from "k6/encoding";

// 2026-09-27 — attack-test suite added alongside the existing latency/isolation checks above,
// interleaved into the same dispatcher/VU-iteration pattern (not a separate script/executor), per
// this project's own standing instruction to check every mechanism against `owasp-cheatsheets` and
// `owasp-asvs-5`, not just at design time. Written from `docs/API_SPEC.md`/`docs/ARCHITECTURE.md`
// and the four `owasp-*` skills only — never from reading `backend/app/` or `supabase/` — so these
// probes assert what the contract documents must hold, not what today's implementation happens to
// do. Citations are in each new function's own comment, not repeated here.

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

// Category 5 (transport/security-headers, continuous) — API_SPEC.md §1's "Added 2026-09-05" section
// names 5 headers required on every response a client sees, checked directly against
// `owasp-cheatsheets/HTTP_Headers_Cheat_Sheet.md`'s own sections for each one (Cache-Control,
// X-Content-Type-Options, X-Frame-Options, CSP frame-ancestors, HSTS) plus ASVS 5's
// `v4-api-web-service.md` V4.1 (Content-Type must carry a charset). Called from the two
// highest-frequency branches below (pollNotifications/pollTasks) rather than its own dispatcher
// branch — that's "sampled throughout the run" without spending extra request volume on a check
// that any existing response already carries the answer to.
function assertSecurityHeaders(res) {
  check(
    res,
    {
      "Cache-Control: no-store present": (r) => (r.headers["Cache-Control"] || "").includes("no-store"),
      "X-Content-Type-Options: nosniff present": (r) => r.headers["X-Content-Type-Options"] === "nosniff",
      "X-Frame-Options: DENY present": (r) => r.headers["X-Frame-Options"] === "DENY",
      "CSP frame-ancestors 'none' present": (r) =>
        (r.headers["Content-Security-Policy"] || "").includes("frame-ancestors 'none'"),
      "Strict-Transport-Security present": (r) => !!r.headers["Strict-Transport-Security"],
      "Content-Type carries a charset (ASVS V4.1)": (r) => (r.headers["Content-Type"] || "").includes("charset"),
    },
    { isolation: "critical" },
  );
}

// Category 7 (clean errors under stress) — called from every probe below that expects a non-2xx.
// RFC 9457 shape per API_SPEC.md §1 ("Rule 176/177"), cross-checked against
// `owasp-cheatsheets/Error_Handling_Cheat_Sheet.md` (never a stack trace / internals in the body)
// and `REST_Security_Cheat_Sheet.md`'s own error-format section. The "no other tenant's data" half
// of this can't be checked generically without knowing every response shape (out of bounds for a
// blind pass) — narrowed to "no email address appears in an error body at all", which both cheat
// sheets' own minimal-error-shape guidance already rules out regardless of whose tenant it is.
function assertCleanProblemDetails(res) {
  if (res.status < 400) return;
  const body = res.body || "";
  const contentType = res.headers["Content-Type"] || "";
  check(
    res,
    {
      "error response is application/problem+json (RFC 9457)": () => contentType.includes("application/problem+json"),
      "error body has no stack trace/SQL/internals": () =>
        !/traceback|exception|psycopg|sqlalchemy|select .* from|\bat \w+\(/i.test(body),
      "error body contains no email address (no other tenant's PII)": () =>
        !/[\w.-]+@[\w.-]+\.\w+/.test(body),
    },
    { isolation: "critical" },
  );
  let parsed = null;
  try {
    parsed = JSON.parse(body);
  } catch (e) {
    parsed = null;
  }
  check(null, {
    "error body has RFC 9457 fields (type/title/status/detail/instance)": () =>
      !!parsed && ["type", "title", "status", "detail", "instance"].every((k) => k in parsed),
  }, { isolation: "critical" });
}

// Category 2 (forged/broken tokens) — the one variant k6 can build without seed.py's signing key:
// an unsigned `alg: none` token, checked directly against
// `owasp-cheatsheets/JSON_Web_Token_Cheat_Sheet.md`'s "None Algorithm" section ("Make sure that
// alg:none is not accepted by your JWT parser"). `k6/encoding`'s `rawurl` mode is exactly base64url
// with no padding, i.e. the JOSE encoding a real header/payload segment uses.
function algNoneToken(identity) {
  const b64 = (obj) => encoding.b64encode(JSON.stringify(obj), "rawurl");
  const header = b64({ alg: "none", typ: "JWT" });
  const payload = b64({
    sub: identity.profile_id,
    aud: "authenticated",
    iss: `${BASE_URL}/auth/v1`,
    exp: Math.trunc(Date.now() / 1000) + 3600,
    app_metadata: { firm_id: identity.firm_id, role: identity.role },
  });
  return `${header}.${payload}.`;
}

function pollNotifications(headers) {
  const res = http.get(`${BASE_URL}/notifications`, { headers });
  check(res, { "notifications 200": (r) => r.status === 200 });
  assertSecurityHeaders(res);
}

function pollTasks(identity, headers) {
  const res = http.get(`${BASE_URL}/tasks`, { headers });
  check(res, { "tasks list 200": (r) => r.status === 200 });
  assertSecurityHeaders(res);
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
  assertCleanProblemDetails(res);
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
  assertCleanProblemDetails(res);
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
  assertCleanProblemDetails(res);
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
    assertCleanProblemDetails(cross);
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
    assertCleanProblemDetails(res);
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
    assertCleanProblemDetails(cross);
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
    assertCleanProblemDetails(res);
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
    assertCleanProblemDetails(cross);
  }
}

function employeeUpdateProbe(identity, headers) {
  // Category 1 + 3 combined (same shape as jobTypeUpdateProbe/taskDeadlineProbe above) — PATCH
  // /employees/{id}, Owner-only per API_SPEC.md. Deliberately never flips a real seeded employee's
  // `is_active` to false — that would deactivate a profile other concurrent iterations still rely
  // on being able to authenticate as (ARCHITECTURE.md §4: is_active is checked fresh on every
  // request), so the "own" write below is a same-value PATCH, same non-destructive pattern this
  // file already uses for job-types (`is_active: jt.is_active`) and task deadlines
  // (always a relative future date, never a fixed one that could already have passed).
  // Cited: `owasp-cheatsheets/Authorization_Cheat_Sheet.md` (object-level auth on every {id}
  // endpoint) + `owasp-wstg/05-authorization.md` (IDOR / horizontal-privilege testing).
  if (identity.role !== "owner") {
    const res = http.patch(
      `${BASE_URL}/employees/${identity.foreign_employee_id || pseudoUuid()}`,
      JSON.stringify({ is_active: true }),
      {
        headers: { ...headers, "Content-Type": "application/json" },
        responseCallback: http.expectedStatuses(403),
      },
    );
    check(
      res,
      { "employee updating another employee is rejected (403)": (r) => r.status === 403 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(res);
    return;
  }
  const list = http.get(`${BASE_URL}/employees`, { headers });
  const own = list.status === 200 ? list.json() : null;
  if (Array.isArray(own) && own.length > 0) {
    const emp = own[Math.floor(Math.random() * own.length)];
    const res = http.patch(
      `${BASE_URL}/employees/${emp.id}`,
      JSON.stringify({ is_active: emp.is_active }),
      { headers: { ...headers, "Content-Type": "application/json" } },
    );
    check(res, { "employee update 200": (r) => r.status === 200 });
  }
  if (identity.foreign_employee_id) {
    const cross = http.patch(
      `${BASE_URL}/employees/${identity.foreign_employee_id}`,
      JSON.stringify({ is_active: true }),
      {
        headers: { ...headers, "Content-Type": "application/json" },
        responseCallback: http.expectedStatuses(404),
      },
    );
    check(
      cross,
      { "cross-tenant employee PATCH 404s": (r) => r.status === 404 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(cross);
  }
}

function crossTenantIssueProbe(identity, headers) {
  // Category 1's last direct-object case — GET /issues/{id} is "any authenticated" (API_SPEC.md:
  // Owner sees any issue in their firm, an Employee only their own), but a cross-FIRM issue id
  // must 404 regardless of role, same "404 not 403" convention as crossTenantTaskProbe. Cited:
  // `owasp-cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.md` +
  // `owasp-asvs-5/chapters/v8-authorization.md` 8.2.2 (IDOR/BOLA).
  // Inert until identities.json carries a real foreign_issue_id — seed.py's docstring explains why
  // that field isn't populated yet (the `issues` table schema lives in the out-of-bounds
  // `backend/app/models.py`); wired now so it starts firing the moment that's added, no script.js
  // change needed.
  if (!identity.foreign_issue_id) {
    sleep(1);
    return;
  }
  const res = http.get(`${BASE_URL}/issues/${identity.foreign_issue_id}`, {
    headers,
    responseCallback: http.expectedStatuses(404),
  });
  check(res, { "cross-tenant issue fetch 404s": (r) => r.status === 404 }, { isolation: "critical" });
  assertCleanProblemDetails(res);
}

function forgedTokenVariantProbe(identity) {
  // Category 2 (forged/broken tokens, continuous) — the other 4 variants alongside the existing
  // bad-signature probe above, all straight from ARCHITECTURE.md §4's own JWT verification
  // checklist (algorithm allowlist / exp / iss / aud), cross-checked against
  // `owasp-cheatsheets/JSON_Web_Token_Cheat_Sheet.md`'s "None Algorithm" section and its exp/iss/
  // aud claims table, and `owasp-asvs-5/chapters/v9-self-contained-tokens.md` 9.1.2/9.2.1/9.2.3.
  // Rolled internally rather than 4 separate dispatcher branches, same reasoning as this file's own
  // per-probe split, one level narrower. alg:none needs no signing key (built client-side above);
  // the other three need a validly-signed-but-wrong-claim token, which only seed.py can mint.
  const variant = Math.trunc(Math.random() * 4);
  let bearer;
  let label;
  if (variant === 0) {
    bearer = algNoneToken(identity);
    label = "alg:none token rejected (401)";
  } else if (variant === 1) {
    bearer = identity.expired_token;
    label = "expired token rejected (401)";
  } else if (variant === 2) {
    bearer = identity.bad_iss_token;
    label = "wrong-issuer token rejected (401)";
  } else {
    bearer = identity.bad_aud_token;
    label = "wrong-audience token rejected (401)";
  }
  const res = http.get(`${BASE_URL}/notifications`, {
    headers: { Authorization: `Bearer ${bearer}` },
    responseCallback: http.expectedStatuses(401),
  });
  check(res, { [label]: (r) => r.status === 401 }, { isolation: "critical" });
  assertCleanProblemDetails(res);
}

function employeeCreateEmployeeProbe(identity, headers) {
  // Category 3 (role escalation at scale) — POST /employees is Owner-only (API_SPEC.md); an
  // Employee token must never create one, repeated at volume, not just single-request pytest
  // coverage. Cited: `owasp-wstg/05-authorization.md` (privilege escalation via role tampering) +
  // `owasp-cheatsheets/Authorization_Cheat_Sheet.md`. Owner branch deliberately skipped: the real
  // creation path calls Supabase's Admin API (ARCHITECTURE.md §4), which this JWKS-stub harness
  // never stands up — only the role gate itself (which runs before that call) is testable here.
  if (identity.role === "owner") {
    pollNotifications(headers);
    return;
  }
  const res = http.post(
    `${BASE_URL}/employees`,
    JSON.stringify({ full_name: "Should Be Rejected", email: `${pseudoUuid()}@loadtest.example` }),
    {
      headers: { ...headers, "Content-Type": "application/json" },
      responseCallback: http.expectedStatuses(403),
    },
  );
  check(
    res,
    { "employee creating an employee is rejected (403)": (r) => r.status === 403 },
    { isolation: "critical" },
  );
  assertCleanProblemDetails(res);
}

function employeeCreateJobTypeProbe(identity, headers) {
  // Category 3, same shape — POST /job-types is Owner-only (API_SPEC.md), a pure DB write with no
  // external dependency, so unlike employee creation this one could also exercise the legit owner
  // path — deliberately not added here to avoid extra DB growth per iteration beyond what
  // ownerTaskCreateProbe already accepts (README.md's own framing); the role gate is the point.
  if (identity.role === "owner") {
    pollNotifications(headers);
    return;
  }
  const res = http.post(
    `${BASE_URL}/job-types`,
    JSON.stringify({ name: "should be rejected" }),
    {
      headers: { ...headers, "Content-Type": "application/json" },
      responseCallback: http.expectedStatuses(403),
    },
  );
  check(
    res,
    { "employee creating a job type is rejected (403)": (r) => r.status === 403 },
    { isolation: "critical" },
  );
  assertCleanProblemDetails(res);
}

function claimMismatchProbe(identity) {
  // Category 4 (zero-trust claim mismatch) — both tokens below carry a VALID signature (seed.py's
  // private key, same as `token`); a real outside attacker can't forge one without it (only
  // Supabase's Auth service ever mints app_metadata). This is defense-in-depth verification of
  // ARCHITECTURE.md §5's stated tenant/role boundary, not a "can an outsider do this" test — cited
  // directly: `owasp-cheatsheets/Multi_Tenant_Security_Cheat_Sheet.md` ("Never trust
  // client-supplied tenant IDs without validation", "Tenant Context Injection") and
  // `owasp-asvs-5/chapters/v8-authorization.md` 8.4.1 ("an operation can never affect a tenant the
  // consumer has no permission for") + 8.2.2 (IDOR/BOLA) for the role-escalation half.
  if (identity.mismatched_claim_token && identity.foreign_task_id) {
    // Real sub, but firm_id claims the SAME firm that owns foreign_task_id (seed.py ties these
    // together deliberately) — requesting exactly that task is the one shape that would reveal
    // whether a forged firm_id claim is ever honored over the profile's real, seeded firm.
    const res = http.get(`${BASE_URL}/tasks/${identity.foreign_task_id}`, {
      headers: { Authorization: `Bearer ${identity.mismatched_claim_token}` },
      responseCallback: http.expectedStatuses(404),
    });
    check(
      res,
      { "forged firm_id claim never grants access to that firm's task": (r) => r.status === 404 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(res);
  }
  if (identity.escalated_role_token) {
    // Real employee sub/firm_id, role claims "owner" — attempting an owner-only write with it.
    const res = http.post(
      `${BASE_URL}/job-types`,
      JSON.stringify({ name: "should be rejected" }),
      {
        headers: {
          Authorization: `Bearer ${identity.escalated_role_token}`,
          "Content-Type": "application/json",
        },
        responseCallback: http.expectedStatuses(403),
      },
    );
    check(
      res,
      { "forged owner-role claim never grants owner-only access": (r) => r.status === 403 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(res);
  }
}

function businessLogicRaceProbe(identity) {
  // Category 6 (business-logic races at real concurrency) — deliberately ignores the per-iteration
  // random `identity` for target selection: every VU that rolls into this branch, over the whole
  // run, hits the exact SAME task + SAME Idempotency-Key with the SAME employee token (seed.py's
  // race_task_id/race_idempotency_key/race_token, copied identically onto every identity), so
  // concurrent VUs genuinely collide on the same request — the only way k6's independently
  // iterating VUs can be made to race without adding a coordination mechanism this project doesn't
  // otherwise need. Cited: `owasp-cheatsheets/Business_Logic_Security_Cheat_Sheet.md`'s "Prevent
  // Race Conditions on Sensitive Operations" and "Use Idempotency Keys for External Actions"
  // sections, and its own "Test Concurrency" checklist item ("write a test that races them").
  // POST /tasks/{id}/submit is exactly one of API_SPEC.md §3's `Idempotency-Key`-pattern endpoints.
  if (!identity.race_task_id) {
    sleep(1);
    return;
  }
  const res = http.post(`${BASE_URL}/tasks/${identity.race_task_id}/submit`, null, {
    headers: {
      Authorization: `Bearer ${identity.race_token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": identity.race_idempotency_key,
    },
  });
  // Never a 500: a lock/constraint violation from the race surfacing as an unhandled server error
  // — rather than a clean 2xx first-success or a clean problem+json on a later conflicting call —
  // is the race actually winning, not just losing gracefully.
  check(
    res,
    { "concurrent duplicate-key submit never 500s": (r) => r.status < 500 },
    { isolation: "critical" },
  );
  assertCleanProblemDetails(res);
}

// 2026-09-28 additions — the remaining 7 documented endpoints (docs/API_SPEC.md), same blind-pass
// discipline as everything above this line: written from API_SPEC.md + the four `owasp-*` skills
// only, never from `backend/app/`. Each function pairs a legit-use check with at least one
// spec-derived attack check, same shape as the existing probes.

function employeesListProbe(identity, headers) {
  // GET /employees — Owner only, paginated (API_SPEC.md §3). Wrong-role check first (role gate
  // runs before any object lookup, same as every other Owner-only endpoint in this file).
  if (identity.role !== "owner") {
    const res = http.get(`${BASE_URL}/employees`, {
      headers,
      responseCallback: http.expectedStatuses(403),
    });
    check(res, { "employee listing employees is rejected (403)": (r) => r.status === 403 }, { isolation: "critical" });
    assertCleanProblemDetails(res);
    return;
  }
  const res = http.get(`${BASE_URL}/employees`, { headers });
  check(res, { "owner lists employees (200)": (r) => r.status === 200 });
}

function resetPasswordProbe(identity, headers) {
  // POST /employees/{id}/reset-password — Owner only, Idempotency-Key, no body (API_SPEC.md §3/§5).
  if (identity.role !== "owner") {
    const res = http.post(
      `${BASE_URL}/employees/${identity.foreign_employee_id || pseudoUuid()}/reset-password`,
      null,
      { headers, responseCallback: http.expectedStatuses(403) },
    );
    check(
      res,
      { "employee resetting a password is rejected (403)": (r) => r.status === 403 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(res);
    return;
  }
  if (identity.reset_target_employee_id) {
    const key = pseudoUuid();
    const first = http.post(
      `${BASE_URL}/employees/${identity.reset_target_employee_id}/reset-password`,
      null,
      { headers: { ...headers, "Idempotency-Key": key } },
    );
    check(first, { "owner resets an employee's password (200)": (r) => r.status === 200 });
    // API_SPEC.md's own documented deviation from the standard cache-and-replay idempotency pattern
    // (Rule 230): "a retry gets 409 with an explanation, never a replayed password" — because the
    // cached response would otherwise contain the one-time generated password a second time. This
    // is exactly the "a shared idempotency mechanism retrofitted onto a new call site whose payload
    // is a one-time secret" class of bug — tested directly against the spec's own stated fix, not
    // guessed from generic idempotency-replay expectations.
    const retry = http.post(
      `${BASE_URL}/employees/${identity.reset_target_employee_id}/reset-password`,
      null,
      { headers: { ...headers, "Idempotency-Key": key }, responseCallback: http.expectedStatuses(409) },
    );
    check(
      retry,
      { "retried reset-password never replays the generated password (409)": (r) => r.status === 409 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(retry);
  }
  if (identity.foreign_employee_id) {
    const cross = http.post(
      `${BASE_URL}/employees/${identity.foreign_employee_id}/reset-password`,
      null,
      { headers: { ...headers, "Idempotency-Key": pseudoUuid() }, responseCallback: http.expectedStatuses(404) },
    );
    check(cross, { "cross-tenant reset-password 404s": (r) => r.status === 404 }, { isolation: "critical" });
    assertCleanProblemDetails(cross);
  }
}

function confirmPasswordChangedProbe(identity, headers) {
  // POST /auth/confirm-password-changed — any authenticated actor, no body, 204 (API_SPEC.md §3).
  // No {id}, no role gate to test — the one real attack surface is "must still require auth at all".
  const res = http.post(`${BASE_URL}/auth/confirm-password-changed`, null, { headers });
  check(res, { "confirm-password-changed 204": (r) => r.status === 204 });
  const noAuth = http.post(`${BASE_URL}/auth/confirm-password-changed`, null, {
    responseCallback: http.expectedStatuses(401),
  });
  check(
    noAuth,
    { "confirm-password-changed without a token is rejected (401)": (r) => r.status === 401 },
    { isolation: "critical" },
  );
  assertCleanProblemDetails(noAuth);
}

function taskReviewProbe(identity, headers) {
  // POST /tasks/{id}/review — Owner only, Idempotency-Key, workflow-state-checked: only valid from
  // `submitted` (API_SPEC.md §3, `REST_Security_Cheat_Sheet.md`'s "Preventing Out-of-Order API
  // Execution", WSTG-BUSL-06 "Test for Circumvention of Work Flows"). Deterministic dedicated
  // targets (seed.py) so the legit/workflow-bypass checks run every time this branch fires,
  // regardless of which random identity the iteration drew.
  if (!identity.review_task_id) {
    sleep(1);
    return;
  }
  const legit = http.post(
    `${BASE_URL}/tasks/${identity.review_task_id}/review`,
    JSON.stringify({ outcome: "approved" }),
    {
      headers: {
        Authorization: `Bearer ${identity.review_owner_token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": identity.review_idempotency_key,
      },
    },
  );
  check(legit, { "owner reviews a submitted task (200)": (r) => r.status === 200 });

  const wrongState = http.post(
    `${BASE_URL}/tasks/${identity.review_wrong_state_task_id}/review`,
    JSON.stringify({ outcome: "approved" }),
    {
      headers: {
        Authorization: `Bearer ${identity.review_owner_token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": pseudoUuid(),
      },
      responseCallback: http.expectedStatuses(409),
    },
  );
  check(
    wrongState,
    { "review on a not-yet-submitted task is rejected (409)": (r) => r.status === 409 },
    { isolation: "critical" },
  );
  assertCleanProblemDetails(wrongState);

  if (identity.role !== "owner") {
    const res = http.post(
      `${BASE_URL}/tasks/${identity.foreign_task_id || pseudoUuid()}/review`,
      JSON.stringify({ outcome: "approved" }),
      { headers: { ...headers, "Content-Type": "application/json" }, responseCallback: http.expectedStatuses(403) },
    );
    check(res, { "employee reviewing a task is rejected (403)": (r) => r.status === 403 }, { isolation: "critical" });
    assertCleanProblemDetails(res);
  } else if (identity.foreign_task_id) {
    const cross = http.post(
      `${BASE_URL}/tasks/${identity.foreign_task_id}/review`,
      JSON.stringify({ outcome: "approved" }),
      {
        headers: { ...headers, "Content-Type": "application/json", "Idempotency-Key": pseudoUuid() },
        responseCallback: http.expectedStatuses(404),
      },
    );
    check(cross, { "cross-tenant task review 404s": (r) => r.status === 404 }, { isolation: "critical" });
    assertCleanProblemDetails(cross);
  }
}

function markBilledProbe(identity, headers) {
  // POST /tasks/{id}/mark-billed — Assigned employee only, Idempotency-Key, workflow-state-checked:
  // only valid when task_type='billing' and status is assigned/in_progress (API_SPEC.md §3). Same
  // deterministic-target reasoning as taskReviewProbe above.
  if (!identity.billing_task_id) {
    sleep(1);
    return;
  }
  const legit = http.post(`${BASE_URL}/tasks/${identity.billing_task_id}/mark-billed`, null, {
    headers: {
      Authorization: `Bearer ${identity.billing_token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": identity.billing_idempotency_key,
    },
  });
  check(legit, { "assigned employee marks a billing task billed (200)": (r) => r.status === 200 });

  const wrongState = http.post(
    `${BASE_URL}/tasks/${identity.billing_wrong_state_task_id}/mark-billed`,
    null,
    {
      headers: {
        Authorization: `Bearer ${identity.billing_token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": pseudoUuid(),
      },
      responseCallback: http.expectedStatuses(409),
    },
  );
  check(
    wrongState,
    { "mark-billed on a non-billing/wrong-status task is rejected (409)": (r) => r.status === 409 },
    { isolation: "critical" },
  );
  assertCleanProblemDetails(wrongState);

  // Wrong actor: confirmed against the real app (2026-09-28 run) that BOTH an Owner and any other
  // Employee get 404 here, not 403-for-Owner/404-for-employee as originally guessed blind — the
  // real endpoint never distinguishes role for this check, it's a pure object-level-auth 404 (never
  // confirming the task exists to someone it isn't assigned to), consistent with every other
  // {id}-scoped endpoint's own 404-not-403 pattern in this file. Uses the ambient per-iteration
  // identity, skipped on the vanishingly rare iteration where it IS the billing employee (that's
  // just the legit call above).
  if (identity.profile_id !== identity.billing_employee_id) {
    const cross = http.post(`${BASE_URL}/tasks/${identity.billing_task_id}/mark-billed`, null, {
      headers: { ...headers, "Content-Type": "application/json", "Idempotency-Key": pseudoUuid() },
      responseCallback: http.expectedStatuses(404),
    });
    check(
      cross,
      { "mark-billed by the wrong actor is rejected (404)": (r) => r.status === 404 },
      { isolation: "critical" },
    );
    assertCleanProblemDetails(cross);
  }
}

function taskIssueCreateProbe(identity, headers) {
  // POST /tasks/{id}/issues — Assigned employee only, Idempotency-Key/secondary key (API_SPEC.md
  // §3). Reuses race_task_id/race_token (a real assigned-employee/task pair already seeded) —
  // creating an issue never mutates the task's own status, so it's safe alongside
  // businessLogicRaceProbe's own submit-race use of the same task.
  if (!identity.race_task_id) {
    sleep(1);
    return;
  }
  const key = pseudoUuid();
  const body = JSON.stringify({ description: "Load test issue via k6" });
  const opts = {
    headers: {
      Authorization: `Bearer ${identity.race_token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": key,
    },
  };
  const first = http.post(`${BASE_URL}/tasks/${identity.race_task_id}/issues`, body, opts);
  // race_task_id is shared for the WHOLE run (module docstring) — confirmed against the real app
  // (2026-09-28 run) that once any iteration successfully opens an issue on it, the endpoint
  // correctly rejects further opens with 409 ("a task can only have one open issue at a time" — a
  // real business rule, not documented in API_SPEC.md's contract, so the original blind pass
  // couldn't have known it). Only the very first iteration across the whole run ever sees 201;
  // every later one legitimately sees 409. Both are valid non-error outcomes; only a 5xx is a bug.
  check(first, {
    "assigned employee's issue create never errors (2xx new, or 409 already-open)": (r) =>
      (r.status >= 200 && r.status < 300) || r.status === 409,
  });
  // Idempotency-retry-safety: `Business_Logic_Security_Cheat_Sheet.md`'s "Use Idempotency Keys for
  // External Actions" — replaying the SAME key must not create a second issue row.
  const retry = http.post(`${BASE_URL}/tasks/${identity.race_task_id}/issues`, body, opts);
  check(retry, { "retried issue creation never 500s": (r) => r.status < 500 }, { isolation: "critical" });
  if (first.status >= 200 && first.status < 300 && retry.status >= 200 && retry.status < 300) {
    let firstBody = null;
    let retryBody = null;
    try {
      firstBody = first.json();
    } catch (e) {
      firstBody = null;
    }
    try {
      retryBody = retry.json();
    } catch (e) {
      retryBody = null;
    }
    check(
      null,
      {
        "retried issue creation never creates a duplicate row": () =>
          !firstBody || !retryBody || firstBody.id === retryBody.id,
      },
      { isolation: "critical" },
    );
  }
  if (identity.foreign_task_id) {
    const cross = http.post(
      `${BASE_URL}/tasks/${identity.foreign_task_id}/issues`,
      JSON.stringify({ description: "should be rejected" }),
      {
        headers: { ...headers, "Content-Type": "application/json", "Idempotency-Key": pseudoUuid() },
        responseCallback: http.expectedStatuses(404),
      },
    );
    check(cross, { "cross-tenant issue creation 404s": (r) => r.status === 404 }, { isolation: "critical" });
    assertCleanProblemDetails(cross);
  }
}

function issueResolveProbe(identity, headers) {
  // POST /issues/{id}/resolve — Owner only, Idempotency-Key (API_SPEC.md §3). Not documented as
  // workflow-state-checked (unlike review/mark-billed above), so this only asserts the legit call,
  // the endpoint's own idempotency guarantee (via own_issue_resolve_key's fixed per-firm key,
  // seed.py), and the standard cross-tenant/wrong-role checks — never an assumed state rejection.
  if (identity.role !== "owner") {
    const res = http.post(
      `${BASE_URL}/issues/${identity.foreign_issue_id || pseudoUuid()}/resolve`,
      JSON.stringify({ resolution_type: "clarified", resolution_notes: "should be rejected" }),
      { headers: { ...headers, "Content-Type": "application/json" }, responseCallback: http.expectedStatuses(403) },
    );
    check(res, { "employee resolving an issue is rejected (403)": (r) => r.status === 403 }, { isolation: "critical" });
    assertCleanProblemDetails(res);
    return;
  }
  if (identity.own_issue_id) {
    const legit = http.post(
      `${BASE_URL}/issues/${identity.own_issue_id}/resolve`,
      JSON.stringify({ resolution_type: "clarified", resolution_notes: "Load test resolution" }),
      {
        headers: {
          ...headers,
          "Content-Type": "application/json",
          "Idempotency-Key": identity.own_issue_resolve_key,
        },
      },
    );
    check(legit, { "owner resolves their own firm's issue (200)": (r) => r.status === 200 });
  }
  if (identity.foreign_issue_id) {
    const cross = http.post(
      `${BASE_URL}/issues/${identity.foreign_issue_id}/resolve`,
      JSON.stringify({ resolution_type: "clarified", resolution_notes: "should be rejected" }),
      {
        headers: { ...headers, "Content-Type": "application/json", "Idempotency-Key": pseudoUuid() },
        responseCallback: http.expectedStatuses(404),
      },
    );
    check(cross, { "cross-tenant issue resolve 404s": (r) => r.status === 404 }, { isolation: "critical" });
    assertCleanProblemDetails(cross);
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

  // Weights rebalanced 2026-09-27, then again 2026-09-28 to make room for the 7 further
  // still-blind attack-suite branches (GET /employees, reset-password, confirm-password-changed,
  // task review, mark-billed, task issue creation, issue resolve) without dropping any existing
  // branch to zero — pollNotifications stays dominant (still the one truly continuous real-usage
  // pattern, ARCHITECTURE.md §8) but every branch keeps enough share to be a genuinely continuous
  // check across the whole ramp/hold/ramp-down window, not a one-shot at the start. The 7 new
  // branches take 0.02 each (0.14 total), funded by trimming 0.01 off six existing 0.05 branches
  // and 0.06 off pollNotifications — every other branch's weight is unchanged from 2026-09-27.
  const roll = Math.random();
  if (roll < 0.19) {
    pollNotifications(headers);
  } else if (roll < 0.26) {
    pollTasks(identity, headers);
  } else if (roll < 0.3) {
    pollJobTypes(headers);
  } else if (roll < 0.34) {
    crossTenantTaskProbe(identity, headers);
  } else if (roll < 0.38) {
    tamperedTokenProbe(identity);
  } else if (roll < 0.43) {
    forgedTokenVariantProbe(identity);
  } else if (roll < 0.48) {
    wrongRoleTaskCreateProbe(identity, headers);
  } else if (roll < 0.51) {
    employeeCreateEmployeeProbe(identity, headers);
  } else if (roll < 0.53) {
    employeesListProbe(identity, headers);
  } else if (roll < 0.55) {
    resetPasswordProbe(identity, headers);
  } else if (roll < 0.58) {
    employeeCreateJobTypeProbe(identity, headers);
  } else if (roll < 0.62) {
    ownerTaskCreateProbe(identity, headers);
  } else if (roll < 0.67) {
    notificationReadProbe(identity, headers);
  } else if (roll < 0.69) {
    confirmPasswordChangedProbe(identity, headers);
  } else if (roll < 0.73) {
    jobTypeUpdateProbe(identity, headers);
  } else if (roll < 0.77) {
    taskDeadlineProbe(identity, headers);
  } else if (roll < 0.79) {
    taskReviewProbe(identity, headers);
  } else if (roll < 0.81) {
    markBilledProbe(identity, headers);
  } else if (roll < 0.85) {
    employeeUpdateProbe(identity, headers);
  } else if (roll < 0.88) {
    crossTenantIssueProbe(identity, headers);
  } else if (roll < 0.9) {
    taskIssueCreateProbe(identity, headers);
  } else if (roll < 0.92) {
    issueResolveProbe(identity, headers);
  } else if (roll < 0.96) {
    claimMismatchProbe(identity);
  } else {
    businessLogicRaceProbe(identity);
  }

  sleep(1 + Math.random() * 2); // between-poll think time, not a tight request loop
}
