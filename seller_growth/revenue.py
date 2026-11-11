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
from dataclasses import replace as dc_replace
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
    # Sales lift a seller gets from the next tier's features. No public evidence, so a cautious 2% by default.
    partner_sales_uplift: float = 0.02       # sales lift from Partner features (comparison tables, showcase)
    pro_sales_uplift: float = 0.02           # extra lift from Professional badge, logo, carousels
    churn_fee_ratio: float = 0.05            # subscription / est. monthly GMV above this = churn risk
    at_risk_loss_prob: float = 0.30          # share of at-risk sellers who would cancel or downgrade without help
    quality_threshold: int = 70
    price_gap_threshold: float = 0.10
    first_sale_units: float = 2.0            # units/month a fixed zero-review listing could reach
    fix_uplift: float = 0.10
    delivery_uplift: float = 0.10
    merge_uplift: float = 0.05
    # --- ESTIMATE: route = automated vs human (seller value vs cost to serve) --
    p_success_human: float = 0.35
    p_success_auto: float = 0.15
    # Cost of a call, built up (rough estimates, not OnCommerce data):
    #   fully loaded yearly cost of a Seller Success exec / productive hours a year x hours per completed call
    sse_annual_cost: float = 45000.0
    sse_productive_hours: float = 1600.0
    call_hours: float = 1.4                  # prep, attempts, the call, follow-up and CRM notes
    # Cost of an automated message per seller: journey build and upkeep / sellers reached + sending cost
    journey_build_cost: float = 1500.0
    journey_sellers_reached: float = 2000.0
    message_send_cost: float = 0.05
    call_cost_override: float | None = None      # set only to test a fixed call cost (sensitivity grid, tests)
    message_cost_override: float | None = None
    value_horizon_months: float = 12.0
    # --- ESTIMATE: forecast and LTV ---------------------------------------
    monthly_churn: float = 0.03
    monthly_upgrade_rate: float = 0.02
    contribution_margin: float = 0.70        # OnCommerce margin on seller revenue (for LTV)
    play_ramp_months: int = 3

    @property
    def human_cost(self) -> float:
        """£ per Seller Success call: yearly cost / productive hours x hours per call (unless overridden)."""
        if self.call_cost_override is not None:
            return float(self.call_cost_override)
        return self.sse_annual_cost / self.sse_productive_hours * self.call_hours if self.sse_productive_hours else 0.0

    @property
    def auto_cost(self) -> float:
        """£ per seller for an automated message: build cost / sellers reached + send cost (unless overridden)."""
        if self.message_cost_override is not None:
            return float(self.message_cost_override)
        build = self.journey_build_cost / self.journey_sellers_reached if self.journey_sellers_reached else 0.0
        return build + self.message_send_cost

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


def survival_months(a: Settings) -> float:
    """Expected months a seller is still trading over the horizon: sum of (1 - churn)^t for t = 1..horizon.
    The same monthly churn is used for LTV and the forecast."""
    h = int(round(a.value_horizon_months))
    return float(sum((1 - a.monthly_churn) ** t for t in range(1, h + 1)))


def contribution_factor(a: Settings) -> float:
    """£ of OnCommerce contribution over the horizon per £1 a month of extra platform revenue that lasts:
    contribution margin x survival-weighted months."""
    return a.contribution_margin * survival_months(a)


def break_even_stake(a: Settings, call_cost: float | None = None, success_gap: float | None = None) -> float:
    """£ of platform revenue a month at stake above which a Seller Success call beats an automated message:
    (call cost - message cost) / (contribution margin x survival-weighted months x (call success - message
    success)). inf if the call is never more successful."""
    cc = a.human_cost if call_cost is None else call_cost
    gap = (a.p_success_human - a.p_success_auto) if success_gap is None else success_gap
    f = contribution_factor(a)
    if gap <= 0 or f <= 0:
        return float("inf")
    return (cc - a.auto_cost) / (f * gap)


