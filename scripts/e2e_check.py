"""Black-box E2E check of SafeRoute against the brief. Stdlib only; no app imports.

usage: python3 e2e.py BASE_URL
"""
import json, math, sys, random, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

BASE = sys.argv[1].rstrip("/")
fails, passes = [], 0


def check(cond, msg):
    global passes
    if cond:
        passes += 1
    else:
        fails.append(msg)
        print("  FAIL:", msg)


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


# ---- independent implementation of the brief's rules ----
def lvl_wind(w): return 4 if w >= 55 else 3 if w >= 45 else 2 if w >= 35 else 1 if w >= 25 else 0
def lvl_rain(r): return 4 if r > 1.0 else 3 if r >= 0.5 else 2 if r >= 0.25 else 1 if r >= 0.10 else 0
def lvl_snow(s): return 4 if s > 3.0 else 3 if s >= 2.0 else 2 if s >= 1.0 else 1 if s >= 0.5 else 0
def brief_level(w, r, s, load):
    lw = lvl_wind(w)
    if w >= 55: lw = 4
    elif 45 <= w < 55 and load > 30000: lw = 4
    elif 35 <= w < 45 and load > 40000: lw = max(lw, 3)
    return max(lw, lvl_rain(r), lvl_snow(s))


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3958.76 * math.asin(math.sqrt(h))


