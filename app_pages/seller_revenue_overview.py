"""Overview of the five per-category Seller Revenue pages (one per category manager)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from seller_growth.categories import CATEGORIES, ORDER, SECTION  # noqa: E402
from app_pages.shared import banner, break_even_panel, data_sidebar, decision_log_section, guarded  # noqa: E402
from seller_growth.revenue import Settings, run_category, units_summary  # noqa: E402

st.title(SECTION)
st.markdown("One page per category, each for its own category manager, with its own products, sellers, assumptions, "
            "plays, routing, forecast and outreach drafts. Pick a category in the menu. The table uses each page's "
            "default assumptions; change them on each category page.")
df, is_example, source = guarded(data_sidebar)
banner(is_example, source)
break_even_panel(Settings())
rows = []
for k in ORDER:
    cfg = CATEGORIES[k]
    p, s, pl = guarded(run_category, df, cfg.subcategories, cfg.assumptions())
    u = units_summary(p)
    top = pl.iloc[0] if len(pl) else None
    rows.append({"Category": cfg.label, "Products": len(p), "Sellers": len(s),
                 "Est. units/month (Nov)": round(u["est_units_month"]),
                 "Avg selling price per unit (£)": round(u["avg_price"], 2) if u["est_units_month"] else None,
                 "Est. GMV/month (£, Nov)": round(u["est_gmv_month"]),
                 "Category commission £/mo": round(u["est_commission_month"]),
                 "Revenue to OnCommerce £/mo": round(s["est_revenue_month"].sum()),
                 "Top play": "" if top is None else f"{top['play_type']}, {top['seller']} ({top['route']})"})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
st.caption("Revenue to OnCommerce counts each seller's whole account; a seller on two category pages is counted on "
           "both, so the column does not add up across categories. Units and GMV are this category only; GMV = units × "
           "average selling price per unit. Each category page has 'How these numbers are worked out' with the "
           "steps in plain words.")
decision_log_section(None)
