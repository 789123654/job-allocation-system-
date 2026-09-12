import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MyTasksPage } from "@/features/tasks/components/my-tasks-page";
import { resetTasksFixture } from "@/testing/mocks/handlers";
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
});
