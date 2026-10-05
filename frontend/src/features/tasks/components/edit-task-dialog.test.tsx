import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EditTaskDialog } from "@/features/tasks/components/edit-task-dialog";
import { server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

const API_BASE_URL = "http://localhost:8000";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

// Valid RFC 4122 v4 UUIDs (variant nibble 8/9/a/b) so schema checks on ids pass.
const TASK_ID = "5b6f2a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b";
const ALEX_ID = "6c7d8e9f-0a1b-4c2d-8e3f-4a5b6c7d8e9f";
const BOB_ID = "7d8e9f0a-1b2c-4d3e-9f4a-5b6c7d8e9f0a";
const CAROL_INACTIVE_ID = "8e9f0a1b-2c3d-4e4f-8a5b-6c7d8e9f0a1b";

const ALEX = { id: ALEX_ID, fullName: "Alex Employee", isActive: true };
const BOB = { id: BOB_ID, fullName: "Bob Active", isActive: true };
const CAROL = { id: CAROL_INACTIVE_ID, fullName: "Carol Inactive", isActive: false };

const ALL_EMPLOYEES = [ALEX, BOB, CAROL];

const ERR_409 = "This task can't be edited from its current status. Refresh and try again.";
const ERR_404 = "Could not load this task.";
const ERR_422 = "That employee can't be assigned. Choose another.";
const ERR_GENERIC = "Something went wrong. Try again.";

type Task = {
  id: string;
  title: string;
  description: string | null;
  assignedTo: string | null;
  status: string;
};

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: TASK_ID,
    title: "Original title",
    description: "Original description",
    assignedTo: ALEX_ID,
    status: "assigned",
    ...overrides,
  };
}

// Records every PATCH body the mock server receives, and answers with the given status/body.
let patchBodies: Record<string, unknown>[] = [];

function mockPatch(status: number, body: unknown = { id: TASK_ID }) {
  server.use(
    http.patch(`${API_BASE_URL}/tasks/:id`, async ({ request }) => {
      patchBodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(body as Record<string, unknown>, { status });
    }),
  );
}

