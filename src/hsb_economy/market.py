import heapq
import logging
from collections import defaultdict

from . import config
from .items import parse_item

log = logging.getLogger(__name__)


def summarize_bazaar(products: dict) -> dict:
    """Per product: instant prices from the top of the order book plus Hypixel's quick_status figures.

    ``buy_summary`` holds sell offers (cheapest first), so its head is what an instant buy costs;
    ``sell_summary`` holds buy orders (highest first), so its head is what an instant sell pays.
    """
    result = {}
    for product_id, product in products.items():
        quick = product["quick_status"]
        result[product_id] = {
            "buy": product["buy_summary"][0]["pricePerUnit"] if product["buy_summary"] else None,
            "sell": product["sell_summary"][0]["pricePerUnit"] if product["sell_summary"] else None,
            "buy_avg": round(quick["buyPrice"], 2) or None,
            "sell_avg": round(quick["sellPrice"], 2) or None,
            "buy_volume": quick["buyVolume"],
            "sell_volume": quick["sellVolume"],
            "buy_moving_week": quick["buyMovingWeek"],
            "sell_moving_week": quick["sellMovingWeek"],
            "buy_orders": quick["buyOrders"],
            "sell_orders": quick["sellOrders"],
        }
    return result


def summarize_auctions(auctions: list[dict]) -> dict:
    """Lowest BIN, second-lowest BIN and listing count per item key, plus per-level lowest BIN for pets."""
    prices: dict[str, list[float]] = defaultdict(list)
    pet_levels: dict[str, dict[int, float]] = defaultdict(dict)
    skipped = 0
    for auction in auctions:
        if not auction["bin"]:
            continue
        try:
            item = parse_item(auction["item_bytes"])
        except Exception:
            # One malformed listing should not sink the snapshot; the count is logged below.
            skipped += 1
            continue
        if item is None:
            continue
        price = auction["starting_bid"]
        prices[item.key].append(price)
        if item.pet_level in config.PET_LEVEL_BUCKETS:
            levels = pet_levels[item.key]
            levels[item.pet_level] = min(price, levels.get(item.pet_level, price))
    if skipped:
        log.warning("Skipped %d auctions with undecodable item data", skipped)

    result = {}
    for key, values in prices.items():
        lowest = heapq.nsmallest(2, values)
        entry = {"lbin": lowest[0], "lbin2": lowest[1] if len(lowest) > 1 else None, "listings": len(values)}
        if key in pet_levels:
            entry["levels"] = {str(level): price for level, price in sorted(pet_levels[key].items())}
        result[key] = entry
    return result
