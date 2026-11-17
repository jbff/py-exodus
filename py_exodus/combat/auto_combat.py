"""Auto-combat tactical AI decision engine (inspired by Lairware UltimaAutocombat.c)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_exodus.combat.arena import Action
from py_exodus.combat.resolver import trace_projectile_path
from py_exodus.constants import Direction, TileAttrib, WeaponType

if TYPE_CHECKING:
    from py_exodus.combat.arena import CombatArena, CombatMonster

_CARDINAL_DIRS: tuple[Direction, ...] = (
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST,
)

_RANGED_WEAPON_TYPES: frozenset[WeaponType] = frozenset(
    {
        WeaponType.BOW,
        WeaponType.BOW_P2,
        WeaponType.BOW_P4,
        WeaponType.SLING,
    }
)


def _get_weapon_info(member: Any, asset_mgr: Any) -> tuple[int, bool]:
    """Return ``(range, attack_through_objects)`` for ``member``'s equipped weapon."""
    weapon = getattr(member, "weapon", WeaponType.NONE)
    if asset_mgr is not None:
        w_name = weapon.value if isinstance(weapon, WeaponType) else str(weapon)
        w_def = asset_mgr.get_weapon(w_name)
        if w_def is not None:
            return (
                max(1, int(getattr(w_def, "range", 1))),
                bool(getattr(w_def, "attack_through_objects", False)),
            )

    if isinstance(weapon, WeaponType):
        wt = weapon
    else:
        try:
            wt = WeaponType(str(weapon))
        except ValueError:
            wt = WeaponType.NONE

    if wt in _RANGED_WEAPON_TYPES:
        return (16, False)
    return (1, False)


def _is_walkable_unoccupied(
    arena: CombatArena, member_idx: int, x: int, y: int
) -> bool:
    """Return True if ``(x, y)`` is in-bounds, walkable, and free of allies/monsters."""
    if not (0 <= x < arena.combat_map.width and 0 <= y < arena.combat_map.height):
        return False

    tile = arena.combat_map.get_tile(x, y)
    if tile is not None:
        attribs = getattr(tile, "attribs", TileAttrib.NONE)
        if bool(attribs & TileAttrib.UNWALKABLE):
            return False

    for p_idx, pos in arena.player_positions.items():
        if p_idx != member_idx and pos == (x, y):
            return False

    for m in arena.monsters:
        if not m.is_dead and (m.x, m.y) == (x, y):
            return False

    return True


def _try_low_hp_retreat(
    arena: CombatArena,
    member_idx: int,
    member: Any,
    pos: tuple[int, int],
    visible_monsters: list[CombatMonster],
) -> Action | None:
    """Retreat one cardinal step if HP is critical and an enemy is adjacent."""
    max_hp = getattr(member, "max_hp", 0)
    if getattr(member, "hp", 0) > max(15, max_hp // 5):
        return None

    px, py = pos
    if not any(max(abs(m.x - px), abs(m.y - py)) <= 1 for m in visible_monsters):
        return None

    cur_min_manh = min(abs(m.x - px) + abs(m.y - py) for m in visible_monsters)
    best_dir: Direction | None = None
    best_score: tuple[int, int] | None = None

    for d in _CARDINAL_DIRS:
        nx, ny = px + d.dx, py + d.dy
        if not _is_walkable_unoccupied(arena, member_idx, nx, ny):
            continue
        min_cheb = min(max(abs(m.x - nx), abs(m.y - ny)) for m in visible_monsters)
        min_manh = min(abs(m.x - nx) + abs(m.y - ny) for m in visible_monsters)
        if min_manh <= cur_min_manh:
            continue
        score = (min_cheb, min_manh)
        if best_score is None or score > best_score:
            best_score = score
            best_dir = d

    return Action.move(best_dir) if best_dir is not None else None


def choose_auto_combat_action(
    arena: CombatArena, member_idx: int, asset_mgr: Any = None
) -> Action:
    """Choose a tactical combat ``Action`` for ``arena.party.members[member_idx]``."""
    if member_idx < 0 or member_idx >= len(arena.party.members):
        return Action.pass_turn()

    member = arena.party.members[member_idx]
    is_dead_attr = getattr(member, "is_dead", False)
    is_dead = is_dead_attr() if callable(is_dead_attr) else bool(is_dead_attr)
    if is_dead or member_idx not in arena.player_positions:
        return Action.pass_turn()

    pos = arena.player_positions[member_idx]
    visible_monsters = [m for m in arena.monsters if not m.is_dead and m.visible]
    if not visible_monsters:
        return Action.pass_turn()

    retreat = _try_low_hp_retreat(arena, member_idx, member, pos, visible_monsters)
    if retreat is not None:
        return retreat

    px, py = pos
    visible_positions = {(m.x, m.y) for m in visible_monsters}

    # Adjacent cardinal melee attack
    for d in _CARDINAL_DIRS:
        if (px + d.dx, py + d.dy) in visible_positions:
            return Action.attack(d)

    effective_asset_mgr = asset_mgr if asset_mgr is not None else getattr(arena, "asset_mgr", None)
    weapon_range, attack_through = _get_weapon_info(member, effective_asset_mgr)

    # Cardinal ranged attack with clear line of sight
    if weapon_range > 1:
        for d in _CARDINAL_DIRS:
            path = trace_projectile_path(
                combat_map=arena.combat_map,
                start_x=px,
                start_y=py,
                direction=d,
                max_range=weapon_range,
                attack_through_objects=attack_through,
                monsters=arena.monsters,
                players=arena.player_positions,
            )
            if path and path[-1] in visible_positions:
                return Action.attack(d)

    # Advance toward nearest visible living monster
    target = min(
        visible_monsters,
        key=lambda m: (abs(m.x - px) + abs(m.y - py), max(abs(m.x - px), abs(m.y - py))),
    )
    cur_dist = abs(target.x - px) + abs(target.y - py)

    best_move_dir: Direction | None = None
    best_move_score: tuple[int, int] | None = None

    for d in _CARDINAL_DIRS:
        nx, ny = px + d.dx, py + d.dy
        if not _is_walkable_unoccupied(arena, member_idx, nx, ny):
            continue
        new_dist = abs(target.x - nx) + abs(target.y - ny)
        if new_dist >= cur_dist:
            continue
        if weapon_range > 1:
            score = (new_dist, min(abs(target.x - nx), abs(target.y - ny)))
        else:
            score = (new_dist, max(abs(target.x - nx), abs(target.y - ny)))
        if best_move_score is None or score < best_move_score:
            best_move_score = score
            best_move_dir = d

    if best_move_dir is not None:
        return Action.move(best_move_dir)

    return Action.pass_turn()
