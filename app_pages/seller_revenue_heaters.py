"""Seller Revenue page for one climate-control category. Logic: app_pages/seller_revenue_common.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_pages.seller_revenue_common import render  # noqa: E402

render("heaters")
