import { QueryClient } from "@tanstack/react-query";

// FRONTEND_ARCHITECTURE.md §3/§4: one preconfigured, reused-everywhere instance — same
// single-client pattern as lib/api-client.ts. No custom retry/staleTime overrides: TanStack
// Query's defaults (3 retries for queries, 0 for mutations — verified against tanstack.com's own
// docs, not assumed) are the right shape here; mutations must not silently auto-retry a
// non-idempotent-by-default call.
//
// refetchOnWindowFocus: false — this app is a Tauri desktop webview (WebView2 on Windows), not a
// browser tab. TanStack Query's default assumes a browser tab regaining focus after the user
// switches back from another tab; general knowledge, not verified against an installed skill (no
// installed skill covers Tauri+TanStack Query interaction specifically), but a well-known
// community-documented issue for Electron/Tauri apps: an embedded webview can dispatch spurious
// `window` focus events from ordinary in-window clicks, not just real tab switches, firing a
// refetch on nearly every click. Disabled after a reported bug, 2026-09-16 — confirmed via direct
// question to the user — Create Task's "Assign to" Select lost its selection no matter which
// field was clicked next; a focus-triggered refetch is the only mechanism in the app that fires
// on every click regardless of which element was clicked.
export const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});
