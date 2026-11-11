"""common/nav.py - page list and footer for the Seller Revenue app."""
import streamlit as st

from common.text import FOOTER, VERSION
from seller_growth.categories import CATEGORIES, ORDER, SECTION


def seller_revenue_pages(default: bool = True) -> list:
    return [st.Page("app_pages/seller_revenue_overview.py", title="Overview (all categories)", default=default)] + [
        st.Page(f"app_pages/seller_revenue_{k}.py", title=CATEGORIES[k].label,
                url_path=f"seller-revenue-{k.replace('_', '-')}") for k in ORDER]


def footer() -> None:
    st.divider()
    st.caption(f"{VERSION} · {FOOTER}")


__all__ = ["SECTION", "FOOTER", "VERSION", "seller_revenue_pages", "footer"]
