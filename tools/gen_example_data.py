"""
tools/gen_example_data.py - seeded generator for the EXAMPLE data used by the Seller Revenue pages.

    python tools/gen_example_data.py            # writes data/example/onbuy_example_products_raw.jsonl
    python seller_growth/build_data.py          # turns it into seller_growth/example_products.csv

Every product and seller is synthetic: titles are "Example ...", brands are "Brand 01", sellers are
"Example Seller A", and there are no URLs or EANs. The distributions per category (price, delivery, review
counts and dates, OnBuy badge mix, offers per product and their price spread, stock-outs, anomalies,
duplicates, overseas dispatch, seller order and review counts, Professional badge rate) are taken from
seller_growth/calibration_stats.json, which holds aggregates only. Shares are matched exactly by count
(largest remainder), continuous values are drawn from log-normal fits, clipped to the observed range.
"""
from __future__ import annotations

import json
import math
import random
import string
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from seller_growth.categories import CATEGORIES, ORDER  # noqa: E402

SEED = 2026
N_PER_CATEGORY = 20
SNAPSHOT = date(2026, 11, 11)
STATS = ROOT / "seller_growth" / "calibration_stats.json"
OUT = ROOT / "data" / "example" / "onbuy_example_products_raw.jsonl"
METHOD = f"synthetic example (tools/gen_example_data.py, seed {SEED})"


def counts(mix: dict, n: int) -> dict:
    """Largest-remainder allocation of n items to the shares in mix."""
    raw = {k: v * n for k, v in mix.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: n - sum(out.values())]:
        out[k] += 1
    return out


def pick_flags(rng: random.Random, share: float, n: int) -> set:
    return set(rng.sample(range(n), round(share * n)))


def draw(rng: random.Random, fit: dict, lo_mult=0.8, hi_mult=1.2) -> float:
    if not fit or not fit.get("n"):
        return 0.0
    x = math.exp(rng.gauss(fit["log_mean"], fit["log_sd"]))
    return min(max(x, fit["min"] * lo_mult), fit["max"] * hi_mult)


