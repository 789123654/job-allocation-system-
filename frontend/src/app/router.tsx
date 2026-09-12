import { Link, Navigate, Outlet, createBrowserRouter, useParams } from "react-router-dom";
import { AccountMenu } from "@/components/app-shell/account-menu";
import { LoginForm } from "@/features/auth/components/login-form";
import { SetNewPasswordForm } from "@/features/auth/components/set-new-password-form";
import { EmployeeManagementPage } from "@/features/employees/components/employee-management-page";
import { useEmployees } from "@/features/employees/api/get-employees";
import { JobTypeManagementPage } from "@/features/job-types/components/job-type-management-page";
import { MyTasksPage } from "@/features/tasks/components/my-tasks-page";
import { OwnerTaskReviewPage } from "@/features/tasks/components/owner-task-review-page";
import { TaskDetailPage } from "@/features/tasks/components/task-detail-page";
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
          {role === "employee" && (
            <Link to="/tasks" className="text-(--color-ledger-text-muted) hover:underline">
              My tasks
            </Link>
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

// Same redirect-not-403 pattern as OwnerRoute, inverted — My Tasks/Task Detail & Submit are
// Employee-only (FRONTEND_ARCHITECTURE.md §1); an Owner has no screen here yet (the Owner
// Dashboard is a later Tasks pass), so redirect to / rather than show nothing or crash.
export function EmployeeRoute() {
  const { role, isLoading } = useSession();
  if (isLoading) return null;
  if (role !== "employee") return <Navigate to="/" replace />;
  return <Outlet />;
}

// task-detail-page.tsx generates a one-time-per-task Idempotency-Key with a plain useState lazy
// initializer (runs once per component *instance*, not per taskId) — so navigating from one
// task's detail page directly to another's needs a real remount to get a fresh key, not just a
// re-render. React's own core guarantee (react-official's preserving-and-resetting-state.md,
// re-checked this pass): a changed `key` always forces unmount+remount, independent of whatever
// react-router itself does internally on a dynamic-segment change (undocumented in any installed
// skill, so not depended on here). This wrapper is the one place that reads the param and keys
// the child on it.
function TaskDetailRoute() {
  const { taskId } = useParams<{ taskId: string }>();
  return <TaskDetailPage key={taskId} />;
}

// Same key-remount reasoning as TaskDetailRoute above, applied to OwnerTaskReviewPage's own
// per-task Idempotency-Key. Also the composition point FRONTEND_ARCHITECTURE.md §2's "features
// cannot import each other" requires: features/tasks can't import features/employees directly,
// so this app/-level wrapper fetches the employee list and passes it down as plain {id,label}
// options — not the Dashboard yet (deferred, this session's scoping decision), just enough to
// make Task Review's reassign/billing employee picker functional and testable now.
function OwnerTaskReviewRoute() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: employees } = useEmployees();
  const employeeOptions = (employees ?? []).map((e) => ({ id: e.id, label: e.fullName }));
  return <OwnerTaskReviewPage key={taskId} employeeOptions={employeeOptions} />;
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
          { path: "owner-tasks/:taskId/review", element: <OwnerTaskReviewRoute /> },
        ],
      },
      {
        element: <EmployeeRoute />,
        children: [
          { path: "tasks", element: <MyTasksPage /> },
          { path: "tasks/:taskId", element: <TaskDetailRoute /> },
        ],
      },
    ],
  },
]);
