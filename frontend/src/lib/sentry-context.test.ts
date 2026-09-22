import type { Breadcrumb, ErrorEvent } from "@sentry/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildSentryOptions,
  scrubBreadcrumb,
  setSentryTenant,
  type TransactionEvent,
} from "@/lib/sentry-context";

const TENANT = "11111111-2222-4333-8444-555555555555";

const options = buildSentryOptions({
  dsn: "https://key@example.invalid/1",
  release: "build-abc123",
  environment: "production",
});

async function tagged(event: ErrorEvent): Promise<ErrorEvent | null> {
  return await options.beforeSend!(event, {});
}

const errorEvent = (tags?: Record<string, string>) => ({ tags }) as ErrorEvent;

afterEach(() => setSentryTenant(null));

describe("Sentry tenant tag", () => {
  it("is added to error events while a firm is signed in", async () => {
    setSentryTenant(TENANT);
    expect((await tagged(errorEvent()))?.tags).toEqual({ tenant_id: TENANT });
  });

  it("is added to transactions too", async () => {
    setSentryTenant(TENANT);
    const event = { type: "transaction" } as TransactionEvent;
    const result = await options.beforeSendTransaction!(event, {});
    expect(result?.tags).toEqual({ tenant_id: TENANT });
  });

  // The whole reason this isn't Sentry.setTag(): a stale firm on a post-logout report is worse than none.
  it("is gone again after the session ends", async () => {
    setSentryTenant(TENANT);
    setSentryTenant(null);
    expect((await tagged(errorEvent()))?.tags).toBeUndefined();
  });

  it("follows a switch to a different firm", async () => {
    setSentryTenant(TENANT);
    const other = "99999999-8888-4777-8666-555555555555";
    setSentryTenant(other);
    expect((await tagged(errorEvent()))?.tags?.tenant_id).toBe(other);
  });

  it("keeps the event's existing tags", async () => {
    setSentryTenant(TENANT);
    expect((await tagged(errorEvent({ page: "tasks" })))?.tags).toEqual({
      page: "tasks",
      tenant_id: TENANT,
    });
  });

  // The value comes from a JWT claim; Sentry tag values are <=200 chars with no newline.
  it.each([
    ["not a uuid", "real-firm-id"],
    ["newline injection", `${TENANT}\nforged`],
    ["too long", "a".repeat(201)],
    ["empty", ""],
  ])("drops a value that is not a plain UUID (%s)", async (_label, value) => {
    setSentryTenant(value);
    expect((await tagged(errorEvent()))?.tags).toBeUndefined();
  });

  it("normalises an upper-case UUID", async () => {
    setSentryTenant(TENANT.toUpperCase());
    expect((await tagged(errorEvent()))?.tags?.tenant_id).toBe(TENANT);
  });

  it("adds nothing about the person: no user, email or other tag", async () => {
    setSentryTenant(TENANT);
    const result = await tagged(errorEvent());
    expect(Object.keys(result?.tags ?? {})).toEqual(["tenant_id"]);
    expect(result).not.toHaveProperty("user");
  });
});

describe("buildSentryOptions", () => {
  it("stamps release and environment and wires all three hooks", () => {
    expect(options.release).toBe("build-abc123");
    expect(options.environment).toBe("production");
    expect(options.tracesSampleRate).toBe(1.0);
    expect(options.beforeSend).toBeTypeOf("function");
    expect(options.beforeSendTransaction).toBeTypeOf("function");
    expect(options.beforeBreadcrumb).toBeTypeOf("function");
  });

  // Same deliberate stance as the backend (main.py): no automatic PII collection.
  it("does not turn on default PII collection", () => {
    expect(options).not.toHaveProperty("sendDefaultPii");
  });
});

