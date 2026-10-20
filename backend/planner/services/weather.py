"""Hourly forecasts from Open-Meteo, batched and cached.

Points are snapped to a 0.1° cell (~7 mi), which is finer than the
forecast models' own grids, so nearby checkpoints share one forecast.
Open-Meteo accepts many locations per request; we send up to 100 at a time.

Reading a value at an arbitrary time:

* wind speed / gusts are instantaneous -> linear interpolation between hours.
* rain / snowfall are "sum over the preceding hour" -> we use the bucket that
  covers the hour starting at the requested time, i.e. the hour the truck
  is about to drive through.
"""

from __future__ import annotations

import hashlib
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache

from ..geo import LatLon

log = logging.getLogger(__name__)

CELL_DEG = 0.1
BATCH_SIZE = 100
VARIABLES = ("wind_speed_10m", "wind_gusts_10m", "rain", "snowfall")


class WeatherError(Exception):
    pass


def cell_of(p: LatLon, cell_deg: float = CELL_DEG) -> LatLon:
    return (round(round(p[0] / cell_deg) * cell_deg, 4), round(round(p[1] / cell_deg) * cell_deg, 4))


@dataclass
class Series:
    """Hourly series starting at `start` (UTC epoch seconds, on the hour)."""

    start: int
    wind: list[float | None]
    gust: list[float | None]
    rain: list[float | None]
    snow: list[float | None]

    def _hour_offset(self, t: float) -> float:
        return (t - self.start) / 3600.0

    def _interp(self, values: list[float | None], t: float) -> float | None:
        h = self._hour_offset(t)
        i = math.floor(h)
        if i < 0 or i >= len(values):
            return None
        a = values[i]
        if i + 1 >= len(values) or h == i:
            return a
        b = values[i + 1]
        if a is None or b is None:
            return a if b is None else b
        return a + (b - a) * (h - i)

    def _bucket(self, values: list[float | None], t: float) -> float | None:
        i = math.floor(self._hour_offset(t)) + 1  # sum over (t_hour, t_hour + 1h]
        if 0 <= i < len(values):
            return values[i]
        return None

    def at(self, t: float) -> dict[str, float | None]:
        return {
            "wind_mph": self._interp(self.wind, t),
            "gust_mph": self._interp(self.gust, t),
            "rain_in_hr": self._bucket(self.rain, t),
            "snow_in_hr": self._bucket(self.snow, t),
        }


def floor_hour(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _cache_key(cell: LatLon, start: datetime, hours: int) -> str:
    raw = f"om:{cell[0]:.4f},{cell[1]:.4f}:{start:%Y%m%d%H}:{hours}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _fetch_batch(cells: list[LatLon], start: datetime, hours: int) -> list[Series]:
    end = start + timedelta(hours=hours - 1)
    params = {
        "latitude": ",".join(f"{c[0]:.4f}" for c in cells),
        "longitude": ",".join(f"{c[1]:.4f}" for c in cells),
        "hourly": ",".join(VARIABLES),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",  # also converts snowfall to inches
        "timezone": "GMT",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }
    if settings.OPEN_METEO_API_KEY:
        params["apikey"] = settings.OPEN_METEO_API_KEY
    try:
        resp = requests.get(
            settings.OPEN_METEO_URL, params=params, timeout=30, headers={"User-Agent": settings.HTTP_USER_AGENT}
        )
    except requests.RequestException as exc:
        raise WeatherError(f"Weather service unreachable: {exc}") from exc
    if resp.status_code != 200:
        try:
            reason = resp.json().get("reason")
        except ValueError:
            reason = None
        raise WeatherError(reason or f"Weather service error (HTTP {resp.status_code})")
    data = resp.json()
    items = data if isinstance(data, list) else [data]
    if len(items) != len(cells):
        raise WeatherError("Weather service returned an unexpected number of locations.")

    start_epoch = int(start.timestamp())
    out = []
    for item in items:
        hourly = item["hourly"]
        first = datetime.fromisoformat(hourly["time"][0]).replace(tzinfo=timezone.utc)
        if int(first.timestamp()) != start_epoch:
            raise WeatherError("Weather service returned an unexpected time range.")
        out.append(
            Series(
                start=start_epoch,
                wind=hourly["wind_speed_10m"],
                gust=hourly["wind_gusts_10m"],
                rain=hourly["rain"],
                snow=hourly["snowfall"],
            )
        )
    return out


def get_forecasts(cells: list[LatLon], start: datetime, hours: int) -> dict[LatLon, Series]:
    """Hourly series for each cell, covering [start, start + hours)."""
    start = floor_hour(start)
    unique = list(dict.fromkeys(cells))
    result: dict[LatLon, Series] = {}
    missing: list[LatLon] = []
    cached = cache.get_many([_cache_key(c, start, hours) for c in unique])
    for c in unique:
        s = cached.get(_cache_key(c, start, hours))
        if s is None:
            missing.append(c)
        else:
            result[c] = s

    batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    if batches:
        log.info("open-meteo: %d cells cached, fetching %d in %d batches", len(result), len(missing), len(batches))
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch, series in zip(batches, pool.map(lambda b: _fetch_batch(b, start, hours), batches)):
                fresh = dict(zip(batch, series))
                result.update(fresh)
                cache.set_many({_cache_key(c, start, hours): s for c, s in fresh.items()})
    return result
