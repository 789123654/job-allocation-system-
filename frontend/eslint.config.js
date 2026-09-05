import { defineConfig } from "eslint/config";
import js from "@eslint/js";
import checkFile from "eslint-plugin-check-file";
import importPlugin from "eslint-plugin-import";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      import: importPlugin,
      "check-file": checkFile,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // Unidirectional architecture: shared -> features -> app. See docs/CODING_STRUCTURE.md §3.
      "import/no-restricted-paths": [
        "error",
        {
          zones: [
            // Cross-feature imports disabled, one zone per feature (bulletproof-react's exact
            // documented pattern) — added for all 7 features FRONTEND_ARCHITECTURE.md §2 already
            // names, not just the ones with content today, so the next feature slice is covered
            // without anyone having to remember to add a zone for it.
            { target: "./src/features/auth", from: "./src/features", except: ["./auth"] },
            { target: "./src/features/tasks", from: "./src/features", except: ["./tasks"] },
            { target: "./src/features/billing", from: "./src/features", except: ["./billing"] },
            {
              target: "./src/features/employees",
              from: "./src/features",
              except: ["./employees"],
            },
            {
              target: "./src/features/job-types",
              from: "./src/features",
              except: ["./job-types"],
            },
            { target: "./src/features/issues", from: "./src/features", except: ["./issues"] },
            {
              target: "./src/features/notifications",
              from: "./src/features",
              except: ["./notifications"],
            },
            {
              target: "./src/features",
              from: "./src/app",
            },
            {
              target: [
                "./src/components",
                "./src/hooks",
                "./src/lib",
                "./src/stores",
                "./src/types",
                "./src/utils",
              ],
              from: ["./src/features", "./src/app"],
            },
          ],
        },
      ],

      "check-file/filename-naming-convention": [
        "error",
        { "**/*.{ts,tsx}": "KEBAB_CASE" },
        { ignoreMiddleExtensions: true },
      ],
      "check-file/folder-naming-convention": ["error", { "src/**/!(__tests__)": "KEBAB_CASE" }],
    },
  },
);
