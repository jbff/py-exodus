"""Shared treasure-chest pipeline used by the overworld, town, and dungeon screens.

Java truth:
- ``exodus.GameScreen.getChest`` (GameScreen.java:1036-1074) — discovery, trap, gold,
  and the ``"The Chest Holds: %d Gold"`` / ``"Not Here!"`` log strings.
- ``exodus.Context.getChestTrapHandler`` (Context.java:248-285) — 50% trap chance,
  the ``dex + 25 < rand(100)`` evade roll, and the Acid/Gas/Poison trap effects.
- ``exodus.Party.getChestGold`` (Party.java:273-277) — ``rand(50) + rand(8) + 10``
  credited to the opening member (``adjustGold`` caps a purse at 9999).
- ``exodus.Party.applyEffect`` / ``PartyMember.applyEffect`` (Party.java:279-370) —
  FIRE/LAVA damage of ``16 + rand(32)`` skipped by Mark of Fire (``marks[1]``),
  POISON status, and dead members being immune.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from py_exodus.constants import Status

if TYPE_CHECKING:
    from py_exodus.entities.party import Party, PartyMember


class ChestNotFound(Exception):
    """Raised when a Get (G) finds no chest where it looked; callers log "Not Here!"."""


class ChestOpenResult(list):
    """The chest's log lines, carrying the credited gold total (``result.gold``).

    A ``list`` subclass so existing callers that iterate or compare the lines
    keep working unchanged while the dungeon state reads the gold figure for
    its event payload.
    """

    gold: int = 0


def take_chest_object(party: Party, x: int, y: int) -> dict:
    """Pop the chest dynamic object exactly at (x, y) and return it.

    Java scans current-map Drawables for cx == x && cy == y (GameScreen.getChest:1041-1050)
    — there is no adjacency scan, and G "Not Here!" when nothing matches.
    Raises ChestNotFound when no chest object is there.
    """
    for obj in party.dynamic_objects:
        if obj.get("tile") == "chest" and obj.get("x", -1) == x and obj.get("y", -1) == y:
            party.dynamic_objects.remove(obj)
            return obj
    raise ChestNotFound("Not Here!")


def open_chest(
    party: Party,
    member: PartyMember,
    dungeon: bool = False,
    disarmed: bool = False,
) -> ChestOpenResult:
    """Open the chest the caller located: roll traps unless disarmed, credit gold.

    Mutates ``member.gold`` / ``member.hp`` / ``member.status`` (and, for a Gas
    trap, the rest of the party) and returns the log lines the screen should add.
    ``disarmed=True`` is the APPAR_UNEM path and skips the trap roll entirely.
    ``dungeon`` distinguishes the caller: Java's dungeon and main-game getChest
    routes (DungeonScreen.java:1224-1252, GameScreen.java:1036-1074) share the
    same trap and gold rules.
    """
    lines = ChestOpenResult()
    if not disarmed:
        lines.extend(_chest_trap(party, member))

    gold = random.randrange(50) + random.randrange(8) + 10
    member.gold = max(0, min(9999, member.gold + gold))
    lines.append(f"The Chest Holds: {gold} Gold")
    lines.gold = gold
    return lines


def _chest_trap(party: Party, member: PartyMember) -> list[str]:
    """Java Context.getChestTrapHandler: 50% trap with a dexterity evade check."""
    if random.randrange(2) != 0:  # hasTrap = rand.nextInt(2) == 0
        return []

    if member.dex + 25 >= random.randrange(100):  # evade: dex + 25 >= rand(100)
        return ["Evaded!"]

    which_trap = random.randrange(4)
    if which_trap == 2:  # POISON
        if member.status != Status.POISONED:
            member.status = Status.POISONED
        return ["Poison Trap!"]

    if which_trap == 3:  # LAVA (Gas Trap): party.applyEffect hits every member
        for m in party.members:
            _apply_fire_lava(m)
        return ["Gas Trap!"]

    _apply_fire_lava(member)  # FIRE (Acid Trap): the opening member only
    return ["Acid Trap!"]


def _apply_fire_lava(member: PartyMember) -> None:
    """Java PartyMember.applyEffect FIRE/LAVA: 16 + rand(32) damage unless Mark of Fire."""
    if member.status == Status.DEAD:
        return
    if member.marks[1] == 0:
        member.hp = max(0, member.hp - (16 + random.randrange(32)))
        if member.hp == 0:
            member.status = Status.DEAD
