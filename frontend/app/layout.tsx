import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NRL Predictor — AI-Powered Match Predictions",
  description:
    "AI-powered NRL match predictions updated from official team sheets. Transparent reasoning, published accuracy record.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">
        <header className="bg-nrl-blue text-white px-4 py-3 flex items-center gap-6">
          <a href="/" className="font-bold text-lg tracking-tight">NRL Predictor</a>
          <nav className="flex gap-4 text-sm">
            <a href="/predictions/current" className="hover:text-yellow-300 transition-colors">Predictions</a>
            <a href="/accuracy" className="hover:text-yellow-300 transition-colors">Accuracy</a>
            <a href="/how-it-works" className="hover:text-yellow-300 transition-colors">How it works</a>
          </nav>
        </header>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
        <footer className="border-t text-center text-xs text-gray-400 py-4">
          Predictions are for entertainment. Always do your own research.
        </footer>
      </body>
    </html>
  );
}
