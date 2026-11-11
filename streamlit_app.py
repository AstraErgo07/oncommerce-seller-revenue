"""
streamlit_app.py - entry point for the OnCommerce (OnBuy) Seller Revenue app.

Run locally:  streamlit run streamlit_app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Seller Revenue (OnCommerce)", layout="wide")

from common.nav import SECTION, footer, seller_revenue_pages  # noqa: E402

nav = st.navigation({
    SECTION: seller_revenue_pages(default=True),
    "About": [st.Page("app_pages/method_page.py", title="Data and method", url_path="data-and-method")],
})
nav.run()
footer()
