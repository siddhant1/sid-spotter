"""Weather risk classification for a truck at a single point in time.

Thresholds (from the spec)::

    Condition  Low        Moderate    High        Severe      No Travel
    Wind       <25 mph    25-34       35-44       45-54       >=55 mph
    Rain       <0.10 in/h 0.10-0.25   0.25-0.50   0.50-1.00   >1.00
    Snow       <0.5 in/h  0.5-1.0     1.0-2.0     2.0-3.0     >3.0

Band edges are inclusive on the low side (25 mph is Moderate, 0.25 in/h is
High) except for the top rain/snow bands, where the spec says ">1.00" / ">3.0":
exactly 1.00 in/h of rain is still Severe.

Load rules can only make a level worse, never better:

* wind >= 55 mph                       -> No Travel (any load)
* 45 <= wind < 55 mph and load > 30,000 lb -> No Travel
* 35 <= wind < 45 mph and load > 40,000 lb -> Severe
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Risk(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return RISK_LABELS[self]


RISK_LABELS = {
    Risk.LOW: "Low",
    Risk.MODERATE: "Moderate",
    Risk.HIGH: "High",
    Risk.SEVERE: "Severe",
    Risk.NO_TRAVEL: "No Travel",
}


def classify_wind(mph: float) -> Risk:
    if mph >= 55:
        return Risk.NO_TRAVEL
    if mph >= 45:
        return Risk.SEVERE
    if mph >= 35:
        return Risk.HIGH
    if mph >= 25:
        return Risk.MODERATE
    return Risk.LOW


def classify_rain(in_per_hr: float) -> Risk:
    if in_per_hr > 1.00:
        return Risk.NO_TRAVEL
    if in_per_hr >= 0.50:
        return Risk.SEVERE
    if in_per_hr >= 0.25:
        return Risk.HIGH
    if in_per_hr >= 0.10:
        return Risk.MODERATE
    return Risk.LOW


def classify_snow(in_per_hr: float) -> Risk:
    if in_per_hr > 3.0:
        return Risk.NO_TRAVEL
    if in_per_hr >= 2.0:
        return Risk.SEVERE
    if in_per_hr >= 1.0:
        return Risk.HIGH
    if in_per_hr >= 0.5:
        return Risk.MODERATE
    return Risk.LOW


def wind_with_load(mph: float, load_lb: float) -> tuple[Risk, str | None]:
    """Wind level after load rules, plus a note naming the rule if one fired."""
    base = classify_wind(mph)
    if mph >= 55:
        return Risk.NO_TRAVEL, "Wind ≥55 mph: no travel for any load"
    if 45 <= mph < 55 and load_lb > 30_000:
        return Risk.NO_TRAVEL, "Wind 45–54 mph with load >30,000 lb"
    if 35 <= mph < 45 and load_lb > 40_000:
        return max(base, Risk.SEVERE), "Wind 35–44 mph with load >40,000 lb"
    return base, None


@dataclass(frozen=True)
class Assessment:
    level: Risk
    wind: Risk  # after load rules
    rain: Risk
    snow: Risk
    driver: str  # which condition set the overall level: "wind" | "rain" | "snow" | "none"
    load_rule: str | None  # load rule that raised the wind level, if any

    def as_dict(self) -> dict:
        return {
            "level": int(self.level),
            "label": self.level.label,
            "wind": int(self.wind),
            "rain": int(self.rain),
            "snow": int(self.snow),
            "driver": self.driver,
            "load_rule": self.load_rule,
        }


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> Assessment:
    """Overall risk is the worst of the individual conditions."""
    wind, rule = wind_with_load(wind_mph, load_lb)
    rain = classify_rain(rain_in_hr)
    snow = classify_snow(snow_in_hr)
    level = max(wind, rain, snow)
    if level == Risk.LOW:
        driver = "none"
    else:
        # Ties go to wind, then snow, then rain: wind is what load rules act on.
        driver = next(name for name, lvl in (("wind", wind), ("snow", snow), ("rain", rain)) if lvl == level)
    # Only report the load rule when it actually changed the wind level.
    if rule and wind == classify_wind(wind_mph):
        rule = None
    return Assessment(level, wind, rain, snow, driver, rule)
