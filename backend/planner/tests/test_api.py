from datetime import datetime, timedelta, timezone

from django.test import Client

from planner.risk import Risk, assess
from planner.services.scenario import Storm, apply_storm
from planner.services.weather import Series

H = 3600


def _plan_body(**overrides):
    body = {
        "origin": {"label": "Chicago", "lat": 41.88, "lon": -87.63},
        "destination": {"label": "St Louis", "lat": 38.63, "lon": -90.2},
        "departure": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "load_lb": 42000,
        "interval_mi": 25,
    }
    body.update(overrides)
    return body


def test_plan_rejects_bad_interval_and_past_departure():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    resp = Client().post("/api/plan", _plan_body(interval_mi=15, departure=past), content_type="application/json")
    assert resp.status_code == 400
    fields = resp.json()["fields"]
    assert "interval_mi" in fields and "departure" in fields


def test_plan_rejects_same_origin_and_destination():
    same = {"label": "X", "lat": 40.0, "lon": -90.0}
    resp = Client().post("/api/plan", _plan_body(origin=same, destination=same), content_type="application/json")
    assert resp.status_code == 400


def test_storm_peaks_at_centre_and_time():
    start = 1_800_000_000 - (1_800_000_000 % H)
    storm = Storm(lat=40.0, lon=-95.0, peak_epoch=start + 2 * H)
    calm = Series(start, wind=[5.0] * 5, gust=[8.0] * 5, rain=[0.0] * 5, snow=[0.0] * 5)
    far = (45.0, -80.0)
    out = apply_storm({(40.0, -95.0): calm, far: calm}, storm)

    core = out[(40.0, -95.0)]
    assert core.wind[2] == max(core.wind) and 45 <= core.wind[2] < 55
    # Core of the storm with a heavy load is No Travel; far away nothing changes.
    assert assess(core.wind[2], 0, core.snow[2], 42_000).level == Risk.NO_TRAVEL
    assert out[far].wind == calm.wind
    # A lighter truck in the same core is Severe, not No Travel (load rule no longer applies).
    assert assess(core.wind[2], 0, core.snow[2], 25_000).level == Risk.SEVERE
