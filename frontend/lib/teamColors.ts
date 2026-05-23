// Accent color for each NRL team (used for match card stripes / dots).
// Picked for legibility against a paper background — teams whose primary
// is black/navy use their secondary (e.g. Cowboys yellow, Panthers teal).
// Sanity-check the choices against the official kit if anything looks off.
const TEAM_COLORS: Record<string, string> = {
  broncos: "#6F0F2A",       // maroon
  bulldogs: "#00529F",      // blue
  cowboys: "#FFDD00",       // yellow (over navy)
  dolphins: "#B8092C",      // red
  dragons: "#E2231B",       // red
  eels: "#006EB5",          // blue
  knights: "#EE2737",       // red (over navy)
  panthers: "#00674F",      // teal (over black)
  rabbitohs: "#006A4E",     // green
  raiders: "#94BF1F",       // lime
  roosters: "#E10027",      // red
  "sea-eagles": "#6F0F2A",  // maroon
  sharks: "#00ACED",        // sky blue
  storm: "#4B208C",         // purple
  titans: "#FBC012",        // gold
  warriors: "#1A1A1A",      // black
  tigers: "#F68B1F",        // orange
  "wests-tigers": "#F68B1F",
};

export function teamColor(name?: string): string {
  if (!name) return "#9CA3AF";
  const key = name.toLowerCase().trim().replace(/\s+/g, "-");
  return TEAM_COLORS[key] ?? "#9CA3AF";
}
