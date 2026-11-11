"""
seller_growth/test_revenue.py - hand-checkable tests for the Seller Revenue Agent.  Run:  python -m unittest -v
"""
import unittest
from datetime import date

import pandas as pd

from revenue import (AUTOMATED, BOOST, HUMAN, LEAK_OOS, RETAIN, SEASON_PROFILES, UPGRADE, Settings,
                     best_boost_level, boost_seller_roi, calibrate_reviews_per_order, evaluate_climate, forecast,
                     generate_plays, ltv, route_play, season_index, seller_table, subscription_for, upgrade_case)


def product(**kw):
    base = {"product_id": "p1", "category": "climate control", "subcategory": "fan heaters", "title": "Heater",
            "brand": "B", "price": 20.0, "delivery_fee": 0.0, "seller": "S1", "seller_professional": False,
            "seller_orders_k": None, "seller_review_count": None, "offers_count": 1, "offer_prices": "20.00",
            "offer_sellers": "S1", "offer_seller_reviews": "", "other_sellers": "", "product_review_count": 0,
            "latest_review": "", "first_review": "", "badge": "", "in_stock": True, "max_qty_selectable": 30,
            "delivery_max_days": 3, "flag_out_of_stock": False, "flag_price_anomaly": False,
            "flag_duplicate_page": False, "listing_notes": "", "url": "u"}
    base.update(kw)
    return base


