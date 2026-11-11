"""
seller_growth/categories.py - one config per climate-control category.

Each category goes to a different category manager, so each gets its own page with its own
products, sellers, plays, forecast and assumption defaults. The engine (revenue.py) is shared; only
this config differs. Every default below is an ESTIMATE (🟠) unless it says REAL; the "why" text is
shown on the page next to the slider it sets.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

try:
    from .revenue import Settings
except ImportError:  # run from inside seller_growth/
    from revenue import Settings


@dataclass(frozen=True)
class CategoryConfig:
    key: str
    label: str
    icon: str
    subcategories: tuple
    season_profile: str                       # heating / cooling / damp / all-year (🟠 judgement)
    large_appliance_question: bool = False    # offer the 7% "Large Appliances" switch on this page
    defaults: dict = field(default_factory=dict)   # overrides of Settings for this page
    why: dict = field(default_factory=dict)        # assumption -> reason for this category's default
    real_notes: tuple = ()                    # aggregate observations from the calibration sample (no rows, no names)

    def assumptions(self, **overrides) -> Settings:
        kw = dict(self.defaults, season_profile=self.season_profile)
        kw.update(overrides)
        return Settings(**kw)


_SAME = ("Same as the other climate pages: no category-specific evidence, kept equal so the five pages are "
         "comparable. Change it in the sidebar.")

CATEGORIES: dict[str, CategoryConfig] = {
    "heaters": CategoryConfig(
        key="heaters", label="Heaters", icon="🔥",
        subcategories=("fan heaters", "oil filled radiators", "convector heaters"),
        season_profile="heating",
        defaults={"boost_adoption": 0.25},
        why={"season_profile": "Heating profile: demand peaks November to February (November index 2.1), close to zero June to August.",
             "boost_adoption": "25%: November is peak season, so more sellers are likely to pay for Boost than the "
                               "20% used elsewhere.",
             "review_rate": _SAME, "commission_rate": "15% Standard Selling Fee (REAL). Heaters are not in the 7% "
                                                      "Large Appliances list."},
        real_notes=("about one in five heater listings was out of stock at the start of the heating season.",),
    ),
    "fans": CategoryConfig(
        key="fans", label="Fans", icon="🌀",
        subcategories=("tower fans", "pedestal fans", "desk fans"),
        season_profile="cooling",
        defaults={"boost_adoption": 0.10},
        why={"season_profile": "Cooling profile: demand peaks June to August (July index 3.0). November is 0.3.",
             "boost_adoption": "10%: off season in November, few sellers pay for Boost now. Raise it for a summer "
                               "plan.",
             "review_rate": _SAME, "commission_rate": "15% Standard Selling Fee (REAL)."},
        real_notes=("the newest review on reviewed fan listings was dated July to September, which fits the cooling profile.",
                    "some listings had several offers priced within pennies of each other."),
    ),
    "dehumidifiers": CategoryConfig(
        key="dehumidifiers", label="Dehumidifiers", icon="💧",
        subcategories=("dehumidifiers",),
        season_profile="damp",
        large_appliance_question=True,
        defaults={"boost_adoption": 0.20},
        why={"season_profile": "Damp profile: autumn and winter condensation season (November index 1.4), flatter than "
                               "heaters.",
             "boost_adoption": "20%: in season but a considered, higher-price purchase.",
             "review_rate": _SAME,
             "commission_rate": "15% default. The published 7% Large Appliances list does not name dehumidifiers; "
                                "the switch tests the other reading."},
        real_notes=("dehumidifier reviews clustered between September and January, which fits the damp profile.",),
    ),
    "portable_ac": CategoryConfig(
        key="portable_ac", label="Portable AC", icon="❄️",
        subcategories=("air conditioners",),
        season_profile="cooling",
        large_appliance_question=True,
        defaults={"boost_adoption": 0.10},
        why={"season_profile": "Cooling profile: demand peaks June to August. November is 0.3.",
             "boost_adoption": "10%: off season in November.",
             "review_rate": _SAME,
             "commission_rate": "15% default. The published 7% Large Appliances list does not name air "
                                "conditioners; the switch tests the other reading."},
        real_notes=("most listings found as 'portable air conditioner' were evaporative or USB air coolers with no "
                    "refrigerant, and the compressor unit was priced far above the usual range. That is a "
                    "classification and buyer-trust issue, so the example includes price anomalies.",),
    ),
    "air_purifiers": CategoryConfig(
        key="air_purifiers", label="Air Purifiers", icon="🌬️",
        subcategories=("air purifiers",),
        season_profile="all-year",
        defaults={"boost_adoption": 0.15},
        why={"season_profile": "Flat (all-year): no clear UK seasonality assumed; pollen season could be tested "
                               "later.",
             "boost_adoption": "15%: steady but not peak demand.",
             "review_rate": _SAME, "commission_rate": "15% Standard Selling Fee (REAL)."},
        real_notes=("one seller showed a Professional Seller badge, so the example includes Professional sellers whose tier is shown, not estimated.",),
    ),
}

ORDER = ["heaters", "fans", "dehumidifiers", "portable_ac", "air_purifiers"]
SECTION = "Seller Revenue: Climate Control"


def get(key: str) -> CategoryConfig:
    return CATEGORIES[key]


def check_config(cfg: CategoryConfig) -> None:
    """Raise if a config sets an assumption the engine does not know."""
    known = {f.name for f in fields(Settings)}
    bad = set(cfg.defaults) - known
    if bad:
        raise KeyError(f"{cfg.key}: unknown assumptions {sorted(bad)}")
