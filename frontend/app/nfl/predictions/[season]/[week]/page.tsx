import { notFound } from "next/navigation";
import { loadNflWeek } from "@/lib/nfl/api";
import NflGameCard from "@/components/nfl/NflGameCard";
import NflUnavailable from "@/components/nfl/NflUnavailable";
import WeekSelector from "@/components/nfl/WeekSelector";

// ISR: regenerate at most hourly (lib/nfl/api.ts NFL_REVALIDATE_SECONDS).
export const revalidate = 3600;

interface Props {
  params: Promise<{ season: string; week: string }>;
}

// Same bounds as the API (nfl/api/http.py), so a bad URL never costs an API call.
function parseParam(value: string, min: number, max: number): number | null {
  if (!/^[0-9]{1,4}$/.test(value)) return null;
  const n = Number(value);
  return n >= min && n <= max ? n : null;
}

export default async function NflWeekPage({ params }: Props) {
  const { season: seasonParam, week: weekParam } = await params;
  const season = parseParam(seasonParam, 1999, 2100);
  const week = parseParam(weekParam, 1, 25);
  if (season === null || week === null) notFound();

  const view = await loadNflWeek(season, week);
  if (view.status === "unavailable") return <NflUnavailable />;

  const anyBackfilled = view.predictions.some((p) => p.backfilled);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="font-display text-3xl text-nrl-blue tracking-wide">
          {season} {view.label} <span className="text-nrl-gold drop-shadow-[1px_1px_0_#003087]">NFL</span>
        </h1>
        <WeekSelector season={season} current={week} weeks={view.weeks} />
      </div>

      {anyBackfilled && (
        <p role="note" className="text-sm text-gray-700 bg-nrl-cream border-2 border-nrl-gold rounded-lg px-3 py-2">
          Games marked <span className="font-semibold">Backtest</span> were predicted after the fact by the
          walk-forward backtest, from ratings as they stood before that week. They are not live picks.
        </p>
      )}

      {view.predictions.length === 0 ? (
        <div className="bg-nrl-paper rounded-xl border-2 border-gray-200 p-8 text-center text-gray-700">
          <p className="text-lg">No NFL predictions yet for {view.label}.</p>
          <p className="text-sm mt-1">Predictions are published daily once the previous week is final.</p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {view.predictions.map((game) => (
            <NflGameCard key={game.matchId} game={game} />
          ))}
        </div>
      )}
    </div>
  );
}
