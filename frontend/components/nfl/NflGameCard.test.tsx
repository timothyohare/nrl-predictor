import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NflGameCard from "./NflGameCard";
import type { NflPrediction } from "@/lib/nfl/api";

function makeGame(overrides: Partial<NflPrediction> = {}): NflPrediction {
  return {
    matchId: "nfl-2026-week-9-raiders-v-chiefs",
    season: 2026,
    week: 9,
    stage: "REG",
    label: "Week 9",
    home_team: "raiders",
    home_team_name: "Raiders",
    away_team: "chiefs",
    away_team_name: "Chiefs",
    neutral: false,
    kickoff_utc: "2026-11-02T18:00:00Z",
    predicted_winner: "chiefs",
    predicted_winner_name: "Chiefs",
    predicted_margin: 6,
    margin_low: 3,
    margin_high: 10,
    home_win_probability: 0.32,
    confidence: "MEDIUM",
    key_factors: ["Elo rating gap: Chiefs +85", "Home-field advantage: Raiders"],
    reasoning: "Reasoning only shown once expanded.",
    model_used: "nfl-elo-v1",
    generation: 1,
    generatedAt: "2026-10-28T12:00:00+00:00",
    backfilled: false,
    ...overrides,
  };
}

describe("NflGameCard — prediction (spec 5.3)", () => {
  it("renders the winner and the integer margin band", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.getByTestId("nfl-pick")).toHaveTextContent("Chiefs by 3–10");
  });

  it("falls back to the point margin and the registry name", () => {
    render(<NflGameCard game={makeGame({
      predicted_winner_name: undefined, margin_low: undefined, margin_high: undefined,
    })} />);
    expect(screen.getByTestId("nfl-pick")).toHaveTextContent("Chiefs by 6");
  });

  it("shows the picked side's win probability and the confidence", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.getByText("68% win chance")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
  });

  it("names both teams with the home team marked", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Chiefs @ Raiders");
  });

  it("renders the kickoff in Sydney time", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.getByText("Tue 3 Nov, 5:00 am AEDT")).toBeInTheDocument();
  });

  it("renders 'Neutral site' iff neutral", () => {
    const { rerender } = render(<NflGameCard game={makeGame()} />);
    expect(screen.queryByText("Neutral site")).not.toBeInTheDocument();
    rerender(<NflGameCard game={makeGame({ neutral: true })} />);
    expect(screen.getByText("Neutral site")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Chiefs vs Raiders");
  });

  it("never renders 'Home ground'", () => {
    const { container, rerender } = render(<NflGameCard game={makeGame()} />);
    expect(container).not.toHaveTextContent("Home ground");
    rerender(<NflGameCard game={makeGame({ neutral: true, backfilled: true, result: {
      home_score: 20, away_score: 20, winner: null, winner_name: null, margin: 0 } })} />);
    expect(container).not.toHaveTextContent("Home ground");
  });

  it("lists key factors and toggles the reasoning accessibly", async () => {
    const user = userEvent.setup();
    render(<NflGameCard game={makeGame()} />);
    expect(screen.getByText("Elo rating gap: Chiefs +85")).toBeInTheDocument();
    expect(screen.queryByText("Reasoning only shown once expanded.")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Show reasoning" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByText("Reasoning only shown once expanded.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide reasoning" })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("NflGameCard — result", () => {
  it("renders no final score before the game is played", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.queryByTestId("nfl-result")).not.toBeInTheDocument();
  });

  it("renders the final score and a correct pick", () => {
    render(<NflGameCard game={makeGame({ result: {
      home_score: 17, away_score: 24, winner: "chiefs", winner_name: "Chiefs", margin: 7 } })} />);
    const result = screen.getByTestId("nfl-result");
    expect(result).toHaveTextContent("Final: Chiefs 24 – Raiders 17");
    expect(result).toHaveTextContent("Correct pick");
  });

  it("renders a wrong pick", () => {
    render(<NflGameCard game={makeGame({ result: {
      home_score: 27, away_score: 24, winner: "raiders", winner_name: "Raiders", margin: 3 } })} />);
    expect(screen.getByTestId("nfl-result")).toHaveTextContent("Wrong pick");
  });

  it("renders 'Tie' when the result has no winner", () => {
    render(<NflGameCard game={makeGame({ result: {
      home_score: 20, away_score: 20, winner: null, winner_name: null, margin: 0 } })} />);
    const result = screen.getByTestId("nfl-result");
    expect(result).toHaveTextContent("Final: Chiefs 20 – Raiders 20");
    expect(result).toHaveTextContent("Tie");
    expect(result).not.toHaveTextContent("pick");
  });
});

describe("NflGameCard — market, comparison only", () => {
  it("renders no market block without market data", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.queryByTestId("nfl-market")).not.toBeInTheDocument();
  });

  it("shows the spread favourite and implied probability, labelled as comparison only", () => {
    render(<NflGameCard game={makeGame({
      market: { spread_favourite: "chiefs", spread_line: -3.5, implied_home_prob: 0.36 },
      is_outlier: false,
    })} />);
    const market = screen.getByTestId("nfl-market");
    expect(market).toHaveTextContent("Market (comparison only)");
    expect(market).toHaveTextContent("Chiefs by 3.5");
    expect(market).toHaveTextContent("Raiders 36% / Chiefs 64%");
    expect(market).not.toHaveTextContent("Disagrees with market");
  });

  it("flags an outlier, a pick'em and a missing implied probability", () => {
    render(<NflGameCard game={makeGame({
      market: { spread_favourite: null, spread_line: 0, implied_home_prob: null },
      is_outlier: true,
    })} />);
    const market = screen.getByTestId("nfl-market");
    expect(market).toHaveTextContent("Pick'em");
    expect(market).toHaveTextContent("Disagrees with market");
    expect(market).not.toHaveTextContent("%");
  });

  it("omits the spread when the market only has moneylines", () => {
    render(<NflGameCard game={makeGame({
      market: { spread_favourite: null, spread_line: null, implied_home_prob: 0.5 },
    })} />);
    const market = screen.getByTestId("nfl-market");
    expect(market).not.toHaveTextContent("Pick'em");
    expect(market).toHaveTextContent("Raiders 50% / Chiefs 50%");
  });
});

describe("NflGameCard — backtest label (user decision Q2)", () => {
  it("shows no badge on a live prediction", () => {
    render(<NflGameCard game={makeGame()} />);
    expect(screen.queryByText("Backtest")).not.toBeInTheDocument();
  });

  it("shows a visible Backtest badge explained in text, not only a tooltip", () => {
    render(<NflGameCard game={makeGame({ backfilled: true })} />);
    const badge = screen.getByText("Backtest");
    expect(badge).toHaveAttribute("title", expect.stringContaining("after the fact"));
    const explanation = screen.getByText(/generated after the fact from pre-week ratings/i);
    expect(badge).toHaveAttribute("aria-describedby", explanation.id);
    expect(within(screen.getByRole("article")).getByText("Backtest")).toBeVisible();
  });
});
