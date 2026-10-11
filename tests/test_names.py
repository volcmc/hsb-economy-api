from hsb_economy.names import display_name, resource_names

NAMES = resource_names(
    {"items": [{"id": "INK_SACK:3", "name": "Cocoa Beans"}, {"id": "HYPERION", "name": "§dHyperion"}]}
)


def test_resource_names_strip_formatting():
    assert NAMES == {"INK_SACK:3": "Cocoa Beans", "HYPERION": "Hyperion"}


def test_plain_ids_use_the_resource_name():
    assert display_name("INK_SACK:3", NAMES) == "Cocoa Beans"


def test_variant_keys_get_derived_names():
    assert display_name("PET.ENDER_DRAGON.LEGENDARY", NAMES) == "Ender Dragon (Legendary pet)"
    assert display_name("RUNE.MUSIC.3", NAMES) == "Music Rune 3"
    assert display_name("UNIQUE_RUNE.PRIMAL_FEAR.3", NAMES) == "Primal Fear Unique Rune 3"
    assert display_name("ENCHANTMENT_ULTIMATE_WISE_5", NAMES) == "Ultimate Wise 5 (Enchantment)"
    assert display_name("POTION.ABSORPTION.5", NAMES) == "Absorption Potion 5"
    assert display_name("NEW_YEAR_CAKE.515", NAMES) == "New Year Cake (Year 515)"


def test_unknown_ids_fall_back_to_title_case():
    assert display_name("SHARD_QUEEN_BEE", NAMES) == "Queen Bee Shard"
    assert display_name("ESSENCE_DRAGON", NAMES) == "Dragon Essence"
    assert display_name("DEAD_MANS_CHESTPLATE", NAMES) == "Dead Mans Chestplate"
