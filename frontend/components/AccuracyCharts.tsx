"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from "recharts";
import type { MetricRecord } from "@/lib/api";

interface Props {
  rounds: MetricRecord[];
}

export default function AccuracyCharts({ rounds }: Props) {
  const pickRateByRound = rounds
    .filter((r) => r.metricName === "pick_rate")
    .map((r) => ({ round: r.period, value: parseFloat((r.value * 100).toFixed(1)) }))
    .sort((a, b) => a.round.localeCompare(b.round));

  const marginByRound = rounds
    .filter((r) => r.metricName === "mean_margin_error")
    .map((r) => ({ round: r.period, value: parseFloat(r.value.toFixed(1)) }))
    .sort((a, b) => a.round.localeCompare(b.round));

  if (pickRateByRound.length === 0) return null;

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border p-6">
        <h2 className="font-semibold text-gray-700 mb-4">Pick Rate by Round (%)</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={pickRateByRound} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <XAxis dataKey="round" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number) => `${v}%`} />
            <ReferenceLine y={50} stroke="#9ca3af" strokeDasharray="4 4" />
            <Bar dataKey="value" radius={[3, 3, 0, 0]}>
              {pickRateByRound.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.value >= 60 ? "#1d4289" : entry.value >= 50 ? "#60a5fa" : "#fca5a5"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {marginByRound.length > 0 && (
        <div className="bg-white rounded-xl border p-6">
          <h2 className="font-semibold text-gray-700 mb-4">Mean Margin Error by Round (pts)</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={marginByRound} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <XAxis dataKey="round" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `${v} pts`} />
              <Bar dataKey="value" fill="#1d4289" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
