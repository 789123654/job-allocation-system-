import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CreateTaskDialog } from "@/features/tasks/components/create-task-dialog";
import { resetTasksFixture, server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

const API_BASE_URL = "http://localhost:8000";

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

  it("keeps both the job type and the assignee selected — selecting one must not reset the other (reported bug, 2026-09-16)", async () => {
    let capturedBody: { job_type_id: string | null; assigned_to: string | null } | null = null;
    server.use(
      http.post(`${API_BASE_URL}/tasks`, async ({ request }) => {
        capturedBody = (await request.json()) as { job_type_id: string | null; assigned_to: string | null };
        return HttpResponse.json({ id: "t-new" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderDialog({ jobTypeOptions: JOB_TYPE_OPTIONS, employeeOptions: EMPLOYEE_OPTIONS });
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "File returns" } });
    await user.click(screen.getByRole("combobox", { name: /job type/i }));
    await user.click(await screen.findByRole("option", { name: /tax audit/i }));

    // The visible trigger must still show the chosen job type right after picking it — before
    // touching the assignee field at all — so a later failure can't be blamed on this step.
    expect(screen.getByRole("combobox", { name: /job type/i })).toHaveTextContent(/tax audit/i);

    await user.click(screen.getByRole("combobox", { name: /assign to/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));

    // The actual reported bug: selecting the assignee must not silently clear job type back to
    // its placeholder, and vice versa.
    expect(screen.getByRole("combobox", { name: /job type/i })).toHaveTextContent(/tax audit/i);
    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);

    fireEvent.click(screen.getByRole("button", { name: /create task/i }));
    await screen.findByRole("button", { name: /new task/i });

    expect(capturedBody).toMatchObject({
      job_type_id: JOB_TYPE_OPTIONS[0].id,
      assigned_to: EMPLOYEE_OPTIONS[0].id,
    });
  });

  it("keeps the assignee selected after clicking into another field afterward (reported bug, 2026-09-16: confirmed via AskUserQuestion — dialog stays open, only Assign To clears)", async () => {
    const user = userEvent.setup();
    renderDialog({ jobTypeOptions: JOB_TYPE_OPTIONS, employeeOptions: EMPLOYEE_OPTIONS });
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("combobox", { name: /assign to/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));
    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);

    // The exact reported trigger: click into an unrelated field after the assignee is set.
    await user.click(screen.getByLabelText(/title/i));
    await user.type(screen.getByLabelText(/title/i), "File returns");

    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);
  });

  it("keeps the assignee selected after opening (without picking) the job type dropdown afterward", async () => {
    const user = userEvent.setup();
    renderDialog({ jobTypeOptions: JOB_TYPE_OPTIONS, employeeOptions: EMPLOYEE_OPTIONS });
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("combobox", { name: /assign to/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));
    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);

    // Open the sibling Select without picking anything, then dismiss it — a different kind of
    // "click on another thing" than typing into a plain input.
    await user.click(screen.getByRole("combobox", { name: /job type/i }));
    await screen.findByRole("option", { name: /tax audit/i });
    await user.keyboard("{Escape}");

    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);
  });

  it("survives employeeOptions becoming a new array reference after the assignee is picked (simulates a background refetch of the employee list while the dialog is open)", async () => {
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
    const user = userEvent.setup();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <CreateTaskDialog jobTypeOptions={JOB_TYPE_OPTIONS} employeeOptions={EMPLOYEE_OPTIONS} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("combobox", { name: /assign to/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));
    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);

    // A brand-new array with the same data, same identity/content per item — exactly what a
    // TanStack Query background refetch produces (owner-dashboard-page.tsx recomputes
    // employeeOptions with .map() on every render).
    rerender(
      <QueryClientProvider client={queryClient}>
        <CreateTaskDialog jobTypeOptions={JOB_TYPE_OPTIONS} employeeOptions={[...EMPLOYEE_OPTIONS]} />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);
  });

  it("survives employeeOptions going empty and back (a field gated behind options.length > 0 unmounts and loses its value on any transient empty state)", async () => {
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
    const user = userEvent.setup();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <CreateTaskDialog jobTypeOptions={JOB_TYPE_OPTIONS} employeeOptions={EMPLOYEE_OPTIONS} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /new task/i }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("combobox", { name: /assign to/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));
    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);

    rerender(
      <QueryClientProvider client={queryClient}>
        <CreateTaskDialog jobTypeOptions={JOB_TYPE_OPTIONS} employeeOptions={[]} />
      </QueryClientProvider>,
    );
    rerender(
      <QueryClientProvider client={queryClient}>
        <CreateTaskDialog jobTypeOptions={JOB_TYPE_OPTIONS} employeeOptions={EMPLOYEE_OPTIONS} />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("combobox", { name: /assign to/i })).toHaveTextContent(/alex employee/i);
  });
});
