// NFL team identity for the frontend — mirrors common/nfl/teams.py.
// A franchise is always its lowercase current nickname ("chiefs", "49ers");
// nflverse codes, full names and relocated forms (SD, OAK, STL) are aliases.
// Every accepted form is an explicit registry entry: there is no fuzzy fallback.
import registry from "./team_registry.json";

interface TeamMeta {
  nickname: string;
  full_name: string;
  abbrev: string;
  aliases: string[];
}

const REGISTRY = registry as Record<string, TeamMeta>;

/** Lower-case, drop full stops, collapse separators — same as the Python `_normalise`. */
const normalise = (s: string) =>
  s.trim().toLowerCase().replace(/\./g, "").replace(/[\s\-_]+/g, " ").trim();

const LOOKUP: Record<string, string> = {};
for (const [slug, meta] of Object.entries(REGISTRY)) {
  for (const form of [slug, meta.nickname, meta.full_name, meta.abbrev, ...meta.aliases]) {
    LOOKUP[normalise(form)] = slug;
  }
}

/** Canonical slug for any inbound team string; unknown input passes through unchanged. */
export function toSlug(name: string | undefined | null): string {
  if (!name) return "";
  return LOOKUP[normalise(name)] ?? name;
}

export function isKnown(name: string): boolean {
  return toSlug(name) in REGISTRY;
}

export function allSlugs(): string[] {
  return Object.keys(REGISTRY);
}

/** Display nickname ("Chiefs") for any inbound form; an unknown name echoes back. */
export function teamName(name: string | undefined | null): string {
  if (!name) return "";
  return REGISTRY[toSlug(name)]?.nickname ?? name;
}
