"""Melee and ranged combat calculations, hit/damage rolls, and projectile path tracing."""
from __future__ import annotations

from dataclasses import dataclass, field, replace as _dc_replace
from enum import Enum
import random
from typing import TYPE_CHECKING, Any

from py_exodus.constants import Direction, Status, TileAttrib
from py_exodus.entities.character import EXP_CAP

if TYPE_CHECKING:
    from py_exodus.entities.character import Character
    from py_exodus.entities.defs import ArmorDef, WeaponDef
    from py_exodus.world.map import ConflictMap


class AttackResult(str, Enum):
    """Result of a combat attack."""

    NONE = "none"
    HIT = "hit"
    MISS = "miss"
    BLOCKED = "blocked"


@dataclass
class AttackVector:
    """Vector representation of an attack target coordinate and distance."""

    x: int
    y: int
    distance: int = 1
    result: AttackResult = AttackResult.NONE


@dataclass
class AttackResolution:
    """Detailed outcome of a melee or ranged attack."""

    hit: bool
    damage: int = 0
    killed: bool = False
    result: AttackResult = AttackResult.NONE
    target_pos: tuple[int, int] | None = None
    projectile_path: list[tuple[int, int]] = field(default_factory=list)
    poisoned: bool = False
    stolen_item: str | None = None
    stolen_food: int = 0
    stolen_gold: int = 0
    message: str = ""


def roll_hit(attacker_dex: int, defender_defense: int = 0) -> bool:
    """The party's to-hit roll, LairWare CombatAttack
    (UltimaSpellCombat.c:1336-1341)::

        if (RandNum(0, 255) < 128) {
            if (Player[rosNum][19] < RandNum(0, 99)) {
                Missed();

    Half the swings face a dexterity check, missing when DEX is below a 0-99
    roll; the other half always land. The monster plays no part
    (``defender_defense`` is ignored). Replaces Java ``Utils.attackHit``.
    """
    if random.randint(0, 255) < 128:
        if attacker_dex < random.randint(0, 99):
            return False
    return True


def lw_weapon_index(weapon: Any) -> int:
    """LairWare Player[48]: 0 hands .. 15 exotic (the WeaponType order)."""
    from py_exodus.constants import WeaponType

    value = getattr(weapon, "type", weapon)
    value = getattr(value, "value", value)
    try:
        return list(WeaponType).index(WeaponType(str(value).upper()))
    except (ValueError, TypeError):
        return 0


def calculate_player_damage(
    character: Character, weapon_def: WeaponDef | None = None
) -> int:
    """Damage of a party member's landed blow, LairWare CombatAttack
    (UltimaSpellCombat.c:1349-1352)::

        damage = RandNum(0, (Player[rosNum][18] | 1));
        damage += Player[rosNum][18] / 2;
        damage += Player[rosNum][48] * 3;
        damage += 4;

    STR is byte 18 and the readied weapon's number byte 48 (hands 0 ..
    exotic 15). Replaces Java ``PartyMember.getDamage``.
    """
    strength = int(getattr(character, "str", 0) or 0)
    return (
        random.randint(0, strength | 1)
        + strength // 2
        + lw_weapon_index(weapon_def) * 3
        + 4
    )


def calculate_monster_damage(basehp: int) -> int:
    """Calculate damage dealt by a monster matching classic Ultima III formula.

    Java truth: ``Creature.getDamage`` (Creature.java:465-472) —
    x = nextInt(basehp >> 2); damage = (x >> 4) + ((x >> 2) & 0xFC) + x % 10.
    There is NO floor: a small monster deals 0 damage.
    """
    shift_val = basehp >> 2
    if shift_val <= 0:
        x = 0
    else:
        x = random.randint(0, shift_val - 1)

    damage = (x >> 4) + ((x >> 2) & 0xFC) + (x % 10)
    return damage


# USER-DIRECTED GBC-RULES DEVIATION (2026-11-16): GBC battle3.c:354-368 adds a
# terrain bonus to monster melee damage (+10 dungeon, +0 Sosaria surface, +30
# Ambrosia / Castle British / Castle of Death, +20 other towns/interiors).
# The GBC inside/peermap table maps onto py map ids; the dungeon maps are the
# maps.xml type="dungeon" rows.
_DUNGEON_MAP_IDS: frozenset | None = None


