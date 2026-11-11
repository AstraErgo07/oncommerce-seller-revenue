"""Tests for Settings, the break-even, the decision log columns, the data schema and the LLM guardrail.
Run: python -m unittest discover -s seller_growth -p "test_*.py"   (from the repository root)"""
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import agent  # noqa: E402
import data_schema  # noqa: E402
from categories import CATEGORIES, ORDER  # noqa: E402
from revenue import HUMAN, Settings, break_even_grid, break_even_stake, route_play, run_all, settings_hash  # noqa: E402

DATA = pd.read_csv(HERE / "example_products.csv")


S12 = sum(0.97 ** t for t in range(1, 13))      # months still trading out of 12 at 3% monthly churn
F12 = 0.70 * S12                                  # x OnCommerce contribution margin


class TestCostBuildUp(unittest.TestCase):
    def test_call_and_message_cost_defaults(self):
        a = Settings()
        self.assertAlmostEqual(a.human_cost, 45000 / 1600 * 1.4)        # £39.375
        self.assertAlmostEqual(round(a.human_cost, 2), 39.38)
        self.assertAlmostEqual(a.auto_cost, 1500 / 2000 + 0.05)         # £0.80
        self.assertAlmostEqual(a.auto_cost, 0.80)

    def test_build_up_inputs_and_overrides(self):
        a = Settings(sse_annual_cost=60000, sse_productive_hours=1500, call_hours=2, journey_build_cost=500,
                     journey_sellers_reached=1000, message_send_cost=0.10)
        self.assertAlmostEqual(a.human_cost, 80.0)
        self.assertAlmostEqual(a.auto_cost, 0.60)
        b = Settings(call_cost_override=120, message_cost_override=2)
        self.assertEqual((b.human_cost, b.auto_cost), (120, 2))

    def test_build_up_text_shows_the_arithmetic(self):
        from workings import cost_buildup_text
        t = cost_buildup_text(Settings())
        self.assertIn("£45,000 fully loaded yearly cost of a Seller Success exec ÷ 1,600 productive hours a year = "
                      "£28.12 an hour, × 1.4 hours per completed call", t)
        self.assertIn("= £39.38", t)
        self.assertIn("£1,500 to build and maintain the journey ÷ 2,000 sellers reached = £0.75, + £0.05 to send = "
                      "£0.80", t)
        self.assertIn("Neither is OnCommerce data.", t)


class TestBreakEven(unittest.TestCase):
    def test_formula_at_defaults(self):
        a = Settings()
        # (call cost - message cost) / (margin x months still trading x (call success - message success))
        self.assertAlmostEqual(break_even_stake(a), (39.375 - 0.80) / (F12 * 0.20))
        self.assertAlmostEqual(round(break_even_stake(a), 2), 27.83)

    def test_cost_change_alone_would_give_16(self):
        # The steering estimate of about £16 is the new costs on the old revenue basis (12 months, no margin, no churn)
        a = Settings(contribution_margin=1.0, monthly_churn=0.0)
        self.assertAlmostEqual(round(break_even_stake(a), 2), 16.07)
        # and the old £120/£2 costs on the old basis give the old £49.17
        old = Settings(contribution_margin=1.0, monthly_churn=0.0, call_cost_override=120, message_cost_override=2)
        self.assertAlmostEqual(round(break_even_stake(old), 2), 49.17)

    def test_formula_other_values_and_no_gap(self):
        a = Settings(call_cost_override=240, message_cost_override=5, p_success_human=0.5, p_success_auto=0.2,
                     value_horizon_months=6, monthly_churn=0.0, contribution_margin=0.5)
        self.assertAlmostEqual(break_even_stake(a), 235 / (0.5 * 6 * 0.3))
        self.assertEqual(break_even_stake(Settings(p_success_human=0.1, p_success_auto=0.2)), float("inf"))

    def test_break_even_matches_routing(self):
        a = Settings()
        be = break_even_stake(a)
        self.assertEqual(route_play(be + 0.01, a)[0], HUMAN)
        self.assertNotEqual(route_play(be - 0.01, a)[0], HUMAN)

    def test_grid(self):
        g = break_even_grid(Settings())
        self.assertEqual(g.shape, (3, 3))
        self.assertEqual(list(g.index), ["£20", "£40", "£80"])
        self.assertAlmostEqual(g.iloc[0, 0], (20 - 0.80) / (F12 * 0.10))
        self.assertAlmostEqual(g.iloc[1, 1], (40 - 0.80) / (F12 * 0.20))
        self.assertAlmostEqual(g.iloc[2, 2], (80 - 0.80) / (F12 * 0.30))


class TestCallVsMessageNetValue(unittest.TestCase):
    def test_net_values_and_winner(self):
        a = Settings()
        for stake in (5, 20, 27, 29, 100, 400):
            route, vh, va, _ = route_play(stake, a)
            self.assertAlmostEqual(vh, stake * F12 * 0.35 - 39.375)
            self.assertAlmostEqual(va, stake * F12 * 0.15 - 0.80)
            self.assertEqual(route == HUMAN, vh > va)
        self.assertNotEqual(route_play(27, a)[0], HUMAN)
        self.assertEqual(route_play(29, a)[0], HUMAN)

    def test_why_route_names_both_values(self):
        from revenue import why_route
        t = why_route(100, Settings())
        self.assertIn("call", t.lower())
        self.assertIn("message", t.lower())


