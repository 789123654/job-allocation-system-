import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskDetailPage } from "@/features/tasks/components/task-detail-page";
import { resetTasksFixture } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderAt(taskId: string) {
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
      <MemoryRouter initialEntries={[`/tasks/${taskId}`]}>
        <Routes>
          <Route path="/tasks" element={<div>MY-TASKS-PAGE</div>} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("TaskDetailPage", () => {
  beforeEach(() => {
    resetTasksFixture();
  });

  it("shows a standard task's title/status and a Mark completed button", async () => {
    renderAt("t1");
    expect(await screen.findByText("File GST return")).toBeInTheDocument();
    expect(screen.getByText("assigned")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark completed/i })).toBeInTheDocument();
  });

  it("shows Mark billed instead of Mark completed for a billing task", async () => {
    renderAt("t2");
    await screen.findByText("Collect billing details");
    expect(screen.getByRole("button", { name: /mark billed/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark completed/i })).not.toBeInTheDocument();
  });

  it("submits a standard task and navigates back to My Tasks", async () => {
    renderAt("t1");
    await screen.findByText("File GST return");
    fireEvent.click(screen.getByRole("button", { name: /mark completed/i }));
    expect(await screen.findByText("MY-TASKS-PAGE")).toBeInTheDocument();
  });

  it("marks a billing task billed and navigates back to My Tasks", async () => {
    renderAt("t2");
    await screen.findByText("Collect billing details");
    fireEvent.click(screen.getByRole("button", { name: /mark billed/i }));
    expect(await screen.findByText("MY-TASKS-PAGE")).toBeInTheDocument();
  });

  it("shows no action button for a task already submitted", async () => {
    renderAt("t3");
    await screen.findByText("Already submitted");
    expect(screen.queryByRole("button", { name: /mark completed/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark billed/i })).not.toBeInTheDocument();
  });

  it("raises an issue from the task detail page", async () => {
    renderAt("t1");
    await screen.findByText("File GST return");

    fireEvent.click(screen.getByRole("button", { name: /^raise issue$/i }));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText(/what's the issue/i), {
      target: { value: "Missing supporting documents" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^submit$/i }));

    // Dialog closes on success — no confirmation step, same pattern as create-job-type-dialog.
    await screen.findByText("File GST return");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
