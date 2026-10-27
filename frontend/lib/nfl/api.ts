// Server-side client for the NFL API (NflPredictorStack's own HttpApi).
//
// The base URL is the server-only NFL_API_BASE_URL (no NEXT_PUBLIC_ prefix: the
// browser never calls the API). Every fetch is ISR-cached for an hour, so page
// renders never hit the API per visitor — the API rate-limits each source IP to
// 20 requests/hour, and server-side every visitor shares the frontend's IPs
// (Phase 4 review N5). The NFL data changes once a day (12:00 UTC orchestrator).

export interface NflResult {
  home_score: number;
  away_score: number;
  /** null on a tie */
  winner: string | null;
  winner_name: string | null;
  margin: number;
}

/** Betting market, for comparison only — never a model input. */
export interface NflMarket {
  /** null on a pick'em or when there is no spread */
  spread_favourite: string | null;
  /** > 0 means the home team is favoured */
  spread_line: number | null;
  implied_home_prob: number | null;
}

export interface NflPrediction {
  matchId: string;
  season: number;
  week: number;
  stage: string;
  label: string;
  home_team: string;
  home_team_name: string;
  away_team: string;
  away_team_name: string;
  neutral: boolean;
  kickoff_utc: string | null;
  predicted_winner: string;
  predicted_winner_name?: string;
  predicted_margin: number;
  margin_low?: number;
  margin_high?: number;
  home_win_probability: number;
  confidence: "LOW" | "MEDIUM" | "HIGH";
  key_factors: string[];
  reasoning: string;
  model_used: string;
  generation: number;
  generatedAt: string;
  /** Walk-forward backtest row written after the fact (user decision Q2). */
  backfilled: boolean;
  result?: NflResult;
  market?: NflMarket;
  is_outlier?: boolean;
}

export interface NflWeek {
  season: number;
  week: number;
  stage: string;
  label: string;
}

export interface NflWeekOption {
  week: number;
  label: string;
}

export interface NflSummary {
  n: number;
  accuracy: number | null;
  brier: number | null;
  margin_mae: number | null;
}

export interface NflAccuracy extends NflSummary {
  season: number;
  n_backfilled: number;
  by_confidence: Record<"HIGH" | "MEDIUM" | "LOW", { n: number; accuracy: number | null }>;
  baselines: {
    home: NflSummary & { p_home: number; margin: number };
    market: NflSummary;
  };
}

export type NflWeekView =
  | {
      status: "ok";
      season: number;
      week: number;
      label: string;
      predictions: NflPrediction[];
      weeks: NflWeekOption[];
    }
  | { status: "unavailable" };

export const NFL_REVALIDATE_SECONDS = 3600;

/** NFL_API_BASE_URL is unset: the NFL section renders its unavailable state. */
export class NflUnavailableError extends Error {}

export function nflApiBase(): string {
  return (process.env.NFL_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
}

async function nflFetch(path: string): Promise<Response> {
  const base = nflApiBase();
  if (!base) throw new NflUnavailableError("NFL_API_BASE_URL is not set");
  return fetch(`${base}${path}`, { next: { revalidate: NFL_REVALIDATE_SECONDS } });
}

async function nflJson<T>(path: string): Promise<T> {
  const res = await nflFetch(path);
  if (!res.ok) throw new Error(`NFL API ${path} failed: ${res.status}`);
  return res.json();
}

export async function getNflPredictions(season: number, week: number): Promise<NflPrediction[]> {
  const res = await nflFetch(`/nfl/predictions/${season}/${week}`);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`NFL API predictions failed: ${res.status}`);
  return res.json();
}

export function getNflCurrentWeek(): Promise<NflWeek> {
  return nflJson<NflWeek>("/nfl/weeks/current");
}

export async function getNflWeeks(season: number): Promise<Omit<NflWeek, "season">[]> {
  const body = await nflJson<{ weeks: Omit<NflWeek, "season">[] }>(`/nfl/weeks?season=${season}`);
  return body.weeks;
}

export function getNflAccuracy(season?: number): Promise<NflAccuracy> {
  return nflJson<NflAccuracy>(season ? `/nfl/accuracy?season=${season}` : "/nfl/accuracy");
}

/** Everything the week page needs. Any failure fetching the predictions makes the
 *  section unavailable rather than throwing; the week list is optional. */
export async function loadNflWeek(season: number, week: number): Promise<NflWeekView> {
  const [predictionsResult, weeksResult] = await Promise.allSettled([
    getNflPredictions(season, week),
    getNflWeeks(season),
  ]);
  if (predictionsResult.status === "rejected") return { status: "unavailable" };
  const predictions = predictionsResult.value;

  const weeks: NflWeekOption[] = weeksResult.status === "fulfilled"
    ? weeksResult.value.map(({ week: w, label }) => ({ week: w, label }))
    : [];
  let label = weeks.find((w) => w.week === week)?.label ?? predictions[0]?.label;
  if (!label) label = `Week ${week}`;
  if (!weeks.some((w) => w.week === week)) {
    weeks.push({ week, label });
    weeks.sort((a, b) => a.week - b.week);
  }
  return { status: "ok", season, week, label, predictions, weeks };
}
