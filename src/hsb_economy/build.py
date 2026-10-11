"""Fetch everything, update state, and write the static site.

The run is all-or-nothing: if any source fails, nothing is written and the previously deployed site
stays live, so consumers see slightly stale data instead of partial data.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import config, hypixel, state
from .history import History
from .market import summarize_auctions, summarize_bazaar
from .names import display_name, resource_names
from .sales import Sales

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SalesFeed:
    url: str
    token: str


@dataclass(frozen=True)
class SalesBatch:
    responses: list[dict]
    # "feed" when the Worker supplied current data, otherwise "direct".
    source: str
    # Newest lastUpdated (ms) read from the feed, if any; only feed data may advance the cursor.
    feed_cursor: int | None


async def fetch_sales(client: httpx.AsyncClient, feed: SalesFeed | None, cursor: int) -> SalesBatch:
    """auctions_ended responses since ``cursor`` from the sales Worker.

    If the feed is unreachable or has nothing recent (e.g. its cron stopped), one direct sample keeps
    sale stats moving; the Worker retains 36 hours of responses, so a later run backfills any gap.
    """
    responses: list[dict] = []
    if feed:
        try:
            responses = await hypixel.fetch_sales_feed(client, feed.url, feed.token, cursor)
        except (httpx.HTTPError, ValueError, KeyError) as error:
            log.error("Sales feed failed (%r); sampling auctions_ended directly instead", error)
        else:
            latest = max((r["lastUpdated"] for r in responses), default=cursor)
            if time.time() * 1000 - latest <= config.SALES_FEED_MAX_AGE_SECONDS * 1000:
                return SalesBatch(responses, "feed", latest)
            log.error("Sales feed has nothing recent; is the Worker cron running? Sampling directly too")
    feed_cursor = max((r["lastUpdated"] for r in responses), default=None)
    return SalesBatch([*responses, await hypixel.fetch_auctions_ended(client)], "direct", feed_cursor)


async def fetch_all(
    feed: SalesFeed | None, cursor: int
) -> tuple[dict, tuple[int, list[dict]], SalesBatch, dict]:
    async with hypixel.new_client() as client:
        return await asyncio.gather(
            hypixel.fetch_bazaar(client),
            hypixel.fetch_auction_snapshot(client),
            fetch_sales(client, feed, cursor),
            hypixel.fetch_item_resource(client),
        )


def file_name(key: str) -> str:
    # Some legacy bazaar ids contain ':' (e.g. INK_SACK:3), which is not a portable file name character.
    return key.replace(":", "-") + ".json"


def trend(history: History, key: str, metric: str, now: int, current: float | None) -> dict:
    result = {}
    for label, ago in (("1d", config.DAY), ("7d", 7 * config.DAY)):
        change = history.change(key, metric, now, ago, current)
        result[f"{metric}_{label}"] = round(change, 4) if change is not None else None
    return result


def update_last_seen(last_seen: dict[str, list], auctions: dict, now: int) -> None:
    """Remember each listed item's lowest BIN as ``[at, lbin]``; forget items unlisted for too long."""
    for key, item in auctions.items():
        if item["lbin"] is not None:
            last_seen[key] = [now, item["lbin"]]
    for key in [key for key, (at, _) in last_seen.items() if at < now - config.LAST_SEEN_RETENTION]:
        del last_seen[key]


