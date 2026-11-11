"""
tools/build_overview.py - writes docs/OVERVIEW.md, a plain markdown write-up of the Seller Revenue tool, from the code.

Every number comes from the same functions the app uses, at each page's default settings, so the document
matches the app. Run:
    python tools/build_overview.py                     # writes docs/OVERVIEW.md
    python tools/build_overview.py --pdf out.pdf       # also renders a PDF (needs the 'markdown' package and Chrome)
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.text import FOOTER, VERSION  # noqa: E402
from seller_growth.categories import CATEGORIES, ORDER  # noqa: E402
from seller_growth.revenue import (Settings, break_even_grid, break_even_stake, run_category,  # noqa: E402
                                   settings_hash, top_play_per_seller, units_summary)
from seller_growth.workings import (GLOSSARY, MONTH_NAMES, play_rules, plain_rule, product_workings,  # noqa: E402
                                    routing_rule, routing_workings, season_table, seller_workings, steps_markdown)

OUT = ROOT / "docs" / "OVERVIEW.md"
REPO = "https://github.com/AstraErgo07/oncommerce-seller-revenue"
EXAMPLE_LABEL = ("Example data: method demo, not market estimates. Calibrated on a small sample of public OnBuy pages "
                 "(Nov 2026); replace with internal data to use.")


def md_table(df: pd.DataFrame) -> str:
    """Plain markdown table. Prices to the penny, monthly units to one decimal, other £ and counts whole."""
    def fmt(col):
        c = col.lower()
        if "price" in c or "/unit" in c:
            return 2
        if "units/month" in c:
            return 1
        return 0

    def cell(v, dp):
        if isinstance(v, (float, int)) and not isinstance(v, bool):
            if isinstance(v, float) and math.isnan(v):
                return ""
            return f"{v:,.{dp}f}" if isinstance(v, float) else f"{v:,}"
        return str(v).replace("|", "/")
    dps = [fmt(c) for c in df.columns]
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(cell(v, d) for v, d in zip(row, dps)) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)

def gbp(x, dp=0):
    return f"£{x:,.{dp}f}"


def seller_revenue_section() -> list[str]:
    df = pd.read_csv(ROOT / "seller_growth" / "example_products.csv")
    out = []
    # headline table
    rows = []
    results = {}
    for k in ORDER:
        cfg = CATEGORIES[k]
        a = cfg.assumptions()
        p, s, pl = run_category(df, cfg.subcategories, a)
        results[k] = (cfg, a, p, s, pl)
        u = units_summary(p)
        top = pl.iloc[0] if len(pl) else None
        rows.append({"Category": cfg.label, "Example products": len(p), "Example sellers": len(s),
                     "Est. units/month (Nov)": round(u["est_units_month"]),
                     "Avg selling price per unit (£)": round(u["avg_price"], 2) if u["est_units_month"] else "",
                     "Est. GMV/month (£)": round(u["est_gmv_month"]),
                     "Commission/month (£)": round(u["est_commission_month"]),
                     "Revenue to OnCommerce/month (£)": round(s["est_revenue_month"].sum()),
                     "Plays": len(pl),
                     "Top play": "" if top is None else f"{top['play_type']}, {top['seller']}"})
    out += ["## Seller Revenue: headline numbers on the example data", "",
            f"{EXAMPLE_LABEL} Page defaults, November 2026. The sellers are synthetic, so these numbers show how the "
            "method behaves, not the size of any OnBuy category.", "", md_table(pd.DataFrame(rows)), "",
            "Revenue to OnCommerce counts each seller's whole account (all categories), so it is larger than the "
            "category commission and does not add up across categories.", ""]

    # worked examples on the heaters page
    cfg, a, p, s, pl = results["heaters"]
    top = p.sort_values("est_units_month", ascending=False).iloc[0].to_dict()
    steps, units, gmv = product_workings(top, a)
    out += ["## Worked example 1: from reviews to units and GMV", "",
            f"Heaters page, top-selling example listing: {top['title']} (seller {top['seller']}).", "",
            steps_markdown(steps), "",
            f"In one line: {int(top['product_review_count'])} reviews, about 1 in {1 / a.review_rate:.0f} buyers reviews, "
            f"so {top['product_review_count'] / a.review_rate:,.0f} sold to date; over "
            f"{top['review_window_months']:.0f} months that is {top['est_units_avg_month']:.1f} a month; x season factor "
            f"{top['season_index_now']:.2f} = {units:.1f} this month; x {gbp(top['avg_price'], 2)} average price = "
            f"{gbp(gmv)} GMV.", ""]
    sr = s.iloc[0].to_dict()
    ssteps, total = seller_workings(sr, a, s.attrs["reviews_per_order"])
    out += ["## Worked example 2: what a seller is worth to OnCommerce", "",
            f"Heaters page, highest-revenue example seller: {sr['seller']}. This uses the seller's whole account, "
            "because subscription and commission are paid on the whole account.", "",
            steps_markdown(ssteps), "",
            f"In this category alone the seller sells about {sr['climate_units_month']:.1f} units a month at an average "
            f"{gbp(sr['climate_avg_price'], 2)} = {gbp(sr['climate_gmv_month'])} GMV (seller GMV / seller units = "
            "average price).", ""]
    if len(pl):
        play = pl.iloc[0].to_dict()
        out += ["## Worked example 3: should a person call, or send an automated message?", "",
                f"Top play on the Heaters page: {play['play_type']} for {play['seller']} "
                f"(why: {plain_rule(play['rule'])}).", "", steps_markdown(routing_workings(play, a)), ""]

    # per category samples
    out += ["## Sample output for each category (example data, page defaults)", ""]
    for k in ORDER:
        cfg, a, p, s, pl = results[k]
        u = units_summary(p)
        out += [f"### {cfg.label}", "",
                f"Subcategories: {', '.join(cfg.subcategories)}. Season pattern: {a.season_profile}. "
                f"Totals: {u['est_units_month']:,.0f} units x "
                + (f"{gbp(u['avg_price'], 2)}" if u["est_units_month"] else "n/a")
                + f" average price = {gbp(u['est_gmv_month'])} GMV this month.", ""]
        tp = p.sort_values(["est_units_month", "est_gmv_month"], ascending=False).head(10)
        out += ["Top 10 products by estimated units:", "", md_table(pd.DataFrame({
            "Product": tp["title"], "Seller": tp["seller"], "Reviews": tp["product_review_count"],
            "Badge": tp["badge"].fillna("").replace("", "none"),
            "In stock": (~tp["flag_out_of_stock"]).map({True: "yes", False: "no"}),
            "Est. units/month": tp["est_units_month"].round(1),
            "Avg selling price per unit (£)": tp["avg_price"].round(2),
            "Est. GMV/month (£)": tp["est_gmv_month"].round(0)})), ""]
        ts = s.head(10)
        out += ["Seller revenue breakdown (top 10 by revenue to OnCommerce; category columns first, then the whole "
                "account):", "", md_table(pd.DataFrame({
                    "Seller": ts["seller"], "Est. units/month here": ts["climate_units_month"].round(1),
                    "Avg selling price per unit (£)": ts["climate_avg_price"].round(2),
                    "Est. GMV/month here (£)": ts["climate_gmv_month"].round(0), "Tier": ts["tier"],
                    "Subscription (£)": ts["subscription_month"], "+ Commission (£)": ts["est_commission_month"].round(0),
                    "+ Boost (£)": ts["est_boost_month"].round(0), "= Revenue/month (£)": ts["est_revenue_month"].round(0)})),
                ""]
        if len(pl):
            tpl = pl.head(10)
            out += ["Top plays:", "", md_table(pd.DataFrame({
                "Rank": tpl["rank"], "Play": tpl["play_type"], "Seller": tpl["seller"],
                "Product": tpl["title"].fillna("").replace("", "(whole account)"), "Why": tpl["rule"].map(plain_rule),
                "£ at stake/month": tpl["stake_month"].round(1), "Route": tpl["route"],
                "Expected £/month": tpl["expected_month"].round(1)})), ""]
            rc = pl["route"].value_counts()
            out += [f"{len(pl)} plays in total: {rc.get('Human (Seller Success)', 0)} calls, "
                    f"{rc.get('Automated journey', 0)} automated. One row per seller: "
                    f"{len(top_play_per_seller(pl))} sellers have a next best play.", ""]
    return out


def break_even_section(a: Settings) -> list[str]:
    be = break_even_stake(a)
    grid = break_even_grid(a).map(lambda v: gbp(v, 2) if v != float("inf") else "never")
    return ["## Call or message: the break-even", "",
            "A Seller Success call is worth it when the £ at stake a month is above "
            "(call cost − message cost) / (12 months × (call success − message success)).", "",
            f"At the defaults: ({gbp(a.human_cost)} − {gbp(a.auto_cost)}) / ({a.value_horizon_months:g} × "
            f"({a.p_success_human:.0%} − {a.p_success_auto:.0%})) = {gbp(be, 2)} a month.", "",
            f"Break-even £ a month for other call costs (rows) and success gaps (columns), message cost "
            f"{gbp(a.auto_cost)}:", "", md_table(grid.reset_index().rename(columns={"index": "Call cost"})), "",
            "Each play on a page is shown as one line: \"£X at stake -> route (break-even £Y) -> expected £Z/mo\".", ""]


RPO = 1.0


def build() -> str:
    a = CATEGORIES["heaters"].assumptions()
    global RPO
    RPO = run_category(pd.read_csv(ROOT / "seller_growth" / "example_products.csv"), ("fan heaters",), a)[1] \
        .attrs["reviews_per_order"]
    cal = json.loads((ROOT / "seller_growth" / "calibration_stats.json").read_text())
    n_cal = sum(v["n_products"] for v in cal["categories"].values())
    L = ["# Seller Revenue (OnCommerce, OnBuy): overview", "",
         f"Version {VERSION}. Generated by `tools/build_overview.py` from the code, at each page's default settings, so "
         f"the numbers match the app. This is the plain-text version of the Streamlit app. Code: {REPO}.", "",
         "Portfolio project. Author details available on request.", "",
         "## Purpose", "",
         "A decision-support prototype for OnBuy (part of OnCommerce) category managers in climate control, one page "
         "per category manager (Heaters, Fans, Dehumidifiers, Portable AC, Air Purifiers). For each listing: estimated "
         "units, average selling price and GMV. For each seller: what they are worth to OnCommerce a month and the next "
         "action, with a choice between a Seller Success call and an automated message. The calculations are plain "
         "Python rules. A person accepts or overrides every recommendation, and every decision is logged. An LLM is "
         "optional and only drafts message text.", "",
         "## What is real and what is assumed", "",
         "| Item | Source |", "|---|---|",
         f"| Listing data | Example data: 20 synthetic products per category, calibrated on {n_cal} public OnBuy product "
         "pages viewed in November 2026. No raw marketplace data is included. Internal data can be loaded instead "
         "(schema in `data/README.md`). |",
         f"| Fees | [Real, published] subscriptions Standard £{a.sub_promo['Standard']:.0f}, Partner "
         f"£{a.sub_promo['Partner']:.0f} (list £{a.sub_list['Partner']:.0f}), Professional "
         f"£{a.sub_promo['Professional']:.0f} (list £{a.sub_list['Professional']:.0f}) a month, promo until January "
         f"2028; commission {a.commission_rate:.0%}, at least £{a.min_fee:.2f} an item; Boost fee levels "
         f"{', '.join(f'{k} {v:.0%}' for k, v in a.boost_levels.items())}. |",
         f"| Units sold | [Assumed] from review counts: 1 in {1 / a.review_rate:.0f} buyers leaves a review. |",
         "| Seasonality | [Assumed] a season factor per month (table below), my judgement. |",
         "| Costs and behaviour | [Assumed] seller tenure, average order value, Boost take-up, sales lift, success "
         "rates and cost of a call or a message, OnCommerce margin, churn. |",
         "| Where to change them | The Assumptions panel in the sidebar of each page, with Reset to defaults. |", "",
         "## Default settings", "",
         f"All assumptions are in one `Settings` object passed to every calculation. Defaults (Heaters page; the "
         f"settings hash for it is `{settings_hash(a)}`):", "",
         f"- Reviews: 1 in {1 / a.review_rate:.0f} buyers. Sales spread over the months since the first review where "
         f"every review is listed, otherwise {a.review_window_months:g} months (at least {a.min_window_months:g}). "
         f"Halve units if the newest review is older than {a.stale_after_months:g} months.",
         f"- Call success {a.p_success_human:.0%}, message success {a.p_success_auto:.0%}; call cost "
         f"{gbp(a.human_cost)}, message cost {gbp(a.auto_cost)}; value counted over {a.value_horizon_months:g} months.",
         f"- OnCommerce margin {a.contribution_margin:.0%}; seller churn {a.monthly_churn:.0%} a month; upgrades "
         f"{a.monthly_upgrade_rate:.0%} a month.",
         f"- Seller reviews to orders: about {1 / RPO:.1f} orders per seller review (median of sellers showing both).",
         f"- Average order value {gbp(a.avg_order_value)}; tenure {a.seller_tenure_months:g} months; Partner if at "
         f"least {a.partner_orders_k:g}k lifetime orders and no badge.",
         f"- Boost: {a.boost_adoption:.0%} of sellers on this page, level {a.boost_level}, "
         f"{a.boosted_share_of_gmv:.0%} of their sales boosted.", "",
         "## Every Seller Revenue formula in plain words", "",
         ]
    for term, meaning in GLOSSARY.items():
        L.append(f"- {term}: {meaning}")
    L += ["",
          "Units for one listing, step by step:", "",
          f"1. Count the reviews on the listing.",
          f"2. About 1 in {1 / a.review_rate:.0f} buyers leaves a review ({a.review_rate:.0%}), so reviews x "
          f"{1 / a.review_rate:.0f} = items sold to date.",
          f"3. Divide by the months the listing has been selling (time since the first review where all reviews are "
          f"listed, otherwise {a.review_window_months:g} months). That gives sales in an average month.",
          f"4. If the newest review is more than {a.stale_after_months:g} months old, halve it.",
          "5. Multiply by the season factor for the current month.",
          f"6. OnBuy badges set a minimum: Bestseller {a.bestseller_floor_units:g}, Hot {a.hot_floor_units:g}, In demand "
          f"{a.in_demand_floor_units:g} a month; a listing with no badge and no reviews counts as {a.no_signal_units:g}.",
          "7. Out of stock, or a price that looks wrong: 0 this month.",
          f"8. Where several sellers offer the product, the recommended offer wins {a.buybox_share:.0%} of its sales and "
          "the others share the rest.",
          "9. GMV = units x average selling price per unit (including delivery).",
          f"10. Commission = units x the larger of {a.commission_rate:.0%} of the delivered price and "
          f"£{a.min_fee:.2f}.", "",
          "What a seller is worth to OnCommerce a month:", "",
          "1. Lifetime orders: the order count in the seller box, or the seller's review count x about 15 (the median "
          "orders per seller review among sellers that show both).",
          f"2. Orders a month = lifetime orders / {a.seller_tenure_months:g} months.",
          f"3. Sales a month for the whole account = orders a month x £{a.avg_order_value:g} average order.",
          f"4. Tier: Professional where the badge is shown; otherwise Partner if at least {a.partner_orders_k:g}k "
          "lifetime orders, else Standard. Subscription from the published price list.",
          f"5. Commission = {a.commission_rate:.0%} x sales.",
          f"6. Boost fees = share of sellers using Boost x share of their sales boosted ({a.boosted_share_of_gmv:.0%}) x "
          f"Boost fee level ({a.boost_level}, {a.boost_levels[a.boost_level]:.0%}) x sales. The share using Boost is set "
          "per category (Heaters 25%, Fans 10% and so on).",
          "7. Revenue = subscription + commission + Boost fees.",
          f"8. Lifetime value = revenue x {a.contribution_margin:.0%} OnCommerce margin / {a.monthly_churn:.0%} monthly "
          f"churn (a seller stays about {1 / a.monthly_churn:.0f} months on average).",
          f"9. Forecast: each month {a.monthly_churn:.0%} of sellers leave, {a.monthly_upgrade_rate:.0%} move up a tier, "
          "prices step up to list in January 2028, and accepted plays add their expected value over three months.", "",
          "Season factors (1.0 is an average month; my judgement for the UK, not OnBuy data):", "",
          season_table(a), "",
          "## The decision workflow", "",
          "1. Load the category's listings (here, example data) and the published fees.",
          "2. Work out units, average price, GMV and commission for each listing.",
          "3. Work out each seller's revenue to OnCommerce and tier.",
          "4. Run the play rules below; each play gets a monthly £ at stake.",
          "5. Route each play to a Seller Success call or an automated message.",
          "6. Rank plays by expected £ a month. A draft message is written by rules, or by an LLM if one is set up. "
          "The LLM sees only the topic, seller, product, reason, listing facts and published fees, never the route, "
          "the decision or an estimated £ figure, and the page labels each draft \"Drafted by rules\" or "
          "\"Drafted by LLM\".",
          "7. The category manager accepts or overrides each play, with a reason for an override. Every decision goes "
          "into a decision log (timestamp, page, seller, product, play, at_stake, route, expected_mo, decision, "
          "reason, settings_hash) that can be downloaded as a CSV.", "",
          "Play rules:", ""]
    L += [f"- {k}: {v}" for k, v in play_rules(a).items()]
    L += ["", "Routing: " + routing_rule(a), ""]
    L += break_even_section(a)
    L += seller_revenue_section()
    L += ["## Limits", "",
          "- The OnBuy data is synthetic. It copies the shape of a small sample found through search, which favours "
          "listings that rank well. It says nothing about any real seller.",
          "- Units are inferred from reviews. Every £ figure scales with them.",
          "- Season factors and the cost benchmarks are judgement, not data.",
          "- OnBuy's website terms restrict automated collection and reuse of its content, so the repository ships "
          "synthetic data only.", "",
          FOOTER, ""]
    text = "\n".join(L)
    for bad in ("\u2014", "\u2013"):
        assert bad not in text, "dash found"
    return text


def to_pdf(md_text: str, pdf: Path) -> None:
    import markdown  # pip install markdown
    body = markdown.markdown(md_text, extensions=["tables"])
    css = ("body{font-family:Arial,Helvetica,sans-serif;font-size:9.5pt;line-height:1.35;margin:0 6mm}"
           "h1{font-size:18pt}h2{font-size:13pt;margin-top:16pt;border-bottom:1px solid #ccc}h3{font-size:11pt}"
           "table{border-collapse:collapse;margin:6pt 0;font-size:8pt;page-break-inside:auto}"
           "td,th{border:1px solid #bbb;padding:2pt 4pt;vertical-align:top}th{background:#f0f0f0}"
           "tr{page-break-inside:avoid}")
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "overview.html"
        h.write_text(html, encoding="utf-8")
        subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", h.as_uri()], check=True, capture_output=True, timeout=120)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--pdf", type=Path)
    args = ap.parse_args()
    text = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    if args.pdf:
        to_pdf(text, args.pdf)
        print(f"wrote {args.pdf}")


if __name__ == "__main__":
    main()
