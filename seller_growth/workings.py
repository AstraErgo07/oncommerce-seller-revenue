"""
seller_growth/workings.py - plain-English, step-by-step workings for the Seller Revenue numbers.

Used by the app pages and by tools/build_overview.py, so the app and docs/OVERVIEW.md show the same words and
numbers. Nothing here changes a calculation: every step re-uses the inputs and results from revenue.py, and the
tests check that the final number of each worked example matches the engine.

Each step is a dict: step (what happens), working (the sum with the numbers in), result, source.
Source labels: "Published" (a published fee), "Observed in sample" (a field on the example listing), "Assumption" (slider),
"Model estimate" (worked out from earlier steps).
"""
from __future__ import annotations

import math

try:
    from .calc import months_since
    from .revenue import (BOOST, FIRST_SALE, LEAK_DELIVERY, LEAK_DUP, LEAK_OOS, LEAK_PRICE, RETAIN,
                          UPGRADE, Settings, break_even_stake, contribution_factor, season_group, subscription_for,
                          survival_months)
except ImportError:
    from calc import months_since
    from revenue import (BOOST, FIRST_SALE, LEAK_DELIVERY, LEAK_DUP, LEAK_OOS, LEAK_PRICE, RETAIN,
                         UPGRADE, Settings, break_even_stake, contribution_factor, season_group, subscription_for,
                          survival_months)

REAL, EXAMPLE, ASSUMED, WORKED = "Published", "Observed in sample", "Assumption", "Model estimate"
SOURCE_TAGS = {REAL: "published by OnCommerce or a public source", EXAMPLE: "a field on the listing (here synthetic example data shaped like the public sample)", ASSUMED: "a judgement you can change in the sidebar", WORKED: "worked out by the model from the items above"}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]

GRID_CALL_LABEL = "Cost of one call"
GRID_GAP_LABEL = "How much more often a call works than a message, in percentage points"
GRID_HOW_TO_READ = ("How to read the grid: pick the row for what a call costs and the column for how much more often "
                    "a call works; the cell is the £ a month at stake above which a call pays.")


def cost_buildup_text(a: Settings) -> str:
    """How the call and message costs are built up (rough estimates, not OnCommerce data)."""
    return (f"Call cost (assumption, a rough estimate): £{a.sse_annual_cost:,.0f} fully loaded yearly cost of a Seller "
            f"Success exec ÷ {a.sse_productive_hours:,.0f} productive hours a year = £{a.sse_annual_cost / a.sse_productive_hours:,.2f} "
            f"an hour, × {a.call_hours:g} hours per completed call (prep, attempts, the call, follow-up and CRM notes) "
            f"= £{a.human_cost:,.2f}. Message cost (assumption, a rough estimate): £{a.journey_build_cost:,.0f} to build "
            f"and maintain the journey ÷ {a.journey_sellers_reached:,.0f} sellers reached = "
            f"£{a.journey_build_cost / a.journey_sellers_reached:,.2f}, + £{a.message_send_cost:,.2f} to send = "
            f"£{a.auto_cost:,.2f}. Neither is OnCommerce data.")


def call_or_message_text(a: Settings) -> str:
    """Plain-English explanation of the call or message tipping point, with the current settings."""
    gap = a.p_success_human - a.p_success_auto
    extra = a.human_cost - a.auto_cost
    head = (f"Should someone phone this seller, or is an automated message enough? A call costs about "
            f"£{a.human_cost:,.2f} of staff time and works about {a.p_success_human:.0%} of the time. A message costs "
            f"about £{a.auto_cost:,.2f} and works about {a.p_success_auto:.0%} of the time. ")
    if gap <= 0:
        return head + "A call does not work more often than a message, so the message is always the better choice."
    be = break_even_stake(a)
    sm = survival_months(a)
    return head + (f"A call works {gap * 100:.0f} percentage points more often but costs £{extra:,.2f} more, so it "
                   "only pays when enough money is at stake. What counts is OnCommerce's contribution, not the "
                   f"seller's sales: each extra £1 of platform revenue a month is worth {a.contribution_margin:.0%} "
                   f"as contribution, for about {sm:.1f} months out of the next {a.value_horizon_months:g} (some "
                   f"sellers leave: {round(a.monthly_churn * 100, 2):g}% a month). So the tipping point is "
                   f"£{extra:,.2f} ÷ ({a.contribution_margin:.0%} × {sm:.1f} × {gap:.0%}) ≈ £{be:,.0f} of platform "
                   "revenue a month. Above it: call. Below it: send the message.")


