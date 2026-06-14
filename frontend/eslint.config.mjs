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
    ignores: [".next/**", "node_modules/**", ".amplify-hosting/**", "next-env.d.ts"],
  },
];

export default eslintConfig;
