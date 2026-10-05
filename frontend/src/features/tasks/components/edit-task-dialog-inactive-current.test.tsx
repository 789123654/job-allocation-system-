import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EditTaskDialog } from "@/features/tasks/components/edit-task-dialog";
import { server } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

const API_BASE_URL = "http://localhost:8000";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

// Valid RFC 4122 v4 UUIDs (variant nibble 8/9/a/b).
const TASK_ID = "5b6f2a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b";
const ALEX_ID = "6c7d8e9f-0a1b-4c2d-8e3f-4a5b6c7d8e9f";
const CAROL_INACTIVE_ID = "8e9f0a1b-2c3d-4e4f-8a5b-6c7d8e9f0a1b";

const ALEX = { id: ALEX_ID, fullName: "Alex Employee", isActive: true };
const CAROL = { id: CAROL_INACTIVE_ID, fullName: "Carol Inactive", isActive: false };

// Task is currently assigned to the deactivated employee C.
const EMPLOYEES = [CAROL, ALEX];

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
    assignedTo: CAROL_INACTIVE_ID,
    status: "assigned",
    ...overrides,
  };
}

let patchBodies: Record<string, unknown>[] = [];

function mockPatch(status: number, body: unknown = { id: TASK_ID }) {
  server.use(
    http.patch(`${API_BASE_URL}/tasks/:id`, async ({ request }) => {
      patchBodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(body as Record<string, unknown>, { status });
    }),
  );
}

function renderDialog() {
  const onOpenChange = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EditTaskDialog task={makeTask()} employees={EMPLOYEES} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

function titleField() {
  return screen.getByLabelText(/^title$/i) as HTMLInputElement;
}

function saveButton() {
  return screen.getByRole("button", { name: /save/i });
}

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

function isDisabledElement(el: Element): boolean {
  return (
    (el as HTMLOptionElement).disabled === true ||
    el.getAttribute("aria-disabled") === "true" ||
    el.hasAttribute("data-disabled")
  );
}

describe("EditTaskDialog when the current assignee is inactive", () => {
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

  // Item 1
  it("shows the inactive current assignee as selected, with a disabled option labelled (inactive)", async () => {
    const user = userEvent.setup();
    renderDialog();
    const trigger = screen.getByLabelText(/^assignee$/i);

    if (trigger instanceof HTMLSelectElement) {
      expect(trigger.value).toBe(CAROL_INACTIVE_ID);
      const carolOption = Array.from(trigger.options).find((o) => o.value === CAROL_INACTIVE_ID);
      expect(carolOption).toBeDefined();
      expect(carolOption!.disabled).toBe(true);
      expect(carolOption!.textContent ?? "").toMatch(/\(inactive\)/i);
    } else {
      expect(trigger.textContent ?? "").toMatch(/carol inactive/i);
      await user.click(trigger);
      const carolOption = await screen.findByRole("option", { name: /carol inactive/i });
      expect(carolOption.textContent ?? "").toMatch(/\(inactive\)/i);
      expect(isDisabledElement(carolOption)).toBe(true);
      await user.keyboard("{Escape}");
    }
  });

  // Item 2
  it("offers the active employee Alex as an enabled choice", async () => {
    const user = userEvent.setup();
    renderDialog();
    const trigger = screen.getByLabelText(/^assignee$/i);

    if (trigger instanceof HTMLSelectElement) {
      const alexOption = Array.from(trigger.options).find((o) => o.value === ALEX_ID);
      expect(alexOption).toBeDefined();
      expect(alexOption!.disabled).toBe(false);
      expect(alexOption!.textContent ?? "").toMatch(/alex employee/i);
    } else {
      await user.click(trigger);
      const alexOption = await screen.findByRole("option", { name: /alex employee/i });
      expect(isDisabledElement(alexOption)).toBe(false);
      await user.keyboard("{Escape}");
    }
  });

  // Item 3
  it("title-only save sends only title, no assigned_to key, and closes on success", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "Renamed while assignee inactive" } });
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toEqual([{ title: "Renamed while assignee inactive" }]);
    expect(Object.prototype.hasOwnProperty.call(patchBodies[0], "assigned_to")).toBe(false);
  });

  // Item 4
  it("choosing Alex and saving sends assigned_to equal to Alex's id", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await chooseAssignee(user, /alex employee/i);
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toEqual([{ assigned_to: ALEX_ID }]);
  });

  // Item 4 (with a changed title)
  it("choosing Alex with a changed title sends both title and assigned_to", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    fireEvent.change(titleField(), { target: { value: "Reassigned and renamed" } });
    await chooseAssignee(user, /alex employee/i);
    await user.click(saveButton());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(patchBodies).toEqual([{ title: "Reassigned and renamed", assigned_to: ALEX_ID }]);
  });

  // Item 5
  it("offers no option with an empty value or empty label while the task has an assignee", async () => {
    const user = userEvent.setup();
    renderDialog();
    const trigger = screen.getByLabelText(/^assignee$/i);

    if (trigger instanceof HTMLSelectElement) {
      const options = Array.from(trigger.options);
      expect(options.some((o) => o.value === "")).toBe(false);
      expect(options.some((o) => (o.textContent ?? "").trim() === "")).toBe(false);
    } else {
      await user.click(trigger);
      const options = await screen.findAllByRole("option");
      expect(options.length).toBeGreaterThan(0);
      for (const o of options) {
        expect((o.textContent ?? "").trim()).not.toBe("");
      }
      await user.keyboard("{Escape}");
    }
    expect(within(screen.getByRole("dialog")).getByLabelText(/^assignee$/i)).toBeInTheDocument();
  });
});

// Items NOT COVERED by this file:
// (none beyond the five numbered items; item 3's "request does not fail" is covered by the 200 mock
// in beforeEach and the onOpenChange(false) assertion.)
