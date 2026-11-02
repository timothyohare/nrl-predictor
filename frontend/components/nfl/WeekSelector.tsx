"use client";

import { useRouter } from "next/navigation";
import type { NflWeekOption } from "@/lib/nfl/api";

/** Week picker for one season. Labels come from the API (`/nfl/weeks`) verbatim —
 *  the playoff week number moved in 2021, so the selector never maps numbers itself. */
export default function WeekSelector({ season, current, weeks }: {
  season: number;
  current: number;
  weeks: NflWeekOption[];
}) {
  const router = useRouter();

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <label className="text-sm text-gray-600" htmlFor="nfl-week-select">Week:</label>
      <select
        id="nfl-week-select"
        value={current}
        onChange={(e) => router.push(`/nfl/predictions/${season}/${e.target.value}`)}
        className="border rounded px-2 py-1 text-sm bg-white"
      >
        {weeks.map(({ week, label }) => (
          <option key={week} value={week}>{label}</option>
        ))}
      </select>
    </div>
  );
}
