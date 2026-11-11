"""
tools/calibrate_from_private.py - turn the private OnBuy sample into AGGREGATE calibration statistics.

    python tools/calibrate_from_private.py [path/to/onbuy_climate_products.csv]

The sample itself is not in this repository (OnBuy's website terms restrict automated collection and reuse).
It is kept outside the repo (default /workspace/private_onbuy_raw/onbuy_climate_products.csv). This script writes
only per-category aggregates (counts, shares, quantiles, log-normal fits) to seller_growth/calibration_stats.json.
No rows, titles, brands, sellers, URLs or product ids are written.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from seller_growth.categories import CATEGORIES, ORDER  # noqa: E402

DEFAULT = Path("/workspace/private_onbuy_raw/onbuy_climate_products.csv")
OUT = ROOT / "seller_growth" / "calibration_stats.json"
SNAPSHOT = date(2026, 11, 11)


def lognorm(x: pd.Series) -> dict:
    x = pd.to_numeric(x, errors="coerce").dropna()
    x = x[x > 0]
    if x.empty:
        return {"n": 0}
    lx = x.map(math.log)
    return {"n": int(len(x)), "log_mean": round(float(lx.mean()), 3),
            "log_sd": round(float(lx.std(ddof=0)) if len(x) > 1 else 0.3, 3),
            "min": round(float(x.min()), 2), "median": round(float(x.median()), 2), "max": round(float(x.max()), 2)}


def share(mask) -> float:
    return round(float(pd.Series(mask).mean()), 3) if len(mask) else 0.0


def months_ago(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, errors="coerce").dropna()
    return d.map(lambda v: (pd.Timestamp(SNAPSHOT) - v).days / 30.44)


def category_stats(p: pd.DataFrame) -> dict:
    reviewed = p[p["product_review_count"] > 0]
    ages = months_ago(reviewed["latest_review"].replace("", None))
    ratios = []
    for prices in p["offer_prices"].fillna(""):
        v = [float(x) for x in str(prices).split(";") if x]
        if len(v) > 1:
            ratios += [x / v[0] for x in v[1:]]
    buybox = p.drop_duplicates("seller")
    sellers = set()
    for s in p["offer_sellers"].fillna(""):
        sellers |= {x for x in str(s).split(";") if x}
    orders = buybox["seller_orders_k"].dropna()
    both = buybox.dropna(subset=["seller_orders_k", "seller_review_count"])
    both = both[(both["seller_orders_k"] > 0) & (both["seller_review_count"] > 0)]
    paid = p[p["delivery_fee"] > 0]["delivery_fee"]
    return {
        "n_products": int(len(p)),
        "n_sellers": int(len(sellers)),
        "subcategory_mix": {k: round(v, 3) for k, v in p["subcategory"].value_counts(normalize=True).items()},
        "price": lognorm(p.loc[~p["flag_price_anomaly"].astype(bool), "price"]),   # anomalies modelled separately
        "paid_delivery_share": share(p["delivery_fee"] > 0),
        "paid_delivery_fee_median": round(float(paid.median()), 2) if len(paid) else 0.0,
        "reviews_zero_share": share(p["product_review_count"] == 0),
        "reviews_nonzero": lognorm(reviewed["product_review_count"]),
        "latest_review_age_months_median": round(float(ages.median()), 1) if len(ages) else None,
        "latest_review_stale_share": share(ages > 12) if len(ages) else 0.0,
        "first_review_known_share": share(reviewed["first_review"].fillna("") != "") if len(reviewed) else 0.0,
        "badge_mix": {k: round(v, 3) for k, v in p["badge"].fillna("none").replace("", "none")
                      .value_counts(normalize=True).items()},
        "offers_count_mix": {str(k): round(v, 3) for k, v in p["offers_count"].clip(upper=4)
                             .value_counts(normalize=True).sort_index().items()},
        "other_offer_price_ratio": {"median": round(float(pd.Series(ratios).median()), 3) if ratios else 1.0,
                                    "max": round(float(max(ratios)), 3) if ratios else 1.0},
        "out_of_stock_share": share(p["flag_out_of_stock"]),
        "price_anomaly_share": share(p["flag_price_anomaly"]),
        "duplicate_page_share": share(p["flag_duplicate_page"]),
        "overseas_dispatch_share": share(p["flag_overseas_dispatch"]),
        "thin_content_share": share(p["flag_thin_content"]),
        "no_brand_share": share(p["flag_no_brand"]),
        "former_seller_reviews_share": share(p["flag_reviews_from_former_seller"]),
        "delivery_max_days_median": round(float(p["delivery_max_days"].median()), 1),
        "seller_orders_shown_share": share(buybox["seller_orders_k"].notna()),
        "seller_orders_k": lognorm(orders),
        "seller_reviews": lognorm(buybox["seller_review_count"]),
        "professional_share": share(buybox["seller_professional"]),
        "reviews_per_order_median": round(float((both["seller_review_count"] / (both["seller_orders_k"] * 1000))
                                                .median()), 4) if len(both) else None,
    }


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    df = pd.read_csv(src)
    out = {"source": "small sample of public OnBuy product pages viewed in November 2026 (not included)",
           "snapshot": SNAPSHOT.isoformat(), "categories": {}}
    for k in ORDER:
        out["categories"][k] = category_stats(df[df["subcategory"].isin(CATEGORIES[k].subcategories)])
    OUT.write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(df)} sample rows summarised, no rows written)")


if __name__ == "__main__":
    main()
