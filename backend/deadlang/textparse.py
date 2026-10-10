"""Code-only parsing of a listing's stated material and item type. First matching rule wins."""
import re

from deadlang.schemas import ItemType, StatedMaterial

_MATERIAL_RULES: list[tuple[str, StatedMaterial]] = [
    (r"\b(tagua|vegetable ivory|corozo)\b", "tagua"),
    (r"\b(faux|imitation|resin|polyresin|plastic|celluloid)\b", "resin"),
    (r"\bivory[\s-]+(colou?r(ed)?|tone|white|finish)\b", "ivory_color"),
    (r"\b(bones?|bovine)\b", "bone"),          # covers "ox bone", "cow bone", "camel bone"
    (r"\b(boxwood|wood|wooden)\b", "wood"),
    (r"\bivory\b", "ivory_mentioned"),
]
_TYPE_RULES: list[tuple[str, ItemType]] = [
    (r"\bnetsukes?\b", "netsuke"),
    (r"\b(bangle|bracelet|bead|necklace|pendant|mala|ring|earring)s?\b", "jewelry"),
    (r"\b(okimono|figurine|figure|statue|carving|sculpture)s?\b", "figurine"),
]


def _first(rules, title: str, description: str, default):
    text = f"{title} {description}".lower()
    return next((value for pattern, value in rules if re.search(pattern, text)), default)


def stated_material(title: str, description: str) -> StatedMaterial:
    return _first(_MATERIAL_RULES, title, description, "unknown")


def item_type(title: str, description: str) -> ItemType:
    return _first(_TYPE_RULES, title, description, "other")
