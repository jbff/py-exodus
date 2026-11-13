"""JSON map reading: load map structs (the same shapes the byte decoders emit).

The JSON assets in ``assets/maps/`` are structural dumps of the original binary
map files; all load-time transforms (tile remaps, NPC filtering, label
overrides) stay in loader/builder code, applied identically on both paths.
"""
from __future__ import annotations

import json
from pathlib import Path

# maps.xml map_type -> structural kind handled by read_map_struct / builders
MAP_KIND_BY_TYPE: dict[str, str] = {
    "world": "grid",
    "city": "grid",
    "castle": "grid",
    "combat": "combat",
    "dungeon": "dungeon",
    "shrine": "shrine",
}


def _infer_kind(struct: dict) -> str:
    """Infer the structural kind from the dict's side data."""
    if "monster_starts" in struct:
        return "combat"
    if "level_texts" in struct:
        return "dungeon"
    if "npcs" in struct:
        return "grid"
    return "shrine"


def read_map_struct(path: Path) -> dict:
    """Read a JSON map file into a decoder-shaped struct.

    Raises FileNotFoundError if the path is missing, ValueError if the shape
    does not match its inferred kind.
    """
    if not path.exists():
        raise FileNotFoundError(f"Map JSON not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        struct = json.load(f)

    if not isinstance(struct, dict):
        raise ValueError(f"Invalid map JSON (expected an object): {path}")
    MISSING = "Map JSON {} is missing required field {} in {}"
    if "tiles" not in struct:
        raise ValueError(MISSING.format(path.name, "tiles", "any map kind"))

    kind = _infer_kind(struct)
    required_by_kind = {
        "grid": ("npcs", "conversations"),
        "combat": ("monster_starts", "player_starts"),
        "dungeon": ("level_texts",),
        "shrine": (),
    }
    for field in required_by_kind[kind]:
        if field not in struct:
            raise ValueError(MISSING.format(path.name, field, kind))

    return struct
