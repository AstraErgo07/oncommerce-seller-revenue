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


class TestBreakEven(unittest.TestCase):
    def test_formula_at_defaults(self):
        a = Settings()
        # (call cost - message cost) / (12 x (call success - message success)) = (120 - 2) / (12 x 0.20)
        self.assertAlmostEqual(break_even_stake(a), 118 / 2.4)
        self.assertAlmostEqual(round(break_even_stake(a), 2), 49.17)

    def test_formula_other_values_and_no_gap(self):
        a = Settings(human_cost=240, auto_cost=5, p_success_human=0.5, p_success_auto=0.2, value_horizon_months=6)
        self.assertAlmostEqual(break_even_stake(a), 235 / (6 * 0.3))
        self.assertEqual(break_even_stake(Settings(p_success_human=0.1, p_success_auto=0.2)), float("inf"))

    def test_break_even_matches_routing(self):
        a = Settings()
        be = break_even_stake(a)
        self.assertEqual(route_play(be + 0.01, a)[0], HUMAN)
        self.assertNotEqual(route_play(be - 0.01, a)[0], HUMAN)

    def test_grid(self):
        g = break_even_grid(Settings())
        self.assertEqual(g.shape, (3, 3))
        self.assertAlmostEqual(g.iloc[0, 0], (60 - 2) / (12 * 0.10))
        self.assertAlmostEqual(g.iloc[1, 1], (120 - 2) / (12 * 0.20))
        self.assertAlmostEqual(g.iloc[2, 2], (240 - 2) / (12 * 0.30))


class TestPlainWords(unittest.TestCase):
    def test_explanation_and_play_line(self):
        from workings import call_or_message_text, play_sentence
        from revenue import AUTOMATED
        a = Settings()
        t = call_or_message_text(a)
        self.assertIn("A call costs about £120 of staff time and works about 35% of the time.", t)
        self.assertIn("A call works 20 percentage points more often but costs £118 more", t)
        self.assertIn("£118 ÷ (12 × 20%) ≈ £49 a month. Above it: call. Below it: send the message.", t)
        self.assertEqual(play_sentence({"stake_month": 200, "route": HUMAN, "expected_month": 70}, a),
                         "£200 a month at stake, above the £49 tipping point, so call. Expected gain £70 a month.")
        self.assertEqual(play_sentence({"stake_month": 20, "route": AUTOMATED, "expected_month": 3}, a),
                         "£20 a month at stake, below the £49 tipping point, so send the message. "
                         "Expected gain £3 a month.")
        for play in run_all(DATA, a)[2].to_dict("records"):   # wording always agrees with the rules' route
            self.assertEqual("so call." in play_sentence(play, a), play["route"] == HUMAN)


class TestSettings(unittest.TestCase):
    def test_hash_is_deterministic_and_sensitive(self):
        self.assertEqual(settings_hash(Settings()), settings_hash(Settings()))
        self.assertEqual(len(settings_hash(Settings())), 12)
        self.assertNotEqual(settings_hash(Settings()), settings_hash(Settings(human_cost=121)))
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
