"""Trip planning: checkpoints, ETAs, weather risk and per-route summaries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .geo import LatLon, TimedPath, elapsed_with_hos, resample, simplify
from .recommend import RouteMetrics, recommend
from .risk import RISK_LABELS, Risk, assess
from .services import routing, scenario, weather

ROUTE_NAMES = "ABC"
DISPLAY_TOLERANCE_DEG = 0.0003  # ~30 m simplification for the map


@dataclass
class TripRequest:
    origin: LatLon
    destination: LatLon
    origin_label: str
    destination_label: str
    departure: datetime  # tz-aware
    load_lb: float
    interval_mi: int
    hos: bool  # insert hours-of-service breaks into ETAs
    simulate_storm: bool = False


def checkpoint_miles(total_mi: float, interval_mi: float) -> list[float]:
    """Origin, every `interval_mi`, and the destination."""
    miles = [k * interval_mi for k in range(int(total_mi // interval_mi) + 1)]
    # Skip a final interval point that sits practically on the destination.
    if total_mi - miles[-1] < 0.5 and len(miles) > 1:
        miles.pop()
    miles.append(total_mi)
    return miles


def ownership(miles: list[float]) -> list[tuple[float, float]]:
    """Stretch of road each checkpoint represents: halfway to each neighbour."""
    bounds = [0.0] + [(a + b) / 2 for a, b in zip(miles, miles[1:])] + [miles[-1]]
    return list(zip(bounds, bounds[1:]))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed(drive_s: float, hos: bool) -> float:
    return elapsed_with_hos(drive_s) if hos else drive_s


def plan_trip(req: TripRequest) -> dict:
    options, warnings, provider = routing.get_route_options(req.origin, req.destination, req.load_lb, req.departure)

    # Lay out checkpoints first so every route's weather comes from one batch.
    layouts = []
    for opt in options:
        miles = checkpoint_miles(opt.path.total_mi, req.interval_mi)
        points = []
        for mile in miles:
            pos, drive_s = opt.path.locate(mile)
            eta = req.departure + timedelta(seconds=_elapsed(drive_s, req.hos))
            points.append((mile, pos, drive_s, eta))
        layouts.append(points)

    start = weather.floor_hour(req.departure)
    last_eta = max(p[3] for pts in layouts for p in pts)
    hours = math.ceil((last_eta - start).total_seconds() / 3600) + 2
    cells = [weather.cell_of(p[1]) for pts in layouts for p in pts]
    forecasts = weather.get_forecasts(cells, start, hours)

    storm = None
    if req.simulate_storm:
        # Centre the storm on the fastest route, peaking as the truck gets there.
        fastest = options[0].path
        pos, drive_s = fastest.locate(fastest.total_mi / 2)
        peak = req.departure + timedelta(seconds=_elapsed(drive_s, req.hos))
        storm = scenario.Storm(round(pos[0], 4), round(pos[1], 4), peak.timestamp())
        forecasts = scenario.apply_storm(forecasts, storm)

    routes = []
    metrics = []
    for idx, (opt, points) in enumerate(zip(options, layouts)):
        route, m = _build_route(ROUTE_NAMES[idx], opt, points, forecasts, req)
        routes.append(route)
        metrics.append(m)

    rec = recommend(metrics)
    for route in routes:
        route["rank"] = rec.order.index(route["id"]) + 1
        route["recommended"] = route["id"] == rec.best

    return {
        "request": {
            "origin": {"label": req.origin_label, "lat": req.origin[0], "lon": req.origin[1]},
            "destination": {"label": req.destination_label, "lat": req.destination[0], "lon": req.destination[1]},
            "departure": _iso(req.departure),
            "load_lb": req.load_lb,
            "interval_mi": req.interval_mi,
            "hos": req.hos,
            "simulate_storm": req.simulate_storm,
        },
        "storm": storm.as_dict() if storm else None,
        "provider": provider,
        "routes": routes,
        "recommendation": rec.as_dict(),
        "warnings": warnings,
        # Route shapes sampled every ~5 mi, posted back to /api/heatmap.
        "corridor": [[round(lat, 4), round(lon, 4)] for opt in options for lat, lon in resample(opt.path, 5.0)],
        "risk_levels": [{"level": int(r), "label": RISK_LABELS[r]} for r in Risk],
    }


def _build_route(name, opt: routing.RouteOption, points, forecasts, req: TripRequest):
    path: TimedPath = opt.path
    miles = [p[0] for p in points]
    spans = ownership(miles)

    checkpoints = []
    miles_by_level = [0.0] * len(Risk)
    unknown_mi = 0.0
    weighted_risk = 0.0
    for i, ((mile, pos, drive_s, eta), (lo, hi)) in enumerate(zip(points, spans)):
        series = forecasts.get(weather.cell_of(pos))
        wx = series.at(eta.timestamp()) if series else None
        complete = wx is not None and None not in (wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"])
        risk = assess(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"], req.load_lb) if complete else None
        span_mi = hi - lo
        if risk is None:
            unknown_mi += span_mi
        else:
            miles_by_level[risk.level] += span_mi
            weighted_risk += risk.level * span_mi
        checkpoints.append(
            {
                "index": i,
                "mile": round(mile, 2),
                "lat": round(pos[0], 5),
                "lon": round(pos[1], 5),
                "drive_s": round(drive_s),
                "eta": _iso(eta),
                "weather": {k: (None if v is None else round(v, 3)) for k, v in wx.items()} if wx else None,
                "risk": risk.as_dict() if risk else None,
                "span_mi": [round(lo, 2), round(hi, 2)],
            }
        )

    known_mi = path.total_mi - unknown_mi
    avg_risk = weighted_risk / known_mi if known_mi > 0 else 0.0
    elapsed_s = _elapsed(path.total_drive_s, req.hos)

    # Polyline pieces coloured by the risk of the checkpoint that owns them.
    segments = []
    for cp, (lo, hi) in zip(checkpoints, spans):
        if hi - lo <= 0:
            continue
        coords = simplify(path.slice(lo, hi), DISPLAY_TOLERANCE_DEG)
        level = cp["risk"]["level"] if cp["risk"] else None
        if segments and segments[-1]["level"] == level:
            segments[-1]["coords"].extend([round(a, 5), round(b, 5)] for a, b in coords[1:])
        else:
            segments.append({"level": level, "coords": [[round(a, 5), round(b, 5)] for a, b in coords]})

    worst = max((cp["risk"]["level"] for cp in checkpoints if cp["risk"]), default=None)
    route = {
        "id": name,
        "name": f"Route {name}",
        "via": opt.summary or "Unnamed roads",
        "source": opt.source,
        "distance_mi": round(path.total_mi, 1),
        "drive_s": round(path.total_drive_s),
        "elapsed_s": round(elapsed_s),
        "arrival": _iso(req.departure + timedelta(seconds=elapsed_s)),
        "miles_by_level": [round(m, 1) for m in miles_by_level],
        "unknown_mi": round(unknown_mi, 1),
        "avg_risk": round(avg_risk, 3),
        "max_level": worst,
        "checkpoints": checkpoints,
        "segments": segments,
        "bounds": [
            [min(c[0] for c in path.coords), min(c[1] for c in path.coords)],
            [max(c[0] for c in path.coords), max(c[1] for c in path.coords)],
        ],
    }
    metrics = RouteMetrics(
        id=name,
        no_travel_mi=miles_by_level[Risk.NO_TRAVEL],
        severe_mi=miles_by_level[Risk.SEVERE],
        high_mi=miles_by_level[Risk.HIGH],
        avg_risk=avg_risk,
        elapsed_s=elapsed_s,
    )
    return route, metrics
