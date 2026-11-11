"""
seller_growth/test_decision_logic.py - next-best-action rules: upgrade benefit, Boost eligibility, fix first,
one counted action per seller, zero-sales and missing data, and approval logging.  Run:  python -m unittest -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from categories import CATEGORIES, ORDER  # noqa: E402
from revenue import (BOOST, FIX_TYPES, LEAK_OOS, UPGRADE, Settings, assign_actions, boost_eligibility,  # noqa: E402
                     evaluate_climate, generate_plays, overview_by_category, portfolio_summary, run_category,
                     seller_table, top_play_per_seller, upgrade_case)
from test_revenue import product  # noqa: E402

DATA = pd.read_csv(HERE / "example_products.csv")


def _boost_row(**kw):
    r = {"flag_out_of_stock": False, "flag_price_anomaly": False, "quality_score": 90, "flag_duplicate_page": False,
         "price": 20.0, "lowest_offer": 20.0, "badge": "", "season_index_now": 2.0, "est_units_month": 5.0,
         "commission_rate": 0.15}
    r.update(kw)
    return r


class TestUpgradeEligibility(unittest.TestCase):
    def test_seller_must_be_better_off_after_the_fee(self):
        a = Settings()
        self.assertIsNone(upgrade_case({"tier": "Standard", "est_account_gmv_month": 10000.0}, a))
        self.assertIsNotNone(upgrade_case({"tier": "Standard", "est_account_gmv_month": 40000.0}, a))
        self.assertIsNone(upgrade_case({"tier": "Professional", "est_account_gmv_month": 1e6}, a))

    def test_commission_on_extra_sales_is_deducted(self):
        a = Settings(partner_sales_uplift=0.02, seller_margin=0.35, commission_rate=0.15)
        up = upgrade_case({"tier": "Standard", "est_account_gmv_month": 40000.0}, a)
        self.assertAlmostEqual(up["seller_gain"], 800 * 0.20)       # not 800 x 0.35

    def test_needs_validation_when_estimated_or_loses_at_list_price(self):
        a = Settings()
        up = upgrade_case({"tier": "Standard", "est_account_gmv_month": 20000.0, "tier_source": "EST",
                           "orders_source": "EST"}, a)
        self.assertTrue(up["needs_validation"])
        reasons = " ".join(up["validation_reasons"])
        self.assertIn("tier is estimated", reasons)
        self.assertIn("list price", reasons)

    def test_uplift_is_editable_and_conservative_by_default(self):
        self.assertLessEqual(Settings().partner_sales_uplift, 0.02)
        self.assertLessEqual(Settings().pro_sales_uplift, 0.02)
        self.assertIsNone(upgrade_case({"tier": "Standard", "est_account_gmv_month": 40000.0},
                                       Settings(partner_sales_uplift=0.0)))


class TestBoostEligibility(unittest.TestCase):
    def test_eligible_listing(self):
        self.assertEqual(boost_eligibility(_boost_row(), Settings()), (True, ""))

    def test_exclusions(self):
        a = Settings()
        cases = {"out of stock": dict(flag_out_of_stock=True), "price looks wrong": dict(flag_price_anomaly=True),
                 "listing quality problems to fix first": dict(quality_score=10),
                 "not price competitive": dict(price=30.0, lowest_offer=20.0),
                 "already a Bestseller": dict(badge="Bestseller"), "out of season": dict(season_index_now=0.5),
                 "no sales to build on": dict(est_units_month=0.0)}
        for reason, kw in cases.items():
            ok, why = boost_eligibility(_boost_row(**kw), a)
            self.assertFalse(ok, reason)
            self.assertEqual(why, reason)
        ok, _ = boost_eligibility(_boost_row(flag_duplicate_page=True), a)
        self.assertFalse(ok)

    def test_poor_seller_economics(self):
        a = Settings(seller_margin=0.16)            # Boost cannot pay back for the seller at any level
        ok, why = boost_eligibility(_boost_row(), a)
        self.assertFalse(ok)
        self.assertIn("pay back", why)


class TestBoostPlays(unittest.TestCase):
    def test_boost_plays_are_eligible_and_pay_back(self):
        from revenue import contribution_factor
        n = 0
        for k in ORDER:
            a = CATEGORIES[k].assumptions()
            p, _, pl = run_category(DATA, CATEGORIES[k].subcategories, a)
            idx = p.set_index("product_id")
            for b in pl[pl["play_type"] == BOOST].to_dict("records"):
                n += 1
                self.assertTrue(boost_eligibility(idx.loc[b["product_id"]].to_dict() | {"product_id": b["product_id"]},
                                                  a)[0])
                self.assertGreater(b["stake_month"] * contribution_factor(a) * a.p_success_auto, a.auto_cost)
        self.assertGreater(n, 0)


class TestFixFirstAndCounting(unittest.TestCase):
    def setUp(self):
        self.a = Settings()

    def test_one_primary_per_seller_and_fix_first(self):
        for k in ORDER:
            a = CATEGORIES[k].assumptions()
            _, s, pl = run_category(DATA, CATEGORIES[k].subcategories, a)
            if pl.empty:
                continue
            prim = pl[pl["role"] == "Primary"]
            self.assertEqual(len(prim), prim["seller"].nunique())
            self.assertEqual(set(prim["seller"]), set(pl["seller"]))
            self.assertTrue((pl["counted"] == (pl["role"] == "Primary")).all())
            self.assertEqual(pl["play_id"].nunique(), len(pl))
            has_fix = set(pl.loc[pl["play_type"].isin(FIX_TYPES), "seller"])
            growth = pl[pl["play_type"].isin([BOOST, UPGRADE]) & pl["seller"].isin(has_fix)]
            self.assertTrue((growth["status"] == "Deferred: fix first").all())
            self.assertFalse((prim["status"] == "Deferred: fix first").any())

    def test_no_duplicate_recommendations(self):
        for k in ORDER:
            _, _, pl = run_category(DATA, CATEGORIES[k].subcategories, CATEGORIES[k].assumptions())
            if pl.empty:
                continue
            dup = pl.duplicated(subset=["seller", "play_type", "product_id"], keep=False)
            self.assertFalse(dup.any(), pl[dup])

    def test_summary_counts_each_seller_once(self):
        _, s, pl = run_category(DATA, CATEGORIES["dehumidifiers"].subcategories, self.a)
        sm = portfolio_summary(s, pl, self.a)
        prim = top_play_per_seller(pl)
        act = prim[(prim["net_contribution"] > 0) & (prim["status"] == "Recommended")]
        self.assertEqual(sm["actionable"], len(act))
        self.assertEqual(sm["primary_needs_validation"], int((prim["status"] == "Needs validation").sum()))
        self.assertAlmostEqual(sm["net_contribution"], act["net_contribution"].sum())
        self.assertLess(sm["net_contribution"], pl.loc[pl["net_contribution"] > 0, "net_contribution"].sum())
        self.assertAlmostEqual(sm["revenue_month"], s["est_revenue_month"].sum())
        self.assertEqual(sm["human"] + sm["automated"], sm["actionable"])

    def test_needs_validation_never_beats_a_firm_action(self):
        for k in ORDER:
            _, _, pl = run_category(DATA, CATEGORIES[k].subcategories, CATEGORIES[k].assumptions())
            for seller, g in pl.groupby("seller"):
                prim = g[g["role"] == "Primary"].iloc[0]
                firm = g[g["status"] == "Recommended"]
                if len(firm):
                    self.assertEqual(prim["status"], "Recommended", seller)

    def test_overview_sums_categories_not_a_merged_run(self):
        cats = [(k, CATEGORIES[k].label, CATEGORIES[k].subcategories, CATEGORIES[k].assumptions()) for k in ORDER]
        rows, total, top = overview_by_category(DATA, cats)
        self.assertEqual(total["sellers"], sum(r["Sellers"] for r in rows))
        self.assertEqual(total["actionable"], sum(r["Actionable sellers"] for r in rows))
        self.assertLessEqual(len(top), 5)
        self.assertTrue(top["Seller (category)"].str.contains(r"\(").all())

    def test_retention_does_not_claim_the_whole_account(self):
        for k in ORDER:
            _, s, pl = run_category(DATA, CATEGORIES[k].subcategories, CATEGORIES[k].assumptions())
            for p in pl[pl["play_type"].str.startswith("Retention")].to_dict("records"):
                rev = s.loc[s["seller"] == p["seller"], "est_revenue_month"].iloc[0]
                self.assertLessEqual(p["stake_month"], rev + 1e-9)

    def test_next_review_rule(self):
        _, _, pl = run_category(DATA, CATEGORIES["heaters"].subcategories, CATEGORIES["heaters"].assumptions())
        for p in pl.to_dict("records"):
            want = {LEAK_OOS: 14, BOOST: 30, UPGRADE: 60}.get(p["play_type"])
            if want:
                self.assertEqual(p["next_review_days"], want)


class TestZeroSalesAndMissingData(unittest.TestCase):
    def test_zero_sales_seller_and_missing_fields(self):
        a = Settings()
        df = pd.DataFrame([
            product(seller="Zero", offer_sellers="Zero", product_review_count=0, seller_orders_k=None,
                    seller_review_count=None),
            product(product_id="p2", seller="Gap", offer_sellers="Gap", price=15.0, delivery_fee=None,
                    latest_review="", first_review="", badge=None, seller_orders_k=None, seller_review_count=0)])
        p = evaluate_climate(df, a)
        s = seller_table(p, a)
        pl = generate_plays(p, s, a)
        self.assertFalse(s[["est_revenue_month", "ltv"]].isna().any().any())
        self.assertTrue((s["est_revenue_month"] >= 0).all())
        if not pl.empty:
            self.assertFalse(pl[["stake_month", "net_contribution", "expected_month"]].isna().any().any())
            self.assertNotIn(UPGRADE, set(pl["play_type"]))
        self.assertIsNone(upgrade_case({"tier": "Standard", "est_account_gmv_month": 0.0}, a))
        self.assertIsNone(upgrade_case({"tier": "Standard", "est_account_gmv_month": None}, a))

    def test_assign_actions_on_empty(self):
        self.assertTrue(assign_actions(pd.DataFrame()).empty)


class TestApprovalLogging(unittest.TestCase):
    def test_approve_and_override_are_logged(self):
        import app_pages.shared as sh
        fake_state = {}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sh, "LOG_FILE", Path(d) / "log.csv"), \
                mock.patch.object(sh.st, "session_state", fake_state):
            _, _, pl = run_category(DATA, CATEGORIES["heaters"].subcategories, CATEGORIES["heaters"].assumptions())
            play = pl.iloc[0].to_dict()
            r1 = sh.log_decision("Heaters", play, "approve", "", Settings())
            r2 = sh.log_decision("Heaters", play, "override: Lower priority", "Seller already contacted", Settings())
            saved = pd.read_csv(Path(d) / "log.csv")
        self.assertEqual(list(saved.columns), sh.LOG_COLS)
        self.assertEqual(saved["decision"].tolist(), ["approve", "override: Lower priority"])
        self.assertEqual(saved["reason"].fillna("").tolist(), ["", "Seller already contacted"])
        self.assertEqual(len(fake_state["decision_log"]), 2)
        self.assertEqual(r1["settings_hash"], r2["settings_hash"])
        self.assertEqual(r1["seller"], play["seller"])


if __name__ == "__main__":
    unittest.main()
