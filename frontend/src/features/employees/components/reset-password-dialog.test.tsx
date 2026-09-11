import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { ResetPasswordDialog } from "@/features/employees/components/reset-password-dialog";
import { resetEmployeesFixture, server } from "@/testing/mocks/handlers";

// VITE_API_BASE_URL (.env.test) — matches testing/mocks/handlers.ts's own constant.
const API_BASE_URL = "http://localhost:8000";

// employee-list.tsx only ever renders ResetPasswordDialog while resetTarget is truthy — closing
// it there unmounts the component, so a test driven through that parent can't tell "the password
// left the DOM because the close-cleanup ran" apart from "the password left the DOM because the
// component doesn't exist anymore". This harness keeps ONE instance mounted across open/close by
// toggling only the `open` prop, so the assertions below can only pass if the dialog's own
// close-cleanup (reset-password-dialog.tsx's `if (!next) {...}` block) actually runs.
function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Reopen
      </button>
      <ResetPasswordDialog
        employeeId="e1"
        employeeName="Alex Employee"
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

function renderHarness() {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
}

describe("ResetPasswordDialog", () => {
  beforeEach(() => {
    resetEmployeesFixture();
  });

  it("clears the shown password and starts a fresh Idempotency-Key on close, on the SAME instance — not provable by an unmount", async () => {
    const capturedKeys: Array<string | null> = [];
    server.use(
      http.post(`${API_BASE_URL}/employees/:id/reset-password`, ({ request }) => {
        capturedKeys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json({ generated_password: "NewTempPass456!" });
      }),
    );

    renderHarness();

    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));
    expect(await screen.findByDisplayValue("NewTempPass456!")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));

    // If the close-cleanup block (lines 31-34) never ran, the stale password from the first call
    // would still be showing right now, with no second network call needed to see it — exactly
    // the BlockStatement/CallExpression mutants that survived the original test.
    expect(screen.queryByDisplayValue("NewTempPass456!")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reset password$/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));
    await screen.findByDisplayValue("NewTempPass456!");

    // rest-api-guidelines Rule 230: closing and reopening is a new logical attempt, so it must
    // get a new Idempotency-Key — not the stale one from the first attempt.
    expect(capturedKeys).toHaveLength(2);
    expect(capturedKeys[0]).toBeTruthy();
    expect(capturedKeys[1]).toBeTruthy();
    expect(capturedKeys[1]).not.toBe(capturedKeys[0]);
  });
});
