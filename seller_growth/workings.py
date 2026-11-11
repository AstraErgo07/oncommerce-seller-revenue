"""
seller_growth/workings.py - plain-English, step-by-step workings for the Seller Revenue numbers.

Used by the app pages and by tools/build_overview.py, so the app and docs/OVERVIEW.md show the same words and
numbers. Nothing here changes a calculation: every step re-uses the inputs and results from revenue.py, and the
tests check that the final number of each worked example matches the engine.

Each step is a dict: step (what happens), working (the sum with the numbers in), result, source.
Source labels: "Real (published fee)", "Example input" (a field on the example listing), "Assumed (slider)",
"Worked out" (from earlier steps).
"""
from __future__ import annotations

import math

try:
    from .calc import months_since
    from .revenue import (BOOST, FIRST_SALE, LEAK_DELIVERY, LEAK_DUP, LEAK_OOS, LEAK_PRICE, RETAIN,
                          UPGRADE, Settings, break_even_stake, season_group, subscription_for)
except ImportError:
    from calc import months_since
    from revenue import (BOOST, FIRST_SALE, LEAK_DELIVERY, LEAK_DUP, LEAK_OOS, LEAK_PRICE, RETAIN,
                         UPGRADE, Settings, break_even_stake, season_group, subscription_for)

REAL, EXAMPLE, ASSUMED, WORKED = "Real (published fee)", "Example input", "Assumed (slider)", "Worked out"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]

GRID_CALL_LABEL = "Cost of one call"
GRID_GAP_LABEL = "How much more often a call works than a message, in percentage points"
GRID_HOW_TO_READ = ("How to read the grid: pick the row for what a call costs and the column for how much more often "
                    "a call works; the cell is the £ a month at stake above which a call pays.")


def call_or_message_text(a: Settings) -> str:
    """Plain-English explanation of the call or message tipping point, with the current settings."""
    gap = a.p_success_human - a.p_success_auto
    extra = a.human_cost - a.auto_cost
    head = (f"Should someone phone this seller, or is an automated message enough? A call costs about "
            f"£{a.human_cost:,.0f} of staff time and works about {a.p_success_human:.0%} of the time. A message costs "
            f"about £{a.auto_cost:,.0f} and works about {a.p_success_auto:.0%} of the time. ")
    if gap <= 0:
        return head + "A call does not work more often than a message, so the message is always the better choice."
    be = break_even_stake(a)
    return head + (f"A call works {gap * 100:.0f} percentage points more often but costs £{extra:,.0f} more, so it "
                   f"only pays when enough money is at stake. Over {a.value_horizon_months:g} months that tipping "
                   f"point is £{extra:,.0f} ÷ ({a.value_horizon_months:g} × {gap:.0%}) ≈ £{be:,.0f} a month. "
                   "Above it: call. Below it: send the message.")


def play_sentence(play: dict, a: Settings) -> str:
    """One line per play: '£X a month at stake, above the £Y tipping point, so call. Expected gain £Z a month.'"""
    be = break_even_stake(a)
    stake = f"£{play['stake_month']:,.0f} a month at stake, "
    if be == float("inf"):
        where = "and a call never pays here, so send the message."
    elif play["route"].startswith("Human"):
        where = f"above the £{be:,.0f} tipping point, so call."
    else:
        where = f"below the £{be:,.0f} tipping point, so send the message."
    return stake + where + f" Expected gain £{play['expected_month']:,.0f} a month."


GLOSSARY = {
    "Est. units/month": "how many items we think the listing sells in the current month.",
    "Avg selling price per unit (£)": "what a buyer pays for one item, including any delivery fee. Where several "
                                      "sellers offer the same product, it is the average across their prices, "
                                      "weighted by how many sales each is expected to win.",
    "Est. GMV/month": "the value of those sales: units x average selling price. GMV means gross merchandise value, "
                      "the total buyers pay.",
    "Season factor": "how busy this month is compared with an average month for this kind of product. 1.0 is an "
                     "average month, 2.0 is twice as busy, 0.3 is about a third.",
    "Revenue to OnCommerce": "what the seller pays OnCommerce each month: subscription + commission + Boost fees.",
}


def _gbp(x: float, dp: int = 0) -> str:
    return f"£{x:,.{dp}f}"


def _n(x: float, dp: int = 0) -> str:
    return f"{x:,.{dp}f}"


def step(step: str, working: str, result: str, source: str) -> dict:
    return {"step": step, "working": working, "result": result, "source": source}


