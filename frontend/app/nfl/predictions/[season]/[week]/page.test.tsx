import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import NflWeekPage from "./page";

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({
  notFound: () => notFound(),
  useRouter: () => ({ push: vi.fn() }),
}));

const BASE = "https://nfl.example.test";

const GAME = {
  matchId: "nfl-2026-week-8-raiders-v-chiefs", season: 2026, week: 8, stage: "REG", label: "Week 8",
  home_team: "raiders", home_team_name: "Raiders", away_team: "chiefs", away_team_name: "Chiefs",
  neutral: false, kickoff_utc: "2026-11-02T18:00:00Z", predicted_winner: "chiefs",
  predicted_winner_name: "Chiefs", predicted_margin: 6, margin_low: 3, margin_high: 10,
  home_win_probability: 0.32, confidence: "MEDIUM", key_factors: ["Elo rating gap"],
  reasoning: "Elo.", model_used: "nfl-elo-v1", generation: 1,
  generatedAt: "2026-10-28T12:00:00+00:00", backfilled: true,
};

function serve(predictions: { ok: boolean; status: number; body?: unknown }) {
  const fn = vi.fn(async (url: string) => {
    if (url.includes("/nfl/weeks")) {
      return { ok: true, status: 200, json: async () => ({ season: 2026, weeks: [
        { week: 7, stage: "REG", label: "Week 7" }, { week: 8, stage: "REG", label: "Week 8" }] }) };
    }
    return { ok: predictions.ok, status: predictions.status, json: async () => predictions.body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const page = (season: string, week: string) =>
  NflWeekPage({ params: Promise.resolve({ season, week }) });

beforeEach(() => {
  vi.stubEnv("NFL_API_BASE_URL", BASE);
  notFound.mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("/nfl/predictions/[season]/[week]", () => {
  it("renders the week's games under the API label with the week selector", async () => {
    serve({ ok: true, status: 200, body: [GAME] });
    render(await page("2026", "8"));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("2026 Week 8");
    expect(screen.getByTestId("nfl-pick")).toHaveTextContent("Chiefs by 3–10");
    expect(screen.getByLabelText("Week:")).toHaveValue("8");
  });

  it("explains the backtest label at page level when any game is backfilled", async () => {
    serve({ ok: true, status: 200, body: [GAME] });
    render(await page("2026", "8"));
    expect(screen.getByRole("note")).toHaveTextContent(/backtest/i);
  });

  it("has no backtest note when every game is live", async () => {
    serve({ ok: true, status: 200, body: [{ ...GAME, backfilled: false }] });
    render(await page("2026", "8"));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("shows an empty state for a week with no predictions", async () => {
    serve({ ok: false, status: 404 });
    render(await page("2026", "7"));
    expect(screen.getByText(/No NFL predictions yet for Week 7/)).toBeInTheDocument();
  });

  it("renders 'NFL predictions unavailable' when NFL_API_BASE_URL is unset (spec 5.6)", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    const fn = serve({ ok: true, status: 200, body: [GAME] });
    render(await page("2026", "8"));
    expect(screen.getByText("NFL predictions unavailable")).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it("renders 'NFL predictions unavailable' when the fetch fails (spec 5.6)", async () => {
    serve({ ok: false, status: 500 });
    render(await page("2026", "8"));
    expect(screen.getByText("NFL predictions unavailable")).toBeInTheDocument();
  });

  it.each([["abc", "8"], ["2026", "eight"], ["2026", "0"], ["2026", "26"], ["1800", "8"], ["2026", "8.5"]])(
    "404s on season %j week %j without calling the API", async (season, week) => {
      const fn = serve({ ok: true, status: 200, body: [GAME] });
      await expect(page(season, week)).rejects.toThrow("NEXT_NOT_FOUND");
      expect(fn).not.toHaveBeenCalled();
    },
  );
});
