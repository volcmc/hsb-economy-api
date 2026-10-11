from conftest import item_bytes, pet, plain, rune
from nbtlib import Compound, Int, String

from hsb_economy.items import Item, parse_item


def test_plain_item_uses_hypixel_id():
    assert parse_item(plain("HYPERION")) == Item("HYPERION")


def test_pet_key_includes_type_tier_and_level():
    assert parse_item(pet("ENDER_DRAGON", "LEGENDARY", 100)) == Item("PET.ENDER_DRAGON.LEGENDARY", 100)


def test_tier_boost_files_pet_under_boosted_rarity():
    assert (
        parse_item(pet("ENDER_DRAGON", "EPIC", 100, "PET_ITEM_TIER_BOOST")).key
        == "PET.ENDER_DRAGON.LEGENDARY"
    )
    assert parse_item(pet("BEE", "MYTHIC", 1, "PET_ITEM_TIER_BOOST")).key == "PET.BEE.MYTHIC"
    assert parse_item(pet("BEE", "RARE", 1, "PET_ITEM_EXP_SHARE")).key == "PET.BEE.RARE"


def test_stack_size_is_read():
    assert parse_item(plain("KAT_FLOWER", count=7)) == Item("KAT_FLOWER", None, 7)


def test_runes_keyed_by_type_and_level():
    assert parse_item(rune("RUNE", "MAGIC", 3)).key == "RUNE.MAGIC.3"
    assert parse_item(rune("UNIQUE_RUNE", "EXPLOSIFALL", 3)).key == "UNIQUE_RUNE.EXPLOSIFALL.3"


def test_single_enchant_book_matches_bazaar_id():
    book = item_bytes({"id": String("ENCHANTED_BOOK"), "enchantments": Compound({"ultimate_wise": Int(5)})})
    assert parse_item(book).key == "ENCHANTMENT_ULTIMATE_WISE_5"


def test_multi_enchant_book_is_unpriced():
    book = item_bytes(
        {"id": String("ENCHANTED_BOOK"), "enchantments": Compound({"sharpness": Int(5), "smite": Int(5)})}
    )
    assert parse_item(book) is None


def test_potion_and_cake_variants():
    potion = item_bytes({"id": String("POTION"), "potion": String("absorption"), "potion_level": Int(5)})
    cake = item_bytes({"id": String("NEW_YEAR_CAKE"), "new_years_cake": Int(515)})
    assert parse_item(potion).key == "POTION.ABSORPTION.5"
    assert parse_item(cake).key == "NEW_YEAR_CAKE.515"
