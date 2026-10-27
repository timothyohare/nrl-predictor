"use client";

import { useId, useState } from "react";
import type { NflMarket, NflPrediction } from "@/lib/nfl/api";
import { formatKickoff, marginText, winnerProbability } from "@/lib/nfl/format";
import { teamName } from "@/lib/nfl/teams";

const CONFIDENCE_STYLES: Record<string, string> = {
  HIGH: "bg-green-700 text-white",
  MEDIUM: "bg-yellow-400 text-yellow-900",
  LOW: "bg-red-700 text-white",
};

export const BACKTEST_EXPLANATION =
  "Backtest: generated after the fact from pre-week ratings, not a live pick.";

const pct = (p: number) => `${Math.round(p * 100)}%`;

function MarketPanel({ market, home, away, isOutlier }: {
  market: NflMarket;
  home: string;
  away: string;
  isOutlier?: boolean;
}) {
  const { spread_line, spread_favourite, implied_home_prob } = market;
  return (
    <div data-testid="nfl-market" className="border-t pt-3 space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
          Market (comparison only)
        </p>
        {isOutlier && (
          <span className="text-[10px] font-bold bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">
            Disagrees with market
          </span>
        )}
      </div>
      <p className="text-xs text-gray-700 flex gap-3 flex-wrap">
        {spread_line != null && (
          <span>
            <span className="text-gray-600">Spread: </span>
            {spread_favourite
              ? `${teamName(spread_favourite)} by ${Math.abs(spread_line)}`
              : "Pick'em"}
          </span>
        )}
        {implied_home_prob != null && (
          <span>
            <span className="text-gray-600">Implied: </span>
            {home} {pct(implied_home_prob)} / {away} {pct(1 - implied_home_prob)}
          </span>
        )}
      </p>
    </div>
  );
}

export default function NflGameCard({ game }: { game: NflPrediction }) {
  const [expanded, setExpanded] = useState(false);
  const explanationId = useId();
  const headingId = useId();

  const home = game.home_team_name || teamName(game.home_team);
  const away = game.away_team_name || teamName(game.away_team);
  const winner = game.predicted_winner_name || teamName(game.predicted_winner);
  const kickoff = formatKickoff(game.kickoff_utc);
  const result = game.result;

  return (
    <article
      aria-labelledby={headingId}
      className="bg-nrl-paper rounded-xl border-2 border-gray-200 border-l-[6px] border-l-nrl-blue p-5 space-y-3"
    >
      <div className="flex justify-between items-start gap-2">
        <div className="space-y-0.5">
          <h3 id={headingId} className="font-semibold text-gray-800 text-sm">
            {away} {game.neutral ? "vs" : "@"} {home}
          </h3>
          <p className="text-xs text-gray-600">
            {kickoff}
            {game.neutral && (
              <span className="ml-2 font-semibold text-nrl-blue">Neutral site</span>
            )}
          </p>
        </div>
        <div className="flex gap-1.5 shrink-0 flex-wrap justify-end">
          {game.backfilled && (
            <span
              title="Generated after the fact by the walk-forward backtest, from ratings as they stood before this week. Not a live pick."
              aria-describedby={explanationId}
              className="font-display text-[10px] tracking-wider px-2 py-1 rounded bg-nrl-gold text-nrl-blue border border-nrl-blue"
            >
              Backtest
            </span>
          )}
          <span className={`font-display text-[10px] tracking-wider px-2 py-1 rounded ${CONFIDENCE_STYLES[game.confidence] ?? ""}`}>
            {game.confidence}
          </span>
        </div>
      </div>

      {game.backfilled && (
        <p id={explanationId} className="text-xs text-gray-700 bg-nrl-cream rounded px-2 py-1">
          {BACKTEST_EXPLANATION}
        </p>
      )}

      <div className="space-y-1">
        <p data-testid="nfl-pick" className="font-display text-2xl leading-none text-nrl-blue">
          {winner} by {marginText(game)}
        </p>
        <p className="text-sm text-gray-700">{pct(winnerProbability(game))} win chance</p>
      </div>

      {result && (
        <div data-testid="nfl-result" className="flex items-baseline gap-2 flex-wrap">
          <p className="font-semibold text-gray-800">
            Final: {away} {result.away_score} – {home} {result.home_score}
          </p>
          {result.winner === null ? (
            <span className="text-xs font-bold text-gray-700">Tie</span>
          ) : result.winner === game.predicted_winner ? (
            <span className="text-xs font-bold text-green-700">✓ Correct pick</span>
          ) : (
            <span className="text-xs font-bold text-red-700">✗ Wrong pick</span>
          )}
        </div>
      )}

      <ul className="space-y-1">
        {game.key_factors.map((factor, i) => (
          <li key={i} className="text-sm text-gray-700 flex gap-1">
            <span aria-hidden="true" className="text-gray-400">•</span> {factor}
          </li>
        ))}
      </ul>

      {game.market && (
        <MarketPanel market={game.market} home={home} away={away} isOutlier={game.is_outlier} />
      )}

      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-nrl-blue rounded"
      >
        {expanded ? "Hide reasoning" : "Show reasoning"}
      </button>
      {expanded && (
        <p className="text-sm text-gray-700 leading-relaxed border-t pt-3">{game.reasoning}</p>
      )}
    </article>
  );
}
