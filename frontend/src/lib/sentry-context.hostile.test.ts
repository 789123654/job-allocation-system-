import type { Breadcrumb } from "@sentry/react";
import { describe, expect, it } from "vitest";

import { scrubBreadcrumb } from "./sentry-context";

// Hostile-input tests for the breadcrumb scrubber (batch 1 of the 2026-09-19 review fixes), written BEFORE the
// fix and from an attacker's seat: the attacker controls what a DOM attribute contains (this app renders
// `<td title={task.description}>`, so that is client-confidential text) and wants it to reach Sentry inside a
// click breadcrumb. The scrubber must not depend on correctly PARSING attacker-controlled text, so these tests
// throw every delimiter Sentry's htmlTreeAsString output uses (quotes, brackets, " > ", newlines) at it.
//
// Each value is `MRK<hex>A` + payload + `MRK<hex>B`: a partial scrub leaves the trailing marker behind.
// Requirement rows: req_01 (no super-linear work), req_02/req_03 (no client data), req_16 (fail closed).

const HOSTILE: Record<string, string> = {
  plain: "Acme Holdings",
  double_quote: 'a"b',
  single_quote: "a'b",
  quote_bracket: '"]',
  closes_and_reopens: '"] > div[title="',
  closes_and_reopens_two: '"][name="x"] > span[alt="',
  descendant_arrow: "a > b > c",
  bracket_only: "]",
  open_bracket: "[",
  many_brackets: '"]'.repeat(50),
  newline: "line1\nline2",
  blank_line: "para1\n\npara2",
  crlf: "line1\r\nline2",
  tab: "a\tb",
  u2028: "a b",
  unicode: "héllo ✓ 😀 ‮ rtl",
  backslashes: 'a\\"b\\\\',
  regex_metachars: '(a+)+$ .* [^"]* \\d{1,9999}',
  format_lookalike: "%s %d {0} ${x}",
  html: '<img src=x onerror="alert(1)">',
  long: "x".repeat(200_000),
};

const ATTRIBUTES = ["title", "aria-label", "alt", "name"] as const;
const CATEGORIES = ["ui.click", "ui.input", "ui.keydown", "ui.", "ui", "UI.click", "ui-event"];

function newMarker(): string {
  return `MRK${Math.random().toString(16).slice(2, 14)}`;
}

function value(marker: string, payload: string): string {
  return `${marker}A${payload}${marker}B`;
}

function expectNoLeak(out: unknown, marker: string): void {
  const text = JSON.stringify(out) ?? "";
  expect(text.includes(`${marker}A`), `leaked ${marker}A`).toBe(false);
  expect(text.includes(`${marker}B`), `leaked ${marker}B`).toBe(false);
}

// the shapes htmlTreeAsString really emits: elements joined by " > ", attributes as [name="raw value"]
function shapes(v: string): Record<string, string> {
  return {
    one_attribute: `main > table > tr > td[title="${v}"]`,
    every_attribute: `a.link[aria-label="${v}"] > input[name="${v}"] > img[alt="${v}"][title="${v}"]`,
    value_first: `${v}`,
    value_after_arrow: `div#root > ${v}`,
    attribute_without_close: `td[title="${v}`,
    two_elements_forged: `td[title="${v}"] > span.x[alt="${v}"]`,
  };
}

function click(category: string, message: string): Breadcrumb {
  return { category, message, timestamp: 1, type: "default" };
}

describe("scrubBreadcrumb: no attribute value survives, whatever it contains", () => {
  for (const [pname, payload] of Object.entries(HOSTILE)) {
    for (const category of CATEGORIES) {
      it(`${category} / ${pname}`, () => {
        const marker = newMarker();
        for (const [sname, message] of Object.entries(shapes(value(marker, payload)))) {
          const result = scrubBreadcrumb(click(category, message));
          expectNoLeak(result, marker);
          expect(result, `shape ${sname} dropped the breadcrumb entirely`).not.toBeNull();
        }
      });
    }
  }
});

