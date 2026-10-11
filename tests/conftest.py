import base64
import gzip
import io

from nbtlib import Compound, File, Int, List, String


def item_bytes(extra: dict, name: str = "") -> str:
    """Encode ExtraAttributes the way Hypixel does: NBT, gzipped, base64."""
    tag = Compound({"ExtraAttributes": Compound(extra), "display": Compound({"Name": String(name)})})
    nbt = File({"i": List[Compound]([Compound({"tag": tag})])})
    buffer = io.BytesIO()
    nbt.write(buffer)
    return base64.b64encode(gzip.compress(buffer.getvalue())).decode()


def pet(type_: str, tier: str, level: int) -> str:
    info = f'{{"type":"{type_}","tier":"{tier}","exp":0.0}}'
    return item_bytes({"id": String("PET"), "petInfo": String(info)}, f"§7[Lvl {level}] §6{type_.title()}")


def plain(item_id: str) -> str:
    return item_bytes({"id": String(item_id)})


def rune(item_id: str, rune_type: str, level: int) -> str:
    return item_bytes({"id": String(item_id), "runes": Compound({rune_type: Int(level)})})
