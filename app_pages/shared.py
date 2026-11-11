"""
app_pages/shared.py - pieces every Seller Revenue page uses: the data switch, the Settings sidebar, the break-even
panel, the decision log and the error wrapper.
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.text import VERSION  # noqa: E402
from seller_growth.categories import CategoryConfig  # noqa: E402
from seller_growth.data_schema import load_csv  # noqa: E402
from seller_growth.workings import (GRID_CALL_LABEL, GRID_GAP_LABEL, GRID_HOW_TO_READ,  # noqa: E402
                                    call_or_message_text, play_sentence, reviews_per_order_text)
from seller_growth.revenue import (Settings, break_even_grid, break_even_stake,  # noqa: E402
                                   calibrate_reviews_per_order, settings_hash)

EXAMPLE_CSV = ROOT / "seller_growth" / "example_products.csv"
CALIBRATION = ROOT / "seller_growth" / "calibration_stats.json"


def sample_ratio_stats() -> dict:
    """Aggregates only: n, median, min and max seller reviews per order in the real calibration sample."""
    import json
    return json.loads(CALIBRATION.read_text()).get("reviews_per_order_pooled", {})
EXAMPLE_BANNER = "Example data: method demo, not market estimates."
EXAMPLE_NOTE = ("Example data, calibrated on a small sample of public OnBuy pages (Nov 2026). Replace with internal "
                "data to use (sidebar > Data).")
REAL, ASSUMED = "[Real, published]", "[Assumed]"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
MODES = ["Example data (default)", "Internal CSV"]
LOG_COLS = ["timestamp", "page", "seller", "product", "play", "at_stake", "route", "expected_mo", "decision", "reason",
            "settings_hash"]
LOG_FILE = ROOT / "seller_growth" / "decisions.csv"     # local copy; git-ignored. The download is the record.


# --- data ---------------------------------------------------------------------------------------------------------
def data_sidebar() -> tuple[pd.DataFrame, bool, str]:
    """Data switch in the sidebar. Returns (listings, is_example, description). Raises on a bad file."""
    sb = st.sidebar
    sb.header("Data")
    # keyed widgets, copied to plain keys so the choice survives moving between pages
    st.session_state.setdefault("data_mode_w", st.session_state.get("data_mode_saved", MODES[0]))
    mode = sb.radio("Listing data", MODES, key="data_mode_w")
    st.session_state["data_mode_saved"] = mode
    if mode == MODES[0]:
        return load_csv(EXAMPLE_CSV), True, "example data (seller_growth/example_products.csv)"
    up = sb.file_uploader("Upload a CSV (schema in data/README.md)", type=["csv"])
    if up is not None:
        st.session_state["internal_csv"] = (up.name, up.getvalue())
    st.session_state.setdefault("data_path_w", st.session_state.get("internal_path_saved", ""))
    path = sb.text_input("or a file path on the server", key="data_path_w")
    st.session_state["internal_path_saved"] = path
    if path.strip():
        return load_csv(path.strip()), False, f"internal file {path.strip()}"
    if "internal_csv" in st.session_state:
        name, data = st.session_state["internal_csv"]
        return load_csv(data), False, f"uploaded file {name}"
    sb.info("No internal file yet, so the example data is shown.")
    return load_csv(EXAMPLE_CSV), True, "example data (no internal file given)"


def guarded(fn, *args, **kwargs):
    """Run fn; on any error show the traceback on the page and stop, instead of a blank or crashed app."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        st.error("Something went wrong loading or calculating the data. Details:")
        st.code(traceback.format_exc())
        st.caption(VERSION)
        st.stop()


def banner(is_example: bool, source: str) -> None:
    if is_example:
        st.warning(EXAMPLE_BANNER + " " + EXAMPLE_NOTE)
    else:
        st.success(f"Internal data: {source}.")
    st.caption(f"Seller Revenue {VERSION}")


# --- settings ------------------------------------------------------------------------------------------------------
def _reset(prefix: str) -> None:
    for key in [x for x in st.session_state if isinstance(x, str) and x.startswith(prefix)]:
        del st.session_state[key]


