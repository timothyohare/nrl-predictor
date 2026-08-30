import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MatchCard from "./MatchCard";
import type { Prediction } from "@/lib/api";

function makePrediction(overrides: Partial<Prediction> = {}): Prediction {
  return {
    matchId: "round-12-panthers-v-broncos",
    predicted_winner: "panthers",
    predicted_margin: 12,
    confidence: "HIGH",
    key_factors: ["Home fortress at BlueBet", "Broncos missing their halfback"],
    reasoning: "A long-form reasoning paragraph that only shows once expanded.",
    data_freshness: "2026-08-01T00:00:00Z",
    model_used: "stats-elo-v1",
    generated_at: new Date().toISOString(),
    staleness_flag: false,
    status: "OK",
    ...overrides,
  };
}

describe("MatchCard — core prediction rendering", () => {
  it("renders predicted winner, margin and confidence", () => {
    const { container } = render(<MatchCard prediction={makePrediction()} />);

    const winnerLine = container.querySelector("p.text-2xl");
    expect(winnerLine).toHaveTextContent("Panthers BY 12");
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("Home fortress at BlueBet")).toBeInTheDocument();
  });

  it("applies the winner's team colour as the left-border accent", () => {
    const { container } = render(<MatchCard prediction={makePrediction()} />);
    // panthers accent is #00674F (teal) — rgb(0, 103, 79)
    expect(container.firstChild).toHaveStyle({ borderLeftColor: "#00674F" });
  });

  it("omits the ' BY n' suffix when the predicted margin is 0", () => {
    const { container } = render(
      <MatchCard prediction={makePrediction({ predicted_margin: 0 })} />,
    );
    expect(container.querySelector("p.text-2xl")).not.toHaveTextContent("BY");
  });

  it("renders the FAILED placeholder instead of a prediction when status is FAILED", () => {
    render(<MatchCard prediction={makePrediction({ status: "FAILED" })} />);
    expect(screen.getByText("Prediction unavailable for this match.")).toBeInTheDocument();
    expect(screen.queryByText("HIGH")).not.toBeInTheDocument();
  });

  it("shows the staleness banner only when staleness_flag is set", () => {
    const { rerender } = render(<MatchCard prediction={makePrediction()} />);
    expect(screen.queryByText(/budget limit reached/)).not.toBeInTheDocument();
    rerender(<MatchCard prediction={makePrediction({ staleness_flag: true })} />);
    expect(screen.getByText(/budget limit reached/)).toBeInTheDocument();
  });
});

describe("MatchCard — result block", () => {
  const scored = makePrediction({
    result: {
      winner: "panthers",
      homeTeam: "panthers",
      awayTeam: "broncos",
      homeScore: 24,
      awayScore: 12,
      margin: 12,
    },
  });

  it("renders the score line and a correct-winner tick once the match is scored", () => {
    render(<MatchCard prediction={scored} />);
    expect(screen.getByText(/PANTHERS/)).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("✓ winner")).toBeInTheDocument();
  });

  it("marks a wrong winner when the result disagrees with the prediction", () => {
    render(
      <MatchCard
        prediction={makePrediction({
          predicted_winner: "panthers",
          result: {
            winner: "broncos",
            homeTeam: "panthers",
            awayTeam: "broncos",
            homeScore: 10,
            awayScore: 30,
            margin: 20,
          },
        })}
      />,
    );
    expect(screen.getByText("✗ winner")).toBeInTheDocument();
  });

  it("shows no result block before the match is scored", () => {
    render(<MatchCard prediction={makePrediction()} />);
    expect(screen.queryByText("✓ winner")).not.toBeInTheDocument();
    expect(screen.queryByText("✗ winner")).not.toBeInTheDocument();
  });
});

describe("MatchCard — outlier badge", () => {
  const odds = {
    market_favourite: "Broncos",
    market_margin: 4,
    home_odds: 2.5,
    away_odds: 1.5,
    implied_home_prob: 0.4,
    implied_away_prob: 0.6,
  };

  it("shows the 'Disagrees with market' badge only when is_outlier is true", () => {
    const { rerender } = render(
      <MatchCard prediction={makePrediction({ odds, is_outlier: true })} />,
    );
    expect(screen.getByText("Disagrees with market")).toBeInTheDocument();

    rerender(<MatchCard prediction={makePrediction({ odds, is_outlier: false })} />);
    expect(screen.queryByText("Disagrees with market")).not.toBeInTheDocument();
  });

  it("renders no market panel at all when there are no odds", () => {
    render(<MatchCard prediction={makePrediction({ is_outlier: true })} />);
    expect(screen.queryByText(/Market odds/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Disagrees with market")).not.toBeInTheDocument();
  });
});

describe("MatchCard — expandable sections", () => {
  it("reveals the reasoning paragraph only after clicking 'Show reasoning'", async () => {
    const user = userEvent.setup();
    render(<MatchCard prediction={makePrediction()} />);
    expect(
      screen.queryByText(/long-form reasoning paragraph/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByText("Show reasoning"));
    expect(screen.getByText(/long-form reasoning paragraph/)).toBeInTheDocument();
  });

  it("offers the post-match analysis toggle only when a retrospective exists, and renders it on click", async () => {
    const user = userEvent.setup();
    const withRetro = makePrediction({
      retrospective: {
        verdict: "Called the winner, under-cooked the margin.",
        hit_factors: ["Home advantage"],
        missed_factors: ["Bench impact"],
        what_actually_happened: "Panthers pulled away in the final ten minutes.",
        lesson: "Trust the home fortress.",
        generated_at: "2026-08-02T00:00:00Z",
      },
    });

    const { rerender } = render(<MatchCard prediction={makePrediction()} />);
    expect(screen.queryByText("Post-match analysis")).not.toBeInTheDocument();

    rerender(<MatchCard prediction={withRetro} />);
    await user.click(screen.getByText("Post-match analysis"));
    expect(screen.getByText("What actually happened")).toBeInTheDocument();
    expect(
      screen.getByText("Called the winner, under-cooked the margin."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Trust the home fortress/)).toBeInTheDocument();
  });

  it("shows an update tag when the prediction is a later generation", () => {
    render(<MatchCard prediction={makePrediction({ generation: 3 })} />);
    expect(screen.getByText(/update #3/)).toBeInTheDocument();
  });
});

describe("MatchCard — staleness footer", () => {
  const hoursAgo = (h: number) =>
    new Date(Date.now() - h * 3600_000).toISOString();

  it("reads 'just now' for a fresh prediction", () => {
    render(<MatchCard prediction={makePrediction({ generated_at: hoursAgo(0) })} />);
    expect(screen.getByText(/Updated just now/)).toBeInTheDocument();
  });

  it("reads 'Nh ago' within the first day", () => {
    render(<MatchCard prediction={makePrediction({ generated_at: hoursAgo(5) })} />);
    expect(screen.getByText(/Updated 5h ago/)).toBeInTheDocument();
  });

  it("reads 'Nd ago' after a day", () => {
    render(<MatchCard prediction={makePrediction({ generated_at: hoursAgo(50) })} />);
    expect(screen.getByText(/Updated 2d ago/)).toBeInTheDocument();
  });
});
