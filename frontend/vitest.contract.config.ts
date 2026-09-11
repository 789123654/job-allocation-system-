import path from "node:path";
import { defineConfig } from "vitest/config";

// Separate config, separate tier — same reasoning as backend/tests/e2e vs. the plain backend
// suite: `vite.config.ts`'s normal `npm run test` loads src/testing/setup-tests.ts, which starts
// MSW with `onUnhandledRequest: "error"`. A contract test's entire point is a REAL network call to
// a real backend, which MSW would treat as an error and reject. No setupFiles here — nothing
// intercepts fetch. Never run by `npm run test`/`test:coverage` (different include pattern, lives
// outside src/); only invoked explicitly in CI's `e2e` job, gated on CONTRACT_API_BASE_URL/
// CONTRACT_TEST_TOKEN being set (the contract test itself skips otherwise).
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  test: {
    include: ["contract-tests/**/*.test.ts"],
    environment: "node",
  },
});
