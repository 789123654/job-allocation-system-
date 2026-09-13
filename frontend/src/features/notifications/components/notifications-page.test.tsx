import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationsPage } from "@/features/notifications/components/notifications-page";
import { server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderAs(role: "owner" | "employee") {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    role,
    firmId: "firm-1",
    mustChangePassword: false,
    isLoading: false,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Regression guard for the same branch-completeness bug class as the code-review finding on
// router.tsx's AuthenticatedHome (2026-09-13, SECURITY_AUDIT_CHECKLIST.md) — that bug was an
// incomplete role branch falling through to the wrong screen. This screen has its own role branch
// (Owner vs Employee task link target) with zero prior coverage; a blind-authored pass for this
// slice found no implementation bug here, but also never got this test passing (its own mock used
// the wrong wire-format field casing) — this is the one behavior worth guarding permanently.
describe("NotificationsPage", () => {
  beforeEach(() => {
    server.use(
      http.get("http://localhost:8000/notifications", () =>
        HttpResponse.json([
          {
            id: "n1",
            type: "task_assigned",
            task_id: "t1",
            issue_id: null,
            is_read: false,
            created_at: "2026-09-01T00:00:00Z",
          },
        ]),
      ),
    );
  });

  it("links a task notification to the Owner review screen for an Owner", async () => {
    renderAs("owner");
    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute("href", "/owner-tasks/t1/review");
  });

  it("links the same task notification to the Employee task screen for an Employee", async () => {
    renderAs("employee");
    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute("href", "/tasks/t1");
  });
});
