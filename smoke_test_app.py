"""smoke_test_app.py - headless check that every page and category loads and the controls work.
Run:  python smoke_test_app.py   (any local decision log written during the test is restored afterwards)"""
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

os.chdir(Path(__file__).parent)
sys.path.insert(0, ".")
from seller_growth.categories import ORDER  # noqa: E402
from seller_growth.data_schema import REQUIRED  # noqa: E402

OPP = "app_pages/seller_opportunities.py"
OVERVIEW = "app_pages/seller_revenue_overview.py"
LOG = Path("seller_growth/decisions.csv")
BACKUP = LOG.read_bytes() if LOG.exists() else None
UNITS, PRICE, GMV = "Est. units/month", "Avg selling price per unit", "Est. GMV/month"
BANNER = "Illustrative: synthetic data and assumptions, not OnBuy performance."
METRICS = ["Est. platform revenue a month", "Actionable seller opportunities", "Net contribution, 12 months",
           "Human calls · automated journeys"]


def all_text(at) -> str:
    parts = [x.value for x in list(at.markdown) + list(at.caption) + list(at.title) + list(at.subheader)
             + list(at.warning) + list(at.info) + list(at.success)]
    parts += [str(d.value.to_dict()) for d in at.dataframe] + [str(t.value.to_dict()) for t in at.table]
    return "\n".join(str(p) for p in parts)


def category(k: str) -> AppTest:
    at = AppTest.from_file(OPP, default_timeout=90)
    at.session_state["category"] = k
    return at.run()


def check_break_even(at, where):
    assert any(e.label == "Why call vs message?" for e in at.expander), where
    assert any(m.value.startswith("Should someone phone this seller") and "≈ £28 of platform revenue a month" in m.value
               for m in at.markdown), where
    assert any("£45,000 fully loaded yearly cost" in c.value and "= £39.38" in c.value and "= £0.80" in c.value
               for c in at.caption), where
    assert any("**£27.83 a month**" in m.value for m in at.markdown), where
    grids = [d.value for d in at.dataframe if "Cost of one call" in d.value.columns]
    assert grids and list(grids[0]["Cost of one call"]) == ["£20", "£40", "£80"], where
    assert any(c.value.startswith("How to read the grid") for c in at.caption), where


