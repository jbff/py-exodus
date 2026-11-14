"""Melee and ranged combat calculations, hit/damage rolls, and projectile path tracing."""
from __future__ import annotations

from dataclasses import dataclass, field, replace as _dc_replace
from enum import Enum
import random
from typing import TYPE_CHECKING, Any

from py_exodus.constants import Direction, Status, TileAttrib

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


def roll_hit(attacker_attack_bonus: int, defender_defense: int) -> bool:
    """Evaluate hit roll matching classic Ultima III mechanics.

    Java ``Utils.attackHit`` (Utils.java:592-602): Attack Value =
    rand.nextInt(256) + attacker_bonus — i.e. rand(0..255) + bonus; the hit
    lands when Attack Value > defender_defense.
    """
    attack_value = random.randint(0, 255) + attacker_attack_bonus
    return attack_value > defender_defense


def calculate_player_damage(
    character: Character, weapon_def: WeaponDef | None = None
) -> int:
    """Calculate damage dealt by a player character.

    Java truth: ``Party.PartyMember.getDamage`` (Party.java:333-340) —
    maxDamage = dmax + str * 1.5 (Int math, capped at 255), then
    ``Utils.getRandomBetween(dmin, maxDamage)`` → ``rand.nextInt(high - low)
    + low`` (Utils.java:50-52): the HIGH bound is EXCLUSIVE.
    """
    if weapon_def is None:
        dmin, dmax = 4, 4
    else:
        dmin, dmax = weapon_def.dmin, weapon_def.dmax

    max_damage = min(255, int(dmax + character.str * 1.5))
    if max_damage < dmin:
        max_damage = dmin
    if max_damage > dmin:
        # nextInt(high - low) + low — high exclusive.
        return random.randrange(max_damage - dmin) + dmin
    return dmin


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


# USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): GBC battle3.c:337-350 adds a
# terrain bonus to monster melee damage (+10 dungeon, +30 surface
# Sosaria/Ambrosia, +20 towns/castles/other interiors). The GBC
# inside/peermap table maps onto py map ids; the dungeon maps are the
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


def monster_damage_bonus(context_map_id: int | None) -> int:
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): terrain tier for monster
    melee damage — +10 on a dungeon map, +30 on the surface worlds (Sosaria,
    Ambrosia), +20 in towns, castles and other interiors; an unknown context
    (None) falls to the interior tier (GBC battle3.c:337-350)
    """
    if context_map_id is not None and context_map_id in _dungeon_map_ids():
        return 10
    import py_exodus.assets as assets

    if context_map_id in (
        assets.MAP_NAME_TO_ID["SOSARIA"],
        assets.MAP_NAME_TO_ID["AMBROSIA"],
    ):
        return 30
    return 20


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
    # bolt trace is skipped.
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


def resolve_player_attack(
    character: Character,
    weapon_def: WeaponDef | None,
    target_monster: Any,
    distance: int = 1,
) -> AttackResolution:
    """Resolve an attack by a player character against a monster."""
    # Check weapon range constraint
    if weapon_def is not None and distance > weapon_def.range:
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(target_monster.x, target_monster.y),
            message=f"{character.name} is out of effective weapon range!",
        )

    # Attack bonus: if DEX >= 40, auto-hit cap (255)
    attack_bonus = 255 if character.dex >= 40 else character.dex
    defense = getattr(target_monster, "get_defense", lambda: 128)()

    is_hit = roll_hit(attack_bonus, defense)
    if not is_hit:
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(target_monster.x, target_monster.y),
            message=f"{character.name} attacked {target_monster.name} - Missed!",
        )

    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): a landed player hit vs
    # the guard tile (0x18) or Lord British tile (0x19) deals damage 0 and
    # never kills; the guard exemption applies in normal mode too, since
    # py-exodus has no GBC extragame hard-mode flag (GBC battle.c:646-648).
    target_tile = (getattr(target_monster, "tile", "") or "").lower()
    if target_tile in ("guard", "lord_british"):
        return AttackResolution(
            hit=True,
            damage=0,
            killed=False,
            result=AttackResult.HIT,
            target_pos=(target_monster.x, target_monster.y),
            message=f"{character.name} struck {target_monster.name} - No effect!",
        )

    # Hit succeeds - calculate damage
    damage = calculate_player_damage(character, weapon_def)
    target_monster.hp = max(0, target_monster.hp - damage)
    killed = target_monster.hp <= 0

    if killed:
        exp_award = getattr(target_monster, "exp", 0)
        # Java Utils.dealDamage(PartyMember, Creature, damage) → awardXP
        # (Party.java:372-375, Utils.java:604-611): every player-caused death
        # pays the creature's EXP, capped at 9999.
        award = getattr(character, "award_xp", None)
        if callable(award):
            award(exp_award)
        else:
            character.exp = min(9999, character.exp + exp_award)
        msg = f"{character.name} struck {target_monster.name} for {damage} dmg - Killed! (+{exp_award} EXP)"
    else:
        msg = f"{character.name} struck {target_monster.name} for {damage} dmg."

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

    # Java CombatScreen.java:723: EXODUS auto-hit vs exotic-armor-less defenders.
    armor_name = getattr(getattr(target_player, "armor", None), "value", None)
    if context_map_id == assets.MAP_NAME_TO_ID["EXODUS"] and armor_name != "EXOTIC":
        is_hit = True
    else:
        attack_bonus = getattr(monster, "get_attack_bonus", lambda: 0)()
        if armor_def is not None:
            defense = armor_def.defense
        else:
            defense = getattr(target_player, "get_defense", lambda: 128)()
        is_hit = roll_hit(attack_bonus, defense)

    if not is_hit:
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
            message="",
        )

    basehp = getattr(monster, "basehp", 48)
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): monster melee damage adds
    # the terrain bonus — +10 dungeon, +30 surface Sosaria/Ambrosia, +20
    # towns/castles/other interiors, per the GBC inside/peermap table mapped to
    # py MAP_NAME_TO_ID (GBC battle3.c:337-350).
    damage = calculate_monster_damage(basehp) + monster_damage_bonus(context_map_id)
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

    # Java logs nothing for the creature melee ATTACK (sounds only).
    msg = ""
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
        for member in roster:
            if _member_is_dead(member):
                continue
            amount = random.randrange(78)
            _deal_monster_damage_to_member(member, amount)
            total += amount
            killed = killed or getattr(member, "status", None) == Status.DEAD
        return AttackResolution(
            hit=True,
            damage=total,
            killed=killed,
            result=AttackResult.HIT,
            target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
            message="Cannonball barrage!",
        )

    armor_name = getattr(getattr(target_player, "armor", None), "value", None)
    if context_map_id == assets.MAP_NAME_TO_ID["EXODUS"] and armor_name != "EXOTIC":
        hit = True
    else:
        attack_bonus = getattr(monster, "get_attack_bonus", lambda: 0)()
        if armor_def is not None:
            defense = armor_def.defense
        else:
            defense = getattr(target_player, "get_defense", lambda: 128)()
        hit = roll_hit(attack_bonus, defense)

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

    basehp = getattr(monster, "basehp", 48)

    def _deal(amount: int) -> None:
        nonlocal damage_total, killed
        _deal_monster_damage_to_member(target_player, amount)
        damage_total += amount
        killed = getattr(target_player, "status", None) == Status.DEAD

    # Java CombatScreen.java:646-671 — the effect switch, entered whatever the
    # hit roll said.
    if effect == "energy":
        message_parts.append("Electrified!")
        _deal(calculate_monster_damage(basehp))
    elif effect == "fire":
        message_parts.append("Fiery Hit!")
        _deal(calculate_monster_damage(basehp))
    elif effect == "poison":
        # CombatScreen.java:661-667 — 1-in-2 to poison a non-poisoned member.
        if random.randrange(2) == 0 and getattr(target_player, "status", None) != Status.POISONED:
            if not getattr(target_player, "is_dead", lambda: False)():
                target_player.status = Status.POISONED
                poisoned = True
                message_parts.append("Poisoned!")

    # CombatScreen.java:673-675 — the hit's own dealDamage.
    if hit:
        _deal(calculate_monster_damage(basehp))
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
