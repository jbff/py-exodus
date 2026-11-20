"""CombatScreen (11x11 CombatArena) state encoder, discrete action space, and legality mask."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_exodus.combat.arena import Action, ActionType
from py_exodus.combat.auto_combat import (
    _CARDINAL_DIRS,
    _can_cast_spell,
    _find_lowest_hp_heal_target,
    _get_weapon_info,
    _is_magic_negated,
    _is_member_dead,
    _is_poisonous,
    _is_undead,
    _is_walkable_unoccupied,
)
from py_exodus.combat.resolver import trace_projectile_path
from py_exodus.constants import Direction, Spell, TileAttrib, Transport

if TYPE_CHECKING:
    from py_exodus.combat.arena import CombatArena

COMBAT_GRID_SIZE = 11
COMBAT_GRID_CHANNELS = 10
COMBAT_CONTEXT_DIM = 20
NUM_COMBAT_ACTIONS = 15

_DIR_TO_OFFSET: dict[Direction, int] = {
    Direction.NORTH: 0,
    Direction.SOUTH: 1,
    Direction.EAST: 2,
    Direction.WEST: 3,
}
_OFFSET_TO_DIR: tuple[Direction, ...] = (
    Direction.NORTH,
    Direction.SOUTH,
    Direction.EAST,
    Direction.WEST,
)
_HEAL_SPELLS = (Spell.SANCTU_MANI, Spell.SANCTU)
_AOE_SPELLS = (
    Spell.REPOND,
    Spell.PONTORI,
    Spell.UNSPEAKABLE,
    Spell.ZXKUQYB,
    Spell.NOXUM,
    Spell.DAG_MENTAR,
    Spell.NECORP,
)
_WIND_TO_IDX: dict[Direction | None, float] = {
    None: -1.0,
    Direction.NORTH: 0.0,
    Direction.EAST: 1.0,
    Direction.SOUTH: 2.0,
    Direction.WEST: 3.0,
}


def action_to_index(action: Action) -> int:
    """Map a CombatArena Action to discrete action index [0, 14]."""
    if action.type == ActionType.MOVE and action.direction in _DIR_TO_OFFSET:
        return _DIR_TO_OFFSET[action.direction]
    if action.type == ActionType.ATTACK and action.direction in _DIR_TO_OFFSET:
        return 4 + _DIR_TO_OFFSET[action.direction]
    if action.type == ActionType.CAST:
        if action.spell == Spell.MITTAR and action.direction in _DIR_TO_OFFSET:
            return 8 + _DIR_TO_OFFSET[action.direction]
        if action.spell in _HEAL_SPELLS:
            return 12
        if action.spell in _AOE_SPELLS:
            return 13
    return 14


def index_to_action(
    idx: int,
    arena: CombatArena,
    member_idx: int,
    asset_mgr: Any = None,
) -> Action:
    """Convert discrete action index [0, 14] into a valid CombatArena Action."""
    if 0 <= idx <= 3:
        return Action.move(_OFFSET_TO_DIR[idx])
    if 4 <= idx <= 7:
        return Action.attack(_OFFSET_TO_DIR[idx - 4])
    if 8 <= idx <= 11:
        return Action.cast(Spell.MITTAR, direction=_OFFSET_TO_DIR[idx - 8])
    if idx == 12:
        member = arena.party.members[member_idx]
        target = _find_lowest_hp_heal_target(arena.party) or member
        spell = Spell.SANCTU_MANI if _can_cast_spell(member, Spell.SANCTU_MANI) else Spell.SANCTU
        return Action.cast(spell, target_member=target)
    if idx == 13:
        member = arena.party.members[member_idx]
        visible = [m for m in arena.monsters if not m.is_dead and m.visible]
        for sp in _AOE_SPELLS:
            free = sp in (Spell.REPOND, Spell.PONTORI)
            if _can_cast_spell(member, sp, check_free=free):
                if sp == Spell.REPOND and not any(getattr(m, "tile", None) == "orc" for m in visible):
                    continue
                if sp == Spell.PONTORI and not any(_is_undead(m) for m in visible):
                    continue
                return Action.cast(sp)
        return Action.pass_turn()
    return Action.pass_turn()


def legal_action_mask(
    arena: CombatArena,
    member_idx: int,
    asset_mgr: Any = None,
) -> list[bool]:
    """Return a 15-element boolean mask of legal actions for the active party member."""
    mask = [False] * NUM_COMBAT_ACTIONS
    mask[14] = True  # PASS is always legal

    if member_idx < 0 or member_idx >= len(arena.party.members):
        return mask
    member = arena.party.members[member_idx]
    if _is_member_dead(member) or member_idx not in arena.player_positions:
        return mask

    px, py = arena.player_positions[member_idx]
    w_range, attack_through = _get_weapon_info(member, asset_mgr)
    visible_monsters = [m for m in arena.monsters if not m.is_dead and m.visible]
    visible_positions = {(m.x, m.y) for m in visible_monsters}

    for i, d in enumerate(_OFFSET_TO_DIR):
        nx, ny = px + d.dx, py + d.dy
        if _is_walkable_unoccupied(arena, member_idx, nx, ny):
            mask[i] = True
        if w_range <= 1:
            if (nx, ny) in visible_positions:
                mask[4 + i] = True
        else:
            path = trace_projectile_path(
                combat_map=arena.combat_map,
                start_x=px,
                start_y=py,
                direction=d,
                max_range=w_range,
                attack_through_objects=attack_through,
                monsters=arena.monsters,
                players=arena.player_positions,
            )
            if path and path[-1] in visible_positions:
                mask[4 + i] = True

    if not _is_magic_negated(arena):
        if _can_cast_spell(member, Spell.MITTAR):
            for i, d in enumerate(_OFFSET_TO_DIR):
                path = trace_projectile_path(
                    combat_map=arena.combat_map,
                    start_x=px,
                    start_y=py,
                    direction=d,
                    max_range=16,
                    attack_through_objects=False,
                    monsters=arena.monsters,
                    players=arena.player_positions,
                )
                if path and path[-1] in visible_positions:
                    mask[8 + i] = True
        if (
            _find_lowest_hp_heal_target(arena.party) is not None
            and (_can_cast_spell(member, Spell.SANCTU_MANI) or _can_cast_spell(member, Spell.SANCTU))
        ):
            mask[12] = True
        for sp in _AOE_SPELLS:
            free = sp in (Spell.REPOND, Spell.PONTORI)
            if _can_cast_spell(member, sp, check_free=free):
                if sp == Spell.REPOND and not any(getattr(m, "tile", None) == "orc" for m in visible_monsters):
                    continue
                if sp == Spell.PONTORI and not any(_is_undead(m) for m in visible_monsters):
                    continue
                mask[13] = True
                break

    return mask


def encode_combat_state(
    arena: CombatArena,
    member_idx: int,
    screen: Any = None,
    asset_mgr: Any = None,
) -> tuple[list[list[list[float]]], list[float]]:
    """Encode CombatArena into (grid[10][11][11], context[20]) float lists."""
    grid = [[[0.0 for _ in range(COMBAT_GRID_SIZE)] for _ in range(COMBAT_GRID_SIZE)] for _ in range(COMBAT_GRID_CHANNELS)]

    cmap = arena.combat_map
    for y in range(min(COMBAT_GRID_SIZE, cmap.height)):
        for x in range(min(COMBAT_GRID_SIZE, cmap.width)):
            tile = cmap.get_tile(x, y)
            attribs = getattr(tile, "attribs", TileAttrib.NONE) if tile is not None else TileAttrib.NONE
            grid[0][y][x] = 0.0 if bool(attribs & TileAttrib.UNWALKABLE) else 1.0
            tname = str(getattr(tile, "name", "")).lower() if tile is not None else ""
            if any(h in tname for h in ("lava", "fire", "poison", "swamp")):
                grid[8][y][x] = 1.0

    for p_idx, (ax, ay) in arena.player_positions.items():
        if not (0 <= ax < COMBAT_GRID_SIZE and 0 <= ay < COMBAT_GRID_SIZE):
            continue
        m = arena.party.members[p_idx]
        if _is_member_dead(m):
            continue
        if p_idx == member_idx:
            grid[1][ay][ax] = 1.0
        else:
            grid[2][ay][ax] = 1.0
        grid[3][ay][ax] = float(m.hp) / max(1, m.max_hp)

    visible_monsters = [m for m in arena.monsters if not m.is_dead and m.visible]
    for mon in visible_monsters:
        mx, my = mon.x, mon.y
        if not (0 <= mx < COMBAT_GRID_SIZE and 0 <= my < COMBAT_GRID_SIZE):
            continue
        grid[4][my][mx] = 1.0
        grid[5][my][mx] = float(mon.hp) / max(1, getattr(mon, "max_hp", max(1, mon.hp)))
        if getattr(mon, "ranged", False) or getattr(mon, "magic", False):
            grid[6][my][mx] = 1.0
        if _is_poisonous(mon):
            grid[7][my][mx] = 1.0

    px, py = arena.player_positions.get(member_idx, (0, 0))
    member = arena.party.members[member_idx] if 0 <= member_idx < len(arena.party.members) else None
    w_range, attack_through = _get_weapon_info(member, asset_mgr) if member is not None else (1, False)
    for d in _CARDINAL_DIRS:
        for step in range(1, min(COMBAT_GRID_SIZE, w_range + 1)):
            rx, ry = px + d.dx * step, py + d.dy * step
            if not (0 <= rx < COMBAT_GRID_SIZE and 0 <= ry < COMBAT_GRID_SIZE):
                break
            grid[9][ry][rx] = 1.0

    living = [m for m in arena.party.members if not _is_member_dead(m)]
    negated = _is_magic_negated(arena)
    mask = legal_action_mask(arena, member_idx, asset_mgr=asset_mgr)
    context = [
        float(getattr(screen, "trammel_phase", 0) if screen is not None else 0) / 24.0,
        float(getattr(screen, "felucca_phase", 0) if screen is not None else 0) / 8.0,
        _WIND_TO_IDX.get(getattr(arena.party, "wind_direction", None), -1.0) / 4.0,
        float(getattr(arena.party, "ship_hull", 50)) / 50.0,
        (float(member.hp) / max(1, member.max_hp)) if member is not None else 0.0,
        (float(member.mp) / max(1, member.max_mp)) if member is not None else 0.0,
        1.0 if (member is not None and getattr(member.status, "name", "") == "POISONED") else 0.0,
        (float(member.food) / 500.0) if member is not None else 0.0,
        float(getattr(arena.party, "gold", 0)) / 5000.0,
        float(w_range) / 16.0,
        1.0 if attack_through else 0.0,
        float(len(living)) / 4.0,
        min((float(m.hp) / max(1, m.max_hp) for m in living), default=0.0),
        float(len(visible_monsters)) / 8.0,
        1.0 if negated else 0.0,
        1.0 if mask[12] else 0.0,
        1.0 if any(mask[8:12]) else 0.0,
        1.0 if mask[13] else 0.0,
        float(getattr(arena, "turn_count", 0)) / 60.0,
        1.0 if getattr(arena.party, "transport", Transport.FOOT) == Transport.SHIP else 0.0,
    ]
    return grid, context
