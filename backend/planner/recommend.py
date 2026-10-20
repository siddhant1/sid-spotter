"""Pick the best route.

Routes are compared lexicographically, per the spec's priority order:

1. fewest Severe miles
2. fewest High miles
3. lowest average risk (distance-weighted, Low=0 ... No Travel=4)
4. shortest travel time

No Travel is strictly worse than Severe, so No Travel miles are compared
before everything else. Checkpoint spacing makes mileage figures coarse,
so values within a small tolerance count as a tie and the next criterion
decides. Otherwise a route 0.2 mi "safer" would beat one that is an hour
faster.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MILES_TOLERANCE = 1.0
AVG_RISK_TOLERANCE = 0.05
TIME_TOLERANCE_S = 60.0


@dataclass(frozen=True)
class RouteMetrics:
    id: str
    no_travel_mi: float
    severe_mi: float
    high_mi: float
    avg_risk: float
    elapsed_s: float


# (attribute, tolerance, human description)
CRITERIA = (
    ("no_travel_mi", MILES_TOLERANCE, "No Travel miles"),
    ("severe_mi", MILES_TOLERANCE, "Severe miles"),
    ("high_mi", MILES_TOLERANCE, "High miles"),
    ("avg_risk", AVG_RISK_TOLERANCE, "average risk"),
    ("elapsed_s", TIME_TOLERANCE_S, "travel time"),
)


def compare(a: RouteMetrics, b: RouteMetrics) -> tuple[int, str | None]:
    """-1 if a is better, 1 if b is better, 0 if tied; plus the deciding criterion."""
    for attr, tol, _ in CRITERIA:
        va, vb = getattr(a, attr), getattr(b, attr)
        if abs(va - vb) > tol:
            return (-1 if va < vb else 1), attr
    return 0, None


@dataclass
class Recommendation:
    best: str
    order: list[str]
    reasons: list[str] = field(default_factory=list)
    safe: bool = True
    advisory: str | None = None

    def as_dict(self) -> dict:
        return {
            "best": self.best,
            "order": self.order,
            "reasons": self.reasons,
            "safe": self.safe,
            "advisory": self.advisory,
        }


def _fmt(attr: str, value: float) -> str:
    if attr == "elapsed_s":
        h, m = divmod(round(value / 60), 60)
        return f"{h}h {m:02d}m"
    if attr == "avg_risk":
        return f"{value:.2f}"
    return f"{value:.0f} mi"


def recommend(routes: list[RouteMetrics]) -> Recommendation:
    # Insertion sort with the tolerant comparator; stable (fastest-first input
    # order breaks exact ties), and n <= 3.
    order: list[RouteMetrics] = []
    for r in routes:
        pos = len(order)
        while pos > 0 and compare(r, order[pos - 1])[0] < 0:
            pos -= 1
        order.insert(pos, r)

    best = order[0]
    reasons = []
    labels = {attr: desc for attr, _, desc in CRITERIA}
    for other in order[1:]:
        _, attr = compare(best, other)
        if attr is None:
            reasons.append(f"Route {best.id} and Route {other.id} are equivalent on every criterion.")
            continue
        reasons.append(
            f"Beats Route {other.id} on {labels[attr]}: "
            f"{_fmt(attr, getattr(best, attr))} vs {_fmt(attr, getattr(other, attr))}."
        )

    rec = Recommendation(best=best.id, order=[r.id for r in order], reasons=reasons)
    if best.no_travel_mi > 0:
        rec.safe = False
        rec.advisory = (
            "Every route crosses No Travel conditions at this departure time. "
            "Delay the trip or wait out the weather before driving."
        )
    elif best.severe_mi > 0:
        rec.advisory = "The best route still includes Severe conditions. Consider a later departure."
    return rec
