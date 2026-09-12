import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CreateTaskDialog } from "@/features/tasks/components/create-task-dialog";
import { resetTasksFixture } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

// Valid RFC 4122 UUIDs (version 4, variant 8) — see owner-task-review-page.test.tsx's comment for
// why a shape like "jt1"/"11111111-1111-1111-1111-111111111111" isn't enough; Zod's .uuid()
// checks the variant nibble too.
const JOB_TYPE_OPTIONS = [{ id: "22222222-2222-4222-8222-222222222222", label: "Tax Audit" }];
const EMPLOYEE_OPTIONS = [{ id: "11111111-1111-4111-8111-111111111111", label: "Alex Employee" }];

function renderDialog(options: { jobTypeOptions?: typeof JOB_TYPE_OPTIONS; employeeOptions?: typeof EMPLOYEE_OPTIONS } = {}) {
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
      <CreateTaskDialog
        jobTypeOptions={options.jobTypeOptions ?? []}
        employeeOptions={options.employeeOptions ?? []}
      />
    </QueryClientProvider>,
  );
}

describe("CreateTaskDialog", () => {
  beforeEach(() => {
    resetTasksFixture();
  });

  it("creates a task with just a title and closes the dialog", async () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "New client onboarding" } });
    fireEvent.click(screen.getByRole("button", { name: /create task/i }));

    await screen.findByRole("button", { name: /new task/i });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a validation error for an empty title", async () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: /create task/i }));

    expect(await screen.findByText(/title is required/i)).toBeInTheDocument();
  });

  it("creates a task with a chosen job type and assignee", async () => {
    const user = userEvent.setup();
    renderDialog({ jobTypeOptions: JOB_TYPE_OPTIONS, employeeOptions: EMPLOYEE_OPTIONS });
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "File returns" } });
    await user.click(screen.getByRole("combobox", { name: /job type/i }));
    await user.click(await screen.findByRole("option", { name: /tax audit/i }));
    await user.click(screen.getByRole("combobox", { name: /assign to/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));

    fireEvent.click(screen.getByRole("button", { name: /create task/i }));

    await screen.findByRole("button", { name: /new task/i });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
