"""common/nav.py - page list and footer for the Seller Revenue app."""
import streamlit as st

from common.text import FOOTER, VERSION
from seller_growth.categories import SECTION


def seller_revenue_pages(default: bool = True) -> list:
    return [st.Page("app_pages/seller_revenue_overview.py", title="Overview", default=default),
            st.Page("app_pages/seller_opportunities.py", title="Seller opportunities", url_path="seller-opportunities")]


def footer() -> None:
    st.divider()
    st.caption(f"{VERSION} · {FOOTER}")


__all__ = ["SECTION", "FOOTER", "VERSION", "seller_revenue_pages", "footer"]
