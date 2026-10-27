// RED stub — implemented in the green commit.
export interface NflResult { home_score: number; away_score: number; winner: string | null; winner_name: string | null; margin: number }
export interface NflMarket { spread_favourite: string | null; spread_line: number | null; implied_home_prob: number | null }
export interface NflPrediction {
  matchId: string; season: number; week: number; stage: string; label: string;
  home_team: string; home_team_name: string; away_team: string; away_team_name: string;
  neutral: boolean; kickoff_utc: string | null; predicted_winner: string; predicted_winner_name?: string;
  predicted_margin: number; margin_low?: number; margin_high?: number; home_win_probability: number;
  confidence: "LOW" | "MEDIUM" | "HIGH"; key_factors: string[]; reasoning: string; model_used: string;
  generation: number; generatedAt: string; backfilled: boolean;
  result?: NflResult; market?: NflMarket; is_outlier?: boolean;
}
export interface NflWeek { season: number; week: number; stage: string; label: string }
export interface NflWeekOption { week: number; label: string }
export type NflWeekView =
  | { status: "ok"; season: number; week: number; label: string; predictions: NflPrediction[]; weeks: NflWeekOption[] }
  | { status: "unavailable" };
export const NFL_REVALIDATE_SECONDS = 0;
export class NflUnavailableError extends Error {}
export function nflApiBase(): string { return "x"; }
export async function getNflPredictions(_s: number, _w: number): Promise<NflPrediction[]> { throw new Error("not implemented"); }
export async function getNflCurrentWeek(): Promise<NflWeek> { throw new Error("not implemented"); }
export async function getNflWeeks(_s: number): Promise<{ week: number; stage: string; label: string }[]> { throw new Error("not implemented"); }
export async function getNflAccuracy(_s?: number): Promise<unknown> { throw new Error("not implemented"); }
export async function loadNflWeek(_s: number, _w: number): Promise<NflWeekView> { throw new Error("not implemented"); }
