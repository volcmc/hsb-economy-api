# HSB Economy API

Static JSON with Hypixel SkyBlock auction and bazaar prices, rebuilt every ~10 minutes by GitHub Actions and
served from GitHub Pages. There is no server: fetch the files directly.

```
https://volcmc.github.io/hsb-economy-api/v1/<file>
```

Responses are CORS-enabled and CDN-cached for up to 10 minutes. GitHub's scheduler is best-effort, so
expect data to be 10–25 minutes old; check `meta.json` or each file's `updated_at` for the exact age.
All timestamps are Unix seconds; all prices are coins.

## Endpoints

| File | Contents |
| --- | --- |
| `v1/prices.json` | Flat `{key: price}`: cheapest current way to buy each item (bazaar instant buy or lowest BIN). |
| `v1/bazaar.json` | Every bazaar product with order-book prices, volumes and trends. |
| `v1/auctions.json` | Every item on the auction house with lowest BIN, listings, sale stats and trends. |
| `v1/history/bazaar/<id>.json` | Hourly (7 days) and daily (1 year) instant buy/sell history. |
| `v1/history/auctions/<key>.json` | Hourly and daily lowest BIN and listing-count history. |
| `v1/meta.json` | Build time, source timestamps, counts, sales source and coverage. |

In history file names, `:` is replaced with `-` (e.g. `INK_SACK:3` → `INK_SACK-3.json`).

## Item keys

Keys are Hypixel item ids, except where one id covers items with very different values:

| Item | Key | Example |
| --- | --- | --- |
| Pets | `PET.<TYPE>.<TIER>` | `PET.ENDER_DRAGON.LEGENDARY` |
| Runes | `RUNE.<TYPE>.<LEVEL>`, `UNIQUE_RUNE.<TYPE>.<LEVEL>` | `RUNE.MUSIC.3` |
| Single-enchant books | `ENCHANTMENT_<NAME>_<LEVEL>` (same as the bazaar id) | `ENCHANTMENT_ULTIMATE_WISE_5` |
| Potions | `POTION.<EFFECT>.<LEVEL>` | `POTION.ABSORPTION.5` |
| New Year Cakes | `NEW_YEAR_CAKE.<YEAR>` | `NEW_YEAR_CAKE.515` |

Multi-enchant books are not priced.

## Schemas

### `bazaar.json`

```jsonc
{
  "updated_at": 1791701442,
  "products": {
    "ENCHANTED_DIAMOND": {
      "buy": 1317.6,          // instant buy: cheapest sell offer
      "sell": 1250.2,         // instant sell: highest buy order
      "buy_avg": 1326.02,     // Hypixel quick_status averages over the top of each book
      "sell_avg": 1250.09,
      "buy_volume": 2562761,  // remaining fields are Hypixel's quick_status, unchanged
      "sell_volume": 3334854,
      "buy_moving_week": 4087360,
      "sell_moving_week": 20779766,
      "buy_orders": 400,
      "sell_orders": 101,
      "trend": { "buy_1d": 0.012, "buy_7d": -0.03, "sell_1d": 0.01, "sell_7d": null }  // relative change
    }
  }
}
```

### `auctions.json`

```jsonc
{
  "updated_at": 1791701406,
  "items": {
    "PET.ENDER_DRAGON.LEGENDARY": {
      "lbin": 448999999,        // lowest BIN right now (null if none listed)
      "lbin2": 449000000,       // second lowest, a sanity check against a single odd listing
      "listings": 35,           // active BIN listings
      "levels": { "1": 448999999, "100": 479899999 },  // pets only: lowest BIN at level 1/100/200
      "trend": { "lbin_1d": -0.02, "lbin_7d": 0.05 },
      "sales": {                // null if no sales in the last 7 days
        "count_1d": 4, "median_1d": 452000000,
        "count_7d": 31, "median_7d": 455000000, "p25_7d": 449000000, "p75_7d": 462000000,
        "est_volume_1d": 19.8,  // count_1d scaled up for any coverage gaps; null below 1 hour of coverage
        "levels": { "100": { "count_7d": 12, "median_7d": 481000000 } }
      }
    }
  }
}
```

**About sale stats:** Hypixel's `auctions_ended` endpoint only exposes the last 60 seconds of sales, so a
small Cloudflare Worker (`worker/`) captures it every minute and the pipeline processes every captured
response. `sales_coverage_1d` in `meta.json` is the share of the last day actually covered (≈1.0 when the
feed is healthy); `sales_source` is `feed`, or `direct` when the feed was unreachable and a single 60-second
sample was used instead. Only BIN sales are counted.

### History files

```jsonc
{
  "key": "HYPERION",
  "lbin": {
    "hourly": { "t": [1791698400, ...], "v": [443000000.0, ...] },  // bucket start, mean of observations
    "daily":  { "t": [1791676800, ...], "v": [...] }
  },
  "listings": { "hourly": { ... }, "daily": { ... } }
}
```

Bazaar history files have `buy` and `sell` instead of `lbin` and `listings`.

## How it works

`worker/` is a Cloudflare Worker that stores every `auctions_ended` response in D1 (kept 36 hours) and
serves them to the pipeline behind a bearer token.

`.github/workflows/update.yml` runs every 10 minutes:

1. Fetches the bazaar, every active auction page from a single Hypixel update (pages are refetched if
   Hypixel regenerates them mid-fetch), and all sales the Worker captured since the last run. If the
   Worker is unreachable it samples `auctions_ended` directly; the Worker's backlog fills the gap next run.
2. Decodes each BIN listing's NBT to its item key and computes lowest BINs.
3. Updates pipeline state (sales, feed cursor and price history), kept in the Actions cache. If the cache is
   ever lost, the copy published at `v1/state.json.gz` is used, so history survives.
4. Writes the JSON files and deploys them to GitHub Pages.

A run either publishes everything or nothing: if any source fails, the previous deployment stays live.

## Development

Requires Python 3.12+.

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"   # .venv\Scripts\pip on Windows
pytest
ruff check . && ruff format --check .
python -m hsb_economy --out site --state state/state.json.gz   # live build into ./site
```

Set `HSB_SALES_URL` and `HSB_SALES_TOKEN` to build from the sales feed; without them sales are sampled directly.

### Sales feed Worker

Requires Node 22+ and a Cloudflare account (the free plan is enough).

```sh
cd worker
npm ci
npm run check                    # generated types are current + type-check
npm run dev                      # local Worker with local D1; trigger the cron at /__scheduled
npm run deploy                   # apply D1 migrations, then deploy
```

The Worker needs a `SALES_TOKEN` secret (`npx wrangler secret put SALES_TOKEN`). The update workflow reads the
same value from the `HSB_SALES_TOKEN` repository secret and the Worker URL from the `HSB_SALES_URL`
repository variable.

## Previous versions

v1 and v2 (a Flask API on PythonAnywhere) are preserved under the `archive/v1` and `archive/v2` tags.
