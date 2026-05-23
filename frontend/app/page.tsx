import Link from "next/link";
import { getAccuracy, currentRound } from "@/lib/api";

export const revalidate = 300;

export default async function HomePage() {
  let pickRate: number | null = null;
  try {
    const accuracy = await getAccuracy();
    const seasonPickRate = accuracy.season.find((m) => m.metricName === "pick_rate");
    if (seasonPickRate) pickRate = seasonPickRate.value;
  } catch {
    // accuracy dashboard is non-critical for landing page
  }

  const round = currentRound();

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden bg-nrl-cream bg-footy-pattern rounded-2xl border-2 border-nrl-blue text-center space-y-5 py-12 px-6">
        <h1 className="font-display text-5xl sm:text-6xl text-nrl-blue leading-tight relative">
          NRL <span className="text-nrl-gold drop-shadow-[2px_2px_0_#003087]">PREDICTOR</span>
        </h1>
        <p className="text-lg text-gray-600 max-w-2xl mx-auto">
          AI-powered predictions for every NRL match. Updated automatically when team sheets drop.
          Transparent reasoning — read exactly why we picked the winner.
        </p>
        <div className="flex justify-center gap-4 pt-2">
          <Link
            href={`/predictions/${round}`}
            className="bg-nrl-blue text-white px-6 py-3 rounded-lg font-bold hover:bg-blue-900 transition-colors"
          >
            Round {round} Predictions
          </Link>
          <Link
            href="/accuracy"
            className="border-2 border-nrl-blue text-nrl-blue px-6 py-3 rounded-lg font-bold hover:bg-blue-50 transition-colors"
          >
            Accuracy Record
          </Link>
        </div>
      </section>

      {pickRate !== null && (
        <section className="bg-white rounded-xl shadow-sm border p-6 text-center">
          <p className="text-sm text-gray-500 uppercase tracking-wide mb-1">Season-to-date correct picks</p>
          <p className="font-display text-7xl text-nrl-blue leading-none">{(pickRate * 100).toFixed(0)}%</p>
          <Link href="/accuracy" className="text-sm text-blue-600 hover:underline mt-2 block">
            Full accuracy breakdown →
          </Link>
        </section>
      )}

      <section className="grid md:grid-cols-3 gap-6">
        {[
          { icon: "📋", title: "Team Sheets", body: "Read official 17s the moment they're published Thursday and Friday nights.", stripe: "bg-nrl-blue" },
          { icon: "🧠", title: "AI Reasoning", body: "Claude analyses form, injuries, weather, and head-to-head records to write out its reasoning.", stripe: "bg-nrl-gold" },
          { icon: "📊", title: "Honest Record", body: "Every pick is tracked. We publish our accuracy every round, even when we're wrong.", stripe: "bg-nrl-red" },
        ].map(({ icon, title, body, stripe }) => (
          <div key={title} className="bg-nrl-paper rounded-xl border-2 border-gray-200 overflow-hidden">
            <div className={`h-1.5 ${stripe}`} />
            <div className="p-6 space-y-2">
              <div className="text-3xl">{icon}</div>
              <h3 className="font-display tracking-wide text-gray-800">{title}</h3>
              <p className="text-sm text-gray-600">{body}</p>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
