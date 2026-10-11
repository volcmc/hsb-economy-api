"""Rolling record of BIN sales from ``auctions_ended`` responses.

Each response covers the 60 seconds before its ``lastUpdated``. The sales feed Worker captures every
response, so normally coverage is complete; ``windows`` records which responses were processed so
gaps (feed outages, direct-fetch fallback) are measured and sample counts can be scaled to a daily
volume estimate.
"""

import bisect
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
        # Insertion-ordered so the oldest ids can be dropped; responses overlap at their edges.
        self.seen: dict[str, None] = dict.fromkeys(data.get("seen", []))
        # Sorted lastUpdated (seconds) of every processed response.
        self.windows: list[int] = data.get("windows", [])

    def to_dict(self) -> dict:
        return {"samples": dict(self.samples), "seen": list(self.seen), "windows": self.windows}

    def add(self, ended: dict) -> int:
        """Record BIN sales from one ``auctions_ended`` response; returns how many were new."""
        window = ended["lastUpdated"] // 1000
        index = bisect.bisect_left(self.windows, window)
        if index < len(self.windows) and self.windows[index] == window:
            return 0
        self.windows.insert(index, window)

        added = 0
        for auction in ended["auctions"]:
            if not auction["bin"] or auction["auction_id"] in self.seen:
                continue
            self.seen[auction["auction_id"]] = None
            try:
                item = parse_item(auction["item_bytes"])
            except Exception:
                log.warning("Skipped sold auction %s with undecodable item data", auction["auction_id"])
                continue
            if item is None:
                continue
            self.samples[item.key].append([auction["timestamp"] // 1000, auction["price"], item.pet_level])
            added += 1
        for stale in list(self.seen)[: max(len(self.seen) - config.SEEN_SALE_IDS_LIMIT, 0)]:
            del self.seen[stale]
        return added

    def prune(self, now: int) -> None:
        cutoff = now - config.SALES_RETENTION
        for key in list(self.samples):
            kept = [s for s in self.samples[key] if s[0] >= cutoff]
            if kept:
                self.samples[key] = kept
            else:
                del self.samples[key]
        del self.windows[: bisect.bisect_left(self.windows, cutoff)]

    def observed_seconds(self, now: int, window: int) -> int:
        """Seconds of sales covered by processed responses ending within the last ``window`` seconds."""
        observed = 0
        previous = None
        for t in self.windows:
            if t >= now - window:
                gap = config.ENDED_WINDOW_SECONDS if previous is None else t - previous
                observed += min(gap, config.ENDED_WINDOW_SECONDS)
            previous = t
        return observed

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
