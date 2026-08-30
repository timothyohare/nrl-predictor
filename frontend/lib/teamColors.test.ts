import { describe, it, expect } from "vitest";
import { teamColor } from "./teamColors";

const NEUTRAL = "#9CA3AF";

describe("teamColor", () => {
  it("returns the mapped accent for a known slug", () => {
    expect(teamColor("broncos")).toBe("#6F0F2A");
    expect(teamColor("storm")).toBe("#4B208C");
    expect(teamColor("sea-eagles")).toBe("#6F0F2A");
    expect(teamColor("wests-tigers")).toBe("#F68B1F");
  });

  it("normalises spacing and case before lookup", () => {
    expect(teamColor("Sea Eagles")).toBe("#6F0F2A");
    expect(teamColor("  WESTS  TIGERS  ")).toBe("#F68B1F");
    expect(teamColor("Storm")).toBe("#4B208C");
  });

  it("falls back to the neutral grey for an unknown slug", () => {
    expect(teamColor("some-expansion-fc")).toBe(NEUTRAL);
    expect(teamColor("bunnies")).toBe(NEUTRAL); // alias, not a colour key
  });

  it("falls back to the neutral grey for empty / missing input", () => {
    expect(teamColor("")).toBe(NEUTRAL);
    expect(teamColor(undefined)).toBe(NEUTRAL);
  });
});
