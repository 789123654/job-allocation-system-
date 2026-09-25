import { Link, Navigate, Outlet, createBrowserRouter, useLocation, useParams } from "react-router-dom";
import { AccountMenu } from "@/components/app-shell/account-menu";
import { BackLink } from "@/components/ui/back-link";
import { ErrorBoundary } from "@/components/error-boundary";
import { LoginForm } from "@/features/auth/components/login-form";
import { SetNewPasswordForm } from "@/features/auth/components/set-new-password-form";
import { EmployeeManagementPage } from "@/features/employees/components/employee-management-page";
import { useEmployees } from "@/features/employees/api/get-employees";
import { OwnerDashboardPage } from "@/app/owner-dashboard-page";
import { JobTypeManagementPage } from "@/features/job-types/components/job-type-management-page";
import { useNotifications } from "@/features/notifications/api/get-notifications";
import { IssueDetailPage } from "@/features/tasks/components/issue-detail-page";
import { IssueResolutionPage } from "@/features/tasks/components/issue-resolution-page";
import { MyTasksPage } from "@/features/tasks/components/my-tasks-page";
import { NotificationsPage } from "@/features/notifications/components/notifications-page";
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

// Reported gap, 2026-09-17: nothing surfaced *that* a new notification existed unless the Owner
// remembered to click into the Notifications screen on their own — a badge on the nav link is the
// actual fix (not a bigger polling interval or a toast, which the PRD/ARCHITECTURE docs never
// asked for) since useNotifications already polls every 45s (get-notifications.ts). `limit: 100`
// (the server's own max, core/validation.py) so the count is real up to a realistic ceiling for
// this app's pilot scale (2-4 firms, ~30 users — ca-tool-project-scope) instead of silently
// capping at the route's default limit of 20 and under-reporting.
function NotificationsNavLink() {
  const { data: notifications } = useNotifications({ unreadOnly: true, limit: 100 });
  const unreadCount = notifications?.length ?? 0;
  return (
    <Link
      to="/notifications"
      className="relative flex items-center gap-1.5 text-(--color-ledger-text-muted) hover:underline"
    >
      Notifications
      {unreadCount > 0 && (
        <span
          className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-(--color-ledger-danger) px-1 text-[10px] leading-none font-semibold text-(--color-ledger-accent-fg)"
          aria-label={`${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}`}
        >
          {unreadCount >= 100 ? "99+" : unreadCount}
        </span>
      )}
    </Link>
  );
}

