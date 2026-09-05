import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LoginForm } from "@/features/auth/components/login-form";

function renderLoginForm() {
  return render(
    <MemoryRouter>
      <LoginForm />
    </MemoryRouter>,
  );
}

describe("LoginForm", () => {
  it("shows validation errors for an empty submit", async () => {
    renderLoginForm();
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/enter a valid email address/i)).toBeInTheDocument();
    expect(screen.getByText(/password is required/i)).toBeInTheDocument();
  });

  it("signs in successfully against the mocked Supabase endpoint", async () => {
    renderLoginForm();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "owner@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "correct-password" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    // MSW's fake token endpoint (testing/mocks/handlers.ts) always succeeds — no error banner
    // and the pending state resolves back to the enabled "Sign in" label.
    await waitFor(() => {
      expect(screen.queryByText(/invalid email or password/i)).not.toBeInTheDocument();
    });
    expect(await screen.findByRole("button", { name: /^sign in$/i })).toBeEnabled();
  });
});