def season_factor_text(product: dict, a: Settings) -> str:
    grp = season_group(product["subcategory"], a)
    month = MONTH_NAMES[a.current_month - 1]
    f = product["season_index_now"]
    return (f"{month} for the '{grp}' season pattern: about {f:.2f} times an average month "
            f"(my judgement for the UK, not OnBuy data)")


def product_workings(p: dict, a: Settings) -> tuple[list[dict], float, float]:
    """Steps from reviews to units and GMV for one product row from evaluate_climate.
    Returns (steps, units, gmv); units and gmv equal the engine's est_units_month and est_gmv_month."""
    s = []
    n = int(p.get("product_review_count") or 0)
    per_review = 1 / a.review_rate
    s.append(step("Reviews on the listing", f"{n} reviews", _n(n), EXAMPLE))
    sold = n / a.review_rate
    s.append(step("How many buyers leave a review",
                  f"about 1 in {per_review:.0f} buyers ({a.review_rate:.0%}), so {n} x {per_review:.0f}",
                  f"{_n(sold)} sold to date", ASSUMED))
    w = p["review_window_months"]
    if isinstance(p.get("first_review"), str) and p["first_review"] and a.use_first_review_window:
        why = f"the first review was {w:.0f} months ago (all reviews listed), so sales are spread over that time"
        src = EXAMPLE
    else:
        why = f"first review date not known, so use the default of {w:.0f} months"
        src = ASSUMED
    avg = sold / w if n else 0.0
    s.append(step("Spread over the time the listing has been selling", f"{why}: {_n(sold)} / {w:.0f}",
                  f"{avg:.1f} a month in an average month", src))
    age = months_since(p.get("latest_review") or None)
    if n and age is not None and age > a.stale_after_months:
        avg *= a.stale_factor
        s.append(step("Newest review is old", f"newest review is {age:.0f} months old (over "
                      f"{a.stale_after_months:g}), so halve it: x {a.stale_factor:g}", f"{avg:.1f} a month", ASSUMED))
    f = p["season_index_now"]
    now = avg * f
    s.append(step("Season factor for this month", f"{season_factor_text(p, a)}: {avg:.1f} x {f:.2f}",
                  f"{now:.1f} this month", ASSUMED))
    badge = p.get("badge") or ""
    floors = {"Bestseller": a.bestseller_floor_units, "Hot": a.hot_floor_units, "In demand": a.in_demand_floor_units}
    floor = floors.get(badge, a.no_signal_units)
    if floor > now:
        label = f"OnBuy '{badge}' badge" if badge else "no badge and few reviews"
        s.append(step("Minimum for the badge", f"{label}: assume at least {floor:g} a month", f"{floor:g} this month",
                      ASSUMED if not badge else f"{ASSUMED}; badge is an {EXAMPLE.lower()}"))
        now = floor
    if p.get("flag_out_of_stock") or p.get("flag_price_anomaly"):
        why = "out of stock" if p.get("flag_out_of_stock") else "the price looks wrong for the product"
        s.append(step("Can it sell now?", f"{why}, so no sales are counted this month", "0", EXAMPLE))
        now = 0.0
    price = p["avg_price"]
    if int(p.get("offers_count") or 1) > 1:
        pw = (f"{int(p['offers_count'])} sellers offer it; the recommended offer wins {a.buybox_share:.0%} of sales "
              f"and the rest share the remainder, so the weighted average price incl. delivery is {_gbp(price, 2)}")
    else:
        pw = f"price {_gbp(p['price'], 2)} + delivery {_gbp(p.get('delivery_fee') or 0, 2)}"
    s.append(step("Avg selling price per unit", pw, _gbp(price, 2), EXAMPLE))
    gmv = now * price
    s.append(step("Est. GMV/month", f"{now:.1f} units x {_gbp(price, 2)}", _gbp(gmv), WORKED))
    comm = now * p["commission_per_unit"]
    s.append(step("Commission to OnCommerce on these sales",
                  f"{p['commission_rate']:.0%} of the delivered price (at least £{a.min_fee:.2f} an item): "
                  f"{now:.1f} x {_gbp(p['commission_per_unit'], 2)}", _gbp(comm), REAL))
    return s, now, gmv


def product_sentence(p: dict, a: Settings) -> str:
    """The whole product working as one line, e.g. for a caption or the overview."""
    steps, units, gmv = product_workings(p, a)
    parts = [f"{x['working']} = {x['result']}" for x in steps[1:-1]]
    return f"{p['title']}: {steps[0]['result']} reviews; " + "; ".join(parts) + "."


