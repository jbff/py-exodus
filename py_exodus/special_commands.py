"""Functional Other commands: bribe, steal, dig, pray, search, score.

USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): functional Other command
(GBC menucmd3.c:1019-1236; menucmd2.c:1440-1540; LW UltimaMisc.c:2262-2503).
The Java source never implemented these (the port's old ``_prompt_other``
handlers were inert stubs), so GBC is the rules authority here, with the
user-directed amendments from the 2026-11-14 controller notes:

- NO remake STEAL additions are ported (LW's GetChestBooty weapon roll is
  simplified per the amendment; KISS is NOT in U3 — the O-menu KISS branch
  was removed from both screens, falling through to "Nothing happened.").
- the town guard/NPC model carries no hostility system: GBC's steal-failure
  aggro (``monsters[p].attribs |= 0x11``, menucmd2.c:1508-1512) is DEFERRED
  (warning-only "Watch out!"); do not invent a system here.
- SCORE prints the party move counter; GBC's own SCORE entry
  (``doscore``, menucmd3.c:872-876) is a "NO EFFECT." stub, so the message
  is the user-directed amendment, not GBC text.

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
    TileAttrib,
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
PLAYER_DEAD = "Player dead."  # deaddat2/3 (menucmd2.c:253-255)
ONLY_INSIDE = "Only inside."  # onlyinsidedat (menucmd2.c:113-115)
NOTHING = "Nothing."  # emptydat2 (menucmd2.c:249-251)
WATCH_OUT = "Watch out!"  # watchoutdat (menucmd2.c:1487-1489)
STEAL_FAILED = "Failed."  # faileddat (menucmd2.c:1491-1493)
STEAL_SUCCESS = "Success."  # successdat (menucmd2.c:1500-1502)
EXOTICS = "Exotics."  # exoticdat (menucmd3.c:1105-1117)
CARD_MESSAGE = "You found a Card with Strange Marks."  # card1..3 (menucmd3.c:1142-1152)
VISION = "A vision appears: Yell 'EVOCARE'!"  # yellevo (menucmd3.c:1011-1013)

# GBC dosteal skill bonus: ``players[pnum].skill`` is the class index and
# grants +0x80 to the thief (index 9) and +0x40 to indices {0, 1, 5, 8}
# (menucmd2.c:1489-1500, same set at dungfunc.c:573-579). GBC's class order
# is its ``classes[]`` display array (u3tiles2.c:667-689):
# 0=Alchemist, 1=Barbarian, 2=Cleric, 3=Druid, 4=Fighter, 5=Illusionist,
# 6=Lark, 7=Paladin, 8=Ranger, 9=Thief, 10=Wizard — so the +0x64 set maps to
# ALCHEMIST, BARBARIAN, ILLUSIONIST, RANGER (per the 2026-11-14 controller
# ruling the py thieves alone take +128; the py Profession thief is GBC
# skill==9). Alchemist stands at GBC index 0 in that 4-profession set —
# the "no Alchemist" ruling voids the later remake additions, not GBC's set.
_STEAL_PLUS_64: tuple[Profession, ...] = (
    Profession.ALCHEMIST,  # GBC skill index 0
    Profession.BARBARIAN,  # GBC skill index 1
    Profession.ILLUSIONIST,  # GBC skill index 5
    Profession.RANGER,  # GBC skill index 8
)

# GBC dist-0 chain tile 0x3C..0x56 is the town people/vendor range; the py
# semantic equivalent is an NPC or map tile with the person/merchant rule
# (py people tiles rule in assets.py RULE_ATTRIBS "person"/"merchant").
_PEOPLE_RULES = ("person", "merchant")
# GBC dist-1 tile 0x0B / 0x16 → py door / locked_door; dist-2 0x0C → chest.
_DOOR_RULES = ("door", "locked_door")

_STEAL_DOOR_TILE = TileDef(index=35, name="door", rule="door", attribs=TileAttrib.DOOR)

# GBC weapon/armor lists index their stacks 1..7 / 1..3; py list(...) order
# matches (list(WeaponType)[1..7] = DAGGER..SWORD_2H,
# list(ArmorType)[1..3] = CLOTH..CHAIN).
_WEAPON_ORDER = list(WeaponType)
_ARMOR_ORDER = list(ArmorType)

_STACK_CAP = 9
_GOLD_CAP = 9999


def do_bribe(
    party: Party,
    member: PartyMember,
    x: int,
    y: int,
    direction: Direction,
    game_map: GameMap | None,
    creatures: list | None = None,
) -> str:
    """BRIBE: pay a town guard 100 gold to leave (GBC menucmd3.c:1019-1103).

    ``party`` is accepted for the brief's signature but unused: GBC checks and
    deducts the ACTING member's own purse (``players[pnum].gold``). Success is
    silent in GBC — "" means no message. Removing the py guard NPC restores
    the underlying tile for free: the map grid already carries the
    ``underlying`` byte (map_build writes it at load), which is the py
    equivalent of GBC restoring its SRAM map copy.
    """
    if getattr(member, "gold", 0) < 100:
        return CANNOT_PAY  # menucmd3.c:1028
    if game_map is None or direction is None:
        return NO_EFFECT

    tx, ty = x + direction.dx, y + direction.dy

    guard_npc = _find_guard_npc(game_map, tx, ty)
    if guard_npc is None and creatures:
        for creature in list(creatures):
            if (
                int(creature.get("x", -1)) == tx
                and int(creature.get("y", -1)) == ty
                and str(creature.get("tile", "")).lower() == "guard"
            ):
                creatures.remove(creature)
                member.gold -= 100
                return ""
    if guard_npc is not None:
        game_map.npcs.remove(guard_npc)
        member.gold -= 100
        return ""
    # No guard at the target: GBC's noeffect branch (any non-0x18 tile),
    # menucmd3.c:1092-1099 — no gold leaves the purse.
    return NO_EFFECT


def do_steal(
    party: Party,
    member: PartyMember,
    x: int,
    y: int,
    direction: Direction,
    game_map: GameMap | None,
    rng=None,
) -> list[str]:
    """STEAL: shoplift the chest behind the shopkeeper (GBC menucmd2.c:1440-1564).

    Returns the log lines (success carries the gold and bonus item lines).
    The chest the chain finds is sealed as a door on success (GBC writes
    0x0B, menucmd2.c:1561-1564).
    """
    if not _is_town_map(game_map):
        return [ONLY_INSIDE]  # GBC dosteal's ``!inside`` guard, menucmd2.c:1456
    if member.is_dead():
        return [PLAYER_DEAD]  # deaddat2, menucmd2.c:1463-1469

    chain = _steal_chain(game_map, x, y, direction)
    if chain is None:
        return [NOTHING]  # emptydat2 (wrong chain), menucmd2.c:1578-1584
    chest = chain[2]

    roll = (rng or random).randrange
    skill = getattr(member, "dex", 0) + _steal_skill_bonus(member)
    if roll(256) >= skill:
        if roll(4) == 0:
            # GBC flags every 0x18 monster hostile (attribs |= 0x11) here
            # (menucmd2.c:1505-1512). The py town NPC model has no hostility
            # flag — warning only, aggro deferred (documented deviation).
            return [WATCH_OUT]
        return [STEAL_FAILED]

    lines = [STEAL_SUCCESS]
    gold = roll(100) | 0x30
    if gold > 100:
        gold -= 100
    member.gold = max(0, min(_GOLD_CAP, member.gold + gold))
    lines.append(f"You stole {gold} Gold.")  # formatnumber + "GOLD", :1524-1529

    if roll(4) == 0:  # GBC make_rnd(0) < 0x40 (menucmd2.c:1530)
        bonus = _steal_bonus_item(member, roll)
        if bonus is not None:
            lines.append(bonus)

    # GBC seals the looted chest as a plain door (menucmd2.c:1561-1564).
    game_map.set_tile(chest[0], chest[1], _STEAL_DOOR_TILE)
    return lines


def do_dig(party: Party, member: PartyMember, x: int, y: int, game_map) -> str:
    """DIG: the Sosaria exotic-equipment sites (GBC menucmd3.c:1120-1133).

    GBC's ``inside != 0`` guard confines DIG to the Sosaria surface, so towns
    and dungeons refuse with the GBC no-effect message. ``party`` matches the
    brief's signature; the grant lands on the acting member's stacks.
    """
    if not _is_sosaria_surface(game_map):
        return NO_EFFECT  # GBC noeffectdat for ``inside != 0``

    if (x, y) == (33, 3):
        if _bump_stack(member.weapons, WeaponType.EXOTIC):
            pass  # GBC silently skips the grant at the stack cap (:1130)
        return EXOTICS
    if (x, y) == (19, 44):
        if _bump_stack(member.armors, ArmorType.EXOTIC):
            pass
        return EXOTICS
    return NO_EFFECT


def do_pray(x: int, y: int, map_id, map_name: str = "") -> str:
    """PRAY: the EVOCARE vision sites (GBC menucmd3.c:1199-1206).

    The GBC site is the EXODUS map at (48,48); the port's pre-existing
    Yew-area hint is kept as well — the union of both references works
    (user ruling 2026-11-14). GBC also flags ``party_specials |= 0x0100``
    in the dopray branch, for which the port's model has no slot.
    """
    if _matches_map(map_id, map_name, "EXODUS") and (x, y) == (48, 48):
        return VISION
    # Kept pre-existing Yew-area hint (legacy "10"/"yew" ids, 44..52 box).
    if str(map_id) in ("10", "yew", "YEW") and 44 <= x <= 52 and 44 <= y <= 52:
        return VISION
    return NO_EFFECT


def do_search(member: PartyMember, x: int, y: int, map_id, map_name: str = "") -> str:
    """SEARCH (O-menu): the Ambrosia card sites (GBC menucmd3.c:1151-1197).

    GBC gates the four sites on ``peermap==12`` (Ambrosia — py map id 13)
    and credits ``players[pnum].markcard`` per member; py credits the
    member's ``cards`` slots (0=Death, 1=Sol, 2=Moons, 3=Love). The existing
    'S' search command is untouched.
    """
    if not _matches_map(map_id, map_name, "AMBROSIA"):
        return NO_EFFECT
    card_index = {(4, 36): 3, (45, 52): 1, (6, 6): 2, (55, 27): 0}.get((x, y))
    if card_index is None:
        return NO_EFFECT
    player = getattr(member, "player", member)
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
        if member.is_dead():
            text_log.add_message(PLAYER_DEAD)
            return
        if getattr(member, "gold", 0) < 100:
            text_log.add_message(CANNOT_PAY)
            return

        def on_dir(d: str) -> None:
            direction = Direction.from_name_or_key(d)
            if direction is None:
                text_log.add_message(CANCELLED if not d.strip() else INVALID_DIRECTION)
                return
            message = do_bribe(
                party, member, x, y, direction, game_map, creatures=creatures
            )
            if message:
                text_log.add_message(message)

        text_log.prompt("BRIBE> Direction? (N,S,E,W):", callback=on_dir, single_char=True)

    _prompt_member(text_log, "BRIBE", on_member)


def steal_flow(text_log: TextLog, party: Party, x: int, y: int, game_map) -> None:
    """STEAL: member choice → direction prompt → do_steal.

    GBC answers "ONLY INSIDE." before the member selection
    (menucmd2.c:1455-1460), so the flow refuses first on non-town maps.
    """
    if not _is_town_map(game_map):
        text_log.add_message(ONLY_INSIDE)
        return

    def on_member(who: str) -> None:
        try:
            member = party.get_member(int(who.strip()) - 1)
        except (TypeError, ValueError):
            member = None
        if member is None:
            text_log.add_message(INVALID_MEMBER)
            return
        if member.is_dead():
            text_log.add_message(PLAYER_DEAD)
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
        if member.is_dead():
            text_log.add_message(PLAYER_DEAD)
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
        map_name = str(getattr(game_map, "name", "") or "")
        message = do_search(member, x, y, getattr(game_map, "id", map_name), map_name)
        if message:
            text_log.add_message(message)

    _prompt_member(text_log, "SEARCH", on_member)


# --- internal helpers ---


def _prompt_member(text_log: TextLog, label: str, callback) -> None:
    """The standard "Which party member? (1-4):" member-selection prompt."""
    text_log.prompt(f"{label}> Which party member? (1-4):", callback=callback, single_char=True)


def _is_town_map(game_map) -> bool:
    """GBC ``inside`` for steals: towns/castles (city-type 64x64 maps)."""
    return game_map is not None and game_map.map_type == MapType.CITY


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


def _find_guard_npc(game_map, x: int, y: int):
    """The py guard: a town map NPC with the ``guard`` tile (GBC tile 0x18)."""
    for npc in game_map.npcs:
        if npc.x == x and npc.y == y:
            tile_name = str(getattr(npc, "tile_name", "")).lower()
            if tile_name == "guard":
                return npc
    return None


def _steal_chain(game_map, x: int, y: int, direction):
    """GBC dosteal's 3-tile chain: person → door/locked door → chest.

    The chain reads the DISPLAY tiles one, two, and three tiles along the
    direction (menucmd2.c:1465-1493: 0x3C..0x56, then 0x0B/0x16, then 0x0C).
    Returns (person, door, chest) coordinate tuples or None.
    """
    if game_map is None or direction is None:
        return None
    d = direction
    person = (x + d.dx, y + d.dy)
    door = (x + 2 * d.dx, y + 2 * d.dy)
    chest = (x + 3 * d.dx, y + 3 * d.dy)

    if not _person_displayed_at(game_map, *person):
        return None
    door_tile = game_map.get_tile(*door)
    if door_tile is None or getattr(door_tile, "rule", "") not in _DOOR_RULES:
        return None
    chest_tile = game_map.get_tile(*chest)
    if chest_tile is None or (
        getattr(chest_tile, "rule", "") != "chest"
        and not (getattr(chest_tile, "attribs", 0) & TileAttrib.CHEST)
    ):
        return None
    return person, door, chest


def _person_displayed_at(game_map, x: int, y: int) -> bool:
    """GBC reads its display buffer, which shows NPC sprites — py checks the
    NPC standing at (x, y) (person/merchant rule tiles), falling back to a
    literal map-level person tile."""
    for npc in game_map.npcs:
        if npc.x == x and npc.y == y:
            rule = str(getattr(getattr(npc, "tile_def", None), "rule", "") or "").lower()
            if rule in _PEOPLE_RULES:
                return True
            name = str(getattr(npc, "tile_name", "")).lower()
            return name in (
                "fighter", "cleric", "wizard", "thief", "ranger", "guard",
                "jester", "merchant", "lord_british",
            )
    tile = game_map.get_tile(x, y)
    return tile is not None and getattr(tile, "rule", "") in _PEOPLE_RULES


def _steal_skill_bonus(member) -> int:
    """GBC dosteal's class bonus: +0x80 thief, +0x40 for {0,1,5,8}."""
    if getattr(member, "profession", None) == Profession.THIEF:
        return 0x80
    if getattr(member, "profession", None) in _STEAL_PLUS_64:
        return 0x40
    return 0


def _steal_bonus_item(member, roll) -> str | None:
    """The 25% extra loot line: a weapon by GBC index 1..7, falling to an
    armor index 1..3 when the weapon stack is capped (GBC menucmd2.c:
    1521-1560 rolls the weapon first; the 2026-11-14 amendment fixes the
    LW GetChestBooty-style widths). None when both stacks are capped."""
    weapon = _WEAPON_ORDER[roll(7) + 1]
    if _bump_stack(member.weapons, weapon):
        return f"and {weapon.name.capitalize()}!"
    armor = _ARMOR_ORDER[roll(3) + 1]
    if _bump_stack(member.armors, armor):
        return f"and {armor.name.capitalize()}!"
    return None


def _bump_stack(stacks: dict, kind) -> bool:
    """Increment an equipment stack up to GBC's 9 cap; False when capped."""
    current = int(stacks.get(kind, 0))
    if current >= _STACK_CAP:
        return False
    stacks[kind] = current + 1
    return True
