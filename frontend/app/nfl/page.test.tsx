import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import NflHomePage from "./page";

const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));

beforeEach(() => {
  redirect.mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("/nfl", () => {
  it("redirects to the current week from /nfl/weeks/current", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "https://nfl.example.test");
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200,
      json: async () => ({ season: 2026, week: 8, stage: "REG", label: "Week 8" }),
    })));
    await expect(NflHomePage()).rejects.toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenCalledWith("/nfl/predictions/2026/8");
  });

  it("renders the unavailable state when NFL_API_BASE_URL is unset", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    render(await NflHomePage());
    expect(screen.getByText("NFL predictions unavailable")).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("renders the unavailable state when the API fails", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "https://nfl.example.test");
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 429, json: async () => ({}) })));
    render(await NflHomePage());
    expect(screen.getByText("NFL predictions unavailable")).toBeInTheDocument();
  });
});
