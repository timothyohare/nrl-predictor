import { redirect } from "next/navigation";
import { getPredictions, currentRound } from "@/lib/api";
import MatchCard from "@/components/MatchCard";
import RoundSelector from "@/components/RoundSelector";

export const revalidate = 300;

interface Props {
  params: Promise<{ round: string }>;
}

export default async function PredictionsPage({ params }: Props) {
  const { round } = await params;
  const roundNum = parseInt(round, 10);
  if (isNaN(roundNum)) {
    redirect(`/predictions/${currentRound()}`);
  }
  const predictions = await getPredictions(roundNum);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="font-display text-3xl text-nrl-blue tracking-wide">
          {roundNum <= 27 ? `ROUND ${roundNum}` : "FINALS"} <span className="text-nrl-gold">PREDICTIONS</span>
        </h1>
        <RoundSelector current={roundNum} />
      </div>

      {predictions.length === 0 ? (
        <div className="bg-nrl-paper rounded-xl border-2 border-gray-200 p-8 text-center text-gray-400">
          <p className="text-lg">No predictions yet for Round {roundNum}.</p>
          <p className="text-sm mt-1">Check back after team sheets are published Thursday night.</p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {predictions.map((p) => (
            <MatchCard key={p.matchId} prediction={p} />
          ))}
        </div>
      )}
    </div>
  );
}
