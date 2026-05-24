// ESLint flat config — see https://eslint.org/docs/latest/use/configure/configuration-files-new
//
// Minimal baseline: typescript-eslint v8 recommended rules + lenient overrides
// so the existing codebase passes without a sweeping rewrite. Goal is "passes
// lint", not "rewrites everything."

import tseslint from "typescript-eslint";

export default tseslint.config(
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts", "tests/**/*.ts", "scripts/**/*.ts"],
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
  {
    ignores: ["dist/", "node_modules/", "**/*.js.map", "**/*.d.ts", "*.config.js"],
  },
);