class TestSellerRevenue(unittest.TestCase):

    def test_1_published_prices_and_seasonality(self):
        a = Settings()
        # REAL published: promo prices now, list prices from Jan 2028
        self.assertEqual(subscription_for("Partner", a), 69.0)
        self.assertEqual(subscription_for("Professional", a, date(2028, 1, 1)), 499.0)
        # each seasonal profile averages 1.0 over the year
        for prof in SEASON_PROFILES.values():
            self.assertAlmostEqual(sum(prof) / 12, 1.0)
        # heaters in November = 2.1x an average month; strength 0 switches seasonality off
        self.assertAlmostEqual(season_index("fan heaters", 11, a), 2.1)
        self.assertAlmostEqual(season_index("tower fans", 11, Settings(seasonality_strength=0)), 1.0)
        # 7% Large Appliances only applies to AC/dehumidifiers when the switch is on
        self.assertEqual(Settings().rate_for("dehumidifiers"), 0.15)
        self.assertEqual(Settings(ac_dehum_as_large_appliance=True).rate_for("dehumidifiers"), 0.07)
        self.assertEqual(Settings(ac_dehum_as_large_appliance=True).rate_for("fan heaters"), 0.15)

    def test_2_seller_revenue_and_tier(self):
        a = Settings()   # tenure 36 months, AOV £35, Partner if >= 10k orders, Boost 20% x 30% x 10%
        df = pd.DataFrame([
            product(seller="Big", offer_sellers="Big", seller_orders_k=36.0, seller_review_count=2520),   # 7% ratio
            product(product_id="p2", seller="Pro", offer_sellers="Pro", seller_professional=True,
                    seller_orders_k=3.6, seller_review_count=180),                                         # 5% ratio
        ])
        p = evaluate_climate(df, a)
        s = seller_table(p, a).set_index("seller")
        # calibration: median of 0.07 and 0.05 = 0.06
        self.assertAlmostEqual(calibrate_reviews_per_order(p)[0], 0.06)
        big = s.loc["Big"]
        # 36,000 orders / 36 months = 1,000 orders/month x £35 = £35,000 GMV ; commission 15% = £5,250
        self.assertEqual(big["tier"], "Partner")
        self.assertAlmostEqual(big["est_account_gmv_month"], 35000.0)
        self.assertAlmostEqual(big["est_commission_month"], 5250.0)
        # Boost = 0.20 adoption x 0.30 boosted share x £35,000 x 10% = £210 ; revenue = 69 + 5250 + 210
        self.assertAlmostEqual(big["est_boost_month"], 210.0)
        self.assertAlmostEqual(big["est_revenue_month"], 5529.0)
        # Professional badge is REAL -> £249; LTV = revenue x 70% / 3%
        pro = s.loc["Pro"]
        self.assertEqual(pro["tier"], "Professional")
        self.assertTrue(pro["tier_source"].startswith("SHOWN"))
        self.assertAlmostEqual(pro["subscription_month"], 249.0)
        self.assertAlmostEqual(ltv(100.0, a), 100 * 0.7 / 0.03)

    def test_3_plays_routes_and_boost_roi(self):
        a = Settings()
        # contribution per £1/month = 70% margin x 9.899 months still trading (12 months, 3% churn) = 6.929
        f = 0.70 * sum(0.97 ** t for t in range(1, 13))
        # route: stake £100/mo -> call 100 x 6.929 x 0.35 - 39.375 = 203.15 ; message 100 x 6.929 x 0.15 - 0.80
        route, vh, va, exp = route_play(100.0, a)
        self.assertEqual(route, HUMAN)
        self.assertAlmostEqual(vh, 100 * f * 0.35 - 39.375)
        self.assertAlmostEqual(round(vh, 2), 203.15)
        self.assertAlmostEqual(va, 100 * f * 0.15 - 0.80)
        self.assertAlmostEqual(exp, 35.0)
        # stake £20/mo -> call 48.50 - 39.38 = 9.13 ; message 20.79 - 0.80 = 19.99 -> automated
        self.assertEqual(route_play(20.0, a)[0], AUTOMATED)
        # Boost ROI for the seller: 0.5 x (0.35-0.15) / (1.5 x 0.05) = 1.33 at Light; 0.67 at Plus -> Light
        self.assertAlmostEqual(boost_seller_roi(0.05, a, 0.15), 0.1 / 0.075)
        self.assertEqual(best_boost_level(a, 0.15), "Light")
        # upgrade: Standard seller with £40,000 GMV: 2% lift = £800 extra sales x (35% margin - 15% commission)
        # = £160 extra profit - £44 extra fee = £116 better off (and £56 at the £104 list-price step) -> upgrade
        up = upgrade_case({"tier": "Standard", "est_account_gmv_month": 40000.0, "tier_source": "SHOWN",
                           "orders_source": "SHOWN"}, a)
        self.assertEqual(up["next_tier"], "Partner")
        self.assertAlmostEqual(up["fee_delta"], 44.0)
        self.assertAlmostEqual(up["seller_net"], 116.0)
        self.assertAlmostEqual(up["seller_net_list"], 56.0)
        self.assertFalse(up["needs_validation"])
        self.assertAlmostEqual(up["stake"], 44.0 + 40000 * 0.02 * 0.15)
        # £10,000 GMV: £200 x 20% = £40 < £44 extra fee -> the seller is not better off, no upgrade
        self.assertIsNone(upgrade_case({"tier": "Standard", "est_account_gmv_month": 10000.0}, a))
        # Professional seller with small GMV -> retention play; out-of-stock heater -> leakage play
        df = pd.DataFrame([
            product(seller="Pro", offer_sellers="Pro", seller_professional=True, seller_orders_k=0.534),
            product(product_id="p2", seller="Oos", offer_sellers="", offer_prices="", offers_count=0,
                    in_stock=False, flag_out_of_stock=True, badge="Bestseller", product_review_count=0)])
        p = evaluate_climate(df, a)
        plays = generate_plays(p, seller_table(p, a), a)
        # 534 orders / 36 x £35 = £519 GMV ; £249 / £519 = 48% > 5% -> retention risk
        self.assertIn(RETAIN, set(plays.loc[plays["seller"] == "Pro", "play_type"]))
        oos = plays[plays["play_type"] == LEAK_OOS].iloc[0]
        # lost units = Bestseller floor 10/month in season; commission 15% x £20 = £3 -> £30/month
        self.assertAlmostEqual(oos["stake_month"], 30.0)
        self.assertNotIn(UPGRADE, set(plays["play_type"]))
        # in-season, good listing, but about 0.5 units a month: Boost would not repay even a £0.80 message
        self.assertNotIn(BOOST, set(plays["play_type"]))

    def test_4_forecast(self):
        a = Settings(monthly_churn=0.10, monthly_upgrade_rate=0.0)
        s = pd.DataFrame([{"tier": "Standard", "est_commission_month": 75.0, "est_boost_month": 0.0}])
        p = evaluate_climate(pd.DataFrame([product()]), a)
        f = forecast(s, pd.DataFrame(), p, a, months=14)
        # month 1: (25 + 75) x 0.9 = 90 ; month 2: x 0.81
        self.assertAlmostEqual(f.loc[0, "base"], 90.0)
        self.assertAlmostEqual(f.loc[1, "base"], 81.0)
        # no plays -> with_plays = base; Jan 2028 (month 14) is flagged as list-price period
        self.assertTrue((f["with_plays"] == f["base"]).all())
        self.assertTrue(f.loc[13, "promo_ended"])

    def test_5_category_configs_and_units(self):
        from pathlib import Path
        import categories as C
        from revenue import run_category, units_summary
        df = pd.read_csv(Path(__file__).parent / "example_products.csv")
        self.assertEqual(C.ORDER, ["heaters", "fans", "dehumidifiers", "portable_ac", "air_purifiers"])
        seen = set()
        for key in C.ORDER:
            cfg = C.get(key)
            C.check_config(cfg)                     # every default is a real Settings field
            a = cfg.assumptions()
            self.assertEqual(a.season_profile, cfg.season_profile)
            self.assertIn(cfg.season_profile, SEASON_PROFILES)
            p, s, pl = run_category(df, cfg.subcategories, a)
            # only this category's products, and every subcategory belongs to exactly one page
            self.assertGreater(len(p), 0, key)
            self.assertTrue(set(p["subcategory"]) <= set(cfg.subcategories), key)
            self.assertFalse(seen & set(cfg.subcategories))
            seen |= set(cfg.subcategories)
            # units columns present at product and seller level, and they add up
            for col in ("est_units_month", "est_units_avg_month", "est_gmv_month"):
                self.assertIn(col, p.columns)
            self.assertIn("climate_units_month", s.columns)
            u = units_summary(p)
            self.assertAlmostEqual(u["est_units_month"], s["climate_units_month"].sum(), places=6)
            # GMV = units x average selling price, at product, seller and category level, and the levels agree
            self.assertAlmostEqual(u["est_gmv_month"], (p["est_units_month"] * p["avg_price"]).sum(), places=6)
            self.assertAlmostEqual(u["est_gmv_month"], s["climate_gmv_month"].sum(), places=6)
            if u["est_units_month"]:
                self.assertAlmostEqual(u["avg_price"], u["est_gmv_month"] / u["est_units_month"], places=9)
            sold = s[s["climate_units_month"] > 0]
            self.assertTrue(((sold["climate_avg_price"] * sold["climate_units_month"] - sold["climate_gmv_month"]).abs()
                             < 1e-6).all(), key)
        self.assertEqual(seen, set(df["subcategory"]))   # no product left without a page
        # per-category defaults differ where the config says so
        self.assertEqual(C.get("heaters").assumptions().boost_adoption, 0.25)
        self.assertEqual(C.get("fans").assumptions().boost_adoption, 0.10)
        # page-level season profile overrides the subcategory default
        self.assertAlmostEqual(season_index("fan heaters", 11, Settings(season_profile="all-year")), 1.0)

    def test_6_units_formula(self):
        a = Settings()
        # 12 reviews, oldest 24 months ago (every review listed), newest recent, Nov heater index 2.1:
        # 12 / 0.02 / 24 = 25 units in an average month x 2.1 = 52.5 units this month
        first = date(2024, 11, 11).isoformat()
        p = evaluate_climate(pd.DataFrame([product(product_review_count=12, first_review=first,
                                                   latest_review="2026-10-01")]), a).iloc[0]
        self.assertAlmostEqual(p["est_units_avg_month"], 12 / 0.02 / p["review_window_months"])
        self.assertAlmostEqual(p["est_units_month"], p["est_units_avg_month"] * 2.1)
        self.assertAlmostEqual(p["est_gmv_month"], p["est_units_month"] * 20.0)


    def test_7_example_data_is_synthetic_and_reproducible(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        here = Path(__file__).parent
        df = pd.read_csv(here / "example_products.csv")
        self.assertTrue(df["title"].str.startswith("Example ").all())
        self.assertTrue(df["seller"].str.startswith("Example Seller ").all())
        self.assertTrue(df["url"].isna().all() or (df["url"].fillna("") == "").all())
        self.assertFalse(df.astype(str).apply(lambda c: c.str.contains("onbuy.com", case=False)).any().any())
        # the generator is seeded: running it again gives identical rows
        raw = here.parent / "data" / "example" / "onbuy_example_products_raw.jsonl"
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.jsonl"
            subprocess.run([sys.executable, str(here.parent / "tools" / "gen_example_data.py"), "--out", str(out)],
                           check=True, capture_output=True)
            self.assertEqual(out.read_text(), raw.read_text())


    def test_8_plain_workings_match_the_engine(self):
        from pathlib import Path
        import categories as C
        from revenue import run_category
        from workings import product_workings, routing_workings, seller_workings
        df = pd.read_csv(Path(__file__).parent / "example_products.csv")
        for key in C.ORDER:
            cfg = C.get(key)
            a = cfg.assumptions()
            p, s, pl = run_category(df, cfg.subcategories, a)
            for r in p.to_dict("records"):
                _, units, gmv = product_workings(r, a)
                self.assertAlmostEqual(units, r["est_units_month"], places=9)
                self.assertAlmostEqual(gmv, r["est_gmv_month"], places=6)
                self.assertAlmostEqual(gmv, units * r["avg_price"], places=6)
            for r in s.to_dict("records"):
                _, total = seller_workings(r, a, s.attrs["reviews_per_order"])
                self.assertAlmostEqual(total, r["est_revenue_month"], places=6)
            if len(pl):
                self.assertEqual(routing_workings(pl.iloc[0].to_dict(), a)[3]["result"], pl.iloc[0]["route"])


    def test_9_overview_doc_is_up_to_date(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.md"
            subprocess.run([sys.executable, str(root / "tools" / "build_overview.py"), "--out", str(out)],
                           check=True, capture_output=True)
            self.assertEqual(out.read_text(), (root / "docs" / "OVERVIEW.md").read_text(),
                             "docs/OVERVIEW.md is stale: run python tools/build_overview.py")
            self.assertNotIn("\u2014", out.read_text())
            self.assertNotIn("\u2013", out.read_text())


if __name__ == "__main__":
    unittest.main()
