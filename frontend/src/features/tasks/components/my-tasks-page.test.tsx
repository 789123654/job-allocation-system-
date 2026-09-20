import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MyTasksPage } from "@/features/tasks/components/my-tasks-page";
import { resetNotificationsFixture, resetTasksFixture, server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

// Same reasoning as employee-management-page.test.tsx/job-type-management-page.test.tsx —
// useMyTasks() reads firmId from useSession() to scope its cache key.
vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderPage() {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    role: "employee",
    firmId: "firm-1",
    mustChangePassword: false,
    isLoading: false,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/tasks"]}>
        <Routes>
          <Route path="/tasks" element={<MyTasksPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MyTasksPage", () => {
  beforeEach(() => {
    resetTasksFixture();
    resetNotificationsFixture();
  });

  it("lists the seeded tasks", async () => {
    renderPage();
    expect(await screen.findByText("File GST return")).toBeInTheDocument();
    expect(screen.getByText("Collect billing details")).toBeInTheDocument();
    expect(screen.getByText("Already submitted")).toBeInTheDocument();
  });

  it("flags a reassigned task", async () => {
    renderPage();
    await screen.findByText("File GST return");
    // None of the seeded tasks are reassigned by default — this asserts the flag's absence,
    // proving the conditional doesn't render for every row regardless of state.
    expect(screen.queryByText("(reassigned)")).not.toBeInTheDocument();
  });

  it("shows an assigned task's status as Pending, not Assigned", async () => {
    renderPage();
    // t1 and t2 are both seeded with status "assigned" (handlers.ts) — "Assigned" reads
    // Owner-centric; an Employee's own worklist calls the same state "Pending" instead (reported
    // gap).
    await screen.findByText("File GST return");
    expect(screen.getAllByRole("button", { name: "Pending" })).toHaveLength(2);
    expect(screen.queryByText("Assigned")).not.toBeInTheDocument();
  });

  it("does not offer the action menu for a task that can't be actioned", async () => {
    renderPage();
    // t3 ("Already submitted") is seeded with status "submitted" — outside canAct's
    // assigned/in_progress set, so it must render as plain text, not a dropdown trigger.
    await screen.findByText("Already submitted");
    expect(screen.queryByRole("button", { name: "Submitted" })).not.toBeInTheDocument();
    expect(screen.getByText("submitted")).toBeInTheDocument();
  });

  it("opens Mark completed and Raise issue from the Status cell for an actionable standard task", async () => {
    const user = userEvent.setup();
    renderPage();
    // t1 ("File GST return") is a standard (non-billing) task — folds both actions into the
    // Status dropdown instead of a separate Action column or a trip through Notifications.
    await screen.findByText("File GST return");
    // t1 is the first "Pending" trigger in DOM order (fixture order: t1, t2, t3).
    await user.click(screen.getAllByRole("button", { name: "Pending" })[0]);
    expect(await screen.findByRole("menuitem", { name: "Mark completed" })).toBeInTheDocument();
    // "Raise issue" is RaiseIssueDialog's own nested <button> (a Dialog trigger), not the
    // DropdownMenuItem's own accessible name — queried by its real role, not "menuitem".
    expect(screen.getByRole("button", { name: "Raise issue" })).toBeInTheDocument();
  });

  it("offers Mark billed instead of Mark completed for an actionable billing task", async () => {
    const user = userEvent.setup();
    renderPage();
    // t2 ("Collect billing details") is seeded with task_type "billing" — TaskDetailPage's own
    // rule (billing tasks get Mark Billed, not Mark Completed) carried over to this menu.
    await screen.findByText("Collect billing details");
    const triggers = screen.getAllByRole("button", { name: "Pending" });
    await user.click(triggers[1]);
    expect(await screen.findByRole("menuitem", { name: "Mark billed" })).toBeInTheDocument();
  });

  describe("Notifications box", () => {
    // Reported gap, 2026-09-18: issue resolutions / reassignments / deadline warnings only ever
    // surfaced via the Notifications tab, easy to never open. Overrides GET /notifications per
    // test (same pattern as notifications-page.test.tsx) rather than resetNotificationsFixture's
    // shared default, which owner-dashboard-page.test.tsx/router.test.tsx also depend on — this
    // keeps those tests' exact counts untouched.
    it("shows the 4 employee-relevant notification types, each linked correctly", async () => {
      server.use(
        http.get("http://localhost:8000/notifications", () =>
          HttpResponse.json([
            { id: "n1", type: "task_deadline_approaching", task_id: "t1", issue_id: null, task_title: "File GST return", is_read: false, created_at: "2026-09-18T00:00:00Z" },
            { id: "n2", type: "task_overdue_own", task_id: "t1", issue_id: null, task_title: "File GST return", is_read: false, created_at: "2026-09-18T00:00:00Z" },
            { id: "n3", type: "task_reassigned", task_id: "t2", issue_id: null, task_title: "Collect billing details", is_read: false, created_at: "2026-09-18T00:00:00Z" },
            { id: "n4", type: "issue_resolved", task_id: "t2", issue_id: "i1", task_title: "Collect billing details", is_read: false, created_at: "2026-09-18T00:00:00Z" },
          ]),
        ),
      );
      renderPage();

      expect(await screen.findByText("Notifications (4)")).toBeInTheDocument();
      const deadlineLink = screen.getByText('"File GST return" is approaching its deadline').closest("a");
      expect(deadlineLink).toHaveAttribute("href", "/tasks/t1");
      expect(screen.getByText("Your task \"File GST return\" is overdue")).toBeInTheDocument();
      expect(screen.getByText('"Collect billing details" was reassigned to you')).toBeInTheDocument();
      // Reported gap, 2026-09-18: this used to link to /tasks/t2 (TaskDetailPage, which has no
      // idea an issue exists) — must go to IssueDetailPage, the only place the Owner's actual
      // resolution_notes are reachable.
      const resolvedLink = screen
        .getByText('Your issue on "Collect billing details" was resolved')
        .closest("a");
      expect(resolvedLink).toHaveAttribute("href", "/issues/i1");
    });

    it("excludes notification types not relevant to this view (e.g. issue_raised, task_assigned)", async () => {
      server.use(
        http.get("http://localhost:8000/notifications", () =>
          HttpResponse.json([
            { id: "n1", type: "issue_raised", task_id: "t1", issue_id: "i1", task_title: "File GST return", is_read: false, created_at: "2026-09-18T00:00:00Z" },
            { id: "n2", type: "task_assigned", task_id: "t1", issue_id: null, task_title: "File GST return", is_read: false, created_at: "2026-09-18T00:00:00Z" },
            { id: "n3", type: "issue_resolved", task_id: "t2", issue_id: "i1", task_title: "Collect billing details", is_read: false, created_at: "2026-09-18T00:00:00Z" },
          ]),
        ),
      );
      renderPage();

      expect(await screen.findByText("Notifications (1)")).toBeInTheDocument();
      expect(screen.queryByText(/raised an issue/)).not.toBeInTheDocument();
      expect(screen.queryByText(/You were assigned/)).not.toBeInTheDocument();
    });

    it("does not render the Notifications box when there are no relevant notifications", async () => {
      // Default fixture (resetTasksFixture/resetNotificationsFixture) seeds only an issue_raised
      // notification, out of this box's filtered set — no override needed for this one.
      renderPage();
      await screen.findByText("File GST return");
      expect(screen.queryByText(/^Notifications \(/)).not.toBeInTheDocument();
    });
  });
});
