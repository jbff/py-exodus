"""Shared treasure-chest pipeline used by the overworld, town, and dungeon screens.

Rules: LairWare GetChest / GetChestBooty / BombTrap (UltimaMain.c:1583-1740)
with StealDisarmFail (UltimaMisc.c:510-529). The chest-object bookkeeping
(``take_chest_object``) and the 50% trap roll follow Java
(GameScreen.java:1036-1074, Context.java:248-285), which agree with LW.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

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


def take_chest_object(party: Party, x: int, y: int, game_map: Any = None) -> dict:
    """Pop the chest dynamic object exactly at (x, y) and return it.

    Java scans current-map Drawables for cx == x && cy == y (GameScreen.getChest:1041-1050)
    — there is no adjacency scan, and G "Not Here!" when nothing matches.
    Raises ChestNotFound when no chest object is there.
    """
    from py_exodus.entities.party import objects_on  # noqa: F811

    objs = party.dynamic_objects if game_map is None else objects_on(party, game_map)
    for obj in objs:
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

    lines.gold = chest_booty(member, lines)
    return lines


def chest_booty(member: PartyMember, lines: ChestOpenResult | None = None) -> int:
    """LairWare GetChestBooty (UltimaMain.c:1684-1726), shared by G, the
    disarmed APPAR UNEM path and a successful Steal (GetChest(2, ...)).

    Gold is ``RandNum(0, 100)``, raised by 30 when under 30 (30-100), added
    with AddGold's 9999 cap. Then ``RandNum(0, 255) > 63`` ends it (75%);
    otherwise a weapon roll ``w = RandNum(0, 255)``: when ``w < 128`` the
    weapon is ``(RandNum(0, 255) & w) & 7`` and a nonzero one is the find
    (Dagger..2-Handed Sword). With no weapon, the armour roll works the same
    way with ``& 3`` (Cloth..Chain). AddItem caps a stack at 99
    (UltimaMisc.c:504-508). Returns the gold; appends the log lines.
    """
    if lines is None:
        lines = ChestOpenResult()
    gold = random.randrange(101)  # RandNum(0, 100)
    if gold < 30:
        gold += 30
    member.gold = max(0, min(9999, member.gold + gold))
    lines.append(f"The Chest Holds: {gold} Gold")
    lines.gold = gold

    lines.item_lines = _chest_item_drops(member)
    lines.extend(lines.item_lines)
    return gold


def _chest_item_drops(member: PartyMember) -> list[str]:
    """LairWare GetChestBooty's item rolls (UltimaMain.c:1702-1726)."""
    if random.randrange(256) > 63:
        return []
    wpn = random.randrange(256)
    if wpn < 128:
        wpn = (random.randrange(256) & wpn) & 0x07
        if wpn != 0:
            weapon = special_commands.WEAPON_ORDER[wpn]
            special_commands.add_item(member.weapons, weapon, getattr(member, "weapon", None))
            return [f"You found a {weapon.name.capitalize()}!"]
    arm = random.randrange(256)
    if arm < 128:
        arm = (random.randrange(256) & arm) & 0x03
        if arm != 0:
            armor = special_commands.ARMOR_ORDER[arm]
            special_commands.add_item(member.armors, armor, getattr(member, "armor", None))
            return [f"You found a {armor.name.capitalize()}!"]
    return []


def disarm_factor(member: Any) -> int:
    """LairWare StealDisarmFail factor (UltimaMisc.c:510-529): dexterity,
    +128 for a Thief, +64 for a Barbarian, Illusionist, Ranger or Alchemist."""
    from py_exodus.constants import Profession

    factor = int(getattr(member, "dex", 0) or 0)
    profession = getattr(member, "profession", None)
    if profession == Profession.THIEF:
        factor += 0x80
    elif profession in (Profession.BARBARIAN, Profession.ILLUSIONIST,
                        Profession.RANGER, Profession.ALCHEMIST):
        factor += 0x40
    return factor


def steal_disarm_fails(member: Any) -> bool:
    """LairWare: the trap goes off when RandNum(0, 255) > factor. Replaces
    Java's dex + 25 >= rand(100) evade (user ruling 2026-11-22: LairWare
    wins). A 25-DEX Thief dodges 60%, a 25-DEX Fighter 10%."""
    return random.randrange(256) > disarm_factor(member)


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

    if not steal_disarm_fails(member):  # LW StealDisarmFail (UltimaMain.c:1630)
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
        # LW poisons CheckAlive members only (UltimaMain.c:1672-1679): the
        # dead and the ashes are untouched.
        for m in party.members:
            if not m.is_disabled() and m.status != Status.POISONED:
                m.status = Status.POISONED
        return ["Gas Trap!"], False

    _apply_fire_lava(member)  # FIRE (Acid Trap): the opening member only
    return ["Acid Trap!"], False


def _apply_fire_lava(member: PartyMember) -> None:
    """LairWare acid trap (UltimaMain.c:1637-1646): HPSubtract of
    ``RandNum(0, 255) & 0x37`` (0-55) on the opener; no Mark of Fire
    immunity (that was Java's FIRE/LAVA effect)."""
    if member.is_dead():
        return
    try:
        member.apply_damage(random.randrange(256) & 0x37)
    except PartyDeathException:
        pass
