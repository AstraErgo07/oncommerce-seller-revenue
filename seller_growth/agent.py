"""
seller_growth/agent.py - drafts the text of a seller message and a call brief for a play.

Guardrail: the rules in revenue.py decide the play, the £ at stake, the route (call or automated message) and the
ranking; the person using the app decides accept or override. The LLM, if one is configured, only writes text. It is
given a facts dict built by llm_facts(), which leaves out the route, the decision, the ranking and every estimated £
figure, and its reply is reduced to text fields. So the LLM cannot change any number, route or decision.
No API key, a network error or a bad reply -> the rules-based draft (source = "rules").
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # so "common" imports work
if not __package__:  # only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.llm import LLMUnavailable, call_llm, extract_json_object, validate_common  # noqa: E402
try:
    from .revenue import (BOOST, FIRST_SALE, LEAK_DELIVERY, LEAK_DUP, LEAK_OOS, LEAK_PRICE,  # noqa: F401
                          RETAIN, UPGRADE, Settings)
    from .workings import plain_rule
except ImportError:
    from revenue import (BOOST, FIRST_SALE, LEAK_DELIVERY, LEAK_DUP, LEAK_OOS, LEAK_PRICE,  # noqa: F401
                         RETAIN, UPGRADE, Settings)
    from workings import plain_rule

LLM_KEYS = ["subject", "message", "call_brief"]          # all the LLM may return
DRAFT_KEYS = LLM_KEYS + ["confidence", "additional_data"]
# evidence keys never shown to the LLM: estimates, £ at stake, route, decision and ranking
BLOCKED_WORDS = ("route", "decision", "rank", "stake", "expected", "net_value", "est_", "gmv", "revenue", "gain",
                 "roi", "breakeven", "fee_to_sales", "units", "lifetime_orders", "orders_source", "season",
                 "assumed", "validation", "chance", "confidence", "status", "net")


def llm_facts(play: dict, a: Settings) -> dict:
    """The only data the LLM sees. Published fees and listing facts, as text. No route, decision or estimates."""
    ev = {k: v for k, v in play["evidence"].items() if not any(w in k.lower() for w in BLOCKED_WORDS)}
    return {
        "topic": play["play_type"], "seller": play["seller"], "product": play.get("title", "") or "",
        "reason": plain_rule(play["rule"]),
        "listing_and_published_facts": {k.replace("_", " "): str(v) for k, v in ev.items()},
        "published_fees": (f"subscriptions a month: Standard £{a.sub_promo['Standard']:.0f}, Partner "
                           f"£{a.sub_promo['Partner']:.0f} (list £{a.sub_list['Partner']:.0f} from Jan 2028), "
                           f"Professional £{a.sub_promo['Professional']:.0f} (list £{a.sub_list['Professional']:.0f}); "
                           f"commission {a.commission_rate:.0%}, at least £{a.min_fee:.2f} an item"),
    }


def build_prompt(facts: dict) -> str:
    return f"""Write a short, helpful note from the OnBuy seller team to a marketplace seller, and a three-line
brief a colleague could use if they phone the seller. Use ONLY the facts below; do not invent sales figures, fees
or promises. Plain UK English, under 120 words for the message. Do not mention internal estimates.

FACTS:
{json.dumps(facts, indent=2)}

