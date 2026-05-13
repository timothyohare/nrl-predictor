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
      <section className="text-center space-y-4 py-8">
        <h1 className="text-4xl font-bold text-nrl-blue">NRL Predictor</h1>
        <p className="text-lg text-gray-600 max-w-2xl mx-auto">
          AI-powered predictions for every NRL match. Updated automatically when team sheets drop.
          Transparent reasoning — read exactly why we picked the winner.
        </p>
        <div className="flex justify-center gap-4 pt-2">
          <Link
            href={`/predictions/${round}`}
            className="bg-nrl-blue text-white px-6 py-3 rounded-lg font-semibold hover:bg-blue-900 transition-colors"
          >
            Round {round} Predictions
          </Link>
          <Link
            href="/accuracy"
            className="border border-nrl-blue text-nrl-blue px-6 py-3 rounded-lg font-semibold hover:bg-blue-50 transition-colors"
          >
            Accuracy Record
          </Link>
        </div>
      </section>

      {pickRate !== null && (
        <section className="bg-white rounded-xl shadow-sm border p-6 text-center">
          <p className="text-sm text-gray-500 uppercase tracking-wide mb-1">Season-to-date correct picks</p>
          <p className="text-5xl font-bold text-nrl-blue">{(pickRate * 100).toFixed(0)}%</p>
          <Link href="/accuracy" className="text-sm text-blue-600 hover:underline mt-2 block">
            Full accuracy breakdown →
          </Link>
        </section>
      )}

      <section className="grid md:grid-cols-3 gap-6">
        {[
          { icon: "📋", title: "Team Sheets", body: "Read official 17s the moment they're published Thursday and Friday nights." },
          { icon: "🧠", title: "AI Reasoning", body: "Claude analyses form, injuries, weather, and head-to-head records to write out its reasoning." },
          { icon: "📊", title: "Honest Record", body: "Every pick is tracked. We publish our accuracy every round, even when we're wrong." },
        ].map(({ icon, title, body }) => (
          <div key={title} className="bg-white rounded-xl border p-6 space-y-2">
            <div className="text-3xl">{icon}</div>
            <h3 className="font-semibold text-gray-800">{title}</h3>
            <p className="text-sm text-gray-600">{body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
