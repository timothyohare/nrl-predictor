import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import {
  NFL_REVALIDATE_SECONDS,
  NflUnavailableError,
  getNflAccuracy,
  getNflCurrentWeek,
  getNflPredictions,
  getNflWeeks,
  loadNflWeek,
  nflApiBase,
} from "./api";

const BASE = "https://nfl.example.test";

function mockFetch(impl: (url: string) => { ok?: boolean; status?: number; json?: () => unknown }) {
  // `init` is declared so the call's fetch options are typed in fn.mock.calls.
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    void init;
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

beforeEach(() => vi.stubEnv("NFL_API_BASE_URL", BASE));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

const CACHED = { next: { revalidate: NFL_REVALIDATE_SECONDS } };

describe("nflApiBase", () => {
  it("reads the server-side NFL_API_BASE_URL and drops trailing slashes", () => {
    vi.stubEnv("NFL_API_BASE_URL", `${BASE}//`);
    expect(nflApiBase()).toBe(BASE);
  });

  it("is '' when unset or blank", () => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    expect(nflApiBase()).toBe("");
    vi.stubEnv("NFL_API_BASE_URL", "   ");
    expect(nflApiBase()).toBe("");
  });
});

describe("review N5: every NFL fetch is ISR-cached, never per visitor", () => {
  it("caches for at least five minutes (the NRL predictions interval)", () => {
    expect(NFL_REVALIDATE_SECONDS).toBeGreaterThanOrEqual(300);
  });

  it.each([
    ["predictions", () => getNflPredictions(2026, 8), "/nfl/predictions/2026/8", []],
    ["current week", () => getNflCurrentWeek(), "/nfl/weeks/current", {}],
    ["week list", () => getNflWeeks(2026), "/nfl/weeks?season=2026", { weeks: [] }],
    ["accuracy", () => getNflAccuracy(2026), "/nfl/accuracy?season=2026", {}],
    ["accuracy (default season)", () => getNflAccuracy(), "/nfl/accuracy", {}],
  ])("%s", async (_name, call, path, payload) => {
    const fn = mockFetch(() => ({ json: async () => payload }));
    await call();
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith(`${BASE}${path}`, CACHED);
    expect(fn.mock.calls[0][1]?.cache).toBeUndefined();
  });
});

describe("getNflPredictions (spec 5.2)", () => {
  it("returns the parsed array on 200", async () => {
    const rows = [{ matchId: "nfl-2026-week-8-raiders-v-chiefs" }];
    mockFetch(() => ({ json: async () => rows }));
    await expect(getNflPredictions(2026, 8)).resolves.toEqual(rows);
  });

  it("resolves to [] on 404", async () => {
    mockFetch(() => ({ ok: false, status: 404 }));
    await expect(getNflPredictions(2026, 17)).resolves.toEqual([]);
  });

  it.each([400, 429, 500])("throws on %i", async (status) => {
    mockFetch(() => ({ ok: false, status }));
    await expect(getNflPredictions(2026, 8)).rejects.toThrow(String(status));
  });

  it("throws NflUnavailableError without fetching when the base URL is unset", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    const fn = mockFetch(() => ({}));
    await expect(getNflPredictions(2026, 8)).rejects.toBeInstanceOf(NflUnavailableError);
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("getNflCurrentWeek / getNflWeeks / getNflAccuracy", () => {
  it("current week returns the body and throws on any non-OK", async () => {
    const week = { season: 2026, week: 8, stage: "REG", label: "Week 8" };
    mockFetch(() => ({ json: async () => week }));
    await expect(getNflCurrentWeek()).resolves.toEqual(week);
    mockFetch(() => ({ ok: false, status: 404 }));
    await expect(getNflCurrentWeek()).rejects.toThrow("404");
  });

  it("week list returns the weeks array and throws on any non-OK", async () => {
    const weeks = [{ week: 19, stage: "WC", label: "Wild Card" }];
    mockFetch(() => ({ json: async () => ({ season: 2025, weeks }) }));
    await expect(getNflWeeks(2025)).resolves.toEqual(weeks);
    mockFetch(() => ({ ok: false, status: 500 }));
    await expect(getNflWeeks(2025)).rejects.toThrow("500");
  });

  it("accuracy throws on any non-OK", async () => {
    mockFetch(() => ({ ok: false, status: 404 }));
    await expect(getNflAccuracy(2019)).rejects.toThrow("404");
  });

  it.each([
    ["current week", () => getNflCurrentWeek()],
    ["week list", () => getNflWeeks(2026)],
    ["accuracy", () => getNflAccuracy()],
  ])("%s throws NflUnavailableError when the base URL is unset", async (_name, call) => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    await expect(call()).rejects.toBeInstanceOf(NflUnavailableError);
  });
});

describe("loadNflWeek (spec 5.6)", () => {
  const prediction = { matchId: "nfl-2025-week-19-bills-v-dolphins", label: "Wild Card" };

  it("returns predictions and the season's week list with API labels", async () => {
    mockFetch((url) => ({
      json: async () => (url.includes("/nfl/weeks")
        ? { season: 2025, weeks: [{ week: 18, stage: "REG", label: "Week 18" },
                                  { week: 19, stage: "WC", label: "Wild Card" }] }
        : [prediction]),
    }));
    await expect(loadNflWeek(2025, 19)).resolves.toEqual({
      status: "ok",
      season: 2025,
      week: 19,
      label: "Wild Card",
      predictions: [prediction],
      weeks: [{ week: 18, label: "Week 18" }, { week: 19, label: "Wild Card" }],
    });
  });

  it("an empty week is ok with no predictions", async () => {
    mockFetch((url) => (url.includes("/nfl/weeks")
      ? { json: async () => ({ season: 2026, weeks: [{ week: 17, stage: "REG", label: "Week 17" }] }) }
      : { ok: false, status: 404 }));
    const view = await loadNflWeek(2026, 17);
    expect(view).toMatchObject({ status: "ok", label: "Week 17", predictions: [] });
  });

  it("falls back to the predictions' own label when the week list fails", async () => {
    mockFetch((url) => (url.includes("/nfl/weeks")
      ? { ok: false, status: 500 }
      : { json: async () => [prediction] }));
    await expect(loadNflWeek(2025, 19)).resolves.toMatchObject({
      status: "ok",
      label: "Wild Card",
      weeks: [{ week: 19, label: "Wild Card" }],
    });
  });

  it("adds the viewed week when the list does not contain it", async () => {
    mockFetch((url) => ({
      json: async () => (url.includes("/nfl/weeks")
        ? { season: 2025, weeks: [{ week: 18, stage: "REG", label: "Week 18" }] }
        : [prediction]),
    }));
    const view = await loadNflWeek(2025, 19);
    expect(view.status === "ok" && view.weeks).toEqual([
      { week: 18, label: "Week 18" }, { week: 19, label: "Wild Card" },
    ]);
  });

  it("is unavailable when the base URL is unset", async () => {
    vi.stubEnv("NFL_API_BASE_URL", "");
    await expect(loadNflWeek(2026, 8)).resolves.toEqual({ status: "unavailable" });
  });

  it("is unavailable when the predictions fetch fails or rejects", async () => {
    mockFetch(() => ({ ok: false, status: 500 }));
    await expect(loadNflWeek(2026, 8)).resolves.toEqual({ status: "unavailable" });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(loadNflWeek(2026, 8)).resolves.toEqual({ status: "unavailable" });
  });
});
