import { getAccuracy } from "@/lib/api";
import AccuracyCharts from "@/components/AccuracyCharts";
import type { MetricRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AccuracyPage() {
  let data = null;
  let error = false;
  try {
    data = await getAccuracy();
  } catch {
    error = true;
  }

  const seasonPickRate = data?.season.find((m) => m.metricName === "pick_rate");
  const seasonBrier = data?.season.find((m) => m.metricName === "brier_score");
  const seasonMargin = data?.season.find((m) => m.metricName === "mean_margin_error");

  const confidenceMetrics = data?.season.filter((m) =>
    m.metricName.startsWith("pick_rate_") && m.metricName.endsWith("_confidence")
  ) ?? [];

  const promptVersionMetrics = data?.season.filter((m) =>
    m.metricName.startsWith("pick_rate_prompt_")
  ) ?? [];

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-nrl-blue">Accuracy Record</h1>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600">
          Could not load accuracy data. Please try again later.
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard
              label="Season Pick Rate"
              value={seasonPickRate ? `${(seasonPickRate.value * 100).toFixed(1)}%` : "—"}
              sub={
                seasonPickRate?.correct_picks != null && seasonPickRate?.total != null
                  ? `${seasonPickRate.correct_picks} / ${seasonPickRate.total} correct`
                  : undefined
              }
            />
            <StatCard
              label="Mean Margin Error"
              value={seasonMargin ? `${seasonMargin.value.toFixed(1)} pts` : "—"}
              sub="average points off per game"
            />
            <StatCard
              label="Brier Score"
              value={seasonBrier ? seasonBrier.value.toFixed(3) : "—"}
              sub="lower is better (0 = perfect)"
            />
          </div>

          <AccuracyCharts rounds={data.rounds} />

          {confidenceMetrics.length > 0 && (
            <section className="bg-white rounded-xl border p-6 space-y-3">
              <h2 className="font-semibold text-gray-700">Confidence Calibration</h2>
              <p className="text-xs text-gray-500">Are higher-confidence picks actually more accurate?</p>
              <CalibrationTable
                rows={[
                  { label: "HIGH", metric: confidenceMetrics.find((m) => m.metricName === "pick_rate_high_confidence") },
                  { label: "MEDIUM", metric: confidenceMetrics.find((m) => m.metricName === "pick_rate_medium_confidence") },
                  { label: "LOW", metric: confidenceMetrics.find((m) => m.metricName === "pick_rate_low_confidence") },
                ].filter((r) => r.metric)}
              />
            </section>
          )}

          {promptVersionMetrics.length > 1 && (
            <section className="bg-white rounded-xl border p-6 space-y-3">
              <h2 className="font-semibold text-gray-700">Prompt Version Accuracy</h2>
              <p className="text-xs text-gray-500">Did prompt changes improve prediction quality?</p>
              <CalibrationTable
                rows={promptVersionMetrics.map((m) => ({
                  label: m.metricName.replace("pick_rate_prompt_", "").replace(/_/g, "."),
                  metric: m,
                }))}
              />
            </section>
          )}

          <section className="bg-white rounded-xl border p-6 space-y-3">
            <h2 className="font-semibold text-gray-700">How we measure accuracy</h2>
            <ul className="text-sm text-gray-600 space-y-1.5">
              <li>
                <span className="font-medium">Pick rate</span> — percentage of winners predicted correctly.
              </li>
              <li>
                <span className="font-medium">Mean margin error</span> — average absolute difference between our predicted margin and the actual margin.
              </li>
              <li>
                <span className="font-medium">Brier score</span> — a proper scoring rule that penalises overconfident wrong picks more than low-confidence wrong picks. Score of 0 is perfect; 0.25 is equivalent to random guessing.
              </li>
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border p-6 text-center">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-4xl font-bold text-nrl-blue">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function CalibrationTable({ rows }: { rows: { label: string; metric?: MetricRecord }[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-gray-500 border-b">
          <th className="text-left pb-1 font-medium">Level</th>
          <th className="text-right pb-1 font-medium">Picks</th>
          <th className="text-right pb-1 font-medium">Correct</th>
          <th className="text-right pb-1 font-medium">Pick rate</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ label, metric }) => (
          <tr key={label} className="border-b last:border-0">
            <td className="py-1.5 font-medium text-gray-700">{label}</td>
            <td className="py-1.5 text-right text-gray-500">{metric?.total ?? "—"}</td>
            <td className="py-1.5 text-right text-gray-500">{metric?.correct_picks ?? "—"}</td>
            <td className="py-1.5 text-right font-semibold text-nrl-blue">
              {metric ? `${(metric.value * 100).toFixed(1)}%` : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
