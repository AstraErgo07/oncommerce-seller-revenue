"""
seller_growth/revenue.py - Seller Revenue Agent economics for OnBuy (OnCommerce network),
focused on ONE category: climate control (fans, heaters, dehumidifiers, portable AC, air purifiers).

What OnCommerce earns from a seller each month =
    subscription (Standard / Partner / Professional)
  + sales commission (15% standard, £0.25 minimum, on price incl. delivery)
  + Boost CPA (5-30% extra, charged only on boosted sales)

REAL (published, read 11 Nov 2026): subscription prices incl. the promo that ends Jan 2028,
commission rates and minimum fee (oncommerce.com/gb/onbuy); Boost CPA levels (channelx.world 2023,
sellerbookkeeping.uk 2026).
LISTING INPUTS (in this repo: synthetic example data, see tools/gen_example_data.py): prices, offers, sellers, order counts
("44k+"), seller review counts, Professional Seller badge, product reviews and dates, OnBuy rank
badges, stock, delivery promise.
ESTIMATED (labelled, every one is a sidebar assumption in Settings): units sold,
seller tier where no badge is shown, whole-account orders and GMV, Boost adoption, seasonality,
uplift and success rates, churn and upgrade rates, cost to serve.
Pure functions: no Streamlit, no AI.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd

try:  # imported as part of the package (Streamlit app)
    from .calc import Assumptions as _QA, est_monthly_units, listing_quality, months_since
except ImportError:  # run from inside seller_growth/ (unittest, python revenue.py)
    from calc import Assumptions as _QA, est_monthly_units, listing_quality, months_since

SCRAPE_DATE = date(2026, 11, 11)
CATEGORY = "climate control"

# ---------------------------------------------------------------------------
# REAL published pricing (oncommerce.com/gb/onbuy, read 11 Nov 2026). £ per month, ex VAT.
# ---------------------------------------------------------------------------
TIERS = ["Standard", "Partner", "Professional"]
SUB_PROMO = {"Standard": 25.0, "Partner": 69.0, "Professional": 249.0}   # promo until Jan 2028
SUB_LIST = {"Standard": 25.0, "Partner": 129.0, "Professional": 499.0}   # list price
PROMO_END = date(2028, 1, 1)
TIER_FEATURES = {
    "Standard": "API & integrations, on/off-site ad tools, no listing fees",
    "Partner": "+ priority support, dedicated store, custom collections, store search, "
               "comparison tables, product-page seller showcase",
    "Professional": "+ Professional Seller badge, logo sitewide, customised store, dedicated product "
                    "carousels, prominent 'Buy it Again'",
}
# REAL (channelx.world Aug 2023; sellerbookkeeping.uk 2026): Boost CPA charged only on boosted sales.
BOOST_LEVELS = {"Light": 0.05, "Plus": 0.10, "Pro": 0.15, "Max": 0.20, "Ultra": 0.30}

# ---------------------------------------------------------------------------
# ESTIMATE: seasonality. Monthly demand index (Jan..Dec, mean = 1.0) by season group.
# Judgement for the UK, NOT OnBuy data. Scrape month is November.
# ---------------------------------------------------------------------------
SEASON_PROFILES = {
    "heating": [2.0, 1.6, 1.1, 0.6, 0.3, 0.15, 0.15, 0.15, 0.45, 1.3, 2.1, 2.1],
    "cooling": [0.2, 0.2, 0.3, 0.5, 1.2, 2.4, 3.0, 2.4, 0.8, 0.4, 0.3, 0.3],
    "damp":    [1.5, 1.3, 1.0, 0.7, 0.6, 0.6, 0.6, 0.6, 0.9, 1.3, 1.4, 1.5],
    "all-year": [1.0] * 12,
}
SUBCAT_SEASON = {
    "fan heaters": "heating", "oil filled radiators": "heating", "convector heaters": "heating",
    "tower fans": "cooling", "pedestal fans": "cooling", "desk fans": "cooling", "air conditioners": "cooling",
    "dehumidifiers": "damp", "air purifiers": "all-year",
}
LARGE_APPLIANCE_CANDIDATES = {"air conditioners", "dehumidifiers"}

# Play types
UPGRADE = "Upgrade subscription"
RETAIN = "Retention / downgrade risk"
BOOST = "Boost adoption"
FIRST_SALE = "Listing fix to unlock sales"
LEAK_OOS = "Leakage: out of stock in season"
LEAK_DUP = "Leakage: duplicate product page"
LEAK_DELIVERY = "Leakage: paid or slow delivery"
LEAK_PRICE = "Leakage: price anomaly"
PLAY_TYPES = [UPGRADE, RETAIN, BOOST, FIRST_SALE, LEAK_OOS, LEAK_DUP, LEAK_DELIVERY, LEAK_PRICE]
AUTOMATED, HUMAN = "Automated journey", "Human (Seller Success)"


@dataclass
class Settings:
    """Every number the calculations use, in one place. Passed to every function; no function reads a global.
    The module-level tables above are only the published defaults copied into a new Settings."""
    # --- REAL (published) -------------------------------------------------
    commission_rate: float = 0.15            # OnCommerce Standard Selling Fee
    large_appliance_rate: float = 0.07       # "Large Appliances & White Goods" (fridges, washers, cookers...)
    ac_dehum_as_large_appliance: bool = False  # ESTIMATE/ambiguity switch; published list names none of them
    min_fee: float = 0.25
    sub_promo: dict = field(default_factory=lambda: dict(SUB_PROMO))
    sub_list: dict = field(default_factory=lambda: dict(SUB_LIST))
    boost_levels: dict = field(default_factory=lambda: dict(BOOST_LEVELS))   # REAL: Boost fee per level
    # --- ESTIMATE: product demand (same method as the first version) -------
    review_rate: float = 0.02
    review_window_months: float = 24.0       # used when the oldest review date is not known
    use_first_review_window: bool = True     # REAL oldest review date (where every review is listed) sets the window
    min_window_months: float = 6.0
    stale_after_months: float = 12.0
    stale_factor: float = 0.5
    bestseller_floor_units: float = 10.0
    hot_floor_units: float = 5.0
    in_demand_floor_units: float = 3.0
    no_signal_units: float = 0.5
    seasonality_strength: float = 1.0        # 0 = ignore seasonality, 1 = full profile
    season_profiles: dict = field(default_factory=lambda: copy.deepcopy(SEASON_PROFILES))  # ESTIMATE: Jan..Dec
    season_profile: str = ""                 # "" = per-subcategory default (SUBCAT_SEASON); else one profile for the page
    current_month: int = 11                  # scrape month (November)
    buybox_share: float = 0.8                # share of a multi-offer product's sales won by the recommended offer
    # --- ESTIMATE: whole seller account (all categories) -------------------
    seller_tenure_months: float = 36.0       # months over which lifetime orders built up
    avg_order_value: float = 35.0            # £ per order across the seller's whole catalogue
    seller_reviews_per_order: float | None = None  # None = calibrate from sellers showing both numbers
    partner_orders_k: float = 10.0           # no badge + >= this many k lifetime orders -> assume Partner
    # --- ESTIMATE: Boost ---------------------------------------------------
    boost_adoption: float = 0.20             # share of sellers running Boost
    boost_level: str = "Plus"                # average level paid by adopters
    boosted_share_of_gmv: float = 0.30       # share of an adopter's sales that go through boosted slots
    boost_incremental_share: float = 0.50    # extra sales created by Boost, as a share of boosted sales
    seller_margin: float = 0.35              # seller gross margin before OnBuy fees
    # --- ESTIMATE: plays ---------------------------------------------------
    partner_sales_uplift: float = 0.05       # sales lift from Partner features (comparison tables, showcase)
    pro_sales_uplift: float = 0.04           # extra lift from Professional badge, logo, carousels
    churn_fee_ratio: float = 0.05            # subscription / est. monthly GMV above this = churn risk
    quality_threshold: int = 70
    price_gap_threshold: float = 0.10
    first_sale_units: float = 2.0            # units/month a fixed zero-review listing could reach
    fix_uplift: float = 0.10
    delivery_uplift: float = 0.10
    merge_uplift: float = 0.05
    # --- ESTIMATE: route = automated vs human (seller value vs cost to serve) --
    p_success_human: float = 0.35
    p_success_auto: float = 0.15
    human_cost: float = 120.0                # £ per seller intervention (account manager time)
    auto_cost: float = 2.0                   # £ per automated journey (messages, tooling)
    value_horizon_months: float = 12.0
    # --- ESTIMATE: forecast and LTV ---------------------------------------
    monthly_churn: float = 0.03
    monthly_upgrade_rate: float = 0.02
    contribution_margin: float = 0.70        # OnCommerce margin on seller revenue (for LTV)
    play_ramp_months: int = 3

    def rate_for(self, subcategory: str) -> float:
        if self.ac_dehum_as_large_appliance and subcategory in LARGE_APPLIANCE_CANDIDATES:
            return float(self.large_appliance_rate)
        return float(self.commission_rate)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


RevenueAssumptions = Settings   # old name, kept so older scripts still run


def settings_hash(a: Settings) -> str:
    """Deterministic short hash of every setting, logged with each decision."""
    return hashlib.sha256(json.dumps(asdict(a), sort_keys=True, default=str).encode()).hexdigest()[:12]


def break_even_stake(a: Settings, call_cost: float | None = None, success_gap: float | None = None) -> float:
    """£ a month at stake above which a Seller Success call beats an automated message:
    (call cost - message cost) / (months x (call success - message success)). inf if the call is never better."""
    cc = a.human_cost if call_cost is None else call_cost
    gap = (a.p_success_human - a.p_success_auto) if success_gap is None else success_gap
    if gap <= 0:
        return float("inf")
    return (cc - a.auto_cost) / (a.value_horizon_months * gap)


def break_even_grid(a: Settings, call_costs=(60.0, 120.0, 240.0), gaps=(0.10, 0.20, 0.30)) -> pd.DataFrame:
    """Break-even £/month for each call cost (rows) and success gap in points (columns); message cost from a."""
    df = pd.DataFrame({f"{g * 100:.0f} points": [break_even_stake(a, c, g) for c in call_costs] for g in gaps},
                      index=[f"£{c:.0f}" for c in call_costs])
    df.index.name = "Cost of one call"
    df.columns.name = "How much more often a call works than a message, in percentage points"
    return df


# ---------------------------------------------------------------------------
# Seasonality and demand
# ---------------------------------------------------------------------------
def season_index(subcategory: str, month: int, a: Settings) -> float:
    """ESTIMATE: demand index for this month (1 = average month), damped by seasonality_strength."""
    prof = a.season_profiles[season_group(subcategory, a)]
    return 1.0 + a.seasonality_strength * (prof[(month - 1) % 12] - 1.0)


def season_group(subcategory: str, a: Settings | None = None) -> str:
    if a is not None and a.season_profile:
        return a.season_profile
    return SUBCAT_SEASON.get(subcategory, "all-year")


def _badge_floor(badge: str, a: Settings) -> float:
    b = (badge or "").strip().lower() if isinstance(badge, str) else ""
    return {"bestseller": a.bestseller_floor_units, "hot": a.hot_floor_units,
            "in demand": a.in_demand_floor_units}.get(b, a.no_signal_units)


def _demand_qa(a: Settings) -> _QA:
    """Map to calc.Assumptions so the review-based unit estimate is computed by the same tested function."""
    return _QA(review_rate=a.review_rate, review_window_months=a.review_window_months,
               stale_after_months=a.stale_after_months, stale_factor=a.stale_factor,
               bestseller_floor_units=0.0, in_demand_floor_units=0.0, no_signal_units=0.0,
               quality_threshold=a.quality_threshold, price_gap_threshold=a.price_gap_threshold)


def _split(x) -> list[str]:
    return [s for s in str(x).split(";") if s] if isinstance(x, str) else []


def evaluate_climate(df: pd.DataFrame, a: Settings) -> pd.DataFrame:
    """Per product: average and in-season units, commission, quality. Units now =
    max(review-based average x season index, OnBuy badge floor); 0 if out of stock or price anomaly."""
    qa = _demand_qa(a)
    out = []
    for r in df.to_dict("records"):
        for k in ("badge", "seller", "offer_sellers", "offer_prices", "offer_seller_reviews", "latest_review",
                  "first_review"):
            r[k] = r.get(k) if isinstance(r.get(k), str) else ""
        window = a.review_window_months
        if a.use_first_review_window and r["first_review"]:
            window = max(months_since(r["first_review"]), a.min_window_months)
        elif a.use_first_review_window and isinstance(r.get("oldest_visible_review"), str) and r["oldest_visible_review"]:
            window = max(window, months_since(r["oldest_visible_review"]))   # reviews go back at least this far
        qa.review_window_months = window
        dp = float(r["price"]) + float(r.get("delivery_fee") or 0.0)
        rate = a.rate_for(r["subcategory"])
        avg_units = est_monthly_units(int(r.get("product_review_count") or 0), months_since(r["latest_review"] or None),
                                      "", qa)
        idx = season_index(r["subcategory"], a.current_month, a)
        potential = max(avg_units * idx, _badge_floor(r["badge"], a))
        oos, anomaly = bool(r.get("flag_out_of_stock")), bool(r.get("flag_price_anomaly"))
        units_now = 0.0 if (oos or anomaly) else potential
        cpu = max(rate * dp, a.min_fee)
        score, issues = listing_quality(r, qa)
        if oos:
            issues.append("Out of stock")
        if anomaly:
            issues.append("Price looks wrong for the product")
        if r.get("flag_overseas_dispatch"):
            issues.append("Dispatched from outside the UK")
        offers = [float(x) for x in _split(r["offer_prices"])]
        # Average selling price per unit, incl. delivery: each offer's price weighted by its share of the
        # product's sales (the recommended offer carries the delivery fee). One offer: just the delivered price.
        if len(offers) > 1:
            fee = float(r.get("delivery_fee") or 0.0)
            avg_price = sum(sh * (op + fee * (i == 0)) for i, (op, sh) in enumerate(zip(offers, offer_shares(len(offers), a))))
        else:
            avg_price = dp
        r.update({
            "season_group": season_group(r["subcategory"], a),
            "season_index_now": idx, "delivered_price": dp, "commission_rate": rate,
            "commission_per_unit": cpu, "min_fee_binds": rate * dp < a.min_fee,
            "review_window_months": window,
            "est_units_avg_month": avg_units, "est_units_potential": potential, "est_units_month": units_now,
            "est_units_deseasonalised": potential / idx if idx > 0 else potential,
            "avg_price": avg_price,
            "est_gmv_month": units_now * avg_price, "est_commission_month": units_now * cpu,
            "lost_units_month": potential if oos else 0.0,
            "lowest_offer": min(offers) if offers else dp, "quality_score": score,
            "quality_issues": "; ".join(issues),
        })
        out.append(r)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Seller accounts
# ---------------------------------------------------------------------------
def calibrate_reviews_per_order(products: pd.DataFrame) -> tuple[float, int]:
    """Calibrated ratio: seller reviews / lifetime orders, median over sellers whose listing shows both."""
    p = products.dropna(subset=["seller_orders_k", "seller_review_count"])
    # seller labels are per category (Seller A in Heaters is not Seller A in Fans), so de-duplicate within category
    key = ["page_category", "seller"] if "page_category" in p.columns else ["seller"]
    p = p[(p["seller_orders_k"] > 0) & (p["seller_review_count"] > 0)].drop_duplicates(key)
    if p.empty:
        return 0.07, 0
    return float((p["seller_review_count"] / (p["seller_orders_k"] * 1000)).median()), len(p)


def subscription_for(tier: str, a: Settings, on: date = SCRAPE_DATE) -> float:
    return float((a.sub_list if on >= PROMO_END else a.sub_promo)[tier])


def offer_shares(n_offers: int, a: Settings) -> list[float]:
    """ESTIMATE: share of a product's sales per offer. Recommended (first) offer gets buybox_share."""
    if n_offers <= 1:
        return [1.0] * max(n_offers, 0)
    rest = (1 - a.buybox_share) / (n_offers - 1)
    return [a.buybox_share] + [rest] * (n_offers - 1)


