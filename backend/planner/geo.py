"""Geometry helpers: distances, walking a polyline, simplification."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


@dataclass
class TimedPath:
    """A polyline with cumulative distance (mi) and driving time (s) at each vertex."""

    coords: list[LatLon]
    cum_mi: list[float]
    cum_drive_s: list[float]

    @property
    def total_mi(self) -> float:
        return self.cum_mi[-1]

    @property
    def total_drive_s(self) -> float:
        return self.cum_drive_s[-1]

    def locate(self, mile: float) -> tuple[LatLon, float]:
        """Position and cumulative driving seconds at `mile` along the path."""
        mile = min(max(mile, 0.0), self.total_mi)
        i = bisect_right(self.cum_mi, mile) - 1
        if i >= len(self.coords) - 1:
            return self.coords[-1], self.cum_drive_s[-1]
        span = self.cum_mi[i + 1] - self.cum_mi[i]
        f = 0.0 if span == 0 else (mile - self.cum_mi[i]) / span
        (la1, lo1), (la2, lo2) = self.coords[i], self.coords[i + 1]
        pos = (la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f)
        t = self.cum_drive_s[i] + (self.cum_drive_s[i + 1] - self.cum_drive_s[i]) * f
        return pos, t

    def slice(self, start_mi: float, end_mi: float) -> list[LatLon]:
        """Sub-polyline between two mileposts (inclusive, interpolated ends)."""
        a, _ = self.locate(start_mi)
        b, _ = self.locate(end_mi)
        i = bisect_right(self.cum_mi, start_mi)
        j = bisect_right(self.cum_mi, end_mi)
        inner = [c for c in self.coords[i:j] if c != a and c != b]
        return [a, *inner, b]


def build_timed_path(
    coords: list[LatLon],
    seg_durations_s: list[float] | None,
    total_duration_s: float,
    max_speed_mph: float,
) -> TimedPath:
    """Attach truck driving times to a route polyline.

    Segment durations come from the router when it provides one per segment;
    otherwise the route's total duration is spread evenly by distance. Each
    segment is then slowed to at most `max_speed_mph` (car profile -> truck).
    """
    seg_mi = [haversine_mi(coords[k], coords[k + 1]) for k in range(len(coords) - 1)]
    total_mi = sum(seg_mi)
    if not seg_durations_s or len(seg_durations_s) != len(seg_mi):
        rate = total_duration_s / total_mi if total_mi else 0.0
        seg_durations_s = [d * rate for d in seg_mi]

    min_s_per_mi = 3600.0 / max_speed_mph
    cum_mi, cum_s = [0.0], [0.0]
    for d, t in zip(seg_mi, seg_durations_s):
        cum_mi.append(cum_mi[-1] + d)
        cum_s.append(cum_s[-1] + max(t, d * min_s_per_mi))
    return TimedPath(coords, cum_mi, cum_s)


# --- Hours of service --------------------------------------------------------
# Simplified FMCSA property-carrying rules: a 30-minute break once 8 hours have
# been driven since the last break, and a 10-hour off-duty rest after 11 hours
# of driving. The 14-hour on-duty window is not modelled.
HOS_DRIVE_LIMIT_S = 11 * 3600
HOS_BREAK_AFTER_S = 8 * 3600
HOS_BREAK_S = 30 * 60
HOS_REST_S = 10 * 3600


def elapsed_with_hos(drive_s: float) -> float:
    """Wall-clock seconds needed to accumulate `drive_s` of driving time."""
    if drive_s <= 0:
        return 0.0
    full_shifts = math.ceil(drive_s / HOS_DRIVE_LIMIT_S) - 1  # rests taken before this point
    in_shift = drive_s - full_shifts * HOS_DRIVE_LIMIT_S
    breaks = full_shifts + (1 if in_shift > HOS_BREAK_AFTER_S else 0)
    return drive_s + full_shifts * HOS_REST_S + breaks * HOS_BREAK_S


# --- Simplification ----------------------------------------------------------


def simplify(coords: list[LatLon], tolerance_deg: float) -> list[LatLon]:
    """Iterative Ramer-Douglas-Peucker in lat/lon degrees."""
    n = len(coords)
    if n <= 2:
        return list(coords)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_deg * tolerance_deg
    while stack:
        s, e = stack.pop()
        (y1, x1), (y2, x2) = coords[s], coords[e]
        dx, dy = x2 - x1, y2 - y1
        seg2 = dx * dx + dy * dy
        best, best_i = -1.0, -1
        for i in range(s + 1, e):
            y, x = coords[i]
            if seg2 == 0:
                d2 = (x - x1) ** 2 + (y - y1) ** 2
            else:
                u = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / seg2))
                d2 = (x - x1 - u * dx) ** 2 + (y - y1 - u * dy) ** 2
            if d2 > best:
                best, best_i = d2, i
        if best > tol2:
            keep[best_i] = True
            stack.append((s, best_i))
            stack.append((best_i, e))
    return [c for c, k in zip(coords, keep) if k]


def resample(path: TimedPath, step_mi: float) -> list[LatLon]:
    """Points every `step_mi` along the path (always includes both ends)."""
    n = max(1, int(path.total_mi // step_mi))
    pts = [path.locate(k * step_mi)[0] for k in range(n + 1)]
    if path.total_mi - n * step_mi > 1e-6:
        pts.append(path.coords[-1])
    return pts


class PointIndex:
    """Bucketed point set for fast 'is anything within r miles?' queries."""

    def __init__(self, points: list[LatLon], cell_deg: float):
        self.cell = cell_deg
        self.buckets: dict[tuple[int, int], list[LatLon]] = {}
        for p in points:
            self.buckets.setdefault(self._key(p), []).append(p)

    def _key(self, p: LatLon) -> tuple[int, int]:
        return int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell))

    def nearest_mi(self, p: LatLon, rings: int = 1) -> float:
        ki, kj = self._key(p)
        best = math.inf
        for di in range(-rings, rings + 1):
            for dj in range(-rings, rings + 1):
                for q in self.buckets.get((ki + di, kj + dj), ()):
                    best = min(best, haversine_mi(p, q))
        return best
