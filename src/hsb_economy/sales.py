"""Rolling record of BIN sales sampled from ``auctions_ended``.

That endpoint only exposes the last 60 seconds, so a scheduled run sees a fraction of all sales.
Prices are still an unbiased sample, and ``coverage`` (seconds of sales actually observed) lets us
scale sample counts up to an estimated daily volume.
"""

import logging
import statistics
from collections import defaultdict

from . import config
from .items import parse_item

log = logging.getLogger(__name__)


class Sales:
    def __init__(self, data: dict | None = None):
        data = data or {}
        # key -> [[timestamp, price, pet_level | None], ...]
        self.samples: dict[str, list[list]] = defaultdict(list, data.get("samples", {}))
        self.seen: list[str] = data.get("seen", [])
        # [[run_timestamp, seconds_observed], ...]
        self.coverage: list[list[int]] = data.get("coverage", [])

    def to_dict(self) -> dict:
        return {"samples": dict(self.samples), "seen": self.seen, "coverage": self.coverage}

    def add(self, ended: dict, now: int) -> int:
        """Record new BIN sales from an ``auctions_ended`` response; returns how many were new."""
        seen = set(self.seen)
        added = 0
        for auction in ended["auctions"]:
            if not auction["bin"] or auction["auction_id"] in seen:
                continue
            seen.add(auction["auction_id"])
            self.seen.append(auction["auction_id"])
            try:
                item = parse_item(auction["item_bytes"])
            except Exception:
                log.warning("Skipped sold auction %s with undecodable item data", auction["auction_id"])
                continue
            if item is None:
                continue
            self.samples[item.key].append([auction["timestamp"] // 1000, auction["price"], item.pet_level])
            added += 1
        del self.seen[: -config.SEEN_SALE_IDS_LIMIT]

        observed = config.ENDED_WINDOW_SECONDS
        if self.coverage:
            observed = min(observed, now - self.coverage[-1][0])
        self.coverage.append([now, max(observed, 0)])
        return added

    def prune(self, now: int) -> None:
        cutoff = now - config.SALES_RETENTION
        for key in list(self.samples):
            kept = [s for s in self.samples[key] if s[0] >= cutoff]
            if kept:
                self.samples[key] = kept
            else:
                del self.samples[key]
        self.coverage = [c for c in self.coverage if c[0] >= cutoff]

    def observed_seconds(self, now: int, window: int) -> int:
        return sum(seconds for t, seconds in self.coverage if t >= now - window)

    def stats(self, key: str, now: int) -> dict | None:
        samples = self.samples.get(key)
        if not samples:
            return None
        observed_day = self.observed_seconds(now, config.DAY)
        result = summarize([s[1] for s in samples if s[0] >= now - config.DAY], "1d")
        result |= summarize([s[1] for s in samples], "7d")
        result["est_volume_1d"] = (
            round(result["count_1d"] * config.DAY / observed_day, 1)
            if observed_day >= config.MIN_OBSERVED_SECONDS_FOR_VOLUME
            else None
        )
        levels = defaultdict(list)
        for _, price, level in samples:
            if level in config.PET_LEVEL_BUCKETS:
                levels[level].append(price)
        if levels:
            result["levels"] = {
                str(level): summarize(prices, "7d") for level, prices in sorted(levels.items())
            }
        return result


def summarize(prices: list[float], window: str) -> dict:
    if not prices:
        return {f"count_{window}": 0, f"median_{window}": None}
    result = {f"count_{window}": len(prices), f"median_{window}": statistics.median(prices)}
    if len(prices) >= 4:
        q1, _, q3 = statistics.quantiles(prices, n=4)
        result[f"p25_{window}"] = q1
        result[f"p75_{window}"] = q3
    return result
