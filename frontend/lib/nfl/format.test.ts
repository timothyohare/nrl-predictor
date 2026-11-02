import { describe, it, expect } from "vitest";
import { formatKickoff, marginText, winnerProbability } from "./format";

describe("formatKickoff — Australia/Sydney (spec 5.3)", () => {
  it.each([
    ["2026-11-02T18:00:00Z", "Tue 3 Nov, 5:00 am AEDT"],
    // Sydney DST starts 2026-10-04 02:00 AEST -> 03:00 AEDT
    ["2026-10-03T15:30:00Z", "Sun 4 Oct, 1:30 am AEST"],
    ["2026-10-03T16:30:00Z", "Sun 4 Oct, 3:30 am AEDT"],
    // and ends 2026-04-05 03:00 AEDT -> 02:00 AEST
    ["2026-04-04T15:30:00Z", "Sun 5 Apr, 2:30 am AEDT"],
    ["2026-04-04T16:30:00Z", "Sun 5 Apr, 2:30 am AEST"],
    // a US-evening kickoff the day before
    ["2026-10-30T00:15:00Z", "Fri 30 Oct, 11:15 am AEDT"],
  ])("%s -> %s", (iso, expected) => {
    expect(formatKickoff(iso)).toBe(expected);
  });

  it("is '' for a missing or unparsable kickoff", () => {
    expect(formatKickoff(null)).toBe("");
    expect(formatKickoff(undefined)).toBe("");
    expect(formatKickoff("not a date")).toBe("");
  });
});

describe("marginText — plain integers, no even-number snapping", () => {
  it("renders the band", () => {
    expect(marginText({ predicted_margin: 6, margin_low: 3, margin_high: 10 })).toBe("3–10");
  });

  it("keeps odd values as they are", () => {
    expect(marginText({ predicted_margin: 5, margin_low: 1, margin_high: 9 })).toBe("1–9");
  });

  it("falls back to the point margin without a usable band", () => {
    expect(marginText({ predicted_margin: 4 })).toBe("4");
    expect(marginText({ predicted_margin: 4, margin_low: 4, margin_high: 4 })).toBe("4");
    expect(marginText({ predicted_margin: 4, margin_low: 2 })).toBe("4");
  });
});

describe("winnerProbability", () => {
  it("is the home probability when the home team is picked", () => {
    expect(winnerProbability({ predicted_winner: "raiders", home_team: "raiders", home_win_probability: 0.62 }))
      .toBeCloseTo(0.62);
  });

  it("is the complement when the away team is picked", () => {
    expect(winnerProbability({ predicted_winner: "chiefs", home_team: "raiders", home_win_probability: 0.3 }))
      .toBeCloseTo(0.7);
  });
});