def break_even_grid(a: Settings, call_costs=(20.0, 40.0, 80.0), gaps=(0.10, 0.20, 0.30)) -> pd.DataFrame:
    """Break-even £/month for each call cost (rows) and success gap in points (columns); message cost from a."""
    df = pd.DataFrame({f"{g * 100:.0f} points": [break_even_stake(a, c, g) for c in call_costs] for g in gaps},
                      index=[f"£{c:.0f}" for c in call_costs])
    df.index.name = "Cost of one call"
    df.columns.name = "How much more often a call works than a message, in percentage points"
    return df


# ---------------------------------------------------------------------------
# Seasonality and demand
# ---------------------------------------------------------------------------
def _num(x) -> float:
    """A missing number (None or NaN) counts as 0."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v != v else v


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
        dp = float(r["price"]) + _num(r.get("delivery_fee"))
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
            fee = _num(r.get("delivery_fee"))
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
            d["prices"].append(p + _num(r.get("delivery_fee")) * (i == 0))
            u = r["est_units_month"] * sh
            d["climate_units"] += u
            d["climate_gmv"] += u * (p + _num(r.get("delivery_fee")) * (i == 0))
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
    """Seller Success call or automated message, on OnCommerce contribution, not GMV.
    stake_month = extra platform revenue a month if the action works (fees and commission, not seller sales).
    Net contribution of a route = stake x contribution margin x survival-weighted months x success rate - its cost.
    Returns (route, net contribution if called, net contribution if messaged, expected extra revenue a month)."""
    f = contribution_factor(a)
    vh = stake_month * f * a.p_success_human - a.human_cost
    va = stake_month * f * a.p_success_auto - a.auto_cost
    route = HUMAN if vh > va else AUTOMATED
    return route, vh, va, stake_month * (a.p_success_human if route == HUMAN else a.p_success_auto)


def why_route(stake_month: float, a: Settings) -> str:
    """Why the chosen route wins, with both net values after cost."""
    _, vh, va, _ = route_play(stake_month, a)
    nets = (f"Net contribution after cost: call £{vh:,.0f} (cost £{a.human_cost:,.2f}), message £{va:,.0f} "
            f"(cost £{a.auto_cost:,.2f}).")
    be = break_even_stake(a)
    if be == float("inf"):
        return "A call is not more successful than a message here, so the cheaper message wins. " + nets
    if vh > va:
        return (f"£{stake_month:,.0f} a month is at stake, above the £{be:,.0f} tipping point, so the higher success "
                "rate of a call is worth its extra cost. " + nets)
    return (f"£{stake_month:,.0f} a month is at stake, below the £{be:,.0f} tipping point, so the extra cost of a "
            "call is not repaid and the automated message wins. " + nets)


def boost_seller_roi(level: float, a: Settings, rate: float) -> float:
    """Seller's incremental gross profit per £1 of Boost fee:
    i x (margin - commission) / ((1 + i) x level). >= 1 means Boost pays for itself."""
    i = a.boost_incremental_share
    return i * (a.seller_margin - rate) / ((1 + i) * level) if level else 0.0


def best_boost_level(a: Settings, rate: float) -> str | None:
    ok = [n for n, l in a.boost_levels.items() if boost_seller_roi(l, a, rate) >= 1.0]
    return ok[-1] if ok else None


def upgrade_case(seller: dict, a: Settings) -> dict | None:
    """Standard->Partner or Partner->Professional, judged on the SELLER's economics first.
    Extra sales = account GMV x assumed sales lift from the next tier (an assumption, default 2%).
    Seller extra profit = extra sales x (seller margin - commission) - extra subscription.
    No case (None) if the seller would not be better off at today's price. Needs validation when the seller is only
    better off on thin margins, would lose money at the Jan 2028 list price, or the tier or orders are estimated."""
    tier = seller["tier"]
    if tier == "Professional":
        return None
    nxt = TIERS[TIERS.index(tier) + 1]
    gmv = float(seller.get("est_account_gmv_month") or 0.0)
    if gmv <= 0:
        return None
    fee_delta = a.sub_promo[nxt] - a.sub_promo[tier]
    fee_delta_list = a.sub_list[nxt] - a.sub_list[tier]
    uplift = a.partner_sales_uplift if nxt == "Partner" else a.pro_sales_uplift
    extra_sales = gmv * uplift
    extra_profit = extra_sales * (a.seller_margin - a.commission_rate)
    seller_net = extra_profit - fee_delta
    if seller_net <= 0:
        return None
    seller_net_list = extra_profit - fee_delta_list
    reasons = []
    if not str(seller.get("tier_source", "")).startswith("SHOWN"):
        reasons.append("current tier is estimated, not shown")
    if not str(seller.get("orders_source", "")).startswith("SHOWN"):
        reasons.append("order volume is estimated from reviews")
    if seller_net_list <= 0:
        reasons.append("seller would lose money at the January 2028 list price")
    if seller_net < fee_delta:
        reasons.append("seller gain is thin compared with the extra fee")
    return {"next_tier": nxt, "fee_delta": fee_delta, "fee_delta_list": fee_delta_list, "uplift": uplift,
            "extra_sales": extra_sales, "seller_gain": extra_profit, "seller_net": seller_net,
            "seller_net_list": seller_net_list, "needs_validation": bool(reasons), "validation_reasons": reasons,
            "stake": fee_delta + extra_sales * a.commission_rate}


FIX_TYPES = (LEAK_OOS, LEAK_DELIVERY, LEAK_DUP, LEAK_PRICE, FIRST_SALE)
OPPORTUNITY = {LEAK_OOS: "Fix a sales leak", LEAK_DELIVERY: "Fix a sales leak", LEAK_DUP: "Fix a sales leak",
               LEAK_PRICE: "Fix a sales leak", FIRST_SALE: "Improve listings and range", BOOST: "Boost advertising",
               UPGRADE: "Subscription upgrade", RETAIN: "Retention or downgrade risk"}
NEXT_REVIEW_DAYS = {LEAK_OOS: 14, LEAK_PRICE: 14, LEAK_DELIVERY: 30, LEAK_DUP: 30, FIRST_SALE: 30, BOOST: 30,
                    UPGRADE: 60, RETAIN: 30}


def _confidence(ptype: str, evidence: dict) -> str:
    """Low or Medium; never High, because the data is synthetic and the uplifts are assumptions."""
    if ptype in (UPGRADE, RETAIN):
        est = (not str(evidence.get("orders_source", "")).startswith("SHOWN")
               or not str(evidence.get("tier_source", "")).startswith("SHOWN"))
        return "Low" if est or evidence.get("needs_validation") else "Medium"
    return "Low" if int(evidence.get("product_reviews", 0) or 0) < 5 else "Medium"


def _play(ptype, seller, rule, stake, evidence, a, product=None):
    route, vh, va, exp = route_play(stake, a)
    p = a.p_success_human if route == HUMAN else a.p_success_auto
    cost = a.human_cost if route == HUMAN else a.auto_cost
    s_m = survival_months(a)
    return {"play_type": ptype, "opportunity": OPPORTUNITY[ptype], "seller": seller,
            "product_id": (product or {}).get("product_id", ""),
            "title": (product or {}).get("title", ""), "subcategory": (product or {}).get("subcategory", ""),
            "rule": rule, "stake_month": stake, "route": route, "net_value_human": vh, "net_value_auto": va,
            "p_success": p, "intervention_cost": cost, "expected_month": exp,
            "expected_revenue_horizon": stake * p * s_m,
            "expected_contribution": stake * p * contribution_factor(a),
            "net_contribution": max(vh, va), "why_route": why_route(stake, a),
            "confidence": _confidence(ptype, evidence), "next_review_days": NEXT_REVIEW_DAYS[ptype],
            "evidence": evidence}


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
                      extra_fee_month_gbp=up["fee_delta"], extra_fee_after_jan_2028_gbp=up["fee_delta_list"],
                      assumed_sales_lift=up["uplift"], est_seller_gain_month_gbp=round(up["seller_gain"], 2),
                      est_seller_net_month_gbp=round(up["seller_net"], 2),
                      est_seller_net_after_jan_2028_gbp=round(up["seller_net_list"], 2),
                      needs_validation=up["needs_validation"],
                      validation_reasons="; ".join(up["validation_reasons"]) or "none")
            plays.append(_play(UPGRADE, s["seller"], "sales_lift_pays_next_tier", up["stake"], ev, a))
        promo_step = s["tier"] in ("Partner", "Professional") and s["fee_to_sales_list"] > a.churn_fee_ratio
        if s["fee_to_sales"] > a.churn_fee_ratio or promo_step:
            ev = dict(base, fee_to_sales_now=round(s["fee_to_sales"], 3),
                      fee_to_sales_after_jan_2028=round(s["fee_to_sales_list"], 3),
                      list_price_after_jan_2028_gbp=a.sub_list[s["tier"]], latest_review=s["latest_review"] or "none")
            rule = ("no_sales_evidence" if not s["lifetime_orders"] else "fee_to_sales_high"
                    if s["fee_to_sales"] > a.churn_fee_ratio else "promo_price_step_jan_2028")
            # Expected revenue at risk = what would be lost x the chance it is lost without help (assumption).
            if rule == "promo_price_step_jan_2028":
                lower = TIERS[TIERS.index(s["tier"]) - 1]          # downgrade risk: the tier difference is at risk
                stake = (a.sub_promo[s["tier"]] - a.sub_promo[lower]) * a.at_risk_loss_prob
            else:                                                   # cancellation risk: the whole account
                stake = s["est_revenue_month"] * a.at_risk_loss_prob
            ev["chance_of_loss_without_help"] = a.at_risk_loss_prob
            plays.append(_play(RETAIN, s["seller"], rule, stake, ev, a))
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
        # Boost: in stock, good quality, competitive, in season, not a Bestseller, pays back for seller and platform
        ok, why_not = boost_eligibility(r, a)
        if ok:
            lvl = best_boost_level(a, r["commission_rate"])
            stake = boost_stake(r, a, lvl)
            L = a.boost_levels[lvl]
            ev = dict(pev, suggested_boost_level=f"{lvl} ({L:.0%})",
                      seller_boost_roi=round(boost_seller_roi(L, a, r["commission_rate"]), 2),
                      breakeven_incremental_share=round(L / (a.seller_margin - r["commission_rate"] - L), 2)
                      if a.seller_margin - r["commission_rate"] - L > 0 else "n/a")
            if stake * contribution_factor(a) * a.p_success_auto > a.auto_cost:   # economics must pay back
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
        if live and (_num(r["delivery_fee"]) > 0 or (pd.notna(r["delivery_max_days"]) and r["delivery_max_days"] > 7)):
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
    return assign_actions(out)


def assign_actions(plays: pd.DataFrame) -> pd.DataFrame:
    """Next best action per seller, counted once.
    1. Fix first: if a seller has a sales leak or listing problem, Boost and upgrade are deferred until it is fixed.
    2. One primary action per seller: the best remaining action by expected net contribution (not by fee). An action
       marked Needs validation (an upgrade resting on estimates) only leads when the seller has nothing firmer.
    3. One optional secondary action. Only primary actions count towards totals, so no value is counted twice.
    Rank = order of primary actions by expected net contribution; other actions follow."""
    if plays.empty:
        return plays
    df = plays.copy()
    df["status"] = "Recommended"
    df.loc[(df["play_type"] == UPGRADE) & df["evidence"].map(lambda e: bool(e.get("needs_validation"))),
           "status"] = "Needs validation"
    has_fix = df[df["play_type"].isin(FIX_TYPES)].groupby("seller").size()
    defer = df["play_type"].isin([BOOST, UPGRADE]) & df["seller"].isin(has_fix.index)
    df.loc[defer, "status"] = "Deferred: fix first"
    df["role"] = "Other"
    df["_d"] = defer.astype(int)
    df["_v"] = (df["status"] == "Needs validation").astype(int)
    df = df.sort_values(["_d", "_v", "net_contribution", "stake_month"], ascending=[True, True, False, False])
    n = df.groupby("seller").cumcount()
    df.loc[n == 0, "role"] = "Primary"
    df.loc[n == 1, "role"] = "Secondary"
    df["counted"] = df["role"] == "Primary"
    df["_r"] = df["role"].map({"Primary": 0, "Secondary": 1, "Other": 2})
    df = df.sort_values(["_r", "_v", "net_contribution", "stake_month"], ascending=[True, True, False, False])
    df = df.drop(columns=["_d", "_v", "_r"]).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    df.insert(1, "play_id", [f"P{i:02d}" for i in range(1, len(df) + 1)])
    return df


def boost_eligibility(r: dict, a: Settings) -> tuple[bool, str]:
    """Boost only for a listing that can sell and is worth advertising. Returns (eligible, reason if not)."""
    if r["flag_out_of_stock"]:
        return False, "out of stock"
    if r["flag_price_anomaly"]:
        return False, "price looks wrong"
    if r["quality_score"] < a.quality_threshold or r.get("flag_duplicate_page"):
        return False, "listing quality problems to fix first"
    gap = (r["price"] - r["lowest_offer"]) / r["lowest_offer"] if r["lowest_offer"] else 0.0
    if gap > a.price_gap_threshold:
        return False, "not price competitive"
    if r["badge"] == "Bestseller":
        return False, "already a Bestseller"
    if r["season_index_now"] < 1.0:
        return False, "out of season"
    if r["est_units_month"] <= 0:
        return False, "no sales to build on"
    if best_boost_level(a, r["commission_rate"]) is None:
        return False, "Boost would not pay back for the seller"
    return True, ""


def boost_stake(r: dict, a: Settings, lvl: str) -> float:
    """Extra platform revenue a month if a seller not yet using Boost starts: Boost fees on boosted sales (including
    the extra ones) plus commission on the extra sales, x the share of sellers not already boosting (Boost fees from
    sellers already boosting are in the base revenue, so they are not counted again)."""
    L, sh, i = a.boost_levels[lvl], a.boosted_share_of_gmv, a.boost_incremental_share
    gmv = r["est_units_month"] * r["delivered_price"]
    fees = gmv * sh * (1 + i) * L + r["est_units_month"] * sh * i * r["commission_per_unit"]
    return fees * (1 - a.boost_adoption)


def top_play_per_seller(plays: pd.DataFrame) -> pd.DataFrame:
    """The primary action of each seller (the only one counted in totals)."""
    if plays.empty:
        return plays
    return plays[plays["role"] == "Primary"].reset_index(drop=True)


def actionable(plays: pd.DataFrame) -> pd.DataFrame:
    """Primary actions that are Recommended (not deferred, not awaiting validation) and worth more than they cost."""
    if plays.empty:
        return plays
    prim = top_play_per_seller(plays)
    return prim[(prim["status"] == "Recommended") & (prim["net_contribution"] > 0)]


def portfolio_summary(sellers: pd.DataFrame, plays: pd.DataFrame, a: Settings) -> dict:
    """Headline figures for a set of sellers. Each seller once; each seller's primary action only, and only if it
    is Recommended (Needs validation is reported separately, not counted)."""
    act = actionable(plays)
    n_h = int((act["route"] == HUMAN).sum()) if not act.empty else 0
    return {"sellers": int(len(sellers)), "revenue_month": float(sellers["est_revenue_month"].sum()),
            "actionable": int(len(act)), "human": n_h, "automated": int(len(act) - n_h),
            "net_contribution": float(act["net_contribution"].sum()) if not act.empty else 0.0,
            "intervention_cost": float(act["intervention_cost"].sum()) if not act.empty else 0.0,
            "expected_month": float(act["expected_month"].sum()) if not act.empty else 0.0,
            "deferred": int((plays["status"] == "Deferred: fix first").sum()) if not plays.empty else 0,
            "needs_validation": int((plays["status"] == "Needs validation").sum()) if not plays.empty else 0,
            "primary_needs_validation": int(((plays["status"] == "Needs validation") & (plays["role"] == "Primary"))
                                            .sum()) if not plays.empty else 0}


def overview_by_category(df_all: pd.DataFrame, cats: list) -> tuple[list[dict], dict, pd.DataFrame]:
    """cats = [(key, label, subcategories, Settings)]. Seller labels are per category (Example Seller A under
    Heaters is not Example Seller A under Fans), so totals are the sum of per-category summaries, never a merged run."""
    rows, sums, tops = [], None, []
    for _key, label, subcats, a in cats:
        _p, s_, pl = run_category(df_all, subcats, a)
        sm = portfolio_summary(s_, pl, a)
        sums = dict(sm) if sums is None else {k: sums[k] + v for k, v in sm.items()}
        act = actionable(pl)
        lead = act.iloc[0] if len(act) else None
        rows.append({"Category": label, "Sellers": sm["sellers"],
                     "Platform revenue £/mo": round(sm["revenue_month"]),
                     "Actionable sellers": sm["actionable"], "Calls · messages": f"{sm['human']} · {sm['automated']}",
                     "Net contribution £ (after cost)": round(sm["net_contribution"]),
                     "Leading action": "" if lead is None else f"{lead['play_type']}, {lead['seller']}"})
        for r in act.head(5).itertuples():
            tops.append({"Seller (category)": f"{r.seller} ({label})", "Action": r.play_type, "Route": r.route,
                         "Platform revenue at stake £/mo": round(r.stake_month),
                         "Net contribution £ (after cost)": round(r.net_contribution), "Confidence": r.confidence})
    top = pd.DataFrame(tops)
    if len(top):
        top = top.sort_values("Net contribution £ (after cost)", ascending=False).head(5)
    return rows, sums or {}, top


def sensitivity_table(df_all: pd.DataFrame, subcats, a: Settings) -> pd.DataFrame:
    """Recompute the headline figures with one weak assumption moved low or high, the rest unchanged."""
    tests = [
        ("1 in N buyers leaves a review", "review_rate", [(f"1 in {round(1 / (a.review_rate * 2))}", a.review_rate * 2),
                                                          (f"1 in {round(1 / (a.review_rate / 2))}", a.review_rate / 2)]),
        ("Upgrade sales lift (Partner)", "partner_sales_uplift", [("0%", 0.0), ("5%", 0.05)]),
        ("Call success rate", "p_success_human", [(f"{a.p_success_human - 0.10:.0%}", a.p_success_human - 0.10),
                                                  (f"{a.p_success_human + 0.10:.0%}", a.p_success_human + 0.10)]),
        ("Message success rate", "p_success_auto", [(f"{max(a.p_success_auto - 0.10, 0.0):.0%}", max(a.p_success_auto - 0.10, 0.0)),
                                                    (f"{a.p_success_auto + 0.10:.0%}", a.p_success_auto + 0.10)]),
        ("Sellers leaving each month", "monthly_churn", [(f"{a.monthly_churn / 2:.1%}", a.monthly_churn / 2),
                                                         (f"{a.monthly_churn * 2:.1%}", a.monthly_churn * 2)]),
    ]
    rows = []

    def one(label, value, s):
        _, sel, pl = run_category(df_all, subcats, s)
        sm = portfolio_summary(sel, pl, s)
        rows.append({"Assumption": label, "Value": value, "Platform revenue £/mo": round(sm["revenue_month"]),
                     "Actionable sellers": sm["actionable"], "Calls · messages": f"{sm['human']} · {sm['automated']}",
                     f"Net contribution £ ({a.value_horizon_months:g} mo)": round(sm["net_contribution"])})

    one("As set now", "", a)
    for label, field, vals in tests:
        for name, v in vals:
            one(label, name, dc_replace(a, **{field: v}))
    return pd.DataFrame(rows)


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
    counted = plays[plays["counted"]] if not plays.empty else plays
    play_exp = float(counted["expected_month"].sum()) if not counted.empty else 0.0   # primary actions only
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
