"""Seller opportunities: one page, one category at a time. Logic: app_pages/seller_revenue_common.py."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_pages.seller_revenue_common import render  # noqa: E402
from app_pages.shared import banner, data_sidebar, guarded  # noqa: E402
from seller_growth.categories import CATEGORIES, ORDER  # noqa: E402

st.title("Seller opportunities")
qp = st.query_params.get("category")
if "category" not in st.session_state:
    st.session_state["category"] = qp if qp in ORDER else ORDER[0]
key = st.segmented_control("Category", ORDER, format_func=lambda k: CATEGORIES[k].label, key="category",
                           required=True) or ORDER[0]
st.query_params["category"] = key
df, is_example, source = guarded(data_sidebar)
banner(is_example, source)
render(key, df, is_example, source)