// Route-level gating (FRONTEND_ARCHITECTURE.md §6) — not per-component checks scattered through
// the tree. UX only: backend/app/api/deps.py's require_password_set/get_current_profile
// independently enforce both gates server-side on every request regardless of what this shows.
export function AuthenticatedLayout() {
  const { session, role, mustChangePassword, isLoading } = useSession();
  const location = useLocation();
  if (isLoading) return null;
  if (!session) return <Navigate to="/login" replace />;
  if (mustChangePassword) return <Navigate to="/set-new-password" replace />;
  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-(--color-ledger-border) p-4">
        <div className="flex items-center gap-4">
          {/* Reported gap, 2026-09-17: BackLink previously only lived on the 3 drill-down screens
              (Task Detail/Owner Task Review/Issue Resolution) that added it individually — so it
              only ever appeared when reached one particular way, not consistently everywhere.
              Hoisted here instead: one instance, in the shared layout every route renders inside,
              so it's on every screen in the system, not screen-by-screen. */}
          <BackLink />
          <nav className="flex gap-4 text-sm">
          {role === "owner" && (
            <>
              <Link to="/" className="text-(--color-ledger-text-muted) hover:underline">
                Dashboard
              </Link>
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
          <NotificationsNavLink />
          </nav>
        </div>
        <AccountMenu />
      </header>
      <main className="p-6">
        {/* Scoped to page content only, not the header/nav/AccountMenu above — a crash rendering
            one screen must not take the notification link or account menu down with it
            (CODING_STRUCTURE.md's error-handling section, code-review finding, whole-Phase-4
            sweep, 2026-09-13). Keyed on the path so navigating away from a crashed screen actually
            recovers, instead of the boundary's tripped state persisting across every later route. */}
        <ErrorBoundary key={location.pathname} fallbackMessage="Something went wrong loading this page — try navigating away and back.">
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}

// Owner's real landing page as of this pass; Employee's landing page is My Tasks (redirect, not
// a duplicate placeholder) — the last remaining use of the Phase 4 Step 1 scaffolding text is
// gone now that Dashboard exists. Exported (like LoginPage/OwnerRoute below) so router.test.tsx
// can exercise the real role branch directly, not a stub.
export function AuthenticatedHome() {
  const { role, isLoading } = useSession();
  if (isLoading) return null;
  if (role === "owner") return <OwnerDashboardPage />;
  if (role === "employee") return <Navigate to="/tasks" replace />;
  // Default-deny, matching OwnerRoute/EmployeeRoute below: an authenticated session with a
  // missing/malformed role claim (session-store.tsx's role is "owner" | "employee" | null) must
  // never fall through to the highest-privilege view. Renders nothing, same as the isLoading case
  // above — found by an independent code-review pass (2026-09-13) after this previously defaulted
  // to <OwnerDashboardPage /> for any non-"employee" role, including null.
  return null;
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

// Same key-remount reasoning as TaskDetailRoute above, applied to IssueDetailPage — a plain read
// view (no per-instance Idempotency-Key to worry about, unlike TaskDetailPage/OwnerTaskReviewRoute
// et al.), but keying it still avoids a stale query-cache render if the raiser navigates from one
// resolved issue's notification straight to another's without an intervening full page load.
function IssueDetailRoute() {
  const { issueId } = useParams<{ issueId: string }>();
  return <IssueDetailPage key={issueId} />;
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
  // Same PRD workload-visibility requirement as owner-dashboard-page.tsx's CreateTaskDialog —
  // reassigning during review is an assignment decision too.
  const employeeOptions = (employees ?? []).map((e) => ({
    id: e.id,
    label: `${e.fullName} (${e.pendingTaskCount} pending)`,
  }));
  return <OwnerTaskReviewPage key={taskId} employeeOptions={employeeOptions} />;
}

// Same reasoning as OwnerTaskReviewRoute above, applied to IssueResolutionPage's reassign
// employee picker — same cross-feature-import restriction, same fix.
function OwnerIssueResolutionRoute() {
  const { issueId } = useParams<{ issueId: string }>();
  const { data: employees } = useEmployees();
  // Same PRD workload-visibility requirement as above.
  const employeeOptions = (employees ?? []).map((e) => ({
    id: e.id,
    label: `${e.fullName} (${e.pendingTaskCount} pending)`,
  }));
  return <IssueResolutionPage key={issueId} employeeOptions={employeeOptions} />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/set-new-password", element: <SetNewPasswordPage /> },
  {
    path: "/",
    element: <AuthenticatedLayout />,
    children: [
      { index: true, element: <AuthenticatedHome /> },
      { path: "notifications", element: <NotificationsPage /> },
      {
        element: <OwnerRoute />,
        children: [
          { path: "employees", element: <EmployeeManagementPage /> },
          { path: "job-types", element: <JobTypeManagementPage /> },
          { path: "owner-tasks/:taskId/review", element: <OwnerTaskReviewRoute /> },
          { path: "owner-issues/:issueId/resolve", element: <OwnerIssueResolutionRoute /> },
        ],
      },
      {
        element: <EmployeeRoute />,
        children: [
          { path: "tasks", element: <MyTasksPage /> },
          { path: "tasks/:taskId", element: <TaskDetailRoute /> },
          { path: "issues/:issueId", element: <IssueDetailRoute /> },
        ],
      },
    ],
  },
]);
