# Seller Revenue tools (OnBuy, part of OnCommerce): sources and assumptions

## Scope

Climate control on OnBuy in five categories, chosen with one category selector on the "Seller opportunities" page;
the Overview page sums them. Each category shows only its own products and sellers and has its own assumption
defaults. Accepts and overrides go to one decision log for the
session, which you download as a CSV. Configuration is in `seller_growth/categories.py`, the
calculations in `seller_growth/revenue.py`, and the shared page in `app_pages/seller_revenue_common.py`.

| Page | Subcategories in the example | Example products | Example sellers | Calibration sample (pages) | Season profile (est.) | Boost adoption default (est.) | 7% rate switch |
|---|---|---|---|---|---|---|---|
| Heaters | fan heaters, oil-filled radiators, convector heaters | 20 | 10 | 14 | heating | 25%, peak season | no |
| Fans | tower, pedestal, desk | 20 | 23 | 8 | cooling | 10%, off season | no |
| Dehumidifiers | dehumidifiers | 20 | 13 | 9 | damp | 20% | yes |
| Portable AC | listed as "air conditioners" | 20 | 10 | 8 | cooling | 10%, off season | yes |
| Air purifiers | air purifiers | 20 | 18 | 8 | flat | 15% | no |

All other assumptions start at the same value on every page, because there is no category-specific evidence for them.
Keeping them equal makes the pages comparable. Each page lists every assumption with its current value, its default
and the reason for it.

## Data

Every page runs on example data, labelled on the page: "Illustrative: synthetic data and assumptions, not OnBuy
performance." Example sellers are separate in each category (Example Seller A under Heaters is not Example Seller A
under Fans), so the Overview adds the categories up.

Distributions calibrated against a small sample of public OnBuy product pages viewed in November 2026. No raw
marketplace data is included.

OnBuy's website terms restrict automated collection and reuse of the site's content, so this repository ships
synthetic data only.

- `tools/gen_example_data.py` (seed 2026) writes `data/example/onbuy_example_products_raw.jsonl`: 20 synthetic
  products per category. Titles are "Example <type> NN", sellers "Example Seller A" and so on, brands "Brand NN". There
  are no real titles, brands, seller names, URLs or EANs.
- `seller_growth/build_data.py` turns that file into `seller_growth/example_products.csv`, which the pages read.
- `seller_growth/calibration_stats.json` holds the calibration targets per category. It contains aggregates only:
  sample size, subcategory mix, price distribution (log-normal fit, median and range), share of listings with no
  reviews and the review count distribution, badge mix, offers per listing, out of stock, paid delivery, price
  anomaly and other flag shares, the share of sellers showing an order count or a Professional badge, and the median
  ratio of seller reviews to lifetime orders. No rows, names or addresses.
- Shares are matched by count (largest remainder), so a 20-product example has the sample's mix as closely as 20 rows
  allow. Prices and review counts are drawn from the fitted log-normal, kept inside the sample's range.
- To use the tools for real, choose Internal CSV under Data in the sidebar. The columns are in `data/README.md`.

Published OnCommerce prices (oncommerce.com/gb/onbuy, read 11 Nov 2026):

- Subscriptions per month, ex VAT: Standard £25, Partner £69 (list £129), Professional £249 (list £499). The promotional
  prices run until January 2028. The forecast moves to list prices from then.
- Commission: 15% Standard Selling Fee on the price including delivery, minimum £0.25 per item. Refund fee 20% of the
  order value (£0.25 to £5), dispute fee £6.50, chargeback £14. These fees are not modelled.
- Lower rates apply only to named categories: 7% Large Appliances and White Goods (fridges, freezers, washing machines,
  dryers, dishwashers, cookers, ovens and hobs), 7% consumer electronic devices, 8% consoles, 10% alcohol, 13% tools
  and DIY, 20% jewellery. No climate product is named, so every page uses 15%. The Dehumidifiers and Portable AC pages
  have a switch to test 7%, off by default.
- Professional tier features (badge, logo across the site, carousels, "Buy it Again") are from the same page.

