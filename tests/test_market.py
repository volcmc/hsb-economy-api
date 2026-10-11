from conftest import pet, plain

from hsb_economy.market import summarize_auctions, summarize_bazaar


def auction(item: str, price: float, bin_: bool = True) -> dict:
    return {"bin": bin_, "item_bytes": item, "starting_bid": price}


def test_lowest_bins_and_listing_count():
    result = summarize_auctions(
        [
            auction(plain("HYPERION"), 500),
            auction(plain("HYPERION"), 300),
            auction(plain("HYPERION"), 400),
            auction(plain("HYPERION"), 1, bin_=False),
        ]
    )
    assert result == {"HYPERION": {"lbin": 300, "lbin2": 400, "listings": 3}}


def test_stacks_are_priced_per_item():
    result = summarize_auctions(
        [auction(plain("KAT_FLOWER", count=7), 3_500_000), auction(plain("KAT_FLOWER"), 600_000)]
    )
    assert result["KAT_FLOWER"] == {"lbin": 500_000, "lbin2": 600_000, "listings": 2}


def test_pet_level_buckets():
    result = summarize_auctions(
        [
            auction(pet("BEE", "RARE", 1), 50),
            auction(pet("BEE", "RARE", 1), 40),
            auction(pet("BEE", "RARE", 57), 10),
            auction(pet("BEE", "RARE", 100), 900),
        ]
    )["PET.BEE.RARE"]
    assert result["lbin"] == 10
    assert result["levels"] == {"1": 40, "100": 900}


def test_undecodable_listing_is_skipped():
    result = summarize_auctions([auction("not-nbt", 1), auction(plain("HYPERION"), 5)])
    assert result["HYPERION"]["lbin"] == 5


def test_bazaar_instant_prices_come_from_order_book_head():
    quick = {
        "buyPrice": 101.123,
        "sellPrice": 89.987,
        "buyVolume": 10,
        "sellVolume": 20,
        "buyMovingWeek": 30,
        "sellMovingWeek": 40,
        "buyOrders": 1,
        "sellOrders": 2,
    }
    products = {
        "A": {
            "buy_summary": [{"pricePerUnit": 100.0}, {"pricePerUnit": 102.0}],
            "sell_summary": [{"pricePerUnit": 90.0}, {"pricePerUnit": 88.0}],
            "quick_status": quick,
        },
        "EMPTY": {"buy_summary": [], "sell_summary": [], "quick_status": quick | {"buyPrice": 0}},
    }
    result = summarize_bazaar(products)
    assert (result["A"]["buy"], result["A"]["sell"]) == (100.0, 90.0)
    assert (result["A"]["buy_avg"], result["A"]["sell_avg"]) == (101.12, 89.99)
    assert (result["EMPTY"]["buy"], result["EMPTY"]["sell"], result["EMPTY"]["buy_avg"]) == (None, None, None)
