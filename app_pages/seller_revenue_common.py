"""
app_pages/seller_revenue_common.py - renderer for one climate-control category (heaters, fans, dehumidifiers,
portable AC, air purifiers). The single "Seller opportunities" page picks a category and calls render("<key>").
Everything category-specific
(products, sellers, defaults, notes) comes from seller_growth/categories.py; the maths is seller_growth/revenue.py.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_pages.shared import (sample_ratio_stats, why_call_vs_message, data_sidebar, decision_log_section,  # noqa: E402
                               guarded, headline_metrics, log_decision, settings_sidebar)
from seller_growth.agent import draft_outreach, drafted_by  # noqa: E402
from seller_growth.categories import CATEGORIES, CategoryConfig  # noqa: E402
from seller_growth.workings import (GLOSSARY, action_economics_steps, action_text, evidence_rows,  # noqa: E402
                                    orders_source_label, plain_rule, play_rules, product_workings,
                                    reviews_per_order_text, routing_rule, seller_situation, seller_value_workings,
                                    seller_workings)
from seller_growth.revenue import (HUMAN, PLAY_TYPES, Settings, forecast, leakage_summary,  # noqa: E402
                                   portfolio_summary, revenue_mix, run_category, sensitivity_table, survival_months,
                                   top_play_per_seller, units_summary)

CALIBRATION = ROOT / "seller_growth" / "calibration_stats.json"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
U_COL, P_COL, G_COL = "Est. units/month", "Avg selling price per unit (£)", "Est. GMV/month (£)"


ASSUMPTION_LABELS = {
    "commission_rate": ("Commission rate", "[Published]"),
    "ac_dehum_as_large_appliance": ("Treat as Large Appliances (7%)", "[Assumption]"),
    "sub_promo": ("Subscription £/month now", "[Published]"),
    "sub_list": ("Subscription £/month from Jan 2028", "[Published]"),
    "min_fee": ("Minimum fee per sale £", "[Published]"),
    "review_rate": ("Share of buyers who leave a review", "[Assumption]"),
    "use_first_review_window": ("Spread sales over months since first review", "[Assumption]"),
    "review_window_months": ("Review window if oldest review unknown (months)", "[Assumption]"),
    "stale_after_months": ("Newest review older than this = stale (months)", "[Assumption]"),
    "stale_factor": ("Stale listing units multiplier", "[Assumption]"),
    "bestseller_floor_units": ("Units floor: OnBuy 'Bestseller'", "[Assumption] (the badge is published)"),
    "hot_floor_units": ("Units floor: OnBuy 'Hot'", "[Assumption] (the badge is published)"),
    "in_demand_floor_units": ("Units floor: OnBuy 'In demand'", "[Assumption] (the badge is published)"),
    "no_signal_units": ("Units floor: no badge, no reviews", "[Assumption]"),
    "season_profiles": ("Season factors by month", "[Assumption]"),
    "season_profile": ("Seasonality profile", "[Assumption]"),
    "seasonality_strength": ("Seasonality strength", "[Assumption]"),
    "current_month": ("Month of the snapshot", "[Published]"),
    "buybox_share": ("Recommended offer's share of sales", "[Assumption]"),
    "seller_tenure_months": ("Months over which lifetime orders built up", "[Assumption]"),
    "seller_reviews_per_order": ("Seller reviews per order (blank = calibrated)", "[Assumption]"),
    "avg_order_value": ("Average order value across catalogue £", "[Assumption]"),
    "partner_orders_k": ("No badge: Partner if lifetime orders ≥ k", "[Assumption]"),
    "boost_adoption": ("Share of sellers running Boost", "[Assumption]"),
    "boost_levels": ("Boost fee per level", "[Published]"),
    "boost_level": ("Average Boost level", "[Assumption] (levels are published)"),
    "boosted_share_of_gmv": ("Share of adopter sales through boosted slots", "[Assumption]"),
    "boost_incremental_share": ("Incremental sales from Boost", "[Assumption]"),
    "seller_margin": ("Seller gross margin before fees", "[Assumption]"),
    "partner_sales_uplift": ("Sales lift from Partner features", "[Assumption]"),
    "pro_sales_uplift": ("Extra lift from Professional features", "[Assumption]"),
    "churn_fee_ratio": ("Churn risk if subscription ÷ GMV above", "[Assumption]"),
    "p_success_human": ("Success rate, human", "[Assumption]"),
    "p_success_auto": ("Success rate, automated", "[Assumption]"),
    "sse_annual_cost": ("Seller Success exec, fully loaded £ a year", "[Assumption]"),
    "sse_productive_hours": ("Productive hours a year", "[Assumption]"),
    "call_hours": ("Hours per completed call", "[Assumption]"),
    "journey_build_cost": ("Message journey build and upkeep £", "[Assumption]"),
    "journey_sellers_reached": ("Sellers reached by the journey", "[Assumption]"),
    "message_send_cost": ("Sending cost per seller £", "[Assumption]"),
    "value_horizon_months": ("Months of value counted", "[Assumption]"),
    "at_risk_loss_prob": ("Chance an at-risk seller leaves without help", "[Assumption]"),
    "monthly_churn": ("Monthly seller churn", "[Assumption]"),
    "monthly_upgrade_rate": ("Monthly upgrade rate", "[Assumption]"),
    "contribution_margin": ("OnCommerce margin (LTV)", "[Assumption]"),
    "play_ramp_months": ("Months for plays to ramp in", "[Assumption]"),
    "first_sale_units": ("Units a fixed zero-review listing could reach", "[Assumption]"),
    "fix_uplift": ("Uplift from a listing fix", "[Assumption]"),
    "delivery_uplift": ("Uplift from free / faster delivery", "[Assumption]"),
    "merge_uplift": ("Uplift from merging duplicate pages", "[Assumption]"),
    "quality_threshold": ("Listing quality threshold /100", "[Assumption]"),
    "price_gap_threshold": ("Price gap vs lowest offer that blocks Boost", "[Assumption]"),
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
                   "commission are paid on the whole account. Assumption inputs are the sliders in the sidebar.")


def get_draft(play: dict, a: Settings, k: str) -> dict:
    cache = st.session_state.setdefault(f"{k}_drafts", {})
    key = (play["play_id"], play["seller"], play["play_type"], a.to_json())
    if key not in cache:
        with st.spinner("Drafting..."):
            cache[key] = draft_outreach(play, a)
    return cache[key]


def seller_value_expander(k: str, a: Settings, sellers: pd.DataFrame) -> None:
    """Collapsed, under the Revenue per seller table: one seller's orders, revenue and LTV, step by step."""
    with st.expander("How orders, revenue and LTV are worked out", expanded=False):
        if sellers.empty:
            st.caption("No sellers on this page.")
            return
        names = sellers["seller"].tolist()          # sorted by revenue, so the default is the top seller
        sid = st.selectbox("Seller", names, index=0, key=f"{k}_value_seller")
        row = sellers[sellers["seller"] == sid].iloc[0].to_dict()
        rpo, n_cal = sellers.attrs["reviews_per_order"], sellers.attrs["calibration_sellers"]
        steps, total, ltv_v = seller_value_workings(row, a, rpo, n_cal)
        st.table(pd.DataFrame(steps).rename(columns={"step": "Step", "working": "Working", "result": "Result",
                                                    "source": "Type"}).set_index("Step"))
        st.caption(f"Where the order count comes from: {orders_source_label(row['orders_source'])}. 'Shown on OnBuy' "
                   "is the order count in the OnBuy seller box: real, but a minimum because of the +. 'Estimated "
                   "from reviews' is the seller's review count × orders per review.")
        st.caption("Note on the ratio: " + reviews_per_order_text(rpo, n_cal, sample_ratio_stats(),
                                                                   bool(a.seller_reviews_per_order)))
        st.caption("Assumptions are in the sidebar; Published means OnBuy's published prices; Observed in sample is what the seller's "
                   "page shows.")


