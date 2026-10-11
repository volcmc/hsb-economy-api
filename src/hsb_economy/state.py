"""Pipeline state carried between runs: recorded sales, sales feed cursor and price history.

The workflow restores it from the Actions cache. If the cache was evicted, the copy published alongside
the API is used instead so history survives; only a genuine 404 (first ever run) starts from scratch.
"""

import gzip
import json
import logging
from pathlib import Path

import httpx

from . import config

log = logging.getLogger(__name__)

STATE_VERSION = 1
STATE_FILE = "state.json.gz"


def empty() -> dict:
    return {"version": STATE_VERSION, "sales": {}, "history": {"bazaar": {}, "auctions": {}}}


def decode(raw: bytes) -> dict:
    state = json.loads(gzip.decompress(raw))
    if state.get("version") != STATE_VERSION:
        raise ValueError(f"Unsupported state version {state.get('version')}")
    return state


def load(path: Path, public_url: str | None) -> dict:
    if path.exists():
        log.info("Loading state from %s", path)
        return decode(path.read_bytes())
    if not public_url:
        log.warning("No cached state and no public URL; starting fresh")
        return empty()

    url = f"{public_url.rstrip('/')}/{config.API_VERSION}/{STATE_FILE}"
    log.info("No cached state; recovering from %s", url)
    response = httpx.get(url, timeout=config.REQUEST_TIMEOUT, follow_redirects=True)
    if response.status_code == 404:
        log.warning("No published state yet; starting fresh")
        return empty()
    # Any other failure must abort the run rather than publish over existing history.
    response.raise_for_status()
    return decode(response.content)


def encode(state: dict) -> bytes:
    return gzip.compress(json.dumps(state, separators=(",", ":")).encode(), compresslevel=6)


def save(path: Path, state: dict) -> bytes:
    raw = encode(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw
