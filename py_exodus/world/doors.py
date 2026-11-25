"""Doors: the Unlock command shared by the overworld and town screens.

LairWare Unlock (UltimaMain.c:2398-2437) is the only way through a door: a
member's key is spent and the door becomes the tile WEST of it. There is no
Open command and no bump-to-open (user 2026-11-25; Java's
``BaseMap.openDoor`` and its closed-but-unlocked "door" tile are gone).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from py_exodus.assets import TileDef

if TYPE_CHECKING:
    from py_exodus.entities.party import PartyMember
    from py_exodus.world.map import GameMap


def unlock_door(
    game_map: GameMap, x: int, y: int, member: PartyMember | None = None
) -> bool:
    """LairWare Unlock (UltimaMain.c:2415-2433): only a locked door (tile
    184) unlocks, and only with ``member``'s key (``Player[rosNum][38] < 1``
    is "None left!"); the key is spent and the door becomes the tile west of
    it. With no member (no key) nothing opens. The screens check the
    east/west direction (2405-2408) and say why a refusal happened."""
    if member is None or getattr(member, "keys", 0) <= 0:
        return False
    tile = game_map.get_tile(x, y)
    if tile is None or getattr(tile, "rule", "") != "locked_door":
        return False
    # LairWare Unlock (UltimaMain.c:2428-2433): the door becomes the tile
    # WEST of it, anything past floor (0x20) reading as grass -- on every
    # map, so a town door opens straight into its floor and Ambrosia's
    # water door at (39, 61) into water.
    west = game_map.get_tile((x - 1) % game_map.width, y)
    if west is None or not 0 <= getattr(west, "index", 99) <= 8:
        west = TileDef(index=1, name="grass", rule="grass")
    game_map.set_tile(x, y, west)
    member.keys -= 1
    return True