def settings_sidebar(cfg: CategoryConfig, df_all: pd.DataFrame) -> Settings:
    """Every Settings field a manager may want to test, each tagged [Real, published] or [Assumed]."""
    d = cfg.assumptions()
    p = f"{cfg.key}_"
    sb = st.sidebar
    sb.header("Assumptions")
    sb.caption(f"{REAL} = OnCommerce's published prices. {ASSUMED} = an estimate; change it to test the result. "
               "Defaults are this category's own.")
    sb.button("Reset to defaults", on_click=_reset, args=(p,), key=f"_reset_{cfg.key}", width="stretch")
    s = lambda name: p + name  # noqa: E731

    with sb.expander("Fees " + REAL):
        rate = st.slider(f"{REAL} Commission", 0.0, 0.25, d.commission_rate, 0.01, format="%.2f", key=s("rate"))
        min_fee = st.number_input(f"{REAL} Minimum commission per item (£)", 0.0, 2.0, d.min_fee, 0.05, key=s("minfee"))
        la = False
        if cfg.large_appliance_question:
            la = st.checkbox(f"{ASSUMED} Treat {cfg.label.lower()} as 'Large Appliances' (7%)",
                             d.ac_dehum_as_large_appliance, key=s("la"),
                             help="The 7% list names fridges, washers, cookers and similar, not this product type.")
        promo, lst = {}, {}
        for t in ("Standard", "Partner", "Professional"):
            c1, c2 = st.columns(2)
            promo[t] = c1.number_input(f"{REAL} {t} £/mo now", 0.0, 2000.0, d.sub_promo[t], 1.0, key=s(f"sp_{t}"))
            lst[t] = c2.number_input(f"{REAL} {t} £/mo from Jan 2028", 0.0, 2000.0, d.sub_list[t], 1.0, key=s(f"sl_{t}"))
        lv = {n: st.number_input(f"{REAL} Boost fee, {n}", 0.0, 1.0, v, 0.01, format="%.2f", key=s(f"bl_{n}"))
              for n, v in d.boost_levels.items()}

    with sb.expander("Units sold " + ASSUMED, expanded=True):
        n_buyers = st.slider(f"{ASSUMED} 1 in N buyers leaves a review: N", 10, 200, int(round(1 / d.review_rate)), 5,
                             key=s("n_buyers"))
        spread = st.radio(f"{ASSUMED} Spread sales over", ["Months since the first review", "A fixed number of months"],
                          index=0 if d.use_first_review_window else 1, key=s("spread"),
                          help="Months since the first review is used only where every review is listed.")
        win = st.slider(f"{ASSUMED} Fixed months (also used when the first review is unknown)", 6.0, 60.0,
                        d.review_window_months, 1.0, key=s("win"))
        stale = st.slider(f"{ASSUMED} Halve units if the newest review is older than (months)", 3.0, 36.0,
                          d.stale_after_months, 1.0, key=s("stale"))
        bb = st.slider(f"{ASSUMED} Share of sales won by the recommended offer", 0.5, 1.0, d.buybox_share, 0.05,
                       key=s("bb"))

    with sb.expander("Season factors " + ASSUMED):
        prof = st.selectbox(f"{ASSUMED} Season pattern", list(d.season_profiles),
                            index=list(d.season_profiles).index(d.season_profile), key=s("prof"))
        ss = st.slider(f"{ASSUMED} Strength (0 = ignore seasons, 1 = full)", 0.0, 1.0, d.seasonality_strength, 0.1,
                       key=s("season"))
        st.caption("Season factor by month: 1.0 is an average month. Edit a cell to test.")
        tbl = st.data_editor(pd.DataFrame([d.season_profiles[prof]], columns=MONTHS), hide_index=True,
                             key=s(f"factors_{prof}"))
        profiles = {k_: list(v) for k_, v in d.season_profiles.items()}
        profiles[prof] = [float(x) for x in tbl.iloc[0].tolist()]

    with sb.expander("Seller accounts " + ASSUMED):
        ratio, n_cal = calibrate_reviews_per_order(df_all)
        opr = st.number_input(f"{ASSUMED} Orders per seller review (1 review per N orders): N", 1.0, 200.0,
                              1 / ratio, 0.5, format="%.1f", key=s("opr"),
                              help=reviews_per_order_text(ratio, n_cal, sample_ratio_stats()))
        ten = st.slider(f"{ASSUMED} Months over which lifetime orders built up", 12.0, 96.0, d.seller_tenure_months,
                        6.0, key=s("ten"))
        aov = st.slider(f"{ASSUMED} Average order value (£)", 10.0, 150.0, d.avg_order_value, 5.0, key=s("aov"))
        pk = st.slider(f"{ASSUMED} No badge: Partner if lifetime orders at least (thousands)", 1.0, 100.0,
                       d.partner_orders_k, 1.0, key=s("pk"))

    with sb.expander("Boost " + ASSUMED):
        adopt = st.slider(f"{ASSUMED} Share of sellers using Boost", 0.0, 1.0, d.boost_adoption, 0.05, key=s("adopt"))
        lvl = st.selectbox(f"{ASSUMED} Typical Boost level", list(lv), index=list(lv).index(d.boost_level),
                           key=s("lvl"))
        bsh = st.slider(f"{ASSUMED} Share of a user's sales that are boosted", 0.0, 1.0, d.boosted_share_of_gmv, 0.05,
                        key=s("bsh"))
        inc = st.slider(f"{ASSUMED} Extra sales Boost creates (share of boosted sales)", 0.0, 1.0,
                        d.boost_incremental_share, 0.05, key=s("inc"))
        mar = st.slider(f"{ASSUMED} Seller margin before fees", 0.1, 0.6, d.seller_margin, 0.05, key=s("mar"))

    with sb.expander("Call or message " + ASSUMED, expanded=True):
        ph = st.slider(f"{ASSUMED} Call success rate", 0.0, 1.0, d.p_success_human, 0.05, key=s("ph"))
        pa = st.slider(f"{ASSUMED} Message success rate", 0.0, 1.0, d.p_success_auto, 0.05, key=s("pa"))
        hc = st.slider(f"{ASSUMED} Call cost (£ per seller)", 0.0, 500.0, d.human_cost, 10.0, key=s("hc"))
        ac = st.slider(f"{ASSUMED} Message cost (£ per seller)", 0.0, 20.0, d.auto_cost, 0.5, key=s("ac"))
        pu = st.slider(f"{ASSUMED} Sales lift from Partner features", 0.0, 0.2, d.partner_sales_uplift, 0.01, key=s("pu"))
        pru = st.slider(f"{ASSUMED} Extra lift from Professional features", 0.0, 0.2, d.pro_sales_uplift, 0.01,
                        key=s("pru"))
        cfr = st.slider(f"{ASSUMED} Cancellation risk if subscription is over this share of sales", 0.01, 0.30,
                        d.churn_fee_ratio, 0.01, key=s("cfr"))

    with sb.expander("Forecast and lifetime value " + ASSUMED):
        cm = st.slider(f"{ASSUMED} OnCommerce margin on seller revenue", 0.1, 1.0, d.contribution_margin, 0.05,
                       key=s("cm"))
        churn = st.slider(f"{ASSUMED} Sellers leaving each month", 0.0, 0.15, d.monthly_churn, 0.005, format="%.3f",
                          key=s("churn"))
        upr = st.slider(f"{ASSUMED} Sellers moving up a tier each month", 0.0, 0.10, d.monthly_upgrade_rate, 0.005,
                        format="%.3f", key=s("upr"))

    return cfg.assumptions(
        commission_rate=rate, min_fee=min_fee, ac_dehum_as_large_appliance=la, sub_promo=promo, sub_list=lst,
        boost_levels=lv, review_rate=1 / n_buyers, use_first_review_window=spread.startswith("Months since"),
        review_window_months=win, stale_after_months=stale, buybox_share=bb, season_profile=prof,
        seasonality_strength=ss, season_profiles=profiles,
        seller_reviews_per_order=None if abs(opr - 1 / ratio) < 1e-9 else 1 / opr,
        seller_tenure_months=ten, avg_order_value=aov, partner_orders_k=pk, boost_adoption=adopt, boost_level=lvl,
        boosted_share_of_gmv=bsh, boost_incremental_share=inc, seller_margin=mar, p_success_human=ph,
        p_success_auto=pa, human_cost=hc, auto_cost=ac, partner_sales_uplift=pu, pro_sales_uplift=pru,
        churn_fee_ratio=cfr, contribution_margin=cm, monthly_churn=churn, monthly_upgrade_rate=upr)


