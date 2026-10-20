from planner.recommend import RouteMetrics, recommend


def m(id, nt=0.0, severe=0.0, high=0.0, avg=0.0, hours=5.0):
    return RouteMetrics(id, nt, severe, high, avg, hours * 3600)


def test_fewest_severe_miles_beats_faster_route():
    rec = recommend([m("A", severe=20, hours=5), m("B", severe=0, high=100, hours=7)])
    assert rec.best == "B"
    assert "Severe miles" in rec.reasons[0]


def test_high_miles_break_severe_tie():
    rec = recommend([m("A", severe=10, high=50), m("B", severe=10, high=5, hours=9)])
    assert rec.best == "B"


def test_average_risk_then_time():
    rec = recommend([m("A", avg=0.8, hours=4), m("B", avg=0.2, hours=6), m("C", avg=0.2, hours=5)])
    assert rec.order == ["C", "B", "A"]


def test_no_travel_ranks_below_severe():
    rec = recommend([m("A", nt=5), m("B", severe=200)])
    assert rec.best == "B"


def test_small_mileage_differences_are_ties():
    # 0.4 mi difference is below checkpoint resolution; time decides.
    rec = recommend([m("A", severe=10.4, hours=6), m("B", severe=10.0, hours=5)])
    assert rec.best == "B"
    assert "travel time" in rec.reasons[0]


def test_unsafe_when_every_route_has_no_travel():
    rec = recommend([m("A", nt=10), m("B", nt=30)])
    assert rec.best == "A" and not rec.safe and rec.advisory


def test_all_low_picks_fastest():
    rec = recommend([m("A", hours=5), m("B", hours=6), m("C", hours=7)])
    assert rec.order == ["A", "B", "C"] and rec.safe and rec.advisory is None
