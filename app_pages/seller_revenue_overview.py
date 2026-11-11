"""Landing page: the commercial picture across the five climate-control categories, at default assumptions."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from seller_growth.categories import CATEGORIES, ORDER  # noqa: E402
from app_pages.shared import (banner, data_sidebar, decision_log_section, guarded, headline_metrics,  # noqa: E402
                              why_call_vs_message)
from seller_growth.revenue import Settings, overview_by_category  # noqa: E402

st.title("Seller Revenue | Commercial Decision Support")
st.markdown("##### Which sellers should we help, what should we recommend, and when is a human conversation worth "
            "more than an automated intervention?")
df, is_example, source = guarded(data_sidebar)
banner(is_example, source)
rows, total, top = guarded(overview_by_category, df, [(k, CATEGORIES[k].label, CATEGORIES[k].subcategories,
                                                        CATEGORIES[k].assumptions()) for k in ORDER])
headline_metrics(total, Settings(), "across five climate-control categories")

st.subheader("Where the opportunity is")
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
st.caption("Each category's default assumptions. Example sellers are separate in each category, so the totals add up "
           "across rows. One primary action per seller is counted; secondary and deferred actions are not.")

st.subheader("Top five opportunities")
st.dataframe(top, hide_index=True, width="stretch")
try:
    st.page_link("app_pages/seller_opportunities.py", label="Open Seller opportunities to review and decide each one",
                 icon=":material/arrow_forward:")
except Exception:  # noqa: BLE001  (page run on its own, outside the app's navigation)
    st.caption("Open Seller opportunities in the menu to review and decide each one.")

with st.expander("How to read this app"):
    st.markdown(
        "- Fix first: stock, price, delivery and duplicate-page problems are dealt with before Boost or a plan change.\n"
        "- Boost is offered only where the listing is in stock, priced in line and of good quality, and the seller "
        "should earn more than the fee.\n"
        "- An upgrade is suggested only if the seller is better off after the extra fee; otherwise it is marked Needs "
        "validation.\n"
        "- Call or message: whichever gives more contribution after its own cost, with costs built up from salary and "
        "hours, not guessed.\n"
        "- Every figure is a model estimate from synthetic data and stated assumptions. None is a measured result. "
        "You approve or override every action, with a reason, and it goes in the decision log.")
why_call_vs_message(Settings())
decision_log_section(None)
