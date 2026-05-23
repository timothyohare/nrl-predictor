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
        <div className="flex justify-center gap-4 pt-2 flex-wrap">
          <Link
            href={`/predictions/${round}`}
            className="bg-nrl-blue text-white px-6 py-3 rounded-md font-display tracking-wider border-2 border-nrl-blue shadow-[4px_4px_0_0_#003087] hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-[2px_2px_0_0_#003087] transition-all"
          >
            ROUND {round} →
          </Link>
          <Link
            href="/accuracy"
            className="bg-nrl-paper text-nrl-blue px-6 py-3 rounded-md font-display tracking-wider border-2 border-nrl-blue shadow-[4px_4px_0_0_#003087] hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-[2px_2px_0_0_#003087] transition-all"
          >
            ACCURACY
          </Link>
        </div>
      </section>

      {pickRate !== null && (
        <section className="bg-nrl-cream rounded-2xl border-2 border-nrl-blue shadow-[6px_6px_0_0_#003087] p-8 text-center">
          <p className="font-display text-xs text-nrl-blue tracking-widest mb-2">SEASON CORRECT PICKS</p>
          <p className="font-display text-8xl text-nrl-blue leading-none drop-shadow-[3px_3px_0_#FFD700]">
            {(pickRate * 100).toFixed(0)}<span className="text-nrl-gold">%</span>
          </p>
          <Link href="/accuracy" className="inline-block mt-4 text-sm font-display tracking-wide text-nrl-blue hover:text-nrl-red transition-colors">
            FULL BREAKDOWN →
          </Link>
        </section>
      )}

      <section className="grid md:grid-cols-3 gap-6">
        {[
          { icon: "📋", title: "Team Sheets", body: "Read official 17s the moment they're published Thursday and Friday nights.", stripe: "bg-nrl-blue" },
          { icon: "🧠", title: "AI Reasoning", body: "Claude analyses form, injuries, weather, and head-to-head records to write out its reasoning.", stripe: "bg-nrl-gold" },
          { icon: "📊", title: "Honest Record", body: "Every pick is tracked. We publish our accuracy every round, even when we're wrong.", stripe: "bg-nrl-red" },
        ].map(({ icon, title, body, stripe }) => (
          <div key={title} className="bg-nrl-paper rounded-xl border-2 border-gray-200 overflow-hidden hover:-translate-y-1 hover:shadow-lg transition-all">
            <div className={`h-2 ${stripe}`} />
            <div className="p-6 space-y-3">
              <div className="text-5xl leading-none">{icon}</div>
              <h3 className="font-display tracking-wide text-nrl-blue text-lg">{title}</h3>
              <p className="text-sm text-gray-600 leading-relaxed">{body}</p>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