class TestPlainWords(unittest.TestCase):
    def test_explanation_and_play_line(self):
        from workings import call_or_message_text, play_sentence
        from revenue import AUTOMATED
        a = Settings()
        t = call_or_message_text(a)
        self.assertIn("A call costs about £39.38 of staff time and works about 35% of the time.", t)
        self.assertIn("A message costs about £0.80 and works about 15% of the time.", t)
        self.assertIn("A call works 20 percentage points more often but costs £38.58 more", t)
        self.assertIn("£38.58 ÷ (70% × 9.9 × 20%) ≈ £28 of platform revenue a month. Above it: call. Below it: "
                      "send the message.", t)
        self.assertEqual(play_sentence({"stake_month": 200, "route": HUMAN, "expected_month": 70}, a),
                         "£200 a month at stake, above the £28 tipping point, so call. Expected extra revenue £70 a month.")
        self.assertEqual(play_sentence({"stake_month": 20, "route": AUTOMATED, "expected_month": 3}, a),
                         "£20 a month at stake, below the £28 tipping point, so send the message. "
                         "Expected extra revenue £3 a month.")
        for play in run_all(DATA, a)[2].to_dict("records"):   # wording always agrees with the rules' route
            self.assertEqual("so call." in play_sentence(play, a), play["route"] == HUMAN)


class TestSellerValueWorkings(unittest.TestCase):
    """The 'How orders, revenue and LTV are worked out' expander shows the engine's own numbers."""

    def test_matches_engine_on_every_page(self):
        from revenue import run_category
        from workings import _gbp, _n, seller_value_workings
        for k in ORDER:
            for a in (CATEGORIES[k].assumptions(), CATEGORIES[k].assumptions(monthly_churn=0.05, avg_order_value=50,
                                                                           seller_reviews_per_order=0.1)):
                _, s, _ = run_category(DATA, CATEGORIES[k].subcategories, a)
                for r in s.to_dict("records"):
                    steps, total, ltv_v = seller_value_workings(r, a, s.attrs["reviews_per_order"],
                                                                s.attrs["calibration_sellers"])
                    self.assertAlmostEqual(total, r["est_revenue_month"], places=6)
                    self.assertAlmostEqual(ltv_v, r["ltv"], places=4)
                    res = {st["step"].split(" ")[0]: st["result"] for st in steps}
                    self.assertEqual(res["1."], _n(r["lifetime_orders"]) if r["lifetime_orders"] else "0")
                    self.assertEqual(res["2."], _n(r["est_orders_month"], 1))
                    self.assertEqual(res["3."], _gbp(r["est_account_gmv_month"]))
                    self.assertEqual(res["4a."], _gbp(r["subscription_month"]))
                    self.assertEqual(res["4b."], _gbp(r["est_commission_month"]))
                    self.assertEqual(res["4c."], _gbp(r["est_boost_month"]))
                    self.assertEqual(res["5."], _gbp(r["ltv"]))
                    for st in steps:
                        self.assertTrue(st["source"].startswith(("Published", "Observed in sample", "Assumption",
                                                                 "Model estimate")), st)

    def test_plain_labels_and_ratio_text(self):
        from workings import orders_source_label, reviews_per_order_text, seller_value_workings
        self.assertEqual(orders_source_label("SHOWN (seller box, lower bound)"), "Shown on OnBuy")
        self.assertEqual(orders_source_label("EST. seller reviews ÷ 0.066"), "Estimated from reviews")
        t = reviews_per_order_text(0.066, 13, {"n": 12, "median": 0.07, "min": 0.05, "max": 0.0815})
        self.assertIn("About 6.6 seller reviews per 100 orders, i.e. 1 review per about 15 orders.", t)
        self.assertIn("then the median (middle value)", t)
        self.assertIn("Based on 13 sellers", t)
        self.assertIn("12 such sellers: median 1 review per 14 orders, ranging from 1 per 12 to 1 per 20", t)
        a = Settings()
        s = run_all(DATA, a)[1]
        steps, _, _ = seller_value_workings(s.iloc[0].to_dict(), a, s.attrs["reviews_per_order"], 13)
        self.assertIn("At 3% churn a seller stays about 33 months on average (1 ÷ 0.03)", steps[-1]["working"])


