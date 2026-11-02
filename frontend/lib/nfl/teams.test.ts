import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { allSlugs, isKnown, teamName, toSlug } from "./teams";
import registry from "./team_registry.json";

// Mirrors tests/common/nfl/test_teams.py so the TS NFL registry
// (frontend/lib/nfl/team_registry.json) and the Python one can't drift (spec 5.1).

// vitest runs from frontend/ (npm scripts, the harness `test` binding).
const PYTHON_REGISTRY = JSON.parse(
  readFileSync(resolve(process.cwd(), "../common/nfl/team_registry.json"), "utf8"),
);

describe("NFL registry parity with common/nfl/team_registry.json", () => {
  it("deep-equals the Python registry", () => {
    expect(registry).toEqual(PYTHON_REGISTRY);
  });

  it("has exactly 32 franchises", () => {
    expect(allSlugs()).toHaveLength(32);
  });

  it("slug is the lowercased current nickname", () => {
    for (const [slug, meta] of Object.entries(registry)) {
      expect(slug).toBe(meta.nickname.toLowerCase());
    }
    expect(allSlugs()).toEqual(expect.arrayContaining(["chiefs", "49ers", "commanders"]));
  });
});

describe("toSlug", () => {
  it.each([
    ["SD", "LAC", "chargers"],
    ["OAK", "LV", "raiders"],
    ["STL", "LA", "rams"],
  ])("relocated %s and %s share the slug %s", (old, current, slug) => {
    expect(toSlug(old)).toBe(slug);
    expect(toSlug(current)).toBe(slug);
  });

  it("resolves every current nflverse code to a distinct franchise", () => {
    const codes = [
      "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
      "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO",
      "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    ];
    expect(codes.map(toSlug).sort()).toEqual([...allSlugs()].sort());
  });

  it("is idempotent over every slug and abbreviation", () => {
    for (const [slug, meta] of Object.entries(registry)) {
      expect(toSlug(slug)).toBe(slug);
      expect(toSlug(toSlug(meta.abbrev))).toBe(slug);
    }
  });

  it.each([
    ["Kansas City Chiefs", "chiefs"],
    ["San Diego Chargers", "chargers"],
    ["Oakland Raiders", "raiders"],
    ["St. Louis Rams", "rams"],
    ["Washington Football Team", "commanders"],
    ["San Francisco 49ers", "49ers"],
    ["  new-england patriots ", "patriots"],
  ])("toSlug(%j) === %j", (name, slug) => {
    expect(toSlug(name)).toBe(slug);
  });

  it("passes an unknown name through unchanged, with no fuzzy match", () => {
    expect(toSlug("XYZ")).toBe("XYZ");
    expect(isKnown("XYZ")).toBe(false);
    expect(toSlug("Chiefs Kingdom")).toBe("Chiefs Kingdom");
  });

  it("returns '' for empty, null and undefined", () => {
    expect(toSlug("")).toBe("");
    expect(toSlug(null)).toBe("");
    expect(toSlug(undefined)).toBe("");
  });
});

describe("teamName", () => {
  it.each([
    ["chiefs", "Chiefs"],
    ["KC", "Chiefs"],
    ["49ers", "49ers"],
    ["SD", "Chargers"],
  ])("teamName(%j) === %j", (name, display) => {
    expect(teamName(name)).toBe(display);
  });

  it("echoes an unknown name and returns '' for empty input", () => {
    expect(teamName("XYZ")).toBe("XYZ");
    expect(teamName(null)).toBe("");
  });
});
