import { redirect } from "next/navigation";
import { getNflCurrentWeek, type NflWeek } from "@/lib/nfl/api";
import NflUnavailable from "@/components/nfl/NflUnavailable";

// ISR: regenerate at most hourly (lib/nfl/api.ts NFL_REVALIDATE_SECONDS).
export const revalidate = 3600;

export default async function NflHomePage() {
  let current: NflWeek;
  try {
    current = await getNflCurrentWeek();
  } catch {
    return <NflUnavailable />;
  }
  // redirect() throws, so it stays outside the try.
  redirect(`/nfl/predictions/${current.season}/${current.week}`);
}
