"""
seller_growth/data_schema.py - the listing CSV the Seller Revenue pages read, and a loader that checks it.

One row per product page. The example data (seller_growth/example_products.csv) follows this schema; internal data
can replace it in the app (sidebar > Data) as long as it has the required columns. data/README.md is the readable
version of SCHEMA.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

# (column, required, default if missing, what it is, which numbers it feeds)
SCHEMA = [
    ("product_id", True, None, "unique id of the product page", "row key; links plays to products"),
    ("subcategory", True, None, "product type; must be one of the subcategories a page lists (e.g. 'fan heaters')",
     "which category page shows the row; season pattern"),
    ("title", True, None, "product title", "display only"),
    ("price", True, None, "price of the recommended offer, £ incl. VAT", "avg selling price, GMV, commission"),
    ("seller", True, None, "seller of the recommended offer", "seller tables, plays"),
    ("product_review_count", True, None, "number of product reviews", "units sold"),
    ("delivery_fee", False, 0.0, "delivery charged on the recommended offer, £", "avg selling price, GMV, commission, delivery play"),
    ("offer_sellers", False, "", "all sellers offering the product, ';'-separated, recommended first (blank = seller)",
     "split of units across sellers, avg selling price"),
    ("offer_prices", False, "", "their prices, ';'-separated, same order (blank = price)", "avg selling price, price checks"),
    ("offers_count", False, None, "number of offers (blank = count of offer_sellers)", "listing checks"),
    ("offer_seller_reviews", False, "", "seller review counts for each offer, ';'-separated", "lifetime orders"),
    ("offer_professional", False, "", "1 where that offer shows a Professional Seller badge, ';'-separated", "tier"),
    ("latest_review", False, "", "date of the newest review, YYYY-MM-DD", "halve units if old"),
    ("first_review", False, "", "date of the first review where every review is listed, YYYY-MM-DD",
     "months the listing has been selling"),
    ("oldest_visible_review", False, None, "oldest review date shown when not every review is listed", "months selling"),
    ("badge", False, "", "OnBuy badge: Bestseller, Hot, In demand or blank", "minimum units"),
    ("seller_professional", False, False, "recommended seller shows the Professional Seller badge", "tier, subscription"),
    ("seller_orders_k", False, None, "seller's lifetime orders in thousands, where shown", "lifetime orders, tier, revenue"),
    ("seller_review_count", False, None, "seller's review count", "lifetime orders when no order count is shown"),
    ("flag_out_of_stock", False, False, "out of stock", "units = 0, out-of-stock play"),
    ("flag_price_anomaly", False, False, "price looks wrong for the product", "units = 0, price play"),
    ("flag_duplicate_page", False, False, "same product on a separate page", "duplicate play, quality score"),
    ("flag_no_brand", False, False, "no brand on the listing", "quality score"),
    ("flag_placeholder_ean", False, False, "placeholder barcode", "quality score"),
    ("flag_thin_content", False, False, "thin or templated description", "quality score"),
    ("flag_overseas_dispatch", False, False, "dispatched from outside the UK", "quality issues"),
    ("flag_reviews_from_former_seller", False, False, "reviews earned by a seller no longer listed", "quality score"),
    ("max_qty_selectable", False, None, "most a buyer can add to the basket (a stock signal)", "quality score"),
    ("delivery_max_days", False, None, "latest promised delivery, days", "delivery play, quality score"),
    ("listing_notes", False, "", "free-text notes", "shown in evidence"),
    ("brand", False, "", "brand", "display only"),
    ("url", False, "", "page address", "link in the play detail"),
]
REQUIRED = [c for c, req, *_ in SCHEMA if req]
BOOL_COLS = [c for c, _, d, *_ in SCHEMA if isinstance(d, bool)]


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Check required columns, fill optional ones, coerce types. Raises ValueError with a readable message."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"The CSV is missing required columns: {', '.join(missing)}. See data/README.md.")
    df = df.copy()
    for c, _, default, *_ in SCHEMA:
        if c not in df.columns:
            df[c] = default
    for c in BOOL_COLS:
        df[c] = df[c].map(lambda v: str(v).strip().lower() in ("true", "1", "yes", "y")).astype(bool)
    for c in ("price", "delivery_fee", "seller_orders_k", "seller_review_count", "max_qty_selectable",
              "delivery_max_days"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["delivery_fee"] = df["delivery_fee"].fillna(0.0)
    df["product_review_count"] = pd.to_numeric(df["product_review_count"], errors="coerce").fillna(0).astype(int)
    for c in ("offer_sellers", "offer_prices", "offer_seller_reviews", "offer_professional", "latest_review",
              "first_review", "badge", "listing_notes", "brand", "url"):
        df[c] = df[c].where(df[c].notna(), "").astype(str).replace("nan", "")
    blank = df["offer_sellers"] == ""
    df.loc[blank, "offer_sellers"] = df.loc[blank, "seller"].astype(str)
    df.loc[blank, "offer_prices"] = df.loc[blank, "price"].map(lambda p: f"{p:.2f}")
    df["offers_count"] = pd.to_numeric(df["offers_count"], errors="coerce")
    n = df["offer_sellers"].map(lambda s: len([x for x in s.split(";") if x]))
    df["offers_count"] = df["offers_count"].fillna(n).astype(int)
    if df["product_id"].duplicated().any():
        raise ValueError("product_id must be unique.")
    return df


def load_csv(source) -> pd.DataFrame:
    """source: a path, or bytes from an upload."""
    if isinstance(source, (bytes, bytearray)):
        return prepare(pd.read_csv(io.BytesIO(source)))
    return prepare(pd.read_csv(Path(source)))


def readme_table() -> str:
    lines = ["| Column | Required | If missing | What it is | Feeds |", "|---|---|---|---|---|"]
    for c, req, d, what, feeds in SCHEMA:
        dflt = "" if req else ("blank" if d in ("", None) else str(d))
        lines.append(f"| `{c}` | {'yes' if req else 'no'} | {dflt} | {what} | {feeds} |")
    return "\n".join(lines)
