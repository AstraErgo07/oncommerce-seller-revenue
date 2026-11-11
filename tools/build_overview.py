"""
tools/build_overview.py - writes docs/OVERVIEW.md, a plain markdown write-up of the Seller Revenue tool, from the code.

Every number comes from the same functions the app uses, at each page's default settings, so the document
matches the app. Run:
    python tools/build_overview.py                     # writes docs/OVERVIEW.md
    python tools/build_overview.py --pdf out.pdf       # also renders a PDF (needs the 'markdown' package and Chrome)
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.text import FOOTER, VERSION  # noqa: E402
from seller_growth.categories import CATEGORIES, ORDER  # noqa: E402
from seller_growth.revenue import (Settings, break_even_grid, break_even_stake, contribution_factor,  # noqa: E402
                                   overview_by_category, portfolio_summary, run_category, sensitivity_table,
                                   settings_hash, survival_months, top_play_per_seller, units_summary)
from seller_growth.workings import (GLOSSARY, MONTH_NAMES, play_rules, plain_rule, product_workings,  # noqa: E402
                                    routing_rule, routing_workings, season_table, seller_workings, steps_markdown,
                                    GRID_CALL_LABEL, GRID_GAP_LABEL, GRID_HOW_TO_READ, call_or_message_text,
                                    play_sentence, reviews_per_order_text, seller_value_workings,
                                    orders_source_label, action_economics_steps, cost_buildup_text)

OUT = ROOT / "docs" / "OVERVIEW.md"
REPO = "https://github.com/AstraErgo07/oncommerce-seller-revenue"
EXAMPLE_LABEL = ("Illustrative: synthetic data and assumptions, not OnBuy performance. Calibrated on a small sample of "
                 "public OnBuy pages (Nov 2026); replace with internal data to use.")


def md_table(df: pd.DataFrame) -> str:
    """Plain markdown table. Prices to the penny, monthly units to one decimal, other £ and counts whole."""
    def fmt(col):
        c = col.lower()
        if "price" in c or "/unit" in c:
            return 2
        if "units/month" in c:
            return 1
        return 0

    def cell(v, dp):
        if isinstance(v, (float, int)) and not isinstance(v, bool):
            if isinstance(v, float) and math.isnan(v):
                return ""
            return f"{v:,.{dp}f}" if isinstance(v, float) else f"{v:,}"
        return str(v).replace("|", "/")
    dps = [fmt(c) for c in df.columns]
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(cell(v, d) for v, d in zip(row, dps)) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)

def gbp(x, dp=0):
    return f"£{x:,.{dp}f}"


def seller_revenue_section() -> list[str]:
    df = pd.read_csv(ROOT / "seller_growth" / "example_products.csv")
    out = []
    # headline table
    rows = []
    results = {}
    for k in ORDER:
        cfg = CATEGORIES[k]
        a = cfg.assumptions()
        p, s, pl = run_category(df, cfg.subcategories, a)
        results[k] = (cfg, a, p, s, pl)
        u = units_summary(p)
        rows.append({"Category": cfg.label, "Example products": len(p), "Example sellers": len(s),
                     "Est. units/month (Nov)": round(u["est_units_month"]),
                     "Avg selling price per unit (£)": round(u["avg_price"], 2) if u["est_units_month"] else "",
                     "Est. GMV/month (£)": round(u["est_gmv_month"]),
                     "Commission/month (£)": round(u["est_commission_month"]),
                     "Revenue to OnCommerce/month (£)": round(s["est_revenue_month"].sum())})
    out += ["## Units, GMV and revenue by category", "",
            f"{EXAMPLE_LABEL} Defaults, November 2026. The sellers are synthetic, so these numbers show how the "
            "method behaves, not the size of any OnBuy category.", "", md_table(pd.DataFrame(rows)), "",
            "Revenue to OnCommerce counts each seller's whole account (all categories), so it is larger than the "
            "category commission. Example sellers are separate in each category, so the column adds up.", ""]

    # worked examples on the heaters page
    cfg, a, p, s, pl = results["heaters"]
    top = p.sort_values("est_units_month", ascending=False).iloc[0].to_dict()
    steps, units, gmv = product_workings(top, a)
    out += ["## Worked example 1: from reviews to units and GMV", "",
            f"Heaters page, top-selling example listing: {top['title']} (seller {top['seller']}).", "",
            steps_markdown(steps), "",
            f"In one line: {int(top['product_review_count'])} reviews, about 1 in {1 / a.review_rate:.0f} buyers reviews, "
            f"so {top['product_review_count'] / a.review_rate:,.0f} sold to date; over "
            f"{top['review_window_months']:.0f} months that is {top['est_units_avg_month']:.1f} a month; x season factor "
            f"{top['season_index_now']:.2f} = {units:.1f} this month; x {gbp(top['avg_price'], 2)} average price = "
            f"{gbp(gmv)} GMV.", ""]
    sr = s.iloc[0].to_dict()
    rpo, n_cal = s.attrs["reviews_per_order"], s.attrs["calibration_sellers"]
    sample = json.loads((ROOT / "seller_growth" / "calibration_stats.json").read_text()).get("reviews_per_order_pooled")
    ssteps, total, _ = seller_value_workings(sr, a, rpo, n_cal)
    out += ["## Worked example 2: how orders, revenue and LTV are worked out for a seller", "",
            f"Heaters page, highest-revenue example seller: {sr['seller']} (order count: "
            f"{orders_source_label(sr['orders_source']).lower()}). This uses the seller's whole account, because "
            "subscription and commission are paid on the whole account. The same steps are in the expander 'How "
            "orders, revenue and LTV are worked out' under the Revenue per seller table on each page.", "",
            steps_markdown(ssteps), "",
            f"In this category alone the seller sells about {sr['climate_units_month']:.1f} units a month at an average "
            f"{gbp(sr['climate_avg_price'], 2)} = {gbp(sr['climate_gmv_month'])} GMV (seller GMV / seller units = "
            "average price).", ""]
    top_shown = str(sr["orders_source"]).startswith("SHOWN")
    other = s[s["orders_source"].str.startswith("EST" if top_shown else "SHOWN")]
    if len(other):
        er = other.iloc[0].to_dict()
        esteps, _, _ = seller_value_workings(er, a, rpo, n_cal)
        why = ("whose page shows no order count, so orders are estimated from seller reviews" if top_shown else
               "whose OnBuy seller box shows an order count, so no estimate is needed")
        out += [f"Step 1 for {er['seller']}, {why}:", "", steps_markdown(esteps[:1]), "",
                "Note on the ratio: " + reviews_per_order_text(rpo, n_cal, sample), ""]
    if len(pl):
        play = pl.iloc[0].to_dict()
        out += ["## Worked example 3: what an action is worth, and call or message?", "",
                f"Top-ranked action for Heaters: {play['play_type']} for {play['seller']} "
                f"(why: {plain_rule(play['rule'])}).", "", steps_markdown(action_economics_steps(play, a)), "",
                f"Why this route: {play['why_route']}", ""]

    # per category samples
    out += ["## Sample output for each category (example data, defaults)", ""]
    for k in ORDER:
        cfg, a, p, s, pl = results[k]
        u = units_summary(p)
        out += [f"### {cfg.label}", "",
                f"Subcategories: {', '.join(cfg.subcategories)}. Season pattern: {a.season_profile}. "
                f"Totals: {u['est_units_month']:,.0f} units x "
                + (f"{gbp(u['avg_price'], 2)}" if u["est_units_month"] else "n/a")
                + f" average price = {gbp(u['est_gmv_month'])} GMV this month.", ""]
        tp = p.sort_values(["est_units_month", "est_gmv_month"], ascending=False).head(10)
        prod_lines = ["Top 10 products by estimated units:", "", md_table(pd.DataFrame({
            "Product": tp["title"], "Seller": tp["seller"], "Reviews": tp["product_review_count"],
            "Badge": tp["badge"].fillna("").replace("", "none"),
            "In stock": (~tp["flag_out_of_stock"]).map({True: "yes", False: "no"}),
            "Est. units/month": tp["est_units_month"].round(1),
            "Avg selling price per unit (£)": tp["avg_price"].round(2),
            "Est. GMV/month (£)": tp["est_gmv_month"].round(0)})), ""]
        ts = s.head(10)
        out += ["Seller revenue breakdown (top 10 by revenue to OnCommerce; category columns first, then the whole "
                "account):", "", md_table(pd.DataFrame({
                    "Seller": ts["seller"], "Est. units/month here": ts["climate_units_month"].round(1),
                    "Avg selling price per unit (£)": ts["climate_avg_price"].round(2),
                    "Est. GMV/month here (£)": ts["climate_gmv_month"].round(0), "Tier": ts["tier"],
                    "Subscription (£)": ts["subscription_month"], "+ Commission (£)": ts["est_commission_month"].round(0),
                    "+ Boost (£)": ts["est_boost_month"].round(0), "= Revenue/month (£)": ts["est_revenue_month"].round(0)})),
                ""]
        if len(pl):
            tpl = top_play_per_seller(pl).head(10)
            out += ["Opportunity ranking (one primary action per seller, top 10):", "", md_table(pd.DataFrame({
                "Rank": tpl["rank"], "Seller": tpl["seller"], "Action": tpl["play_type"], "Status": tpl["status"],
                "Product": tpl["title"].fillna("").replace("", "(whole account)"), "Why": tpl["rule"].map(plain_rule),
                "At stake £/month": tpl["stake_month"].round(1), "Route": tpl["route"],
                "Net contribution £": tpl["net_contribution"].round(0), "Confidence": tpl["confidence"],
                "Review (days)": tpl["next_review_days"]})), ""]
            sm = portfolio_summary(s, pl, a)
            out += [f"{len(pl)} candidate actions; {sm['sellers']} sellers; {sm['actionable']} sellers with an "
                    f"actionable primary action ({sm['human']} calls, {sm['automated']} messages); "
                    f"{sm['deferred']} deferred until a fix is done; {sm['needs_validation']} need validation. Modelled "
                    f"net contribution {gbp(sm['net_contribution'])} over {a.value_horizon_months:g} months.", ""]
        out += prod_lines     # sellers and plays first, then products, as on the page
    return out


def break_even_section(a: Settings, example_play: dict | None = None) -> list[str]:
    be = break_even_stake(a)
    sm = survival_months(a)
    grid = break_even_grid(a).map(lambda v: gbp(v, 2) if v != float("inf") else "never")
    grid = grid.rename(columns=lambda c: f"{c} more often").reset_index()
    old_basis = Settings(contribution_margin=1.0, monthly_churn=0.0)
    old_all = Settings(contribution_margin=1.0, monthly_churn=0.0, call_cost_override=120, message_cost_override=2)
    out = ["## Why call vs message?", "",
           call_or_message_text(a), "",
           "### What a call and a message cost (rough estimates, not OnCommerce data)", "",
           cost_buildup_text(a), "",
           "| Item | Value | Type |", "|---|---|---|",
           f"| Seller Success exec, fully loaded cost a year | {gbp(a.sse_annual_cost)} | Assumption |",
           f"| Productive hours a year | {a.sse_productive_hours:,.0f} | Assumption |",
           f"| Hours per completed call (prep, attempts, call, follow-up, CRM notes) | {a.call_hours:g} | Assumption |",
           f"| Cost of one call | {gbp(a.sse_annual_cost, 0)} ÷ {a.sse_productive_hours:,.0f} × {a.call_hours:g} = "
           f"{gbp(a.human_cost, 2)} | Model estimate |",
           f"| Journey build and upkeep | {gbp(a.journey_build_cost)} | Assumption |",
           f"| Sellers reached | {a.journey_sellers_reached:,.0f} | Assumption |",
           f"| Sending cost per seller | {gbp(a.message_send_cost, 2)} | Assumption |",
           f"| Cost of one message | {gbp(a.journey_build_cost)} ÷ {a.journey_sellers_reached:,.0f} + "
           f"{gbp(a.message_send_cost, 2)} = {gbp(a.auto_cost, 2)} | Model estimate |", "",
           "### The tipping point (break-even)", "",
           "A Seller Success call is worth it when the platform revenue at stake a month is above "
           "(call cost − message cost) ÷ (OnCommerce margin × months still trading × (call success − message "
           "success)).", "",
           f"Months still trading: of the next {a.value_horizon_months:g} months a seller is expected to trade for "
           f"{sm:.2f}, because {a.monthly_churn:.0%} leave each month (0.97 + 0.97² + ... + 0.97¹²).", "",
           f"At the defaults: ({gbp(a.human_cost, 2)} − {gbp(a.auto_cost, 2)}) ÷ ({a.contribution_margin:.0%} × "
           f"{sm:.2f} × ({a.p_success_human:.0%} − {a.p_success_auto:.0%})) = {gbp(be, 2)} a month.", "",
           f"Before this version the tipping point was {gbp(break_even_stake(old_all), 2)}: a £120 call and £2 message "
           "(unsupported placeholders) on gross revenue over 12 months, with no margin and no churn. The new costs "
           f"alone on that old basis give {gbp(break_even_stake(old_basis), 2)}. Counting contribution rather than "
           f"revenue, and allowing for sellers who leave, raises it to {gbp(be, 2)}.", "",
           f"Tipping point, £ a month, for other call costs and success gaps (message cost {gbp(a.auto_cost, 2)}). "
           f"Rows: {GRID_CALL_LABEL.lower()}. Columns: {GRID_GAP_LABEL.lower()}.", "",
           md_table(grid), "", GRID_HOW_TO_READ, "",
           "Each action gets one line in plain words, in the form \"£X a month at stake, above the £Y "
           "tipping point, so call. Expected extra revenue £Z a month.\" (or below it, so send the message)."]
    if example_play is not None:
        out += ["", f"For example, the top-ranked action for Heaters: {play_sentence(example_play, a)}"]
    return out + [""]


AUDIT = [
    ("Call or message was judged on gross platform revenue over 12 months, with no OnCommerce margin and no "
     "seller churn.", "Calls looked better value than they are.",
     "Value is now platform revenue × 70% contribution margin × months still trading (9.9 of 12 at 3% churn) × "
     "success rate, minus the cost of the call or message."),
    ("The £120 call and £2 message costs were placeholders with no build-up.", "The tipping point (£49.17) had "
     "no support.", "Costs are built up from salary, productive hours and hours per call (£39.38), and from the "
     "journey build cost per seller plus sending (£0.80). All editable, all tagged Assumption."),
    ("Totals added every play, so a seller with three plays was counted three times and product plays overlapped "
     "with account plays.", "Expected value and the human/automated split were overstated (203 plays, £5,933 a "
     "month expected).", "One primary action per seller, plus an optional secondary. Only the primary is counted in "
     "totals and in the forecast."),
    ("The upgrade case counted the seller's extra sales at full margin, ignored commission on those sales, assumed "
     "a 5% (Partner) and 4% (Professional) sales lift with no evidence, and ignored the January 2028 price rise.",
     "Upgrades were recommended to sellers who might lose money.", "Seller gain = extra sales × (seller margin − "
     "commission) − extra fee. The lift defaults to 2%, is editable, and the upgrade is dropped if the seller is "
     "not better off. It is marked Needs validation if the tier or orders are estimated, the gain is thin, or the "
     "seller would lose money at the 2028 list price."),
    ("Retention counted the seller's whole monthly revenue as saved.", "Retention value was overstated: "
     "it assumed every at-risk seller would leave without help, taking all their revenue.", "Value at risk = "
     "revenue × 30% chance of losing the seller without help (Assumption); for a downgrade risk, only the "
     "difference between the two subscription prices."),
    ("Boost counted fees from sellers who would have boosted anyway, and could be suggested for duplicate pages, "
     "zero-sales listings or while a stock or listing problem was open.", "Boost value was overstated and could "
     "be recommended before a fix.", "Boost value is scaled by (1 − current Boost take-up); eligibility excludes "
     "out of stock, price problems, poor quality or duplicate pages, out of season, no sales and poor seller "
     "return; it must repay its own message; and it is deferred while the seller has a fix outstanding."),
    ("The overview said a seller appears on two category pages and ran one merged calculation, but the example "
     "seller names are per category.", "Unrelated synthetic sellers could be merged.", "The landing page sums "
     "per-category results and labels sellers as Seller (Category)."),
    ("Missing delivery fees (blank, not zero) produced blank values for listing-fix actions when the engine was "
     "called without the data loader.", "A blank value could drop out of totals unnoticed.", "Missing numbers now "
     "count as 0 inside the engine as well as in the loader; covered by a test."),
]


RPO = 1.0


def build() -> str:
    a = CATEGORIES["heaters"].assumptions()
    global RPO
    RPO = run_category(pd.read_csv(ROOT / "seller_growth" / "example_products.csv"), ("fan heaters",), a)[1] \
        .attrs["reviews_per_order"]
    cal = json.loads((ROOT / "seller_growth" / "calibration_stats.json").read_text())
    n_cal = sum(v["n_products"] for v in cal["categories"].values())
    df_all = pd.read_csv(ROOT / "seller_growth" / "example_products.csv")
    cats = [(k, CATEGORIES[k].label, CATEGORIES[k].subcategories, CATEGORIES[k].assumptions()) for k in ORDER]
    rows, tot, top5 = overview_by_category(df_all, cats)
    L = ["# Seller Revenue | Commercial Decision Support: overview", "",
         "Which sellers should we help, what should we recommend, and when is a human conversation worth more than "
         "an automated intervention?", "",
         f"Version {VERSION}. Generated by `tools/build_overview.py` from the code, at each category's default "
         f"settings, so the numbers match the app. Code: {REPO}.", "",
         "Portfolio project. Made by Ami Sata. A prototype for discussion, not production software.", "",
         "## Purpose", "",
         "A decision-support prototype for OnBuy (part of OnCommerce) seller revenue in climate control (Heaters, "
         "Fans, Dehumidifiers, Portable AC, Air Purifiers). For each seller: what they are worth to OnCommerce a "
         "month, one recommended next action (fix a sales leak, Boost, upgrade, retention or downgrade risk, or "
         "listing work), what it is worth after its cost, and whether a Seller Success call or an automated message "
         "is the better route. The calculations are plain Python rules. A person approves or overrides every "
         "recommendation, with a reason, and every decision is logged. An LLM is optional and only drafts message "
         "text.", "",
         "## Headline (illustrative)", "",
         EXAMPLE_LABEL, "",
         "| Measure | Value |", "|---|---|",
         f"| Est. platform revenue a month (each seller once) | {gbp(tot['revenue_month'])} |",
         f"| Actionable seller opportunities | {tot['actionable']} of {tot['sellers']} sellers |",
         f"| Modelled net contribution over 12 months, after intervention costs | {gbp(tot['net_contribution'])} "
         f"(costs {gbp(tot['intervention_cost'])}) |",
         f"| Human calls · automated journeys | {tot['human']} · {tot['automated']} |",
         f"| Not counted: sellers whose lead action is an upgrade that needs validation | "
         f"{tot['primary_needs_validation']} |", "",
         md_table(pd.DataFrame(rows)), "",
         "Top five opportunities:", "", md_table(top5), "",
         "These are model estimates from synthetic data and stated assumptions. None is a measured or claimed "
         "result.", "",
         "## Audit: what was wrong and what changed", "",
         "| Problem | Impact | Fix |", "|---|---|---|"] + [f"| {p_} | {i_} | {f_} |" for p_, i_, f_ in AUDIT] + [
         "", "Not changed, noted as limits: the badge-based unit floors are applied before seasonality is taken out, "
         "so off-season months can look slightly high for listings on a floor.", "",
         "## What is real and what is assumed", "",
         "| Item | Source |", "|---|---|",
         f"| Listing data | Example data: 20 synthetic products per category, calibrated on {n_cal} public OnBuy product "
         "pages viewed in November 2026. No raw marketplace data is included. Internal data can be loaded instead "
         "(schema in `data/README.md`). |",
         f"| Fees | [Published] subscriptions Standard £{a.sub_promo['Standard']:.0f}, Partner "
         f"£{a.sub_promo['Partner']:.0f} (list £{a.sub_list['Partner']:.0f}), Professional "
         f"£{a.sub_promo['Professional']:.0f} (list £{a.sub_list['Professional']:.0f}) a month, promo until January "
         f"2028; commission {a.commission_rate:.0%}, at least £{a.min_fee:.2f} an item; Boost fee levels "
         f"{', '.join(f'{k} {v:.0%}' for k, v in a.boost_levels.items())}. |",
         f"| Units sold | [Assumption] from review counts: 1 in {1 / a.review_rate:.0f} buyers leaves a review. |",
         "| Seasonality | [Assumption] a season factor per month (table below), my judgement. |",
         "| Costs and behaviour | [Assumption] seller tenure, average order value, Boost take-up, sales lift, success "
         "rates, the cost build-up for a call or a message, OnCommerce margin, churn. |",
         "| Estimates | [Model estimate] units, GMV, seller revenue, value at stake, net contribution. |",
         "| Where to change them | The Assumptions panel in the sidebar, per category, with Reset to defaults. |", "",
         "In the app every input is tagged Published, Observed in sample, Assumption or Model estimate, and every "
         "action has a confidence of Low or Medium (never High: nothing has been tested against OnBuy data).", "",
         "## Default settings", "",
         f"All assumptions are in one `Settings` object passed to every calculation. Defaults (Heaters page; the "
         f"settings hash for it is `{settings_hash(a)}`):", "",
         f"- Reviews: 1 in {1 / a.review_rate:.0f} buyers. Sales spread over the months since the first review where "
         f"every review is listed, otherwise {a.review_window_months:g} months (at least {a.min_window_months:g}). "
         f"Halve units if the newest review is older than {a.stale_after_months:g} months.",
         f"- Call success {a.p_success_human:.0%}, message success {a.p_success_auto:.0%}; call cost "
         f"{gbp(a.human_cost, 2)}, message cost {gbp(a.auto_cost, 2)} (built up in 'Why call vs message?'); value "
         f"counted over {a.value_horizon_months:g} months.",
         f"- Upgrade sales lift {a.partner_sales_uplift:.0%} (Partner), {a.pro_sales_uplift:.0%} (Professional); seller "
         f"margin {a.seller_margin:.0%}; chance an at-risk seller leaves without help {a.at_risk_loss_prob:.0%}.",
         f"- OnCommerce margin {a.contribution_margin:.0%}; seller churn {a.monthly_churn:.0%} a month; upgrades "
         f"{a.monthly_upgrade_rate:.0%} a month.",
         f"- Seller reviews to orders: 1 review per about {1 / RPO:.1f} orders ({RPO * 100:.1f} seller reviews per 100 "
         "orders; median of the sellers showing both numbers, explained in worked example 2).",
         f"- Average order value {gbp(a.avg_order_value)}; tenure {a.seller_tenure_months:g} months; Partner if at "
         f"least {a.partner_orders_k:g}k lifetime orders and no badge.",
         f"- Boost: {a.boost_adoption:.0%} of sellers on this page, level {a.boost_level}, "
         f"{a.boosted_share_of_gmv:.0%} of their sales boosted.", "",
         "## Every Seller Revenue formula in plain words", "",
         ]
    for term, meaning in GLOSSARY.items():
        L.append(f"- {term}: {meaning}")
    L += ["",
          "Units for one listing, step by step:", "",
          f"1. Count the reviews on the listing.",
          f"2. About 1 in {1 / a.review_rate:.0f} buyers leaves a review ({a.review_rate:.0%}), so reviews x "
          f"{1 / a.review_rate:.0f} = items sold to date.",
          f"3. Divide by the months the listing has been selling (time since the first review where all reviews are "
          f"listed, otherwise {a.review_window_months:g} months). That gives sales in an average month.",
          f"4. If the newest review is more than {a.stale_after_months:g} months old, halve it.",
          "5. Multiply by the season factor for the current month.",
          f"6. OnBuy badges set a minimum: Bestseller {a.bestseller_floor_units:g}, Hot {a.hot_floor_units:g}, In demand "
          f"{a.in_demand_floor_units:g} a month; a listing with no badge and no reviews counts as {a.no_signal_units:g}.",
          "7. Out of stock, or a price that looks wrong: 0 this month.",
          f"8. Where several sellers offer the product, the recommended offer wins {a.buybox_share:.0%} of its sales and "
          "the others share the rest.",
          "9. GMV = units x average selling price per unit (including delivery).",
          f"10. Commission = units x the larger of {a.commission_rate:.0%} of the delivered price and "
          f"£{a.min_fee:.2f}.", "",
          "What a seller is worth to OnCommerce a month:", "",
          "1. Lifetime orders: the order count in the OnBuy seller box (real, a minimum because of the +), or the seller's review count x about 15 (1 review per about 15 orders: the median "
          "orders per seller review among sellers that show both).",
          f"2. Orders a month = lifetime orders / {a.seller_tenure_months:g} months.",
          f"3. Sales a month for the whole account = orders a month x £{a.avg_order_value:g} average order.",
          f"4. Tier: Professional where the badge is shown; otherwise Partner if at least {a.partner_orders_k:g}k "
          "lifetime orders, else Standard. Subscription from the published price list.",
          f"5. Commission = {a.commission_rate:.0%} x sales.",
          f"6. Boost fees = share of sellers using Boost x share of their sales boosted ({a.boosted_share_of_gmv:.0%}) x "
          f"Boost fee level ({a.boost_level}, {a.boost_levels[a.boost_level]:.0%}) x sales. The share using Boost is set "
          "per category (Heaters 25%, Fans 10% and so on).",
          "7. Revenue = subscription + commission + Boost fees.",
          f"8. Lifetime value = revenue x {a.contribution_margin:.0%} OnCommerce margin / {a.monthly_churn:.0%} monthly "
          f"churn (a seller stays about {1 / a.monthly_churn:.0f} months on average).",
          f"9. Forecast: each month {a.monthly_churn:.0%} of sellers leave, {a.monthly_upgrade_rate:.0%} move up a tier, "
          "prices step up to list in January 2028, and accepted plays add their expected value over three months.", "",
          "Season factors (1.0 is an average month; my judgement for the UK, not OnBuy data):", "",
          season_table(a), "",
          "## The decision workflow", "",
          "1. Load the category's listings (here, example data) and the published fees.",
          "2. Work out units, average price, GMV and commission for each listing.",
          "3. Work out each seller's revenue to OnCommerce and tier.",
          "4. Run the action rules below; each candidate action gets the platform revenue at stake a month.",
          "5. Value each action for a call and for a message: stake × OnCommerce margin × months still trading × "
          "success rate, minus the cost. The route with the higher net value wins.",
          "6. Fix first: if a seller has a stock, price, delivery, duplicate-page or listing problem, Boost and "
          "upgrades are deferred. Upgrades the seller may not benefit from are marked Needs validation.",
          "7. One primary action per seller (the highest net contribution not deferred), plus an optional secondary. "
          "Only the primary is counted in totals. Sellers are ranked by that net contribution, not by fee size.",
          "8. Each action gets a rule-based review date: 14 days for a stock or price fix, 30 for Boost, delivery, "
          "duplicate pages, listing work and retention, 60 for an upgrade.",
          "9. A draft message is written by rules, or by an LLM if one is set up. "
          "The LLM sees only the topic, seller, product, reason, listing facts and published fees, never the route, "
          "the decision or an estimated £ figure, and the page labels each draft \"Drafted by rules\" or "
          "\"Drafted by LLM\".",
          "10. The category manager approves or overrides each action, with a reason for an override. Every decision goes "
          "into a decision log (timestamp, page, seller, product, play, at_stake, route, expected_mo, decision, "
          "reason, settings_hash) that can be downloaded as a CSV.", "",
          "Play rules:", ""]
    L += [f"- {k}: {v}" for k, v in play_rules(a).items()]
    L += ["", "Routing: " + routing_rule(a), "",
          "## Sensitivity: how much the answer moves with the weakest assumptions", "",
          "Heaters, one assumption moved at a time, the rest at defaults. Platform revenue does not move with the "
          "review rate because seller revenue comes from order counts, not product reviews.", "",
          md_table(sensitivity_table(df_all, CATEGORIES["heaters"].subcategories, a)), ""]
    hp = run_category(pd.read_csv(ROOT / "seller_growth" / "example_products.csv"),
                      CATEGORIES["heaters"].subcategories, a)[2]
    sr = seller_revenue_section()
    w1 = sr.index("## Worked example 1: from reviews to units and GMV")
    s0 = sr.index("## Sample output for each category (example data, defaults)")
    cut = L.index("## What is real and what is assumed")
    # same order as the pages: results, sellers and plays first; why call vs message next; method after
    L = (L[:cut] + sr[:w1] + sr[s0:] + break_even_section(a, hp.iloc[0].to_dict() if len(hp) else None)
         + ["## Method and formulas", "", "The rest of this document shows how the numbers above are worked out.", ""] + L[cut:] + sr[w1:s0])
    L += ["## Limits", "",
          "- The OnBuy data is synthetic. It copies the shape of a small sample found through search, which favours "
          "listings that rank well. It says nothing about any real seller.",
          "- Units are inferred from reviews. Every £ figure scales with them.",
          "- Season factors, success rates, the upgrade sales lift, the chance an at-risk seller leaves and the cost "
          "build-up for calls and messages are judgement, not data. None has been tested against OnBuy results.",
          "- Fix first is applied per seller, so a small fix can hold back a larger upgrade; the upgrade still shows "
          "as a deferred secondary action.",
          "- The badge-based unit floors are applied before seasonality is taken out, so off-season months can look "
          "slightly high for listings on a floor.",
          "- This is a prototype for discussion, not production software.",
          "- OnBuy's website terms restrict automated collection and reuse of its content, so the repository ships "
          "synthetic data only.", "",
          FOOTER, ""]
    text = "\n".join(L)
    for bad in ("\u2014", "\u2013"):
        assert bad not in text, "dash found"
    return text


def to_pdf(md_text: str, pdf: Path) -> None:
    import markdown  # pip install markdown
    body = markdown.markdown(md_text, extensions=["tables"])
    css = ("body{font-family:Arial,Helvetica,sans-serif;font-size:9.5pt;line-height:1.35;margin:0 6mm}"
           "h1{font-size:18pt}h2{font-size:13pt;margin-top:16pt;border-bottom:1px solid #ccc}h3{font-size:11pt}"
           "table{border-collapse:collapse;margin:6pt 0;font-size:8pt;page-break-inside:auto}"
           "td,th{border:1px solid #bbb;padding:2pt 4pt;vertical-align:top}th{background:#f0f0f0}"
           "tr{page-break-inside:avoid}")
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "overview.html"
        h.write_text(html, encoding="utf-8")
        subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", h.as_uri()], check=True, capture_output=True, timeout=120)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--pdf", type=Path)
    args = ap.parse_args()
    text = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    if args.pdf:
        to_pdf(text, args.pdf)
        print(f"wrote {args.pdf}")


if __name__ == "__main__":
    main()
