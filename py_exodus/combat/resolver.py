"""Melee and ranged combat calculations, hit/damage rolls, and projectile path tracing."""
from __future__ import annotations

from dataclasses import dataclass, field
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
    stolen_food: int = 0
    stolen_gold: int = 0
    message: str = ""


def roll_hit(attacker_attack_bonus: int, defender_defense: int) -> bool:
    """Evaluate hit roll matching classic Ultima III mechanics.

    Attack Value = rand(0..255) + attacker_bonus.
    Hit succeeds if Attack Value > defender_defense.
    """
    attack_value = random.randint(0, 255) + attacker_attack_bonus
    return attack_value > defender_defense


def calculate_player_damage(
    character: Character, weapon_def: WeaponDef | None = None
) -> int:
    """Calculate damage dealt by a player character.

    Formula:
      max_damage = min(255, weapon.dmax + int(str * 1.5))
      damage = rand(weapon.dmin .. max_damage)
    """
    if weapon_def is None:
        dmin, dmax = 4, 4
    else:
        dmin, dmax = weapon_def.dmin, weapon_def.dmax

    max_damage = min(255, int(dmax + character.str * 1.5))
    if max_damage < dmin:
        max_damage = dmin
    return random.randint(dmin, max_damage)


def calculate_monster_damage(basehp: int) -> int:
    """Calculate damage dealt by a monster matching classic Ultima III formula.

    Formula:
      x = rand(0 .. (basehp >> 2) - 1)
      damage = (x >> 4) + ((x >> 2) & 0xFC) + (x % 10)
    """
    shift_val = basehp >> 2
    if shift_val <= 0:
        x = 0
    else:
        x = random.randint(0, shift_val - 1)

    damage = (x >> 4) + ((x >> 2) & 0xFC) + (x % 10)
    return max(1, damage)


def trace_projectile_path(
    combat_map: ConflictMap,
    start_x: int,
    start_y: int,
    direction: Direction,
    max_range: int = 16,
    attack_through_objects: bool = False,
    monsters: list[Any] | None = None,
    players: dict[int, tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Trace directional projectile path until stopped by boundary, wall, or target creature.

    Stops at:
      - Map edge (0 <= x < 11, 0 <= y < 11)
      - Solid wall / unwalkable tile without rangeattackover (unless weapon attacks through objects)
      - First living monster or player encountered along the trajectory.
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

        # Check if hitting a monster target
        if (nx, ny) in monster_positions:
            break

        # Check if hitting a player target
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

    # Hit succeeds - calculate damage
    damage = calculate_player_damage(character, weapon_def)
    target_monster.hp = max(0, target_monster.hp - damage)
    killed = target_monster.hp <= 0

    if killed:
        exp_award = getattr(target_monster, "exp", 0)
        character.exp += exp_award
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


def resolve_monster_attack(
    monster: Any,
    target_player: Any,
    armor_def: ArmorDef | None = None,
    is_ranged: bool = False,
) -> AttackResolution:
    """Resolve an attack by a monster against a player character."""
    # Attacker attack bonus for monsters is 0
    attack_bonus = getattr(monster, "get_attack_bonus", lambda: 0)()

    # Target defense
    if armor_def is not None:
        defense = armor_def.defense
    else:
        # Default skin defense is 128
        defense = getattr(target_player, "get_defense", lambda: 128)()

    is_hit = roll_hit(attack_bonus, defense)
    if not is_hit:
        return AttackResolution(
            hit=False,
            damage=0,
            killed=False,
            result=AttackResult.MISS,
            target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
            message=f"{monster.name} attacked {target_player.name} - Missed!",
        )

    # Hit succeeds - deal damage
    basehp = getattr(monster, "basehp", 48)
    damage = calculate_monster_damage(basehp)

    char = getattr(target_player, "character", target_player)
    char.hp = max(0, char.hp - damage)
    killed = char.hp <= 0
    if killed:
        char.status = Status.DEAD

    # Special creature on-hit effects (only if target survived)
    poisoned = False
    stolen_food = 0
    stolen_gold = 0

    if not killed:
        # Poison check
        if getattr(monster, "poisons", False) or (is_ranged and getattr(monster, "ranged_hit_tile", "") == "poison"):
            if char.status != Status.POISONED and random.randint(0, 1) == 0:
                char.status = Status.POISONED
                poisoned = True

        # Steal effects
        steals = getattr(monster, "steals", None)
        if steals == "food" and random.randint(0, 7) == 0:
            stolen_food = random.randint(1, 10)
            char.food = max(0, char.food - stolen_food)
        elif steals == "gold" and random.randint(0, 7) == 0:
            stolen_gold = random.randint(1, 40)
            char.gold = max(0, char.gold - stolen_gold)

    msg = f"{monster.name} struck {char.name} for {damage} dmg."
    if killed:
        msg += f" {char.name} was slain!"
    elif poisoned:
        msg += f" {char.name} was poisoned!"
    if stolen_food:
        msg += f" Stole {stolen_food} food!"
    if stolen_gold:
        msg += f" Stole {stolen_gold} gold!"

    return AttackResolution(
        hit=True,
        damage=damage,
        killed=killed,
        result=AttackResult.HIT,
        target_pos=(getattr(target_player, "x", 0), getattr(target_player, "y", 0)),
        poisoned=poisoned,
        stolen_food=stolen_food,
        stolen_gold=stolen_gold,
        message=msg,
    )