def seller_workings(sr: dict, a: Settings, reviews_per_order: float) -> tuple[list[dict], float]:
    """Steps from the seller's order count to revenue to OnCommerce. Returns (steps, total), total equal to
    the engine's est_revenue_month."""
    s = []
    life = sr["lifetime_orders"]
    if str(sr["orders_source"]).startswith("SHOWN"):
        s.append(step("Lifetime orders", "the seller box shows the order count (a lower bound, e.g. '24k+')",
                      _n(life), EXAMPLE))
    elif life:
        per = 1 / reviews_per_order
        s.append(step("Lifetime orders", f"{_n(sr['seller_reviews'])} seller reviews; about 1 seller review per "
                      f"{per:.0f} orders (median of sellers that show both numbers), so {_n(sr['seller_reviews'])} x "
                      f"{per:.1f}", _n(life), WORKED))
    else:
        s.append(step("Lifetime orders", "no order count and no seller reviews shown", "0", EXAMPLE))
    om = sr["est_orders_month"]
    s.append(step("Orders a month", f"spread over {a.seller_tenure_months:g} months of trading: {_n(life)} / "
                  f"{a.seller_tenure_months:g}", _n(om, 1), ASSUMED))
    gmv = sr["est_account_gmv_month"]
    s.append(step("Sales a month, whole account (GMV)", f"average order {_gbp(a.avg_order_value)}: {_n(om, 1)} x "
                  f"{_gbp(a.avg_order_value)}", _gbp(gmv), ASSUMED))
    tier = sr["tier"]
    if str(sr["tier_source"]).startswith("SHOWN"):
        why = "the listing shows the Professional Seller badge"
    elif tier == "Partner":
        why = f"no badge, and at least {a.partner_orders_k:g}k lifetime orders, so assume Partner"
    else:
        why = f"no badge, and fewer than {a.partner_orders_k:g}k lifetime orders, so assume Standard"
    sub = sr["subscription_month"]
    s.append(step("Subscription", f"{why}; {tier} costs {_gbp(sub)} a month (promotional price until January 2028, "
                  f"then {_gbp(a.sub_list[tier])})", _gbp(sub), REAL))
    comm = sr["est_commission_month"]
    s.append(step("Commission", f"{a.commission_rate:.0%} of sales: {a.commission_rate:.0%} x {_gbp(gmv)}",
                  _gbp(comm), REAL))
    lvl = a.boost_levels[a.boost_level]
    boost = sr["est_boost_month"]
    s.append(step("Boost fees", f"{a.boost_adoption:.0%} chance the seller uses Boost x {a.boosted_share_of_gmv:.0%} "
                  f"of their sales boosted x {lvl:.0%} fee ('{a.boost_level}' level) x {_gbp(gmv)}", _gbp(boost),
                  f"{ASSUMED}; the {lvl:.0%} level is a real published fee"))
    total = sub + comm + boost
    s.append(step("Revenue to OnCommerce a month", f"{_gbp(sub)} + {_gbp(comm)} + {_gbp(boost)}", _gbp(total),
                  WORKED))
    return s, total


def play_rules(a: Settings) -> dict[str, str]:
    """One plain sentence per play: when it fires, and the £ at stake."""
    return {
        UPGRADE: (f"Suggest the next subscription tier when the extra profit we expect it to bring the seller "
                  f"({a.partner_sales_uplift:.0%} more sales for Partner, {a.pro_sales_uplift:.0%} for Professional, "
                  f"at a {a.seller_margin:.0%} margin) is more than the extra monthly fee. At stake: the extra fee plus "
                  f"commission on the extra sales."),
        RETAIN: (f"Flag a seller whose subscription is more than {a.churn_fee_ratio:.0%} of their estimated monthly "
                 f"sales, now or after the promotional prices end in January 2028, because they may cancel or "
                 f"downgrade. At stake: everything the seller pays OnCommerce a month."),
        BOOST: (f"Suggest Boost for an in-stock listing in its busy season (season factor at least 1.0) that scores at "
                f"least {a.quality_threshold}/100 for listing quality, is priced within {a.price_gap_threshold:.0%} of "
                f"the cheapest offer, has no Bestseller badge, and where the Boost fee would pay for itself for the "
                f"seller. At stake: Boost fees plus commission on the extra sales."),
        FIRST_SALE: (f"Suggest a listing fix when a listing has no reviews yet or scores under "
                     f"{a.quality_threshold}/100 (missing brand, paid or slow delivery, low stock and similar). At "
                     f"stake: commission if it reached {a.first_sale_units:g} sales a month, or "
                     f"{a.fix_uplift:.0%} more commission."),
        LEAK_OOS: ("Flag a listing that is out of stock. At stake: the commission on the sales it would make this "
                   "month."),
        LEAK_DUP: (f"Flag a product listed on two separate pages. At stake: merging them is assumed to add "
                   f"{a.merge_uplift:.0%} to its commission."),
        LEAK_DELIVERY: (f"Flag paid delivery or a delivery promise over 7 days. At stake: fixing it is assumed to add "
                        f"{a.delivery_uplift:.0%} to its commission."),
        LEAK_PRICE: ("Flag a price that looks wrong for the product, or an offer more than twice the cheapest offer "
                     "on the same page. No £ is put on it; it is a check for the category manager."),
    }


