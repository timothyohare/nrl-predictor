"""
Spike: Bureau of Meteorology (BOM)
Tests two BOM data paths:
  1. BOM JSON API (IDN10064 format) — machine-readable forecasts
  2. BOM observations for NRL venue postcodes

NRL venues and their BOM product codes:
  Accor Stadium (Sydney Olympic Park)  → IDN10064 (Sydney metro)
  Suncorp Stadium (Brisbane)           → IDQ10095 (Brisbane)
  AAMI Park (Melbourne)                → IDV10450 (Melbourne)
  McDonald Jones Stadium (Newcastle)   → IDN10064 or IDN11051
  GIO Stadium (Canberra)               → IDN11060
  WIN Stadium (Wollongong)             → IDN10064
  PointsBet Stadium (Cronulla)         → IDN10064
  Allegiant Stadium (Las Vegas)        → skip / use Open-Meteo
  CommBank Stadium (Parramatta)        → IDN10064

BOM also provides a free JSON API via api.weather.bom.gov.au (newer, REST-style).
We test both the legacy product feed and the new API.
"""

import json
import time
import requests
from datetime import datetime, timedelta
from pprint import pformat

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Accept-Language": "en-AU,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# BOM station IDs for key NRL venues (lat/lon for new API)
NRL_VENUES = {
    "Accor Stadium":          {"bom_product": "IDN10064", "lat": -33.8474, "lon": 151.0631},
    "Suncorp Stadium":        {"bom_product": "IDQ10095", "lat": -27.4653, "lon": 153.0089},
    "AAMI Park":              {"bom_product": "IDV10450", "lat": -37.8200, "lon": 144.9836},
    "McDonald Jones Stadium": {"bom_product": "IDN11051", "lat": -32.9265, "lon": 151.7666},
    "GIO Stadium":            {"bom_product": "IDN11060", "lat": -35.2009, "lon": 149.1231},
}

def get(url, label):
    print(f"\n[GET] {label}")
    print(f"      {url}")
    t0 = time.time()
    try:
        r = SESSION.get(url, timeout=10)
        elapsed = time.time() - t0
        print(f"      Status: {r.status_code}  |  {elapsed:.2f}s  |  {len(r.content):,} bytes")
        print(f"      Content-Type: {r.headers.get('Content-Type', '?')}")
        return r
    except Exception as e:
        print(f"      ERROR: {type(e).__name__}: {e}")
        return None

def section(title):
    print(f"\n{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}")

# ── Test 1: BOM New REST API ──────────────────────────────────────────────────

