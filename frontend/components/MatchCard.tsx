"use client";

import { useState } from "react";
import type { Prediction } from "@/lib/api";

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

export default function MatchCard({ prediction }: { prediction: Prediction }) {
  const [expanded, setExpanded] = useState(false);
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

      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-600 hover:underline"
      >
        {expanded ? "Hide reasoning" : "Show reasoning"}
      </button>

      {expanded && (
        <p className="text-sm text-gray-600 leading-relaxed border-t pt-3">{prediction.reasoning}</p>
      )}

      <p className="text-xs text-gray-400">{staleness(prediction.generated_at)}</p>
    </div>
  );
}