def routing_rule(a: Settings) -> str:
    h, au = a.p_success_human, a.p_success_auto
    yrs = a.value_horizon_months
    diff = (h - au) * yrs
    breakeven = (a.human_cost - a.auto_cost) / diff if diff > 0 else math.inf
    return (f"Each play has a monthly £ at stake. A Seller Success call is assumed to work {h:.0%} of the time and "
            f"cost {_gbp(a.human_cost)}; an automated message works {au:.0%} of the time and costs "
            f"{_gbp(a.auto_cost, 0)}. Over {yrs:g} months, pick whichever leaves more money after its cost. With these "
            f"settings a call is worth it when about {_gbp(breakeven)} a month or more is at stake. Expected £ a month = "
            f"£ at stake x the success rate of the chosen route.")


def routing_workings(play: dict, a: Settings) -> list[dict]:
    st_ = play["stake_month"]
    y = a.value_horizon_months
    return [
        step("£ at stake a month", "from the play rule", _gbp(st_, 2), WORKED),
        step("Call from Seller Success", f"{_gbp(st_, 2)} x {y:g} months x {a.p_success_human:.0%} success - "
             f"{_gbp(a.human_cost)} cost", _gbp(play["net_value_human"]), ASSUMED),
        step("Automated message", f"{_gbp(st_, 2)} x {y:g} months x {a.p_success_auto:.0%} success - "
             f"{_gbp(a.auto_cost)} cost", _gbp(play["net_value_auto"]), ASSUMED),
        step("Route", "the larger of the two", play["route"], WORKED),
        step("Expected £ a month", f"{_gbp(st_, 2)} x {(a.p_success_human if 'Human' in play['route'] else a.p_success_auto):.0%}",
             _gbp(play["expected_month"], 2), WORKED),
    ]


def steps_markdown(steps: list[dict]) -> str:
    """Markdown table (plain, readable without JavaScript)."""
    out = ["| Step | Working | Result | Source |", "|---|---|---|---|"]
    for s in steps:
        out.append(f"| {s['step']} | {s['working']} | {s['result']} | {s['source']} |")
    return "\n".join(out)


def season_table(a: Settings) -> str:
    head = "| Pattern | " + " | ".join(m[:3] for m in MONTH_NAMES) + " |"
    out = [head, "|---" * 13 + "|"]
    for k, v in a.season_profiles.items():
        out.append(f"| {k} | " + " | ".join(f"{x:g}" for x in v) + " |")
    return "\n".join(out)


RULE_PLAIN = {
    "sales_lift_pays_next_tier": "extra sales would pay for the next tier",
    "fee_to_sales_high": "subscription is a high share of sales",
    "promo_price_step_jan_2028": "fee becomes a high share of sales when promo prices end (Jan 2028)",
    "no_sales_evidence": "pays a subscription but shows no sales",
    "in_season_quality_listing_no_bestseller": "good listing, in season, Boost pays for itself",
    "no_reviews_yet": "no reviews yet",
    "low_quality_score": "listing quality under the threshold",
    "out_of_stock_in_season": "out of stock",
    "duplicate_page": "same product on two pages",
    "paid_or_slow_delivery": "paid or slow delivery",
    "price_anomaly": "price looks wrong for the product",
    "outlier_offer": "one offer is over twice the cheapest",
}


def plain_rule(code: str) -> str:
    return RULE_PLAIN.get(code, code.replace("_", " "))
