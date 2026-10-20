import pytest

from planner.risk import Risk, assess, classify_rain, classify_snow, classify_wind, wind_with_load

L, M, H, S, N = Risk.LOW, Risk.MODERATE, Risk.HIGH, Risk.SEVERE, Risk.NO_TRAVEL


@pytest.mark.parametrize(
    "mph,expected",
    [(0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H), (45, S), (54.9, S), (55, N), (80, N)],
)
def test_wind_bands(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize(
    "rate,expected",
    [(0, L), (0.099, L), (0.10, M), (0.249, M), (0.25, H), (0.499, H), (0.50, S), (1.00, S), (1.001, N)],
)
def test_rain_bands(rate, expected):
    assert classify_rain(rate) == expected


@pytest.mark.parametrize(
    "rate,expected",
    [(0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H), (2.0, S), (3.0, S), (3.01, N)],
)
def test_snow_bands(rate, expected):
    assert classify_snow(rate) == expected


class TestLoadRules:
    def test_55_mph_is_no_travel_for_any_load(self):
        assert wind_with_load(55, 0)[0] == N

    def test_45_to_54_over_30k_is_no_travel(self):
        assert wind_with_load(45, 30_001)[0] == N
        assert wind_with_load(54.9, 45_000)[0] == N

    def test_45_to_54_at_exactly_30k_stays_severe(self):
        assert wind_with_load(50, 30_000)[0] == S

    def test_35_to_44_over_40k_is_severe(self):
        assert wind_with_load(35, 40_001)[0] == S
        assert wind_with_load(44.9, 80_000)[0] == S

    def test_35_to_44_at_or_under_40k_stays_high(self):
        assert wind_with_load(40, 40_000)[0] == H

    def test_load_does_not_affect_lower_winds(self):
        assert wind_with_load(34.9, 80_000)[0] == M


class TestAssess:
    def test_worst_condition_wins(self):
        a = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=2.5, load_lb=10_000)
        assert a.level == S and a.driver == "snow"

    def test_calm_is_low(self):
        a = assess(5, 0, 0, 80_000)
        assert a.level == L and a.driver == "none" and a.load_rule is None

    def test_load_rule_reported_when_it_raises_level(self):
        a = assess(40, 0, 0, 45_000)
        assert a.level == S and a.driver == "wind"
        assert a.load_rule and "40,000" in a.load_rule

    def test_load_rule_not_reported_when_level_unchanged(self):
        a = assess(60, 0, 0, 45_000)
        assert a.level == N and a.load_rule is None
