import asyncio
import json
import logging
import random

import httpx

from . import config

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HypixelError(RuntimeError):
    pass


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=config.REQUEST_TIMEOUT,
        headers={"User-Agent": "hsb-economy-api (+https://github.com/volcmc/hsb-economy-api)"},
        limits=httpx.Limits(max_connections=config.PAGE_CONCURRENCY),
    )


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
    """GET a Hypixel endpoint, retrying transient failures including truncated bodies."""
    last_error: Exception | None = None
    for attempt in range(config.REQUEST_RETRIES):
        if attempt:
            await asyncio.sleep(2**attempt + random.random())
        try:
            response = await client.get(url, params=params)
            if response.status_code in RETRY_STATUSES:
                last_error = HypixelError(f"{url} {params} returned HTTP {response.status_code}")
                log.warning("%s (attempt %d)", last_error, attempt + 1)
                continue
            response.raise_for_status()
            # Hypixel occasionally ends the body early with a 200; that surfaces as invalid JSON.
            data = response.json()
        except (httpx.TransportError, json.JSONDecodeError) as error:
            last_error = error
            log.warning("%s %s failed: %r (attempt %d)", url, params, error, attempt + 1)
            continue
        if not data.get("success", False):
            raise HypixelError(f"{url} {params} responded without success: {data.get('cause')}")
        return data
    raise HypixelError(f"{url} {params} failed after {config.REQUEST_RETRIES} attempts") from last_error


async def fetch_bazaar(client: httpx.AsyncClient) -> dict:
    return await get_json(client, config.BAZAAR_URL)


async def fetch_auctions_ended(client: httpx.AsyncClient) -> dict:
    return await get_json(client, config.AUCTIONS_ENDED_URL)


async def fetch_sales_feed(client: httpx.AsyncClient, url: str, token: str, after: int) -> list[dict]:
    """Every auctions_ended response the sales Worker captured with lastUpdated > ``after`` (ms)."""
    responses: list[dict] = []
    while True:
        response = await client.get(
            f"{url.rstrip('/')}/ended",
            params={"after": after, "limit": config.SALES_FEED_PAGE_SIZE},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        page = response.json()
        responses.extend(page["responses"])
        if not page["more"]:
            return responses
        after = page["responses"][-1]["lastUpdated"]


async def fetch_pages(client: httpx.AsyncClient, pages: list[int]) -> dict[int, dict]:
    responses = await asyncio.gather(
        *(get_json(client, config.AUCTIONS_URL, {"page": page}) for page in pages)
    )
    return dict(zip(pages, responses, strict=True))


def lagging_pages(pages: dict[int, dict]) -> tuple[dict, list[int]]:
    """The newest page, and every page index missing or behind it (dropping pages past its totalPages)."""
    newest = max(pages.values(), key=lambda page: page["lastUpdated"])
    for index in [index for index in pages if index >= newest["totalPages"]]:
        del pages[index]
    behind = [
        index
        for index in range(newest["totalPages"])
        if index not in pages or pages[index]["lastUpdated"] != newest["lastUpdated"]
    ]
    return newest, behind


async def fetch_auction_snapshot(client: httpx.AsyncClient) -> tuple[int, list[dict]]:
    """Fetch every active-auction page, converging on Hypixel's newest update.

    Pages can come from different updates, either because Hypixel regenerated them mid-fetch or because
    a CDN copy lags behind. Only the lagging pages are refetched. If they never converge, the mixed
    snapshot is used: pages a minute or two old barely move lowest BINs, while failing would stall
    every dataset.

    :return: (lastUpdated in ms of the newest page, all auctions)
    """
    first = await get_json(client, config.AUCTIONS_URL, {"page": 0})
    pages = {0: first} | await fetch_pages(client, list(range(1, first["totalPages"])))
    for attempt in range(config.SNAPSHOT_ATTEMPTS + 1):
        newest, behind = lagging_pages(pages)
        if not behind or attempt == config.SNAPSHOT_ATTEMPTS:
            break
        log.warning(
            "%d auction pages behind the newest update (attempt %d); refetching", len(behind), attempt + 1
        )
        await asyncio.sleep(config.SNAPSHOT_RETRY_DELAY)
        pages |= await fetch_pages(client, behind)
    if behind:
        versions = len({page["lastUpdated"] for page in pages.values()})
        log.warning("Auction pages never converged; using a snapshot spanning %d updates", versions)

    # A mixed snapshot can list an auction twice when it moved between pages across updates.
    auctions = list({a["uuid"]: a for index in sorted(pages) for a in pages[index]["auctions"]}.values())
    log.info("Fetched %d auctions across %d pages", len(auctions), len(pages))
    return newest["lastUpdated"], auctions
