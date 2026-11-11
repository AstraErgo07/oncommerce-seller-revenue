# Seller Revenue: OnCommerce (OnBuy), climate control

A decision-support prototype for OnBuy category managers. There is one page per category (Heaters, Fans,
Dehumidifiers, Portable AC, Air Purifiers) and an overview. For each listing it estimates units sold, the average
selling price per unit and GMV. For each seller it works out what they are worth to OnCommerce a month
(subscription, commission and Boost fees), suggests the next play (upgrade, retention, Boost, listing fix or a
revenue leak) and decides whether a Seller Success call or an automated message is the better use of money. The
category manager accepts or overrides every play, and each decision goes into a downloadable log.

The app runs on synthetic example data by default: "Example data: method demo, not market estimates." Internal data
can be loaded from the sidebar (schema in `data/README.md`).

Portfolio project. Made by Ami Sata.

## Run it

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Python 3.12 or newer. To host it on Streamlit Community Cloud: Create app, pick this repository, branch `main`, main
file `streamlit_app.py`, and choose Python 3.12 or newer under Advanced settings.

A plain-text write-up of the method with every number at the default settings is in `docs/OVERVIEW.md`, generated
from the code by `python tools/build_overview.py`.

## How it works

- Settings: every assumption is in one `Settings` object (`seller_growth/revenue.py`) passed to each calculation.
  The sidebar shows each one tagged [Real, published] or [Assumed], with a Reset to defaults button.
- Units: product reviews × 50 (about 1 in 50 buyers leaves a review) ÷ months selling × the season factor for the
  month, with OnBuy badge minimums. GMV = units × average selling price per unit.
- Seller revenue: lifetime orders ÷ tenure × average order value gives account sales; revenue = subscription +
  commission + Boost fees, using OnCommerce's published prices.
- Call or message: a call is worth it when the £ at stake a month is above
  (call cost − message cost) / (12 × (call success − message success)). At the defaults that is
  (£120 − £2) / (12 × 0.20) = £49.17 a month. Each page explains this tipping point in plain words under "Why call vs message?", after the plays, with a grid
  for other call costs and success gaps, and gives one line per play, for example "£X a month at stake, above the
  £Y tipping point, so call. Expected gain £Z a month."
- Decision log: timestamp, page, seller, product, play, at_stake, route, expected_mo, decision, reason and
  settings_hash (a short hash of the Settings in use). Download it with "Download decision log".
- LLM: optional (`OPENAI_API_KEY`). It only drafts the message text, from facts that leave out the route, the
  decision and every estimated £ figure. Each draft is labelled "Drafted by rules" or "Drafted by LLM". Without a
  key the rules write the draft.

## Layout

| Path | What it is |
|---|---|
| `streamlit_app.py` | entry point |
| `app_pages/` | the category pages, overview, and data and method page |
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

The unit tests check the formulas by hand, the break-even and its grid, the settings hash, the data schema, and
that plays and routes are identical with and without the LLM. The smoke test loads every page headless and uses the
controls.

## Data

OnBuy's website terms restrict automated collection and reuse of the site's content, so this repository ships
synthetic data only. Distributions are calibrated against a small sample of public OnBuy product pages viewed in
November 2026, kept as aggregates in `seller_growth/calibration_stats.json`. No raw marketplace data is included.

Independent portfolio project using public data. Not affiliated with OnCommerce or OnBuy.
