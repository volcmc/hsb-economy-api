"""Human-readable names for item keys.

Plain Hypixel ids use the name from Hypixel's items resource. Keys that split one id into variants
(pets, runes, books, potions, cakes) and ids missing from the resource get a name derived from the key.
"""

import re

FORMATTING = re.compile(r"§.")
ENCHANTMENT = re.compile(r"^ENCHANTMENT_(.+)_(\d+)$")
# Bazaar ids like SHARD_SALMON or ESSENCE_DRAGON read better with the kind last.
SUFFIXED_KINDS = {"SHARD": "Shard", "ESSENCE": "Essence"}


def resource_names(resource: dict) -> dict[str, str]:
    """Map item id to display name from ``/v2/resources/skyblock/items``."""
    return {item["id"]: FORMATTING.sub("", item["name"]).strip() for item in resource.get("items", [])}


def title_case(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split("_") if word)


def display_name(key: str, names: dict[str, str]) -> str:
    parts = key.split(".")
    if parts[0] == "PET" and len(parts) == 3:
        return f"{title_case(parts[1])} ({title_case(parts[2])} pet)"
    if parts[0] in ("RUNE", "UNIQUE_RUNE") and len(parts) == 3:
        kind = "Rune" if parts[0] == "RUNE" else "Unique Rune"
        return f"{title_case(parts[1])} {kind} {parts[2]}"
    if parts[0] == "POTION" and len(parts) == 3:
        return f"{title_case(parts[1])} Potion {parts[2]}"
    if parts[0] == "NEW_YEAR_CAKE" and len(parts) == 2:
        return f"New Year Cake (Year {parts[1]})"
    if match := ENCHANTMENT.match(key):
        return f"{title_case(match.group(1))} {match.group(2)} (Enchantment)"
    if key in names:
        return names[key]
    kind, _, rest = key.partition("_")
    if kind in SUFFIXED_KINDS and rest:
        return f"{title_case(rest)} {SUFFIXED_KINDS[kind]}"
    return title_case(key)
