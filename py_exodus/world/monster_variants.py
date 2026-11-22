"""Monster variant names, per LairWare.

LairWare ``SpawnMonster`` (refs/ultima3/Sources/UltimaMisc.c:1181-1185) gives
each new wandering monster a variant: none half the time, otherwise 1 or 2.
``PrintMonster`` (UltimaText.c:642-646) names the variants of the Thief through
the Balron from Tiles.plist entries 64-79 (plurals from TilesPlural.plist);
every other type keeps its plain name. Only the name (and, in LairWare's tile
sheets, the art) changes; the stats are the base type's.
"""
from __future__ import annotations

import random

# Base creature tile -> (variant 1, variant 2), singular and plural.
VARIANT_NAMES: dict[str, tuple[str, str]] = {
    "thief": ("Brigand", "Cutpurse"),
    "orc": ("Goblin", "Troll"),
    "skeleton": ("Ghoul", "Zombie"),
    "giant": ("Golem", "Titan"),
    "daemon": ("Gargoyle", "Mane"),
    "pincher": ("Snatch", "Bradle"),
    "dragon": ("Griffon", "Wyvern"),
    "balron": ("Orcus", "Devil"),
}
VARIANT_PLURALS: dict[str, tuple[str, str]] = {
    "thief": ("Brigands", "Cutpurses"),
    "orc": ("Goblins", "Trolls"),
    "skeleton": ("Ghouls", "Zombies"),
    "giant": ("Golems", "Titans"),
    "daemon": ("Gargoyles", "Manes"),
    "pincher": ("Snatches", "Bradles"),
    "dragon": ("Griffons", "Wyverns"),
    "balron": ("Orcuses", "Devils"),
}
# LairWare tile index of each variant's art: Tiles.plist 64..79, in the
# order of VARIANT_NAMES (Thief's variant 1 is 64, Balron's variant 2 is 79).
VARIANT_TILE_INDEX: dict[str, tuple[int, int]] = {
    tile: (64 + 2 * i, 65 + 2 * i) for i, tile in enumerate(VARIANT_NAMES)
}


def roll_variant(rng: random.Random | None = None) -> int:
    """LairWare: ``if (RandNum(0, 1)) var = RandNum(1, 2);`` else 0."""
    r = rng or random
    return r.randint(1, 2) if r.randint(0, 1) else 0


def variant_name(tile: str, variant: int, plural: bool = False) -> str | None:
    """The variant's display name, or None for variant 0 / unnamed types."""
    table = VARIANT_PLURALS if plural else VARIANT_NAMES
    names = table.get(str(tile).lower())
    if not names or variant not in (1, 2):
        return None
    return names[variant - 1]
