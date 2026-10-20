"""Route options from TomTom truck routing.

TomTom routes for the actual truck: weight and size restrictions, truck
speed profiles and traffic at the departure time (see `tomtom.py`).

It can return fewer than three routes. When it does, we ask for extra
routes forced through a via point offset to either side of the
origin-destination line, and keep the ones that are genuinely different
(little overlap with routes we already have, no U-turn spur at the via
point, and not absurdly slower than the fastest route).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings

from ..geo import LatLon, PointIndex, TimedPath, haversine_mi, resample
from . import tomtom

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
    provider_duration_s: float
    summary: str  # major roads, e.g. "I 55, I 70"
    source: str  # "alternative" (TomTom's own) | "via" (forced through a via point)


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


# Turns waypoints into route options: fetch(points, alternatives) -> options.
Fetch = Callable[[list[LatLon], int], list[RouteOption]]


def _tomtom_fetch(truck: tomtom.TruckProfile, departure: datetime) -> Fetch:
    def fetch(points: list[LatLon], alternatives: int) -> list[RouteOption]:
        try:
            routes = tomtom.fetch_routes(points, alternatives, truck, departure)
        except tomtom.TomTomError as exc:
            raise RoutingError(str(exc)) from exc
        return [tomtom.to_option(r) for r in routes]

    return fetch


def get_route_options(
    origin: LatLon, dest: LatLon, load_lb: float, departure: datetime
) -> tuple[list[RouteOption], list[str], dict]:
    """Up to three distinct truck routes (fastest first), warnings, and the truck used."""
    if not settings.TOMTOM_API_KEY:
        raise RoutingError("Truck routing isn't configured: set the TOMTOM_API_KEY environment variable.")
    truck = tomtom.truck_for_load(load_lb)
    kept = _collect(origin, dest, _tomtom_fetch(truck, departure))

    warnings: list[str] = []
    if len(kept) < WANTED_ROUTES:
        warnings.append(
            f"Only {len(kept)} distinct route{'s' if len(kept) != 1 else ''} could be found for this trip."
        )
    kept.sort(key=lambda o: o.path.total_drive_s)
    return kept, warnings, {"name": "TomTom truck", "truck": truck.as_dict()}


def _collect(origin: LatLon, dest: LatLon, fetch: Fetch) -> list[RouteOption]:
    options = fetch([origin, dest], WANTED_ROUTES - 1)
    if not options:
        raise RoutingError("No drivable route found between these locations.")

    kept: list[RouteOption] = []
    for opt in options:
        if _is_distinct(opt, kept, fastest_s=options[0].path.total_drive_s):
            kept.append(opt)

    for via in _via_points(origin, dest):
        if len(kept) >= WANTED_ROUTES:
            break
        try:
            via_options = fetch([origin, via, dest], 0)
        except RoutingError as exc:
            log.warning("via route failed: %s", exc)
            continue
        if not via_options:
            continue
        opt = via_options[0]
        opt.source = "via"
        if _is_distinct(opt, kept, fastest_s=kept[0].path.total_drive_s) and not _has_spur(opt.path):
            kept.append(opt)
    return kept


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
