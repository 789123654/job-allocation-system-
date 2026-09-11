import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmployeeManagementPage } from "@/features/employees/components/employee-management-page";
import { resetEmployeesFixture } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

// useEmployees() now reads firmId from useSession() to scope its TanStack Query cache key
// (ASVS 5 §8.4.1 / Multi_Tenant_Security_Cheat_Sheet.md's "prefix all cache keys with tenant
// identifier") — mocked the same way router.test.tsx does, not a real SessionProvider (which
// would need a real/MSW-backed Supabase session round-trip this component test doesn't need).
vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderPage() {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    role: "owner",
    firmId: "firm-1",
    mustChangePassword: false,
    isLoading: false,
  });
  // retry: false — the 409/404 mocked error paths shouldn't wait out TanStack Query's default
  // 3-retry backoff in every test run.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EmployeeManagementPage />
    </QueryClientProvider>,
  );
}

describe("EmployeeManagementPage", () => {
  beforeEach(() => {
    resetEmployeesFixture();
  });

  it("lists the seeded employee", async () => {
    renderPage();
    expect(await screen.findByText("Alex Employee")).toBeInTheDocument();
    expect(screen.getByText("alex@example.com")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows validation errors for an empty submit", async () => {
    renderPage();
    await screen.findByText("Alex Employee");

    fireEvent.click(screen.getByRole("button", { name: /\+ add employee/i }));
    fireEvent.click(screen.getByRole("button", { name: /^add employee$/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/enter a valid email address/i)).toBeInTheDocument();
  });

  it("shows a max-length error for an overlong name", async () => {
    renderPage();
    await screen.findByText("Alex Employee");

    fireEvent.click(screen.getByRole("button", { name: /\+ add employee/i }));
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "A".repeat(201) } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "valid@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^add employee$/i }));

    expect(await screen.findByText(/name is too long/i)).toBeInTheDocument();
  });

  it("creates a new employee and shows the generated password exactly once", async () => {
    renderPage();
    await screen.findByText("Alex Employee");

    fireEvent.click(screen.getByRole("button", { name: /\+ add employee/i }));
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "New Person" } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "new@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^add employee$/i }));

    expect(await screen.findByDisplayValue("TempPass123!")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    // Closed: the one-time password is gone from the DOM entirely, not just visually hidden.
    expect(screen.queryByDisplayValue("TempPass123!")).not.toBeInTheDocument();
    expect(await screen.findByText("New Person")).toBeInTheDocument();
  });

  it("shows a readable error when the email is already in use", async () => {
    renderPage();
    await screen.findByText("Alex Employee");

    fireEvent.click(screen.getByRole("button", { name: /\+ add employee/i }));
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "Dup" } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "alex@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^add employee$/i }));

    expect(await screen.findByText(/email already in use/i)).toBeInTheDocument();
  });

  it("deactivates and reactivates an employee", async () => {
    renderPage();
    await screen.findByText("Alex Employee");

    fireEvent.click(screen.getByRole("button", { name: /^deactivate$/i }));
    expect(await screen.findByText("Deactivated")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^reactivate$/i }));
    expect(await screen.findByText("Active")).toBeInTheDocument();
  });

  it("resets a password and shows it exactly once", async () => {
    renderPage();
    await screen.findByText("Alex Employee");

    // The row's trigger button and the dialog's confirm button share the exact label "Reset
    // password" once the dialog is open (Radix only mounts DialogContent while open, but the row
    // trigger stays mounted the whole time) — scope the confirm click to the dialog.
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^reset password$/i }));

    expect(await screen.findByDisplayValue("NewTempPass456!")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    expect(screen.queryByDisplayValue("NewTempPass456!")).not.toBeInTheDocument();
  });
});
