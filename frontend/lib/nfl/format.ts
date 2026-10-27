// Display helpers for NFL predictions.

const SYDNEY = new Intl.DateTimeFormat("en-AU", {
  timeZone: "Australia/Sydney",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZoneName: "short",
});

/** Kickoff in Sydney time, e.g. "Tue 3 Nov, 5:00 am AEDT" (AEST/AEDT follows the date). */
export function formatKickoff(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const part: Record<string, string> = {};
  for (const { type, value } of SYDNEY.formatToParts(date)) part[type] = value;
  return `${part.weekday} ${part.day} ${part.month}, ${part.hour}:${part.minute} ` +
    `${part.dayPeriod.toLowerCase()} ${part.timeZoneName}`;
}

interface MarginFields {
  predicted_margin: number;
  margin_low?: number;
  margin_high?: number;
}

/** The margin band as plain integers ("3–10"); NFL margins are never snapped to even
 *  numbers. Falls back to the point margin when there is no usable band. */
export function marginText({ predicted_margin, margin_low, margin_high }: MarginFields): string {
  if (margin_low != null && margin_high != null && margin_high > margin_low) {
    return `${margin_low}–${margin_high}`;
  }
  return String(predicted_margin);
}

interface ProbabilityFields {
  predicted_winner: string;
  home_team: string;
  home_win_probability: number;
}

/** Win probability of the picked side. */
export function winnerProbability(p: ProbabilityFields): number {
  return p.predicted_winner === p.home_team ? p.home_win_probability : 1 - p.home_win_probability;
}
