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

  it("removes attribute VALUES (a task description in a title) but keeps what was clicked", () => {
    const description = "a making a legal will of the 100 cr property of the mr verma";
    const result = scrubBreadcrumb(click(`main > table > tr > td[title="${description}"]`));
    expect(result?.message).toBe("main > table > tr > td[title]");
    expect(JSON.stringify(result)).not.toContain("verma");
  });

  it.each(["title", "aria-label", "alt", "name"])("scrubs the %s attribute value", (attribute) => {
    const result = scrubBreadcrumb(click(`button[${attribute}="SENSITIVE-TEXT"]`));
    expect(result?.message).toBe(`button[${attribute}]`);
  });

  it("scrubs every attribute in a multi-attribute path", () => {
    const result = scrubBreadcrumb(click('a.link[aria-label="one"] > img[alt="two"][title="three"]'));
    expect(result?.message).toBe("a.link[aria-label] > img[alt][title]");
  });

  it("leaves a click with nothing sensitive in its path untouched", () => {
    expect(scrubBreadcrumb(click("div#root > button.btn"))?.message).toBe("div#root > button.btn");
  });

  it("drops console breadcrumbs, which carry raw console arguments", () => {
    expect(
      scrubBreadcrumb({ category: "console", message: "task: SENSITIVE", data: { arguments: [] } }),
    ).toBeNull();
  });

  it("passes network and navigation breadcrumbs through unchanged", () => {
    const fetchCrumb: Breadcrumb = {
      category: "fetch",
      data: { url: "http://localhost:8000/tasks", status_code: 200 },
    };
    expect(scrubBreadcrumb(fetchCrumb)).toEqual(fetchCrumb);
    const nav: Breadcrumb = { category: "navigation", data: { from: "/tasks", to: "/" } };
    expect(scrubBreadcrumb(nav)).toEqual(nav);
  });

  it("tolerates a ui breadcrumb with no message", () => {
    expect(scrubBreadcrumb({ category: "ui.click" })).toEqual({ category: "ui.click" });
  });
});
