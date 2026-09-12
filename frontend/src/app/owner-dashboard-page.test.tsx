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
    expect(await screen.findByText("File GST return")).toBeInTheDocument();
    expect(screen.getByText("Collect billing details")).toBeInTheDocument();
    // "Already submitted" (t3) legitimately appears twice — Awaiting Review panel + All Tasks
    // table both render it, same as test below; getByText would throw on 2 matches.
    expect(screen.getAllByText("Already submitted").length).toBeGreaterThan(0);
  });

  it("shows the submitted task under Awaiting Review", async () => {
    renderDashboard();
    await screen.findByText(/awaiting review/i);
    // "Already submitted" (t3, status=submitted) appears twice: once in the Awaiting Review
    // panel, once in the All Tasks table below it — both real, not a duplicate-render bug.
    expect(await screen.findAllByText("Already submitted")).toHaveLength(2);
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
    await screen.findByText("File GST return");

    await user.click(screen.getByRole("combobox", { name: /filter by status/i }));
    await user.click(await screen.findByRole("option", { name: /^submitted$/i }));

    expect(screen.queryByText("File GST return")).not.toBeInTheDocument();
    expect(screen.queryByText("Collect billing details")).not.toBeInTheDocument();
    // "Already submitted" (t3) still legitimately renders twice — Awaiting Review + All Tasks —
    // same reasoning as the unfiltered test above; the filter narrows the underlying task list,
    // it doesn't change how many sections re-display each entry.
    expect(await screen.findAllByText("Already submitted")).toHaveLength(2);
  });

  it("narrows the All Tasks table to only billing tasks when the task-type filter is set", async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText("File GST return");

    await user.click(screen.getByRole("combobox", { name: /filter by task type/i }));
    await user.click(await screen.findByRole("option", { name: /^billing$/i }));

    expect(await screen.findByText("Collect billing details")).toBeInTheDocument();
    expect(screen.queryByText("File GST return")).not.toBeInTheDocument();
    expect(screen.queryByText("Already submitted")).not.toBeInTheDocument();
  });
});
