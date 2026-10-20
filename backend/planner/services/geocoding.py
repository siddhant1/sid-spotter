"""Place search via Photon (OpenStreetMap data, keyless, autocomplete-friendly)."""

from __future__ import annotations

import hashlib

import requests
from django.conf import settings
from django.core.cache import cache


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
        resp = requests.get(
            f"{settings.PHOTON_URL}/api/",
            params={"q": query, "limit": limit, "lang": "en"},
            timeout=10,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding service error: {exc}") from exc

    results = []
    for f in resp.json().get("features", []):
        lon, lat = f["geometry"]["coordinates"]
        label = _label(f.get("properties", {}))
        if label and label not in {r["label"] for r in results}:
            results.append({"label": label, "lat": lat, "lon": lon})
    cache.set(key, results, 24 * 3600)
    return results
