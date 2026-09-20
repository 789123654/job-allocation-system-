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
// alt and name attribute VALUES (read from the installed @sentry/core htmlTreeAsString, 2026-09-19,
// not assumed). This app renders `<td title={task.description}>`, so a click on that cell followed
// by any error would ship client-confidential text (a CA firm's task description) to a third party
// as breadcrumb data. The attribute names stay (they still say WHAT was clicked); the values go.
// Console breadcrumbs carry raw console arguments, so they are dropped entirely.
// TCASVS 3.2.3 (app logs never hold sensitive data), ASVS 14.2.3, Logging_Cheat_Sheet.md "Data to
// exclude: commercially-sensitive".
const ATTRIBUTE_VALUES = /\[(title|aria-label|alt|name)="[^"]*"\]/g;

export function scrubBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb | null {
  if (breadcrumb.category === "console") return null;
  if (breadcrumb.category?.startsWith("ui.") && breadcrumb.message) {
    breadcrumb.message = breadcrumb.message.replace(ATTRIBUTE_VALUES, "[$1]");
  }
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