def _dungeon_map_ids() -> frozenset:
    """Lazily resolved ids of the maps.xml type="dungeon" rows."""
    global _DUNGEON_MAP_IDS
    if _DUNGEON_MAP_IDS is None:
        import py_exodus.assets as assets

        _DUNGEON_MAP_IDS = frozenset(
            assets.MAP_NAME_TO_ID[name]
            for name in ("PERINIAN", "DARDIN", "MINE", "FIRE", "DOOM", "SNAKE", "TIME")
        )
    return _DUNGEON_MAP_IDS


# LairWare Combat (UltimaSpellCombat.c:867): starting-HP ceiling per monster
# type, indexed by (gMonType / 2) & 0x0F, i.e. the LW tile index & 15.
LW_MONHPSTART = (0x20, 0x20, 0xF0, 0xF0, 0xC0, 0x60, 0xA0, 0x80,
                 0x30, 0x50, 0x70, 0xA0, 0xC0, 0xE0, 0xF0, 0xF0)
# Port creature tile -> LairWare tile index (Tiles.plist). Variants share
# their base type's gMonType. The port's "ranger" is a fighter variant.
LW_TILE_INDEX = {
    "grass": 1, "floor": 8, "chest": 9, "horse": 10,
    "serpent": 13, "squid": 14, "man-o-war": 14, "pirate": 15,
    "merchant": 16, "jester": 17, "guard": 18, "lord_british": 19,
    "fighter": 20, "ranger": 20, "cleric": 21, "wizard": 22, "thief": 23,
    "orc": 24, "skeleton": 25, "giant": 26, "daemon": 27, "pincher": 28,
    "dragon": 29, "balron": 30, "exodus": 31,
}


def lw_monhpstart(monster: Any) -> int:
    """LairWare monhpstart[] for this monster's type (unknown: from basehp)."""
    for attr in ("tile", "tile_name", "name"):
        key = str(getattr(monster, attr, "") or "").lower().replace(" ", "_")
        if key in LW_TILE_INDEX:
            return LW_MONHPSTART[LW_TILE_INDEX[key] & 0x0F]
    return int(getattr(monster, "basehp", 48) or 48)


def _armor_index(target_player: Any) -> int:
    """LW Player[40]: 0 none .. 7 exotic (the ArmorType order)."""
    from py_exodus.constants import ArmorType

    armor = getattr(target_player, "armor", None)
    try:
        return list(ArmorType).index(ArmorType(getattr(armor, "value", armor)))
    except (ValueError, TypeError):
        return 0


def lw_monster_hits(target_player: Any, context_map_id: int | None) -> bool:
    """LairWare monster attack roll (UltimaSpellCombat.c:1207-1216): in Castle
    Exodus a defender without exotic armor is hit automatically; otherwise
    RandNum(0, armor + 16) < 8 hits (exotic: 8 in 24)."""
    import py_exodus.assets as assets

    if context_map_id == assets.MAP_NAME_TO_ID["EXODUS"] and _armor_index(target_player) != 7:
        return True
    return lw_armor_roll(target_player)


def lw_armor_roll(target_player: Any) -> bool:
    """LairWare: RandNum(0, armor + 16) < 8 hits (exotic armor: 8 in 24)."""
    return random.randint(0, _armor_index(target_player) + 0x10) < 8


def lw_monster_damage(monster: Any, target_player: Any, context_map_id: int | None) -> int:
    """LairWare hit damage (UltimaSpellCombat.c:1221-1226): RandNum(0,
    (monhpstart/8 + the target's max HP/100) | 1) + 1, then the location
    bonus. It grows with the victim's max HP, so strong parties stay tested."""
    return lw_monster_damage_roll(monster, target_player) + monster_damage_bonus(context_map_id)


