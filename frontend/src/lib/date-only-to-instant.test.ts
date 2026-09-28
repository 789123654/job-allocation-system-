import { describe, expect, it } from "vitest";
import { dateOnlyToEndOfDayIso } from "@/lib/date-only-to-instant";

// Ordinary regression test, not blind — this is pure date arithmetic (code-review finding #12,
// 2026-09-14), not a security boundary, so no adversarial framing is warranted.
//
// Research (failure-6 manner — grepped whole directories, not just familiar filenames, before
// concluding rather than assuming): owasp-wstg/chapters and owasp-cheatsheets/cheatsheets have no
// procedure or guidance covering date-boundary/timezone arithmetic specifically — Input_Validation
// _Cheat_Sheet.md (the closest-sounding candidate) has no date-format section at all. Honestly
// reporting no applicable OWASP citation here rather than forcing one; this test exists purely to
// close a real mutation-testing gap (`month - 1` mutated to `month + 1` survived the full suite —
// see the second test below for why).
describe("dateOnlyToEndOfDayIso", () => {
  function expectEndOfDayLocal(dateOnly: string, year: number, month: number, day: number): void {
    const result = new Date(dateOnlyToEndOfDayIso(dateOnly));
    expect(result.getFullYear()).toBe(year);
    expect(result.getMonth()).toBe(month - 1); // JS Date months are 0-indexed
    expect(result.getDate()).toBe(day);
    expect(result.getHours()).toBe(23);
    expect(result.getMinutes()).toBe(59);
    expect(result.getSeconds()).toBe(59);
    expect(result.getMilliseconds()).toBe(999);
  }

  it("resolves a mid-year date to that day's last local instant", () => {
    expectEndOfDayLocal("2026-06-15", 2026, 6, 15);
  });

  it("does not roll over into the next year for December — kills the exact mutant that survived (month - 1 vs month + 1)", () => {
    // `month + 1` instead of `month - 1` feeds month index 12 (December, correctly 0-indexed as
    // 11, wrongly computed as 12) into the Date constructor, which normalizes month 12 into
    // January of the FOLLOWING year — an obviously wrong, dramatic failure this case is built to
    // catch. This is the mutation the frontend mutation-testing sweep found surviving the full
    // existing suite (2026-09-15) — no dedicated unit test asserted on the actual computed date
    // before this file existed, only indirectly through UI form-submission tests.
    expectEndOfDayLocal("2026-12-31", 2026, 12, 31);
  });

  it("does not roll back into the previous year for January", () => {
    expectEndOfDayLocal("2026-01-01", 2026, 1, 1);
  });

  it("handles a real leap-day date correctly", () => {
    expectEndOfDayLocal("2028-02-29", 2028, 2, 29); // 2028 is a genuine leap year
  });

  it("returns a real, round-trippable ISO 8601 string", () => {
    const result = dateOnlyToEndOfDayIso("2026-07-04");
    expect(new Date(result).toISOString()).toBe(result);
  });
});