try:
    # Overview (landing)
    at = AppTest.from_file(OVERVIEW, default_timeout=90).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Seller Revenue | Commercial Decision Support"
    assert any("when is a human conversation worth more than an automated intervention?" in m.value
               for m in at.markdown)
    assert any(BANNER in w.value for w in at.warning)
    assert [m.label for m in at.metric] == METRICS, [m.label for m in at.metric]
    assert at.metric[0].value == "£186,276" and at.metric[1].value == "49" and at.metric[3].value == "15 · 34", \
        [m.value for m in at.metric]
    assert len(at.dataframe) <= 3, len(at.dataframe)      # few tables on the first screen (+ the break-even grid)
    check_break_even(at, "overview")
    assert any(b.label == "Download decision log" for b in at.get("download_button"))
    print("overview ok:", [m.value for m in at.metric])

    for k in ORDER:
        at = category(k)
        print(k, "exceptions:", [e.value for e in at.exception], "| dataframes:", len(at.dataframe),
              "| buttons:", len(at.button))
        assert not at.exception, k
        assert any(BANNER in w.value for w in at.warning), k
        assert [m.label for m in at.metric[:4]] == METRICS, k
        check_break_even(at, k)
        assert any(c.value.startswith("Seller Revenue v1.0") for c in at.caption), k
        heads = [s.value for s in at.subheader]
        order = ["Opportunity ranking", "Seller decision view", "Revenue per seller (to OnCommerce, per month)",
                 "Products: est. units, average price and GMV per month", "Method and formulas"]
        assert [heads.index(h) for h in order] == sorted(heads.index(h) for h in order), heads
        rank = [d.value for d in at.dataframe if "Recommended action" in d.value.columns][0]
        assert rank["Seller"].is_unique, k
        assert (rank["Status"] != "Deferred: fix first").all(), k
        for h in ("Seller situation", "Recommended action", "Why", "Commercial value", "Delivery", "Next review"):
            assert any(m.value == f"#### {h}" for m in at.markdown), (k, h)
        assert any("Expected net contribution after cost" in str(t.value.index.tolist()) for t in at.table), k
        assert any(set(d.value.columns) >= {"Item", "Value", "Type"} for d in at.dataframe), k
        types = set().union(*[set(d.value["Type"]) for d in at.dataframe if "Type" in d.value.columns
                              and "Item" in d.value.columns])
        assert types <= {"Published", "Observed in sample", "Assumption", "Model estimate"}, types
        for e in ("How these numbers are worked out", "How orders, revenue and LTV are worked out",
                  "Sensitivity: how much the answer moves with the weakest assumptions", "Action rules in plain words"):
            assert any(x.label == e for x in at.expander), (k, e)
        assert any("Net contribution £ (12 mo)" in d.value.columns for d in at.dataframe), k   # sensitivity
        cols = [list(d.value.columns) for d in at.dataframe]
        assert sum(any(UNITS in c for c in cs) for cs in cols) >= 2, (k, cols)
        for cs in cols:
            for i, c in enumerate(cs):
                if UNITS in c:
                    assert PRICE in cs[i + 1] and GMV in cs[i + 2], (k, cs)
        vals = [d.value["Where the order count comes from"] for d in at.dataframe
                if "Where the order count comes from" in d.value.columns][0]
        assert set(vals) <= {"Shown on OnBuy", "Estimated from reviews", "Not shown"}, set(vals)
        assert at.selectbox(key=f"{k}_value_seller").index == 0
        assert any("5. Lifetime value (LTV)" in str(t.value.index.tolist()) for t in at.table), k
        assert any(c.value.startswith("Note on the ratio: About") and "1 review per about 15 orders" in c.value
                   for c in at.caption), k
        assert any("sold to date" in str(t.value.to_dict()) for t in at.table), k
        labels = [w.label for w in list(at.sidebar.slider) + list(at.sidebar.number_input)
                  + list(at.sidebar.selectbox) + list(at.sidebar.checkbox)]
        assert labels and all(lb.startswith(("[Published]", "[Assumption]")) for lb in labels), labels
        assert any(b.label == "Reset to defaults" for b in at.sidebar.button), k

    # Interaction on heaters: approve and override, then change the cost build-up, then reset
    at = category("heaters")
    assert any(m.value.startswith("Route: **") for m in at.markdown)
    assert any("Drafted by rules" in m.value for m in at.markdown)
    [b for b in at.button if b.key.startswith("heaters_acc_")][0].click().run()
    [t for t in at.text_area if t.key.startswith("heaters_reason_")][0].input("Seller already on the right tier").run()
    [b for b in at.button if b.key.startswith("heaters_ovr_")][0].click().run()
    print("heaters approve/override:", [s.value for s in at.success])
    log = pd.DataFrame(at.session_state["decision_log"])
    assert list(log.columns) == ["timestamp", "page", "seller", "product", "play", "at_stake", "route", "expected_mo",
                                 "decision", "reason", "settings_hash"], log.columns
    assert log["decision"].tolist()[:2] == ["approve", "override: Reject, no action"], log["decision"].tolist()
    at.number_input(key="heaters_ch").set_value(2.8).run()       # double the hours per call -> £78.75 a call
    assert any("= £78.75" in c.value for c in at.caption), "cost build-up did not follow the hours"
    assert any("**£56.25 a month**" in m.value for m in at.markdown), "break-even did not follow the call cost"
    at.slider(key="heaters_churn").set_value(0.06).run()
    at.selectbox(key="heaters_prof").set_value("all-year").run()
    at.slider(key="heaters_n_buyers").set_value(100).run()
    at.slider(key="heaters_pu").set_value(0.05).run()
    at.slider(key="heaters_months").set_value(18).run()
    assert not at.exception, at.exception
    [b for b in at.sidebar.button if b.label == "Reset to defaults"][0].click().run()
    assert at.number_input(key="heaters_ch").value == 1.4 and at.slider(key="heaters_n_buyers").value == 50
    assert any("**£27.83 a month**" in m.value for m in at.markdown)
    print("reset ok")
    # 7% switch only on dehumidifiers / portable AC
    at = category("dehumidifiers")
    at.checkbox(key="dehumidifiers_la").check().run()
    assert not at.exception
    # each category has its own defaults (fans: Boost adoption 10%)
    assert category("fans").slider(key="fans_adopt").value == 0.10

    # Data mode: internal CSV by path (minimal columns), then a bad file shows the error, not a crash
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "internal.csv"
        pd.read_csv("seller_growth/example_products.csv")[REQUIRED].to_csv(good, index=False)
        bad = Path(d) / "bad.csv"
        pd.DataFrame({"x": [1]}).to_csv(bad, index=False)
        at = category("heaters")
        at.sidebar.radio[0].set_value("Internal CSV").run()
        at.sidebar.text_input[0].input(str(good)).run()
        assert not at.exception and not any(BANNER in w.value for w in at.warning), at.exception
        assert any("Internal data" in s.value for s in at.success)
        at.sidebar.text_input[0].input(str(bad)).run()
        assert any("Something went wrong" in e.value for e in at.error), [e.value for e in at.error]
        assert any("missing required columns" in str(c.value) for c in at.code)
        print("data mode ok")

    at = AppTest.from_file("app_pages/method_page.py", default_timeout=90).run()
    assert not at.exception and "Internal data: the listing CSV" in all_text(at)

    # launcher renders the default page, footer and version
    at = AppTest.from_file("streamlit_app.py", default_timeout=90).run()
    ok_footer = any("Not affiliated with OnCommerce or OnBuy" in c.value and "v1.0" in c.value
                    and "Made by Ami Sata" in c.value for c in at.caption)
    assert not at.exception and ok_footer and at.title[0].value == "Seller Revenue | Commercial Decision Support"
    print("launcher ok")
finally:
    if BACKUP is None:
        LOG.unlink(missing_ok=True)
    else:
        LOG.write_bytes(BACKUP)
print("SMOKE TEST PASSED")
