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

  it.each(["sentry.event", "info"])("passes %s through unchanged (no url-shaped data)", (category) => {
    const crumb: Breadcrumb = { category, message: "GET /api/tasks", data: { note: "not a url field" } };
    expect(scrubBreadcrumb({ ...crumb, data: { ...crumb.data } })).toEqual(crumb);
  });

  // batch 2 slice 3 (req_23): fetch/xhr/navigation data.url|from|to are stripped to scheme+host,
  // not passed through — see sentry-context.test.ts for the behavioral assertions. Everything else
  // on the breadcrumb (category, message, non-url data keys) is untouched.
  it.each(["fetch", "xhr", "navigation"])("%s keeps its category and non-url fields", (category) => {
    const crumb: Breadcrumb = { category, message: "GET /api/tasks", data: { status_code: 200 } };
    const result = scrubBreadcrumb({ ...crumb, data: { ...crumb.data } });
    expect(result?.category).toBe(category);
    expect(result?.message).toBe("GET /api/tasks");
    expect(result?.data?.status_code).toBe(200);
  });

  it("passes a breadcrumb with no category through unchanged", () => {
    const crumb: Breadcrumb = { message: "hello" };
    expect(scrubBreadcrumb({ ...crumb })).toEqual(crumb);
  });

  // A hand-rolled mutation pass (req_40) found no test exercised a non-string, non-nullish
  // category (e.g. a number): `breadcrumb.category?.toLowerCase()` -- a mutant of the real
  // `typeof === "string"` guard -- crashes on `(123).toLowerCase is not a function` while still
  // passing every other test here, since undefined/null were already covered.
  it.each([123, true, {}, [], () => 1])("does not throw when category is %s (not a string, not nullish)", (bad) => {
    const crumb = { category: bad, message: "hello" } as unknown as Breadcrumb;
    expect(() => scrubBreadcrumb(crumb)).not.toThrow();
  });
});

// batch 2 slice 3 (req_23): hostile URL payloads for the new data.url/from/to stripping. Same
// marker convention as the section above: a partial strip leaves the trailing marker behind.
describe("scrubBreadcrumb: no query string or fragment survives in url/from/to, whatever it contains", () => {
  const HOSTILE_URLS: Record<string, string> = {
    plain_query: "http://api.example.test/tasks?search=MARKER",
    fragment_only: "http://api.example.test/tasks#MARKER",
    query_and_fragment: "http://api.example.test/tasks?search=MARKER#MARKER2",
    credentials_embedded: "http://user:MARKER@api.example.test/tasks",
    relative_with_query: "/tasks?search=MARKER",
    relative_dot: "./tasks?search=MARKER",
    protocol_relative: "//api.example.test/tasks?search=MARKER",
    double_encoded: "http://api.example.test/tasks?q=%2557MARKER",
    many_params: "http://api.example.test/tasks?" + Array.from({ length: 50 }, (_, i) => `p${i}=MARKER`).join("&"),
    javascript_uri: "javascript:MARKER",
    data_uri: "data:text/plain,MARKER",
    unicode_query: "http://api.example.test/tasks?q=héllo-MARKER-✓",
    newline_in_query: "http://api.example.test/tasks?q=line1%0AMARKER",
    very_long_query: `http://api.example.test/tasks?q=${"MARKER".repeat(10_000)}`,
    not_a_url_at_all: "MARKER not a url just text",
    empty_string: "",
  };

  for (const key of ["url", "from", "to"] as const) {
    describe(`data.${key}`, () => {
      for (const [pname, urlTemplate] of Object.entries(HOSTILE_URLS)) {
        it(pname, () => {
          const payload = urlTemplate.replace(/MARKER2?/g, (m) => (m === "MARKER2" ? "SECONDMARK" : "SECRETMARK"));
          const crumb: Breadcrumb = { category: "fetch", data: { [key]: payload } };
          const result = scrubBreadcrumb(crumb);
          const text = JSON.stringify(result) ?? "";
          expect(text.includes("SECRETMARK"), `${key}=${payload} leaked SECRETMARK`).toBe(false);
          expect(text.includes("SECONDMARK"), `${key}=${payload} leaked SECONDMARK`).toBe(false);
        });
      }
    });
  }

  it("does not throw and does not leak when url is not a string", () => {
    for (const bad of [123, null, undefined, { toString: () => "SECRETMARK" }, ["SECRETMARK"], true]) {
      const crumb = { category: "fetch", data: { url: bad } } as unknown as Breadcrumb;
      expect(() => scrubBreadcrumb(crumb)).not.toThrow();
      const text = JSON.stringify(scrubBreadcrumb(crumb)) ?? "";
      expect(text.includes("SECRETMARK")).toBe(false);
    }
  });

  it("tolerates a breadcrumb with no data at all", () => {
    expect(() => scrubBreadcrumb({ category: "fetch" })).not.toThrow();
    expect(() => scrubBreadcrumb({ category: "navigation", data: {} })).not.toThrow();
  });

  it("is idempotent on a fetch breadcrumb", () => {
    const once = scrubBreadcrumb({ category: "fetch", data: { url: "http://api.example.test/tasks?q=1" } });
    const twice = scrubBreadcrumb({ ...once, data: { ...once?.data } } as Breadcrumb);
    expect(twice).toEqual(once);
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