def lw_monster_damage_roll(monster: Any, target_player: Any) -> int:
    """The random part of a LairWare hit, before the location bonus."""
    max_hp = int(getattr(target_player, "max_hp", 0) or 0)
    ceiling = ((lw_monhpstart(monster) // 8) + max_hp // 100) | 1
    return random.randint(0, ceiling) + 1


def monster_damage_bonus(context_map_id: int | None) -> int:
    """LairWare location bonus on every monster hit: (g835E & 3) * 16
    (UltimaSpellCombat.c:1226), g835E being Party[3] before the battle:
    Sosaria 0 -> +0, dungeon 1 -> +16, town 2 -> +32, castle 3 (Castle
    British, Castle Exodus) -> +48, Ambrosia 255 -> +48. An unknown context
    (None) counts as a town. Replaces the GBC 0/10/20/30 tiers (LairWare is
    the authority, user ruling 2026-11-22)."""
    if context_map_id is None:
        return 32
    if context_map_id in _dungeon_map_ids():
        return 16
    import py_exodus.assets as assets

    if context_map_id == assets.MAP_NAME_TO_ID["SOSARIA"]:
        return 0
    if context_map_id in (
        assets.MAP_NAME_TO_ID["BRITISH"],
        assets.MAP_NAME_TO_ID["EXODUS"],
        assets.MAP_NAME_TO_ID["AMBROSIA"],
    ):
        return 48
    return 32


# USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the GBC magic-creature tiles
# get a no-LOS "magic poke". The tile set mirrors creatures.xml: man-o-war is
# tile="squid" there, so both spellings are accepted (GBC battle3.c:856-866)
_MAGIC_POKE_TILES: frozenset[str] = frozenset(
    {"serpent", "man-o-war", "squid", "wizard", "daemon", "dragon", "balron"}
)


def _member_is_dead(member: Any) -> bool:
    is_dead = getattr(member, "is_dead", None)
    if callable(is_dead):
        return bool(is_dead())
    if is_dead is not None:
        return bool(is_dead)
    return (
        getattr(member, "status", None) == Status.DEAD
        or getattr(member, "hp", 1) <= 0
    )


def member_is_adjacent_to_monster(member: Any, monster: Any) -> bool:
    """Chebyshev distance 1 — a member standing beside the monster (or on it)."""
    dx = abs(getattr(member, "x", 999) - getattr(monster, "x", 0))
    dy = abs(getattr(member, "y", 999) - getattr(monster, "y", 0))
    return max(dx, dy) <= 1


def monster_has_magic_attribute(monster: Any) -> bool:
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): whether the creature's
    tile is one of the six GBC magic-poke tiles (GBC battle3.c:856-866)."""
    tile = str(getattr(monster, "tile", "") or "").strip().lower()
    return tile in _MAGIC_POKE_TILES


def try_monster_magic_poke(
    monster: Any,
    members: list[Any] | None,
    context_map_id: int | None = None,
) -> AttackResolution | None:
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the GBC no-LOS magic
    poke — a magic-creature monster with NO living party member adjacent rolls
    make_rnd(0xC1)&0x80 (random.randrange(193) & 0x80: ~34% success) and, on
    success, blasts a RANDOM living member directly with the normal
    single-target (melee) damage roll through the apply_damage chokepoint;
    no LOS check and no bolt trace. Returns None (and consumes nothing if the
    tile or the adjacency gate fails) when the caller must fire its normal
    bolt instead (GBC battle3.c:856-866)"""
    if not monster_has_magic_attribute(monster):
        return None
    living = [m for m in (members or []) if not _member_is_dead(m)]
    if not living or any(member_is_adjacent_to_monster(m, monster) for m in living):
        return None
    if (random.randrange(193) & 0x80) == 0:
        return None  # failed the ~34% make_rnd(0xC1)&0x80 draw
    victim = random.choice(living)
    res = resolve_monster_melee_attack(
        monster, victim, context_map_id=context_map_id
    )
    # The blast went off whatever the victim's individual save said: the
    # damage lands through the melee roll (0 on a miss), and the caller's
    # bolt trace is skipped. Item 3 note: GBC prints no text on this branch
    # (battle3.c:856-866 — magiceffect2(3) + damageplayer, no
    # writegamemessage) and Java's ranged magic bolt logs nothing; the
    # "Magic Blast!" line stays as the branch's player feedback per the
    # item-3 ruling to keep GBC-adopted mechanic strings and note them.
    return _dc_replace(res, hit=True, message="Magic Blast!")


def get_relative_direction_mask(width: int, height: int, to_x: int, to_y: int, from_x: int, from_y: int) -> int:
    """Java ``Utils.getRelativeDirection`` (Utils.java:359-401), fixed border
    (every combat map is MapBorderBehavior.fixed): the bitmask of the single
    axis-aligned directions that lead from (from_x, from_y) toward (to_x, to_y).
    """
    dx = from_x - to_x
    dy = from_y - to_y
    dirmask = 0
    if dx < 0:
        dirmask |= Direction.EAST.mask
    elif dx > 0:
        dirmask |= Direction.WEST.mask
    if dy < 0:
        dirmask |= Direction.SOUTH.mask
    elif dy > 0:
        dirmask |= Direction.NORTH.mask
    return dirmask


def trace_directional_path(
    combat_map: ConflictMap,
    dirmask: int,
    start_x: int,
    start_y: int,
    min_distance: int = 1,
    max_distance: int = 11,
    attack_through_objects: bool = False,
    check_for_creatures: bool = False,
    monsters: list[Any] | None = None,
) -> list[tuple[int, int]]:
    """Java ``Utils.getDirectionalActionPath`` (Utils.java:446-494) port.

    Walks the mask — which may hold TWO direction bits, so the "bolt" steps
    diagonally — up to ``max_distance`` tiles. The action stops at the map
    edge, or on the first blocking tile (unwalkable without rangeattackover,
    unless ``attack_through_objects``); the blocking tile itself is included
    in the path exactly as in Java.
    """
    from py_exodus.constants import TileAttrib as _TA

    path: list[tuple[int, int]] = []
    nx = start_x
    ny = start_y
    monster_positions: set[tuple[int, int]] = set()
    if check_for_creatures and monsters:
        for m in monsters:
            if not getattr(m, "is_dead", False):
                monster_positions.add((m.x, m.y))

    for _ in range(min_distance, max_distance + 1):
        if not (0 <= nx < combat_map.width and 0 <= ny < combat_map.height):
            break

        monster_blocked = (nx, ny) in monster_positions
        tile = combat_map.get_tile(nx, ny)
        tile_blocked = False
        if tile is not None:
            attribs = getattr(tile, "attribs", _TA.NONE)
            tile_blocked = bool(attribs & _TA.UNWALKABLE) and not bool(
                attribs & _TA.RANGEATTACKOVER
            )
        blocked = tile_blocked or monster_blocked
        can_attack_over = attack_through_objects and tile is not None

        path.append((nx, ny))
        if blocked and not can_attack_over:
            break

        if dirmask & Direction.NORTH.mask:
            ny -= 1
        if dirmask & Direction.SOUTH.mask:
            ny += 1
        if dirmask & Direction.EAST.mask:
            nx += 1
        if dirmask & Direction.WEST.mask:
            nx -= 1

    return path


def trace_projectile_path(
    combat_map: ConflictMap,
    start_x: int,
    start_y: int,
    direction: Direction,
    max_range: int = 16,
    attack_through_objects: bool = False,
    monsters: list[Any] | None = None,
    players: dict[int, tuple[int, int]] | None = None,
    is_player_attack: bool = True,
) -> list[tuple[int, int]]:
    """Trace directional projectile path until stopped by boundary, wall, or target creature.

    Stops at:
      - Map edge (0 <= x < 11, 0 <= y < 11)
      - Solid wall / unwalkable tile without rangeattackover (unless weapon attacks through objects)
      - Living target creature (monsters for player attacks; players for monster attacks).
        Player attacks pass cleanly through party members.
    """
    path: list[tuple[int, int]] = []
    nx = start_x
    ny = start_y

    monster_positions: set[tuple[int, int]] = set()
    if monsters:
        for m in monsters:
            if not getattr(m, "is_dead", False) and getattr(m, "hp", 1) > 0:
                monster_positions.add((m.x, m.y))

    player_positions_set: set[tuple[int, int]] = set()
    if players:
        for pos in players.values():
            player_positions_set.add(pos)

    for _ in range(1, max_range + 1):
        nx += direction.dx
        ny += direction.dy

        # Boundary check
        if not (0 <= nx < combat_map.width and 0 <= ny < combat_map.height):
            break

        path.append((nx, ny))

        # Check if hitting target (monsters for player attack, players for monster attack)
        if is_player_attack:
            if (nx, ny) in monster_positions:
                break
        else:
            if (nx, ny) in player_positions_set:
                break

        # Check wall / obstacle blocking
        tile = combat_map.get_tile(nx, ny)
        if tile is not None and not attack_through_objects:
            attribs = getattr(tile, "attribs", TileAttrib.NONE)
            is_unwalkable = bool(attribs & TileAttrib.UNWALKABLE)
            can_range_over = bool(attribs & TileAttrib.RANGEATTACKOVER)
            if is_unwalkable and not can_range_over:
                # Wall reached - projectile stops here
                break

    return path


def _deal_monster_damage_to_member(target_player: Any, damage: int) -> bool:
    """Java ``PartyMember.applyDamage(damage, true)`` (Party.java:556-577): the
    Task 2 chokepoint. Falls back to the pre-chokepoint direct mutation for
    bare ``Character`` stand-ins (tests) that carry no ``apply_damage``."""
    apply_damage = getattr(target_player, "apply_damage", None)
    if callable(apply_damage):
        return bool(apply_damage(damage, True))
    new_hp = target_player.hp - damage
    if new_hp < 0:
        target_player.status = Status.DEAD
        new_hp = 0
    target_player.hp = new_hp
    return True


def creature_wound_message(creature: Any) -> str:
    """Java's single canonical per-hit creature status line.

    ``Utils.damageCreature`` (Utils.java:617-653) runs after every
    player-caused damage application: on a kill it prints
    ``"%s Killed! Exp. %d"`` (Utils.java:628, the byplayer branch), otherwise
    the wound tier of ``Creature.getDamageStatus`` (Creature.java:390-401)
    formatted by ``Utils.java:634-650``. Java names the creature, never the
    attacker, and prints nothing about the raw damage number.

    Tier thresholds are integer divisions of the creature's ``basehp``
    (Creature.java:391-393): critical < basehp/4, heavily < basehp/2, lightly
    < crit+heavy; everything above is "Barely Wounded!".
    """
    name = getattr(creature, "name", "Creature")
    hp = getattr(creature, "hp", 0)
    if hp <= 0:
        return f"{name} Killed! Exp. {getattr(creature, 'exp', 0)}"  # Utils.java:628
    basehp = getattr(creature, "basehp", 48) or 48
    crit_threshold = basehp // 4
    heavy_threshold = basehp // 2
    light_threshold = crit_threshold + heavy_threshold
    if hp < crit_threshold:
        status = "Critical!"  # Utils.java:638
    elif hp < heavy_threshold:
        status = "Heavily Wounded!"  # Utils.java:642
    elif hp < light_threshold:
        status = "Lightly Wounded!"  # Utils.java:646
    else:
        status = "Barely Wounded!"  # Utils.java:650
    return f"{name} {status}"  # "{name} {status}" per Utils.java:634-650


def resolve_player_attack(
    character: Character,
    weapon_def: WeaponDef | None,
    target_monster: Any,
    distance: int = 1,
) -> AttackResolution:
    """Resolve an attack by a player character against a monster."""
    # Check weapon range constraint.
    # Java `attackAt` (Utils.java:841-845): an absolute-range weapon fired at
    # the wrong distance returns NONE and logs NOTHING — the range check is
    # silent, so this is an empty message (the arena skips writing it).
    if weapon_def is not None and distance > weapon_def.range:
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(target_monster.x, target_monster.y),
            message="",
        )

    # LairWare CombatAttack dexterity check (UltimaSpellCombat.c:1336-1341).
    is_hit = roll_hit(character.dex)
    if not is_hit:
        # Java's miss line (Utils.java:853): just `"Missed!"` — the GBC miss
        # message is the same terse form (battle.c missmsg, battle.c:96-99;
        # printed at battle.c:657-659).
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(target_monster.x, target_monster.y),
            message="Missed!",
        )

    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): a landed player hit vs
    # the guard tile (0x18) or Lord British tile (0x19) deals damage 0 and
    # never kills; the guard exemption applies in normal mode too, since
    # py-exodus has no GBC extragame hard-mode flag (GBC battle.c:646-648).
    target_tile = (getattr(target_monster, "tile", "") or "").lower()
    if target_tile in ("guard", "lord_british"):
        # Message parity (item 3): GBC prints no text on that zero-damage
        # branch (battle.c:640-657 shows showmonsterhit → "HIT" and the
        # damage=0 write with no writegamemessage), so Java governs: a landed
        # hit runs the wound-status line through damageCreature with the HP
        # write skipped (the Utils.java:621 lord_british exemption), i.e. the
        # creature's current tier.
        return AttackResolution(
            hit=True,
            damage=0,
            killed=False,
            result=AttackResult.HIT,
            target_pos=(target_monster.x, target_monster.y),
            message=creature_wound_message(target_monster),
        )

    # Hit succeeds - calculate damage
    damage = calculate_player_damage(character, weapon_def)
    target_monster.hp = max(0, target_monster.hp - damage)
    killed = target_monster.hp <= 0

    if killed:
        exp_award = getattr(target_monster, "exp", 0)
        # Java Utils.dealDamage(PartyMember, Creature, damage) → awardXP
        # (Party.java:372-375, Utils.java:604-611): every player-caused death
        # pays the creature's EXP, capped at 9899 (LairWare AddExp,
        # UltimaMisc.c:475-477).
        award = getattr(character, "award_xp", None)
        if callable(award):
            award(exp_award)
        else:
            character.exp = min(EXP_CAP, character.exp + exp_award)

    # Message parity (item 3): whatever the outcome, Java's
    # ``Utils.damageCreature`` (Utils.java:617-653) is the only player
    # visible line — "{name} Killed! Exp. {n}" on death (Utils.java:628),
    # else the wound tier (Utils.java:634-650). No damage number, no
    # attacker name.
    msg = creature_wound_message(target_monster)

    return AttackResolution(
        hit=True,
        damage=damage,
        killed=killed,
        result=AttackResult.HIT,
        target_pos=(target_monster.x, target_monster.y),
        message=msg,
    )


