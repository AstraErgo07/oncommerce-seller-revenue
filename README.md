# Seller Revenue | Commercial Decision Support (OnCommerce, OnBuy, climate control)

Which sellers should we help, what should we recommend, and when is a human conversation worth more than an
automated intervention?

A decision-support prototype for seller revenue in OnBuy's climate-control categories (Heaters, Fans,
Dehumidifiers, Portable AC, Air Purifiers). For each seller it estimates what they are worth to OnCommerce a month
(subscription, commission and Boost fees), picks one recommended next action (fix a sales leak, Boost, upgrade,
retention or downgrade risk, or listing work), works out what that action is worth after its own cost, and says
whether a Seller Success call or an automated message is the better route. A person approves or overrides every
action, with a reason, and each decision goes into a downloadable log. It is a prototype for discussion, not
production software.

Illustrative: synthetic data and assumptions, not OnBuy performance. Internal data can be loaded from the sidebar
(schema in `data/README.md`).

Portfolio project. Made by Ami Sata.

## Headline figures (illustrative, example data, defaults)

| Measure | Value |
|---|---|
| Est. platform revenue a month, each seller counted once | £186,276 (74 example sellers) |
| Actionable seller opportunities (Recommended primary actions worth more than they cost) | 49 |
| Modelled net contribution over 12 months, after £618 of intervention costs | £2,853 |
| Human calls · automated journeys | 15 · 34 |
| Not counted: sellers whose lead action is an upgrade that needs validation | 2 |
| Call or message tipping point | £27.83 of platform revenue at stake a month |

These are model estimates, not results. `docs/OVERVIEW.md` has the full figures, the audit of the earlier version
and a sensitivity table.

## Run it

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Python 3.12 or newer. To host it on Streamlit Community Cloud: Create app, pick this repository, branch `main`, main
file `streamlit_app.py`, and choose Python 3.12 or newer under Advanced settings.

A plain-text write-up of the method with every number at the default settings is in `docs/OVERVIEW.md`, generated
from the code by `python tools/build_overview.py`.

## Pages

- Overview: the four headline figures, a short table by category and the top five opportunities.
- Seller opportunities: pick a category, then the opportunity ranking (one primary action per seller), the seller
  decision view (situation, recommended action, why, commercial value, delivery, next review, approve or override),
  "Why call vs message?", the supporting tables and the method, with a sensitivity table.
- Data and method: sources, published prices and the data schema.

## How it works

- Settings: every assumption is in one `Settings` object (`seller_growth/revenue.py`) passed to each calculation.
  The sidebar shows each one tagged [Published] or [Assumption], with a Reset to defaults button. Evidence in the
  seller view is tagged Published, Observed in sample, Assumption or Model estimate, and each action has a
  confidence of Low or Medium.
- Units: product reviews × 50 (about 1 in 50 buyers leaves a review) ÷ months selling × the season factor for the
  month, with OnBuy badge minimums. GMV = units × average selling price per unit.
- Seller revenue: lifetime orders ÷ tenure × average order value gives account sales; revenue = subscription +
  commission + Boost fees, using OnCommerce's published prices.
- Next best action: fix first (stock, price, delivery, duplicate pages, listing work), then Boost only where the
  listing is eligible and it repays the seller and the message, then an upgrade only if the seller is better off
  after commission and the extra fee (otherwise none, or Needs validation if the case rests on estimates). One
  primary action per seller, plus an optional secondary; only the primary is counted. Ranked by net contribution
  after cost, not by fee size. Next review: 14 days for a stock or price fix, 30 for Boost and listing work, 60 for
  an upgrade.
- Value of an action: platform revenue at stake a month × success rate × 70% OnCommerce margin × 9.90 months still
  trading out of 12 (3% churn a month), minus the cost of the call or message.
- Call and message costs (rough estimates, not OnCommerce data, all editable): call = £45,000 fully loaded a year
  ÷ 1,600 productive hours × 1.4 hours per completed call = £39.38; message = £1,500 journey build ÷ 2,000 sellers
  reached + £0.05 to send = £0.80.
- Call or message: a call is worth it when the platform revenue at stake a month is above
  (call cost − message cost) / (margin × months still trading × (call success − message success)). At the defaults
  that is (£39.38 − £0.80) / (70% × 9.90 × 0.20) = £27.83 a month (the earlier version said £49.17, using placeholder
  £120 and £2 costs and no margin or churn). "Why call vs message?" explains it in plain words, with the cost build-up
  and a grid for £20, £40 and £80 calls.
- Decision log: timestamp, page, seller, product, play, at_stake, route, expected_mo, decision, reason and
  settings_hash (a short hash of the Settings in use). Download it with "Download decision log".
- LLM: optional (`OPENAI_API_KEY`). It only drafts the message text, from facts that leave out the route, the
  decision and every estimated £ figure. Each draft is labelled "Drafted by rules" or "Drafted by LLM". Without a
  key the rules write the draft.

## Layout

| Path | What it is |
|---|---|
| `streamlit_app.py` | entry point |
| `app_pages/` | overview, seller opportunities (one page, category selector), data and method |
| `seller_growth/revenue.py` | the calculations and `Settings` |
| `seller_growth/categories.py` | per-category defaults and the reasons for them |
| `seller_growth/agent.py` | message drafts (rules, or an LLM for the text only) |
| `seller_growth/data_schema.py`, `data/README.md` | the listing CSV and how each column is used |
| `seller_growth/example_products.csv` | synthetic example data |
| `data/SOURCES.md` | sources, published prices and every assumption |
| `tools/` | example data generator, calibration and the overview builder |

## Tests

```
python -m unittest discover -s seller_growth -p "test_*.py"
python smoke_test_app.py
```

The unit tests check the formulas by hand, seller revenue, upgrade eligibility and seller benefit, Boost eligibility,
call vs message net value, the cost build-up, the break-even and its grid, zero-sales and missing data, that each
seller is counted once, approval and override logging, the settings hash, the data schema, and that actions and
routes are identical with and without the LLM. The smoke test loads every page headless and uses the controls.

## Data

OnBuy's website terms restrict automated collection and reuse of the site's content, so this repository ships
synthetic data only. Distributions are calibrated against a small sample of public OnBuy product pages viewed in
November 2026, kept as aggregates in `seller_growth/calibration_stats.json`. No raw marketplace data is included.

Independent portfolio project using public data. Not affiliated with OnCommerce or OnBuy.
