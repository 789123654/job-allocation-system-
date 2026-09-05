import { Navigate, Outlet, createBrowserRouter } from "react-router-dom";
import { AccountMenu } from "@/components/app-shell/account-menu";
import { LoginForm } from "@/features/auth/components/login-form";
import { SetNewPasswordForm } from "@/features/auth/components/set-new-password-form";
import { useSession } from "@/stores/session-store";

function LoginPage() {
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

function SetNewPasswordPage() {
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
function AuthenticatedLayout() {
  const { session, mustChangePassword, isLoading } = useSession();
  if (isLoading) return null;
  if (!session) return <Navigate to="/login" replace />;
  if (mustChangePassword) return <Navigate to="/set-new-password" replace />;
  return (
    <div className="min-h-screen">
      <header className="flex justify-end border-b border-(--color-ledger-border) p-4">
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

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/set-new-password", element: <SetNewPasswordPage /> },
  {
    path: "/",
    element: <AuthenticatedLayout />,
    children: [{ index: true, element: <AuthenticatedHome /> }],
  },
]);
