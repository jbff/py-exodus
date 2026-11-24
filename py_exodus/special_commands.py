"""Other commands (bribe, steal, dig, pray, search, score) and the item
helpers they share.

Rules: LairWare OtherCommand and Steal (UltimaMisc.c:2262-2510;
UltimaMain.c:2248-2287). Port additions kept from the 2026-11-14 GBC work:
SCORE (the move counter) and the Alchemist's lack of a steal bonus (LW
gives one; ledger ask row). KISS is not a U3 word.

The ``do_*`` functions are pure logic taking explicit args (screen-agnostic,
shared by the town, overworld, and dungeon O prompts); the ``*_flow``
functions own the member/direction prompt orchestration both screens reuse.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from py_exodus.assets import MAP_NAME_TO_ID, TileDef
from py_exodus.constants import (
    ArmorType,
    Direction,
    MapType,
    Profession,
    WeaponType,
)

if TYPE_CHECKING:
    from py_exodus.ui.text_log import TextLog
    from py_exodus.entities.party import Party, PartyMember
    from py_exodus.world.map import GameMap

# --- GBC message set (port phrasing; 0x82 sentence mark → period) ---
NO_EFFECT = "No effect."  # noeffectdat (menucmd3.c:868-870)
CANNOT_PAY = "Cannot pay."  # cantpay (menucmd3.c:1015-1017)
CANCELLED = "Cancelled."  # canceldat3 (menucmd3.c:170-172)
INVALID_MEMBER = "Invalid member #!"
INVALID_DIRECTION = "Invalid direction!"
NOT_HERE = "Not Here!"  # LW NotHere (UltimaMain.c:2781-2784)
INCAPACITATED = "Incapacitated!"  # LW message 126
WATCH_OUT = "Watch out!"  # watchoutdat (menucmd2.c:1487-1489)
STEAL_FAILED = "Failed."  # faileddat (menucmd2.c:1491-1493)
EXOTICS = "Exotics."  # exoticdat (menucmd3.c:1105-1117)
CARD_MESSAGE = "You found a Card with Strange Marks."  # card1..3 (menucmd3.c:1142-1152)
VISION = "A vision appears: Yell 'EVOCARE'!"  # yellevo (menucmd3.c:1011-1013)

# GBC dosteal skill bonus: ``players[pnum].skill`` is the class index and
# grants +0x80 to the thief (index 9) and +0x40 to other classes (menucmd2.c:
# 1489-1500). USER RULING (2026-11-14, coordinator fix round): the +64 set is
# the ORIGINAL U3 roster per the Apple-II-derived table (LW UltimaMisc.c:
# 500-526, which marks the Alchemist non-Apple-II at :523-530) mapped to the
# py Profession enum — thief +128; BARBARIAN, ILLUSIONIST, RANGER +64; the
# Alchemist takes NO steal bonus.
_STEAL_PLUS_64: tuple[Profession, ...] = (
    Profession.BARBARIAN,
    Profession.ILLUSIONIST,
    Profession.RANGER,
)

# GBC weapon/armor lists index their stacks 1..7 / 1..3; py list(...) order
# matches (list(WeaponType)[1..7] = DAGGER..SWORD_2H,
# list(ArmorType)[1..3] = CLOTH..CHAIN).
WEAPON_ORDER = list(WeaponType)
ARMOR_ORDER = list(ArmorType)

_ITEM_CAP = 99  # LairWare AddItem (UltimaMisc.c:504-508)


def do_bribe(
    member: PartyMember,
    x: int,
    y: int,
    direction: Direction,
    game_map: GameMap | None,
    creatures: list | None = None,
) -> str:
    """LairWare Bribe (UltimaMisc.c:2446-2464): someone must stand in the
    chosen direction (else NotHere, free); under 100 gold "Not enough
    gold!"; otherwise 100 gold goes, and only a guard (0x48) leaves --
    anyone else answers NoEffect. Success is silent ("")."""
    if game_map is None or direction is None:
        return NO_EFFECT
    tx, ty = x + direction.dx, y + direction.dy

    npc = next((n for n in game_map.npcs if n.x == tx and n.y == ty), None)
    creature = None
    if npc is None and creatures:
        creature = next(
            (c for c in creatures
             if int(c.get("x", -1)) == tx and int(c.get("y", -1)) == ty),
            None,
        )
    if npc is None and creature is None:
        return NOT_HERE  # MonsterHere == 255 (UltimaMisc.c:2449-2452)
    if getattr(member, "gold", 0) < 100:
        return CANNOT_PAY  # UltimaMisc.c:2454-2457
    member.gold -= 100  # paid before the guard test (UltimaMisc.c:2459-2461)
    if npc is not None:
        if str(getattr(npc, "tile_name", "")).lower() != "guard":
            return NO_EFFECT
        game_map.npcs.remove(npc)
        return ""
    if str(creature.get("tile", creature.get("tile_name", ""))).lower() != "guard":
        return NO_EFFECT
    creatures.remove(creature)
    return ""


def do_steal(
    party: Party,
    member: PartyMember,
    x: int,
    y: int,
    direction: Direction,
    game_map: GameMap | None,
    rng=None,
) -> list[str]:
    """LairWare Steal (UltimaMain.c:2248-2287).

    StealDisarmFail first (``RandNum(0, 255) > factor`` fails). A good roll
    still needs a counter tile (0x94-0xE4) next to the thief and a chest
    (0x24) three tiles out; it then becomes floor and GetChestBooty pays.
    Any failure: three times in four "Failed!", else every guard turns
    hostile (ctrl 0xC0) and "Watch out!".
    """
    from py_exodus.world import chests

    roll = (rng or random).randrange
    skill = getattr(member, "dex", 0) + _steal_skill_bonus(member)
    chest = None
    if roll(256) <= skill and game_map is not None and direction is not None:
        counter = game_map.get_tile(x + direction.dx, y + direction.dy)
        target = (x + 3 * direction.dx, y + 3 * direction.dy)
        far = game_map.get_tile(*target)
        if (
            counter is not None and 37 <= getattr(counter, "index", -1) <= 57
            and far is not None and getattr(far, "rule", "") == "chest"
        ):
            chest = target
    if chest is None:
        if roll(256) & 0x03:
            return [STEAL_FAILED]
        if game_map is not None:
            for npc in game_map.npcs:
                if str(getattr(npc, "tile_name", "")).lower() == "guard":
                    npc.movement = "ATTACK_AVATAR"
        return [WATCH_OUT]

    floor = TileDef(index=8, name="floor", rule="floors")
    game_map.set_tile(chest[0], chest[1], floor)  # PutXYVal(0x20, ...)
    booty = chests.ChestOpenResult()
    chests.chest_booty(member, booty)  # GetChest(2, chnum): booty, no trap
    return list(booty)


def do_dig(party: Party, member: PartyMember, x: int, y: int, game_map) -> str:
    """LairWare Dig (UltimaMisc.c:2417-2430): only on Sosaria (``Party[3]
    != 0`` -> NotHere). At (33, 3) the Exotic weapon count is SET to 1, at
    (19, 44) the Exotic armour's; anywhere else NotHere."""
    if not _is_sosaria_surface(game_map):
        return NOT_HERE
    if (x, y) == (33, 3):
        _set_one(member.weapons, WeaponType.EXOTIC, getattr(member, "weapon", None))
        return EXOTICS
    if (x, y) == (19, 44):
        _set_one(member.armors, ArmorType.EXOTIC, getattr(member, "armor", None))
        return EXOTICS
    return NOT_HERE