def play_sentence(play: dict, a: Settings) -> str:
    """One line per play: '£X a month at stake, above the £Y tipping point, so call. Expected extra revenue £Z a month.'"""
    be = break_even_stake(a)
    stake = f"£{play['stake_month']:,.0f} a month at stake, "
    if be == float("inf"):
        where = "and a call never pays here, so send the message."
    elif play["route"].startswith("Human"):
        where = f"above the £{be:,.0f} tipping point, so call."
    else:
        where = f"below the £{be:,.0f} tipping point, so send the message."
    return stake + where + f" Expected extra revenue £{play['expected_month']:,.0f} a month."


def action_economics_steps(play: dict, a: Settings) -> list[dict]:
    """The money behind one action, on OnCommerce contribution: stake, success, cost, revenue and net contribution."""
    sm, f = survival_months(a), contribution_factor(a)
    st_, p = play["stake_month"], play["p_success"]
    return [
        step("Platform revenue at stake a month", "extra fees and commission to OnCommerce if the action works "
             "(not the seller's sales)", _gbp(st_, 2), WORKED),
        step("Chance it works", f"{play['route']}: assumed success rate", f"{p:.0%}", ASSUMED),
        step("Cost of the intervention", "call or message cost, built up in the sidebar",
             _gbp(play["intervention_cost"], 2), ASSUMED),
        step(f"Expected extra revenue over {a.value_horizon_months:g} months",
             f"{_gbp(st_, 2)} × {p:.0%} × {sm:.1f} months still trading (churn {round(a.monthly_churn * 100, 2):g}% "
             "a month)", _gbp(play["expected_revenue_horizon"]), WORKED),
        step("Expected contribution", f"× {a.contribution_margin:.0%} OnCommerce margin", _gbp(play["expected_contribution"]),
             WORKED),
        step("Expected net contribution after cost", f"{_gbp(play['expected_contribution'])} − "
             f"{_gbp(play['intervention_cost'], 2)}", _gbp(play["net_contribution"]), WORKED),
        step("Why this route", play["why_route"], play["route"], WORKED),
    ]


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



# --- seller orders, revenue and LTV, in plain words ---------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{round(x * 100, 2):g}%"


def orders_source_label(src) -> str:
    src = str(src)
    if src.startswith("SHOWN"):
        return "Shown on OnBuy"
    if src.startswith("EST"):
        return "Estimated from reviews"
    return "Not shown"


def reviews_per_order_text(ratio: float, n: int, sample: dict | None = None, set_by_user: bool = False) -> str:
    """Plain explanation of the seller reviews to orders ratio (e.g. 0.066 = 1 review per about 15 orders)."""
    if set_by_user:
        out = (f"Set in the sidebar to 1 review per {1 / ratio:.1f} orders ({ratio * 100:.1f} seller reviews per 100 "
               "orders). ")
    else:
        out = (f"About {ratio * 100:.1f} seller reviews per 100 orders, i.e. 1 review per about {1 / ratio:.0f} "
               "orders. Worked out from the sellers whose OnBuy page shows both their order count and review count: "
               "for each, seller reviews ÷ orders, then the median (middle value) so one odd seller can't skew it. "
               f"Based on {n} sellers in the data (all five pages together), so treat as rough. ")
    if sample and sample.get("n"):
        out += (f"For reference, the real sample the example data copies had {sample['n']} such sellers: median 1 "
                f"review per {1 / sample['median']:.0f} orders, ranging from 1 per {1 / sample['max']:.0f} to 1 per "
                f"{1 / sample['min']:.0f}.")
    return out.strip()


