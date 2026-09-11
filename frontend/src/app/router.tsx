import { Link, Navigate, Outlet, createBrowserRouter } from "react-router-dom";
import { AccountMenu } from "@/components/app-shell/account-menu";
import { LoginForm } from "@/features/auth/components/login-form";
import { SetNewPasswordForm } from "@/features/auth/components/set-new-password-form";
import { EmployeeManagementPage } from "@/features/employees/components/employee-management-page";
import { JobTypeManagementPage } from "@/features/job-types/components/job-type-management-page";
import { useSession } from "@/stores/session-store";

// Exported for router.test.tsx — the client-side gate logic (mirroring backend/app/api/deps.py's
// require_password_set) is exercised directly, not through createBrowserRouter's real History API
// (which reads window.location at module-load time and isn't controllable per-test).
export function LoginPage() {
  const { session, mustChangePassword, isLoading } = useSession();
  if (isLoading) return null;
  if (session && !mustChangePassword) return <Navigate to="/" replace />;
  if (session && mustChangePassword) return <Navigate to="/set-new-password" replace />;
  return (
    <div className="flex min-h-screen items-center justify-center">
      <LoginForm />
    </div>
  );
}

export function SetNewPasswordPage() {
  const { session, mustChangePassword, isLoading } = useSession();
  if (isLoading) return null;
  if (!session) return <Navigate to="/login" replace />;
  if (!mustChangePassword) return <Navigate to="/" replace />;
  return (
    <div className="flex min-h-screen items-center justify-center">
      <SetNewPasswordForm />
    </div>
  );
}

// Route-level gating (FRONTEND_ARCHITECTURE.md §6) — not per-component checks scattered through
// the tree. UX only: backend/app/api/deps.py's require_password_set/get_current_profile
// independently enforce both gates server-side on every request regardless of what this shows.
export function AuthenticatedLayout() {
  const { session, role, mustChangePassword, isLoading } = useSession();
  if (isLoading) return null;
  if (!session) return <Navigate to="/login" replace />;
  if (mustChangePassword) return <Navigate to="/set-new-password" replace />;
  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-(--color-ledger-border) p-4">
        <nav className="flex gap-4 text-sm">
          {role === "owner" && (
            <>
              <Link to="/employees" className="text-(--color-ledger-text-muted) hover:underline">
                Employees
              </Link>
              <Link to="/job-types" className="text-(--color-ledger-text-muted) hover:underline">
                Job types
              </Link>
            </>
          )}
        </nav>
        <AccountMenu />
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  );
}

function AuthenticatedHome() {
  return <p>Signed in — Phase 4 Step 1 scaffolding.</p>;
}

// FRONTEND_ARCHITECTURE.md §6: "an Employee hitting an Owner route by URL redirects, same
// principle as API_SPEC.md's 404-not-403 object-access pattern applied one layer up, at the route
// rather than the resource" — a plain redirect to `/`, not a client-side 403 page. UX only: every
// Owner-gated endpoint this calls (RequireOwnerDep in deps.py) independently authorizes
// server-side regardless of what this route shows or hides.
export function OwnerRoute() {
  const { role, isLoading } = useSession();
  if (isLoading) return null;
  if (role !== "owner") return <Navigate to="/" replace />;
  return <Outlet />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/set-new-password", element: <SetNewPasswordPage /> },
  {
    path: "/",
    element: <AuthenticatedLayout />,
    children: [
      { index: true, element: <AuthenticatedHome /> },
      {
        element: <OwnerRoute />,
        children: [
          { path: "employees", element: <EmployeeManagementPage /> },
          { path: "job-types", element: <JobTypeManagementPage /> },
        ],
      },
    ],
  },
]);
