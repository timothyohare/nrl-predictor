"use client";

import { useState } from "react";
import type { Prediction, Retrospective } from "@/lib/api";
import { teamColor } from "@/lib/teamColors";

const CONFIDENCE_STYLES: Record<string, string> = {
  HIGH: "bg-green-600 text-white",
  MEDIUM: "bg-yellow-400 text-yellow-900",
  LOW: "bg-red-500 text-white",
};

// matchIds may be either old-format ("panthers-v-broncos") or
// new round-qualified format ("round-12-panthers-v-broncos")
function splitMatchId(matchId: string): [string, string] {
  const cleaned = matchId.replace(/^round-\d+-/, "");
  const [home, away] = cleaned.split("-v-");
  return [home ?? "", away ?? ""];
}

function staleness(generated_at: string): string {
  const diffMs = Date.now() - new Date(generated_at).getTime();
  const hours = Math.floor(diffMs / 3600000);
  if (hours < 1) return "Updated just now";
  if (hours < 24) return `Updated ${hours}h ago`;
  return `Updated ${Math.floor(hours / 24)}d ago`;
}

function RetrospectivePanel({ retro }: { retro: Retrospective }) {
  return (
    <div className="border-t pt-3 space-y-2 mt-2">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">What actually happened</p>
      <p className="text-sm text-gray-700">{retro.verdict}</p>
      {retro.hit_factors.length > 0 && (
        <div>
          <p className="text-xs text-green-700 font-medium mb-0.5">Got right</p>
          <ul className="space-y-0.5">
            {retro.hit_factors.map((f, i) => (
              <li key={i} className="text-xs text-gray-600 flex gap-1">
                <span className="text-green-400">✓</span> {f}
              </li>
            ))}
          </ul>
        </div>
      )}
      {retro.missed_factors.length > 0 && (
        <div>
          <p className="text-xs text-red-700 font-medium mb-0.5">Missed</p>
          <ul className="space-y-0.5">
            {retro.missed_factors.map((f, i) => (
              <li key={i} className="text-xs text-gray-600 flex gap-1">
                <span className="text-red-400">✗</span> {f}
              </li>
            ))}
          </ul>
        </div>
      )}
      {retro.what_actually_happened && (
        <p className="text-xs text-gray-500 leading-relaxed border-t pt-2">{retro.what_actually_happened}</p>
      )}
      {retro.lesson && (
        <p className="text-xs text-blue-700 italic">Lesson: {retro.lesson}</p>
      )}
    </div>
  );
}

