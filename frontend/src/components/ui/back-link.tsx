import { useNavigate } from "react-router-dom";

// Reported gap, 2026-09-17: Task Detail / Owner Task Review / Issue Resolution are all reached by
// drilling into one specific task or issue (My Tasks, All Tasks, a notification, Issues Raised),
// but none of them had any way back except the top nav tabs (Dashboard/Notifications/Job
// types/Employees) — those always land on a fixed top-level screen, not "wherever I came from".
// navigate(-1) (react-router's history-back) returns to the actual entry point regardless of which
// one was used, rather than hardcoding a single "back to X" destination per page.
export function BackLink() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(-1)}
      className="w-fit text-sm text-(--color-ledger-text-muted) hover:underline"
    >
      ← Back
    </button>
  );
}
