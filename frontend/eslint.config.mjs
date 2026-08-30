import { FlatCompat } from "@eslint/eslintrc";

// Flat-config replacement for the deprecated `next lint`. `next/core-web-vitals`
// pulls in the React, react-hooks, and @next/next rule sets (including the
// SEO-relevant ones — next/image, sync scripts, etc. — that matter for this SSR
// app); `next/typescript` adds @typescript-eslint/recommended.
const compat = new FlatCompat({
  // import.meta.dirname is available on Node >= 20.11.
  baseDirectory: import.meta.dirname,
});

const eslintConfig = [
  ...compat.config({
    extends: ["next/core-web-vitals", "next/typescript"],
  }),
  {
    // Vitest test / setup files: allow the test-runner globals and the
    // loose typing that fixtures and mocks tend to need.
    files: [
      "**/*.test.ts",
      "**/*.test.tsx",
      "vitest.setup.ts",
      "vitest.config.mts",
    ],
    languageOptions: {
      globals: {
        describe: "readonly",
        it: "readonly",
        test: "readonly",
        expect: "readonly",
        vi: "readonly",
        beforeAll: "readonly",
        afterAll: "readonly",
        beforeEach: "readonly",
        afterEach: "readonly",
      },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      ".amplify-hosting/**",
      "coverage/**",
      "next-env.d.ts",
    ],
  },
];

export default eslintConfig;
