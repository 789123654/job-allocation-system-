/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Cargo writes to src-tauri/target concurrently while `tauri dev` builds the Rust binary —
    // Vite's own fs watcher racing that write causes an EBUSY crash on Windows. Tauri's official
    // Vite quickstart excludes this path for the same reason.
    watch: { ignored: ["**/src-tauri/**"] },
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    // Scoped to src/ so this config never discovers contract-tests/ (a separate tier, its own
    // vitest.contract.config.ts, no MSW setupFiles — see that file's own comment for why).
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/testing/setup-tests.ts"],
    globals: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      // Scaffold, entrypoints, test infra, and generated types — nothing with logic worth asserting.
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/testing/**",
        "src/**/types/**",
      ],
      // No `thresholds` yet on purpose: the frontend is mid-scaffold (Phase 4 slice 1), so a gate
      // now would be noise. Add one once the auth slice's screens land with their tests.
    },
  },
});