def test_new_bom_api():
    section("1. BOM REST API (api.weather.bom.gov.au)")

    # The new BOM API uses a geohash/location endpoint
    # Step 1: search for location
    for venue_name, info in list(NRL_VENUES.items())[:2]:
        lat, lon = info["lat"], info["lon"]
        print(f"\n  Venue: {venue_name}")

        # Location search
        search_url = f"https://api.weather.bom.gov.au/v1/locations?search={lat},{lon}"
        r = get(search_url, "Location search")
        if r and r.status_code == 200:
            try:
                data = r.json()
                print(f"  Response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                locs = data.get("data", [])
                if locs:
                    loc = locs[0]
                    print(f"  First location: {loc.get('name')} — geohash: {loc.get('geohash')}")
                    geohash = loc.get("geohash")

                    if geohash:
                        # Daily forecast
                        fc_url = f"https://api.weather.bom.gov.au/v1/locations/{geohash}/forecasts/daily"
                        fr = get(fc_url, "Daily forecast")
                        if fr and fr.status_code == 200:
                            fc = fr.json()
                            days = fc.get("data", [])
                            print(f"\n  Forecast days available: {len(days)}")
                            if days:
                                print(f"  Day 0 keys: {list(days[0].keys())}")
                                for day in days[:3]:
                                    date = day.get("date", "?")
                                    rain = day.get("rain", {})
                                    temp = day.get("temp_max", "?")
                                    chance = rain.get("chance", "?")
                                    amount = rain.get("amount", {})
                                    print(f"    {date}  temp_max={temp}°C  rain_chance={chance}%  amount={amount}")
                        
                        # Hourly forecast (more precise for match-time)
                        hr_url = f"https://api.weather.bom.gov.au/v1/locations/{geohash}/forecasts/hourly"
                        hr = get(hr_url, "Hourly forecast")
                        if hr and hr.status_code == 200:
                            hf = hr.json()
                            hours = hf.get("data", [])
                            print(f"\n  Hourly forecasts available: {len(hours)}")
                            if hours:
                                print(f"  Hour 0 keys: {list(hours[0].keys())}")
                                for h in hours[:3]:
                                    print(f"    {h.get('time','?')}  "
                                          f"temp={h.get('temp','?')}°C  "
                                          f"rain={h.get('rain',{}).get('chance','?')}%  "
                                          f"wind={h.get('wind',{}).get('speed_kilometre','?')}km/h")
            except Exception as e:
                print(f"  Parse error: {e}")
                print(f"  Raw (first 200 chars): {r.text[:200]}")

# ── Test 2: BOM Legacy JSON Feed ──────────────────────────────────────────────

def test_legacy_bom_feed():
    section("2. BOM Legacy JSON Product Feed")
    
    # Legacy BOM feeds: https://reg.bom.gov.au/fwo/IDN10064/IDN10064.95.json
    # Format: IDxxxxxx = product code, .95 = city forecast observations
    
    for venue_name, info in list(NRL_VENUES.items())[:2]:
        product = info["bom_product"]
        url = f"https://reg.bom.gov.au/fwo/{product}/{product}.95.json"
        print(f"\n  Venue: {venue_name}  Product: {product}")
        r = get(url, "Legacy feed")
        if r and r.status_code == 200:
            try:
                data = r.json()
                obs = data.get("observations", {})
                header = obs.get("header", [{}])
                entries = obs.get("data", [])
                print(f"  Header: {header[0] if header else '?'}")
                print(f"  Observations: {len(entries)} entries")
                if entries:
                    print(f"  Entry keys: {list(entries[0].keys())[:12]}")
                    e = entries[0]
                    print(f"  Latest: {e.get('local_date_time_full','?')}  "
                          f"rain={e.get('rain_trace','?')}mm  "
                          f"temp={e.get('air_temp','?')}°C  "
                          f"wind={e.get('wind_spd_kmh','?')}km/h {e.get('wind_dir','?')}")
            except Exception as ex:
                print(f"  Parse error: {ex}")
                print(f"  Raw: {r.text[:300]}")

# ── Test 3: Open-Meteo fallback ────────────────────────────────────────────────

def test_open_meteo():
    section("3. Open-Meteo (free, no key, international fallback)")
    
    # Good for Las Vegas games or if BOM is unreliable
    # https://open-meteo.com/en/docs
    venues = [
        ("Accor Stadium",  -33.8474, 151.0631),
        ("Suncorp Stadium",-27.4653, 153.0089),
    ]
    
    for name, lat, lon in venues:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,precipitation_probability,precipitation,windspeed_10m"
            f"&daily=precipitation_probability_max,precipitation_sum,windspeed_10m_max"
            f"&timezone=Australia%2FSydney&forecast_days=7"
        )
        print(f"\n  Venue: {name}")
        r = get(url, "Open-Meteo forecast")
        if r and r.status_code == 200:
            try:
                data = r.json()
                daily = data.get("daily", {})
                hourly = data.get("hourly", {})
                print(f"  Daily fields:  {list(daily.keys())}")
                print(f"  Hourly fields: {list(hourly.keys())}")
                dates = daily.get("time", [])
                rain_prob = daily.get("precipitation_probability_max", [])
                rain_sum = daily.get("precipitation_sum", [])
                wind = daily.get("windspeed_10m_max", [])
                for i, d in enumerate(dates[:4]):
                    print(f"    {d}  rain_prob={rain_prob[i] if i < len(rain_prob) else '?'}%  "
                          f"rain={rain_sum[i] if i < len(rain_sum) else '?'}mm  "
                          f"wind={wind[i] if i < len(wind) else '?'}km/h")
            except Exception as ex:
                print(f"  Parse error: {ex}")

# ── Summary ───────────────────────────────────────────────────────────────────

def summarise():
    section("Summary / Recommendations")
    print("""
  Priority order for weather data:

  1. BOM REST API (api.weather.bom.gov.au)
       → Best for Australian venues
       → Use location search to get geohash, then hit /forecasts/hourly
       → Hourly is better than daily: get forecast for kick-off time specifically
       → Free, no API key required
       → If geohash lookup fails, fall back to hardcoded geohashes per venue

  2. BOM Legacy Feed (reg.bom.gov.au/fwo/...)
       → More stable URL structure, but observations not forecasts
       → Useful for checking conditions on match day

  3. Open-Meteo (api.open-meteo.com)
       → Free, no key, global coverage
       → Use for Las Vegas games or as fallback if BOM is down
       → 7-day hourly forecast available

  PROMPT INTEGRATION:
    Don't pass raw weather data to the agent. Pre-process it:
      {
        "venue": "Suncorp Stadium",
        "match_date": "2026-05-16",
        "kickoff_time": "19:35",
        "forecast_at_kickoff": {
          "rain_chance_pct": 70,
          "expected_rain_mm": 4.2,
          "wind_kmh": 22,
          "temp_c": 18,
          "conditions": "Wet and windy — expect kicking game, errors"
        }
      }
    The "conditions" summary is generated by a cheap Haiku call before
    the main agent runs, so the main agent gets a plain English summary.
    """)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    test_new_bom_api()
    test_legacy_bom_feed()
    test_open_meteo()
    summarise()

if __name__ == "__main__":
    run()