def seller_name(i: int) -> str:
    L = string.ascii_uppercase
    return "Example Seller " + (L[i] if i < 26 else L[i // 26 - 1] + L[i % 26])


def make_sellers(rng, st, n):
    rpo = st.get("reviews_per_order_median") or 0.07
    shown = pick_flags(rng, st["seller_orders_shown_share"], n)
    k = round(st["professional_share"] * n)
    pro = set(rng.sample(range(min(n, max(2 * k, 4))), k))   # among the busier sellers, so they appear on pages
    out = []
    for i in range(n):
        orders_k = round(draw(rng, st["seller_orders_k"]) * 2) / 2 if i in shown and st["seller_orders_k"].get("n") else None
        if orders_k:
            reviews = int(orders_k * 1000 * rpo * rng.uniform(0.7, 1.3))
        else:
            reviews = int(draw(rng, st["seller_reviews"])) if st["seller_reviews"].get("n") else int(rng.uniform(20, 400))
        out.append({"name": seller_name(i), "orders": f"{orders_k:g}k+" if orders_k else None,
                    "reviews": max(reviews, 1), "pro": i in pro})
    return out


def gen_category(rng: random.Random, key: str, st: dict) -> list[dict]:
    cfg = CATEGORIES[key]
    n = N_PER_CATEGORY
    ratio = st["n_sellers"] / max(st["n_products"], 1)
    sellers = make_sellers(rng, st, max(4, round(n * min(ratio, 2.0) * 0.8)))
    weights = [1 / (i + 1) ** 0.8 for i in range(len(sellers))]          # a few sellers carry several products
    subs = [s for s, c in counts(st["subcategory_mix"], n).items() for _ in range(c)]
    badges = [b for b, c in counts(st["badge_mix"], n).items() for _ in range(c)]
    offers_n = [int(k) for k, c in counts(st["offers_count_mix"], n).items() for _ in range(c)]
    rng.shuffle(subs), rng.shuffle(badges), rng.shuffle(offers_n)
    oos = {i for i, k in enumerate(offers_n) if k == 0}
    extra_oos = round(st["out_of_stock_share"] * n) - len(oos)
    if extra_oos > 0:
        oos |= set(rng.sample([i for i in range(n) if i not in oos], extra_oos))
    zero_rev = pick_flags(rng, st["reviews_zero_share"], n)
    flags = {name: pick_flags(rng, st[f"{name}_share"], n) for name in
             ("price_anomaly", "duplicate_page", "overseas_dispatch", "thin_content", "no_brand",
              "former_seller_reviews", "paid_delivery")}
    rows = []
    for i in range(n):
        price = round(draw(rng, st["price"]), 2)
        notes = []
        if i in flags["price_anomaly"]:
            price = round(price * rng.uniform(5, 10), 2)
            notes.append("price anomaly: price far above comparable listings")
        if i in flags["duplicate_page"]:
            notes.append("duplicate page of another example listing")
        if i in flags["overseas_dispatch"]:
            notes.append("overseas dispatch")
        if i in flags["thin_content"]:
            notes.append("templated description")
        if i in flags["former_seller_reviews"]:
            notes.append("recent reviews from a seller no longer listed")
        k_offers = 0 if i in oos else max(offers_n[i], 1)
        chosen = rng.choices(range(len(sellers)), weights=weights, k=1)
        pool = [j for j in range(len(sellers)) if j != chosen[0]]
        chosen += rng.sample(pool, min(k_offers - 1, len(pool))) if k_offers > 1 else []
        med, mx = st["other_offer_price_ratio"]["median"], st["other_offer_price_ratio"]["max"]
        prices = [price] + sorted(round(price * min(rng.uniform(1.0, 2 * med - 1 if med > 1 else 1.05), mx), 2)
                                  for _ in chosen[1:])
        buy = sellers[chosen[0]]
        n_rev = 0 if i in zero_rev else max(1, round(draw(rng, st["reviews_nonzero"], 1.0, 1.3)))
        latest = first = None
        if n_rev:
            age = (st["latest_review_age_months_median"] or 6) * math.exp(rng.gauss(0, 0.7))
            latest = SNAPSHOT - timedelta(days=int(age * 30.44))
            if rng.random() < st["first_review_known_share"]:
                first = latest - timedelta(days=int(rng.uniform(3, 30) * 30.44)) if n_rev > 1 else latest
        stars = [min(5, max(1, round(rng.gauss(4.6, 0.7)))) for _ in range(n_rev)]
        fee = st["paid_delivery_fee_median"] if i in flags["paid_delivery"] else 0.0
        days = max(1, round(st["delivery_max_days_median"] * rng.uniform(0.6, 1.6) * (2 if i in flags["overseas_dispatch"] else 1)))
        rows.append({
            "marketplace": "OnBuy (example)", "category": "climate control",
            "pid": f"EX-{key[:3].upper()}-{i + 1:02d}", "subcategory": subs[i],
            "title": f"Example {subs[i].rstrip('s')} {i + 1:02d}",
            "brand": "" if i in flags["no_brand"] else f"Brand {rng.randint(1, 12):02d}",
            "price": price, "rrp": None, "delivery_fee": fee,
            "seller": buy["name"], "seller_professional": buy["pro"], "seller_orders": buy["orders"],
            "seller_review_count": buy["reviews"],
            "offers": [] if i in oos else [[sellers[j]["name"], p] for j, p in zip(chosen, prices)],
            "offer_seller_reviews": [] if i in oos else [sellers[j]["reviews"] for j in chosen],
            "offer_professional": [] if i in oos else [sellers[j]["pro"] for j in chosen],
            "product_review_count": n_rev, "rating_dist": {str(s): stars.count(s) for s in range(1, 6)},
            "latest_review": latest.isoformat() if latest else None,
            "first_review": first.isoformat() if first else None,
            "rank": "" if badges[i] == "none" else badges[i], "max_qty": rng.choice([1, 2, 5, 10, 30]),
            "delivery_latest": (SNAPSHOT + timedelta(days=days)).isoformat(),
            "in_stock": i not in oos, "notes": "; ".join(notes), "url": "",
            "scrape_date": SNAPSHOT.isoformat(), "method": METHOD,
        })
    return rows


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    out = ap.parse_args().out
    stats = json.loads(STATS.read_text())["categories"]
    rng = random.Random(SEED)
    rows = [r for k in ORDER for r in gen_category(rng, k, stats[k])]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {out}: {len(rows)} example products ({N_PER_CATEGORY} per category, seed {SEED})")

if __name__ == "__main__":
    main()
