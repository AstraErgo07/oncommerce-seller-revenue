"""smoke_test_app.py - headless check that every page loads and the controls work.
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

SR_PAGES = [f"app_pages/seller_revenue_{k}.py" for k in ORDER]
LOG = Path("seller_growth/decisions.csv")
BACKUP = LOG.read_bytes() if LOG.exists() else None
UNITS, PRICE, GMV = "Est. units/month", "Avg selling price per unit", "Est. GMV/month"
BANNER = "Example data: method demo, not market estimates."


def all_text(at) -> str:
    parts = [x.value for x in list(at.markdown) + list(at.caption) + list(at.title) + list(at.subheader)
             + list(at.warning) + list(at.info) + list(at.success)]
    parts += [str(d.value.to_dict()) for d in at.dataframe] + [str(t.value.to_dict()) for t in at.table]
    return "\n".join(str(p) for p in parts)


try:
    for page in SR_PAGES + ["app_pages/seller_revenue_overview.py", "app_pages/method_page.py"]:
        at = AppTest.from_file(page, default_timeout=90).run()
        print(page, "exceptions:", [e.value for e in at.exception], "| dataframes:", len(at.dataframe),
              "| buttons:", len(at.button))
        assert not at.exception, page
        text = all_text(at)
        if page == "app_pages/method_page.py":
            assert "Internal data: the listing CSV" in text
            continue
        assert any(BANNER in w.value for w in at.warning), page
        assert any(b.label == "Download decision log" for b in at.get("download_button")), page
        assert any(e.label == "Why call vs message?" for e in at.expander), page
        assert any(m.value.startswith("Should someone phone this seller") and "≈ £49 a month" in m.value
                   for m in at.markdown), page
        assert any("Cost of one call" in list(d.value.columns) for d in at.dataframe), page
        assert any(c.value.startswith("How to read the grid") for c in at.caption), page
        assert any("£49.17 a month" in m.value for m in at.markdown), page
        if page in SR_PAGES:
            assert any(c.value.startswith("Seller Revenue v1.0") for c in at.caption), page
            assert any(UNITS in m.label for m in at.metric), page
            cols = [list(d.value.columns) for d in at.dataframe]
            assert sum(any(UNITS in c for c in cs) for cs in cols) >= 2, (page, cols)
            for cs in cols:
                for i, c in enumerate(cs):
                    if UNITS in c:
                        assert PRICE in cs[i + 1] and GMV in cs[i + 2], (page, cs)
            # results, sellers and plays first; method afterwards
            heads = [s.value for s in at.subheader]
            order = ["Results", "1. Revenue per seller (to OnCommerce, per month)", "2. Plays, ranked by expected £/month",
                     "3. Products: est. units, average price and GMV per month", "Method and formulas"]
            assert [heads.index(h) for h in order] == sorted(heads.index(h) for h in order), heads
            assert any(e.label == "How these numbers are worked out" for e in at.expander), page
            assert any(e.label == "How orders, revenue and LTV are worked out" for e in at.expander), page
            seller_cols = [cs for cs in cols if "Where the order count comes from" in cs]
            assert seller_cols and not any("Orders source" in cs for cs in cols), cols
            vals = [d.value["Where the order count comes from"] for d in at.dataframe
                    if "Where the order count comes from" in d.value.columns][0]
            assert set(vals) <= {"Shown on OnBuy", "Estimated from reviews", "Not shown"}, set(vals)
            key = page.split("seller_revenue_")[1][:-3]
            assert at.selectbox(key=f"{key}_value_seller").index == 0
            assert any("5. Lifetime value (LTV)" in str(t.value.index.tolist()) for t in at.table), page
            assert any(c.value.startswith("Note on the ratio: About") and "1 review per about 15 orders" in c.value
                       for c in at.caption), page
            assert any("sold to date" in str(t.value.to_dict()) for t in at.table), page
            # every assumption control carries a tag
            labels = [w.label for w in list(at.sidebar.slider) + list(at.sidebar.number_input)
                      + list(at.sidebar.selectbox) + list(at.sidebar.checkbox)]
            assert labels and all(lb.startswith(("[Real, published]", "[Assumed]")) for lb in labels), labels
            assert any(b.label == "Reset to defaults" for b in at.sidebar.button), page
            plays = [d.value for d in at.dataframe if "Decision line" in d.value.columns]
            if plays:
                line = plays[0]["Decision line"].iloc[0]
                assert " a month at stake, " in line and "£49 tipping point, so " in line \
                    and "Expected gain £" in line and "->" not in line, line

    # Interaction on the heaters page
    at = AppTest.from_file("app_pages/seller_revenue_heaters.py", default_timeout=90).run()
    assert any(m.value.startswith("Route ") and "Drafted by rules" in m.value for m in at.markdown)
    [t for t in at.text_area if t.key.startswith("heaters_reason_")][0].input("Seller already on the right tier").run()
    [b for b in at.button if b.key.startswith("heaters_ovr_")][0].click().run()
    print("heaters override success:", [s.value for s in at.success])
    assert at.success
    log = pd.DataFrame(at.session_state["decision_log"])
    assert list(log.columns) == ["timestamp", "page", "seller", "product", "play", "at_stake", "route", "expected_mo",
                                 "decision", "reason", "settings_hash"], log.columns
    assert log["settings_hash"].iloc[0] and log["decision"].iloc[0].startswith("override")
    # change settings, then reset
    at.slider(key="heaters_hc").set_value(240.0).run()
    assert any("£99.17 a month" in m.value for m in at.markdown), "break-even did not follow the call cost"
    assert any("A call costs about £240 of staff time" in m.value and "≈ £99 a month" in m.value
               for m in at.markdown), "explanation did not follow the slider"
    at.slider(key="heaters_churn").set_value(0.06).run()
    at.selectbox(key="heaters_prof").set_value("all-year").run()
    at.slider(key="heaters_n_buyers").set_value(100).run()
    at.slider(key="heaters_months").set_value(18).run()
    assert not at.exception, at.exception
    [b for b in at.sidebar.button if b.label == "Reset to defaults"][0].click().run()
    assert at.slider(key="heaters_hc").value == 120.0 and at.slider(key="heaters_n_buyers").value == 50
    assert any("£49.17 a month" in m.value for m in at.markdown)
    print("reset ok")
    # 7% switch only on dehumidifiers / portable AC pages
    at = AppTest.from_file("app_pages/seller_revenue_dehumidifiers.py", default_timeout=90).run()
    at.checkbox(key="dehumidifiers_la").check().run()
    assert not at.exception
    # each page has its own defaults (fans: Boost adoption 10%)
    assert AppTest.from_file("app_pages/seller_revenue_fans.py", default_timeout=90).run() \
        .slider(key="fans_adopt").value == 0.10

    # Data mode: internal CSV by path (minimal columns), then a bad file shows the error, not a crash
    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "internal.csv"
        pd.read_csv("seller_growth/example_products.csv")[REQUIRED].to_csv(good, index=False)
        bad = Path(d) / "bad.csv"
        pd.DataFrame({"x": [1]}).to_csv(bad, index=False)
        at = AppTest.from_file("app_pages/seller_revenue_heaters.py", default_timeout=90).run()
        at.sidebar.radio[0].set_value("Internal CSV").run()
        at.sidebar.text_input[0].input(str(good)).run()
        assert not at.exception and not any(BANNER in w.value for w in at.warning), at.exception
        assert any("Internal data" in s.value for s in at.success)
        at.sidebar.text_input[0].input(str(bad)).run()
        assert any("Something went wrong" in e.value for e in at.error), [e.value for e in at.error]
        assert any("missing required columns" in str(c.value) for c in at.code)
        print("data mode ok")

    # launcher renders the default page, footer and version
    at = AppTest.from_file("streamlit_app.py", default_timeout=90).run()
    ok_footer = any("Not affiliated with OnCommerce or OnBuy" in c.value and "v1.0" in c.value
                    and "Made by Ami Sata" in c.value for c in at.caption)
    assert not at.exception and ok_footer and any("Seller Revenue" in t.value for t in at.title)
    print("launcher ok")
finally:
    if BACKUP is None:
        LOG.unlink(missing_ok=True)
    else:
        LOG.write_bytes(BACKUP)
print("SMOKE TEST PASSED")
