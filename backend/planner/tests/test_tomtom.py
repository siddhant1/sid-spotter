from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from planner.services import routing, tomtom

# Shaped like the documented calculateRoute response (two legs via a waypoint).
ROUTE = {
    "summary": {"lengthInMeters": 300000, "travelTimeInSeconds": 12000},
    "legs": [
        {"points": [{"latitude": 40.0, "longitude": -90.0}, {"latitude": 40.5, "longitude": -90.0}, {"latitude": 41.0, "longitude": -90.0}]},
        {"points": [{"latitude": 41.0, "longitude": -90.0}, {"latitude": 42.0, "longitude": -90.0}]},
    ],
    # Sparse progress: only some point indexes carry a time.
    "progress": [
        {"pointIndex": 0, "travelTimeInSeconds": 0, "distanceInMeters": 0},
        {"pointIndex": 2, "travelTimeInSeconds": 4000, "distanceInMeters": 111000},
        {"pointIndex": 3, "travelTimeInSeconds": 12000, "distanceInMeters": 222000},
    ],
    "sections": [
        {"sectionType": "IMPORTANT_ROAD_STRETCH", "startPointIndex": 0, "endPointIndex": 2, "roadNumbers": [{"text": "I-39"}]},
        {"sectionType": "IMPORTANT_ROAD_STRETCH", "startPointIndex": 2, "endPointIndex": 3, "roadNumbers": [{"text": "US-51"}, {"text": "I-39"}]},
        {"sectionType": "TRAVEL_MODE", "startPointIndex": 0, "endPointIndex": 3},
    ],
}


def test_legs_are_joined_without_duplicating_the_via_point():
    path = tomtom.to_timed_path(ROUTE)
    assert len(path.coords) == 4
    assert path.coords[2] == (41.0, -90.0)


def test_travel_time_comes_from_progress_and_is_interpolated_by_distance():
    path = tomtom.to_timed_path(ROUTE)
    assert path.cum_drive_s[2] == 4000
    assert path.cum_drive_s[3] == 12000
    assert path.cum_drive_s[1] == pytest.approx(2000, rel=0.01)  # halfway between index 0 and 2
    _, t = path.locate(path.total_mi * 0.75)
    assert 4000 < t < 12000


def test_road_summary_ranks_by_distance_in_driving_order():
    path = tomtom.to_timed_path(ROUTE)
    assert tomtom.road_summary(ROUTE, path) == "I-39, US-51"


def test_truck_profile_is_gross_weight():
    with override_settings(TRUCK_TARE_LB=35000):
        assert tomtom.truck_for_load(42000).gross_lb == 77000


@override_settings(TOMTOM_API_KEY="test-key")
def test_request_sends_truck_parameters():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"routes": [ROUTE]}
    truck = tomtom.TruckProfile(gross_lb=77000, height_ft=13.5, length_ft=72, width_ft=8.5, max_speed_mph=65)
    dep = datetime.now(timezone.utc) + timedelta(hours=3)
    with patch.object(tomtom.requests, "get", return_value=resp) as get:
        tomtom.fetch_routes([(40, -90), (42, -90)], 2, truck, dep)
    params = dict(get.call_args.kwargs["params"])
    assert params["travelMode"] == "truck"
    assert params["vehicleWeight"] == str(round(77000 / 2.20462))  # kg
    assert params["vehicleHeight"] == "4.11"  # 13'6" in metres
    assert params["vehicleMaxSpeed"] == "105"  # 65 mph in km/h
    assert params["maxAlternatives"] == "2"
    assert "departAt" in params
    reps = [v for k, v in get.call_args.kwargs["params"] if k == "extendedRouteRepresentation"]
    assert set(reps) == {"distance", "travelTime"}


@override_settings(TOMTOM_API_KEY="")
def test_missing_key_is_a_clear_error():
    with patch.object(tomtom, "fetch_routes") as tt, pytest.raises(routing.RoutingError, match="TOMTOM_API_KEY"):
        routing.get_route_options((40, -90), (42, -90), 42000, datetime.now(timezone.utc))
    assert not tt.called


@override_settings(TOMTOM_API_KEY="test-key")
def test_tomtom_errors_surface_as_routing_errors():
    with (
        patch.object(tomtom, "fetch_routes", side_effect=tomtom.TomTomError("Forbidden")),
        pytest.raises(routing.RoutingError, match="Forbidden"),
    ):
        routing.get_route_options((40, -90), (42, -90), 42000, datetime.now(timezone.utc))


@override_settings(TOMTOM_API_KEY="test-key")
def test_tops_up_to_three_routes_with_via_points():
    main = tomtom.to_option(ROUTE)
    alt_route = {**ROUTE, "legs": [{"points": [{"latitude": 40.0, "longitude": -90.0}, {"latitude": 41.0, "longitude": -89.0}, {"latitude": 42.0, "longitude": -90.0}]}], "progress": [], "sections": []}
    calls = []

    def fake_fetch(points, alternatives, truck, departure):
        calls.append((len(points), alternatives))
        return [ROUTE] if len(points) == 2 else [alt_route]

    with patch.object(tomtom, "fetch_routes", side_effect=fake_fetch), patch.object(routing, "_is_distinct", return_value=True), patch.object(routing, "_has_spur", return_value=False):
        options, warnings, info = routing.get_route_options((40, -90), (42, -90), 42000, datetime.now(timezone.utc))
    assert len(options) == 3 and not warnings
    assert calls[0] == (2, 2)  # first ask TomTom for 2 alternatives
    assert sum(o.source == "via" for o in options) == 2
    assert info["truck"]["gross_lb"] == 77000
    assert main.summary == "I-39, US-51"
