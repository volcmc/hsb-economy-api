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


async def fetch_auction_snapshot(client: httpx.AsyncClient) -> tuple[int, list[dict]]:
    """Fetch every active-auction page from a single Hypixel update.

    :return: (lastUpdated in ms, all auctions)
    """
    for attempt in range(config.SNAPSHOT_ATTEMPTS):
        first = await get_json(client, config.AUCTIONS_URL, {"page": 0})
        updated = first["lastUpdated"]
        rest = await asyncio.gather(
            *(get_json(client, config.AUCTIONS_URL, {"page": page}) for page in range(1, first["totalPages"]))
        )
        if all(page["lastUpdated"] == updated for page in rest):
            auctions = [auction for page in (first, *rest) for auction in page["auctions"]]
            log.info("Fetched %d auctions across %d pages", len(auctions), first["totalPages"])
            return updated, auctions
        log.warning("Auction pages changed mid-fetch (attempt %d), refetching", attempt + 1)
    raise HypixelError(f"No consistent auction snapshot after {config.SNAPSHOT_ATTEMPTS} attempts")
