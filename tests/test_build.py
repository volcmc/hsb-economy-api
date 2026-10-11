import asyncio

import httpx

from hsb_economy import config
from hsb_economy.build import SalesFeed, fetch_sales

FEED = SalesFeed("https://feed.test/", "secret")
DIRECT = {"success": True, "lastUpdated": 99, "auctions": []}


def run(handler, feed=FEED, cursor=0):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_sales(client, feed, cursor)

    return asyncio.run(go())


def test_feed_is_paged_from_the_cursor():
    pages = {
        5: {"more": True, "responses": [{"lastUpdated": 6}, {"lastUpdated": 7}]},
        7: {"more": False, "responses": [{"lastUpdated": 8}]},
    }
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ended"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.url.params["limit"] == str(config.SALES_FEED_PAGE_SIZE)
        after = int(request.url.params["after"])
        seen.append(after)
        return httpx.Response(200, json=pages[after])

    responses, source = run(handler, cursor=5)
    assert source == "feed"
    assert [r["lastUpdated"] for r in responses] == [6, 7, 8]
    assert seen == [5, 7]


def test_falls_back_to_direct_sample_when_feed_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "feed.test":
            return httpx.Response(503)
        assert str(request.url) == config.AUCTIONS_ENDED_URL
        return httpx.Response(200, json=DIRECT)

    assert run(handler) == ([DIRECT], "direct")


def test_samples_directly_without_a_feed():
    assert run(lambda request: httpx.Response(200, json=DIRECT), feed=None) == ([DIRECT], "direct")