Boost cost per acquisition, charged only on boosted sales: Light 5%, Plus 10%, Pro 15%, Max 20%, Ultra 30%
(channelx.world, August 2023; sellerbookkeeping.uk, 2026).

Seller tier is taken as shown only where the listing shows the Professional Seller badge. Every other tier is
estimated: no badge and at least 10k lifetime orders means Partner, otherwise Standard. The threshold is in the sidebar.

Reviews per lifetime order is the median over the sellers whose listing shows both counts. It is used to estimate
lifetime orders for sellers who show reviews but no order count. The calibration pools all five categories. In the
example data it comes to about 6.6 seller reviews per 100 orders, i.e. 1 review per about 15 orders, from 13 example
sellers. The real sample it copies had 12 such sellers: median 1 review per 14 orders, ranging from 1 per 12 to 1 per
20 (aggregates only, in `seller_growth/calibration_stats.json`). The median (middle value) is used so one odd seller
cannot skew it. With so few sellers, treat it as rough. Each page explains it, with one seller's orders, revenue and
LTV step by step, under "How orders, revenue and LTV are worked out" below the Revenue per seller table.

Observations from the calibration sample (aggregates, shown on each page):

- Heaters: about one in five listings out of stock at the start of the heating season.
- Fans: the newest review on reviewed listings dated July to September.
- Dehumidifiers: reviews clustered between September and January.
- Portable AC: most listings found as "portable air conditioner" were evaporative or USB coolers with no refrigerant,
  and none had a product review. The example includes price anomalies to reflect this.
- Air purifiers: one seller showed a Professional Seller badge.

## Units sold per month (estimate)

Shown in every product, seller and category table, always next to the average selling price per unit and GMV.
In plain steps:

1. Reviews on the listing x 50 (about 1 in 50 buyers leaves a review) = items sold to date.
2. Divide by the months the listing has been selling: the time since the first review where every review is listed,
   otherwise 24 months, or longer when older reviews are visible. This is sales in an average month.
3. Halve it if the newest review is over 12 months old.
4. Multiply by the season factor for the month (how busy the month is against an average month; table below).
5. OnBuy badges set a minimum: Bestseller 10, Hot 5, In demand 3; no badge and no reviews 0.5.
6. Out of stock, or a price that looks wrong: 0.
7. Where several sellers offer the product, the recommended offer wins 80% of its sales and the rest share the
   remainder.

Average selling price per unit = the delivered price (price plus delivery), averaged across offers by their share of
sales. GMV = units x average selling price. For a seller, average price = seller GMV / seller units. Commission is
units x the larger of 15% of the delivered price and £0.25.

With a 2% review rate, one review stands for about 50 orders, so units move in proportion to that assumption. Most
listings have few reviews, so the badge floors drive many of the estimates.

## Assumptions (all estimates, all in the sidebar)

| Assumption | Default | Used for |
|---|---|---|
| Product review rate | 1 in 50 buyers (2%) | units per month |
| Review window | 24 months, or the real span since the first review where all reviews are listed (minimum 6) | units per month |
| Badge floors, units per month | Bestseller 10, Hot 5, In demand 3, none 0.5 | demand where reviews are sparse |
| Share of sales won by the recommended offer | 80% | splitting units across offers |
| Season profile and strength | per page, strength 1.0 (0 turns it off) | season factor |
| Seller tenure | 36 months | account orders per month = lifetime orders / tenure |
| Average order value | £35 | account GMV (sellers sell outside climate control) |
| Boost adoption, level, boosted share, extra sales | per page, Plus, 30%, 50% | Boost revenue and the Boost play |
| Seller gross margin before fees | 35% | seller payback on an upgrade or Boost |
| Sales lift from upgrading | Partner 2%, Professional 2% (no public evidence; deliberately cautious) | upgrade action, only if the seller is better off after commission and the extra fee |
| Churn risk threshold | subscription above 5% of estimated monthly GMV, now or at list price | retention action |
| Chance an at-risk seller leaves without help | 30% | retention value at risk |
| Success rate | call 35%, message 15% | routing |
| Call cost | £45,000 fully loaded a year ÷ 1,600 productive hours × 1.4 hours per completed call = £39.38 (rough estimate, not OnCommerce data) | routing |
| Message cost | £1,500 journey build and upkeep ÷ 2,000 sellers reached + £0.05 to send = £0.80 (rough estimate, not OnCommerce data) | routing |
| Value horizon and margin | 12 months, 70% OnCommerce contribution margin, 3% monthly churn (9.90 months still trading) | routing and net contribution |
| Forecast | churn 3% a month, upgrades 2% a month, plays ramp over 3 months, no new sellers | forecast |
| LTV | monthly revenue x 70% margin / monthly churn | LTV per seller |