describe("scrubBreadcrumb: every attribute name is covered, not only the four it knows", () => {
  it("scrubs an attribute name Sentry does not currently emit", () => {
    const marker = newMarker();
    const result = scrubBreadcrumb(click("ui.click", `td[data-client="${value(marker, "secret")}"]`));
    expectNoLeak(result, marker);
  });
  it.each(ATTRIBUTES)("scrubs [%s]", (attribute) => {
    const marker = newMarker();
    const result = scrubBreadcrumb(click("ui.click", `td[${attribute}="${value(marker, 'a"]b')}"]`));
    expectNoLeak(result, marker);
  });
});

describe("scrubBreadcrumb: the data field and odd shapes", () => {
  it("does not let a ui breadcrumb carry client text in data", () => {
    const marker = newMarker();
    const crumb: Breadcrumb = {
      category: "ui.click",
      message: "td",
      data: { "ui.component_name": value(marker, "x"), nested: { deep: [value(marker, "y")] } },
    };
    expectNoLeak(scrubBreadcrumb(crumb), marker);
  });

  it("does not throw and does not leak when message is not a string", () => {
    const marker = newMarker();
    for (const bad of [123, null, { toString: () => value(marker, "x") }, [value(marker, "y")], true]) {
      const crumb = { category: "ui.click", message: bad } as unknown as Breadcrumb;
      expect(() => scrubBreadcrumb(crumb)).not.toThrow();
      expectNoLeak(scrubBreadcrumb(crumb), marker);
    }
  });

  it("tolerates a ui breadcrumb with no message and no data", () => {
    expect(() => scrubBreadcrumb({ category: "ui.click" })).not.toThrow();
  });

  it("keeps the fields that carry no client text", () => {
    const result = scrubBreadcrumb({
      category: "ui.click",
      message: 'td[title="x"]',
      level: "info",
      timestamp: 5,
      type: "default",
    });
    expect(result?.category).toBe("ui.click");
    expect(result?.level).toBe("info");
    expect(result?.timestamp).toBe(5);
  });

  it("is idempotent", () => {
    const once = scrubBreadcrumb(click("ui.click", 'td[title="a"] > b'));
    const twice = scrubBreadcrumb(once as Breadcrumb);
    expect(twice).toEqual(once);
  });
});

describe("scrubBreadcrumb: the categories it must not touch or must drop", () => {
  it.each(["console", "Console", "CONSOLE"])("drops %s breadcrumbs (raw console arguments)", (category) => {
    expect(scrubBreadcrumb({ category, message: "task: SENSITIVE", data: { arguments: ["SENSITIVE"] } })).toBeNull();
  });

  it.each(["fetch", "xhr", "navigation", "sentry.event", "info"])("passes %s through unchanged", (category) => {
    const crumb: Breadcrumb = { category, message: "GET /api/tasks", data: { url: "/api/tasks?status=open" } };
    expect(scrubBreadcrumb({ ...crumb, data: { ...crumb.data } })).toEqual(crumb);
  });

  it("passes a breadcrumb with no category through unchanged", () => {
    const crumb: Breadcrumb = { message: "hello" };
    expect(scrubBreadcrumb({ ...crumb })).toEqual(crumb);
  });
});

describe("scrubBreadcrumb: hostile size and shape never stall the UI thread", () => {
  const shapesToTry: Record<string, string> = {
    repeated_open: '[title="'.repeat(100_000),
    repeated_close: '"]'.repeat(500_000),
    repeated_arrow: " > ".repeat(300_000),
    one_huge_line: "a".repeat(5_000_000),
    alternating: 'a[title="x"] > '.repeat(100_000),
    newline_run: "\n".repeat(1_000_000),
  };
  for (const [name, message] of Object.entries(shapesToTry)) {
    it(`${name} finishes quickly`, () => {
      const started = performance.now();
      scrubBreadcrumb(click("ui.click", message));
      expect(performance.now() - started).toBeLessThan(500);
    });
  }
});
