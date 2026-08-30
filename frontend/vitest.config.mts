import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": new URL(".", import.meta.url).pathname,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["lib/**/*.test.{ts,tsx}", "components/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["lib/**", "components/**"],
      exclude: ["**/*.test.{ts,tsx}", "**/team_registry.json"],
      reporter: ["text", "html"],
      thresholds: {
        // lib/ is pure logic — hold it to a high bar. Components are a touch
        // lower because recharts / Next router internals aren't worth chasing
        // to 100.
        "lib/**": { lines: 90, functions: 90, statements: 90, branches: 80 },
        lines: 85,
        functions: 85,
        statements: 85,
        branches: 75,
      },
    },
  },
});