def _decrement_lowest_stack(counts: dict[Any, int] | None) -> bool:
    """Decrement one owned stack, lowest index first (dict insertion order).

    GBC ``((players[pnum].armors)[itemnum])--`` / ``weapons`` equivalent:
    only a non-empty (owned) stack is decremented; nothing stolen otherwise.
    """
    if not counts:
        return False
    for item_type, count in counts.items():
        if count > 0:
            counts[item_type] = count - 1
            return True
    return False


def resolve_monster_melee_attack(
    monster: Any,
    target_player: Any,
    armor_def: ArmorDef | None = None,
    context_map_id: int | None = None,
) -> AttackResolution:
    """Resolve a monster's melee ATTACK (Java CombatScreen.java:720-745).

    The hit roll is forced when the combat happens on the Castle of Death
    (Maps.EXODUS) and the defender is not wearing EXOTIC armor
    (CombatScreen.java:723). A hit deals ``Creature.getDamage`` through the
    ``PartyMember.applyDamage(_, True)`` chokepoint; a surviving target can be
    robbed (CombatScreen.java:733-743). Java logs nothing here (sounds only).

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): on-hit specials follow the
    GBC port — poisoner creatures roll 1-in-4 melee poison (battle3.c:267-277)
    and the thief steals equipment (battle3.c:280-301) — instead of Java's
    food/gold-only theft.
    """
    import py_exodus.assets as assets

    # LairWare hit roll (user ruling 2026-11-22: LairWare monster attacks).
    is_hit = lw_monster_hits(target_player, context_map_id)

    if not is_hit:
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
            message="",
        )

    # LairWare damage, location bonus included (UltimaSpellCombat.c:1221-1226).
    damage = lw_monster_damage(monster, target_player, context_map_id)
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): a NECORP-weakened creature
    # deals half its melee damage. GBC NECORP clamps the monster's hp to 5 AND
    # sets monsterpower=10 (battle.c:1361-1373; LW UltimaSpellCombat.c:498-520
    # sets MonsterHP[mon]=5 exactly); GBC's monsterpower field scales the
    # creature's damage output, so the py-side approximation halves the
    # terrain-bonused melee total — deterministic floor-halving, no randomness.
    # Ranged bolts do not consult monsterpower in GBC and are not affected.
    if getattr(monster, "weakened", False):
        damage //= 2
    # Java: Utils.dealDamage(Creature, target) → applyDamage(damage, true);
    # False (no effect) when the member was already DEAD.
    applied = _deal_monster_damage_to_member(target_player, damage)
    killed = applied and getattr(target_player, "status", None) == Status.DEAD

    poisoned = False
    stolen_item: str | None = None
    stolen_food = 0
    stolen_gold = 0

    if applied and not killed:
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): poisoner melee hits
        # roll 1-in-4 poison on a surviving, not-yet-poisoned target (GBC
        # battle3.c:272-277); Java's melee branch has no poison path.
        if (
            getattr(monster, "poisons", False)
            and random.randrange(4) == 0
            and getattr(target_player, "status", None) != Status.POISONED
        ):
            target_player.status = Status.POISONED
            poisoned = True
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the thief steals
        # equipment — a 50/50 pick then 1-in-8 armor slot or 1-in-16 weapon
        # slot, decremented when owned (GBC battle3.c:280-303); Java robber is
        # food/gold-only.
        if getattr(monster, "steals", None) == "equipment" and random.randrange(2) == 0:
            if (
                random.randrange(8) == 0
                and _decrement_lowest_stack(getattr(target_player, "armors", None))
            ):
                stolen_item = "armor"
        elif getattr(monster, "steals", None) == "equipment" and random.randrange(16) == 0:
            if _decrement_lowest_stack(getattr(target_player, "weapons", None)):
                stolen_item = "weapon"
        # Java CombatScreen.java:733-743 — the Java melee theft branches, kept
        # for the food/gold robbers (rand.nextInt(8) == 0 gate).
        if getattr(monster, "steals", None) == "food" and random.randrange(8) == 0:
            # Java: adjustValue(food, -(rand.nextInt(10)), 9999, 0) — 0..9.
            stolen_food = random.randrange(10)
            food = getattr(target_player, "food", 0)
            setattr(target_player, "food", max(0, food - stolen_food))
        elif getattr(monster, "steals", None) == "gold" and random.randrange(8) == 0:
            # Java: adjustValue(gold, -(rand.nextInt(40)), 9999, 0) — 0..39.
            stolen_gold = random.randrange(40)
            gold = getattr(target_player, "gold", 0)
            setattr(target_player, "gold", max(0, gold - stolen_gold))

    # Java logs nothing for the creature melee ATTACK (sounds only). GBC does
    # post the equipment theft for the player (USER-DIRECTED DEVIATION,
    # 2026-11-14): writegamemessage(pilfered) — battle3.c:288/298 prints
    # "PILFERED!", carried here so the arena log pipeline surfaces it. The
    # matching poison feedback (pending item 22) rides the same pipeline:
    # writegamemessage(poisoned) — battle3.c:257 prints "POISONED!" after the
    # 1-in-4 melee poison lands; Java's melee branch is message-silent there
    # too (its own "Poisoned!" log is ranged-only, CombatScreen.java:664), so
    # GBC wording is adopted per the PILFERED! precedent. No roster creature
    # both poisons and steals (creatures.xml), so the two lines can never
    # collide on the single message slot of one hit.
    msg = "PILFERED!" if stolen_item else ("POISONED!" if poisoned else "")
    return AttackResolution(
        hit=True,
        damage=damage,
        killed=killed,
        result=AttackResult.HIT,
        target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
        poisoned=poisoned,
        stolen_item=stolen_item,
        stolen_food=stolen_food,
        stolen_gold=stolen_gold,
        message=msg,
    )


