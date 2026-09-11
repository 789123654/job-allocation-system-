import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JobTypeManagementPage } from "@/features/job-types/components/job-type-management-page";
import { resetJobTypesFixture } from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

// Same reasoning as employee-management-page.test.tsx: useJobTypes() reads firmId from
// useSession() to scope its cache key, so it's mocked directly rather than rendered under a real
// SessionProvider.
vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function renderPage() {
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
      <JobTypeManagementPage />
    </QueryClientProvider>,
  );
}

describe("JobTypeManagementPage", () => {
  beforeEach(() => {
    resetJobTypesFixture();
  });

  it("lists the seeded job type", async () => {
    renderPage();
    expect(await screen.findByText("Tax Audit")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows a validation error for an empty submit", async () => {
    renderPage();
    await screen.findByText("Tax Audit");

    fireEvent.click(screen.getByRole("button", { name: /\+ add job type/i }));
    fireEvent.click(screen.getByRole("button", { name: /^add job type$/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
  });

  it("shows a max-length error for an overlong name", async () => {
    renderPage();
    await screen.findByText("Tax Audit");

    fireEvent.click(screen.getByRole("button", { name: /\+ add job type/i }));
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "A".repeat(201) } });
    fireEvent.click(screen.getByRole("button", { name: /^add job type$/i }));

    expect(await screen.findByText(/name is too long/i)).toBeInTheDocument();
  });

  it("creates a new job type", async () => {
    renderPage();
    await screen.findByText("Tax Audit");

    fireEvent.click(screen.getByRole("button", { name: /\+ add job type/i }));
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "GST Filing" } });
    fireEvent.click(screen.getByRole("button", { name: /^add job type$/i }));

    expect(await screen.findByText("GST Filing")).toBeInTheDocument();
    // Closed on success — no confirmation step, unlike the employees create dialog.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a readable error when the name is already in use", async () => {
    renderPage();
    await screen.findByText("Tax Audit");

    fireEvent.click(screen.getByRole("button", { name: /\+ add job type/i }));
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "Tax Audit" } });
    fireEvent.click(screen.getByRole("button", { name: /^add job type$/i }));

    expect(await screen.findByText(/job type name already in use/i)).toBeInTheDocument();
  });

  it("deactivates and reactivates a job type", async () => {
    renderPage();
    await screen.findByText("Tax Audit");

    fireEvent.click(screen.getByRole("button", { name: /^deactivate$/i }));
    expect(await screen.findByText("Deactivated")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^reactivate$/i }));
    expect(await screen.findByText("Active")).toBeInTheDocument();
  });
});
