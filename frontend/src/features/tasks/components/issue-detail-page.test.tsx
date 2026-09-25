import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IssueDetailPage } from "@/features/tasks/components/issue-detail-page";
import { resetIssuesFixture, resetTasksFixture, server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

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
      <MemoryRouter initialEntries={["/issues/i1"]}>
        <Routes>
          <Route path="/issues/:issueId" element={<IssueDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Reported gap, 2026-09-18: an Employee's "issue resolved" notification used to open
// TaskDetailPage, which has no idea an issue exists — the Owner's resolution_notes were
// unreachable. This is the raiser's read-only counterpart to IssueResolutionPage.
describe("IssueDetailPage", () => {
  beforeEach(() => {
    resetTasksFixture();
    resetIssuesFixture();
  });

  it("shows the task title and the raised description while the issue is still open", async () => {
    renderPage();
    expect(await screen.findByText("File GST return")).toBeInTheDocument();
    expect(screen.getByText("Client hasn't sent the required documents")).toBeInTheDocument();
    expect(screen.getByText("Awaiting the owner's response.")).toBeInTheDocument();
  });

  it("shows the owner's resolution once the issue is resolved (clarified)", async () => {
    server.use(
      http.get("http://localhost:8000/issues/:id", () =>
        HttpResponse.json({
          id: "i1",
          task_id: "t1",
          raised_by: "e1",
          description: "Client hasn't sent the required documents",
          status: "resolved",
          resolution_type: "clarified",
          resolution_notes: "The client confirmed the documents are on the way",
          remaining_work_description: null,
          resolved_by: "owner-1",
          resolved_at: "2026-09-18T00:00:00Z",
          created_at: "2026-09-17T00:00:00Z",
        }),
      ),
    );
    renderPage();

    expect(await screen.findByText("Clarified")).toBeInTheDocument();
    expect(
      screen.getByText("The client confirmed the documents are on the way"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Awaiting the owner's response.")).not.toBeInTheDocument();
  });

  it("shows the remaining work description when the resolution was a reassignment", async () => {
    server.use(
      http.get("http://localhost:8000/issues/:id", () =>
        HttpResponse.json({
          id: "i1",
          task_id: "t1",
          raised_by: "e1",
          description: "Client hasn't sent the required documents",
          status: "resolved",
          resolution_type: "reassigned",
          resolution_notes: "Handing this to someone with more bandwidth",
          remaining_work_description: "Finish collecting the outstanding receipts",
          resolved_by: "owner-1",
          resolved_at: "2026-09-18T00:00:00Z",
          created_at: "2026-09-17T00:00:00Z",
        }),
      ),
    );
    renderPage();

    expect(await screen.findByText("Reassigned")).toBeInTheDocument();
    expect(
      screen.getByText("Remaining work: Finish collecting the outstanding receipts"),
    ).toBeInTheDocument();
  });

  it("shows an error state when the issue can't be loaded (e.g. not this employee's own)", async () => {
    server.use(
      http.get("http://localhost:8000/issues/:id", () => new HttpResponse(null, { status: 404 })),
    );
    renderPage();

    expect(await screen.findByText("Could not load this issue.")).toBeInTheDocument();
  });
});
