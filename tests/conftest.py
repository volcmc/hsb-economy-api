import base64
import gzip
import io

from nbtlib import Byte, Compound, File, Int, List, String


def item_bytes(extra: dict, name: str = "", count: int = 1) -> str:
    """Encode ExtraAttributes the way Hypixel does: NBT, gzipped, base64."""
    tag = Compound({"ExtraAttributes": Compound(extra), "display": Compound({"Name": String(name)})})
    nbt = File({"i": List[Compound]([Compound({"Count": Byte(count), "tag": tag})])})
    buffer = io.BytesIO()
    nbt.write(buffer)
    return base64.b64encode(gzip.compress(buffer.getvalue())).decode()


def pet(type_: str, tier: str, level: int, held_item: str | None = None) -> str:
    held = f',"heldItem":"{held_item}"' if held_item else ""
    info = f'{{"type":"{type_}","tier":"{tier}","exp":0.0{held}}}'
    return item_bytes({"id": String("PET"), "petInfo": String(info)}, f"§7[Lvl {level}] §6{type_.title()}")


def plain(item_id: str, count: int = 1) -> str:
    return item_bytes({"id": String(item_id)}, count=count)


def rune(item_id: str, rune_type: str, level: int) -> str:
    return item_bytes({"id": String(item_id), "runes": Compound({rune_type: Int(level)})})