# --- break-even ----------------------------------------------------------------------------------------------------
def why_call_vs_message(a: Settings) -> None:
    """Collapsed expander after the plays table: the plain explanation first, then the tipping point and grid."""
    with st.expander("Why call vs message?", expanded=False):
        break_even_panel(a)


def break_even_panel(a: Settings) -> None:
    be = break_even_stake(a)
    st.markdown(call_or_message_text(a))
    with st.container(border=True):
        st.markdown("##### The tipping point (break-even)")
        st.markdown(
            f"A Seller Success call is worth it when the £ at stake a month is above "
            f"(call cost − message cost) ÷ ({a.value_horizon_months:g} months × (call success − message success)) = "
            f"(£{a.human_cost:,.0f} − £{a.auto_cost:,.0f}) ÷ ({a.value_horizon_months:g} × "
            f"({a.p_success_human:.0%} − {a.p_success_auto:.0%})) = "
            + (f"**£{be:,.2f} a month**." if be != float("inf") else "never (calls are not more successful)."))
        st.markdown(f"Tipping point, £ a month, for other call costs and success gaps (message cost "
                    f"£{a.auto_cost:,.0f}). Rows: {GRID_CALL_LABEL.lower()}. Columns: {GRID_GAP_LABEL.lower()}.")
        grid = break_even_grid(a).map(lambda v: f"£{v:,.0f}" if v != float("inf") else "never")
        grid = grid.reset_index().rename(columns={"index": GRID_CALL_LABEL})
        st.dataframe(grid, hide_index=True, width="content",
                     column_config={c: st.column_config.TextColumn(c, help=GRID_GAP_LABEL)
                                    for c in grid.columns[1:]})
        st.caption(GRID_HOW_TO_READ)