def open_meteo_at(lat, lon, eta):
    """Ask Open-Meteo directly for the forecast at (lat, lon) around eta."""
    h0 = eta.replace(minute=0, second=0, microsecond=0)
    q = urllib.parse.urlencode({"latitude": round(round(lat / 0.1) * 0.1, 4), "longitude": round(round(lon / 0.1) * 0.1, 4),
        "hourly": "wind_speed_10m,rain,snowfall", "wind_speed_unit": "mph", "precipitation_unit": "inch", "timezone": "GMT",
        "start_hour": h0.strftime("%Y-%m-%dT%H:%M"), "end_hour": (h0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")})
    for _ in range(4):
        try:
            d = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=30))["hourly"]
            break
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(30)
    f = (eta - h0).total_seconds() / 3600
    wind = d["wind_speed_10m"][0] + (d["wind_speed_10m"][1] - d["wind_speed_10m"][0]) * f
    return wind, d["rain"][1], d["snowfall"][1]  # precip: bucket for the hour being driven


def parse(t): return datetime.fromisoformat(t.replace("Z", "+00:00"))


PLACES = {}
def geocode(q):
    st, d = call("/api/geocode?q=" + urllib.parse.quote(q))
    check(st == 200 and d["results"], f"geocode '{q}' returns results")
    PLACES[q] = d["results"][0]
    return d["results"][0]


TRIPS = [("Chicago, IL", "Denver, CO", 25, 42000, True), ("Dallas, TX", "Atlanta, GA", 10, 29000, False),
         ("Seattle, WA", "Salt Lake City, UT", 50, 45000, True), ("Kansas City, MO", "Minneapolis, MN", 10, 80000, False)]

print("== Requirement: user enters origin/destination (geocoding)")
for o, d, *_ in TRIPS:
    geocode(o); geocode(d)

for n_trip, (o, d, interval, load, hos) in enumerate(TRIPS):
    if n_trip: time.sleep(65)  # stay under the free weather tier's per-minute quota
    print(f"\n== Trip {o} -> {d}  interval={interval} load={load} hos={hos}")
    dep = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    body = {"origin": PLACES[o], "destination": PLACES[d], "departure": dep.isoformat(), "load_lb": load,
            "interval_mi": interval, "hos": hos}
    st, plan = call("/api/plan", body)
    check(st == 200, f"plan HTTP 200 (got {st}: {plan.get('error') if st != 200 else ''})")
    if st != 200: continue
    check(plan["storm"] is None, "real weather only (no simulated storm) by default")
    routes = plan["routes"]

    # R: 3 route options, genuinely different
    check(len(routes) == 3, f"3 route options (got {len(routes)})")
    for i in range(len(routes)):
        for j in range(i + 1, len(routes)):
            a, b = routes[i], routes[j]
            same = abs(a["distance_mi"] - b["distance_mi"]) < 0.5 and abs(a["drive_s"] - b["drive_s"]) < 60
            check(not same, f"routes {a['id']} and {b['id']} are distinct")

    for r in routes:
        cps = r["checkpoints"]
        # R: sample every N miles
        gaps = [cps[k + 1]["mile"] - cps[k]["mile"] for k in range(len(cps) - 1)]
        check(cps[0]["mile"] == 0 and abs(cps[-1]["mile"] - r["distance_mi"]) < 0.2, f"{r['id']}: checkpoints span origin..destination")
        check(all(abs(g - interval) < 0.01 for g in gaps[:-1]) and 0 < gaps[-1] <= interval + 0.5,
              f"{r['id']}: checkpoints every {interval} mi (gaps {sorted(set(round(g,1) for g in gaps))[:5]})")
        # checkpoint positions are actually on the route, spaced ~interval apart in straight line (<= road distance)
        for k in range(len(cps) - 1):
            sl = hav((cps[k]["lat"], cps[k]["lon"]), (cps[k + 1]["lat"], cps[k + 1]["lon"]))
            if sl > gaps[k] + 0.5:
                check(False, f"{r['id']}: checkpoint {k} straight-line {sl:.1f} > road gap {gaps[k]:.1f}"); break
        # R: ETA at each checkpoint, monotonic, starts at departure, matches arrival
        etas = [parse(c["eta"]) for c in cps]
        check(abs((etas[0] - dep).total_seconds()) < 1, f"{r['id']}: first ETA = departure")
        check(all(etas[k] < etas[k + 1] for k in range(len(etas) - 1)), f"{r['id']}: ETAs strictly increase")
        check(abs((etas[-1] - parse(r["arrival"])).total_seconds()) < 2, f"{r['id']}: last ETA = arrival")
        avg_mph = r["distance_mi"] / (r["drive_s"] / 3600)
        check(35 < avg_mph <= 65.5, f"{r['id']}: truck avg speed plausible ({avg_mph:.1f} mph, cap 65)")
        if hos:
            dh = r["drive_s"] / 3600
            rests = math.ceil(dh / 11) - 1 if dh > 0 else 0
            extra = rests * 10 + (rests + (1 if dh - rests * 11 > 8 else 0)) * 0.5
            check(abs(r["elapsed_s"] / 3600 - dh - extra) < 0.02, f"{r['id']}: HOS breaks applied ({dh:.1f}h drive -> +{extra}h)")
        else:
            check(r["elapsed_s"] == r["drive_s"], f"{r['id']}: no HOS -> elapsed == drive")

        # R: weather risk per brief rules (independent reimplementation)
        bad = [c for c in cps if c["risk"] and c["risk"]["level"] != brief_level(c["weather"]["wind_mph"], c["weather"]["rain_in_hr"], c["weather"]["snow_in_hr"], load)]
        check(not bad, f"{r['id']}: every checkpoint level matches the brief's table+load rules ({len(bad)} mismatches)")
        check(all(c["risk"] is not None for c in cps), f"{r['id']}: weather present at every checkpoint")
        # miles by level add up and match checkpoint attribution
        mbl = [0.0] * 5
        for c in cps:
            mbl[c["risk"]["level"]] += c["span_mi"][1] - c["span_mi"][0]
        check(all(abs(a - b) < 0.3 for a, b in zip(mbl, r["miles_by_level"])), f"{r['id']}: miles_by_level consistent with checkpoints")
        check(abs(sum(r["miles_by_level"]) - r["distance_mi"]) < 0.5, f"{r['id']}: miles_by_level sums to distance")
        avg = sum(l * m for l, m in enumerate(mbl)) / r["distance_mi"]
        check(abs(avg - r["avg_risk"]) < 0.01, f"{r['id']}: avg risk distance-weighted ({avg:.3f} vs {r['avg_risk']})")
        # R: map data
        check(r["segments"] and all(len(s["coords"]) >= 2 for s in r["segments"]), f"{r['id']}: route geometry for map")
        check(r["via"] and r["via"] != "Unnamed roads", f"{r['id']}: route summary names roads ({r['via']})")

    # R: weather sampled at ETA — compare a few checkpoints to Open-Meteo directly
    random.seed(1)
    sample = random.sample([(r["id"], c) for r in routes for c in r["checkpoints"]], 4)
    for rid, c in sample:
        w, rn, sn = open_meteo_at(c["lat"], c["lon"], parse(c["eta"]))
        ok = abs(w - c["weather"]["wind_mph"]) < 0.6 and abs(rn - c["weather"]["rain_in_hr"]) < 0.006 and abs(sn - c["weather"]["snow_in_hr"]) < 0.006
        check(ok, f"{rid} mile {c['mile']}: weather equals Open-Meteo at ETA {c['eta']} (app {c['weather']} vs api {w:.2f},{rn},{sn})")

    # R: recommendation (independent strict ranking with the documented tolerances)
    def key(r): return (r["miles_by_level"][4], r["miles_by_level"][3], r["miles_by_level"][2], r["avg_risk"], r["elapsed_s"])
    tol = (1.0, 1.0, 1.0, 0.05, 60)
    def better(a, b):
        for x, y, t in zip(key(a), key(b), tol):
            if abs(x - y) > t: return x < y
        return False
    best = next(r for r in routes if r["id"] == plan["recommendation"]["best"])
    check(not any(better(r, best) for r in routes if r is not best), "recommended route is not beaten on (NoTravel, Severe, High, avg, time)")
    check(sum(r["recommended"] for r in routes) == 1, "exactly one route marked recommended")
    check(len(plan["recommendation"]["reasons"]) == len(routes) - 1, "a reason given vs every other route")
    for r in routes:
        print(f"  {r['id']} {r['via'][:38]:38} {r['distance_mi']:7.1f} mi drive {r['drive_s']/3600:5.2f}h total {r['elapsed_s']/3600:5.2f}h  miles/level {r['miles_by_level']} avg {r['avg_risk']:.3f}{'  <- BEST' if r['recommended'] else ''}")
    print("  reasons:", plan["recommendation"]["reasons"])

    # R: heatmap 0-48h along corridor
    st, hm = call("/api/heatmap", {"corridor": plan["corridor"], "departure": dep.isoformat(), "load_lb": load, "storm": None})
    check(st == 200, "heatmap HTTP 200")
    if st == 200:
        n = len(hm["cells"])
        check(hm["hours"] == 49 and len(hm["times"]) == 49, "heatmap has 49 hourly frames (0..48 h)")
        check(parse(hm["times"][0]) == dep and parse(hm["times"][48]) == dep + timedelta(hours=48), "heatmap frames start at departure, end +48h")
        check(all(len(hm[k]) == 49 * n for k in ("wind", "rain", "snow", "risk")), "heatmap arrays sized hours x cells")
        g = hm["grid"]
        pts = [(g["lat0"] + rr * g["dlat"], g["lon0"] + cc * g["dlon"]) for rr, cc in hm["cells"]]
        corr = plan["corridor"]
        far = max(min(hav(p, q) for q in corr[::3]) for p in pts)
        check(far < 120, f"heatmap cells stay in the trip corridor (farthest {far:.0f} mi)")
        mism = sum(1 for k in range(49 * n) if hm["wind"][k] is not None and hm["risk"][k] != brief_level(hm["wind"][k], hm["rain"][k], hm["snow"][k], load))
        check(mism == 0, f"heatmap risk matches brief rules for every cell-hour ({mism} mismatches)")
        print(f"  heatmap: {n} cells x 49 h, max wind {max(v for v in hm['wind'] if v is not None):.0f} mph, max risk {max(hm['risk'])}")

print("\n== Validation")
dep = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
base = {"origin": PLACES["Chicago, IL"], "destination": PLACES["Denver, CO"], "departure": dep, "load_lb": 40000, "interval_mi": 25}
for name, over in [("interval 15", {"interval_mi": 15}), ("past departure", {"departure": "2020-01-01T00:00:00Z"}),
                   ("departure >7 days", {"departure": (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()}),
                   ("negative load", {"load_lb": -5}), ("same origin/dest", {"destination": PLACES["Chicago, IL"]})]:
    st, _ = call("/api/plan", {**base, **over})
    check(st == 400, f"rejects {name} with 400 (got {st})")

print(f"\nRESULT: {passes} checks passed, {len(fails)} failed")
sys.exit(1 if fails else 0)
