import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OwnerTaskReviewPage } from "@/features/tasks/components/owner-task-review-page";
import { resetTasksFixture } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

// A real RFC 4122 UUID, not the fixture's short "e1" convenience id — taskReviewSchema's
// assignedTo field mirrors tasks.py's real `UUID` type (Supabase auth.users.id in production), so
// this option's id has to actually validate as one. Caught two real, distinct bugs while writing
// this: "e1" fails Zod's .uuid() outright (expected); a first fix attempt using
// "11111111-1111-1111-1111-111111111111" *still* failed with the same "Invalid UUID" error, since
// the variant nibble (4th group's first hex digit) must be 8/9/a/b per RFC 4122 — "1" isn't a
// valid variant, so Zod's .uuid() correctly rejected that shape too, even though it "looks like" a
// UUID. This one has a valid version (4) and variant (8) nibble.
const EMPLOYEE_OPTIONS = [{ id: "11111111-1111-4111-8111-111111111111", label: "Alex Employee" }];

function renderAt(taskId: string) {
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
      <MemoryRouter initialEntries={[`/owner-tasks/${taskId}/review`]}>
        <Routes>
          <Route path="/" element={<div>OWNER-HOME</div>} />
          <Route
            path="/owner-tasks/:taskId/review"
            element={<OwnerTaskReviewPage employeeOptions={EMPLOYEE_OPTIONS} />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OwnerTaskReviewPage", () => {
  beforeEach(() => {
    resetTasksFixture();
  });

  it("approves a submitted task by default and navigates home", async () => {
    renderAt("t3");
    await screen.findByText("Already submitted");

    fireEvent.click(screen.getByRole("button", { name: /submit review/i }));

    expect(await screen.findByText("OWNER-HOME")).toBeInTheDocument();
  });

  // Regression guard for the code-review finding (whole-Phase-4 sweep, 2026-09-13): every entry
  // point to this screen (deadline notifications, the All Tasks table) links here regardless of
  // task status, but review only succeeds for "submitted" — this screen must refuse to render the
  // form at all for a task in any other status (t1 is fixture-seeded as "assigned"), not merely
  // surface the backend's 409 only after the Owner fills out and submits the whole form.
  it("refuses to render the review form for a task that isn't awaiting review", async () => {
    renderAt("t1");

    expect(await screen.findByText(/isn't awaiting review/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit review/i })).not.toBeInTheDocument();
  });

  // Exercises the Radix Select outcome-switcher for the first time in this codebase's test suite
  // — not assumed to work under jsdom just because the "approve" test above passed (that test
  // never opens a Select at all, since "approved" is the form's default value). Uses
  // @testing-library/user-event, not fireEvent, for the Select clicks specifically — verified
  // empirically this pass: Radix Select's item-selection internals key off a real pointer-event
  // sequence, and plain fireEvent.click (a bare synthetic "click", no preceding pointerdown/up)
  // left the underlying value stuck at undefined even though the trigger's displayed text
  // updated, caught by the "Invalid UUID" zod error that surfaced instead of a silent pass.
  it("switches to the billing outcome and submits the billing sub-form", async () => {
    const user = userEvent.setup();
    renderAt("t3");
    await screen.findByText("Already submitted");

    await user.click(screen.getByRole("combobox", { name: /outcome/i }));
    await user.click(await screen.findByRole("option", { name: /^billing$/i }));

    await user.click(await screen.findByRole("combobox", { name: /bill via/i }));
    await user.click(await screen.findByRole("option", { name: /alex employee/i }));

    fireEvent.change(screen.getByLabelText(/billing deadline/i), {
      target: { value: "2026-12-01" },
    });
    fireEvent.change(screen.getByLabelText(/billing description/i), {
      target: { value: "GST filing fee" },
    });
    fireEvent.change(screen.getByLabelText(/billing amount/i), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText(/billing recipient/i), {
      target: { value: "Acme Corp" },
    });

    fireEvent.click(screen.getByRole("button", { name: /submit review/i }));

    expect(await screen.findByText("OWNER-HOME")).toBeInTheDocument();
  });
});