function renderDialog(
  options: { task?: Task; employees?: typeof ALL_EMPLOYEES } = {},
) {
  const onOpenChange = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EditTaskDialog
        task={options.task ?? makeTask()}
        employees={options.employees ?? ALL_EMPLOYEES}
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

function titleField() {
  return screen.getByLabelText(/^title$/i) as HTMLInputElement;
}

function descriptionField() {
  return screen.getByLabelText(/^description$/i) as HTMLInputElement;
}

function saveButton() {
  return screen.getByRole("button", { name: /save/i });
}

// Works for a native <select> or a Radix-style combobox trigger.
async function chooseAssignee(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  const trigger = screen.getByLabelText(/^assignee$/i);
  if (trigger instanceof HTMLSelectElement) {
    const option = Array.from(trigger.options).find((o) => name.test(o.textContent ?? ""));
    await user.selectOptions(trigger, option!.value);
    return;
  }
  await user.click(trigger);
  await user.click(await screen.findByRole("option", { name }));
}

// Returns the visible option labels (and, for a native select, their values).
async function listAssigneeOptions(user: ReturnType<typeof userEvent.setup>) {
  const trigger = screen.getByLabelText(/^assignee$/i);
  if (trigger instanceof HTMLSelectElement) {
    return Array.from(trigger.options).map((o) => ({ label: o.textContent ?? "", value: o.value }));
  }
  await user.click(trigger);
  const labels = (await screen.findAllByRole("option")).map((o) => ({
    label: o.textContent ?? "",
    value: null as string | null,
  }));
  await user.keyboard("{Escape}");
  return labels;
}

// The contract does not fix the wording of validation messages, so this checks the structural
// signal: an alert region with text, or an aria-invalid field inside the dialog.
function expectVisibleValidationError() {
  const dialog = screen.getByRole("dialog");
  const hasAlertText = within(dialog)
    .queryAllByRole("alert")
    .some((a) => (a.textContent ?? "").trim().length > 0);
  const hasInvalidField = dialog.querySelector('[aria-invalid="true"]') !== null;
  expect(hasAlertText || hasInvalidField).toBe(true);
}

describe("EditTaskDialog", () => {
  let consoleSpies: ReturnType<typeof vi.spyOn>[] = [];

  beforeEach(() => {
    patchBodies = [];
    vi.mocked(useSession).mockReturnValue({
      session: null,
      role: "owner",
      firmId: "firm-1",
      mustChangePassword: false,
      isLoading: false,
    });
    mockPatch(200);
  });

  afterEach(() => {
    for (const spy of consoleSpies) spy.mockRestore();
    consoleSpies = [];
  });

  // Item 1 and 2 (edit control hidden for employees / for other statuses) are NOT COVERED here:
  // the control lives on the task detail page, which the contract puts out of scope.

  // Item 3
  it("has no deadline field", () => {
    renderDialog();
    expect(screen.queryByLabelText(/deadline/i)).not.toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).queryByText(/deadline/i)).not.toBeInTheDocument();
  });

  // Item 4
  it.each([
    ["an empty title", ""],
    ["a whitespace-only title", "    "],
    ["a title over 300 characters", "a".repeat(301)],
  ])("rejects %s with a visible message and sends no request", async (_label, value) => {
    const user = userEvent.setup();
    renderDialog();
    fireEvent.change(titleField(), { target: { value } });
    await user.click(saveButton());

    expectVisibleValidationError();
    expect(patchBodies).toHaveLength(0);
  });

  it("accepts a title of exactly 300 characters", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "a".repeat(300) } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toHaveLength(1);
  });

  // Item 5
  it("rejects a description over 5000 characters with a visible message and sends no request", async () => {
    const user = userEvent.setup();
    renderDialog();
    fireEvent.change(descriptionField(), { target: { value: "x".repeat(5001) } });
    await user.click(saveButton());

    expectVisibleValidationError();
    expect(patchBodies).toHaveLength(0);
  });

  it("accepts a description of exactly 5000 characters", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(descriptionField(), { target: { value: "x".repeat(5000) } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toHaveLength(1);
  });

  // Item 6
  it("lists only active employees as assignee options", async () => {
    const user = userEvent.setup();
    renderDialog();
    const options = await listAssigneeOptions(user);

    const labels = options.map((o) => o.label);
    expect(labels.some((l) => /alex employee/i.test(l))).toBe(true);
    expect(labels.some((l) => /bob active/i.test(l))).toBe(true);
    expect(labels.some((l) => /carol inactive/i.test(l))).toBe(false);
  });

  it("offers no empty assignee option", async () => {
    const user = userEvent.setup();
    renderDialog();
    const options = await listAssigneeOptions(user);

    expect(options.some((o) => o.label.trim() === "")).toBe(false);
    expect(options.some((o) => o.value === "")).toBe(false);
  });

  it("rejects an empty assignee selection: no request carries an empty assigned_to", async () => {
    const user = userEvent.setup();
    renderDialog();
    fireEvent.change(titleField(), { target: { value: "Changed title" } });
    const trigger = screen.getByLabelText(/^assignee$/i);
    if (trigger instanceof HTMLSelectElement) {
      fireEvent.change(trigger, { target: { value: "" } });
    }
    await user.click(saveButton());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    for (const body of patchBodies) {
      expect(body.assigned_to === null || body.assigned_to === "").toBe(false);
    }
  });

  // Item 7
  it("sends only title when only the title changed", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "Renamed task" } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toEqual([{ title: "Renamed task" }]);
  });

  // Item 8
  it("sends description: null when the description is cleared, and treats empty as valid", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(descriptionField(), { target: { value: "" } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toEqual([{ description: null }]);
  });

  // Item 9
  it("sends assigned_to set to the chosen employee's id", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await chooseAssignee(user, /bob active/i);
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toEqual([{ assigned_to: BOB_ID }]);
  });

  // Item 10
  it("shows the 409 message, shows no success, and keeps the dialog open", async () => {
    mockPatch(409, {
      type: "about:blank",
      title: "Conflict",
      status: 409,
      detail: "Task cannot be edited from its current status",
      instance: "",
    });
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());

    expect(await screen.findByText(ERR_409)).toBeInTheDocument();
    expect(patchBodies).toHaveLength(1);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("lets the owner save again after a failed save: the second Save sends a second PATCH", async () => {
    mockPatch(409, { detail: "conflict" });
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());
    expect(await screen.findByText(ERR_409)).toBeInTheDocument();

    mockPatch(200, { id: TASK_ID });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toHaveLength(2);
    expect(patchBodies[1]).toEqual({ title: "New title" });
  });

  // Item 11
  it("shows the 404 message and shows no success", async () => {
    mockPatch(404, {});
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());

    expect(await screen.findByText(ERR_404)).toBeInTheDocument();
    expect(patchBodies).toHaveLength(1);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  // Item 12
  it("shows the 422 assignee message and keeps the dialog open", async () => {
    mockPatch(422, {
      type: "about:blank",
      title: "Unprocessable",
      status: 422,
      detail: "assigned_to is not an active employee",
      instance: "",
    });
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());

    expect(await screen.findByText(ERR_422)).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  // Item 13
  it("shows the generic message for a 500 and never shows raw server text", async () => {
    mockPatch(500, {
      type: "https://internal.example/errors/SECRET_TYPE_XYZ",
      title: "Internal Server Error",
      status: 500,
      detail: "SECRET_DETAIL_ABC stack trace",
      instance: "/internal/SECRET_INSTANCE_QRS",
    });
    const user = userEvent.setup();
    renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());

    expect(await screen.findByText(ERR_GENERIC)).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("SECRET_TYPE_XYZ");
    expect(text).not.toContain("SECRET_DETAIL_ABC");
    expect(text).not.toContain("SECRET_INSTANCE_QRS");
    expect(text).not.toContain("stack trace");
  });

  // Item 14
  it("closes the dialog on HTTP 200", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  // Item 15
  it("sends exactly one PATCH when Save is clicked twice quickly", async () => {
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "New title" } });
    fireEvent.click(saveButton());
    fireEvent.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toHaveLength(1);
  });

  // Item 16
  it("renders an img-injection title as literal text, not markup", async () => {
    const payload = '<img src=x onerror="alert(1)">';
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: payload } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(titleField().value).toBe(payload);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("[onerror]")).toBeNull();
    expect(patchBodies).toEqual([{ title: payload }]);
  });

  // Item 17
  it("writes nothing to console during a successful save", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    consoleSpies.push(log, error, warn);

    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));

    expect(log).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });

  it("writes nothing to console during a failed save", async () => {
    mockPatch(500, { detail: "boom" });
    const user = userEvent.setup();
    renderDialog();
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    consoleSpies.push(log, error, warn);

    fireEvent.change(titleField(), { target: { value: "New title" } });
    await user.click(saveButton());
    expect(await screen.findByText(ERR_GENERIC)).toBeInTheDocument();

    expect(log).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });

  // Item 18
  it("moves focus into the Title field when opened", async () => {
    renderDialog();
    await waitFor(() => expect(titleField()).toHaveFocus());
  });

  it("calls onOpenChange(false) on Escape", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await waitFor(() => expect(titleField()).toHaveFocus());
    await user.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
