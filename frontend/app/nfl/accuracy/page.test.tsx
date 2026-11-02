import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import NflAccuracyPage, { metadata } from "./page";

const ACCURACY = {
  season: 2026, n: 100, accuracy: 0.655, brier: 0.2154, margin_mae: 10.42,
  n_accuracy: 99, n_brier: 100, n_margin: 100, n_backfilled: 90,
  by_confidence: {
    HIGH: { n: 30, accuracy: 0.8 }, MEDIUM: { n: 40, accuracy: 0.65 }, LOW: { n: 30, accuracy: null },
  },
  baselines: {
    home: { p_home: 0.5727, margin: 2.6, n: 100, accuracy: 0.55, brier: 0.245, margin_mae: 11.9 },
    market: { n: 100, accuracy: 0.68, brier: 0.208, margin_mae: 10.1 },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function serve(body: unknown, ok = true, status = 200) {
  vi.stubEnv("NFL_API_BASE_URL", "https://nfl.example.test");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok, status, json: async () => body })));
}

describe("/nfl/accuracy", () => {
  it("compares the model with the home baseline and the market", async () => {
    serve(ACCURACY);
    render(await NflAccuracyPage());
    const table = screen.getByRole("table", { name: /model vs baselines/i });
    expect(table).toHaveTextContent("Model");
    expect(table).toHaveTextContent("65.5%");
    expect(table).toHaveTextContent("Always pick the home team");
    expect(table).toHaveTextContent("55.0%");
    expect(table).toHaveTextContent("Betting market (comparison only)");
    expect(table).toHaveTextContent("0.208");
    expect(table).toHaveTextContent("10.4");
  });

  it("discloses how many graded games are backtest predictions", async () => {
    serve(ACCURACY);
    render(await NflAccuracyPage());
    expect(screen.getByRole("note")).toHaveTextContent("90 of 100 graded games are backtest predictions");
  });

  it("shows accuracy by confidence, with a dash where nothing is graded", async () => {
    serve(ACCURACY);
    render(await NflAccuracyPage());
    const table = screen.getByRole("table", { name: /by confidence/i });
    expect(table).toHaveTextContent("HIGH");
    expect(table).toHaveTextContent("80.0%");
    expect(table).toHaveTextContent("—");
  });

  it("handles a season with nothing graded yet", async () => {
    serve({ ...ACCURACY, n: 0, accuracy: null, brier: null, margin_mae: null, n_backfilled: 0 });
    render(await NflAccuracyPage());
    expect(screen.getByText(/No graded NFL games yet/)).toBeInTheDocument();
  });

  it("renders the unavailable state when NFL_API_BASE_URL is unset", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    render(await NflAccuracyPage());
    expect(screen.getByText("NFL predictions unavailable")).toBeInTheDocument();
  });

  // Final fixes (review N1): only "not configured" renders unavailable; any other
  // failure throws so ISR keeps serving the last good page.
  it.each([429, 500])("throws when the API returns %i", async (status) => {
    serve({}, false, status);
    await expect(NflAccuracyPage()).rejects.toThrow(String(status));
  });

  it("throws on a network failure", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "https://nfl.example.test");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(NflAccuracyPage()).rejects.toThrow("fetch failed");
  });

  it("has its own title and description", () => {
    expect(metadata.title).toBe("NFL Prediction Accuracy — NRL Predictor");
    expect(metadata.description).toMatch(/home-team baseline and the betting market/);
  });
});
