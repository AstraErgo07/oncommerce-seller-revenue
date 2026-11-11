# Internal data: the listing CSV

The app runs on example data by default (`seller_growth/example_products.csv`, synthetic, made by
`tools/gen_example_data.py`). To run it on internal data, choose "Internal CSV" under Data in the sidebar and either
upload a CSV or give a file path on the server. The file is checked when it loads: missing required columns, or a
repeated `product_id`, show an error on the page instead of results. The upload is kept for the browser session only.

One row per product page. Lists inside a cell (the offer columns) are separated by `;`, in the same order in every
offer column, with the recommended offer first. Dates are `YYYY-MM-DD`. True or false columns accept true/false,
1/0 or yes/no. Ages of reviews are measured to the snapshot month in the settings (November 2026).

## Columns

| Column | Required | If missing | What it is | Feeds |
|---|---|---|---|---|
| `product_id` | yes |  | unique id of the product page | row key; links plays to products |
| `subcategory` | yes |  | product type; must be one of the subcategories a page lists (e.g. 'fan heaters') | which category page shows the row; season pattern |
| `title` | yes |  | product title | display only |
| `price` | yes |  | price of the recommended offer, £ incl. VAT | avg selling price, GMV, commission |
| `seller` | yes |  | seller of the recommended offer | seller tables, plays |
| `product_review_count` | yes |  | number of product reviews | units sold |
| `delivery_fee` | no | 0.0 | delivery charged on the recommended offer, £ | avg selling price, GMV, commission, delivery play |
| `offer_sellers` | no | blank | all sellers offering the product, ';'-separated, recommended first (blank = seller) | split of units across sellers, avg selling price |
| `offer_prices` | no | blank | their prices, ';'-separated, same order (blank = price) | avg selling price, price checks |
| `offers_count` | no | blank | number of offers (blank = count of offer_sellers) | listing checks |
| `offer_seller_reviews` | no | blank | seller review counts for each offer, ';'-separated | lifetime orders |
| `offer_professional` | no | blank | 1 where that offer shows a Professional Seller badge, ';'-separated | tier |
| `latest_review` | no | blank | date of the newest review, YYYY-MM-DD | halve units if old |
| `first_review` | no | blank | date of the first review where every review is listed, YYYY-MM-DD | months the listing has been selling |
| `oldest_visible_review` | no | blank | oldest review date shown when not every review is listed | months selling |
| `badge` | no | blank | OnBuy badge: Bestseller, Hot, In demand or blank | minimum units |
| `seller_professional` | no | False | recommended seller shows the Professional Seller badge | tier, subscription |
| `seller_orders_k` | no | blank | seller's lifetime orders in thousands, where shown | lifetime orders, tier, revenue |
| `seller_review_count` | no | blank | seller's review count | lifetime orders when no order count is shown |
| `flag_out_of_stock` | no | False | out of stock | units = 0, out-of-stock play |
| `flag_price_anomaly` | no | False | price looks wrong for the product | units = 0, price play |
| `flag_duplicate_page` | no | False | same product on a separate page | duplicate play, quality score |
| `flag_no_brand` | no | False | no brand on the listing | quality score |
| `flag_placeholder_ean` | no | False | placeholder barcode | quality score |
| `flag_thin_content` | no | False | thin or templated description | quality score |
| `flag_overseas_dispatch` | no | False | dispatched from outside the UK | quality issues |
| `flag_reviews_from_former_seller` | no | False | reviews earned by a seller no longer listed | quality score |
| `max_qty_selectable` | no | blank | most a buyer can add to the basket (a stock signal) | quality score |
| `delivery_max_days` | no | blank | latest promised delivery, days | delivery play, quality score |
| `listing_notes` | no | blank | free-text notes | shown in evidence |
| `brand` | no | blank | brand | display only |
| `url` | no | blank | page address | link in the play detail |

The checks live in `seller_growth/data_schema.py`.

## Which subcategories each page reads

`subcategory` must use these values (lower case); rows with other values are not shown on any page.

| Page | subcategory values |
|---|---|
| Heaters | fan heaters, oil filled radiators, convector heaters |
| Fans | tower fans, pedestal fans, desk fans |
| Dehumidifiers | dehumidifiers |
| Portable AC | air conditioners |
| Air Purifiers | air purifiers |

## Which formulas each column feeds

- Units a month: `product_review_count`, `latest_review`, `first_review` or `oldest_visible_review`, `badge`,
  `flag_out_of_stock`, `flag_price_anomaly`, `offer_sellers` (and the season pattern from `subcategory`).
  Units = reviews × (1 ÷ review rate) ÷ months selling × season factor, halved if the newest review is old, at least
  the badge floor, 0 if out of stock or mispriced.
- Average selling price per unit and GMV: `price`, `delivery_fee`, `offer_prices`, `offer_sellers`.
  GMV = units × average selling price per unit.
- Commission: GMV × commission rate, at least the minimum fee per item.
- Seller tier and subscription: `seller_professional`, `offer_professional`, `seller_orders_k`.
- Seller account revenue: lifetime orders from `seller_orders_k`, or `seller_review_count` × orders per seller review;
  then lifetime orders ÷ tenure months × average order value = account GMV a month.
- Listing plays and quality score: the `flag_*` columns, `delivery_fee`, `delivery_max_days`, `max_qty_selectable`,
  `offers_count`, `offer_prices`.
- Routing (call or message) uses only the £ at stake from the play and the settings; no column feeds it directly.
