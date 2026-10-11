from conftest import pet, plain

from hsb_economy import config
from hsb_economy.sales import Sales

NOW = 1_800_000_000


def sold(auction_id: str, item: str, price: float, at: int = NOW, bin_: bool = True) -> dict:
    return {"auction_id": auction_id, "item_bytes": item, "price": price, "timestamp": at * 1000, "bin": bin_}


def test_records_bin_sales_once():
    sales = Sales()
    ended = {"auctions": [sold("a", plain("X"), 10), sold("b", plain("X"), 99, bin_=False)]}
    assert sales.add(ended, NOW) == 1
    assert sales.add(ended, NOW + 300) == 0
    assert sales.samples["X"] == [[NOW, 10, None]]


def test_coverage_never_double_counts_overlapping_runs():
    sales = Sales()
    sales.add({"auctions": []}, NOW)
    sales.add({"auctions": []}, NOW + 20)
    sales.add({"auctions": []}, NOW + 320)
    assert sales.observed_seconds(NOW + 320, config.DAY) == 60 + 20 + 60


def test_stats_medians_and_volume_estimate():
    sales = Sales()
    # 3,600 observed seconds is the minimum before a volume estimate is reported.
    sales.coverage = [[NOW - i * 300, 60] for i in range(60)]
    prices = [100, 200, 300, 400, 1_000_000]
    sales.samples["X"] = [[NOW - 60, p, None] for p in prices] + [[NOW - 3 * config.DAY, 5, None]]
    stats = sales.stats("X", NOW)
    assert stats["count_1d"] == 5
    assert stats["median_1d"] == 300
    assert stats["count_7d"] == 6
    assert stats["est_volume_1d"] == 5 * config.DAY / 3_600


def test_no_volume_estimate_from_too_little_coverage():
    sales = Sales({"coverage": [[NOW, 60]], "samples": {"X": [[NOW, 1, None]]}})
    assert sales.stats("X", NOW)["est_volume_1d"] is None


def test_pet_level_sales_breakdown():
    sales = Sales()
    sales.add({"auctions": [sold("a", pet("BEE", "RARE", 100), 5), sold("b", pet("BEE", "RARE", 3), 1)]}, NOW)
    assert sales.stats("PET.BEE.RARE", NOW)["levels"] == {"100": {"count_7d": 1, "median_7d": 5}}


def test_prune_drops_expired_samples():
    sales = Sales({"samples": {"OLD": [[NOW - config.SALES_RETENTION - 1, 1, None]]}})
    sales.prune(NOW)
    assert "OLD" not in sales.samples
