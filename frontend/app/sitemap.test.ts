import { describe, it, expect } from "vitest";
import sitemap from "./sitemap";

const BASE = "https://nrl-predictor.ohare.id.au";
const urls = () => sitemap().map((entry) => entry.url);

describe("sitemap (spec 5.7)", () => {
  it("still lists every NRL round and the NRL pages", () => {
    for (let round = 1; round <= 27; round++) {
      expect(urls()).toContain(`${BASE}/predictions/${round}`);
    }
    expect(urls()).toEqual(expect.arrayContaining([BASE, `${BASE}/accuracy`, `${BASE}/how-it-works`]));
  });

  it("lists the NFL landing and accuracy pages", () => {
    expect(urls()).toEqual(expect.arrayContaining([`${BASE}/nfl`, `${BASE}/nfl/accuracy`]));
  });

  it("has no duplicate URLs", () => {
    expect(new Set(urls()).size).toBe(urls().length);
  });
});
