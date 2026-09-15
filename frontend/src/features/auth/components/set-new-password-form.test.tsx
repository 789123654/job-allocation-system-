import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, delay, http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SetNewPasswordForm } from "@/features/auth/components/set-new-password-form";
import { supabase } from "@/lib/supabase-client";
import { SessionProvider, useSession } from "@/stores/session-store";
import { server } from "@/testing/mocks/handlers";

// Same fake project URL as testing/mocks/handlers.ts (.env.test's VITE_SUPABASE_URL) — not
// exported from there, so re-declared here, same convention as change-password-form.test.tsx.
const SUPABASE_URL = "https://test-project.supabase.co";

const forcedChangeUser = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "owner@example.com",
  app_metadata: {
    firm_id: "22222222-2222-2222-2222-222222222222",
    role: "owner",
    must_change_password: true,
  },
};

// Sets up a signed-in session whose JWT/user carries must_change_password: true (the state that
// routes a real user to this forced screen), and returns a setter so a test can flip it once the
// mocked backend would actually flip it — used to verify the "promptly" requirement empirically,
// regardless of whether the real hook gets there via the updateUser response's USER_UPDATED event,
// an explicit refreshSession() call, or something else: both the token endpoint (any grant_type,
// covering a possible refresh) and whatever the PUT /auth/v1/user override does read this same flag.
function mockForcedPasswordSession(): { setMustChangePassword: (v: boolean) => void } {
  let mustChangePassword = true;

  server.use(
    http.post(`${SUPABASE_URL}/auth/v1/token`, () =>
      HttpResponse.json({
        access_token: "fake-access-token",
        refresh_token: "fake-refresh-token",
        expires_in: 3600,
        token_type: "bearer",
        user: {
          ...forcedChangeUser,
          app_metadata: { ...forcedChangeUser.app_metadata, must_change_password: mustChangePassword },
        },
      }),
    ),
  );

  return {
    setMustChangePassword: (v: boolean) => {
      mustChangePassword = v;
    },
  };
}

function SessionProbe() {
  const { mustChangePassword } = useSession();
  return <span data-testid="must-change-password">{String(mustChangePassword)}</span>;
}

function renderSetNewPasswordForm() {
  return render(
    <SessionProvider>
      <MemoryRouter initialEntries={["/set-new-password"]}>
        <SessionProbe />
        <Routes>
          <Route path="/set-new-password" element={<SetNewPasswordForm />} />
          {/* Catches any navigation target without assuming a specific dashboard route path. */}
          <Route path="*" element={<div data-testid="elsewhere">Elsewhere</div>} />
        </Routes>
      </MemoryRouter>
    </SessionProvider>,
  );
}

function submitButton(container: HTMLElement): HTMLButtonElement {
  // Real accessible name is unknown (blind contract) — scope to the <form> itself, same convention
  // as change-password-form.test.tsx.
  const button = container.querySelector("form button");
  if (!button) throw new Error("Expected the form to render a submit button");
  return button as HTMLButtonElement;
}

describe("SetNewPasswordForm", () => {
  it("shows real validation errors for an empty submit", async () => {
    mockForcedPasswordSession();
    await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "temp-admin-password",
    });

    const { container } = renderSetNewPasswordForm();
    fireEvent.click(submitButton(container));

    // Exact strings from the shared passwordChangeSchema (features/auth/types/index.ts) — documented
    // as shared between Set New Password and Change Password, safe to assert verbatim.
    expect(await screen.findByText(/current password is required/i)).toBeInTheDocument();
    expect(screen.getByText(/password must be at least 8 characters/i)).toBeInTheDocument();
  });

  it("on success: flips must_change_password promptly and leaves the forced screen", async () => {
    const session = mockForcedPasswordSession();
    await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "temp-admin-password",
    });

    server.use(
      http.put(`${SUPABASE_URL}/auth/v1/user`, () => {
        session.setMustChangePassword(false);
        return HttpResponse.json({
          ...forcedChangeUser,
          app_metadata: { ...forcedChangeUser.app_metadata, must_change_password: false },
        });
      }),
    );

    const { container } = renderSetNewPasswordForm();

    await waitFor(() => expect(screen.getByTestId("must-change-password").textContent).toBe("true"));

    fireEvent.change(screen.getByLabelText(/temporary|current/i), {
      target: { value: "temp-admin-password" },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: "a-valid-new-password-123" },
    });
    fireEvent.click(submitButton(container));

    // Promptness: this must resolve within a couple seconds, not on the JWT's natural 3600s expiry.
    await waitFor(() => expect(screen.getByTestId("must-change-password").textContent).toBe("false"), {
      timeout: 2000,
    });

    // Real navigation consequence, not just a resolved boolean: the forced screen is gone.
    expect(await screen.findByTestId("elsewhere")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^new password/i)).not.toBeInTheDocument();
  });

  it("on wrong temporary password: shows a visible error, stays on the forced screen, and leaves the form usable", async () => {
    mockForcedPasswordSession();
    await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "wrong-temp-password",
    });

    // Same documented judgment call as change-password-form.test.tsx: Supabase doesn't document a
    // distinct error code for a wrong current_password on updateUser, so this reuses the closest
    // documented GoTrue code (invalid_credentials).
    server.use(
      http.put(`${SUPABASE_URL}/auth/v1/user`, () =>
        HttpResponse.json(
          { code: 400, error_code: "invalid_credentials", msg: "Invalid login credentials" },
          { status: 400 },
        ),
      ),
    );

    const { container } = renderSetNewPasswordForm();

    fireEvent.change(screen.getByLabelText(/temporary|current/i), {
      target: { value: "wrong-temp-password" },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: "a-valid-new-password-123" },
    });
    fireEvent.click(submitButton(container));

    expect(await screen.findByText(/invalid login credentials/i)).toBeInTheDocument();
    expect(screen.queryByTestId("elsewhere")).not.toBeInTheDocument();
    expect(screen.getByTestId("must-change-password").textContent).toBe("true");

    // Form must still be usable — fields present, enabled, and editable — not stuck or swallowed.
    const tempField = screen.getByLabelText(/temporary|current/i) as HTMLInputElement;
    expect(tempField).toBeEnabled();
    fireEvent.change(tempField, { target: { value: "another-try" } });
    expect(tempField.value).toBe("another-try");
  });

  it("does not allow a second submission while one is already in flight", async () => {
    const session = mockForcedPasswordSession();
    await supabase.auth.signInWithPassword({
      email: "owner@example.com",
      password: "temp-admin-password",
    });

    let putCallCount = 0;
    server.use(
      http.put(`${SUPABASE_URL}/auth/v1/user`, async () => {
        putCallCount += 1;
        await delay(75);
        session.setMustChangePassword(false);
        return HttpResponse.json({
          ...forcedChangeUser,
          app_metadata: { ...forcedChangeUser.app_metadata, must_change_password: false },
        });
      }),
    );

    const { container } = renderSetNewPasswordForm();

    fireEvent.change(screen.getByLabelText(/temporary|current/i), {
      target: { value: "temp-admin-password" },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: "a-valid-new-password-123" },
    });

    const button = submitButton(container);
    fireEvent.click(button);
    fireEvent.click(button); // fired immediately, while the first request is still in flight

    await waitFor(() => expect(putCallCount).toBeGreaterThanOrEqual(1));
    // Give the 75ms delayed handler time to resolve, then confirm it was only ever hit once.
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(putCallCount).toBe(1);
  });
});
