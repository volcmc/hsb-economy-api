import asyncio
import json
import time

import httpx

from hsb_economy import config
from hsb_economy.build import SalesBatch, SalesFeed, fetch_sales, update_last_seen

FEED = SalesFeed("https://feed.test/", "secret")
NOW_MS = int(time.time() * 1000)
DIRECT = {"success": True, "lastUpdated": NOW_MS, "auctions": []}


def run(handler, feed=FEED, cursor=0):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_sales(client, feed, cursor)

    return asyncio.run(go())


def direct_or(feed_handler):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "feed.test":
            return feed_handler(request)
        assert str(request.url) == config.AUCTIONS_ENDED_URL
        return httpx.Response(200, json=DIRECT)

    return handler


def test_feed_is_paged_from_the_cursor():
    first, second, third = NOW_MS - 120_000, NOW_MS - 60_000, NOW_MS
    pages = {
        5: {"more": True, "responses": [{"lastUpdated": first}, {"lastUpdated": second}]},
        second: {"more": False, "responses": [{"lastUpdated": third}]},
    }
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ended"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.url.params["limit"] == str(config.SALES_FEED_PAGE_SIZE)
        after = int(request.url.params["after"])
        seen.append(after)
        return httpx.Response(200, json=pages[after])

    batch = run(handler, cursor=5)
    assert batch.source == "feed"
    assert [r["lastUpdated"] for r in batch.responses] == [first, second, third]
    assert batch.feed_cursor == third
    assert seen == [5, second]


def test_falls_back_to_direct_sample_when_feed_fails():
    batch = run(direct_or(lambda request: httpx.Response(503)), cursor=5)
    assert batch == SalesBatch([DIRECT], "direct", None)


def test_stale_feed_is_used_and_topped_up_with_a_direct_sample():
    stale = NOW_MS - (config.SALES_FEED_MAX_AGE_SECONDS + 60) * 1000
    feed_page = {"more": False, "responses": [{"lastUpdated": stale}]}
    batch = run(direct_or(lambda request: httpx.Response(200, json=feed_page)))
    assert batch == SalesBatch([{"lastUpdated": stale}, DIRECT], "direct", stale)


def test_empty_feed_counts_as_stale():
    batch = run(
        direct_or(lambda request: httpx.Response(200, json={"more": False, "responses": []})), cursor=5
    )
    assert batch == SalesBatch([DIRECT], "direct", None)


def test_samples_directly_without_a_feed():
    assert run(lambda request: httpx.Response(200, json=DIRECT), feed=None) == SalesBatch(
        [DIRECT], "direct", None
    )


def test_last_seen_remembers_listed_items_and_expires():
    now = 1_800_000_000
    last_seen = {"OLD": [now - config.LAST_SEEN_RETENTION - 1, 5], "KEEP": [now - 3_600, 7]}
    update_last_seen(last_seen, {"A": {"lbin": 10}, "KEEP": {"lbin": None}}, now)
    assert last_seen == {"A": [now, 10], "KEEP": [now - 3_600, 7]}


def test_build_end_to_end(tmp_path, monkeypatch):
    """Two runs: an item listed in the first and sold out in the second keeps its last lowest BIN."""
    from conftest import item_bytes, plain
    from nbtlib import Int, String

    from hsb_economy import build as build_module

    starred = item_bytes({"id": String("HYPERION"), "upgrade_level": Int(5)})
    listings = {
        "first": [
            {"uuid": "1", "bin": True, "item_bytes": plain("KAT_FLOWER", count=4), "starting_bid": 2_000},
            {"uuid": "2", "bin": True, "item_bytes": starred, "starting_bid": 400},
            {"uuid": "3", "bin": True, "item_bytes": plain("HYPERION"), "starting_bid": 500},
        ]
    }
    product = {
        "buy_summary": [{"pricePerUnit": 10.0}],
        "sell_summary": [{"pricePerUnit": 9.0}],
        "quick_status": {
            "buyPrice": 10,
            "sellPrice": 9,
            "buyVolume": 1,
            "sellVolume": 1,
            "buyMovingWeek": 1,
            "sellMovingWeek": 1,
            "buyOrders": 1,
            "sellOrders": 1,
        },
    }
    run = {"name": "first"}

    async def fake_fetch_all(feed, cursor):
        now_ms = int(time.time() * 1000)
        return (
            {"lastUpdated": now_ms, "products": {"INK_SACK:3": product}},
            (now_ms, listings.get(run["name"], [])),
            SalesBatch([{"lastUpdated": now_ms, "auctions": []}], "direct", None),
            {"items": [{"id": "INK_SACK:3", "name": "Cocoa Beans"}]},
        )

    monkeypatch.setattr(build_module, "fetch_all", fake_fetch_all)
    out, state_path = tmp_path / "site", tmp_path / "state.json.gz"

    build_module.build(out, state_path, None, None)
    auctions = json.loads((out / "v1" / "auctions.json").read_text())["items"]
    assert auctions["KAT_FLOWER"]["lbin"] == 500
    assert auctions["KAT_FLOWER"]["name"] == "Kat Flower"
    # No upgraded copies were listed or sold, so there is no separate plain-copy block.
    assert "plain" not in auctions["KAT_FLOWER"] and "_upgraded" not in auctions["KAT_FLOWER"]
    assert auctions["HYPERION"]["lbin"] == 400
    assert auctions["HYPERION"]["plain"] == {"lbin": 500, "listings": 1, "sales": None}
    bazaar = json.loads((out / "v1" / "bazaar.json").read_text())["products"]
    assert bazaar["INK_SACK:3"]["name"] == "Cocoa Beans"
    assert (out / "v1" / "history" / "bazaar" / "INK_SACK-3.json").exists()

    run["name"] = "second"
    build_module.build(out, state_path, None, None)
    item = json.loads((out / "v1" / "auctions.json").read_text())["items"]["KAT_FLOWER"]
    assert item["lbin"] is None and item["listings"] == 0
    assert item["last_seen"]["lbin"] == 500
    assert item["trend"] == {"lbin_1d": None, "lbin_7d": None}
    assert "KAT_FLOWER" not in json.loads((out / "v1" / "prices.json").read_text())["prices"]
