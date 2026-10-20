"""Optional simulated storm layered on top of the real forecast.

Real hazardous weather is often absent from the trip someone happens to be
testing, which leaves the risk and recommendation logic with nothing to do.
With `simulate_storm` on, a winter storm (strong wind plus snow) is centred
on the fastest route's midpoint and timed to peak as the truck gets there,
drifting east at 20 mph. Classification, load rules and ranking all run
unchanged on the modified forecast. The UI labels the weather as simulated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..geo import LatLon, haversine_mi
from .weather import Series

RADIUS_MI = 70.0
DURATION_H = 6.0  # e-folding half-width in time
DRIFT_MPH = 20.0
PEAK_WIND_MPH = 42.0  # + typical 5-10 mph base -> 45-54 mph core, where load rules decide
PEAK_GUST_MPH = 65.0
PEAK_SNOW_IN_HR = 1.5


@dataclass(frozen=True)
class Storm:
    lat: float
    lon: float
    peak_epoch: float

    def as_dict(self) -> dict:
        return {"lat": self.lat, "lon": self.lon, "peak_epoch": self.peak_epoch}

    def intensity(self, p: LatLon, t: float) -> float:
        dt_h = (t - self.peak_epoch) / 3600.0
        # Centre drifts east over time.
        center_lon = self.lon + DRIFT_MPH * dt_h / (69.172 * math.cos(math.radians(self.lat)))
        d = haversine_mi(p, (self.lat, center_lon))
        return math.exp(-((d / RADIUS_MI) ** 2)) * math.exp(-((dt_h / DURATION_H) ** 2))


def apply_storm(forecasts: dict[LatLon, Series], storm: Storm) -> dict[LatLon, Series]:
    out = {}
    for cell, s in forecasts.items():
        f = [storm.intensity(cell, s.start + h * 3600) for h in range(len(s.wind))]

        def add(values, peak):
            return [None if v is None else v + peak * k for v, k in zip(values, f)]

        out[cell] = Series(
            start=s.start,
            wind=add(s.wind, PEAK_WIND_MPH),
            gust=add(s.gust, PEAK_GUST_MPH),
            rain=list(s.rain),
            snow=add(s.snow, PEAK_SNOW_IN_HR),
        )
    return out