class TestSettings(unittest.TestCase):
    def test_hash_is_deterministic_and_sensitive(self):
        self.assertEqual(settings_hash(Settings()), settings_hash(Settings()))
        self.assertEqual(len(settings_hash(Settings())), 12)
        self.assertNotEqual(settings_hash(Settings()), settings_hash(Settings(call_hours=1.5)))
        a = Settings()
        a.season_profiles["heating"][0] = 9.9
        self.assertNotEqual(settings_hash(a), settings_hash(Settings()))

    def test_no_shared_mutable_defaults(self):
        a, b = Settings(), Settings()
        a.boost_levels["Plus"] = 0.5
        a.season_profiles["cooling"][6] = 0.0
        self.assertEqual(b.boost_levels["Plus"], 0.10)
        self.assertEqual(b.season_profiles["cooling"][6], 3.0)

    def test_settings_change_results(self):
        p1, _, _ = run_all(DATA, Settings())
        p2, _, _ = run_all(DATA, Settings(review_rate=0.04))
        self.assertGreater(p1["est_units_month"].sum(), p2["est_units_month"].sum())
        a = Settings()
        a.boost_levels = {k: v * 2 for k, v in a.boost_levels.items()}
        s1 = run_all(DATA, Settings())[1]["est_boost_month"].sum()
        s2 = run_all(DATA, a)[1]["est_boost_month"].sum()
        self.assertAlmostEqual(s2, 2 * s1, places=6)


class TestDataSchema(unittest.TestCase):
    def test_example_data_unchanged_by_prepare(self):
        a = Settings()
        x, y = run_all(DATA, a), run_all(data_schema.prepare(DATA), a)
        self.assertAlmostEqual(x[0]["est_gmv_month"].sum(), y[0]["est_gmv_month"].sum())
        self.assertEqual(len(x[2]), len(y[2]))

    def test_required_columns_and_minimal_file(self):
        with self.assertRaises(ValueError):
            data_schema.prepare(DATA.drop(columns=["price"]))
        minimal = data_schema.prepare(DATA[data_schema.REQUIRED])
        self.assertGreater(run_all(minimal, Settings())[0]["est_units_month"].sum(), 0)

    def test_readme_lists_every_column(self):
        text = (HERE.parent / "data" / "README.md").read_text(encoding="utf-8")
        for col, *_ in data_schema.SCHEMA:
            self.assertIn(f"`{col}`", text)


class TestDecisionLog(unittest.TestCase):
    def test_columns(self):
        src = (HERE.parent / "app_pages" / "shared.py").read_text(encoding="utf-8")
        self.assertIn('LOG_COLS = ["timestamp", "page", "seller", "product", "play", "at_stake", "route", '
                      '"expected_mo", "decision", "reason",\n            "settings_hash"]', src)


class TestLLMGuardrail(unittest.TestCase):
    """The LLM only writes text. Plays, routes and stakes are identical with and without it."""

    def setUp(self):
        self.a = CATEGORIES["heaters"].assumptions()
        self.plays = run_all(DATA, self.a)[2]

    def test_facts_exclude_route_decision_and_estimates(self):
        for play in self.plays.to_dict("records"):
            facts = agent.llm_facts(play, self.a)
            text = json.dumps(facts).lower()
            for word in ("route", "decision", "human (seller success)", "automated journey", "stake", "expected",
                         "est_", "gmv", "revenue", "rank"):
                self.assertNotIn(word, text, f"{word!r} leaked into the LLM facts for {play['play_id']}")
            listing = json.dumps(facts["listing_and_published_facts"])
            if play["stake_month"] >= 1:
                self.assertNotIn(f"{play['stake_month']:.2f}", listing)

    def test_decisions_identical_with_and_without_llm(self):
        sneaky = json.dumps({"subject": "S", "message": "M", "call_brief": "C", "route": "Automated journey",
                             "decision": "reject", "stake_month": 0})
        without = [agent.draft_outreach(p, self.a) for p in self.plays.to_dict("records")]
        before = self.plays.copy()
        with mock.patch.object(agent, "call_llm", return_value=sneaky) as m:
            with_llm = [agent.draft_outreach(p, self.a) for p in self.plays.to_dict("records")]
            self.assertEqual(m.call_count, len(self.plays))
            prompt = m.call_args[0][0].lower()
            self.assertNotIn("human (seller success)", prompt)
            self.assertNotIn("automated journey", prompt)
        after = run_all(DATA, self.a)[2]
        pd.testing.assert_frame_equal(before.drop(columns=["evidence"]), after.drop(columns=["evidence"]))
        for d0, d1 in zip(without, with_llm):
            self.assertEqual(d0["source"], "rules")
            self.assertEqual(d1["source"], "llm")
            self.assertEqual((d1["subject"], d1["message"], d1["call_brief"]), ("S", "M", "C"))
            self.assertNotIn("route", d1)
            self.assertNotIn("decision", d1)
            self.assertEqual(agent.drafted_by(d0), "Drafted by rules")
            self.assertEqual(agent.drafted_by(d1), "Drafted by LLM")

    def test_bad_llm_reply_falls_back_to_rules(self):
        play = self.plays.iloc[0].to_dict()
        with mock.patch.object(agent, "call_llm", return_value="not json"):
            d = agent.draft_outreach(play, self.a)
        self.assertEqual(d["source"], "rules")


class TestCategories(unittest.TestCase):
    def test_every_page_runs(self):
        for k in ORDER:
            cfg = CATEGORIES[k]
            a = replace(cfg.assumptions())
            self.assertTrue(cfg.subcategories)
            self.assertIsInstance(settings_hash(a), str)


if __name__ == "__main__":
    unittest.main()