def ranking_table(prim: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Rank": prim["rank"], "Seller": prim["seller"], "Opportunity": prim["opportunity"],
        "Recommended action": prim["play_type"], "Status": prim["status"],
        "Platform revenue at stake £/mo": prim["stake_month"].round(0), "Route": prim["route"],
        "Net contribution £ (after cost)": prim["net_contribution"].round(0),
        "Confidence": prim["confidence"], "Review in (days)": prim["next_review_days"]})


def seller_decision_view(cfg: CategoryConfig, a: Settings, products: pd.DataFrame, sellers: pd.DataFrame,
                         plays: pd.DataFrame, prim: pd.DataFrame, picked: str | None) -> None:
    k = cfg.key
    names = prim["seller"].tolist()
    if picked and st.session_state.get(f"_{k}_last") != picked:
        st.session_state[f"{k}_dv_seller"] = picked
    st.session_state[f"_{k}_last"] = picked
    if st.session_state.get(f"{k}_dv_seller") not in names:
        st.session_state.pop(f"{k}_dv_seller", None)
    labels = {r.seller: f"#{r.rank} {r.seller}: {r.play_type} ({r.status})" for r in prim.itertuples()}
    sid = st.selectbox("Seller", names, format_func=lambda x: labels[x], key=f"{k}_dv_seller")
    play = prim[prim["seller"] == sid].iloc[0].to_dict()
    srow = sellers[sellers["seller"] == sid]
    srow = srow.iloc[0].to_dict() if len(srow) else None
    sprods = products[products["seller"] == sid].to_dict("records")
    splays = plays[plays["seller"] == sid]
    others = splays[splays["role"] != "Primary"]
    draft = get_draft(play, a, k)
    pid = play["play_id"]
    review = date.today() + timedelta(days=int(play["next_review_days"]))

    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### Seller situation")
        st.markdown(seller_situation(srow, sprods, splays.to_dict("records")))
        st.markdown("#### Recommended action")
        st.markdown(f"**{play['play_type']}** ({play['opportunity']}): {action_text(play)}.  \n"
                    f"Status: {play['status']} · confidence {play['confidence']}")
        if play["status"] == "Needs validation":
            st.warning("Needs validation: " + str(play["evidence"].get("validation_reasons", "")))
        if len(others):
            sec = others.iloc[0]
            st.caption(f"Secondary: {sec['play_type']} ({sec['status']}). "
                       + (f"{len(others) - 1} further action(s) held back. " if len(others) > 1 else "")
                       + "Only the primary action is counted in the totals.")
        st.markdown("#### Why")
        st.markdown(plain_rule(play["rule"]) + ".")
        st.dataframe(pd.DataFrame(evidence_rows(play["evidence"])), hide_index=True, width="stretch")
    with right:
        st.markdown("#### Commercial value")
        st.table(pd.DataFrame(action_economics_steps(play, a)).rename(columns=str.capitalize).set_index("Step"))
        st.caption("Model estimate from the assumptions in the sidebar. Not a measured result.")
        st.markdown("#### Delivery")
        st.markdown(f"Route: **{play['route']}**. {play['why_route']}")
        st.markdown(f"**Subject:** {draft['subject']}  \n{drafted_by(draft)}")
        if draft.get("note"):
            st.caption(draft["note"])
        st.info(draft["message"])
        if play["route"] == HUMAN:
            with st.popover("Call brief for Seller Success"):
                st.markdown(draft["call_brief"].replace("\n", "  \n"))
        st.caption(f"What data would change this: {draft['additional_data']}")
        st.markdown("#### Next review")
        st.markdown(f"Check again in {play['next_review_days']} days, by {review:%d %b %Y}, to see whether the "
                    "action happened and the seller's numbers moved (rule-based: 14 days for stock and price fixes, "
                    "30 for Boost and listing work, 60 for an upgrade).")
    with st.container(border=True):
        st.markdown(f"Your decision on {pid}. Suggested: {play['play_type']}, via {play['route']}.")
        reason = st.text_area("Reason (required to override)", key=f"{k}_reason_{pid}")
        alt = st.selectbox("If overriding, what instead?",
                           ["Reject, no action", "Switch route (human ↔ automated)", "Lower priority",
                            "Raise priority", "Different action (explain in reason)"], key=f"{k}_alt_{pid}")
        b1, b2 = st.columns(2)
        if b1.button("Approve", key=f"{k}_acc_{pid}", width="stretch"):
            log_decision(cfg.label, play, "approve", reason.strip(), a)
            st.success(f"Saved: approved {pid}.")
        if b2.button("Override", key=f"{k}_ovr_{pid}", width="stretch"):
            if not reason.strip():
                st.error("Please give a reason for the override.")
            else:
                log_decision(cfg.label, play, f"override: {alt}", reason.strip(), a)
                st.success(f"Saved: override ({alt}) for {pid}.")


