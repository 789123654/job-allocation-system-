import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OwnerDashboardPage } from "@/app/owner-dashboard-page";
import {
  resetEmployeesFixture,
  resetIssuesFixture,
  resetJobTypesFixture,
  resetNotificationsFixture,
  resetTasksFixture,
} from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderDashboard() {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    role: "owner",
    firmId: "firm-1",
    mustChangePassword: false,
    isLoading: false,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <OwnerDashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OwnerDashboardPage", () => {
  beforeEach(() => {
    resetTasksFixture();
    resetEmployeesFixture();
    resetJobTypesFixture();
    resetNotificationsFixture();
    resetIssuesFixture();
  });

  it("lists all seeded tasks in the All Tasks table", async () => {
    renderDashboard();
    // "File GST return" (t1) legitimately appears twice: once in the All Tasks table, once
    // in Issues Raised (t1 has the seeded open issue i1) — a real consequence of linking each
    // Issues Raised entry to the new Issue Resolution screen, not a duplicate-render bug.
    expect(await screen.findAllByText("File GST return")).toHaveLength(2);
    expect(screen.getByText("Collect billing details")).toBeInTheDocument();
    // "Already submitted" (t3) appears once now — Awaiting Review is a count+link card
    // (2026-09-17 restructure), not a per-item list, so only the All Tasks table renders the
    // title itself.
    expect(screen.getAllByText("Already submitted")).toHaveLength(1);
  });

  // Reported gap, 2026-09-17: a submitted task (awaiting Owner review) had no visual flag in the
  // All Tasks table itself, only the Status column's plain text — an accent-tinted row now flags
  // it, distinct from the deadline urgency colors (t3 has no deadline, so this isolates the new
  // "submitted" rule from deadlineStatus entirely).
  it("tints a submitted task's row to flag it as awaiting review", async () => {
    renderDashboard();
    const cell = await screen.findByText("Already submitted");
    const row = cell.closest("tr");
    expect(row).toHaveClass("bg-(--color-ledger-accent)/10");
  });

  // Restructured 2026-09-17: Awaiting Review is a count + "View all" link card now, not a
  // per-item list (the untidy-as-it-grows concern) — asserting the count reflects the real
  // submitted-task total is the equivalent check to the old per-item-title assertion.
  it("shows the submitted task count under Awaiting Review", async () => {
    renderDashboard();
    expect(await screen.findByText("Awaiting Review (1)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view all/i })).toHaveAttribute(
      "href",
      "/?status=submitted",
    );
  });

  // /code-review finding (2026-09-17): "View all" used to be a static "?status=submitted" link
  // that silently dropped any other active All Tasks filter instead of merging into it. This
  // proves the merge: with job_type_id already selected, the link must carry both params, not
  // replace it with status alone.
  it("preserves an existing All Tasks filter in the Awaiting Review 'View all' link", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText("Collect billing details");

    await user.click(screen.getByRole("combobox", { name: /filter by job type/i }));
    await user.click(await screen.findByRole("option", { name: /^tax audit$/i }));

    const href = screen.getByRole("link", { name: /view all/i }).getAttribute("href") ?? "";
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("job_type_id")).toBe("jt1");
    expect(params.get("status")).toBe("submitted");
  });

  it("shows each employee's pending task count", async () => {
    renderDashboard();
    // t1 and t2 are both assigned to e1 (Alex Employee) and both status=assigned; t3 is
    // submitted, so it must not count — 2 is the real expected pending count, not 3.
    expect(await screen.findByText("Alex Employee: 2 pending")).toBeInTheDocument();
  });

  it("shows the raised issue's real description against its task title", async () => {
    renderDashboard();
    await screen.findByText(/issues raised/i);
    expect(
      await screen.findByText(/Client hasn't sent the required documents/),
    ).toBeInTheDocument();
  });

  it("renders the New task trigger", async () => {
    renderDashboard();
    expect(await screen.findByRole("button", { name: /new task/i })).toBeInTheDocument();
  });

  // Regression coverage for setFilter (owner-dashboard-page.tsx) + useAllTasks' query-param
  // building (get-all-tasks.ts) — neither was exercised by any prior test, since all of them
  // rendered with default/empty URL params. This drives a real Select selection end-to-end
  // through the MSW handler's own status filter (handlers.ts), so it fails if either the
  // component never sends the param or the handler stops honoring it — not just a rendered-JSX
  // check.
  it("narrows the All Tasks table to only submitted tasks when the status filter is set", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText("Collect billing details");

    await user.click(screen.getByRole("combobox", { name: /filter by status/i }));
    await user.click(await screen.findByRole("option", { name: /^submitted$/i }));

    // "File GST return" (t1) is excluded from the (now-filtered) All Tasks table, but still
    // appears once via the filter-independent Issues Raised panel — it must not vanish entirely.
    expect(await screen.findAllByText("File GST return")).toHaveLength(1);
    expect(screen.queryByText("Collect billing details")).not.toBeInTheDocument();
    // "Already submitted" (t3) now renders once — only via the All Tasks table (which the
    // status=submitted filter correctly includes it in); Awaiting Review is a count card, not a
    // per-item list.
    expect(await screen.findAllByText("Already submitted")).toHaveLength(1);
  });

  // Reported gap, 2026-09-17: filters.jobTypeId/useAllTasks already accepted job_type_id, but no
  // Select ever rendered it — the only filters an Owner could actually use were Status and the
  // unrelated Standard/Billing task type, never the Owner's own job types. None of the seeded
  // tasks have jt1 ("Tax Audit") as their job type, so selecting it is a real, meaningful filter:
  // every seeded task must disappear from All Tasks.
  it("narrows the All Tasks table by job type when the job-type filter is set", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText("Collect billing details");

    await user.click(screen.getByRole("combobox", { name: /filter by job type/i }));
    await user.click(await screen.findByRole("option", { name: /^tax audit$/i }));

    expect(screen.queryByText("Collect billing details")).not.toBeInTheDocument();
    // "File GST return" (t1) still appears once via the filter-independent Issues Raised panel.
    expect(screen.getAllByText("File GST return")).toHaveLength(1);
    expect(screen.queryByText("Already submitted")).not.toBeInTheDocument();
  });

  // Regression for the code-review finding (2026-09-13): Awaiting Review and Issues Raised were
  // previously derived from the same filtered task list as the All Tasks table, so applying any
  // All Tasks filter silently hid unrelated entries from those other panels too. A prior version
  // of this test suite actually asserted that disappearance as expected, passing behavior. The
  // 2026-09-17 restructure changed Awaiting Review's shape (count+link, not a per-item list) but
  // the same real invariant is what this test has to keep proving: its count must come from the
  // unfiltered `allTasks`, not `filteredTasks` — if that regressed, this filter (status=assigned,
  // which excludes the one submitted task) would wrongly drop the count to 0.
  it("keeps the Awaiting Review count unaffected even when the All Tasks status filter excludes that task", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText("Collect billing details");

    await user.click(screen.getByRole("combobox", { name: /filter by status/i }));
    await user.click(await screen.findByRole("option", { name: /^assigned$/i }));

    // All Tasks now shows only the two assigned tasks — "Already submitted" (t3, status=submitted)
    // is correctly excluded from that table. "File GST return" (t1) appears twice here: once in
    // All Tasks (still assigned, so included by this filter) and once in Issues Raised.
    expect(await screen.findAllByText("File GST return")).toHaveLength(2);
    expect(screen.getByText("Collect billing details")).toBeInTheDocument();
    expect(screen.queryByText("Already submitted")).not.toBeInTheDocument();
    // ...but Awaiting Review's count must never be affected by the All Tasks filter.
    expect(screen.getByText("Awaiting Review (1)")).toBeInTheDocument();
  });
});
