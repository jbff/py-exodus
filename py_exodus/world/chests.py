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

USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): chest ITEM DROPS after the gold
credit (LW ``GetChestBooty`` UltimaMain.c:1736-1760; GBC menucmd.c:1148-1170) —
~25% weapon find, else an independent ~25% armor find (see
``_chest_item_drops``). Java never implemented them; the gold band stays
py/Java (the refs' gold bands mutually diverge).
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from py_exodus import special_commands
from py_exodus.constants import Status
from py_exodus.entities.party import PartyDeathException

if TYPE_CHECKING:
    from py_exodus.entities.party import Party, PartyMember


class ChestNotFound(Exception):
    """Raised when a Get (G) finds no chest where it looked; callers log "Not Here!"."""


class ChestOpenResult(list):
    """The chest's log lines, carrying the credited gold total (``result.gold``)
    and the item-drop lines (``result.item_lines``).

    A ``list`` subclass so existing callers that iterate or compare the lines
    keep working unchanged while the dungeon state reads the gold figure for
    its event payload.
    """

    def __init__(self) -> None:
        super().__init__()
        self.gold: int = 0
        self.item_lines: list[str] = []


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
    ``disarmed=True`` is the APPAR_UNEM path and skips the trap roll entirely but
    still rolls the item drops (LW's trap cases 0/1/3 all fall into the same
    GetChestBooty rolls, UltimaMain.c:1683-1733; the sprung-Bomb case 2 is the
    lone early return — see ``_chest_trap``).
    ``dungeon`` distinguishes the caller: Java's dungeon and main-game getChest
    routes (DungeonScreen.java:1224-1252, GameScreen.java:1036-1074) share the
    same trap and gold rules.
    """
    lines = ChestOpenResult()
    if not disarmed:
        trap_lines, bomb_sprung = _chest_trap(party, member)
        lines.extend(trap_lines)
        if bomb_sprung:
            # LW case 2 (UltimaMain.c:1655-1663) returns unconditionally after
            # BombTrap — no GetChestBooty gold or item drops, wipe or not.
            return lines

    gold = random.randrange(50) + random.randrange(8) + 10
    member.gold = max(0, min(9999, member.gold + gold))
    lines.append(f"The Chest Holds: {gold} Gold")
    lines.gold = gold

    lines.item_lines = _chest_item_drops(member)
    lines.extend(lines.item_lines)
    return lines


def _chest_item_drops(member: PartyMember) -> list[str]:
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): chest item drops (LW GetChestBooty UltimaMain.c:1736-1760; GBC menucmd.c:1148-1170 corroborates ~25% find)

    After gold, a ~25% weapon find (index 1..7 -> DAGGER..SWORD_2H via
    list(WeaponType), +1 to the opening member's stack), else an independent
    ~25% armor find (index 1..3 -> CLOTH..CHAIN). LW's weapon grant returns
    before the armor block (UltimaMain.c:1750-1755); a weapon stack already
    at the 9 cap falls straight to the armor side, per the steal/dig stack
    conventions (special_commands.bump_stack, cap 9). Names come from the
    same enum tables the vendor/steal messages use.
    """
    item_lines: list[str] = []
    weapon_side = random.randrange(4) == 0  # LW RandNum(0,255) <= 63 (~25%)
    weapon_granted = False
    if weapon_side:
        weapon = special_commands.WEAPON_ORDER[random.randrange(7) + 1]
        weapon_granted = special_commands.bump_stack(member.weapons, weapon)
        if weapon_granted:
            item_lines.append(f"You found a {weapon.name.capitalize()}!")
    if weapon_granted:
        return item_lines
    if weapon_side or random.randrange(4) == 0:
        # weapon side fired but the stack was capped: the armor side rolls
        # directly; the weapon side missing: armor needs its own ~25% roll.
        armor = special_commands.ARMOR_ORDER[random.randrange(3) + 1]
        if special_commands.bump_stack(member.armors, armor):
            item_lines.append(f"You found a {armor.name.capitalize()}!")
    return item_lines


def _chest_trap(party: Party, member: PartyMember) -> tuple[list[str], bool]:
    """Java Context.getChestTrapHandler: 50% trap with a dexterity evade check.

    Returns ``(trap_lines, bomb_sprung)``; ``bomb_sprung`` ends open_chest
    before the booty rolls.

    OUTCOME TABLE — 4-way per LairWare (pending item 21; the trap ODDS and
    the dex+25 evade above stay the port's Java-parity ladder, while the typing
    roll follows LW UltimaMain.c:1628 `(RandNum(0, 255) & RandNum(0, 255)) & 0x03`
    (9/16 Acid, 3/16 Poison, 3/16 Bomb, 1/16 Gas)):
      0 Acid  — the Java FIRE/LAVA opener damage (LW case 0, UltimaMain.c:1637-1646,
                damages the opener only)         -> "Acid Trap!"
      1 Poison— single-member POISONED write (LW case 1, UltimaMain.c:1647-1654)
      2 Bomb  — LW BombTrap (UltimaMain.c:1662 + 1728-1740): party-wide blast
                through apply_damage, per living member (rnd255 & 0x77) +
                (dungeon_level + 1) * 8; 0x77 = 119, dungeon_level 0 = surface
                (LW reads the emulated zp[0x13]; the C sources never write it,
                so surface chests sit at 0 and the band is 8-127, 8-119+level*8
                below). Case 2 then RETURNS (UltimaMain.c:1655-1663): no
                GetChestBooty gold or item drops, wipe or not.
                                                  -> "Bomb Trap!"
      3 Gas   — party-wide POISONED write, no damage (LW case 3, UltimaMain.c:1665-1681)
    LW message strings (Messages.plist 41-44) read "ACID/POISON/BOMB/GAS TRAP!".
    """
    if random.randrange(2) != 0:  # hasTrap = rand.nextInt(2) == 0
        return [], False

    if member.dex + 25 >= random.randrange(100):  # evade: dex + 25 >= rand(100)
        return ["Evaded!"], False

    which_trap = (random.randrange(256) & random.randrange(256)) & 0x03
    if which_trap == 1:  # POISON
        if member.status != Status.POISONED:
            member.status = Status.POISONED
        return ["Poison Trap!"], False

    if which_trap == 2:  # BOMB (LW BombTrap, UltimaMain.c:1728-1740)
        # Party-wide through the apply_damage chokepoint, living members only
        # (LW checks CheckAlive per member); a wipe raises PartyDeathException
        # out of open_chest for the calling screen's try/except, mirroring the
        # Gas branch's shape (no internal catch). Per LW case 2's unconditional
        # return (UltimaMain.c:1655-1663) open_chest then skips the booty
        # rolls — gold and item drops never follow a sprung bomb.
        level_term = (party.dungeon_level + 1) * 8
        for m in party.members:
            if m.is_dead():
                continue
            m.apply_damage((random.randrange(256) & 0x77) + level_term)
        return ["Bomb Trap!"], True

    if which_trap == 3:  # GAS: poisons the whole party, no damage
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): Gas trap poisons every living member (GBC menucmd.c:1077-1147; LW UltimaMain.c:1665-1681 case 3)
        # Same status write as the POISON branch above — a party-wide loop
        # instead of the opener alone, skipping dead members.
        for m in party.members:
            if m.status != Status.DEAD and m.status != Status.POISONED:
                m.status = Status.POISONED
        return ["Gas Trap!"], False

    _apply_fire_lava(member)  # FIRE (Acid Trap): the opening member only
    return ["Acid Trap!"], False


def _apply_fire_lava(member: PartyMember) -> None:
    """Java PartyMember.applyEffect FIRE/LAVA (Party.java:353-358):
    16 + rand(32) damage through apply_damage unless Mark of Fire."""
    if member.is_dead():
        return
    if member.marks[1] == 0:
        try:
            member.apply_damage(16 + random.randrange(32))
        except PartyDeathException:
            pass