export default function MatchCard({ prediction }: { prediction: Prediction }) {
  const [expanded, setExpanded] = useState(false);
  const [retroExpanded, setRetroExpanded] = useState(false);
  const [homeSlug, awaySlug] = splitMatchId(prediction.matchId);

  const homeTeam = prediction.homeTeam || homeSlug?.replace(/-/g, " ") || "Home";
  const awayTeam = prediction.awayTeam || awaySlug?.replace(/-/g, " ") || "Away";
  const homeColor = teamColor(homeSlug);
  const awayColor = teamColor(awaySlug);
  const winnerSlug = prediction.predicted_winner?.toLowerCase().replace(/\s+/g, "-");
  const winnerColor = teamColor(winnerSlug || homeSlug);

  if (prediction.status === "FAILED") {
    return (
      <div className="bg-nrl-paper rounded-xl border border-gray-200 p-5">
        <div className="flex justify-between items-start">
          <h3 className="font-semibold text-gray-700 capitalize">{homeTeam} vs {awayTeam}</h3>
        </div>
        <p className="text-sm text-gray-400 mt-2">Prediction unavailable for this match.</p>
      </div>
    );
  }

  return (
    <div
      className={`bg-nrl-paper rounded-xl border-2 p-5 space-y-3 border-l-[6px] ${prediction.staleness_flag ? "border-yellow-300" : "border-gray-200"}`}
      style={{ borderLeftColor: winnerColor }}
    >
      {prediction.staleness_flag && (
        <div className="text-xs bg-yellow-50 text-yellow-700 rounded px-2 py-1 inline-block">
          Prediction may be stale — budget limit reached
        </div>
      )}

      <div className="flex justify-between items-start gap-2">
        <h3 className="font-semibold text-gray-700 capitalize text-sm flex items-center gap-1.5 flex-wrap">
          <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: homeColor }} />
          {homeTeam}
          <span className="text-gray-400 font-normal">vs</span>
          <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: awayColor }} />
          {awayTeam}
        </h3>
        <span className={`font-display text-[10px] tracking-wider px-2 py-1 rounded ${CONFIDENCE_STYLES[prediction.confidence]} shrink-0`}>
          {prediction.confidence}
        </span>
      </div>

      <div className="space-y-1.5">
        <p className="font-display text-2xl leading-none" style={{ color: winnerColor }}>
          {prediction.predicted_winner}
          {prediction.predicted_margin > 0 && (
            <span className="text-gray-700"> BY {prediction.predicted_margin}</span>
          )}
        </p>
        {prediction.result && (() => {
          const r = prediction.result;
          const actualWinnerColor = teamColor(r.winner.toLowerCase().replace(/\s+/g, "-"));
          const winnerCorrect = r.winner === prediction.predicted_winner;
          const marginError = Math.abs(prediction.predicted_margin - r.margin);
          const marginWithin6 = winnerCorrect && marginError <= 6;
          return (
            <div className="flex items-baseline gap-2 flex-wrap">
              <p className="font-display text-xl leading-none" style={{ color: actualWinnerColor }}>
                {r.homeTeam.toUpperCase()} <span className="text-gray-800">{r.homeScore}</span>
                <span className="text-gray-400 mx-1">—</span>
                {r.awayTeam.toUpperCase()} <span className="text-gray-800">{r.awayScore}</span>
              </p>
              <span
                title={winnerCorrect ? "Correct winner" : "Wrong winner"}
                className={`text-xs font-bold ${winnerCorrect ? "text-green-600" : "text-red-500"}`}
              >
                {winnerCorrect ? "✓ winner" : "✗ winner"}
              </span>
              {winnerCorrect && (
                <span
                  title={marginWithin6 ? "Within 6 pts" : `Off by ${marginError} pts`}
                  className={`text-xs font-bold ${marginWithin6 ? "text-green-600" : "text-gray-400"}`}
                >
                  {marginWithin6 ? "✓ margin" : `✗ margin (±${marginError})`}
                </span>
              )}
            </div>
          );
        })()}
      </div>

      <ul className="space-y-1">
        {prediction.key_factors.map((f, i) => (
          <li key={i} className="text-sm text-gray-600 flex gap-1">
            <span className="text-gray-300">•</span> {f}
          </li>
        ))}
      </ul>

      <div className="flex gap-3">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-blue-600 hover:underline"
        >
          {expanded ? "Hide reasoning" : "Show reasoning"}
        </button>
        {prediction.retrospective && (
          <button
            onClick={() => setRetroExpanded(!retroExpanded)}
            className="text-xs text-purple-600 hover:underline"
          >
            {retroExpanded ? "Hide post-match" : "Post-match analysis"}
          </button>
        )}
      </div>

      {expanded && (
        <p className="text-sm text-gray-600 leading-relaxed border-t pt-3">{prediction.reasoning}</p>
      )}

      {retroExpanded && prediction.retrospective && (
        <RetrospectivePanel retro={prediction.retrospective} />
      )}

      <p className="text-xs text-gray-400">
        {staleness(prediction.generated_at)}
        {prediction.generation && prediction.generation > 1 && (
          <span className="ml-1.5 text-blue-400">(update #{prediction.generation})</span>
        )}
      </p>
    </div>
  );
}