def render(key: str, all_products=None, is_example=None, source=None) -> None:
    cfg = CATEGORIES[key]
    k = cfg.key
    if all_products is None:
        all_products, is_example, source = guarded(data_sidebar)
    a = guarded(settings_sidebar, cfg, all_products)
    products, sellers, plays = guarded(run_category, all_products, cfg.subcategories, a)
    u = units_summary(products)
    mix = revenue_mix(sellers)
    leak = leakage_summary(products, a)
    month = MONTHS[a.current_month - 1]
    summ = portfolio_summary(sellers, plays, a)

    st.caption(f"{', '.join(cfg.subcategories)} · {len(products)} listings · {len(sellers)} sellers · "
               f"est. {u['est_units_month']:,.0f} units and £{u['est_gmv_month']:,.0f} of sales in {month} (model estimate)")
    headline_metrics(summ, a, f"selling {cfg.label.lower()}")

    # Opportunity ranking ------------------------------------------------------
    st.subheader("Opportunity ranking")
    st.caption("One primary action per seller, ranked by expected net contribution after the cost of the call or "
               "message, not by fee size. Listing and stock fixes come first: Boost and upgrades wait until the "
               "seller has none outstanding. Upgrades the seller may not benefit from are marked Needs validation.")
    if plays.empty:
        st.info("No actions for this category at the current assumptions.")
        prim, picked = plays, None
    else:
        prim = top_play_per_seller(plays).reset_index(drop=True)
        event = st.dataframe(ranking_table(prim), hide_index=True, width="stretch", on_select="rerun",
                             selection_mode="single-row", key=f"{k}_rank", height=300)
        rows = event.selection.rows if event is not None and hasattr(event, "selection") else []
        picked = prim["seller"].iloc[rows[0]] if rows else None
        st.caption("Click a row to open it below. "
                   f"{summ['deferred']} further actions are deferred until a fix is done; "
                   f"{summ['needs_validation']} upgrade(s) need validation.")
        with st.expander("All actions, including secondary and deferred"):
            types = st.multiselect("Action types", PLAY_TYPES, default=PLAY_TYPES, key=f"{k}_types")
            view = plays[plays["play_type"].isin(types)]
            st.dataframe(pd.DataFrame({
                "Rank": view["rank"], "Seller": view["seller"], "Role": view["role"], "Status": view["status"],
                "Action": view["play_type"], "Product": view["title"].fillna("").str.slice(0, 50),
                "Why": view["rule"].map(plain_rule), "At stake £/mo": view["stake_month"].round(1),
                "Route": view["route"], "Net contribution £": view["net_contribution"].round(0),
                "Counted in totals": view["counted"]}), hide_index=True, width="stretch")
    why_call_vs_message(a)

    # Seller decision view ----------------------------------------------------
    st.subheader("Seller decision view")
    if prim.empty:
        st.caption("No seller has an action at the current assumptions.")
    else:
        seller_decision_view(cfg, a, products, sellers, plays, prim, picked)

    # Sellers -----------------------------------------------------------------
    st.subheader("Revenue per seller (to OnCommerce, per month)")
    st.caption(f"Left block: this category only. Avg selling price per unit = the seller's GMV here ÷ their units "
               f"here. Right block: the seller's whole account, worked out as lifetime orders ÷ "
               f"{a.seller_tenure_months:g} months × £{a.avg_order_value:g} average order (assumed), then revenue = "
               "subscription + commission + Boost. Tier is Professional only where the badge is shown; otherwise "
               "estimated from lifetime orders. The expander below shows one seller step by step.")
    tbl = pd.DataFrame({
        "Seller": sellers["seller"],
        f"{U_COL} ({cfg.label})": sellers["climate_units_month"].round(1),
        f"{P_COL} ({cfg.label})": sellers["climate_avg_price"].round(2),
        f"{G_COL} ({cfg.label})": sellers["climate_gmv_month"].round(0),
        f"{cfg.label} commission £/mo": sellers["climate_commission_month"].round(1),
        "Tier": sellers["tier"], "Tier source": sellers["tier_source"],
        "Lifetime orders": sellers["lifetime_orders"].round(0), "Where the order count comes from": sellers["orders_source"].map(orders_source_label),
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
    seller_value_expander(k, a, sellers)
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
    # Products -----------------------------------------------------------------
    st.subheader("Products: est. units, average price and GMV per month")
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
    st.subheader("Revenue leakage check")
    lk = st.columns(5)
    lk[0].metric("Sales under the min-fee floor", leak["min_fee_floor_products"],
                 help=f"The floor only binds below £{leak['min_fee_breakeven_price']:.2f}; cheapest item here is "
                      f"£{leak['cheapest_delivered_price']:.2f}.")
    lk[1].metric("Out of stock", leak["out_of_stock_products"])
    lk[2].metric("Units lost to OOS / month", f"{u['lost_units_month']:,.0f}")
    lk[3].metric("Commission lost to OOS / month", f"£{leak['lost_commission_oos_month']:,.0f}")
    lk[4].metric("Duplicate pages · price anomalies", f"{leak['duplicate_pages']} · {leak['price_anomalies']}")
    # Forecast ----------------------------------------------------------------
    st.subheader("12-month forecast and LTV")
    months = st.slider("Months", 12, 24, 12, 1, key=f"{k}_months",
                       help="Go past 13 months to see the Jan 2028 step from promo to list prices.")
    fc = forecast(sellers, plays, products, a, months)
    f1, f2 = st.columns([3, 2])
    with f1:
        st.markdown("**Revenue to OnCommerce from these sellers, £/month: base vs with plays**")
        st.line_chart(fc.set_index("month")[["base", "with_plays"]], x_label="", y_label="£ / month")
        st.caption(f"Base = this seller cohort with {a.monthly_churn:.1%} monthly churn and "
                   f"{a.monthly_upgrade_rate:.1%} monthly upgrades, no new sign-ups. With plays = base + each seller's primary "
                   f"action's expected £/month (counted once), ramped in over {a.play_ramp_months} months.")
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
    # Methodology ---------------------------------------------------------------
    st.subheader("Method and formulas")
    st.markdown(
        f"- Units a month = product reviews × {1 / a.review_rate:,.0f} (1 in {1 / a.review_rate:,.0f} buyers reviews) "
        "÷ months selling × this month's season factor; halved if the newest review is older than "
        f"{a.stale_after_months:g} months; 0 if out of stock or mispriced.\n"
        "- GMV a month = units × average selling price per unit (price plus delivery, weighted across offers).\n"
        "- Revenue to OnCommerce a month = subscription + commission (at least the minimum fee per item) + Boost fees.\n"
        f"- Each action has platform revenue at stake a month. Its value = stake × OnCommerce margin "
        f"({a.contribution_margin:.0%}) × months still trading out of {a.value_horizon_months:g} "
        f"({survival_months(a):.2f}) × success rate, minus the cost of the call or message. The route with the higher "
        "net value wins.\n"
        "- Every input is tagged Published, Observed in sample, Assumption or Model estimate. Confidence is Medium at "
        "best: nothing here has been tested against OnBuy's own data.")
    st.caption(routing_rule(a))
    with st.expander("Action rules in plain words"):
        for name, rule in play_rules(a).items():
            st.markdown(f"- {name}: {rule}")
    render_workings(cfg, a, products, sellers, plays, month)
    with st.expander("Sensitivity: how much the answer moves with the weakest assumptions"):
        st.caption("Each row moves one assumption and keeps the rest as set in the sidebar. If a row changes the "
                   "answer a lot, that assumption needs checking with real data before acting on it.")
        st.dataframe(sensitivity_table(all_products, cfg.subcategories, a), hide_index=True, width="stretch")
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
            f"- [Published] subscriptions £{a.sub_promo['Standard']:.0f} / £{a.sub_promo['Partner']:.0f} / "
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