def build(out: Path, state_path: Path, public_url: str | None, feed: SalesFeed | None) -> None:
    current = state.load(state_path, public_url)
    cursor = current.get("feed_cursor", 0)
    bazaar_raw, (auctions_updated, auctions_raw), batch, item_resource = asyncio.run(fetch_all(feed, cursor))
    names = resource_names(item_resource)
    sales_source = batch.source
    now = int(time.time())

    sales = Sales(current["sales"])
    new_sales = sum(sales.add(response) for response in batch.responses)
    sales.prune(now)
    if batch.feed_cursor is not None:
        current["feed_cursor"] = batch.feed_cursor

    bazaar_history = History(current["history"]["bazaar"])
    bazaar = summarize_bazaar(bazaar_raw["products"])
    for product_id, product in bazaar.items():
        bazaar_history.record(product_id, "buy", now, product["buy"])
        bazaar_history.record(product_id, "sell", now, product["sell"])
    bazaar_history.prune(now)
    for product_id, product in bazaar.items():
        product["trend"] = trend(bazaar_history, product_id, "buy", now, product["buy"]) | trend(
            bazaar_history, product_id, "sell", now, product["sell"]
        )
    bazaar = {key: {"name": display_name(key, names), **product} for key, product in bazaar.items()}

    auction_history = History(current["history"]["auctions"])
    auctions = summarize_auctions(auctions_raw)
    for key, item in auctions.items():
        auction_history.record(key, "lbin", now, item["lbin"])
        auction_history.record(key, "listings", now, item["listings"])
    auction_history.prune(now)
    last_seen = current.setdefault("last_seen", {})
    update_last_seen(last_seen, auctions, now)
    # Unlisted items stay visible while they have recent sales or a remembered lowest BIN.
    for key in (sales.samples.keys() | last_seen.keys()) - auctions.keys():
        auctions[key] = {
            "lbin": None,
            "lbin2": None,
            "listings": 0,
            "plain": {"lbin": None, "listings": 0},
            "_upgraded": False,
        }
    observed_day = sales.observed_seconds(now, config.DAY)
    for key, item in auctions.items():
        if item["lbin"] is None and key in last_seen:
            at, lbin = last_seen[key]
            item["last_seen"] = {"lbin": lbin, "at": at}
        item["trend"] = trend(auction_history, key, "lbin", now, item["lbin"])
        item["sales"] = sales.stats(key, now, observed_day)
        # Plain-copy figures are only published where upgraded copies exist; otherwise they'd repeat the
        # overall ones.
        plain = item.pop("plain")
        if item.pop("_upgraded") or sales.has_upgraded(key):
            item["plain"] = plain | {"sales": sales.plain_stats(key, now)}
    auctions = {key: {"name": display_name(key, names), **item} for key, item in auctions.items()}

    prices = {key: item["lbin"] for key, item in auctions.items() if item["lbin"] is not None}
    for product_id, product in bazaar.items():
        if product["buy"] is not None:
            prices[product_id] = min(product["buy"], prices.get(product_id, product["buy"]))

    current["sales"] = sales.to_dict()
    current["history"] = {"bazaar": bazaar_history.data, "auctions": auction_history.data}
    raw_state = state.save(state_path, current)

    meta = {
        "generated_at": now,
        "sources": {
            "bazaar_updated_at": bazaar_raw["lastUpdated"] // 1000,
            "auctions_updated_at": auctions_updated // 1000,
        },
        "counts": {
            "bazaar_products": len(bazaar),
            "auction_items": len(auctions),
            "active_auctions": len(auctions_raw),
            "new_sales": new_sales,
        },
        "sales_source": sales_source,
        "sales_coverage_1d": round(observed_day / config.DAY, 4),
    }

    root = out / config.API_VERSION
    write_json(root / "meta.json", meta)
    write_json(root / "bazaar.json", {"updated_at": meta["sources"]["bazaar_updated_at"], "products": bazaar})
    write_json(
        root / "auctions.json", {"updated_at": meta["sources"]["auctions_updated_at"], "items": auctions}
    )
    write_json(root / "prices.json", {"updated_at": now, "prices": prices})
    for kind, history in (("bazaar", bazaar_history), ("auctions", auction_history)):
        for key in history.data:
            write_json(root / "history" / kind / file_name(key), {"key": key, **history.export(key)})
    (root / state.STATE_FILE).write_bytes(raw_state)
    log.info(
        "Built %d bazaar products, %d auction items, %d new sales (%s)",
        len(bazaar),
        len(auctions),
        new_sales,
        sales_source,
    )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
