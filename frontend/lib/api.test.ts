import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  splitMatchId,
  getPredictions,
  getAccuracy,
  getTournamentLeaderboard,
  currentRound,
} from "./api";

function mockFetch(impl: (url: string) => Partial<Response> & { json?: () => unknown }) {
  const fn = vi.fn(async (url: string) => {
    const r = impl(url);
    return {
      ok: r.ok ?? true,
      status: r.status ?? 200,
      json: r.json ?? (async () => ({})),
    } as unknown as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("splitMatchId", () => {
  it("strips a round-N- prefix and splits on -v-", () => {
    expect(splitMatchId("round-12-panthers-v-broncos")).toEqual(["panthers", "broncos"]);
    expect(splitMatchId("round-3-sea-eagles-v-wests-tigers")).toEqual([
      "sea-eagles",
      "wests-tigers",
    ]);
  });

  it("leaves an unqualified matchId alone", () => {
    expect(splitMatchId("panthers-v-broncos")).toEqual(["panthers", "broncos"]);
  });

  it("only strips a leading round-<digits>- (not mid-string)", () => {
    expect(splitMatchId("round-x-panthers-v-broncos")).toEqual(["round-x-panthers", "broncos"]);
  });

  it("degrades to empty strings on a malformed id", () => {
    expect(splitMatchId("garbage")).toEqual(["garbage", ""]);
    expect(splitMatchId("")).toEqual(["", ""]);
  });
});

describe("getPredictions", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("returns the parsed array on 200", async () => {
    const rows = [{ matchId: "round-1-a-v-b" }, { matchId: "round-1-c-v-d" }];
    const fn = mockFetch(() => ({ ok: true, status: 200, json: async () => rows }));
    await expect(getPredictions(1)).resolves.toEqual(rows);
    expect(fn).toHaveBeenCalledWith(
      expect.stringContaining("/predictions/1"),
      expect.objectContaining({ next: { revalidate: 300 } }),
    );
  });

  it("returns [] on 404 (round not yet published)", async () => {
    mockFetch(() => ({ ok: false, status: 404 }));
    await expect(getPredictions(99)).resolves.toEqual([]);
  });

  it("throws on any other non-2xx status", async () => {
    mockFetch(() => ({ ok: false, status: 500 }));
    await expect(getPredictions(1)).rejects.toThrow("Failed to fetch predictions: 500");
  });
});

describe("getAccuracy", () => {
  it("returns the parsed body on 200", async () => {
    const body = { season: [], rounds: [] };
    mockFetch(() => ({ ok: true, status: 200, json: async () => body }));
    await expect(getAccuracy()).resolves.toEqual(body);
  });

  it("throws on non-2xx", async () => {
    mockFetch(() => ({ ok: false, status: 502 }));
    await expect(getAccuracy()).rejects.toThrow("Failed to fetch accuracy: 502");
  });
});

describe("getTournamentLeaderboard", () => {
  it("returns the parsed body on 200 and omits the query string when no season", async () => {
    const body = { season: 2026, leaderboard: [] };
    const fn = mockFetch(() => ({ ok: true, status: 200, json: async () => body }));
    await expect(getTournamentLeaderboard()).resolves.toEqual(body);
    expect(fn.mock.calls[0][0]).toMatch(/\/tournament\/leaderboard$/);
  });

  it("appends ?season= when a season is given", async () => {
    const fn = mockFetch(() => ({ ok: true, status: 200, json: async () => ({}) }));
    await getTournamentLeaderboard(2025);
    expect(fn.mock.calls[0][0]).toContain("/tournament/leaderboard?season=2025");
  });

  it("returns null on any non-2xx rather than throwing", async () => {
    mockFetch(() => ({ ok: false, status: 500 }));
    await expect(getTournamentLeaderboard()).resolves.toBeNull();
  });
});

describe("currentRound", () => {
  it("clamps to 1 before the season starts", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    expect(currentRound()).toBe(1);
  });

  it("clamps to 27 late in the year", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-12-01T00:00:00Z"));
    expect(currentRound()).toBe(27);
  });

  it("returns the week-derived round mid-season", () => {
    vi.useFakeTimers();
    // ~5 weeks after the 2026-03-05 start
    vi.setSystemTime(new Date("2026-04-09T00:00:00Z"));
    const r = currentRound();
    expect(r).toBeGreaterThanOrEqual(4);
    expect(r).toBeLessThanOrEqual(6);
  });
});
