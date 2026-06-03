import { getTournamentLeaderboard } from "@/lib/api";
import type { VariantResult } from "@/lib/api";

export const dynamic = "force-dynamic";

const VARIANT_LABELS: Record<string, { label: string; hypothesis: string }> = {
  "baseline": { label: "Baseline (production)", hypothesis: "Control — identical to production prompt" },
  "heavy-home-advantage": { label: "Heavy home (+6pts)", hypothesis: "Home advantage is worth 6 points, not 4" },
  "light-home-advantage": { label: "Light home (+2pts)", hypothesis: "Modern travel has reduced home advantage to 2pts" },
  "form-over-h2h": { label: "Form > H2H", hypothesis: "Recent form is more predictive than historical H2H" },
  "h2h-over-form": { label: "H2H > Form", hypothesis: "H2H records reveal structural mismatches that outlast personnel changes" },
  "high-confidence-strict": { label: "Strict confidence", hypothesis: "Only HIGH confidence when 3+ factors clearly align" },
  "margin-conservative": { label: "Conservative margins", hypothesis: "NRL is high-parity — cap uncertain margins at 6-10pts" },
  "upset-detector": { label: "Upset detector", hypothesis: "Actively seek conditions where underdog can win" },
};

export default async function TournamentPage() {
  const data = await getTournamentLeaderboard();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-nrl-blue">Prompt Tournament</h1>
        <p className="text-sm text-gray-500 mt-1">
          Each round, 8 prompt variants analyse the same matches independently.
          After results come in, the most accurate variant wins.
          After 6 rounds of statistical signal, the best variant gets promoted to production.
        </p>
      </div>

      {!data || data.leaderboard.length === 0 ? (
        <div className="bg-nrl-paper rounded-xl border border-gray-200 p-8 text-center text-gray-500">
          <p className="font-medium">Tournament hasn&apos;t started yet</p>
          <p className="text-sm mt-1">Results will appear here after the first scored round.</p>
        </div>
      ) : (
        <LeaderboardTable leaderboard={data.leaderboard} season={data.season} />
      )}

      <section className="bg-white rounded-xl border p-6 space-y-3">
        <h2 className="font-semibold text-gray-700">What are we testing?</h2>
        <p className="text-xs text-gray-500">
          Each variant tweaks one dimension of the prediction prompt to isolate its effect on accuracy.
        </p>
        <table className="w-full text-sm mt-2">
          <thead>
            <tr className="text-xs text-gray-500 border-b">
              <th className="text-left pb-1 font-medium">Variant</th>
              <th className="text-left pb-1 font-medium hidden sm:table-cell">Hypothesis</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(VARIANT_LABELS).map(([id, { label, hypothesis }]) => (
              <tr key={id} className="border-b last:border-0">
                <td className="py-1.5 font-medium text-gray-700">{label}</td>
                <td className="py-1.5 text-gray-500 hidden sm:table-cell">{hypothesis}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function LeaderboardTable({ leaderboard, season }: { leaderboard: VariantResult[]; season: number }) {
  const baseline = leaderboard.find((v) => v.variantId === "baseline");
  const baselineRate = baseline?.pick_rate ?? 0;

  return (
    <section className="bg-white rounded-xl border p-6 space-y-3">
      <div className="flex justify-between items-baseline">
        <h2 className="font-semibold text-gray-700">Season {season} Leaderboard</h2>
        <span className="text-xs text-gray-400">ranked by pick rate</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b">
              <th className="text-left pb-2 font-medium">Rank</th>
              <th className="text-left pb-2 font-medium">Variant</th>
              <th className="text-right pb-2 font-medium">Picks</th>
              <th className="text-right pb-2 font-medium">Pick rate</th>
              <th className="text-right pb-2 font-medium hidden sm:table-cell">vs baseline</th>
              <th className="text-right pb-2 font-medium hidden sm:table-cell">Margin err</th>
              <th className="text-right pb-2 font-medium hidden md:table-cell">Brier</th>
              <th className="text-right pb-2 font-medium hidden md:table-cell">Rounds</th>
            </tr>
          </thead>
          <tbody>
            {leaderboard.map((v, i) => {
              const meta = VARIANT_LABELS[v.variantId];
              const diff = v.pick_rate - baselineRate;
              const isBaseline = v.variantId === "baseline";
              const isLeader = i === 0 && !isBaseline;
              return (
                <tr key={v.variantId} className={`border-b last:border-0 ${isLeader ? "bg-green-50" : ""}`}>
                  <td className="py-2 text-gray-400 text-xs w-6">{i + 1}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-1.5">
                      {isBaseline && (
                        <span className="text-[10px] bg-nrl-blue text-white px-1.5 py-0.5 rounded font-bold">PROD</span>
                      )}
                      {isLeader && (
                        <span className="text-[10px] bg-green-600 text-white px-1.5 py-0.5 rounded font-bold">LEADING</span>
                      )}
                      <span className="font-medium text-gray-800">{meta?.label ?? v.variantId}</span>
                    </div>
                  </td>
                  <td className="py-2 text-right text-gray-500 text-xs">
                    {v.correct_picks}/{v.total_picks}
                  </td>
                  <td className="py-2 text-right font-semibold text-nrl-blue">
                    {(v.pick_rate * 100).toFixed(1)}%
                  </td>
                  <td className={`py-2 text-right text-xs hidden sm:table-cell ${isBaseline ? "text-gray-400" : diff > 0 ? "text-green-600 font-medium" : diff < 0 ? "text-red-500" : "text-gray-400"}`}>
                    {isBaseline ? "—" : `${diff > 0 ? "+" : ""}${(diff * 100).toFixed(1)}%`}
                  </td>
                  <td className="py-2 text-right text-gray-500 text-xs hidden sm:table-cell">
                    {v.avg_margin_error.toFixed(1)} pts
                  </td>
                  <td className="py-2 text-right text-gray-500 text-xs hidden md:table-cell">
                    {v.brier_score.toFixed(3)}
                  </td>
                  <td className="py-2 text-right text-gray-400 text-xs hidden md:table-cell">
                    {v.rounds_active}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {leaderboard.length > 0 && leaderboard[0].rounds_active < 6 && (
        <p className="text-xs text-gray-400 pt-1">
          Needs 6 rounds of data (~48 matches) for statistical significance. Currently {leaderboard[0].rounds_active} round{leaderboard[0].rounds_active !== 1 ? "s" : ""} active.
        </p>
      )}
    </section>
  );
}
