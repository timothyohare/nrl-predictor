import { describe, it, expect } from "vitest";
import { toSlug, teamName } from "./teams";
import registry from "./team_registry.json";

// These cases mirror tests/common/test_teams.py so the TS registry
// (frontend/lib/team_registry.json) and the Python one can't silently drift.

describe("toSlug — known forms resolve to the canonical slug", () => {
  const cases: [string, string][] = [
    ["sea-eagles", "sea-eagles"],
    ["Sea Eagles", "sea-eagles"],
    ["Manly Sea Eagles", "sea-eagles"],
    ["Manly-Warringah Sea Eagles", "sea-eagles"],
    ["manly", "sea-eagles"],
    ["Melbourne Storm", "storm"],
    ["STORM", "storm"],
    ["Canterbury-Bankstown Bulldogs", "bulldogs"],
    ["South Sydney Rabbitohs", "rabbitohs"],
    ["souths", "rabbitohs"],
    ["Wests Tigers", "wests-tigers"],
    ["wests-tigers", "wests-tigers"],
    ["tigers", "wests-tigers"],
    ["Dolphins", "dolphins"],
    ["redcliffe", "dolphins"],
  ];
  it.each(cases)("toSlug(%j) === %j", (supplied, expected) => {
    expect(toSlug(supplied)).toBe(expected);
  });
});

describe("toSlug — separator variants collapse", () => {
  const cases: [string, string][] = [
    ["Manly_Sea_Eagles", "sea-eagles"],
    ["wests_tigers", "wests-tigers"],
    ["_manly", "sea-eagles"],
  ];
  it.each(cases)("toSlug(%j) === %j", (supplied, expected) => {
    expect(toSlug(supplied)).toBe(expected);
  });
});

describe("toSlug — idempotent over every registered slug", () => {
  it.each(Object.keys(registry))("toSlug is a fixed point for %s", (slug) => {
    expect(toSlug(slug)).toBe(slug);
    expect(toSlug(toSlug(slug))).toBe(slug);
  });
});

describe("toSlug — total on unknown / empty input", () => {
  it("passes an unrecognised name through unchanged", () => {
    expect(toSlug("Some Expansion FC")).toBe("Some Expansion FC");
  });
  it("returns '' for empty string", () => {
    expect(toSlug("")).toBe("");
  });
  it("returns '' for null", () => {
    expect(toSlug(null)).toBe("");
  });
  it("returns '' for undefined", () => {
    expect(toSlug(undefined)).toBe("");
  });
});

describe("teamName — display nickname for any inbound form", () => {
  const cases: [string, string][] = [
    ["storm", "Storm"],
    ["Melbourne Storm", "Storm"],
    ["STORM", "Storm"],
    ["sea-eagles", "Sea Eagles"],
    ["manly", "Sea Eagles"],
    ["Manly-Warringah Sea Eagles", "Sea Eagles"],
    ["wests-tigers", "Wests Tigers"],
    ["tigers", "Wests Tigers"],
    ["redcliffe", "Dolphins"],
  ];
  it.each(cases)("teamName(%j) === %j", (supplied, expected) => {
    expect(teamName(supplied)).toBe(expected);
  });

  it("title-cases an unknown slug-like string as a fallback", () => {
    expect(teamName("some-expansion-fc")).toBe("Some Expansion Fc");
    expect(teamName("some_expansion_fc")).toBe("Some Expansion Fc");
  });

  it("echoes a genuinely unknown free-text name unchanged (already title-ish)", () => {
    expect(teamName("Some Expansion FC")).toBe("Some Expansion FC");
  });

  it("returns '' for null / undefined / empty", () => {
    expect(teamName(null)).toBe("");
    expect(teamName(undefined)).toBe("");
    expect(teamName("")).toBe("");
  });
});

describe("registry shape", () => {
  it("nickname and full_name round-trip back to the slug", () => {
    for (const [slug, meta] of Object.entries(registry)) {
      expect(toSlug(meta.nickname)).toBe(slug);
      expect(toSlug(meta.full_name)).toBe(slug);
    }
  });
});
