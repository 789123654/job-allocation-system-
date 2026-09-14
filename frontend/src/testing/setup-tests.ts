import "@testing-library/jest-dom/vitest";
import { mockIPC } from "@tauri-apps/api/mocks";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "@/testing/mocks/handlers";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom doesn't implement scrollIntoView/hasPointerCapture/setPointerCapture/releasePointerCapture
// at all (a real, documented jsdom gap, not a project bug) — @radix-ui/react-select's own
// internals call these when its item list opens, first hit 2026-09-12 building the Owner Task
// Review outcome picker (this codebase's first Radix Select — Dialog/DropdownMenu don't need
// them). Confirmed empirically: the Select-interaction test failed with
// "candidate?.scrollIntoView is not a function" from inside @radix-ui/react-select's own source
// before this was added. No-op stubs are the standard workaround, since jsdom has no real layout
// engine to scroll within.
if (typeof Element !== "undefined") {
  Element.prototype.scrollIntoView ??= () => {};
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
}

// tauri-plugin-store's LazyStore (lib/supabase-client.ts) calls real Tauri IPC as soon as
// createClient() runs auth session recovery — which happens at module-import time (module-level
// `export const supabase = createClient(...)`), before any test's own beforeEach fires. Must be
// registered here at this file's top level (setupFiles run before the test file's own imports),
// not inside a hook, or the very first import of supabase-client.ts in any test file races this
// mock and loses.
//
// Must be a real, stateful in-memory map, not an always-empty stub: supabase-js's getSession()
// re-reads the custom storage adapter as its source of truth on every call (not just in-memory
// state) — an always-"not found" get() would silently clobber a session signInWithPassword just
// set, which is exactly what happened before this was made stateful (caught by
// lib/api-client.test.ts failing with a null Authorization header despite a successful sign-in).
// Exported (test-infra addition, not the module under test) so supabase-client.test.ts can assert
// directly on what actually got IPC'd into the mock Tauri store — e.g. that sign-in populates it
// and sign-out clears it — without re-mocking IPC itself.
export const storeState = new Map<string, unknown>();

mockIPC((cmd, args) => {
  // Return shapes matched against @tauri-apps/plugin-store's own JS wrapper source
  // (node_modules/@tauri-apps/plugin-store/dist-js/index.js) rather than guessed — `get` expects
  // an [value, exists] tuple, `load` expects a resource id.
  const params = args as { key?: string; value?: unknown };
  switch (cmd) {
    case "plugin:store|load":
      return 1;
    case "plugin:store|get": {
      const key = params.key ?? "";
      return storeState.has(key) ? [storeState.get(key), true] : [null, false];
    }
    case "plugin:store|set":
      storeState.set(params.key ?? "", params.value);
      return undefined;
    case "plugin:store|delete":
      return storeState.delete(params.key ?? "");
    default:
      if (cmd.startsWith("plugin:store|")) return undefined;
  }
});
