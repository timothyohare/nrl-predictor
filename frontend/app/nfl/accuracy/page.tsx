import { getNflAccuracy, type NflAccuracy, type NflSummary } from "@/lib/nfl/api";
import NflUnavailable from "@/components/nfl/NflUnavailable";

// ISR: regenerate at most hourly (lib/nfl/api.ts NFL_REVALIDATE_SECONDS).
export const revalidate = 3600;

const DASH = "—";
const pct = (v: number | null) => (v == null ? DASH : `${(v * 100).toFixed(1)}%`);
const brier = (v: number | null) => (v == null ? DASH : v.toFixed(3));
const points = (v: number | null) => (v == null ? DASH : v.toFixed(1));

export default async function NflAccuracyPage() {
  let data: NflAccuracy;
  try {
    data = await getNflAccuracy();
  } catch {
    return <NflUnavailable />;
  }

  const rows: [string, NflSummary][] = [
    ["Model", data],
    ["Always pick the home team", data.baselines.home],
    ["Betting market (comparison only)", data.baselines.market],
  ];

  return (
    <div className="space-y-8">
      <h1 className="font-display text-3xl text-nrl-blue tracking-wide">
        {data.season} NFL <span className="text-nrl-gold drop-shadow-[1px_1px_0_#003087]">ACCURACY</span>
      </h1>

      {data.n === 0 ? (
        <div className="bg-nrl-paper rounded-xl border-2 border-gray-200 p-8 text-center text-gray-700">
          No graded NFL games yet for {data.season}.
        </div>
      ) : (
        <>
          {data.n_backfilled > 0 && (
            <p role="note" className="text-sm text-gray-700 bg-nrl-cream border-2 border-nrl-gold rounded-lg px-3 py-2">
              {data.n_backfilled} of {data.n} graded games are backtest predictions, generated after the
              fact from pre-week ratings rather than published before kickoff.
            </p>
          )}

          <section className="bg-white rounded-xl border p-6 space-y-3 overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="text-left font-semibold text-gray-800 pb-2">Model vs baselines</caption>
              <thead>
                <tr className="text-left text-gray-600 border-b">
                  <th scope="col" className="py-1.5 pr-3">Predictor</th>
                  <th scope="col" className="py-1.5 pr-3">Correct picks</th>
                  <th scope="col" className="py-1.5 pr-3">Brier</th>
                  <th scope="col" className="py-1.5">Margin error (pts)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, s]) => (
                  <tr key={label} className="border-b last:border-0">
                    <th scope="row" className="py-1.5 pr-3 text-left font-medium text-gray-800">{label}</th>
                    <td className="py-1.5 pr-3">{pct(s.accuracy)}</td>
                    <td className="py-1.5 pr-3">{brier(s.brier)}</td>
                    <td className="py-1.5">{points(s.margin_mae)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-600">
              {data.n} graded games. Ties count as half in Brier and are left out of correct picks.
              The market line is shown for comparison only and is never a model input.
            </p>
          </section>

          <section className="bg-white rounded-xl border p-6 space-y-3">
            <table className="w-full text-sm">
              <caption className="text-left font-semibold text-gray-800 pb-2">Correct picks by confidence</caption>
              <thead>
                <tr className="text-left text-gray-600 border-b">
                  <th scope="col" className="py-1.5 pr-3">Confidence</th>
                  <th scope="col" className="py-1.5 pr-3">Games</th>
                  <th scope="col" className="py-1.5">Correct picks</th>
                </tr>
              </thead>
              <tbody>
                {(["HIGH", "MEDIUM", "LOW"] as const).map((level) => (
                  <tr key={level} className="border-b last:border-0">
                    <th scope="row" className="py-1.5 pr-3 text-left font-medium text-gray-800">{level}</th>
                    <td className="py-1.5 pr-3">{data.by_confidence[level].n}</td>
                    <td className="py-1.5">{pct(data.by_confidence[level].accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
