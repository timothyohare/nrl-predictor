import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "NFL Predictions — NRL Predictor",
  description:
    "Weekly NFL game predictions from an Elo + Monte Carlo model, graded against results, a home-team baseline and the betting market.",
};

export default function NflLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <nav aria-label="NFL" className="flex gap-4 text-sm border-b-2 border-nrl-blue pb-2">
        <span className="font-display text-nrl-blue tracking-wide">NFL</span>
        <Link href="/nfl" className="text-nrl-blue hover:text-nrl-red transition-colors">Predictions</Link>
        <Link href="/nfl/accuracy" className="text-nrl-blue hover:text-nrl-red transition-colors">Accuracy</Link>
      </nav>
      {children}
      <footer className="border-t pt-3 text-xs text-gray-600">
        NFL schedule and results data:{" "}
        <a href="https://github.com/nflverse/nfldata" className="underline hover:text-nrl-blue">
          nflverse
        </a>
        . Betting lines are shown for comparison only and never feed the model.
      </footer>
    </div>
  );
}
