import type { Breadcrumb, BrowserOptions, ErrorEvent } from "@sentry/react";

// @sentry/react re-exports ErrorEvent but not TransactionEvent (it lives in @sentry/core, a
// transitive dependency we don't import directly), so derive it from the option that receives it.
export type TransactionEvent = Parameters<NonNullable<BrowserOptions["beforeSendTransaction"]>>[0];

// Tenant tag for Sentry events, attached in beforeSend from this module variable rather than via
// Sentry.setTag(): the SDK documents that setTag writes to the isolation scope but documents no way
// to REMOVE a tag, and a stale tenant on an event after logout/switch is worse than none (the
// Logging Cheat Sheet's "attacker causes the wrong identity to be logged" applies to whoever reads
// these events too). A variable we own is trivially cleared and easy to test.
//
// The value is validated as a UUID before it can become a tag: it comes from a JWT claim, and
// Sentry tag values must be <=200 chars with no newline (Sentry's tag docs) — anything else is
// dropped, never sent. Opaque tenant UUID only: no user, email or name (ASVS 14.2.3, TCASVS 3.2.3).
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

let currentTenantId: string | null = null;

export function setSentryTenant(firmId: string | null): void {
  currentTenantId = firmId !== null && UUID_RE.test(firmId) ? firmId.toLowerCase() : null;
}

function withTenantTag<T extends ErrorEvent | TransactionEvent>(event: T): T {
  if (currentTenantId !== null) {
    event.tags = { ...event.tags, tenant_id: currentTenantId };
  }
  return event;
}

// Sentry's default click breadcrumbs describe the element by tag/class/id AND its title, aria-label,
// alt and name attribute VALUES, written raw and unescaped (read from the installed @sentry/core
// htmlTreeAsString, 2026-09-19, not assumed). This app renders `<td title={task.description}>`, so a
// click on that cell followed by any error would ship client-confidential text (a CA firm's task
// description) to a third party as breadcrumb data.
//
// FAIL CLOSED (2026-09-21). The first version stripped the attribute values with a regex. An independent
// review showed why that cannot be made safe: the value is attacker-controlled text that may itself contain
// the quotes, brackets and " > " the grammar is built from, so any pattern that has to PARSE it can be
// walked past (a title containing a double quote already leaked). So a `ui.*` breadcrumb now keeps only its
// category, type, level and timestamp: the message is replaced with a fixed string and the data removed.
// The cost, accepted: Sentry no longer shows WHICH element was clicked. ASVS 1.3.12, TCASVS 3.2.3,
// Logging_Cheat_Sheet.md "Data to exclude: commercially-sensitive".
//
// Console breadcrumbs carry raw console arguments, so they are dropped entirely. Categories are compared
// case-insensitively because a category we did not anticipate must not become a way around the scrubber.
const UI_DETAIL_REMOVED = "[element detail removed]";

// BATCH 2 SLICE 3 (2026-09-22). `fetch`/`xhr` breadcrumbs carry `data.url` and `navigation`
// breadcrumbs carry `data.from`/`data.to`, all populated by @sentry/browser's own instrumentation
// (confirmed by reading the installed integrations/breadcrumbs.js and browser-utils/instrument/
// xhr.js, not assumed) with NO sanitisation: `xhr.js` stores exactly the string this app's own
// fetch call passed to `${env.API_BASE_URL}${path}` (api-client.ts), and `navigation`'s `from`/`to`
// go through @sentry/core's `parseUrl`, whose `relative` field is literally `path + query +
// fragment` for a same-origin URL. So a search page's `?q=<client-confidential text>` or a
// `/employees?email=...` reset-password path would reach Sentry raw.
//
// Deliberately mirrors the backend's `_strip_url_path_and_query` (sentry_config.py) rather than
// inventing a second convention: a URL is arbitrary client-supplied text with no shape a scrubber
// can selectively redact (same reasoning as this file's own `ui.*` fail-closed decision above), so
// path/query/fragment are dropped entirely and only scheme+host survives. Accepted cost, same as
// the backend's: which specific endpoint/page is no longer visible from the breadcrumb alone.
const STRIPPED_URL = "[stripped: ASVS 14.2.1, never sent to Sentry]";
const URL_KEYS = ["url", "from", "to"] as const;

function stripUrlPathAndQuery(url: string): string {
  try {
    return new URL(url, window.location.origin).origin;
  } catch {
    return STRIPPED_URL;
  }
}

function stripUrlsFromData(data: Breadcrumb["data"]): void {
  if (!data) return;
  for (const key of URL_KEYS) {
    // Fail closed on the key's presence, not its shape: the real SDK only ever puts a string here
    // (confirmed by reading xhr.js/fetch.js/navigation's history handler), but a hostile-input test
    // for this exact function found that an unexpected non-string value (array/object) was being
    // left untouched -- same "malformed shape is worse to trust than to replace" reasoning as the
    // backend's _exception_entries/_breadcrumb_entries tolerance.
    if (key in data) {
      data[key] = typeof data[key] === "string" ? stripUrlPathAndQuery(data[key]) : STRIPPED_URL;
    }
  }
}

export function scrubBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb | null {
  const category = typeof breadcrumb.category === "string" ? breadcrumb.category.toLowerCase() : "";
  if (category === "console") return null;
  if (category.startsWith("ui")) {
    breadcrumb.message = UI_DETAIL_REMOVED;
    delete breadcrumb.data;
    return breadcrumb;
  }
  stripUrlsFromData(breadcrumb.data);
  return breadcrumb;
}

export function buildSentryOptions(config: {
  dsn: string;
  release: string | undefined;
  environment: string;
}): BrowserOptions {
  return {
    dsn: config.dsn,
    release: config.release,
    environment: config.environment,
    tracesSampleRate: 1.0,
    beforeSend: withTenantTag,
    beforeSendTransaction: withTenantTag,
    beforeBreadcrumb: scrubBreadcrumb,
  };
}
