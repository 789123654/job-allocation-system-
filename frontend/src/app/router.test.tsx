import type { Session } from "@supabase/supabase-js";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AuthenticatedHome,
  AuthenticatedLayout,
  LoginPage,
  OwnerRoute,
  SetNewPasswordPage,
} from "@/app/router";
import {
  resetEmployeesFixture,
  resetJobTypesFixture,
  resetNotificationsFixture,
  resetTasksFixture,
} from "@/testing/mocks/handlers";
import { useSession } from "@/stores/session-store";

// The one thing worth an automated test here: the client-side mirror of backend/app/api/deps.py's
// require_password_set gate. A session with must_change_password: true must never reach the
// authenticated shell — this is UX only (the backend independently enforces both gates on every
// request regardless of what the client shows), but it was previously unverified by any test.
vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

// Only truthiness of `session` matters to the gate logic under test — session-store.tsx's own
// deriveState (reading app_metadata) is a separate, already-decoded input here, not re-tested.
const _FAKE_SESSION = {} as unknown as Session;

function mockSession(overrides: {
  session: Session | null;
  mustChangePassword: boolean;
  isLoading?: boolean;
  role?: "owner" | "employee" | null;
}) {
  vi.mocked(useSession).mockReturnValue({
    session: overrides.session,
    role: overrides.role ?? null,
    firmId: null,
    mustChangePassword: overrides.mustChangePassword,
    isLoading: overrides.isLoading ?? false,
  });
}

// QueryClientProvider added 2026-09-17: AuthenticatedLayout's nav now renders NotificationsNavLink
// (the unread-count badge), which calls useNotifications -> useQuery — every test through this
// helper needs a real provider now, not just the AuthenticatedHome describe block below that
// already had one for its own, separate reasons.
function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/set-new-password" element={<SetNewPasswordPage />} />
          <Route path="/" element={<AuthenticatedLayout />}>
            <Route index element={<div>HOME-CONTENT</div>} />
            <Route element={<OwnerRoute />}>
              <Route path="employees" element={<div>EMPLOYEES-CONTENT</div>} />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  it("shows the login form when there is no session", () => {
    mockSession({ session: null, mustChangePassword: false });
    renderAt("/login");
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("redirects to / when already signed in and no password change is due", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false });
    renderAt("/login");
    expect(screen.getByText("HOME-CONTENT")).toBeInTheDocument();
  });

  it("redirects to /set-new-password when signed in but a password change is due", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: true });
    renderAt("/login");
    expect(screen.getByRole("button", { name: /set password/i })).toBeInTheDocument();
  });
});

describe("SetNewPasswordPage", () => {
  it("redirects to /login when there is no session", () => {
    mockSession({ session: null, mustChangePassword: false });
    renderAt("/set-new-password");
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("redirects to / when signed in but no password change is due", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false });
    renderAt("/set-new-password");
    expect(screen.getByText("HOME-CONTENT")).toBeInTheDocument();
  });

  it("shows the form when signed in and a password change is due", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: true });
    renderAt("/set-new-password");
    expect(screen.getByRole("button", { name: /set password/i })).toBeInTheDocument();
  });
});

describe("AuthenticatedLayout", () => {
  it("redirects to /login when there is no session — the case that matters most: this must never leak the authenticated shell to a signed-out client", () => {
    mockSession({ session: null, mustChangePassword: false });
    renderAt("/");
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("HOME-CONTENT")).not.toBeInTheDocument();
  });

  it("redirects to /set-new-password when a password change is due — must never render the authenticated shell first", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: true });
    renderAt("/");
    expect(screen.getByRole("button", { name: /set password/i })).toBeInTheDocument();
    expect(screen.queryByText("HOME-CONTENT")).not.toBeInTheDocument();
  });

  it("renders the authenticated shell when signed in with no password change due", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false });
    renderAt("/");
    expect(screen.getByText("HOME-CONTENT")).toBeInTheDocument();
  });

  it("renders nothing while the session is still loading — never a flash of the gate's wrong state", () => {
    mockSession({ session: null, mustChangePassword: false, isLoading: true });
    const { container } = renderAt("/");
    expect(container).toBeEmptyDOMElement();
  });
});

// AuthenticatedHome (the "/" index route) wasn't covered by any test at all — every test above
// renders a <div>HOME-CONTENT</div> stub in its place, deliberately isolating the gate logic from
// the real screens. This describe block exercises the real component instead, since the
// Owner-vs-Employee branch it added is exactly the kind of "must never show the wrong role their
// screen" logic worth a real regression test, not a stub-based one.
describe("AuthenticatedHome", () => {
  beforeEach(() => {
    resetTasksFixture();
    resetEmployeesFixture();
    resetJobTypesFixture();
    resetNotificationsFixture();
  });

  function renderHome(role: "owner" | "employee" | null) {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false, role });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route index element={<AuthenticatedHome />} />
            <Route path="tasks" element={<div>MY-TASKS-CONTENT</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("redirects an Employee to /tasks instead of showing the Owner Dashboard", () => {
    renderHome("employee");
    expect(screen.getByText("MY-TASKS-CONTENT")).toBeInTheDocument();
  });

  it("renders the Owner Dashboard for an Owner", async () => {
    renderHome("owner");
    expect(await screen.findByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
  });

  // Regression for the code-review finding (2026-09-13): this previously fell through to
  // <OwnerDashboardPage /> for any role other than "employee", including the reachable null case
  // (a signed-in session whose app_metadata.role claim is missing/malformed). Must default-deny,
  // same as OwnerRoute/EmployeeRoute below — never default to the highest-privilege view.
  it("renders nothing for a session with no recognized role, rather than defaulting to the Owner Dashboard", () => {
    const { container } = renderHome(null);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("OwnerRoute", () => {
  it("redirects an Employee hitting an Owner route to / — FRONTEND_ARCHITECTURE.md §6's redirect-not-403 pattern, applied at the route", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false, role: "employee" });
    renderAt("/employees");
    expect(screen.getByText("HOME-CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("EMPLOYEES-CONTENT")).not.toBeInTheDocument();
  });

  it("renders the route for an Owner", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false, role: "owner" });
    renderAt("/employees");
    expect(screen.getByText("EMPLOYEES-CONTENT")).toBeInTheDocument();
  });

  it("renders nothing while the session is still loading", () => {
    mockSession({ session: _FAKE_SESSION, mustChangePassword: false, isLoading: true });
    const { container } = renderAt("/employees");
    expect(container).toBeEmptyDOMElement();
  });
});