def _set_one(stacks: dict, kind, equipped) -> None:
    """``Player[rosNum][item] = 1``: LW counts the readied one in the stack,
    the port keeps it out."""
    stacks[kind] = 0 if equipped == kind else 1


def do_pray(x: int, y: int, map_id, map_name: str = "") -> str:
    """LairWare Pray (UltimaMisc.c:2466-2481): only in the town entered at
    LocationX[4] (Yew), standing on (0x30, 0x30); else NoEffect."""
    if _matches_map(map_id, map_name, "YEW") and (x, y) == (48, 48):
        return VISION
    return NO_EFFECT


def do_search(member: PartyMember, x: int, y: int, map_id, map_name: str = "") -> str | None:
    """SEARCH (O-menu): the Ambrosia card sites (GBC menucmd3.c:1151-1197).

    GBC gates the four sites on ``peermap==12`` (Ambrosia — py map id 13)
    and credits ``players[pnum].markcard`` per member — an idempotent bit
    ``|=``, so a repeat visit grants nothing (coordinator fix round 2026-11-14:
    the port's ``world/search.py:63-65`` convention is adopted — an owned
    card returns None and the site answers NO message). py credits the
    member's ``cards`` slots (0=Death, 1=Sol, 2=Moons, 3=Love). The existing
    'S' search command is untouched.
    """
    if not _matches_map(map_id, map_name, "AMBROSIA"):
        return NO_EFFECT
    card_index = {(4, 36): 3, (45, 52): 1, (6, 6): 2, (55, 27): 0}.get((x, y))
    if card_index is None:
        return NO_EFFECT
    player = getattr(member, "player", member)
    if player.cards[card_index] > 0:
        return None  # already carries the card — GBC markcard |= is idempotent
    player.cards[card_index] = player.cards[card_index] + 1
    return CARD_MESSAGE


def do_score(party) -> str:
    """SCORE: the party move counter (2026-11-14 amendment).

    GBC's ``doscore`` (menucmd3.c:872-876) is a "NO EFFECT." stub; the
    move-counter message is user-directed, reading the port's
    ``party.moves``.
    """
    return f"Thou hast achieved a score of {party.moves}!"


# --- shared prompt flows (both screens; text-log orchestration only) ---