Season profiles (my judgement for the UK, not OnBuy data), January to December, averaging 1.0:

- heating: 2.0 1.6 1.1 0.6 0.3 0.15 0.15 0.15 0.45 1.3 2.1 2.1
- cooling: 0.2 0.2 0.3 0.5 1.2 2.4 3.0 2.4 0.8 0.4 0.3 0.3
- damp: 1.5 1.3 1.0 0.7 0.6 0.6 0.6 0.6 0.9 1.3 1.4 1.5
- flat: 1.0 every month

November is the snapshot month. The season factor also decides whether a listing is in season for the Boost play, so
Fans and Portable AC get no Boost plays in November.

## Settings, break-even and the decision log

All assumptions sit in one `Settings` object (`seller_growth/revenue.py`), built from the sidebar and passed to every
calculation; there are no global settings. Each control is tagged [Published] or [Assumption], and "Reset to
defaults" puts the category back to its defaults. Evidence in the seller view is tagged Published, Observed in
sample, Assumption or Model estimate.

A call is worth it when the platform revenue at stake a month is above the break-even:
(call cost − message cost) / (OnCommerce margin × months still trading × (call success − message success)). At the
defaults that is (£39.38 − £0.80) / (70% × 9.90 × (35% − 15%)) = £27.83 a month. (The earlier version used
(£120 − £2) / (12 × 20%) = £49.17, with placeholder costs and no margin or churn.) The page shows a grid of the
break-even for call costs of £20, £40 and £80 and success gaps of 10, 20 and 30 points, and one line per action:
"£X a month at stake, above the £Y tipping point, so call. Expected extra revenue £Z a month." (or below it, so send the
message). A "percentage point" is the plain difference between two percentages: a call that works 35% of the time
works 20 percentage points more often than a message that works 15% of the time.

The decision log has the columns timestamp, page, seller, product, play, at_stake, route, expected_mo, decision,
reason and settings_hash. settings_hash is the first 12 characters of a SHA-256 of the Settings, so two decisions
with the same hash were made under the same assumptions.

## The LLM

The rules decide the play, the £ at stake and the route; the person using the app decides approve or override. If an
LLM is configured (`OPENAI_API_KEY`), it only drafts the message text. It is given the topic, seller, product, the
reason in plain words, listing facts and the published fees. It is not given the route, the decision, the ranking or
any estimated £ figure, and only the subject, message and call brief are taken from its reply. Each draft is labelled
"Drafted by rules" or "Drafted by LLM". A test checks that plays and routes are identical with and without the LLM.

## Limits

- The example data is synthetic. It reproduces the shape of a small sample found through search, which favours
  listings that rank well. It says nothing about any real seller.
- Seller revenue uses each seller's lifetime orders across all categories, so it describes the whole account. Units,
  GMV and commission labelled with the category name cover that category only.
- Success rates, the upgrade sales lift, the chance an at-risk seller leaves and the call and message cost build-up
  are judgement. None has been tested against OnBuy results, so every value is a model estimate, not a result.
- OnBuy's own GMV, units, tiers, Boost spend and churn are not public.

## Earlier version

An earlier four-category version (duvets, air fryers, solar lights, hair straighteners) used real page data. That data
has been removed from the repository. Its hand-checkable tests (`seller_growth/test_calc.py`) still run and use no
marketplace data.