describe("scrubBreadcrumb", () => {
  const click = (message: string): Breadcrumb => ({ category: "ui.click", message });

  // Contract changed on 2026-09-21 (docs/SECURITY_AUDIT_CHECKLIST.md req_16): a ui breadcrumb FAILS CLOSED,
  // it no longer describes the clicked element at all. The hostile-input suite is sentry-context.hostile.test.ts.
  it("removes the task description (a title value) from a click", () => {
    const description = "a making a legal will of the 100 cr property of the mr verma";
    const result = scrubBreadcrumb(click(`main > table > tr > td[title="${description}"]`));
    expect(JSON.stringify(result)).not.toContain("verma");
    expect(result?.message).toBe("[element detail removed]");
  });

  it.each(["title", "aria-label", "alt", "name"])("does not carry the %s attribute value", (attribute) => {
    const result = scrubBreadcrumb(click(`button[${attribute}="SENSITIVE-TEXT"]`));
    expect(JSON.stringify(result)).not.toContain("SENSITIVE-TEXT");
  });

  it("gives every ui click the same fixed message, whatever the path was", () => {
    const result = scrubBreadcrumb(click('a.link[aria-label="one"] > img[alt="two"][title="three"]'));
    expect(result?.message).toBe("[element detail removed]");
  });

  it("also blanks a click with nothing sensitive in its path: the accepted cost of failing closed", () => {
    expect(scrubBreadcrumb(click("div#root > button.btn"))?.message).toBe("[element detail removed]");
  });

  it("drops console breadcrumbs, which carry raw console arguments", () => {
    expect(
      scrubBreadcrumb({ category: "console", message: "task: SENSITIVE", data: { arguments: [] } }),
    ).toBeNull();
  });

  // Contract changed 2026-09-22 (batch 2 slice 3, req_23): fetch/xhr/navigation breadcrumbs used to
  // pass through unchanged, but @sentry/browser populates their `data.url`/`data.from`/`data.to`
  // with the literal request/route path+query, unsanitised (confirmed by reading the installed SDK
  // source). Non-URL fields (method, status_code) still pass through untouched.
  it("strips path and query from a fetch breadcrumb's url, keeps method/status_code", () => {
    const fetchCrumb: Breadcrumb = {
      category: "fetch",
      data: { url: "http://localhost:8000/tasks?search=confidential", method: "GET", status_code: 200 },
    };
    const result = scrubBreadcrumb({ ...fetchCrumb, data: { ...fetchCrumb.data } });
    expect(result?.data?.url).toBe("http://localhost:8000");
    expect(result?.data?.method).toBe("GET");
    expect(result?.data?.status_code).toBe(200);
  });

  it("strips path and query from a navigation breadcrumb's from/to", () => {
    const nav: Breadcrumb = { category: "navigation", data: { from: "/tasks?q=secret", to: "/employees" } };
    const result = scrubBreadcrumb({ ...nav, data: { ...nav.data } });
    expect(result?.data?.from).not.toContain("secret");
    expect(result?.data?.to).not.toContain("/employees");
  });

  // A hand-rolled mutation pass (Stryker itself crashes on this machine, see req_40) found that
  // dropping the `new URL(url, BASE)` base argument still "passed" the test above: every relative
  // (same-origin) URL then throws on parse and silently falls back to the placeholder, which also
  // happens to contain no secret -- a real assertion-strength gap, not just a leak check. This
  // asserts the CORRECT resolved value for a benign relative URL, not just "no leak".
  it("resolves a benign relative navigation url to this page's real origin, not the fallback placeholder", () => {
    const nav: Breadcrumb = { category: "navigation", data: { from: "/tasks", to: "/" } };
    const result = scrubBreadcrumb({ ...nav, data: { ...nav.data } });
    expect(result?.data?.from).toBe(window.location.origin);
    expect(result?.data?.to).toBe(window.location.origin);
    expect(result?.data?.from).not.toBe("[stripped: ASVS 14.2.1, never sent to Sentry]");
  });

  // `new URL()` itself throws on a handful of malformed absolute URLs (confirmed live in node: e.g.
  // "http://" with no host) — the catch branch falls back to a fixed placeholder rather than leaving
  // the unparseable (but possibly still sensitive) original string in place.
  it("falls back to a fixed placeholder when the url string itself is unparseable", () => {
    const crumb: Breadcrumb = { category: "fetch", data: { url: "http://" } };
    const result = scrubBreadcrumb({ ...crumb, data: { ...crumb.data } });
    expect(result?.data?.url).toBe("[stripped: ASVS 14.2.1, never sent to Sentry]");
  });

  it("tolerates a ui breadcrumb with no message", () => {
    expect(scrubBreadcrumb({ category: "ui.click" })?.category).toBe("ui.click");
  });
});