def seller_table(products: pd.DataFrame, a: Settings,
                 calibration: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per seller seen in the sample (as recommended offer or as a competing offer).
    calibration = products used to calibrate reviews-per-order (default: the same products). Category pages
    pass the whole climate sample so a thin category still gets a calibration."""
    ratio, n_cal = calibrate_reviews_per_order(products if calibration is None else calibration)
    if a.seller_reviews_per_order:
        ratio = a.seller_reviews_per_order
    s = {}

    def get(name):
        return s.setdefault(name, {"seller": name, "products_buybox": 0, "offers": 0, "pro_badge": False,
                                   "orders_k_real": None, "seller_reviews": None, "climate_units": 0.0,
                                   "climate_gmv": 0.0, "climate_commission": 0.0, "latest_review": "",
                                   "subcats": set(), "product_ids": [], "prices": []})

    for r in products.to_dict("records"):
        sellers = _split(r["offer_sellers"])
        prices = [float(x) for x in _split(r["offer_prices"])]
        revs = str(r.get("offer_seller_reviews") or "").split(";") if r.get("offer_seller_reviews") else []
        if not sellers and r["seller"]:            # out of stock: seller known from the page/reviews, no live offer
            sellers, prices, revs = [r["seller"]], [float(r["price"])], []
        pros = _split(r.get("offer_professional"))
        shares = offer_shares(len(sellers), a)
        for i, (name, p, sh) in enumerate(zip(sellers, prices, shares)):
            d = get(name)
            d["offers"] += 1
            d["subcats"].add(r["subcategory"])
            d["product_ids"].append(r["product_id"])
            d["prices"].append(p + (r.get("delivery_fee") or 0.0) * (i == 0))
            u = r["est_units_month"] * sh
            d["climate_units"] += u
            d["climate_gmv"] += u * (p + (r.get("delivery_fee") or 0.0) * (i == 0))
            d["climate_commission"] += u * max(r["commission_rate"] * p, a.min_fee)
            if i < len(pros) and pros[i] == "1":
                d["pro_badge"] = True              # REAL: Professional Seller tag on this offer row
            if i < len(revs) and revs[i]:
                d["seller_reviews"] = max(d["seller_reviews"] or 0, int(float(revs[i])))
            if i == 0:
                d["products_buybox"] += 1
                d["pro_badge"] |= bool(r.get("seller_professional"))
                if pd.notna(r.get("seller_orders_k")):
                    d["orders_k_real"] = float(r["seller_orders_k"])
                if pd.notna(r.get("seller_review_count")) and r.get("seller_review_count"):
                    d["seller_reviews"] = max(d["seller_reviews"] or 0, int(r["seller_review_count"]))
                if r["latest_review"] and r["latest_review"] > d["latest_review"]:
                    d["latest_review"] = r["latest_review"]
    rows = []
    for d in s.values():
        if d["orders_k_real"] is not None:
            lifetime, src = d["orders_k_real"] * 1000, "SHOWN (seller box, lower bound)"
        elif d["seller_reviews"]:
            lifetime, src = d["seller_reviews"] / ratio, f"EST. seller reviews ÷ {ratio:.3f}"
        else:
            lifetime, src = 0.0, "unknown"
        if d["pro_badge"]:
            tier, tier_src = "Professional", "SHOWN (Professional Seller badge)"
        elif lifetime >= a.partner_orders_k * 1000:
            tier, tier_src = "Partner", f"EST. (no badge, ≥{a.partner_orders_k:g}k orders)"
        else:
            tier, tier_src = "Standard", "EST. (no badge, smaller seller)"
        orders_m = lifetime / a.seller_tenure_months
        gmv = orders_m * a.avg_order_value
        comm = orders_m * max(a.commission_rate * a.avg_order_value, a.min_fee)
        sub = subscription_for(tier, a)
        boost = a.boost_adoption * a.boosted_share_of_gmv * gmv * a.boost_levels[a.boost_level]
        rev = sub + comm + boost
        rows.append({
            "seller": d["seller"], "tier": tier, "tier_source": tier_src,
            "products_buybox": d["products_buybox"], "offers_in_sample": d["offers"],
            "subcategories": ", ".join(sorted(d["subcats"])), "product_ids": ";".join(d["product_ids"]),
            "seller_reviews": d["seller_reviews"], "lifetime_orders": lifetime, "orders_source": src,
            "est_orders_month": orders_m, "est_account_gmv_month": gmv,
            "subscription_month": sub, "est_commission_month": comm, "est_boost_month": boost,
            "est_revenue_month": rev, "climate_units_month": d["climate_units"],
            "climate_gmv_month": d["climate_gmv"], "climate_commission_month": d["climate_commission"],
            "climate_avg_price": (d["climate_gmv"] / d["climate_units"] if d["climate_units"] > 0
                                  else (sum(d["prices"]) / len(d["prices"]) if d["prices"] else float("nan"))),
            "fee_to_sales": sub / gmv if gmv else float("inf"),
            "fee_to_sales_list": subscription_for(tier, a, PROMO_END) / gmv if gmv else float("inf"),
            "latest_review": d["latest_review"],
            "ltv": rev * a.contribution_margin / a.monthly_churn if a.monthly_churn > 0 else float("inf"),
        })
    out = pd.DataFrame(rows).sort_values("est_revenue_month", ascending=False).reset_index(drop=True)
    out.attrs.update(reviews_per_order=ratio, calibration_sellers=n_cal)
    return out


def revenue_mix(sellers: pd.DataFrame) -> dict:
    return {"Subscriptions": float(sellers["subscription_month"].sum()),
            "Commission": float(sellers["est_commission_month"].sum()),
            "Boost": float(sellers["est_boost_month"].sum())}


# ---------------------------------------------------------------------------
# Plays
# ---------------------------------------------------------------------------
def route_play(stake_month: float, a: Settings) -> tuple[str, float, float, float]:
    """Seller value vs cost to serve. Value over the horizon of each route, net of its cost:
    human = stake x horizon x p_human - human_cost ; automated = stake x horizon x p_auto - auto_cost.
    Returns (route, net value human, net value automated, expected £/month for the chosen route)."""
    vh = stake_month * a.value_horizon_months * a.p_success_human - a.human_cost
    va = stake_month * a.value_horizon_months * a.p_success_auto - a.auto_cost
    route = HUMAN if vh > va else AUTOMATED
    return route, vh, va, stake_month * (a.p_success_human if route == HUMAN else a.p_success_auto)


def boost_seller_roi(level: float, a: Settings, rate: float) -> float:
    """Seller's incremental gross profit per £1 of Boost fee:
    i x (margin - commission) / ((1 + i) x level). >= 1 means Boost pays for itself."""
    i = a.boost_incremental_share
    return i * (a.seller_margin - rate) / ((1 + i) * level) if level else 0.0


def best_boost_level(a: Settings, rate: float) -> str | None:
    ok = [n for n, l in a.boost_levels.items() if boost_seller_roi(l, a, rate) >= 1.0]
    return ok[-1] if ok else None


def upgrade_case(seller: dict, a: Settings) -> dict | None:
    """Standard->Partner or Partner->Professional when the seller's estimated sales lift pays the extra fee."""
    tier = seller["tier"]
    if tier == "Professional":
        return None
    nxt = TIERS[TIERS.index(tier) + 1]
    fee_delta = a.sub_promo[nxt] - a.sub_promo[tier]
    uplift = a.partner_sales_uplift if nxt == "Partner" else a.pro_sales_uplift
    gain = seller["est_account_gmv_month"] * uplift * a.seller_margin
    if gain <= fee_delta:
        return None
    return {"next_tier": nxt, "fee_delta": fee_delta, "seller_gain": gain,
            "stake": fee_delta + seller["est_account_gmv_month"] * uplift * a.commission_rate}


def _play(ptype, seller, rule, stake, evidence, a, product=None):
    route, vh, va, exp = route_play(stake, a)
    return {"play_type": ptype, "seller": seller, "product_id": (product or {}).get("product_id", ""),
            "title": (product or {}).get("title", ""), "subcategory": (product or {}).get("subcategory", ""),
            "rule": rule, "stake_month": stake, "route": route, "net_value_human": vh, "net_value_auto": va,
            "expected_month": exp, "evidence": evidence}


def generate_plays(products: pd.DataFrame, sellers: pd.DataFrame, a: Settings) -> pd.DataFrame:
    plays = []
    by_seller = {r["seller"]: r for r in sellers.to_dict("records")}
    for s in by_seller.values():
        base = {"tier": s["tier"], "tier_source": s["tier_source"], "lifetime_orders": round(s["lifetime_orders"]),
                "orders_source": s["orders_source"], "est_account_gmv_month_gbp": round(s["est_account_gmv_month"]),
                "subscription_month_gbp": s["subscription_month"],
                "est_revenue_month_gbp": round(s["est_revenue_month"], 2)}
        up = upgrade_case(s, a)
        if up:
            ev = dict(base, next_tier=up["next_tier"], next_tier_features=TIER_FEATURES[up["next_tier"]],
                      extra_fee_month_gbp=up["fee_delta"], est_seller_gain_month_gbp=round(up["seller_gain"], 2))
            plays.append(_play(UPGRADE, s["seller"], "sales_lift_pays_next_tier", up["stake"], ev, a))
        promo_step = s["tier"] in ("Partner", "Professional") and s["fee_to_sales_list"] > a.churn_fee_ratio
        if s["fee_to_sales"] > a.churn_fee_ratio or promo_step:
            ev = dict(base, fee_to_sales_now=round(s["fee_to_sales"], 3),
                      fee_to_sales_after_jan_2028=round(s["fee_to_sales_list"], 3),
                      list_price_after_jan_2028_gbp=a.sub_list[s["tier"]], latest_review=s["latest_review"] or "none")
            rule = ("no_sales_evidence" if not s["lifetime_orders"] else "fee_to_sales_high"
                    if s["fee_to_sales"] > a.churn_fee_ratio else "promo_price_step_jan_2028")
            plays.append(_play(RETAIN, s["seller"], rule, s["est_revenue_month"], ev, a))
    for r in products.to_dict("records"):
        seller = r["seller"]
        if not seller:
            seller = "(no live seller)"
        pev = {"price_gbp": r["price"], "delivered_price_gbp": round(r["delivered_price"], 2),
               "offers": int(r["offers_count"]), "product_reviews": int(r["product_review_count"]),
               "onbuy_badge": r["badge"] or "none", "in_stock": not r["flag_out_of_stock"],
               "season_group": r["season_group"], "season_index_now": round(r["season_index_now"], 2),
               "est_units_month": round(r["est_units_month"], 1),
               "est_commission_month_gbp": round(r["est_commission_month"], 2), "quality_score": r["quality_score"]}
        live = not r["flag_out_of_stock"] and not r["flag_price_anomaly"]
        gap = (r["price"] - r["lowest_offer"]) / r["lowest_offer"] if r["lowest_offer"] else 0.0
        # Boost: good, competitive, in-season listing without a Bestseller badge
        lvl = best_boost_level(a, r["commission_rate"])
        if (live and lvl and r["quality_score"] >= a.quality_threshold and gap <= a.price_gap_threshold
                and r["badge"] != "Bestseller" and r["season_index_now"] >= 1.0):
            L, sh, i = a.boost_levels[lvl], a.boosted_share_of_gmv, a.boost_incremental_share
            gmv = r["est_units_month"] * r["delivered_price"]
            stake = gmv * sh * (1 + i) * L + r["est_units_month"] * sh * i * r["commission_per_unit"]
            ev = dict(pev, suggested_boost_level=f"{lvl} ({L:.0%})",
                      seller_boost_roi=round(boost_seller_roi(L, a, r["commission_rate"]), 2),
                      breakeven_incremental_share=round(L / (a.seller_margin - r["commission_rate"] - L), 2)
                      if a.seller_margin - r["commission_rate"] - L > 0 else "n/a")
            plays.append(_play(BOOST, seller, "in_season_quality_listing_no_bestseller", stake, ev, a, r))
        # Listing fix to unlock the first / more sales
        if live and (r["product_review_count"] == 0 or r["quality_score"] < a.quality_threshold):
            if r["product_review_count"] == 0:
                stake = max(a.first_sale_units - r["est_units_month"], 0) * r["commission_per_unit"] \
                    + a.fix_uplift * r["est_commission_month"]
                rule = "no_reviews_yet"
            else:
                stake, rule = a.fix_uplift * r["est_commission_month"], "low_quality_score"
            if r["quality_score"] < a.quality_threshold or r["product_review_count"] == 0:
                plays.append(_play(FIRST_SALE, seller, rule, stake, dict(pev, issues=r["quality_issues"]), a, r))
        # Leakage
        if r["flag_out_of_stock"]:
            stake = r["lost_units_month"] * r["commission_per_unit"]
            plays.append(_play(LEAK_OOS, seller, "out_of_stock_in_season", stake,
                               dict(pev, lost_units_month=round(r["lost_units_month"], 1), notes=r["listing_notes"]), a, r))
        if r["flag_duplicate_page"]:
            plays.append(_play(LEAK_DUP, seller, "duplicate_page", a.merge_uplift * r["est_commission_month"],
                               dict(pev, notes=r["listing_notes"]), a, r))
        if live and ((r["delivery_fee"] or 0) > 0 or (pd.notna(r["delivery_max_days"]) and r["delivery_max_days"] > 7)):
            plays.append(_play(LEAK_DELIVERY, seller, "paid_or_slow_delivery", a.delivery_uplift * r["est_commission_month"],
                               dict(pev, delivery_fee_gbp=r["delivery_fee"], delivery_max_days=r["delivery_max_days"]), a, r))
        prices = [float(x) for x in _split(r["offer_prices"])]
        if r["flag_price_anomaly"] or (len(prices) > 1 and max(prices) > 2 * min(prices)):
            ev = dict(pev, lowest_offer_gbp=min(prices) if prices else r["price"],
                      highest_offer_gbp=max(prices) if prices else r["price"], notes=r["listing_notes"])
            who = seller if r["flag_price_anomaly"] else _split(r["offer_sellers"])[prices.index(max(prices))]
            plays.append(_play(LEAK_PRICE, who, "price_anomaly" if r["flag_price_anomaly"] else "outlier_offer",
                               0.0, ev, a, r))
    out = pd.DataFrame(plays)
    if out.empty:
        return out
    out = out.sort_values(["expected_month", "stake_month"], ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.insert(1, "play_id", [f"P{i:02d}" for i in range(1, len(out) + 1)])
    return out


def top_play_per_seller(plays: pd.DataFrame) -> pd.DataFrame:
    if plays.empty:
        return plays
    return plays.drop_duplicates("seller").reset_index(drop=True)


def leakage_summary(products: pd.DataFrame, a: Settings) -> dict:
    floor = products[products["min_fee_binds"]]
    former = set()
    for n in products["listing_notes"].fillna(""):
        if "no longer listed" in n.lower() or "former seller" in n.lower():
            former.add(n)
    return {"min_fee_floor_products": int(len(floor)),
            "cheapest_delivered_price": float(products["delivered_price"].min()),
            "min_fee_breakeven_price": a.min_fee / a.commission_rate,
            "out_of_stock_products": int(products["flag_out_of_stock"].sum()),
            "lost_commission_oos_month": float((products["lost_units_month"] * products["commission_per_unit"]).sum()),
            "duplicate_pages": int(products["flag_duplicate_page"].sum()),
            "price_anomalies": int(products["flag_price_anomaly"].sum()),
            "paid_delivery_products": int((products["delivery_fee"] > 0).sum()),
            "products_with_reviews_from_departed_sellers": len(former)}


# ---------------------------------------------------------------------------
# Forecast and LTV
# ---------------------------------------------------------------------------
def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def forecast(sellers: pd.DataFrame, plays: pd.DataFrame, products: pd.DataFrame, a: Settings,
             months: int = 12, start: date = date(2026, 12, 1)) -> pd.DataFrame:
    """Monthly revenue to OnCommerce from the sampled sellers.
    base(t) = survival(t) x [subscription(t) + commission + Boost], survival = (1 - churn)^t,
    subscription(t) moves a share 1-(1-upgrade_rate)^t of each seller up one tier and switches to
    list prices from Jan 2028. with_plays adds each play's expected £/month (route success rate),
    ramped in over play_ramp_months from month 2. climate_commission is the category-only commission:
    today's units de-seasonalised, then x that month's season index (in-stock, correctly priced listings)."""
    rows = []
    play_exp = float(plays["expected_month"].sum()) if not plays.empty else 0.0
    live = products[~products["flag_out_of_stock"] & ~products["flag_price_anomaly"]]
    for t in range(1, months + 1):
        d = _add_months(start, t - 1)
        surv = (1 - a.monthly_churn) ** t
        up = 1 - (1 - a.monthly_upgrade_rate) ** t
        subs = 0.0
        for s in sellers.to_dict("records"):
            cur = subscription_for(s["tier"], a, d)
            nxt = subscription_for(TIERS[min(TIERS.index(s["tier"]) + 1, 2)], a, d)
            subs += cur + up * (nxt - cur)
        other = float(sellers["est_commission_month"].sum() + sellers["est_boost_month"].sum())
        base = surv * (subs + other)
        ramp = 0.0 if t < 2 else min(1.0, (t - 1) / max(a.play_ramp_months, 1))
        units = [r["est_units_deseasonalised"] * season_index(r["subcategory"], d.month, a) for r in live.to_dict("records")]
        climate = float(sum(u * r["commission_per_unit"] for u, r in zip(units, live.to_dict("records"))))
        rows.append({"month": d.strftime("%b %Y"), "t": t, "survival": surv, "subscriptions": surv * subs,
                     "commission_and_boost": surv * other, "base": base,
                     "with_plays": base + surv * ramp * play_exp, "climate_commission": climate,
                     "category_units": float(sum(units)),
                     "promo_ended": d >= PROMO_END})
    return pd.DataFrame(rows)


def ltv(monthly_revenue: float, a: Settings) -> float:
    """Seller lifetime value to OnCommerce = monthly revenue x contribution margin / monthly churn."""
    return monthly_revenue * a.contribution_margin / a.monthly_churn if a.monthly_churn > 0 else float("inf")


def run_all(df: pd.DataFrame, a: Settings, calibration: pd.DataFrame | None = None):
    products = evaluate_climate(df, a)
    sellers = seller_table(products, a, calibration)
    plays = generate_plays(products, sellers, a)
    return products, sellers, plays


def run_category(df_all: pd.DataFrame, subcategories, a: Settings):
    """One category manager's view: only that category's products and the sellers seen on them.
    Reviews-per-order is still calibrated on every climate seller that shows both numbers."""
    df = df_all[df_all["subcategory"].isin(list(subcategories))].reset_index(drop=True)
    return run_all(df, a, calibration=df_all)


def units_summary(products: pd.DataFrame) -> dict:
    """Headline units/GMV for a category (all 🟠 estimates built on review counts and badges)."""
    units, gmv = float(products["est_units_month"].sum()), float(products["est_gmv_month"].sum())
    return {"est_units_month": units, "avg_price": gmv / units if units else float("nan"),
            "est_units_avg_month": float(products["est_units_avg_month"].sum()),
            "est_gmv_month": float(products["est_gmv_month"].sum()),
            "est_commission_month": float(products["est_commission_month"].sum()),
            "lost_units_month": float(products["lost_units_month"].sum())}


if __name__ == "__main__":
    from pathlib import Path
    a = Settings()
    p, s, pl = run_all(pd.read_csv(Path(__file__).parent / "example_products.csv"), a)
    print(f"reviews/order calibrated on {s.attrs['calibration_sellers']} sellers: {s.attrs['reviews_per_order']:.4f}")
    print(s[["seller", "tier", "tier_source", "lifetime_orders", "est_account_gmv_month", "subscription_month",
             "est_commission_month", "est_boost_month", "est_revenue_month", "fee_to_sales"]].round(2).to_string())
    print(revenue_mix(s))
    print(pl[["rank", "play_type", "seller", "rule", "stake_month", "route", "expected_month"]].round(2).to_string())
    print(leakage_summary(p, a))
    print(forecast(s, pl, p, a, 18)[["month", "base", "with_plays", "climate_commission"]].round(0).to_string())
