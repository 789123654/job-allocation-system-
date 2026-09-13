import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IssueResolutionPage } from "@/features/tasks/components/issue-resolution-page";
import { resetIssuesFixture, resetTasksFixture } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderAt(issueId: string) {
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
      <MemoryRouter initialEntries={[`/owner-issues/${issueId}/resolve`]}>
        <Routes>
          <Route path="/" element={<div>OWNER-HOME</div>} />
          <Route
            path="/owner-issues/:issueId/resolve"
            element={<IssueResolutionPage employeeOptions={[]} />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("IssueResolutionPage", () => {
  beforeEach(() => {
    resetTasksFixture();
    resetIssuesFixture();
  });

  // Regression guard for the shouldUnregister fix (SECURITY_AUDIT_CHECKLIST.md, Issue Resolution
  // pass, 2026-09-13): react-hook-form otherwise keeps a conditionally-rendered field's value in
  // form state after its input unmounts, so switching resolutionType away from a branch you'd
  // partially filled leaves that branch's stale value sitting in form state, which then trips
  // issueResolveSchema's own combination guard and silently blocks submission. Originally caught
  // by a blind-authored test (deleted after reporting, per this session's verification-only
  // convention for blind passes) — kept as a permanent test because this is the one behavior this
  // slice actually needs guarded long-term, not because every blind-test assertion earns that.
  it("does not leak a previously entered deadline into a Clarify submission after switching resolution types", async () => {
    const user = userEvent.setup();
    renderAt("i1");
    await screen.findByRole("heading", { name: /file gst return/i });

    await user.click(screen.getByRole("combobox", { name: /resolution/i }));
    await user.click(await screen.findByRole("option", { name: /^adjust deadline$/i }));
    fireEvent.change(await screen.findByLabelText(/new deadline/i), { target: { value: "2026-12-25" } });

    await user.click(screen.getByRole("combobox", { name: /resolution/i }));
    await user.click(await screen.findByRole("option", { name: /^clarify$/i }));
    fireEvent.change(screen.getByLabelText(/notes/i), {
      target: { value: "Client confirmed the original deadline is fine after all." },
    });
    fireEvent.click(screen.getByRole("button", { name: /resolve issue/i }));

    expect(await screen.findByText("OWNER-HOME")).toBeInTheDocument();
  });
});