Reply with ONE JSON object and nothing else, with exactly these keys:
{{"subject": "subject line", "message": "the seller-facing message", "call_brief": "three short lines"}}"""


def parse_reply(text: str) -> dict:
    return validate_common(extract_json_object(text), LLM_KEYS, {})


def _short(title: str, n: int = 70) -> str:
    return title if len(title) <= n else title[:n].rsplit(" ", 1)[0] + "…"


def rules_outreach(play: dict, a: Settings) -> dict:
    t, ev, s = play["play_type"], play["evidence"], play["seller"]
    prod = _short(play.get("title") or "", 60)
    est_tier = str(ev.get("tier_source", "")).startswith("EST")
    conf = "low" if est_tier else "medium"
    if t == UPGRADE:
        nxt = ev["next_tier"]
        subj = f"{s}: what {nxt} would add to your OnBuy store"
        msg = (f"Hi {s} team, we'd like to check whether {nxt} would be worth it for you. For "
               f"£{ev['extra_fee_month_gbp']:.0f}/month more (promo price until Jan 2028, then "
               f"£{ev['extra_fee_after_jan_2028_gbp']:.0f}) you get: {ev['next_tier_features'].lstrip('+ ')}. Could we "
               "look at your sales and margins together to see whether those features would pay for themselves?")
        brief = (f"Tier: {ev['tier']} ({ev['tier_source']}). Lifetime orders {ev['lifetime_orders']:,} ({ev['orders_source']}).\n"
                 f"Est. account GMV £{ev['est_account_gmv_month_gbp']:,}/mo (estimate); assumed "
                 f"{ev['assumed_sales_lift']:.0%} sales lift gives the seller about £{ev['est_seller_gain_month_gbp']:,.0f}/mo "
                 f"extra profit vs £{ev['extra_fee_month_gbp']:.0f} extra fee (net £{ev['est_seller_net_month_gbp']:,.0f}; "
                 f"£{ev['est_seller_net_after_jan_2028_gbp']:,.0f} at list price).\n"
                 f"Validation needed: {ev['validation_reasons']}. Confirm tier, real GMV and margin before recommending.")
        more = "Seller's actual tier, monthly GMV and margin; conversion lift seen by sellers who upgraded."
    elif t == RETAIN:
        subj = f"{s}: getting more from your OnBuy plan"
        if play["rule"] == "no_sales_evidence":
            msg = (f"Hi {s} team, we noticed your listings haven't picked up reviews or sales yet. Here's a 3-step "
                   "checklist (brand, full description, UK delivery promise) and a free listing review. Reply 'review' and we'll book it.")
        else:
            msg = (f"Hi {s} team, we'd like to make sure your {ev['tier']} plan is paying back. Can we book 15 minutes "
                   f"to review your listings, Boost settings and which plan fits best ahead of the Jan 2028 price change?")
        brief = (f"Tier {ev['tier']} ({ev['tier_source']}): fee £{ev['subscription_month_gbp']:.0f}/mo = "
                 f"{ev['fee_to_sales_now']:.1%} of est. GMV now, {ev['fee_to_sales_after_jan_2028']:.1%} at the "
                 f"£{ev['list_price_after_jan_2028_gbp']:.0f} list price after Jan 2028 (GMV is an estimate).\n"
                 f"Revenue at risk ~£{play['stake_month']:,.0f}/mo; latest review {ev['latest_review']}.\n"
                 "Offer: listing fixes + Boost test before any downgrade; a planned downgrade beats a cancellation.")
        more = "Login activity, cancellation-page visits, real GMV trend and support tickets."
        conf = "medium" if ev["tier"] == "Professional" and not est_tier else "low"
    elif t == BOOST:
        subj = f"Boost '{prod}' while demand is in season"
        msg = (f"Hi {s} team, '{prod}' is in season now and your offer is competitive. Boost {ev['suggested_boost_level']} "
               "puts it in higher-visibility slots and is charged only on boosted sales. Turn it on for 4 weeks and "
               "we'll share the incremental sales report.")
        brief = (f"Season index now {ev['season_index_now']} (estimate). Est. {ev['est_units_month']} units/mo.\n"
                 f"Seller ROI at {ev['suggested_boost_level']} = {ev['seller_boost_roi']} (assumes "
                 f"{a.boost_incremental_share:.0%} incremental sales, {a.seller_margin:.0%} margin).\n"
                 f"Break-even incremental share {ev['breakeven_incremental_share']}; measure with a holdout.")
        more = "Boost holdout results for similar listings; the seller's real margin."
    elif t == FIRST_SALE:
        subj = f"Quick fixes for '{prod}'"
        msg = (f"Hi {s} team, '{prod}' has no sales reviews yet. These fixes usually help first sales: "
               f"{ev.get('issues') or 'add brand, full description and images'}. Update the listing and we'll re-check it in 7 days.")
        brief = f"Quality {ev['quality_score']}/100: {ev.get('issues')}.\nn/a"
        more = "Page views and conversion for this listing."
    elif t == LEAK_OOS:
        subj = f"'{prod}' is out of stock in peak season"
        msg = (f"Hi {s} team, '{prod}' is showing out of stock just as demand peaks. Can you restock or tell us the "
               "back-in-stock date? We can notify waiting customers.")
        brief = (f"Est. lost {ev.get('lost_units_month')} units/mo in season (estimate from reviews).\n"
                 "Ask for restock date and whether a second seller can be matched to the page.\nn/a")
        more = "Restock date; page traffic while out of stock."
    elif t == LEAK_DUP:
        subj = f"Merge your duplicate page for '{prod}'"
        msg = (f"Hi {s} team, '{prod}' appears to duplicate an existing OnBuy page. Listing on the existing page keeps "
               "reviews together and puts your offer in the price comparison.")
        brief, more = "n/a", "Barcode and spec match between the two pages."
    elif t == LEAK_DELIVERY:
        subj = f"Delivery on '{prod}'"
        msg = (f"Hi {s} team, '{prod}' shows paid or slow delivery (fee £{ev.get('delivery_fee_gbp') or 0:.2f}, up to "
               f"{ev.get('delivery_max_days')} days). Could you offer free delivery within a week? Buyers tend to compare delivery terms.")
        brief, more = "n/a", "Dispatch location and on-time rate."
    else:  # LEAK_PRICE
        subj = f"Please check the price on '{prod}'"
        msg = (f"Hi {s} team, your price on '{prod}' looks out of line with the product (lowest offer "
               f"£{ev.get('lowest_offer_gbp')}, yours up to £{ev.get('highest_offer_gbp')}). Please check it's not a typo.")
        brief, more = "n/a", "Whether the price is a typo or a pack-size issue."
        conf = "high"
    return {"subject": subj, "message": msg, "call_brief": brief, "confidence": conf, "additional_data": more}


def draft_outreach(play: dict, a: Settings) -> dict:
    """Returns DRAFT_KEYS plus source ('llm' or 'rules') and note. Never returns or changes a route or decision."""
    base = rules_outreach(play, a)
    try:
        text = parse_reply(call_llm(build_prompt(llm_facts(play, a))))
        out = dict(base, **{k: text[k] for k in LLM_KEYS}, source="llm", note="")
    except LLMUnavailable as e:
        out = dict(base, source="rules", note=str(e))
    except (ValueError, json.JSONDecodeError) as e:
        out = dict(base, source="rules", note=f"LLM reply rejected ({e}); using the rules-based draft")
    except Exception as e:  # never crash the app
        out = dict(base, source="rules", note=f"Unexpected error ({type(e).__name__}: {e})")
    return {k: out[k] for k in DRAFT_KEYS + ["source", "note"]}


def drafted_by(draft: dict) -> str:
    return "Drafted by LLM" if draft.get("source") == "llm" else "Drafted by rules"


if __name__ == "__main__":
    import pandas as pd
    from revenue import run_all, top_play_per_seller
    here = Path(__file__).parent
    print("LLM key set:", bool(os.environ.get("OPENAI_API_KEY")))
    ra = Settings()
    _, _, plays = run_all(pd.read_csv(here / "example_products.csv"), ra)   # example data
    for play in top_play_per_seller(plays).head(4).to_dict("records"):
        d = draft_outreach(play, ra)
        print("\n" + "=" * 70)
        print(f"{play['play_id']} {play['play_type']} | {play['seller']} | route={play['route']} | {drafted_by(d)}")
        print(json.dumps(d, indent=2, ensure_ascii=False))
