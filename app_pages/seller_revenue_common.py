"""
app_pages/seller_revenue_common.py - shared page renderer for the per-category Seller Revenue pages.

Each climate-control category (heaters, fans, dehumidifiers, portable AC, air purifiers) has its own page
and category manager. The page files are thin: they call render("<key>"). Everything category-specific
(products, sellers, defaults, notes) comes from seller_growth/categories.py; the maths is seller_growth/revenue.py.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_pages.shared import (banner, why_call_vs_message, data_sidebar, decision_log_section, guarded,  # noqa: E402
                               log_decision, play_line, settings_sidebar)
from seller_growth.agent import draft_outreach, drafted_by  # noqa: E402
from seller_growth.categories import CATEGORIES, CategoryConfig  # noqa: E402
from seller_growth.workings import (GLOSSARY, play_rules, plain_rule, product_workings,  # noqa: E402
                                    routing_rule, routing_workings, seller_workings)
from seller_growth.revenue import (AUTOMATED, HUMAN, PLAY_TYPES, Settings, break_even_stake,  # noqa: E402
                                   forecast, leakage_summary, revenue_mix, run_category, top_play_per_seller,
                                   units_summary)

CALIBRATION = ROOT / "seller_growth" / "calibration_stats.json"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
U_COL, P_COL, G_COL = "Est. units/month", "Avg selling price per unit (£)", "Est. GMV/month (£)"


ASSUMPTION_LABELS = {
    "commission_rate": ("Commission rate", "[Real, published]"),
    "ac_dehum_as_large_appliance": ("Treat as Large Appliances (7%)", "[Assumed]"),
    "sub_promo": ("Subscription £/month now", "[Real, published]"),
    "sub_list": ("Subscription £/month from Jan 2028", "[Real, published]"),
    "min_fee": ("Minimum fee per sale £", "[Real, published]"),
    "review_rate": ("Share of buyers who leave a review", "[Assumed]"),
    "use_first_review_window": ("Spread sales over months since first review", "[Assumed]"),
    "review_window_months": ("Review window if oldest review unknown (months)", "[Assumed]"),
    "stale_after_months": ("Newest review older than this = stale (months)", "[Assumed]"),
    "stale_factor": ("Stale listing units multiplier", "[Assumed]"),
    "bestseller_floor_units": ("Units floor: OnBuy 'Bestseller'", "[Assumed] (the badge is real)"),
    "hot_floor_units": ("Units floor: OnBuy 'Hot'", "[Assumed] (the badge is real)"),
    "in_demand_floor_units": ("Units floor: OnBuy 'In demand'", "[Assumed] (the badge is real)"),
    "no_signal_units": ("Units floor: no badge, no reviews", "[Assumed]"),
    "season_profiles": ("Season factors by month", "[Assumed]"),
    "season_profile": ("Seasonality profile", "[Assumed]"),
    "seasonality_strength": ("Seasonality strength", "[Assumed]"),
    "current_month": ("Month of the snapshot", "[Real, published]"),
    "buybox_share": ("Recommended offer's share of sales", "[Assumed]"),
    "seller_tenure_months": ("Months over which lifetime orders built up", "[Assumed]"),
    "seller_reviews_per_order": ("Seller reviews per order (blank = calibrated)", "[Assumed]"),
    "avg_order_value": ("Average order value across catalogue £", "[Assumed]"),
    "partner_orders_k": ("No badge: Partner if lifetime orders ≥ k", "[Assumed]"),
    "boost_adoption": ("Share of sellers running Boost", "[Assumed]"),
    "boost_levels": ("Boost fee per level", "[Real, published]"),
    "boost_level": ("Average Boost level", "[Assumed] (levels are published)"),
    "boosted_share_of_gmv": ("Share of adopter sales through boosted slots", "[Assumed]"),
    "boost_incremental_share": ("Incremental sales from Boost", "[Assumed]"),
    "seller_margin": ("Seller gross margin before fees", "[Assumed]"),
    "partner_sales_uplift": ("Sales lift from Partner features", "[Assumed]"),
    "pro_sales_uplift": ("Extra lift from Professional features", "[Assumed]"),
    "churn_fee_ratio": ("Churn risk if subscription ÷ GMV above", "[Assumed]"),
    "p_success_human": ("Success rate, human", "[Assumed]"),
    "p_success_auto": ("Success rate, automated", "[Assumed]"),
    "human_cost": ("Cost to serve, human £", "[Assumed]"),
    "auto_cost": ("Cost to serve, automated £", "[Assumed]"),
    "monthly_churn": ("Monthly seller churn", "[Assumed]"),
    "monthly_upgrade_rate": ("Monthly upgrade rate", "[Assumed]"),
    "contribution_margin": ("OnCommerce margin (LTV)", "[Assumed]"),
    "play_ramp_months": ("Months for plays to ramp in", "[Assumed]"),
    "first_sale_units": ("Units a fixed zero-review listing could reach", "[Assumed]"),
    "fix_uplift": ("Uplift from a listing fix", "[Assumed]"),
    "delivery_uplift": ("Uplift from free / faster delivery", "[Assumed]"),
    "merge_uplift": ("Uplift from merging duplicate pages", "[Assumed]"),
    "quality_threshold": ("Listing quality threshold /100", "[Assumed]"),
    "price_gap_threshold": ("Price gap vs lowest offer that blocks Boost", "[Assumed]"),
}


def assumptions_table(cfg: CategoryConfig, a: Settings) -> pd.DataFrame:
    default = asdict(cfg.assumptions())
    now_ = asdict(a)
    rows = []
    for key, (label, kind) in ASSUMPTION_LABELS.items():
        v, dv = now_[key], default[key]
        rows.append({"Assumption": label, "Value now": str(v) + (" (changed)" if v != dv else ""),
                     "Why this default for this category": cfg.why.get(key, ""), "Type": kind,
                     "Page default": str(dv)})
    return pd.DataFrame(rows)


def render_workings(cfg, a, products, sellers, plays, month) -> None:
    """Plain step-by-step workings: one product (units to GMV) and one seller (revenue breakdown)."""
    with st.expander("How these numbers are worked out", expanded=False):
        st.markdown("Plain words for the main columns:")
        for term, meaning in GLOSSARY.items():
            st.markdown(f"- {term}: {meaning}")
        if products.empty:
            return
        st.markdown("#### From reviews to units and GMV, for one product")
        order = products.sort_values("est_units_month", ascending=False)
        names = dict(zip(order["product_id"], order["title"]))
        pid = st.selectbox("Product", list(names), format_func=lambda x: names[x], key=f"{cfg.key}_wk_prod")
        row = products[products["product_id"] == pid].iloc[0].to_dict()
        steps, units, gmv = product_workings(row, a)
        st.table(pd.DataFrame(steps).rename(columns=str.capitalize).set_index("Step"))
        st.caption("Category totals add the same numbers up over every listing on this page.")
        st.markdown("#### What a seller is worth to OnCommerce a month")
        sids = sellers["seller"].tolist()
        sid = st.selectbox("Seller", sids, key=f"{cfg.key}_wk_seller")
        srow = sellers[sellers["seller"] == sid].iloc[0].to_dict()
        ssteps, total = seller_workings(srow, a, sellers.attrs["reviews_per_order"])
        st.table(pd.DataFrame(ssteps).rename(columns=str.capitalize).set_index("Step"))
        st.caption("This uses the seller's whole account (every category they sell in), because subscription and "
                   "commission are paid on the whole account. 'Assumed' inputs are the sliders in the sidebar.")


def get_draft(play: dict, a: Settings, k: str) -> dict:
    cache = st.session_state.setdefault(f"{k}_drafts", {})
    key = (play["play_id"], play["seller"], play["play_type"], a.to_json())
    if key not in cache:
        with st.spinner("Drafting..."):
            cache[key] = draft_outreach(play, a)
    return cache[key]


def render(key: str) -> None:
    cfg = CATEGORIES[key]
    k = cfg.key
    all_products, is_example, source = guarded(data_sidebar)
    a = guarded(settings_sidebar, cfg, all_products)
    products, sellers, plays = guarded(run_category, all_products, cfg.subcategories, a)
    u = units_summary(products)
    mix = revenue_mix(sellers)
    leak = leakage_summary(products, a)
    month = MONTHS[a.current_month - 1]

    st.title(f"Seller Revenue: {cfg.label}")
    banner(is_example, source)
    st.caption(f"OnBuy (OnCommerce) · climate control · {', '.join(cfg.subcategories)} · for the {cfg.label} "
               "category manager")
    st.markdown(
        f"Decision support for the {cfg.label.lower()} category manager. For each seller: estimated units sold, what "
        "the seller is worth to OnCommerce (subscription, commission and Boost), the next play (upgrade, retention, "
        "Boost, listing fix or leakage) and whether it should be an automated message or a Seller Success call. "
        "The calculations are plain-Python rules. An LLM, if configured, only drafts the message text and never sees "
        "or changes a route, a decision or an estimate. You accept or override every play.")

    # Headline ------------------------------------------------------------------
    st.subheader("Results")
    h = st.columns(5)
    h[0].metric("Products", len(products))
    h[1].metric("Sellers", len(sellers))
    h[2].metric(f"Est. units/month ({month})", f"{u['est_units_month']:,.0f}",
                help="Sum over this category's listings. See 'How these numbers are worked out'.")
    h[3].metric("Avg selling price per unit", f"£{u['avg_price']:,.2f}" if u["est_units_month"] else "n/a",
                help="Category GMV ÷ category units, so it is weighted by what sells.")
    h[4].metric(f"Est. GMV/month ({month})", f"£{u['est_gmv_month']:,.0f}",
                help="Units × average selling price per unit.")
    h2 = st.columns(5)
    h2[0].metric("Est. category commission / month", f"£{u['est_commission_month']:,.0f}")
    h2[1].metric("Revenue to OnCommerce / month", f"£{sellers['est_revenue_month'].sum():,.0f}",
                 help="Subscription + commission + Boost fees across each seller's whole account (all categories). "
                      "A seller listed in two categories appears on both pages.")
    if u["est_units_month"]:
        st.caption(f"Category check: {u['est_units_month']:,.0f} units × £{u['avg_price']:,.2f} average price = "
                   f"£{u['est_gmv_month']:,.0f} GMV this month.")

    # Sellers -----------------------------------------------------------------
    st.subheader("1. Revenue per seller (to OnCommerce, per month)")
    st.caption(f"Left block: this category only. Avg selling price per unit = the seller's GMV here ÷ their units "
               f"here. Right block: the seller's whole account, worked out as lifetime orders ÷ "
               f"{a.seller_tenure_months:g} months × £{a.avg_order_value:g} average order (assumed), then revenue = "
               "subscription + commission + Boost. Tier is Professional only where the badge is shown; otherwise "
               "estimated from lifetime orders. 'How these numbers are worked out', under Method and formulas further down, "
               "shows one seller step by step.")
    tbl = pd.DataFrame({
        "Seller": sellers["seller"],
        f"{U_COL} ({cfg.label})": sellers["climate_units_month"].round(1),
        f"{P_COL} ({cfg.label})": sellers["climate_avg_price"].round(2),
        f"{G_COL} ({cfg.label})": sellers["climate_gmv_month"].round(0),
        f"{cfg.label} commission £/mo": sellers["climate_commission_month"].round(1),
        "Tier": sellers["tier"], "Tier source": sellers["tier_source"],
        "Lifetime orders": sellers["lifetime_orders"].round(0), "Orders source": sellers["orders_source"],
        "Account orders / month": sellers["est_orders_month"].round(0),
        "Account GMV £/mo": sellers["est_account_gmv_month"].round(0),
        "Subscription £/mo": sellers["subscription_month"],
        "+ Commission £/mo": sellers["est_commission_month"].round(0),
        "+ Boost £/mo": sellers["est_boost_month"].round(0), "= Revenue £/mo": sellers["est_revenue_month"].round(0),
        "Subscription as % of sales": (sellers["fee_to_sales"].clip(upper=9.99) * 100).round(1),
        "Same, after Jan 2028": (sellers["fee_to_sales_list"].clip(upper=9.99) * 100).round(1),
        "Lifetime value £": sellers["ltv"].round(0),
        "Products (recommended offer)": sellers["products_buybox"], "Offers": sellers["offers_in_sample"],
    })
    st.dataframe(tbl, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.1f%%") for c in
                                ["Subscription as % of sales", "Same, after Jan 2028"]})
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("**Revenue mix (sellers on this page, £/month)**")
        st.bar_chart(pd.DataFrame({"£/month": mix}), horizontal=True)
        tot = sum(mix.values()) or 1
        st.caption(" · ".join(f"{n} {v / tot:.0%}" for n, v in mix.items()))
    with c2:
        st.markdown("**Subscription revenue by tier (£/month)**")
        st.bar_chart(sellers.groupby("tier")["subscription_month"].sum()
                     .reindex(["Standard", "Partner", "Professional"]).fillna(0))
        st.caption("Partner/Professional on promo prices until Jan 2028; at list prices the same mix would be "
                   f"£{sum(a.sub_list[t] for t in sellers['tier']):,.0f}/month vs "
                   f"£{sellers['subscription_month'].sum():,.0f} today.")

    # Plays -------------------------------------------------------------------
    st.subheader("2. Plays, ranked by expected £/month")
    st.caption(routing_rule(a))
    with st.expander("Play rules in plain words"):
        for name, rule in play_rules(a).items():
            st.markdown(f"- {name}: {rule}")
    if plays.empty:
        st.info("No plays for this category at the current assumptions.")
        why_call_vs_message(a)
    else:
        types = st.multiselect("Play types", PLAY_TYPES, default=PLAY_TYPES, key=f"{k}_types")
        view = plays[plays["play_type"].isin(types)].reset_index(drop=True)
        units_by_pid = products.set_index("product_id")["est_units_month"]
        pidx = products.set_index("product_id")
        table = pd.DataFrame({
            "Rank": view["rank"], "Play": view["play_type"], "Seller": view["seller"],
            "Product": view["title"].str.slice(0, 50),
            U_COL: view["product_id"].map(pidx["est_units_month"]).round(1),
            P_COL: view["product_id"].map(pidx["avg_price"]).round(2),
            G_COL: view["product_id"].map(pidx["est_gmv_month"]).round(0),
            "Why": view["rule"].map(plain_rule), "£ at stake / mo": view["stake_month"].round(1),
            "Route": view["route"], "Expected £/mo": view["expected_month"].round(1),
            "Decision line": [play_line(p_, a) for p_ in view.to_dict("records")]})
        event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                             key=f"{k}_plays")
        rc = plays["route"].value_counts()
        st.caption(f"{len(plays)} plays · {rc.get(HUMAN, 0)} human · {rc.get(AUTOMATED, 0)} automated · "
                   f"total expected £{plays['expected_month'].sum():,.0f}/month")
        why_call_vs_message(a)
        ids = view["play_id"].tolist()
        if ids:
            rows = event.selection.rows if event is not None and hasattr(event, "selection") else []
            picked = ids[rows[0]] if rows else None
            if picked and st.session_state.get(f"_{k}_last") != picked:
                st.session_state[f"{k}_pick"] = picked
            st.session_state[f"_{k}_last"] = picked
            if st.session_state.get(f"{k}_pick") not in ids:
                st.session_state.pop(f"{k}_pick", None)
            labels = {r.play_id: f"#{r.rank} {r.play_type}, {r.seller}" for r in view.itertuples()}
            pid = st.selectbox("Play", ids, format_func=lambda x: labels[x], key=f"{k}_pick")
            play = view[view["play_id"] == pid].iloc[0].to_dict()
            draft = get_draft(play, a, k)
            left, right = st.columns([3, 2])
            with left:
                st.markdown(f"#### {play['play_type']}: {play['seller']}")
                st.markdown(play_line(play, a))
                st.markdown(f"Route {play['route']} (set by the rules) · confidence {draft['confidence']} · "
                            f"{drafted_by(draft)}")
                if draft.get("note"):
                    st.caption(draft["note"])
                st.markdown(f"**Subject:** {draft['subject']}")
                st.markdown("**Message to seller (draft):**")
                st.info(draft["message"])
                if play["route"] == HUMAN:
                    st.markdown("**Call brief for Seller Success:**  \n" + draft["call_brief"].replace("\n", "  \n"))
                st.markdown(f"**What data would change this:** {draft['additional_data']}")
            with right:
                st.markdown("**Evidence** (est. = estimate)")
                est_words = ("est_", "gmv", "units", "season", "roi", "breakeven", "fee_to_sales", "gain", "revenue")
                ev = {(("est. " if any(w in n for w in est_words) else "") + n.replace("season_index", "season_factor")
                       .replace("_", " ")):
                      (round(v, 2) if isinstance(v, float) else v) for n, v in play["evidence"].items()}
                st.table(pd.DataFrame({"Value": [str(v) for v in ev.values()]}, index=list(ev.keys())))
                st.markdown("**Call or automated message?**")
                st.table(pd.DataFrame(routing_workings(play, a)).rename(columns=str.capitalize).set_index("Step"))
                if play.get("product_id"):
                    url = products.loc[products["product_id"] == play["product_id"], "url"].dropna()
                    url = url[url.astype(str).str.startswith("http")]
                    if len(url):                   # example data has no URLs, so no link is shown
                        st.markdown(f"[Open the OnBuy page]({url.iloc[0]})")
            with st.container(border=True):
                st.markdown(f"Your decision on {pid}. Suggested: {play['play_type']}, via {play['route']}.")
                reason = st.text_area("Reason (required to override)", key=f"{k}_reason_{pid}")
                alt = st.selectbox("If overriding, what instead?",
                                   ["Reject, no action", "Switch route (human ↔ automated)", "Lower priority",
                                    "Raise priority", "Different play (explain in reason)"], key=f"{k}_alt_{pid}")
                b1, b2 = st.columns(2)
                if b1.button("Accept", key=f"{k}_acc_{pid}", width="stretch"):
                    log_decision(cfg.label, play, "accept", reason.strip(), a)
                    st.success(f"Saved: accepted {pid}.")
                if b2.button("Override", key=f"{k}_ovr_{pid}", width="stretch"):
                    if not reason.strip():
                        st.error("Please give a reason for the override.")
                    else:
                        log_decision(cfg.label, play, f"override: {alt}", reason.strip(), a)
                        st.success(f"Saved: override ({alt}) for {pid}.")
        with st.expander("Next best play per seller (one row per seller)"):
            tp = top_play_per_seller(plays)
            st.dataframe(pd.DataFrame({"Seller": tp["seller"], "Top play": tp["play_type"], "Route": tp["route"],
                                       "Expected £/mo": tp["expected_month"].round(1)}),
                         hide_index=True, width="stretch")

    # Products -----------------------------------------------------------------
    st.subheader("3. Products: est. units, average price and GMV per month")
    pt = pd.DataFrame({
        "Product": products["title"].str.slice(0, 55), "Type": products["subcategory"], "Seller": products["seller"],
        U_COL: products["est_units_month"].round(1),
        P_COL: products["avg_price"].round(2),
        G_COL: products["est_gmv_month"].round(0),
        "Units, average month": products["est_units_avg_month"].round(1),
        "Season factor": products["season_index_now"].round(2),
        "Reviews": products["product_review_count"], "Months selling": products["review_window_months"].round(0),
        "Latest review": products["latest_review"], "OnBuy badge": products["badge"],
        "In stock": ~products["flag_out_of_stock"], "Price £": products["price"], "Delivery £": products["delivery_fee"],
        "Offers": products["offers_count"],
        "Commission £/mo": products["est_commission_month"].round(1),
        "Quality /100": products["quality_score"], "Issues": products["quality_issues"],
    }).sort_values(U_COL, ascending=False)
    st.dataframe(pt, hide_index=True, width="stretch")
    st.caption("Reviews, dates, badges, stock, prices and offers are example inputs; units, GMV and commission are "
               "estimates from them. GMV = units × average selling price per unit (incl. delivery; weighted across "
               "sellers where several offer the product). Season factor: how busy this month is against an average "
               "month (1.0 = average).")

    # Leakage -----------------------------------------------------------------
    st.subheader("4. Revenue leakage check")
    lk = st.columns(5)
    lk[0].metric("Sales under the min-fee floor", leak["min_fee_floor_products"],
                 help=f"The floor only binds below £{leak['min_fee_breakeven_price']:.2f}; cheapest item here is "
                      f"£{leak['cheapest_delivered_price']:.2f}.")
    lk[1].metric("Out of stock", leak["out_of_stock_products"])
    lk[2].metric("Units lost to OOS / month", f"{u['lost_units_month']:,.0f}")
    lk[3].metric("Commission lost to OOS / month", f"£{leak['lost_commission_oos_month']:,.0f}")
    lk[4].metric("Duplicate pages · price anomalies", f"{leak['duplicate_pages']} · {leak['price_anomalies']}")

    # Forecast ----------------------------------------------------------------
    st.subheader("5. 12-month forecast and LTV")
    months = st.slider("Months", 12, 24, 12, 1, key=f"{k}_months",
                       help="Go past 13 months to see the Jan 2028 step from promo to list prices.")
    fc = forecast(sellers, plays, products, a, months)
    f1, f2 = st.columns([3, 2])
    with f1:
        st.markdown("**Revenue to OnCommerce from these sellers, £/month: base vs with plays**")
        st.line_chart(fc.set_index("month")[["base", "with_plays"]], x_label="", y_label="£ / month")
        st.caption(f"Base = this seller cohort with {a.monthly_churn:.1%} monthly churn and "
                   f"{a.monthly_upgrade_rate:.1%} monthly upgrades, no new sign-ups. With plays = base + each play's "
                   f"expected £/month, ramped in over {a.play_ramp_months} months.")
    with f2:
        st.markdown(f"**{cfg.label}: est. units sold by month ({a.season_profile} profile)**")
        st.bar_chart(fc.set_index("month")[["category_units"]], x_label="", y_label="units / month")
        st.caption("In-stock, correctly priced listings: average-month units × that month's season factor. "
                   f"Category commission over the period: £{fc['climate_commission'].sum():,.0f}.")
    m = st.columns(4)
    m[0].metric("Base, 12-month total", f"£{fc['base'].head(12).sum():,.0f}")
    m[1].metric("With plays, 12-month total", f"£{fc['with_plays'].head(12).sum():,.0f}",
                f"+£{(fc['with_plays'] - fc['base']).head(12).sum():,.0f}")
    m[2].metric("Units, next 12 months", f"{fc['category_units'].head(12).sum():,.0f}")
    m[3].metric("LTV, median seller", f"£{sellers['ltv'].median():,.0f}" if len(sellers) else "n/a",
                help="Lifetime value = monthly revenue × OnCommerce margin ÷ monthly churn. With 3% churn a seller stays "
                     "about 33 months on average.")

    # Method and formulas -----------------------------------------------------
    st.subheader("Method and formulas")
    st.markdown(
        f"- Units a month = product reviews × {1 / a.review_rate:,.0f} (1 in {1 / a.review_rate:,.0f} buyers reviews) "
        "÷ months selling × this month's season factor; halved if the newest review is older than "
        f"{a.stale_after_months:g} months; 0 if out of stock or mispriced.\n"
        "- GMV a month = units × average selling price per unit (price plus delivery, weighted across offers).\n"
        "- Revenue to OnCommerce a month = subscription + commission (at least the minimum fee per item) + Boost fees.\n"
        "- Each play has a £ at stake a month. Expected £ a month = £ at stake × success rate of the route chosen.")
    render_workings(cfg, a, products, sellers, plays, month)

    # Data vs assumptions ------------------------------------------------------
    st.subheader("Data vs assumptions")
    cal = json.loads(CALIBRATION.read_text())["categories"][k]
    r_col, a_col = st.columns([2, 3])
    with r_col:
        st.markdown("#### Data on this page")
        pro = int(sellers["tier_source"].str.startswith("SHOWN").sum())
        reviewed = int((products["product_review_count"] > 0).sum())
        if is_example:
            st.markdown(
                f"- Listing inputs are example data: {len(products)} synthetic products and {len(sellers)} synthetic "
                "sellers, generated by `tools/gen_example_data.py` (seed 2026). No real titles, brands, sellers, "
                "URLs or EANs.\n"
                "- Distributions calibrated against a small sample of public OnBuy product pages viewed in November "
                "2026. No raw marketplace data is included.")
        else:
            st.markdown(f"- Listing inputs: {source}, {len(products)} products and {len(sellers)} sellers.")
        st.markdown(
            f"- In the data: {reviewed} listings with reviews, {pro} sellers with a Professional badge, "
            f"{leak['out_of_stock_products']} out of stock, {leak['paid_delivery_products']} with paid delivery, "
            f"{leak['price_anomalies']} price anomalies.\n"
            f"- [Real, published] subscriptions £{a.sub_promo['Standard']:.0f} / £{a.sub_promo['Partner']:.0f} / "
            f"£{a.sub_promo['Professional']:.0f} (promo to Jan 2028; list £{a.sub_list['Partner']:.0f} / "
            f"£{a.sub_list['Professional']:.0f}), {a.commission_rate:.0%} commission, £{a.min_fee:.2f} minimum "
            "(oncommerce.com/gb/onbuy); Boost fee 5% to 30% (channelx.world, sellerbookkeeping.uk).")
        with st.expander("Calibration targets (aggregates from the sample)"):
            badge = ", ".join(f"{b_} {v:.0%}" for b_, v in cal["badge_mix"].items())
            st.markdown(
                f"- Sample size: {cal['n_products']} product pages, {cal['n_sellers']} sellers.\n"
                f"- Price: median £{cal['price']['median']:.0f}, range £{cal['price']['min']:.0f} to "
                f"£{cal['price']['max']:.0f} (price anomalies excluded).\n"
                f"- Listings with no reviews: {cal['reviews_zero_share']:.0%}; median reviews where any: "
                f"{cal['reviews_nonzero'].get('median', 0):g}.\n"
                f"- OnBuy badges: {badge}.\n"
                f"- Out of stock {cal['out_of_stock_share']:.0%}, paid delivery {cal['paid_delivery_share']:.0%}, "
                f"price anomalies {cal['price_anomaly_share']:.0%}, overseas dispatch {cal['overseas_dispatch_share']:.0%}.\n"
                f"- Sellers showing an order count: {cal['seller_orders_shown_share']:.0%}; Professional badge "
                f"{cal['professional_share']:.0%}.")
            for n in cfg.real_notes:
                st.markdown(f"- Observed in the sample: {n}")
    with a_col:
        st.markdown("#### Assumptions (all in the sidebar)")
        st.dataframe(assumptions_table(cfg, a), hide_index=True, width="stretch", height=300)
        st.caption("Not available publicly: OnBuy's GMV, units, tiers, Boost spend and churn. Units are the main "
                   "estimate. Every £ figure on this page scales with them.")

    decision_log_section(cfg.label)