def play_line(play: dict, a: Settings) -> str:
    return play_sentence(play, a)


# --- decision log --------------------------------------------------------------------------------------------------
def log_decision(page: str, play: dict, decision: str, reason: str, a: Settings) -> dict:
    row = {"timestamp": datetime.now().isoformat(timespec="seconds"), "page": page, "seller": play["seller"],
           "product": play.get("title", "") or "", "play": play["play_type"],
           "at_stake": round(float(play["stake_month"]), 2), "route": play["route"],
           "expected_mo": round(float(play["expected_month"]), 2), "decision": decision, "reason": reason,
           "settings_hash": settings_hash(a)}
    st.session_state.setdefault("decision_log", []).append(row)
    try:   # local copy for running on your own machine; Streamlit Cloud storage does not last, so download the CSV
        pd.DataFrame([row])[LOG_COLS].to_csv(LOG_FILE, mode="a", header=not LOG_FILE.exists(), index=False)
    except OSError:
        pass
    return row


def decision_log_section(page: str | None = None) -> None:
    log = pd.DataFrame(st.session_state.get("decision_log", []), columns=LOG_COLS)
    st.subheader("Decision log")
    st.caption("Every accept or override in this session, all pages. settings_hash identifies the exact assumptions "
               "used. Download it to keep it: the hosted app does not store files between sessions.")
    view = log if page is None else log[log["page"] == page]
    if view.empty:
        st.caption("No decisions on this page yet.")
    else:
        st.dataframe(view.iloc[::-1], hide_index=True, width="stretch")
    st.download_button("Download decision log", log.to_csv(index=False).encode("utf-8"), "decision_log.csv",
                       "text/csv", key=f"dl_log_{page or 'all'}")


def setting_rows(a: Settings) -> list[str]:
    return [f.name for f in fields(a)]