def bribe_flow(text_log: TextLog, party: Party, x: int, y: int, game_map, creatures=None) -> None:
    """BRIBE: member choice → direction prompt → do_bribe.

    GBC checks the purse BEFORE the direction prompt (menucmd3.c:1028), so
    a member under 100 gold answers without the direction step.
    """
    def on_member(who: str) -> None:
        try:
            member = party.get_member(int(who.strip()) - 1)
        except (TypeError, ValueError):
            member = None
        if member is None:
            text_log.add_message(INVALID_MEMBER)
            return
        if member.is_disabled():
            text_log.add_message(INCAPACITATED)
            return

        def on_dir(d: str) -> None:
            direction = Direction.from_name_or_key(d)
            if direction is None:
                text_log.add_message(CANCELLED if not d.strip() else INVALID_DIRECTION)
                return
            message = do_bribe(member, x, y, direction, game_map, creatures=creatures)
            if message:
                text_log.add_message(message)

        text_log.prompt("BRIBE> Direction? (N,S,E,W):", callback=on_dir, single_char=True)

    _prompt_member(text_log, "BRIBE", on_member)


def steal_flow(text_log: TextLog, party: Party, x: int, y: int, game_map) -> None:
    """STEAL: member choice → direction prompt → do_steal.

    GBC answers "ONLY INSIDE." before the member selection
    (menucmd2.c:1455-1460), so the flow refuses first on non-town maps.
    """
    def on_member(who: str) -> None:
        try:
            member = party.get_member(int(who.strip()) - 1)
        except (TypeError, ValueError):
            member = None
        if member is None:
            text_log.add_message(INVALID_MEMBER)
            return
        if member.is_disabled():
            text_log.add_message(INCAPACITATED)  # CheckAlive, UltimaMisc.c:2276
            return

        def on_dir(d: str) -> None:
            direction = Direction.from_name_or_key(d)
            if direction is None:
                text_log.add_message(CANCELLED if not d.strip() else INVALID_DIRECTION)
                return
            for line in do_steal(party, member, x, y, direction, game_map):
                text_log.add_message(line)

        text_log.prompt("STEAL> Direction? (N,S,E,W):", callback=on_dir, single_char=True)

    _prompt_member(text_log, "STEAL", on_member)


def dig_flow(text_log: TextLog, party: Party, x: int, y: int, game_map) -> None:
    """DIG: member choice (GBC dodig credits players[pnum]) → do_dig."""

    def on_member(who: str) -> None:
        try:
            member = party.get_member(int(who.strip()) - 1)
        except (TypeError, ValueError):
            member = None
        if member is None:
            text_log.add_message(INVALID_MEMBER)
            return
        if member.is_disabled():
            text_log.add_message(INCAPACITATED)  # CheckAlive, UltimaMisc.c:2276
            return
        message = do_dig(party, member, x, y, game_map)
        if message:
            text_log.add_message(message)

    _prompt_member(text_log, "DIG", on_member)


def search_flow(text_log: TextLog, party: Party, x: int, y: int, game_map) -> None:
    """SEARCH (O-menu): member choice → do_search (Ambrosia card sites)."""

    def on_member(who: str) -> None:
        try:
            member = party.get_member(int(who.strip()) - 1)
        except (TypeError, ValueError):
            member = None
        if member is None:
            text_log.add_message(INVALID_MEMBER)
            return
        if member.is_disabled():
            text_log.add_message(INCAPACITATED)  # CheckAlive, UltimaMisc.c:2276
            return
        map_name = str(getattr(game_map, "name", "") or "")
        message = do_search(member, x, y, getattr(game_map, "id", map_name), map_name)
        if message:
            text_log.add_message(message)

    _prompt_member(text_log, "SEARCH", on_member)


# --- internal helpers ---


def _prompt_member(text_log: TextLog, label: str, callback) -> None:
    """The standard "Which party member? (1-4):" member-selection prompt."""
    text_log.prompt(f"{label}> Which party member? (1-4):", callback=callback, single_char=True)


def _is_sosaria_surface(game_map) -> bool:
    """GBC ``inside == 0``: only the Sosaria overworld (ult3.c:1150)."""
    return (
        game_map is not None
        and game_map.map_type == MapType.WORLD
        and game_map.id == MAP_NAME_TO_ID["SOSARIA"]
    )


def _matches_map(map_id, map_name: str, name: str) -> bool:
    """Match a map reference by id or display name (py id / GBC peermap map)."""
    if str(map_name).strip().upper() == name:
        return True
    try:
        return int(map_id) == MAP_NAME_TO_ID[name]
    except (TypeError, ValueError):
        return str(map_id).strip().upper() == name


def _steal_skill_bonus(member) -> int:
    """StealDisarmFail's class bonus (UltimaMisc.c:513-521): +0x80 Thief,
    +0x40 Barbarian/Illusionist/Ranger; not the Alchemist (user ruling
    2026-11-14; LW adds it -- ledger ask row)."""
    if getattr(member, "profession", None) == Profession.THIEF:
        return 0x80
    if getattr(member, "profession", None) in _STEAL_PLUS_64:
        return 0x40
    return 0


def add_item(stacks: dict, kind, equipped=None) -> None:
    """LairWare AddItem (UltimaMisc.c:504-508): +1, the stack capped at 99.

    LW counts the readied weapon / worn armour in its stack; the port keeps
    it out of ``stacks``, so the cap leaves room for it.
    """
    cap = _ITEM_CAP - (1 if equipped == kind else 0)
    stacks[kind] = min(cap, int(stacks.get(kind, 0)) + 1)