def seller_value_workings(sr: dict, a: Settings, reviews_per_order: float, n_cal: int,
                          sample: dict | None = None) -> tuple[list[dict], float, float]:
    """Steps (1) orders, (2) orders a month, (3) sales a month, (4) revenue, (5) LTV, for one seller.
    Returns (steps, revenue a month, LTV); both equal the engine's est_revenue_month and ltv."""
    R, A, W, O = REAL, ASSUMED, WORKED, EXAMPLE
    s = []
    life = sr["lifetime_orders"]
    src = str(sr["orders_source"])
    if src.startswith("SHOWN"):
        s.append(step("1. Lifetime orders (shown on OnBuy)",
                      f"the OnBuy seller box shows {life / 1000:g}k+ orders. The + means at least this many, so "
                      "this is a minimum", _n(life), O))
    elif src.startswith("EST"):
        per = 1 / reviews_per_order
        s.append(step("1. Lifetime orders (estimated from reviews)",
                      f"no order count is shown, so {_n(sr['seller_reviews'])} seller reviews (observed in sample) × about "
                      f"{per:.1f} orders per review (assumption, explained in the note on the ratio): "
                      f"{_n(sr['seller_reviews'])} × {per:.1f}",
                      _n(life), f"{O} review count × {A} ratio"))
    else:
        s.append(step("1. Lifetime orders", "no order count and no seller reviews shown", "0", O))
    om = sr["est_orders_month"]
    s.append(step("2. Orders a month", f"lifetime orders ÷ months trading (assumption: {a.seller_tenure_months:g}): "
                  f"{_n(life)} ÷ {a.seller_tenure_months:g}", _n(om, 1), A))
    gmv = sr["est_account_gmv_month"]
    s.append(step("3. Sales a month, whole account", f"orders a month × average order value (assumption: "
                  f"{_gbp(a.avg_order_value)}): {_n(om, 1)} × {_gbp(a.avg_order_value)}", _gbp(gmv), A))
    tier, sub = sr["tier"], sr["subscription_month"]
    if str(sr["tier_source"]).startswith("SHOWN"):
        why, tsrc = "tier shown: the listing has the Professional Seller badge", f"{R} price, {O} tier"
    elif tier == "Partner":
        why, tsrc = (f"tier estimated: no badge, and at least {a.partner_orders_k:g}k lifetime orders, so assume "
                     "Partner", f"{R} price, {A} tier")
    else:
        why, tsrc = (f"tier estimated: no badge, and fewer than {a.partner_orders_k:g}k lifetime orders, so assume "
                     "Standard", f"{R} price, {A} tier")
    s.append(step("4a. Subscription", f"{why}. {tier} costs {_gbp(sub)} a month (published promotional price until "
                  f"January 2028, then {_gbp(a.sub_list[tier])})", _gbp(sub), tsrc))
    comm = sr["est_commission_month"]
    s.append(step("4b. Commission", f"{a.commission_rate:.0%} of sales (published, at least {_gbp(a.min_fee, 2)} an "
                  f"order): {a.commission_rate:.0%} × {_gbp(gmv)}", _gbp(comm), R))
    lvl = a.boost_levels[a.boost_level]
    boost = sr["est_boost_month"]
    s.append(step("4c. Boost fees", f"share of sellers using Boost ({a.boost_adoption:.0%}, assumed) × share of their "
                  f"sales boosted ({a.boosted_share_of_gmv:.0%}, assumed) × Boost fee ({a.boost_level} {lvl:.0%}, "
                  f"published) × {_gbp(gmv)}", _gbp(boost), f"{A} (fee level {R})"))
    total = sub + comm + boost
    s.append(step("4. Revenue to OnCommerce a month", f"subscription + commission + Boost: {_gbp(sub)} + "
                  f"{_gbp(comm)} + {_gbp(boost)}", _gbp(total), W))
    if a.monthly_churn > 0:
        ltv_v = total * a.contribution_margin / a.monthly_churn
        s.append(step("5. Lifetime value (LTV)", f"revenue a month × OnCommerce margin ({a.contribution_margin:.0%}, "
                      f"assumed) ÷ monthly churn ({_pct(a.monthly_churn)}, assumed): {_gbp(total)} × "
                      f"{a.contribution_margin:.0%} ÷ {_pct(a.monthly_churn)}. At {_pct(a.monthly_churn)} churn a seller "
                      f"stays about {1 / a.monthly_churn:.0f} months on average (1 ÷ {a.monthly_churn:g})",
                      _gbp(ltv_v), A))
    else:
        ltv_v = float("inf")
        s.append(step("5. Lifetime value (LTV)", "churn is set to 0, so sellers never leave and LTV has no limit",
                      "no limit", A))
    return s, total, ltv_v


