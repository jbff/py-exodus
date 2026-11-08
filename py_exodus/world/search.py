"""Search (S) at a grid coordinate — Java ``objects/BaseMap.searchLocation``
(BaseMap.java:855-937): scan the map's labels at (x, y, z); grant the item once
and award 100 experience; return the item description, or None ("Nothing
here!").
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_exodus.entities.party import Party, PartyMember
    from py_exodus.world.map import GameMap


_LABEL_DESCS = {
    "EXOTIC_ARMOR": "Exotic Armour",
    "EXOTIC_WEAPON": "Exotic Weapon",
    "CARD_OF_DEATH": "Card of Death",
    "CARD_OF_SOL": "Card of Sol",
    "CARD_OF_MOONS": "Card of Moons",
    "CARD_OF_LOVE": "Card of Love",
}


def search_location(
    game_map: GameMap,
    party: Party,
    member: PartyMember,
    x: int,
    y: int,
    z: int = 0,
) -> str | None:
    """Java ``BaseMap.searchLocation`` — returns the label's description when
    something was granted, None otherwise (BaseMap.java:855-937)."""
    if game_map is None:
        return None

    name = None
    for lbl in game_map.labels:
        if lbl.x == x and lbl.y == y and getattr(lbl, "z", 0) == z:
            name = str(lbl.name).upper()
            break
    if name is None or name not in _LABEL_DESCS:
        return None

    player = getattr(member, "player", member)

    if name == "EXOTIC_ARMOR":
        if player.armors.get(_armor_type("EXOTIC"), 0) > 0:
            return None
        player.armors[_armor_type("EXOTIC")] = player.armors.get(_armor_type("EXOTIC"), 0) + 1
    elif name == "EXOTIC_WEAPON":
        if player.weapons.get(_weapon_type("EXOTIC"), 0) > 0:
            return None
        player.weapons[_weapon_type("EXOTIC")] = player.weapons.get(_weapon_type("EXOTIC"), 0) + 1
    else:
        card_index = {
            "CARD_OF_DEATH": 0,
            "CARD_OF_SOL": 1,
            "CARD_OF_MOONS": 2,
            "CARD_OF_LOVE": 3,
        }[name]
        if player.cards[card_index] > 0:
            return None
        player.cards[card_index] += 1

    member.award_xp(100)
    return _LABEL_DESCS[name]


def _armor_type(name: str):
    from py_exodus.constants import ArmorType

    return ArmorType[name]


def _weapon_type(name: str):
    from py_exodus.constants import WeaponType

    return WeaponType[name]