def resolve_monster_ranged_attack(
    monster: Any,
    target_player: Any,
    armor_def: ArmorDef | None = None,
    context_map_id: int | None = None,
    ship_battle: bool = False,
    members: list[Any] | None = None,
) -> AttackResolution:
    """Resolve a monster's ranged bolt vs a party member (Java
    ``CombatScreen.rangedAttackAt``, CombatScreen.java:591-678).

    Java's single ``rangedAttackAt`` body: the hit roll (forced on EXODUS vs a
    non-EXOTIC defender), then the ``rangedhittile`` effect switch, then —
    when the bolt HIT — one more ``dealDamage``:

    - fire/lava ("Fiery Hit!") and energy ("Electrified!") roll damage in the
      effect switch AND again on a hit → damage TWICE on a hit, once on a miss;
    - poison rolls 1-in-2 to set POISONED (hit or miss, no damage of its own);
    - magic/rocks/none deal a single damage roll, only on a hit.

    ``ship_battle`` (the party's transport at battle start is a SHIP) replaces
    the whole branch with the GBC cannonfire party-wide rules; ``members`` (the
    living party roster) feeds the ship branch's party-wide damage roster.
    """
    import py_exodus.assets as assets

    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): in a ship battle the
    # monster ranged branch is GBC cannonfire — no bolt trace; every living
    # party member takes one random.randrange(78) blow through the
    # _deal_monster_damage_to_member (PartyMember.applyDamage) chokepoint.
    # damage totals the individual rolls; killed reports any member lost.
    if ship_battle:
        roster = members if members is not None else [target_player]
        total = 0
        killed = False
        # Playtest-1 fix batch, item 4 (user-approved affordance deviating
        # from Java's silence): each landed blow reports in the port's voice
        # — the per-member damage never left the resolver before, so the
        # lines are assembled here and ride the message pipeline the arena
        # already mirrors. Zero-damage blows stay silent (a blow that takes
        # nothing is a miss for the transcript's purpose).
        monster_name = getattr(monster, "name", "Monster") or "Monster"
        lines = ["Cannonball barrage!"]
        for member in roster:
            if _member_is_dead(member):
                continue
            amount = random.randrange(78)
            _deal_monster_damage_to_member(member, amount)
            total += amount
            died = getattr(member, "status", None) == Status.DEAD
            killed = killed or died
            if amount > 0:
                member_name = getattr(member, "name", "member")
                lines.append(
                    f"{monster_name} cannonfire hits {member_name} ({-amount})."
                )
                if died:
                    lines.append(f"{member_name} falls!")
        return AttackResolution(
            hit=True,
            damage=total,
            killed=killed,
            result=AttackResult.HIT,
            target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
            # Item 3 note: this mechanic is GBC-adopted (cannonfire);
            # GBC prints no text for it (cannonfire3, battle3.c:501-560,
            # calls no writegamemessage) and Java's rangedAttackAt logs only
            # "Electrified!"/"Fiery Hit!"/"Poisoned!" — the barrage line
            # stays as the branch's player feedback per the item-3 ruling to
            # keep GBC-adopted mechanic strings and note them.
            message="\n".join(lines),
        )

    # LairWare hit roll and damage for monster bolts and spells too: its
    # monmagic and monshoot paths end in the same roll/damage code
    # (UltimaSpellCombat.c:1138-1226; user ruling 2026-11-22).
    hit = lw_monster_hits(target_player, context_map_id)
    if str(getattr(monster, "tile", "")).lower() == "dragon":
        hit = True  # monshoot skips the roll (UltimaSpellCombat.c:1193)

    hit_tile = (getattr(monster, "ranged_hit_tile", None) or "").lower()
    effect: str | None = None
    if hit_tile == "poison":
        effect = "poison"
    elif hit_tile == "fire":
        effect = "fire"
    elif hit_tile == "energy":
        effect = "energy"

    damage_total = 0
    killed = False
    poisoned = False
    message_parts: list[str] = []

    def _bolt() -> int:
        return lw_monster_damage(monster, target_player, context_map_id)

    def _deal(amount: int) -> None:
        nonlocal damage_total, killed
        _deal_monster_damage_to_member(target_player, amount)
        damage_total += amount
        killed = getattr(target_player, "status", None) == Status.DEAD

    # Java CombatScreen.java:646-671 — the effect switch, entered whatever the
    # hit roll said.
    # LairWare deals one damage roll per landed bolt; Java's extra roll for
    # fire/energy (hit or miss) is gone (user ruling 2026-11-22).
    if effect == "energy" and hit:
        message_parts.append("Electrified!")
    elif effect == "fire" and hit:
        message_parts.append("Fiery Hit!")
    elif effect == "poison":
        # CombatScreen.java:661-667 — 1-in-2 to poison a non-poisoned member.
        if random.randrange(2) == 0 and getattr(target_player, "status", None) != Status.POISONED:
            if not getattr(target_player, "is_dead", lambda: False)():
                target_player.status = Status.POISONED
                poisoned = True
                message_parts.append("Poisoned!")

    # CombatScreen.java:673-675 — the hit's own dealDamage.
    if hit:
        _deal(_bolt())
        if effect in (None, "magic", "rocks") and not message_parts:
            pass  # Java logs nothing for the plain bolt
    elif effect == "poison" and not poisoned:
        pass  # a missed poison bolt leaves no trace

    return AttackResolution(
        hit=hit,
        damage=damage_total,
        killed=killed,
        result=AttackResult.HIT if hit else AttackResult.MISS,
        target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
        poisoned=poisoned,
        message="".join(f"{p}\n" for p in message_parts).rstrip("\n"),
    )


def resolve_monster_attack(
    monster: Any,
    target_player: Any,
    armor_def: ArmorDef | None = None,
    is_ranged: bool = False,
    context_map_id: int | None = None,
    ship_battle: bool = False,
    members: list[Any] | None = None,
) -> AttackResolution:
    """Resolve an attack by a monster against a player character."""
    if is_ranged:
        return resolve_monster_ranged_attack(
            monster,
            target_player,
            armor_def=armor_def,
            context_map_id=context_map_id,
            ship_battle=ship_battle,
            members=members,
        )
    return resolve_monster_melee_attack(
        monster, target_player, armor_def=armor_def, context_map_id=context_map_id
    )
