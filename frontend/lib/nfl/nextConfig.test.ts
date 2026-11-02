import { afterEach, describe, expect, it, vi } from "vitest";

// Amplify's Next.js SSR compute doesn't reliably expose console env vars at
// runtime, only at build time — so NFL_API_BASE_URL is baked in via next.config.
describe("next.config env", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("bakes NFL_API_BASE_URL from the build environment", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "https://nfl.example.test");
    const { default: config } = await import("../../next.config");
    expect(config.env?.NFL_API_BASE_URL).toBe("https://nfl.example.test");
  });

  it("bakes an empty string when NFL_API_BASE_URL is unset", async () => {
    vi.stubEnv("NFL_API_BASE_URL", undefined);
    const { default: config } = await import("../../next.config");
    expect(config.env?.NFL_API_BASE_URL).toBe("");
  });
});
