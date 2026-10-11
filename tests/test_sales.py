from conftest import pet, plain

from hsb_economy import config
from hsb_economy.sales import Sales

NOW = 1_800_000_000


def sold(auction_id: str, item: str, price: float, at: int = NOW, bin_: bool = True) -> dict:
    return {"auction_id": auction_id, "item_bytes": item, "price": price, "timestamp": at * 1000, "bin": bin_}


def response(at: int, *auctions: dict) -> dict:
    return {"lastUpdated": at * 1000, "auctions": list(auctions)}


def test_records_bin_sales_once_across_overlapping_responses():
    sales = Sales()
    first = response(NOW, sold("a", plain("X"), 10), sold("b", plain("X"), 99, bin_=False))
    assert sales.add(first) == 1
    assert sales.add(first) == 0
    assert sales.add(response(NOW + 60, sold("a", plain("X"), 10), sold("c", plain("X"), 12))) == 1
    assert sales.samples["X"] == [[NOW, 10, None], [NOW, 12, None]]


def test_coverage_counts_gaps_between_responses():
    sales = Sales()
    # Responses arrive out of order during a backfill; a 3-minute gap only contributes one window.
    for at in (NOW + 60, NOW, NOW + 300, NOW + 120):
        sales.add(response(at))
    assert sales.windows == [NOW, NOW + 60, NOW + 120, NOW + 300]
    assert sales.observed_seconds(NOW + 300, config.DAY) == 4 * 60


def test_coverage_only_counts_the_requested_window():
    sales = Sales({"windows": [NOW - config.DAY - 60, NOW - config.DAY + 30]})
    assert sales.observed_seconds(NOW, config.DAY) == 60


def test_stats_medians_and_volume_estimate():
    sales = Sales()
    # 3,600 observed seconds is the minimum before a volume estimate is reported.
    sales.windows = [NOW - i * 60 for i in range(60)][::-1]
    prices = [100, 200, 300, 400, 1_000_000]
    sales.samples["X"] = [[NOW - 60, p, None] for p in prices] + [[NOW - 3 * config.DAY, 5, None]]
    stats = sales.stats("X", NOW, sales.observed_seconds(NOW, config.DAY))
    assert stats["count_1d"] == 5
    assert stats["median_1d"] == 300
    assert stats["count_7d"] == 6
    assert stats["est_volume_1d"] == 5 * config.DAY / 3_600


def test_no_volume_estimate_from_too_little_coverage():
    sales = Sales({"windows": [NOW], "samples": {"X": [[NOW, 1, None]]}})
    assert sales.stats("X", NOW, sales.observed_seconds(NOW, config.DAY))["est_volume_1d"] is None


def test_pet_level_sales_breakdown():
    sales = Sales()
    sales.add(response(NOW, sold("a", pet("BEE", "RARE", 100), 5), sold("b", pet("BEE", "RARE", 3), 1)))
    assert sales.stats("PET.BEE.RARE", NOW, 60)["levels"] == {"100": {"count_7d": 1, "median_7d": 5}}


def test_stack_sales_are_priced_per_item():
    sales = Sales()
    sales.add(response(NOW, sold("a", plain("KAT_FLOWER", count=4), 2_000_000)))
    assert sales.samples["KAT_FLOWER"] == [[NOW, 500_000, None]]


def test_prune_drops_expired_samples_and_windows():
    old = NOW - config.SALES_RETENTION - 1
    sales = Sales({"samples": {"OLD": [[old, 1, None]]}, "windows": [old, NOW]})
    sales.prune(NOW)
    assert "OLD" not in sales.samples
    assert sales.windows == [NOW]


def test_seen_ids_are_bounded(monkeypatch):
    monkeypatch.setattr(config, "SEEN_SALE_IDS_LIMIT", 2)
    sales = Sales()
    sales.add(response(NOW, *(sold(str(i), plain("X"), i) for i in range(5))))
    assert list(sales.seen) == ["3", "4"]
