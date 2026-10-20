"""Place search via Photon (OpenStreetMap data, keyless, autocomplete-friendly).

The public Photon server rate-limits bursts, so requests are retried with a
short backoff and fall back to Nominatim (same OSM data) if Photon stays down.
"""

from __future__ import annotations

import hashlib
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache


log = logging.getLogger(__name__)
RETRY_DELAYS_S = (0.5, 1.5)


class GeocodingError(Exception):
    pass


def _label(props: dict) -> str:
    name = props.get("name") or props.get("street") or ""
    if props.get("housenumber") and props.get("street"):
        name = f"{props['housenumber']} {props['street']}"
    parts = [name, props.get("city") if props.get("city") != name else None, props.get("state"), props.get("country")]
    return ", ".join(dict.fromkeys(p for p in parts if p))


def search(query: str, limit: int = 6) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    key = "geo:" + hashlib.sha1(f"{query.lower()}:{limit}".encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        results = _photon(query, limit)
    except requests.RequestException as exc:
        log.warning("photon failed (%s), falling back to nominatim", exc)
        try:
            results = _nominatim(query, limit)
        except requests.RequestException as exc2:
            raise GeocodingError(f"Geocoding service unavailable: {exc2}") from exc2
    cache.set(key, results, 24 * 3600)
    return results


def _get(url: str, params: dict) -> requests.Response:
    """GET with retries on network errors, 429 and 5xx."""
    for attempt, delay in enumerate((*RETRY_DELAYS_S, None)):
        try:
            resp = requests.get(url, params=params, timeout=10, headers={"User-Agent": settings.HTTP_USER_AGENT})
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            retryable = status is None or status == 429 or status >= 500
            if delay is None or not retryable:
                raise
            log.info("geocoder %s attempt %d failed: %s", url, attempt + 1, exc)
            time.sleep(delay)
    raise AssertionError("unreachable")


def _photon(query: str, limit: int) -> list[dict]:
    resp = _get(f"{settings.PHOTON_URL}/api/", {"q": query, "limit": limit, "lang": "en"})
    results = []
    for f in resp.json().get("features", []):
        lon, lat = f["geometry"]["coordinates"]
        label = _label(f.get("properties", {}))
        if label and label not in {r["label"] for r in results}:
            results.append({"label": label, "lat": lat, "lon": lon})
    return results


def _nominatim(query: str, limit: int) -> list[dict]:
    resp = _get(f"{settings.NOMINATIM_URL}/search", {"q": query, "format": "jsonv2", "limit": limit})
    return [{"label": r["display_name"], "lat": float(r["lat"]), "lon": float(r["lon"])} for r in resp.json()]
