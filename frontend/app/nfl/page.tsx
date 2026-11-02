import { redirect } from "next/navigation";
import { getNflCurrentWeek, NflUnavailableError, type NflWeek } from "@/lib/nfl/api";
import NflUnavailable from "@/components/nfl/NflUnavailable";

// ISR: regenerate at most hourly (lib/nfl/api.ts NFL_REVALIDATE_SECONDS).
export const revalidate = 3600;

export default async function NflHomePage() {
  let current: NflWeek;
  try {
    current = await getNflCurrentWeek();
  } catch (err) {
    // Only "not configured" renders unavailable; anything else throws so ISR
    // keeps serving the last good page (Phase 5 review N1).
    if (err instanceof NflUnavailableError) return <NflUnavailable />;
    throw err;
  }
  // redirect() throws, so it stays outside the try.
  redirect(`/nfl/predictions/${current.season}/${current.week}`);
}
