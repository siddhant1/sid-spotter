"""Forecast grid over the trip corridor for the 0-48 h heatmap.

The grid covers the routes' bounding box with roughly square cells and keeps
only cells within reach of a route, so the request stays small and the map
shows weather where the truck could actually be.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .geo import LatLon, PointIndex
from .risk import assess
from .services import scenario, weather

HOURS = 49  # 0..48 inclusive
TARGET_CELLS_ACROSS = 26
MIN_STEP_DEG = 0.15
MAX_CELLS = 260  # bounded by the weather API's free-tier per-minute quota


def build_grid(corridor: list[LatLon]) -> dict:
    lats = [p[0] for p in corridor]
    lons = [p[1] for p in corridor]
    mid_lat = (min(lats) + max(lats)) / 2
    coslat = max(0.2, math.cos(math.radians(mid_lat)))
    span = max(max(lats) - min(lats), (max(lons) - min(lons)) * coslat, 0.5)
    step = max(MIN_STEP_DEG, span / TARGET_CELLS_ACROSS)
    index = PointIndex(corridor, cell_deg=1.0)

    while True:
        dlat, dlon = step, step / coslat
        pad = 2 * step
        lat0, lon0 = min(lats) - pad, min(lons) - pad / coslat
        rows = math.ceil((max(lats) + pad - lat0) / dlat) + 1
        cols = math.ceil((max(lons) + pad / coslat - lon0) / dlon) + 1
        radius_mi = max(40.0, 2.0 * step * 69.0)
        rings = math.ceil(radius_mi / (69.0 * coslat)) + 1
        cells = [
            (r, c)
            for r in range(rows)
            for c in range(cols)
            if index.nearest_mi((lat0 + r * dlat, lon0 + c * dlon), rings=rings) <= radius_mi
        ]
        if len(cells) <= MAX_CELLS:
            break
        step *= 1.2

    return {"lat0": lat0, "lon0": lon0, "dlat": dlat, "dlon": dlon, "rows": rows, "cols": cols, "cells": cells}


def build_heatmap(
    corridor: list[LatLon], departure: datetime, load_lb: float, storm: scenario.Storm | None = None
) -> dict:
    grid = build_grid(corridor)
    points = [(grid["lat0"] + r * grid["dlat"], grid["lon0"] + c * grid["dlon"]) for r, c in grid["cells"]]
    start = weather.floor_hour(departure)
    # +1 hour: precipitation at hour h is read from the bucket ending at h+1.
    forecasts = weather.get_forecasts([weather.cell_of(p) for p in points], start, HOURS + 1)
    if storm:
        forecasts = scenario.apply_storm(forecasts, storm)

    n = len(points)
    wind = [None] * (HOURS * n)
    gust = [None] * (HOURS * n)
    rain = [None] * (HOURS * n)
    snow = [None] * (HOURS * n)
    risk = [-1] * (HOURS * n)
    for i, p in enumerate(points):
        series = forecasts.get(weather.cell_of(p))
        if series is None:
            continue
        for h in range(HOURS):
            wx = series.at(start.timestamp() + h * 3600)
            k = h * n + i
            wind[k] = _r(wx["wind_mph"], 1)
            gust[k] = _r(wx["gust_mph"], 1)
            rain[k] = _r(wx["rain_in_hr"], 3)
            snow[k] = _r(wx["snow_in_hr"], 3)
            if None not in (wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"]):
                risk[k] = int(assess(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"], load_lb).level)

    return {
        "grid": {k: grid[k] for k in ("lat0", "lon0", "dlat", "dlon", "rows", "cols")},
        "cells": grid["cells"],
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "hours": HOURS,
        "times": [
            (start + timedelta(hours=h)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            for h in range(HOURS)
        ],
        # Flat, hour-major arrays: value for cell i at hour h is at h * len(cells) + i.
        "wind": wind,
        "gust": gust,
        "rain": rain,
        "snow": snow,
        "risk": risk,
    }


def _r(v: float | None, nd: int) -> float | None:
    return None if v is None else round(v, nd)
