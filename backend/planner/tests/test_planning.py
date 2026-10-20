from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from planner import planning
from planner.geo import build_timed_path, elapsed_with_hos, haversine_mi, simplify
from planner.planning import TripRequest, checkpoint_miles, ownership, plan_trip
from planner.services.routing import RouteOption
from planner.services.weather import Series

H = 3600


class TestCheckpoints:
    def test_every_interval_plus_ends(self):
        assert checkpoint_miles(55, 25) == [0, 25, 50, 55]

    def test_drops_interval_point_on_top_of_destination(self):
        assert checkpoint_miles(50.2, 25) == [0, 25, 50.2]

    def test_short_trip(self):
        assert checkpoint_miles(8, 10) == [0, 8]

    def test_ownership_covers_route_exactly_once(self):
        spans = ownership([0, 25, 50, 55])
        assert spans == [(0, 12.5), (12.5, 37.5), (37.5, 52.5), (52.5, 55)]


class TestHoursOfService:
    def test_short_drive_unchanged(self):
        assert elapsed_with_hos(7 * H) == 7 * H

    def test_break_after_8_hours(self):
        assert elapsed_with_hos(9 * H) == 9.5 * H

    def test_arriving_at_11_hours_needs_no_rest(self):
        assert elapsed_with_hos(11 * H) == 11.5 * H

    def test_rest_after_11_hours(self):
        # 11h drive + 0.5 break + 10h rest + 1h drive
        assert elapsed_with_hos(12 * H) == 22.5 * H


class TestTimedPath:
    def test_speed_cap_slows_fast_segments(self):
        coords = [(40.0, -90.0), (41.0, -90.0)]  # ~69 mi
        miles = haversine_mi(*coords)
        path = build_timed_path(coords, [miles / 80 * H], miles / 80 * H, max_speed_mph=65)
        assert path.total_drive_s == pytest.approx(miles / 65 * H)

    def test_locate_interpolates(self):
        coords = [(40.0, -90.0), (41.0, -90.0)]
        path = build_timed_path(coords, None, 2 * H, max_speed_mph=200)
        pos, t = path.locate(path.total_mi / 2)
        assert pos == pytest.approx((40.5, -90.0))
        assert t == pytest.approx(H)

    def test_simplify_keeps_ends_and_corners(self):
        line = [(0, 0), (0, 1), (0, 2), (1, 2)]
        assert simplify(line, 0.01) == [(0, 0), (0, 2), (1, 2)]


class TestSeries:
    start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    s = Series(start, wind=[10, 20, 30], gust=[15, 25, 35], rain=[0.0, 0.2, 0.6], snow=[0, 0, 0])

    def test_wind_is_interpolated(self):
        assert self.s.at(self.start + 1.5 * H)["wind_mph"] == pytest.approx(25)

    def test_precip_uses_upcoming_hour_bucket(self):
        # Open-Meteo precip at index i is the total for the hour ending at i.
        assert self.s.at(self.start + 0.5 * H)["rain_in_hr"] == 0.2
        assert self.s.at(self.start + 1.0 * H)["rain_in_hr"] == 0.6

    def test_out_of_range_is_none(self):
        assert self.s.at(self.start + 5 * H)["wind_mph"] is None


def test_plan_trip_scores_checkpoints_at_their_eta():
    """A storm arriving 2h after departure only hits checkpoints reached after it."""
    departure = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    coords = [(40.0, -90.0), (42.0, -90.0)]  # ~138 mi straight north
    path = build_timed_path(coords, None, 138 / 46 * H, max_speed_mph=65)  # ~3h
    option = RouteOption(path=path, osrm_duration_s=path.total_drive_s, summary="US 51", source="osrm")
    start = int(departure.timestamp())

    def fake_forecasts(cells, start_dt, hours):
        wind = [10, 10, 48, 48, 48, 48, 48]  # 48 mph from 14:00 on
        return {c: Series(start, wind=wind, gust=wind, rain=[0] * 7, snow=[0] * 7) for c in cells}

    req = TripRequest((40, -90), (42, -90), "A", "B", departure, load_lb=35_000, interval_mi=25, hos=False)
    with (
        patch.object(planning.routing, "get_route_options", return_value=([option], [])),
        patch.object(planning.weather, "get_forecasts", side_effect=fake_forecasts),
    ):
        result = plan_trip(req)

    route = result["routes"][0]
    for cp in route["checkpoints"]:
        eta = datetime.fromisoformat(cp["eta"].replace("Z", "+00:00"))
        # Wind ramps linearly 10 -> 48 mph between 13:00 and 14:00.
        if eta <= departure + timedelta(hours=1):
            assert cp["risk"]["level"] == 0, cp
        elif eta >= departure + timedelta(hours=2):
            assert cp["risk"]["level"] == 4, cp  # 45-54 mph with >30k lb -> No Travel
    assert sum(route["miles_by_level"]) == pytest.approx(route["distance_mi"], abs=0.2)
    assert route["miles_by_level"][4] > 0
    assert result["recommendation"]["safe"] is False
