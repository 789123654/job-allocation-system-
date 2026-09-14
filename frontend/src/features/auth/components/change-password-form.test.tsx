import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, delay, http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChangePasswordForm } from "@/features/auth/components/change-password-form";
import { supabase } from "@/lib/supabase-client";
import { server } from "@/testing/mocks/handlers";

// Same fake project URL as testing/mocks/handlers.ts (.env.test's VITE_SUPABASE_URL) — not
// exported from there, so re-declared here to build server.use() overrides for this file's
// wrong-current-password and double-submit cases.
const SUPABASE_URL = "https://test-project.supabase.co";

function renderChangePasswordForm(onSuccess?: () => void) {
  return render(
    <MemoryRouter>
      <ChangePasswordForm onSuccess={onSuccess} />
    </MemoryRouter>,
  );
}

function submitButton(container: HTMLElement): HTMLButtonElement {
  // Real accessible name is unknown (blind contract) — the form is required to render exactly one
  // submit control, so scope to the <form> itself rather than guessing button text.
  const button = container.querySelector("form button");
  if (!button) throw new Error("Expected the form to render a submit button");
  return button as HTMLButtonElement;
}

describe("ChangePasswordForm", () => {
  beforeEach(async () => {
    // Establish a real signed-in session first (against MSW's unconditional token-endpoint mock —
    // same one login-form.test.tsx relies on) since this is a re-authentication-style flow for an
    // already-logged-in user, not a standalone public form.
    await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "correct-password",
    });
  });

  it("shows real validation errors for an empty submit", async () => {
    const { container } = renderChangePasswordForm();
    fireEvent.click(submitButton(container));

    // Exact strings from passwordChangeSchema (features/auth/types/index.ts) — safe to assert
    // verbatim, that schema is the form's documented validation contract, not implementation logic.
    expect(await screen.findByText(/current password is required/i)).toBeInTheDocument();
    expect(screen.getByText(/password must be at least 8 characters/i)).toBeInTheDocument();
  });

  it("on success: shows the success confirmation BEFORE any dismiss action, and does not fire onSuccess until the user explicitly dismisses", async () => {
    const onSuccess = vi.fn();
    const { container } = renderChangePasswordForm(onSuccess);

    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: "correct-password" },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: "a-valid-new-password-123" },
    });
    fireEvent.click(submitButton(container));

    // THE regression check: the success confirmation must actually be on screen right after
    // submit succeeds — asserted here, before any dismiss click is simulated below. If a future
    // change reintroduces firing the dismiss/close action synchronously in the same event as the
    // success state update, React 18 batching would collapse both into one commit and this
    // intermediate success UI would never be observed as present on its own.
    const successMessage = await screen.findByText(/password.{0,25}(changed|updated)|success/i);
    expect(successMessage).toBeInTheDocument();

    // The old form fields must be gone — this is a distinct success UI, not the form still shown
    // underneath the message.
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();

    // onSuccess must NOT have fired yet — only the later explicit action should trigger it.
    expect(onSuccess).not.toHaveBeenCalled();

    // Now perform the explicit, separate dismiss/continue action.
    const doneButton = screen.getByRole("button", { name: /done|close|continue|ok|got it/i });
    fireEvent.click(doneButton);

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  });

  it("on wrong current password: shows a visible error, never shows success, never calls onSuccess, and leaves the form usable", async () => {
    // Real GoTrue/Supabase Auth error shape (code/error_code/msg fields; AuthApiError.message is
    // populated from `msg`) per Supabase's own error-codes doc
    // (supabase.com/docs/guides/auth/debugging/error-codes) — that page documents `invalid_credentials`
    // ("Login credentials or grant type not recognized") but does NOT document a distinct code for a
    // wrong current_password specifically on updateUser; this reuses the closest documented code
    // rather than inventing one, and is called out here as that judgment call.
    server.use(
      http.put(`${SUPABASE_URL}/auth/v1/user`, () =>
        HttpResponse.json(
          { code: 400, error_code: "invalid_credentials", msg: "Invalid login credentials" },
          { status: 400 },
        ),
      ),
    );

    const onSuccess = vi.fn();
    const { container } = renderChangePasswordForm(onSuccess);

    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: "wrong-password" },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: "a-valid-new-password-123" },
    });
    fireEvent.click(submitButton(container));

    expect(await screen.findByText(/invalid login credentials/i)).toBeInTheDocument();
    expect(screen.queryByText(/password.{0,25}(changed|updated)/i)).not.toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();

    // Form must still be usable — fields present, enabled, and editable — not stuck or swallowed.
    const currentPasswordField = screen.getByLabelText(/current password/i) as HTMLInputElement;
    expect(currentPasswordField).toBeEnabled();
    fireEvent.change(currentPasswordField, { target: { value: "another-try" } });
    expect(currentPasswordField.value).toBe("another-try");
  });

  it("does not allow a second submission while one is already in flight", async () => {
    let putCallCount = 0;
    server.use(
      http.put(`${SUPABASE_URL}/auth/v1/user`, async () => {
        putCallCount += 1;
        await delay(75);
        return HttpResponse.json({ id: "11111111-1111-1111-1111-111111111111" });
      }),
    );

    const { container } = renderChangePasswordForm();

    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: "correct-password" },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: "a-valid-new-password-123" },
    });

    const button = submitButton(container);
    fireEvent.click(button);
    fireEvent.click(button); // fired immediately, while the first change is still in flight

    await waitFor(() => expect(putCallCount).toBeGreaterThanOrEqual(1));
    // Give the 75ms delayed handler time to resolve, then confirm it was only ever hit once.
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(putCallCount).toBe(1);
  });
});
