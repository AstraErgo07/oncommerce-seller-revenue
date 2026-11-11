"""
seller_growth/calc.py - Seller Growth Agent economics for OnBuy (OnCommerce network).
Pure functions, no AI, no Streamlit. Every number the app or agent shows comes from here.

LISTING INPUTS (example data in this repo, see tools/gen_example_data.py): price, delivery fee,
seller, number of offers and their prices, product review count and rating, badge, delivery
window, stock signal, listing content flags.
REAL (published): OnCommerce sales fee 15% standard rate on price incl. delivery, £0.25 minimum.
ESTIMATED (labelled, editable in the sidebar): units sold (from reviews), GMV, commission
revenue, and the share of commission each action could recover.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

CATEGORIES = ["home textiles", "kitchen", "outdoor", "beauty"]
SCRAPE_DATE = date(2026, 11, 11)

# Action types the engine can propose
RECRUIT_SELLER = "Recruit a second seller"
PRICE_NUDGE = "Nudge seller on price"
FIX_LISTING = "Fix listing quality"
FIX_DELIVERY = "Improve delivery promise"
STOCK_RISK = "Secure stock depth"
MERGE_DUPLICATE = "Merge duplicate product pages"
CATEGORY_RECRUIT = "Recruit sellers into category"
ACTION_TYPES = [RECRUIT_SELLER, PRICE_NUDGE, FIX_LISTING, FIX_DELIVERY, STOCK_RISK,
                MERGE_DUPLICATE, CATEGORY_RECRUIT]


@dataclass
class Assumptions:
    # REAL (published, OnCommerce fee table, Nov 2026): 15% "Standard Selling Fee" applies
    # to all four categories here (none falls under the 7/8/10/13/20% named categories).
    commission_rates: dict = field(default_factory=lambda: {c: 0.15 for c in CATEGORIES})
    # REAL (published): minimum sales fee per product sold, UK.
    min_fee: float = 0.25
    # ESTIMATE: share of orders that leave a product review. 2% => 50 orders per review.
    review_rate: float = 0.02
    # ESTIMATE: reviews are assumed to have built up over this many months.
    review_window_months: float = 24.0
    # ESTIMATE: if the newest review is older than this, demand is treated as fading...
    stale_after_months: float = 12.0
    # ...and multiplied by this factor.
    stale_factor: float = 0.5
    # ESTIMATE: minimum monthly units implied by OnBuy's own rank badges (real badges,
    # estimated meaning). Used when a product has few or no reviews.
    bestseller_floor_units: float = 10.0
    in_demand_floor_units: float = 3.0
    no_signal_units: float = 0.5
    # Thresholds (judgement, editable)
    high_demand_units: float = 5.0        # units/month that count as "real demand"
    price_gap_threshold: float = 0.10     # offer >10% above the lowest offer = uncompetitive
    slow_delivery_days: int = 7           # latest promised delivery more than 7 days away
    low_stock_qty: int = 2                # max quantity a buyer can select <= 2
    quality_threshold: int = 70           # listing quality score below this = fix
    # ESTIMATE: share of a product's monthly commission each action could add or protect.
    uplift: dict = field(default_factory=lambda: {
        RECRUIT_SELLER: 0.20, PRICE_NUDGE: 0.10, FIX_LISTING: 0.10, FIX_DELIVERY: 0.15,
        STOCK_RISK: 0.10, MERGE_DUPLICATE: 0.05, CATEGORY_RECRUIT: 0.10})

    def rate_for(self, category: str) -> float:
        return float(self.commission_rates.get(category, 0.15))

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


# ---------------------------------------------------------------------------
# Demand and revenue (per product)
# ---------------------------------------------------------------------------
def months_since(iso_date: str | None, today: date = SCRAPE_DATE) -> float | None:
    if not iso_date or (isinstance(iso_date, float) and pd.isna(iso_date)):
        return None
    d = date.fromisoformat(str(iso_date))
    return (today - d).days / 30.44


def est_monthly_units(review_count: int, months_since_latest: float | None, badge: str,
                      a: Assumptions) -> float:
    """ESTIMATE of units sold per month.
    = review_count / review_rate / review_window_months
      x stale_factor if the newest review is older than stale_after_months
      then floored by the OnBuy badge (Bestseller / In demand / none)."""
    units = (review_count / a.review_rate) / a.review_window_months if review_count else 0.0
    if units and months_since_latest is not None and months_since_latest > a.stale_after_months:
        units *= a.stale_factor
    badge = (badge or "").strip().lower() if isinstance(badge, str) else ""
    floor = (a.bestseller_floor_units if badge == "bestseller"
             else a.in_demand_floor_units if badge == "in demand" else a.no_signal_units)
    return max(units, floor)


def delivered_price(price: float, delivery_fee: float) -> float:
    """What the buyer pays per unit; OnCommerce charges its fee on this total."""
    return price + (delivery_fee or 0.0)


def commission_per_unit(delivered: float, rate: float, min_fee: float) -> float:
    """Marketplace sales fee per unit = max(rate x delivered price, minimum fee)."""
    return max(rate * delivered, min_fee)


def price_dispersion(offer_prices: list[float]) -> float:
    """(highest offer - lowest offer) / lowest offer. 0 when there is one offer."""
    if len(offer_prices) < 2 or min(offer_prices) <= 0:
        return 0.0
    return (max(offer_prices) - min(offer_prices)) / min(offer_prices)


def gap_to_lowest(price: float, offer_prices: list[float]) -> float:
    """How far one offer sits above the lowest offer on the same product (0.10 = 10%)."""
    low = min(offer_prices)
    return (price - low) / low if low > 0 else 0.0


def listing_quality(row: dict, a: Assumptions) -> tuple[int, list[str]]:
    """Listing quality score out of 100 and the issues found. Penalties (judgement):
    no brand -15, no reviews -10, paid delivery -10, slow delivery -15, low stock -10,
    title > 120 chars or ALL CAPS -5, duplicate page -10, placeholder barcode -10,
    thin/templated content -10, reviews earned by a seller no longer listed -5."""
    score, issues = 100, []

    def hit(points, text):
        nonlocal score
        score -= points
        issues.append(text)

    if row.get("flag_no_brand"):
        hit(15, "No brand on the listing")
    if int(row.get("product_review_count") or 0) == 0:
        hit(10, "No product reviews yet")
    if (row.get("delivery_fee") or 0) > 0:
        hit(10, f"Paid delivery (£{row['delivery_fee']:.2f}) on a site where most listings ship free")
    days = row.get("delivery_max_days")
    if days is not None and not pd.isna(days) and days > a.slow_delivery_days:
        hit(15, f"Slow delivery promise (up to {int(days)} days)")
    qty = row.get("max_qty_selectable")
    if qty is not None and not pd.isna(qty) and qty <= a.low_stock_qty:
        hit(10, f"Low stock (buyer can select only {int(qty)})")
    title = str(row.get("title") or "")
    if len(title) > 120 or (title.isupper() and len(title) > 10):
        hit(5, "Title too long or in ALL CAPS")
    if row.get("flag_duplicate_page"):
        hit(10, "Same product listed on a separate page")
    if row.get("flag_placeholder_ean"):
        hit(10, "Placeholder barcode (EAN)")
    if row.get("flag_thin_content"):
        hit(10, "Thin, empty or templated description")
    if row.get("flag_reviews_from_former_seller"):
        hit(5, "Reviews were earned by a seller no longer on the page")
    return max(score, 0), issues


def _offers(row: dict) -> list[float]:
    raw = str(row.get("offer_prices") or row["price"])
    return [float(x) for x in raw.split(";") if x]


def evaluate_products(df: pd.DataFrame, a: Assumptions) -> pd.DataFrame:
    """Add every calculated column to the product table."""
    out = []
    for r in df.to_dict("records"):
        r["badge"] = r.get("badge") if isinstance(r.get("badge"), str) else ""   # CSV blanks -> ""
        r["other_sellers"] = r.get("other_sellers") if isinstance(r.get("other_sellers"), str) else ""
        offers = _offers(r)
        dp = delivered_price(r["price"], r.get("delivery_fee", 0.0))
        units = est_monthly_units(int(r.get("product_review_count") or 0),
                                  months_since(r.get("latest_review")), r.get("badge"), a)
        cpu = commission_per_unit(dp, a.rate_for(r["category"]), a.min_fee)
        score, issues = listing_quality(r, a)
        r.update({
            "delivered_price": dp,
            "est_units_month": units,
            "est_gmv_month": units * dp,
            "commission_rate": a.rate_for(r["category"]),
            "commission_per_unit": cpu,
            "est_commission_month": units * cpu,
            "price_dispersion": price_dispersion(offers),
            "quality_score": score,
            "quality_issues": "; ".join(issues),
        })
        out.append(r)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Category view
# ---------------------------------------------------------------------------
def category_summary(products: pd.DataFrame, listings: pd.DataFrame | None = None) -> pd.DataFrame:
    """Demand and supply per category. `products` must come from evaluate_products.
    under_supply_index = (est units per distinct seller) x (share of products with one offer),
    scaled so the top category = 100."""
    rows = []
    for cat, g in products.groupby("category"):
        sellers = set(g["seller"])
        for s in g["other_sellers"].fillna(""):
            sellers.update(x for x in str(s).split(";") if x)
        by_seller = g.groupby("seller")["est_gmv_month"].sum()
        units = g["est_units_month"].sum()
        rows.append({
            "category": cat,
            "products": len(g),
            "distinct_sellers": len(sellers),
            "avg_offers_per_product": g["offers_count"].mean(),
            "share_single_offer": (g["offers_count"] == 1).mean(),
            "est_units_month": units,
            "est_gmv_month": g["est_gmv_month"].sum(),
            "est_commission_month": g["est_commission_month"].sum(),
            "top_seller_share_gmv": (by_seller.max() / by_seller.sum()) if by_seller.sum() else 0.0,
            "units_per_seller": units / max(len(sellers), 1),
            "avg_quality_score": g["quality_score"].mean(),
            "share_slow_delivery": (g["quality_issues"].str.contains("Slow delivery")).mean(),
            "median_price": g["price"].median(),
        })
    out = pd.DataFrame(rows)
    raw = out["units_per_seller"] * out["share_single_offer"]
    out["under_supply_index"] = (100 * raw / raw.max()).round(0) if raw.max() > 0 else 0
    if listings is not None and not listings.empty:
        lp = listings.groupby("category")["price"].agg(
            listing_rows="count", listing_p10=lambda s: s.quantile(0.1),
            listing_median="median", listing_p90=lambda s: s.quantile(0.9)).reset_index()
        out = out.merge(lp, on="category", how="left")
    return out.sort_values("under_supply_index", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Actions for the marketplace manager
# ---------------------------------------------------------------------------
def _action(atype, r, a, rule, evidence, seller=None, at_stake=None):
    stake = r["est_commission_month"] if at_stake is None else at_stake
    return {
        "action_type": atype,
        "category": r["category"],
        "product_id": r.get("product_id", ""),
        "title": r.get("title", ""),
        "seller": seller if seller is not None else r.get("seller", ""),
        "est_commission_month": stake,
        "priority_gbp_month": stake * a.uplift[atype],
        "rule": rule,
        "evidence": evidence,
    }


def generate_actions(products: pd.DataFrame, a: Assumptions, cat_summary: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rules that turn the numbers into prioritised actions.
    priority (£/month) = estimated monthly commission at stake x uplift share for that action."""
    acts = []
    for r in products.to_dict("records"):
        offers = _offers(r)
        demand = r["est_units_month"] >= a.high_demand_units or str(r.get("badge")) == "Bestseller"
        base_ev = {"price_gbp": r["price"], "delivered_price_gbp": round(r["delivered_price"], 2),
                   "offers_count": int(r["offers_count"]), "product_reviews": int(r["product_review_count"]),
                   "avg_rating": r.get("avg_rating"), "onbuy_badge": r.get("badge") or "none",
                   "est_units_month": round(r["est_units_month"], 1),
                   "est_gmv_month_gbp": round(r["est_gmv_month"], 0),
                   "est_commission_month_gbp": round(r["est_commission_month"], 2),
                   "quality_score": r["quality_score"]}
        # 1. Single seller on a product with real demand -> recruit a second seller
        if r["offers_count"] == 1 and demand:
            acts.append(_action(RECRUIT_SELLER, r, a, "single_offer_with_demand", base_ev))
        # 2. Non-lowest offers priced well above the lowest -> nudge those sellers
        others = [s for s in str(r.get("other_sellers") or "").split(";") if s]
        for seller, p in zip([r["seller"]] + others, offers):
            gap = gap_to_lowest(p, offers)
            if gap > a.price_gap_threshold:
                ev = dict(base_ev, seller_price_gbp=p, lowest_offer_gbp=min(offers), gap_to_lowest=round(gap, 3))
                share = r["est_commission_month"] / max(len(offers), 1)   # ESTIMATE: equal share per offer
                acts.append(_action(PRICE_NUDGE, r, a, "offer_above_lowest", ev, seller=seller, at_stake=share))
        # 3. Low listing quality on a product people are buying
        if r["quality_score"] < a.quality_threshold and r["est_units_month"] >= a.in_demand_floor_units:
            ev = dict(base_ev, issues=r["quality_issues"])
            acts.append(_action(FIX_LISTING, r, a, "low_quality_score", ev))
        # 4. Slow or paid delivery
        days = r.get("delivery_max_days")
        if (days is not None and not pd.isna(days) and days > a.slow_delivery_days) or (r.get("delivery_fee") or 0) > 0:
            ev = dict(base_ev, delivery_max_days=None if pd.isna(days) else int(days), delivery_fee_gbp=r.get("delivery_fee"))
            acts.append(_action(FIX_DELIVERY, r, a, "slow_or_paid_delivery", ev))
        # 5. Thin stock on a product with demand
        qty = r.get("max_qty_selectable")
        if qty is not None and not pd.isna(qty) and qty <= a.low_stock_qty and r["est_units_month"] >= a.in_demand_floor_units:
            ev = dict(base_ev, max_qty_selectable=int(qty))
            acts.append(_action(STOCK_RISK, r, a, "low_stock_with_demand", ev))
        # 6. Duplicate product pages split reviews and sales
        if r.get("flag_duplicate_page"):
            acts.append(_action(MERGE_DUPLICATE, r, a, "duplicate_page", dict(base_ev, notes=r.get("listing_notes"))))
    # 7. Category-level: the most under-supplied category
    if cat_summary is not None and not cat_summary.empty:
        top = cat_summary.iloc[0]
        r = {"category": top["category"], "product_id": "", "title": f"Category: {top['category']}",
             "seller": "", "est_commission_month": top["est_commission_month"]}
        ev = {"products_sampled": int(top["products"]), "distinct_sellers": int(top["distinct_sellers"]),
              "share_single_offer": round(top["share_single_offer"], 2),
              "est_units_per_seller_month": round(top["units_per_seller"], 1),
              "top_seller_share_gmv": round(top["top_seller_share_gmv"], 2),
              "est_commission_month_gbp": round(top["est_commission_month"], 2),
              "under_supply_index": int(top["under_supply_index"])}
        acts.append(_action(CATEGORY_RECRUIT, r, a, "most_under_supplied_category", ev))
    out = pd.DataFrame(acts)
    if out.empty:
        return out
    out = out.sort_values("priority_gbp_month", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.insert(1, "action_id", [f"A{i:02d}-{t.split()[0][:3].upper()}-{p or c[:4]}"
                                for i, (t, p, c) in enumerate(zip(out["action_type"], out["product_id"], out["category"]), 1)])
    return out


def load_products(path) -> pd.DataFrame:
    return pd.read_csv(path)


def load_listings(path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=["category", "price"])
