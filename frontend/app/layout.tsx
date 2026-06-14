import type { Metadata } from "next";
import { Bungee, Nunito } from "next/font/google";
import Link from "next/link";
import Logo from "@/components/Logo";
import "./globals.css";

const bungee = Bungee({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
  display: "swap",
});

const nunito = Nunito({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NRL Predictor — AI-Powered Match Predictions",
  description:
    "AI-powered NRL match predictions updated from official team sheets. Transparent reasoning, published accuracy record.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${bungee.variable} ${nunito.variable}`}>
      <body className="bg-gray-50 text-gray-900 min-h-screen font-sans">
        <header className="bg-nrl-blue text-white px-4 py-3 flex items-center gap-6 border-b-4 border-nrl-gold">
          <Link href="/" className="hover:opacity-90 transition-opacity">
            <Logo />
          </Link>
          <nav className="flex gap-4 text-sm ml-auto sm:ml-0">
            <Link href="/predictions/current" className="hover:text-nrl-gold transition-colors">Predictions</Link>
            <Link href="/accuracy" className="hover:text-nrl-gold transition-colors">Accuracy</Link>
            <Link href="/tournament" className="hover:text-nrl-gold transition-colors">Tournament</Link>
            <Link href="/how-it-works" className="hover:text-nrl-gold transition-colors">How it works</Link>
          </nav>
        </header>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
        <footer className="border-t text-center text-xs text-gray-400 py-4 space-y-1">
          <p>Predictions are for entertainment. Always do your own research.</p>
          <p className="text-gray-300">build {process.env.GIT_SHA}</p>
        </footer>
      </body>
    </html>
  );
}
