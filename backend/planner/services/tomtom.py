"""TomTom Routing API in truck mode.

TomTom routes for the actual vehicle: it
avoids roads with weight, height, length or width limits the truck exceeds,
and its travel times come from truck speed profiles plus historic traffic
for the departure time. Per-point travel times come back in `progress`
(`extendedRouteRepresentation=travelTime`), so checkpoint ETAs need no
car-to-truck speed adjustment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import requests
from django.conf import settings

from ..geo import LatLon, TimedPath, haversine_mi

if TYPE_CHECKING:
    from .routing import RouteOption

LB_PER_KG = 2.20462
M_PER_FT = 0.3048
KMH_PER_MPH = 1.609344


@dataclass(frozen=True)
class TruckProfile:
    gross_lb: float
    height_ft: float
    length_ft: float
    width_ft: float
    max_speed_mph: float

    def as_dict(self) -> dict:
        return {
            "gross_lb": round(self.gross_lb),
            "height_ft": self.height_ft,
            "length_ft": self.length_ft,
            "width_ft": self.width_ft,
            "max_speed_mph": self.max_speed_mph,
        }


def truck_for_load(load_lb: float) -> TruckProfile:
    """Gross weight = empty tractor-trailer + cargo; US standard dimensions."""
    return TruckProfile(
        gross_lb=settings.TRUCK_TARE_LB + load_lb,
        height_ft=settings.TRUCK_HEIGHT_FT,
        length_ft=settings.TRUCK_LENGTH_FT,
        width_ft=settings.TRUCK_WIDTH_FT,
        max_speed_mph=settings.TRUCK_MAX_SPEED_MPH,
    )


class TomTomError(Exception):
    pass


def fetch_routes(points: list[LatLon], alternatives: int, truck: TruckProfile, departure: datetime) -> list[dict]:
    loc = ":".join(f"{lat:.6f},{lon:.6f}" for lat, lon in points)
    params = [
        ("key", settings.TOMTOM_API_KEY),
        ("travelMode", "truck"),
        ("vehicleCommercial", "true"),
        ("vehicleWeight", str(round(truck.gross_lb / LB_PER_KG))),
        ("vehicleHeight", f"{truck.height_ft * M_PER_FT:.2f}"),
        ("vehicleLength", f"{truck.length_ft * M_PER_FT:.2f}"),
        ("vehicleWidth", f"{truck.width_ft * M_PER_FT:.2f}"),
        ("vehicleMaxSpeed", str(round(truck.max_speed_mph * KMH_PER_MPH))),
        ("routeType", "fastest"),
        ("traffic", "true"),
        ("maxAlternatives", str(alternatives)),
        ("routeRepresentation", "polyline"),
        ("extendedRouteRepresentation", "distance"),
        ("extendedRouteRepresentation", "travelTime"),
        ("sectionType", "importantRoadStretch"),
    ]
    # TomTom rejects departure times in the past; "now" covers the grace hour we allow.
    if departure > datetime.now(timezone.utc) + timedelta(minutes=1):
        params.append(("departAt", departure.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    try:
        resp = requests.get(
            f"{settings.TOMTOM_URL}/routing/1/calculateRoute/{loc}/json",
            params=params,
            timeout=25,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
        )
    except requests.RequestException as exc:
        raise TomTomError(f"TomTom unreachable: {exc}") from exc
    if resp.status_code == 400 and "NO_ROUTE_FOUND" in resp.text.upper().replace(" ", "_"):
        return []
    if resp.status_code != 200:
        try:
            msg = resp.json().get("detailedError", {}).get("message")
        except ValueError:
            msg = None  # auth/quota errors come back as XML
        raise TomTomError(msg or f"TomTom error (HTTP {resp.status_code})")
    return resp.json().get("routes", [])


def to_timed_path(route: dict) -> TimedPath:
    """Polyline with TomTom's own cumulative truck travel time at every point."""
    coords: list[LatLon] = []
    for leg in route["legs"]:
        pts = [(p["latitude"], p["longitude"]) for p in leg["points"]]
        # Consecutive legs share the via point; don't duplicate it.
        coords.extend(pts[1:] if coords and pts and pts[0] == coords[-1] else pts)

    cum_mi = [0.0]
    for a, b in zip(coords, coords[1:]):
        cum_mi.append(cum_mi[-1] + haversine_mi(a, b))

    total_s = float(route["summary"]["travelTimeInSeconds"])
    # progress gives travel time at (some or all) point indexes; interpolate by distance between them.
    known = sorted(
        (min(p["pointIndex"], len(coords) - 1), float(p["travelTimeInSeconds"]))
        for p in route.get("progress", [])
        if "pointIndex" in p and "travelTimeInSeconds" in p
    )
    if not known or known[0][0] != 0:
        known.insert(0, (0, 0.0))
    if known[-1][0] != len(coords) - 1:
        known.append((len(coords) - 1, total_s))

    cum_s = [0.0] * len(coords)
    for (i0, t0), (i1, t1) in zip(known, known[1:]):
        span = cum_mi[i1] - cum_mi[i0]
        for k in range(i0, i1 + 1):
            f = (cum_mi[k] - cum_mi[i0]) / span if span else 0.0
            cum_s[k] = t0 + (t1 - t0) * f
    return TimedPath(coords, cum_mi, cum_s)


def road_summary(route: dict, path: TimedPath, top: int = 3) -> str:
    """Main road numbers by distance driven on them, in driving order."""
    miles: dict[str, float] = {}
    first: dict[str, int] = {}
    last = len(path.coords) - 1
    for sec in route.get("sections", []):
        if sec.get("sectionType") != "IMPORTANT_ROAD_STRETCH":
            continue
        a, b = min(sec.get("startPointIndex", 0), last), min(sec.get("endPointIndex", 0), last)
        length = path.cum_mi[b] - path.cum_mi[a]
        for rn in sec.get("roadNumbers", []):
            name = rn.get("text") if isinstance(rn, dict) else str(rn)
            name = re.sub(r"\s+[NSEW]B?$", "", name or "")  # "I-80 W" -> "I-80"
            if name:
                miles[name] = miles.get(name, 0.0) + length
                first.setdefault(name, a)
    best = sorted(miles, key=miles.get, reverse=True)[:top]
    return ", ".join(sorted(best, key=first.get))


def to_option(route: dict, source: str = "alternative") -> RouteOption:
    from .routing import RouteOption

    path = to_timed_path(route)
    return RouteOption(path, float(route["summary"]["travelTimeInSeconds"]), road_summary(route, path), source)
