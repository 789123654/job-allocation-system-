import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deadlineStatus } from "@/features/tasks/utils/deadline-status";

// Fixed clock so "1 day away"/"overdue" boundaries are deterministic, not flaky against real time.
const NOW = new Date("2026-09-17T12:00:00Z");

describe("deadlineStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns null when there is no deadline", () => {
    expect(deadlineStatus({ deadline: null, status: "assigned" })).toBeNull();
  });

  it("returns 'overdue' when the deadline has already passed", () => {
    expect(
      deadlineStatus({ deadline: "2026-09-17T11:59:59Z", status: "in_progress" }),
    ).toBe("overdue");
  });

  it("returns 'urgent' when the deadline is within 1 day (matching the task_deadline_1_day notification window)", () => {
    expect(
      deadlineStatus({ deadline: "2026-09-18T11:59:59Z", status: "assigned" }),
    ).toBe("urgent");
  });

  it("returns null when the deadline is more than 1 day away", () => {
    expect(
      deadlineStatus({ deadline: "2026-09-18T12:00:01Z", status: "assigned" }),
    ).toBeNull();
  });

  // Mirrors backend crud.py's _ACTIVE_TASK_STATUSES — a completed/billed task must never be
  // flagged overdue/urgent even if its deadline was in the past, same as it never fires a
  // deadline notification server-side.
  it.each(["completed", "billed"] as const)(
    "returns null for a %s task even when its deadline is in the past",
    (status) => {
      expect(deadlineStatus({ deadline: "2026-09-01T00:00:00Z", status })).toBeNull();
    },
  );

  it.each(["created", "assigned", "in_progress", "submitted"] as const)(
    "flags a %s task as overdue when its deadline is in the past",
    (status) => {
      expect(deadlineStatus({ deadline: "2026-09-01T00:00:00Z", status })).toBe("overdue");
    },
  );
});
