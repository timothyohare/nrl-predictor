export interface Retrospective {
  verdict: string;
  hit_factors: string[];
  missed_factors: string[];
  what_actually_happened: string;
  lesson: string;
  generated_at: string;
}

export interface MatchResult {
  winner: string;
  winner_name?: string;
  homeTeam: string;
  homeTeam_name?: string;
  awayTeam: string;
  awayTeam_name?: string;
  homeScore: number;
  awayScore: number;
  margin: number;
}

export interface Odds {
  market_favourite: string;
  market_margin: number;
  home_odds: number;
  away_odds: number;
  implied_home_prob: number;
  implied_away_prob: number;
}

export interface Prediction {
  matchId: string;
  predicted_winner: string;
  predicted_winner_name?: string;
  predicted_margin: number;
  confidence: "LOW" | "MEDIUM" | "HIGH";
  key_factors: string[];
  reasoning: string;
  data_freshness: string;
  model_used: string;
  generated_at: string;
  staleness_flag: boolean;
  status: string;
  homeTeam?: string;
  awayTeam?: string;
  prompt_version?: string;
  generation?: number;
  retrospective?: Retrospective;
  result?: MatchResult;
  odds?: Odds;
  is_outlier?: boolean;
}

export interface AccuracyData {
  season: MetricRecord[];
  rounds: MetricRecord[];
}

export interface MetricRecord {
  period: string;
  metricName: string;
  value: number;
  correct_picks?: number;
  total?: number;
}

export interface VariantResult {
  variantId: string;
  pick_rate: number;
  correct_picks: number;
  total_picks: number;
  avg_margin_error: number;
  brier_score: number;
  rounds_active: number;
}

export interface TournamentLeaderboard {
  season: number;
  leaderboard: VariantResult[];
}

const API_BASE = process.env.API_GATEWAY_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "";

/**
 * Split a matchId into its [home, away] team slugs.
 *
 * matchIds may be either the old unqualified format ("panthers-v-broncos")
 * or the round-qualified format ("round-12-panthers-v-broncos"); the
 * `round-<N>-` prefix is stripped when present. Unknown / malformed ids
 * degrade to empty strings rather than throwing.
 */
export function splitMatchId(matchId: string): [string, string] {
  const cleaned = matchId.replace(/^round-\d+-/, "");
  const [home, away] = cleaned.split("-v-");
  return [home ?? "", away ?? ""];
}

export async function getPredictions(round: number): Promise<Prediction[]> {
  const res = await fetch(`${API_BASE}/predictions/${round}`, { next: { revalidate: 300 } });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`Failed to fetch predictions: ${res.status}`);
  return res.json();
}

export async function getAccuracy(): Promise<AccuracyData> {
  const res = await fetch(`${API_BASE}/accuracy`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch accuracy: ${res.status}`);
  return res.json();
}

export async function getTournamentLeaderboard(season?: number): Promise<TournamentLeaderboard | null> {
  const qs = season ? `?season=${season}` : "";
  const res = await fetch(`${API_BASE}/tournament/leaderboard${qs}`, { next: { revalidate: 3600 } });
  if (!res.ok) return null;
  return res.json();
}

export function currentRound(): number {
  // Derive from current date — NRL season starts ~March, round 1 week 1
  const start = new Date("2026-03-05");
  const now = new Date();
  const weeks = Math.floor((now.getTime() - start.getTime()) / (7 * 24 * 60 * 60 * 1000));
  return Math.max(1, Math.min(27, weeks + 1));
}
