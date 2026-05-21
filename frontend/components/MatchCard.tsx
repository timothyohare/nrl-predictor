"use client";

import { useState } from "react";
import type { Prediction, Retrospective } from "@/lib/api";

const CONFIDENCE_STYLES: Record<string, string> = {
  HIGH: "bg-green-100 text-green-800",
  MEDIUM: "bg-yellow-100 text-yellow-800",
  LOW: "bg-red-100 text-red-800",
};

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
  const matchSlug = prediction.matchId;
  const [homeSlug, awaySlug] = matchSlug.split("-v-");

  const homeTeam = prediction.homeTeam || homeSlug?.replace(/-/g, " ") || "Home";
  const awayTeam = prediction.awayTeam || awaySlug?.replace(/-/g, " ") || "Away";

  if (prediction.status === "FAILED") {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex justify-between items-start">
          <h3 className="font-semibold text-gray-700 capitalize">{homeTeam} vs {awayTeam}</h3>
        </div>
        <p className="text-sm text-gray-400 mt-2">Prediction unavailable for this match.</p>
      </div>
    );
  }

  return (
    <div className={`bg-white rounded-xl border p-5 space-y-3 ${prediction.staleness_flag ? "border-yellow-300" : "border-gray-200"}`}>
      {prediction.staleness_flag && (
        <div className="text-xs bg-yellow-50 text-yellow-700 rounded px-2 py-1 inline-block">
          Prediction may be stale — budget limit reached
        </div>
      )}

      <div className="flex justify-between items-start gap-2">
        <h3 className="font-semibold text-gray-700 capitalize text-sm">
          {homeTeam} <span className="text-gray-400">vs</span> {awayTeam}
        </h3>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${CONFIDENCE_STYLES[prediction.confidence]}`}>
          {prediction.confidence}
        </span>
      </div>

      <div>
        <p className="text-xl font-bold text-nrl-blue">{prediction.predicted_winner}</p>
        {prediction.predicted_margin > 0 && (
          <p className="text-sm text-gray-500">by {prediction.predicted_margin} pts</p>
        )}
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

      <p className="text-xs text-gray-400">{staleness(prediction.generated_at)}</p>
    </div>
  );
}
