"""Route options from OSRM.

OSRM's `alternatives` often returns fewer than three routes. When it does, we
ask for extra routes forced through a via point offset to either side of the
origin-destination line, and keep the ones that are genuinely different
(little overlap with routes we already have, no U-turn spur at the via
point, and not absurdly slower than the fastest route).
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass

import requests
from django.conf import settings

from ..geo import LatLon, PointIndex, TimedPath, build_timed_path, haversine_mi, resample

log = logging.getLogger(__name__)

WANTED_ROUTES = 3
MAX_DETOUR_RATIO = 1.6  # reject alternatives slower than 1.6x the fastest
MAX_OVERLAP = 0.75  # reject alternatives sharing >75% of their length with a kept route
OVERLAP_RADIUS_MI = 1.0


class RoutingError(Exception):
    pass


@dataclass
class RouteOption:
    path: TimedPath
    osrm_duration_s: float
    summary: str  # major roads, e.g. "I 55, I 70"
    source: str  # "osrm" | "via"


def _osrm_route(points: list[LatLon], alternatives: int = 0) -> list[dict]:
    coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "duration",
        "steps": "true",  # needed for the leg summary (major road names)
        "alternatives": str(alternatives) if alternatives else "false",
    }
    try:
        resp = requests.get(
            f"{settings.OSRM_URL}/route/v1/driving/{coord_str}",
            params=params,
            timeout=20,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
        )
    except requests.RequestException as exc:
        raise RoutingError(f"Routing service unreachable: {exc}") from exc
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if data.get("code") == "NoRoute":
        return []
    if resp.status_code != 200 or data.get("code") != "Ok":
        raise RoutingError(data.get("message") or f"Routing service error (HTTP {resp.status_code})")
    return data["routes"]


def _to_option(route: dict, source: str) -> RouteOption:
    coords = [(lat, lon) for lon, lat in route["geometry"]["coordinates"]]
    seg_durations: list[float] = []
    for leg in route["legs"]:
        seg_durations.extend(leg.get("annotation", {}).get("duration", []))
    path = build_timed_path(coords, seg_durations, route["duration"], settings.TRUCK_MAX_SPEED_MPH)
    # OSRM separates road names with "," or ";", and via routes have two legs
    # that can repeat the same road, so split, dedupe and rejoin.
    names = (n.strip() for leg in route["legs"] for n in re.split(r"[,;]", leg.get("summary", "")))
    summary = ", ".join(dict.fromkeys(n for n in names if n))
    return RouteOption(path, route["duration"], summary, source)


def _overlap(candidate: list[LatLon], index: PointIndex) -> float:
    near = sum(1 for p in candidate if index.nearest_mi(p) <= OVERLAP_RADIUS_MI)
    return near / len(candidate)


def _has_spur(path: TimedPath) -> bool:
    """Detect a U-turn: the route revisiting a spot it drove >3 mi earlier."""
    pts = resample(path, 0.5)
    cell = 0.01  # ~0.7 mi buckets
    grid: dict[tuple[int, int], list[int]] = {}
    hits = 0
    for i, p in enumerate(pts):
        ki, kj = int(p[0] // cell), int(p[1] // cell)
        revisit = any(
            i - j > 6 and haversine_mi(p, pts[j]) < 0.15  # >3 mi earlier along the route
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
            for j in grid.get((ki + di, kj + dj), ())
        )
        hits += revisit
        grid.setdefault((ki, kj), []).append(i)
    return hits / len(pts) > 0.02


def _via_points(origin: LatLon, dest: LatLon) -> list[LatLon]:
    """Points offset perpendicular to the straight line, alternating sides."""
    lat0 = math.radians((origin[0] + dest[0]) / 2)
    # Local equirectangular frame (x east, y north) in miles.
    dx = (dest[1] - origin[1]) * 69.172 * math.cos(lat0)
    dy = (dest[0] - origin[0]) * 69.0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length  # unit normal
    vias = []
    for frac, offset in ((0.5, 0.15), (0.5, -0.15), (0.5, 0.3), (0.5, -0.3), (0.35, 0.2), (0.65, -0.2)):
        mx, my = dx * frac + nx * offset * length, dy * frac + ny * offset * length
        vias.append((origin[0] + my / 69.0, origin[1] + mx / (69.172 * math.cos(lat0))))
    return vias


def get_route_options(origin: LatLon, dest: LatLon) -> tuple[list[RouteOption], list[str]]:
    """Up to three distinct route options, fastest first, plus warnings."""
    warnings: list[str] = []
    routes = _osrm_route([origin, dest], alternatives=WANTED_ROUTES)
    if not routes:
        raise RoutingError("No drivable route found between these locations.")

    options = [_to_option(r, "osrm") for r in routes]
    kept: list[RouteOption] = []
    for opt in options:
        if _is_distinct(opt, kept, fastest_s=options[0].path.total_drive_s):
            kept.append(opt)

    if len(kept) < WANTED_ROUTES:
        for via in _via_points(origin, dest):
            if len(kept) >= WANTED_ROUTES:
                break
            try:
                via_routes = _osrm_route([origin, via, dest])
            except RoutingError as exc:
                log.warning("via route failed: %s", exc)
                continue
            if not via_routes:
                continue
            opt = _to_option(via_routes[0], "via")
            if _is_distinct(opt, kept, fastest_s=kept[0].path.total_drive_s) and not _has_spur(opt.path):
                kept.append(opt)

    if len(kept) < WANTED_ROUTES:
        warnings.append(
            f"Only {len(kept)} distinct route{'s' if len(kept) != 1 else ''} could be found for this trip."
        )
    kept.sort(key=lambda o: o.path.total_drive_s)
    return kept, warnings


def _is_distinct(opt: RouteOption, kept: list[RouteOption], fastest_s: float) -> bool:
    if opt.path.total_drive_s > fastest_s * MAX_DETOUR_RATIO:
        return False
    if not kept:
        return True
    pts = resample(opt.path, 1.0)
    for other in kept:
        index = PointIndex(resample(other.path, 0.5), cell_deg=0.05)
        if _overlap(pts, index) > MAX_OVERLAP:
            return False
    return True
