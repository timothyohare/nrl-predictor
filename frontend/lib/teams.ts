// Team identity for the frontend — mirrors common/teams.py.
// Internally a team is the lowercase slug ("sea-eagles"); this maps any inbound form
// (slug, nickname, full name, alias) to its display nickname and slug.
import registry from "./team_registry.json";

interface TeamMeta {
  nickname: string;
  full_name: string;
  abbrev: string;
  aliases: string[];
}

const REGISTRY = registry as Record<string, TeamMeta>;

const normalise = (s: string) => s.trim().toLowerCase().replace(/[\s\-_]+/g, " ").trim();

// inbound (normalised) form -> slug
const LOOKUP: Record<string, string> = {};
for (const [slug, meta] of Object.entries(REGISTRY)) {
  LOOKUP[normalise(slug)] = slug;
  LOOKUP[normalise(meta.nickname)] = slug;
  LOOKUP[normalise(meta.full_name)] = slug;
  for (const a of meta.aliases) LOOKUP[normalise(a)] = slug;
}

/** Resolve any inbound team string to its canonical slug (or the input if unknown). */
export function toSlug(name: string | undefined | null): string {
  if (!name) return "";
  const norm = normalise(name);
  if (LOOKUP[norm]) return LOOKUP[norm];
  for (const [slug, meta] of Object.entries(REGISTRY)) {
    if (norm.includes(normalise(meta.nickname))) return slug;
  }
  return name;
}

/** Display nickname ("Sea Eagles") for any inbound form; falls back to a title-cased echo. */
export function teamName(name: string | undefined | null): string {
  if (!name) return "";
  const meta = REGISTRY[toSlug(name)];
  if (meta) return meta.nickname;
  return name.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
