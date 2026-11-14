"""Door interactions shared by the overworld, town, and dungeon screens.

Java truth: ``exodus/objects/BaseMap.java:804-820`` — a door state exists for
every ``door`` (unlocked) and ``locked_door`` (locked) tile; ``openDoor(x, y)``
succeeds only for an existing *unlocked* door, and ``unlockDoor(x, y)``
succeeds whenever a door state exists at (x, y) regardless of lock state.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from py_exodus.assets import TileAttrib, TileDef

if TYPE_CHECKING:
    from py_exodus.entities.party import PartyMember
    from py_exodus.world.map import GameMap


def _floor_tile() -> TileDef:
    """Replacement tile for an opened door (Java replaceTile("floor", x, y))."""
    return TileDef(index=3, name="floor")


def _door_tile() -> TileDef:
    """Replacement tile for an unlocked-but-closed door (U on a locked door)."""
    return TileDef(index=35, name="door", rule="door", attribs=TileAttrib.DOOR)


def open_door(game_map: GameMap, x: int, y: int) -> bool:
    """Java ``BaseMap.openDoor`` — success only when a door tile is there and
    it is not locked (Java BaseMap.java:813-820). The open door is replaced
    with floor (Java ``GameScreen.replaceTile("door", ...)`` visual state)."""
    tile = game_map.get_tile(x, y)
    if tile is None:
        return False
    if getattr(tile, "rule", "") != "door":
        return False
    game_map.set_tile(x, y, _floor_tile())
    return True


def unlock_door(
    game_map: GameMap, x: int, y: int, member: PartyMember | None = None
) -> bool:
    """Java ``BaseMap.unlockDoor`` — a door state (locked or not) exists at
    (x, y) (BaseMap.java:804-811); this port unlocks the ``locked_door`` tile
    (a door state Java marks ``ds.locked = False``).

    GBC acting member: the U screen prompts for the acting member 1-4 (the
    existing member-selection flow), then passes that member here — the key
    check and decrement are done below against its ``keys``.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): unlocking consumes one key (GBC menucmd2.c:1595-1650)
    — with ``member`` provided, success requires ``member.keys > 0`` and
    decrements it by one (one key per successful unlock only; NES refunds the
    key on failure, GBC does not and GBC governs). ``member=None`` keeps the
    legacy Java behavior (no key check — legacy/test callers)."""
    if member is not None and getattr(member, "keys", 0) <= 0:
        return False
    tile = game_map.get_tile(x, y)
    if tile is None:
        return False
    if getattr(tile, "rule", "") not in ("door", "locked_door"):
        return False
    if getattr(tile, "rule", "") == "locked_door":
        game_map.set_tile(x, y, _door_tile())
    if member is not None:
        member.keys -= 1
    return True
