import asyncio
import time

import httpx

from hsb_economy import config
from hsb_economy.build import SalesBatch, SalesFeed, fetch_sales

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
