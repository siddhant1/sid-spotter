import logging

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .heatmap import build_heatmap
from .planning import TripRequest, plan_trip
from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
from .services.geocoding import GeocodingError, search
from .services.routing import RoutingError
from .services.scenario import Storm
from .services.weather import WeatherError

log = logging.getLogger(__name__)

UPSTREAM_ERRORS = (RoutingError, WeatherError, GeocodingError)


def _error(message: str, code=status.HTTP_502_BAD_GATEWAY) -> Response:
    return Response({"error": message}, status=code)


@api_view(["GET"])
def health(request):
    return Response({"ok": True})


@api_view(["GET"])
def geocode(request):
    try:
        return Response({"results": search(request.query_params.get("q", ""))})
    except GeocodingError as exc:
        return _error(str(exc))


@api_view(["POST"])
def plan(request):
    s = PlanRequestSerializer(data=request.data)
    if not s.is_valid():
        return Response({"error": "Invalid request.", "fields": s.errors}, status=status.HTTP_400_BAD_REQUEST)
    d = s.validated_data
    req = TripRequest(
        origin=(d["origin"]["lat"], d["origin"]["lon"]),
        destination=(d["destination"]["lat"], d["destination"]["lon"]),
        origin_label=d["origin"]["label"],
        destination_label=d["destination"]["label"],
        departure=d["departure"],
        load_lb=d["load_lb"],
        interval_mi=int(d["interval_mi"]),
        hos=d["hos"],
        simulate_storm=d["simulate_storm"],
    )
    try:
        return Response(plan_trip(req))
    except UPSTREAM_ERRORS as exc:
        log.warning("plan failed: %s", exc)
        return _error(str(exc))


@api_view(["POST"])
def heatmap(request):
    s = HeatmapRequestSerializer(data=request.data)
    if not s.is_valid():
        return Response({"error": "Invalid request.", "fields": s.errors}, status=status.HTTP_400_BAD_REQUEST)
    d = s.validated_data
    try:
        corridor = [(p[0], p[1]) for p in d["corridor"]]
        storm = Storm(**d["storm"]) if d.get("storm") else None
        return Response(build_heatmap(corridor, d["departure"], d["load_lb"], storm))
    except UPSTREAM_ERRORS as exc:
        log.warning("heatmap failed: %s", exc)
        return _error(str(exc))


def spa(request):
    """Serve the built React app for any non-API path."""
    if not (settings.FRONTEND_DIST / "index.html").exists():
        raise Http404("Frontend not built. Run `npm run build` in frontend/ or use the Vite dev server.")
    return render(request, "index.html")
