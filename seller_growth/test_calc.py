"""
seller_growth/test_calc.py - hand-checkable tests.  Run:  python -m unittest -v
"""
import unittest

import pandas as pd

from calc import (Assumptions, commission_per_unit, est_monthly_units, gap_to_lowest,
                  listing_quality, price_dispersion, evaluate_products, generate_actions,
                  RECRUIT_SELLER, PRICE_NUDGE)


class TestSellerGrowthCalc(unittest.TestCase):

    def test_1_units_from_reviews_and_badges(self):
        a = Assumptions()   # 2% review rate (50 orders per review), 24-month window
        # 48 reviews -> 48 / 0.02 / 24 = 100 units/month (recent review, no staleness)
        self.assertAlmostEqual(est_monthly_units(48, 1.0, "", a), 100.0)
        # same reviews but newest is 18 months old (> 12) -> x 0.5 = 50
        self.assertAlmostEqual(est_monthly_units(48, 18.0, "", a), 50.0)
        # no reviews: Bestseller badge floor = 10, In demand = 3, nothing = 0.5
        self.assertAlmostEqual(est_monthly_units(0, None, "Bestseller", a), 10.0)
        self.assertAlmostEqual(est_monthly_units(0, None, "In demand", a), 3.0)
        self.assertAlmostEqual(est_monthly_units(0, None, "", a), 0.5)

    def test_2_commission_and_price_position(self):
        # £20 item + £0 delivery at 15% = £3.00 ; a £1.00 item hits the £0.25 minimum
        self.assertAlmostEqual(commission_per_unit(20.0, 0.15, 0.25), 3.00)
        self.assertAlmostEqual(commission_per_unit(1.00, 0.15, 0.25), 0.25)
        # offers £10, £11, £15 -> dispersion (15-10)/10 = 0.5 ; £11 is 10% above lowest
        self.assertAlmostEqual(price_dispersion([10, 11, 15]), 0.5)
        self.assertAlmostEqual(gap_to_lowest(11, [10, 11, 15]), 0.10)
        self.assertAlmostEqual(price_dispersion([10]), 0.0)

    def test_3_quality_score_and_actions(self):
        a = Assumptions()
        row = {"title": "X", "flag_no_brand": True, "product_review_count": 0, "delivery_fee": 3.0,
               "delivery_max_days": 20, "max_qty_selectable": 30}
        # 100 - 15 (no brand) - 10 (no reviews) - 10 (paid delivery) - 15 (slow) = 50
        score, issues = listing_quality(row, a)
        self.assertEqual(score, 50)
        self.assertEqual(len(issues), 4)
        # One single-seller bestseller with 48 reviews: 100 units x £10 x 15% = £150/month commission
        # -> "Recruit a second seller", priority = £150 x 20% uplift = £30/month.
        # Plus a 2-offer product where the 2nd seller is 25% above -> price nudge.
        df = pd.DataFrame([
            {"product_id": "p1", "category": "kitchen", "title": "Hero", "brand": "B", "price": 10.0,
             "delivery_fee": 0.0, "seller": "S1", "offers_count": 1, "offer_prices": "10.00",
             "other_sellers": "", "product_review_count": 48, "latest_review": "2026-10-11",
             "badge": "Bestseller", "max_qty_selectable": 30, "delivery_max_days": 3},
            {"product_id": "p2", "category": "kitchen", "title": "Two offers", "brand": "B", "price": 8.0,
             "delivery_fee": 0.0, "seller": "S2", "offers_count": 2, "offer_prices": "8.00;10.00",
             "other_sellers": "S3", "product_review_count": 0, "latest_review": "",
             "badge": "", "max_qty_selectable": 30, "delivery_max_days": 3}])
        p = evaluate_products(df, a)
        self.assertAlmostEqual(p.loc[0, "est_commission_month"], 150.0)
        acts = generate_actions(p, a)
        rec = acts[acts["action_type"] == RECRUIT_SELLER].iloc[0]
        self.assertAlmostEqual(rec["priority_gbp_month"], 30.0)
        nudge = acts[acts["action_type"] == PRICE_NUDGE].iloc[0]
        self.assertEqual(nudge["seller"], "S3")   # £10 is 25% above £8


if __name__ == "__main__":
    unittest.main()
