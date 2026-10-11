import asyncio
from collections import Counter

import httpx
import pytest

from hsb_economy import config, hypixel


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOT_RETRY_DELAY", 0)


def page(updated: int, total: int, *uuids: str) -> dict:
    auctions = [{"uuid": uuid} for uuid in uuids]
    return {"success": True, "lastUpdated": updated, "totalPages": total, "auctions": auctions}


def snapshot(serve):
    """Run fetch_auction_snapshot where ``serve(page, nth_request_for_that_page)`` builds each response."""
    requests = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        index = int(request.url.params["page"])
        requests[index] += 1
        return httpx.Response(200, json=serve(index, requests[index]))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await hypixel.fetch_auction_snapshot(client)

    return asyncio.run(go()), requests


def test_consistent_pages_are_fetched_once():
    (updated, auctions), requests = snapshot(lambda i, n: page(100, 3, f"a{i}"))
    assert updated == 100
    assert [a["uuid"] for a in auctions] == ["a0", "a1", "a2"]
    assert requests == {0: 1, 1: 1, 2: 1}


def test_only_lagging_pages_are_refetched():
    # Page 1 is served from a stale copy until its second request.
    def serve(i, n):
        return page(90 if i == 1 and n == 1 else 100, 3, f"a{i}")

    (updated, auctions), requests = snapshot(serve)
    assert updated == 100
    assert len(auctions) == 3
    assert requests == {0: 1, 1: 2, 2: 1}


def test_converges_on_an_update_that_lands_mid_fetch():
    # Page 0 was fetched before Hypixel regenerated; the rest come from the newer update.
    def serve(i, n):
        return page(200 if i or n > 1 else 100, 2, f"a{i}")

    (updated, _), requests = snapshot(serve)
    assert updated == 200
    assert requests == {0: 2, 1: 1}


def test_uses_mixed_snapshot_when_pages_never_converge():
    # The same auction appears on both pages because it moved between updates.
    def serve(i, n):
        return page(90, 2, "moved", "b") if i == 1 else page(100, 2, "a", "moved")

    (updated, auctions), requests = snapshot(serve)
    assert updated == 100
    assert sorted(a["uuid"] for a in auctions) == ["a", "b", "moved"]
    assert requests[1] == 1 + config.SNAPSHOT_ATTEMPTS


def test_pages_beyond_the_newest_total_are_dropped():
    # The newest update shrank to two pages, so stale page 2 no longer exists.
    def serve(i, n):
        return page(90, 3, "stale") if i == 2 else page(100, 2, f"a{i}")

    (updated, auctions), _ = snapshot(serve)
    assert updated == 100
    assert [a["uuid"] for a in auctions] == ["a0", "a1"]