def play_rules(a: Settings) -> dict[str, str]:
    """One plain sentence per play: when it fires, and the £ at stake."""
    return {
        UPGRADE: (f"Suggest the next subscription tier only when the seller would be better off: extra sales from "
                  f"the tier's features (assumption: {a.partner_sales_uplift:.0%} for Partner, {a.pro_sales_uplift:.0%} for "
                  f"Professional; no public evidence, so cautious) × the seller's margin after commission "
                  f"({a.seller_margin:.0%} − {a.commission_rate:.0%}) must be more than the extra monthly fee. Marked "
                  "'Needs validation' if the tier or orders are estimated, the gain is thin, or the seller would lose "
                  "money at the January 2028 list price. Deferred if the seller has a sales leak to fix first. At "
                  "stake: the extra fee plus commission on the extra sales."),
        RETAIN: (f"Flag a seller whose subscription is more than {a.churn_fee_ratio:.0%} of their estimated monthly "
                 f"sales, now or after the promotional prices end in January 2028, because they may cancel or "
                 f"downgrade. At stake: what would be lost (the whole account if they cancel, the tier difference if "
                 f"they downgrade) × the assumed {a.at_risk_loss_prob:.0%} chance of losing it without help."),
        BOOST: (f"Suggest Boost only for an in-stock, correctly priced listing in its busy season (season factor at "
                f"least 1.0) that scores at least {a.quality_threshold}/100 for listing quality, is not a duplicate "
                f"page, is priced within {a.price_gap_threshold:.0%} of the cheapest offer, has no Bestseller badge, "
                "where the Boost fee pays for itself for the seller and the platform's return covers the cost of "
                "asking. Deferred if the seller has a sales leak to fix first. At stake: Boost fees plus commission "
                f"on the extra sales, × {1 - a.boost_adoption:.0%} (the share of sellers not already using Boost, "
                "whose Boost fees are already in the base revenue)."),
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
    be = break_even_stake(a)
    return (f"Each action has a monthly platform revenue at stake. A Seller Success call is assumed to work "
            f"{a.p_success_human:.0%} of the time and cost {_gbp(a.human_cost, 2)}; an automated message works "
            f"{a.p_success_auto:.0%} of the time and costs {_gbp(a.auto_cost, 2)}. Value = £ at stake × "
            f"{a.contribution_margin:.0%} OnCommerce margin × {survival_months(a):.1f} months still trading × success "
            f"rate, minus the cost. The route that leaves more contribution wins: a call when about {_gbp(be)} a month "
            "or more is at stake.")


def routing_workings(play: dict, a: Settings) -> list[dict]:
    st_ = play["stake_month"]
    f = contribution_factor(a)
    return [
        step("£ at stake a month", "platform revenue from the action rule", _gbp(st_, 2), WORKED),
        step("Call from Seller Success", f"{_gbp(st_, 2)} × {f:.2f} (margin × months still trading) × "
             f"{a.p_success_human:.0%} success − {_gbp(a.human_cost, 2)} cost", _gbp(play["net_value_human"]), ASSUMED),
        step("Automated message", f"{_gbp(st_, 2)} × {f:.2f} × {a.p_success_auto:.0%} success − "
             f"{_gbp(a.auto_cost, 2)} cost", _gbp(play["net_value_auto"]), ASSUMED),
        step("Route", "the larger of the two", play["route"], WORKED),
        step("Expected £ a month", f"{_gbp(st_, 2)} × {play['p_success']:.0%}", _gbp(play["expected_month"], 2), WORKED),
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


# --- seller decision view, in business language -----------------------------------------------------------------
_EST_KEYS = ("est_", "units", "gmv", "gain", "net", "roi", "breakeven", "fee_to_sales", "season_index", "lifetime")
_PUB_KEYS = ("extra_fee", "subscription", "next_tier_features", "list_price", "suggested_boost_level")
_ASM_KEYS = ("assumed", "chance", "next_tier")


def evidence_source(key: str) -> str:
    k = key.lower()
    if any(w in k for w in _PUB_KEYS):
        return REAL
    if any(w in k for w in _ASM_KEYS):
        return ASSUMED
    if any(w in k for w in _EST_KEYS):
        return WORKED
    return EXAMPLE


def evidence_rows(ev: dict) -> list[dict]:
    """Evidence as rows tagged Published / Observed in sample / Assumption / Model estimate."""
    rows = []
    for k_, v in ev.items():
        label = k_.replace("_gbp", " (£)").replace("season_index", "season_factor").replace("_", " ")
        rows.append({"Item": label[:1].upper() + label[1:], "Value": str(round(v, 2) if isinstance(v, float) else v),
                     "Type": evidence_source(k_)})
    return rows


ACTION_WORDS = {
    UPGRADE: "Talk to the seller about moving to {next_tier}, only if their own numbers show it pays for itself",
    RETAIN: "Check in with the seller before they cancel or downgrade, and help them get more from their plan",
    BOOST: "Offer Boost on {product} at the {boost} level, now that the listing is ready for it",
    FIRST_SALE: "Help the seller improve {product} so it starts selling or sells more",
    LEAK_OOS: "Ask the seller to restock {product}: it is out of stock in its selling season",
    LEAK_DUP: "Merge the duplicate pages for {product} so sales and reviews are not split",
    LEAK_DELIVERY: "Help the seller offer free or faster delivery on {product}",
    LEAK_PRICE: "Ask the seller to check the price on {product}: it looks wrong",
}


def action_text(play: dict) -> str:
    ev = play.get("evidence", {})
    return ACTION_WORDS[play["play_type"]].format(
        next_tier=ev.get("next_tier", "the next tier"), product=play.get("title") or "this listing",
        boost=str(ev.get("suggested_boost_level", "")).split(" ")[0] or "suggested")


def seller_situation(seller: dict | None, seller_products: list[dict], seller_plays: list[dict]) -> str:
    """Two or three sentences on what is happening commercially for a seller."""
    parts = []
    if seller:
        parts.append(
            f"{seller['seller']} is on the {seller['tier']} plan ({'shown' if str(seller['tier_source']).startswith('SHOWN') else 'estimated'})"
            f" and is estimated to pay OnCommerce about £{seller['est_revenue_month']:,.0f} a month across its whole "
            f"account. In this category it sells about {seller['climate_units_month']:,.1f} units a month "
            f"(£{seller['climate_gmv_month']:,.0f} of sales, model estimate).")
    n = len(seller_products)
    oos = sum(1 for p in seller_products if p.get("flag_out_of_stock"))
    low_q = sum(1 for p in seller_products if not p.get("flag_out_of_stock") and p.get("quality_issues"))
    if n:
        bits = [f"{n} listing{'s' if n != 1 else ''} here as the recommended offer"]
        if oos:
            bits.append(f"{oos} out of stock")
        if low_q:
            bits.append(f"{low_q} with listing issues")
        parts.append("It has " + ", ".join(bits) + ".")
    types = {p["play_type"] for p in seller_plays}
    if types & {LEAK_OOS, LEAK_DELIVERY, LEAK_DUP, LEAK_PRICE, FIRST_SALE}:
        parts.append("It is losing sales to problems that can be fixed, so fixing them comes before advertising or a "
                     "plan change.")
    elif RETAIN in types:
        parts.append("Its subscription looks high next to its sales, so there is a risk it cancels or downgrades.")
    elif types & {BOOST, UPGRADE}:
        parts.append("Its listings are in good shape, so there may be room to grow with Boost or a better plan.")
    return " ".join(parts)
