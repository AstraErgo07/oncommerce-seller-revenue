"""Data and method page: sources and assumptions, then the internal data schema."""
from pathlib import Path

import streamlit as st

from common.text import VERSION

ROOT = Path(__file__).resolve().parent.parent
st.caption(f"Seller Revenue {VERSION}")
for name in ["SOURCES.md", "README.md"]:
    st.markdown((ROOT / "data" / name).read_text(encoding="utf-8"))
    st.divider()
