"""Decode auction item NBT and map each item to a stable pricing key.

Keys are the Hypixel item id, except where one id covers items with very different values:

- ``PET.<TYPE>.<TIER>``                      e.g. ``PET.ENDER_DRAGON.LEGENDARY``
- ``RUNE.<TYPE>.<LEVEL>`` / ``UNIQUE_RUNE...``  e.g. ``RUNE.MAGIC.3``
- ``ENCHANTMENT_<NAME>_<LEVEL>``             single-enchant books; matches bazaar product ids
- ``POTION.<EFFECT>.<LEVEL>``                e.g. ``POTION.ABSORPTION.5``
- ``NEW_YEAR_CAKE.<YEAR>``

Hypixel ids never contain ``.``, so the separator is unambiguous.
"""

import base64
import gzip
import io
import json
import re
from dataclasses import dataclass

from nbtlib import File

PET_LEVEL = re.compile(r"^\[Lvl (\d+)\]")
FORMATTING = re.compile(r"§.")


# Upgrades that raise a copy's price well above a plain one. Reforges and enchantments are left out:
# most gear carries some, so excluding them would leave almost nothing to price.
COUNT_UPGRADES = (
    "upgrade_level",  # stars
    "dungeon_item_level",  # stars on older items
    "rarity_upgrades",  # recombobulator
    "hot_potato_count",  # hot and fuming potato books
    "art_of_war_count",
    "artOfPeaceApplied",
)
PRESENCE_UPGRADES = ("dye_item", "skin", "ability_scroll", "power_ability_scroll")


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    pet_level: int | None = None
    # Auctions can sell a stack; their price covers the whole stack.
    count: int = 1
    # False when the copy carries any of the upgrades above.
    plain: bool = True


def is_plain(extra: dict) -> bool:
    if any(int(extra.get(field, 0)) > 0 for field in COUNT_UPGRADES):
        return False
    if any(extra.get(field) for field in PRESENCE_UPGRADES):
        return False
    # Applied gemstones; slots that are merely unlocked don't count.
    if any(slot != "unlocked_slots" for slot in extra.get("gems", {})):
        return False
    return not ("petInfo" in extra and "skin" in json.loads(str(extra["petInfo"])))


def decode_item(item_bytes: str) -> dict:
    nbt = File.parse(io.BytesIO(gzip.decompress(base64.b64decode(item_bytes))))
    return nbt["i"][0]


def item_key(extra: dict) -> str | None:
    item_id = extra.get("id")
    if item_id is None:
        return None
    item_id = str(item_id)

    if item_id == "PET" and "petInfo" in extra:
        pet = json.loads(str(extra["petInfo"]))
        if pet.get("heldItem") == "PET_ITEM_TIER_BOOST":
            # Displays one rarity up but trades as a cheaper base pet plus a boost: filed under either
            # rarity it would distort that rarity's prices, so it is left unpriced.
            return None
        return f"PET.{pet['type']}.{pet['tier']}"

    if item_id in ("RUNE", "UNIQUE_RUNE") and extra.get("runes"):
        rune, level = next(iter(extra["runes"].items()))
        return f"{item_id}.{rune}.{int(level)}"

    if item_id == "ENCHANTED_BOOK":
        enchantments = extra.get("enchantments") or {}
        if len(enchantments) != 1:
            # Multi-enchant books have no meaningful single price.
            return None
        name, level = next(iter(enchantments.items()))
        return f"ENCHANTMENT_{str(name).upper()}_{int(level)}"

    if item_id == "POTION" and "potion" in extra:
        return f"POTION.{str(extra['potion']).upper()}.{int(extra.get('potion_level', 0))}"

    if item_id == "NEW_YEAR_CAKE" and "new_years_cake" in extra:
        return f"NEW_YEAR_CAKE.{int(extra['new_years_cake'])}"

    return item_id


def parse_item(item_bytes: str) -> Item | None:
    item = decode_item(item_bytes)
    tag = item.get("tag", {})
    extra = tag.get("ExtraAttributes", {})
    key = item_key(extra)
    if key is None:
        return None
    level = None
    if key.startswith("PET."):
        # auctions_ended has no item_name field, so read the display name from NBT for both sources.
        name = FORMATTING.sub("", str(tag.get("display", {}).get("Name", "")))
        if match := PET_LEVEL.match(name):
            level = int(match.group(1))
    return Item(key, level, max(int(item.get("Count", 1)), 1), is_plain(extra))
