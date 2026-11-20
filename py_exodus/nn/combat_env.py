"""CombatScreen (11x11 CombatArena) state encoder, discrete action space, and legality mask."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from py_exodus.combat.arena import Action, ActionType
from py_exodus.combat.auto_combat import (
    _CARDINAL_DIRS,
    _can_cast_spell,
    _find_lowest_hp_heal_target,
    _find_ranged_attack_dir,
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
COMBAT_GRID_CHANNELS = 11  # v2: +1 monster-type ordinal channel
COMBAT_CONTEXT_DIM = 33  # v2: 20 - 4 (moon/wind/hull) + level + weapon one-hot

# v3 action space (2026-11-20): every combat-castable spell gets its own
# learnable index instead of the compressed heal/aoe buckets — the net can
# now *choose* which spell (heal size, cure poison, nuke, decayer, bolt).
# Directions/targets for directed spells stay mechanical: engine helpers
# pick the line of sight / lowest-HP ally, matching what the symbolic
# teacher does, so BC imitates spell *choice*.
#   0-3   MOVE  (N, S, E, W)
#   4-7   ATTACK with equipped weapon (same directions)
#   8     REPOND   (wizard, free — destroys orcs/gremlins/trolls)
#   9     PONTORI  (cleric, free — turns undead)
#   10-16 wizard: MITTAR, FULGAR, NOXUM, DAG_MENTAR, NECORP, DECORP, UNSPEAKABLE
#   17-21 cleric: SANCTU, ALCORT, SANCTU_MANI, EXCUUN, ZXKUQYB
#   22    PASS (always legal)
SPELL_ACTION_INDEX: dict["Spell", int] = {
    Spell.REPOND: 8,
    Spell.PONTORI: 9,
    Spell.MITTAR: 10,
    Spell.FULGAR: 11,
    Spell.NOXUM: 12,
    Spell.DAG_MENTAR: 13,
    Spell.NECORP: 14,
    Spell.DECORP: 15,
    Spell.UNSPEAKABLE: 16,
    Spell.SANCTU: 17,
    Spell.ALCORT: 18,
    Spell.SANCTU_MANI: 19,
    Spell.EXCUUN: 20,
    Spell.ZXKUQYB: 21,
}
PASS_INDEX = 22
_DIRECTED_SPELLS: tuple["Spell", ...] = (
    Spell.MITTAR, Spell.FULGAR, Spell.DECORP, Spell.EXCUUN,
)
_FREE_SPELLS: tuple["Spell", ...] = (Spell.REPOND, Spell.PONTORI)

#: Battle-creature id -> ordinal, straight from creatures.xml (parity-stable).
#: Encoded on the monster-type grid channel so the net knows WHAT it is
#: fighting (dragon vs equal-HP orc behave very differently), not just where.
MONSTER_TYPE_ORDINAL: dict[str, float] = {
    "orc": 10, "skeleton": 11, "thief": 12, "giant": 13, "daemon": 14,
    "fighter": 15, "wizard": 16, "pincher": 17, "dragon": 18, "balron": 19,
    "pirate": 20, "serpent": 21, "squid": 22,
}
_MONSTER_TYPE_NORM = max(MONSTER_TYPE_ORDINAL.values())


def _weapon_onehot(member: Any) -> list[float]:
    """One-hot of the equipped weapon (16 WeaponType slots, parity order)."""
    weapon = getattr(member, "weapon", None)
    return [
        1.0 if weapon is not None and (weapon == wk or getattr(weapon, "value", None) == wk) else 0.0
        for wk in _WEAPON_TYPE_KEYS
    ]

#: WeaponType members, ordered, for the equipped-weapon one-hot (the net
#: must see what is armed: Exotic vs Dagger damage differ enormously).
_WEAPON_TYPE_KEYS: tuple[str, ...] = (
    "NONE", "DAGGER", "MACE", "SLING", "AXE", "BOW", "SWORD", "SWORD_2H",
    "AXE_P2", "BOW_P2", "SWORD_P2", "GLOVES", "AXE_P4", "BOW_P4", "SWORD_P4",
    "EXOTIC",
)
NUM_COMBAT_ACTIONS = 23  # v3: per-spell actions (see SPELL_ACTION_INDEX)

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
# Spell-book membership for mask/context derivations: which profession can
# index which spell action (engine truth — Spell's value[3] is its book).
_PROFESSION_SPELL_INDICES: dict[str, tuple[int, ...]] = {}
for _sp, _idx in SPELL_ACTION_INDEX.items():
    _book = str(_sp.value[3])
    _PROFESSION_SPELL_INDICES.setdefault(_book, _PROFESSION_SPELL_INDICES.get(_book, ()) + (_idx,))

_HEAL_SPELLS = (Spell.SANCTU_MANI, Spell.SANCTU)


def _member_book(member: Any) -> str:
    """Spell book of the member's profession ('wizard'/'cleric'/other)."""
    prof = getattr(getattr(member, "profession", None), "name", "").lower()
    return prof if prof in ("wizard", "cleric") else "none"
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
    """Map a CombatArena Action to discrete action index [0, 22]."""
    if action.type == ActionType.MOVE and action.direction in _DIR_TO_OFFSET:
        return _DIR_TO_OFFSET[action.direction]
    if action.type == ActionType.ATTACK and action.direction in _DIR_TO_OFFSET:
        return 4 + _DIR_TO_OFFSET[action.direction]
    if action.type == ActionType.CAST and action.spell in SPELL_ACTION_INDEX:
        return SPELL_ACTION_INDEX[action.spell]
    return PASS_INDEX


def index_to_action(
    idx: int,
    arena: CombatArena,
    member_idx: int,
    asset_mgr: Any = None,
) -> Action:
    """Convert discrete action index [0, 22] into a valid CombatArena Action."""
    if 0 <= idx <= 3:
        return Action.move(_OFFSET_TO_DIR[idx])
    if 4 <= idx <= 7:
        return Action.attack(_OFFSET_TO_DIR[idx - 4])
    if idx == PASS_INDEX:
        return Action.pass_turn()

    spell = _ACTION_INDEX_TO_SPELL.get(idx)
    if spell is None:
        return Action.pass_turn()
    member = arena.party.members[member_idx]

    if spell in _FREE_SPELLS:
        return Action.cast(spell)

    if spell in _DIRECTED_SPELLS:
        # Direction stays mechanical, like the symbolic teacher: pick the
        # cardinal line with a visible target.
        px, py = arena.player_positions.get(member_idx, (0, 0))
        visible_positions = {
            (m.x, m.y) for m in arena.monsters if not m.is_dead and m.visible
        }
        direction = _find_ranged_attack_dir(
            arena, px, py, max_range=5, attack_through=False,
            visible_positions=visible_positions,
        )
        if direction is None:
            return Action.pass_turn()
        return Action.cast(spell, direction=direction)

    if spell in (Spell.SANCTU, Spell.SANCTU_MANI):
        target = _find_lowest_hp_heal_target(arena.party) or member
        return Action.cast(spell, target_member=target)

    if spell == Spell.ALCORT:
        target = next(
            (
                m
                for m in arena.party.members
                if not _is_member_dead(m)
                and getattr(getattr(m, "status", None), "name", "")
                in ("POISON", "POISONED")
            ),
            member,
        )
        return Action.cast(spell, target_member=target)

    # AOE / decay nukes: no direction or target.
    return Action.cast(spell)


_ACTION_INDEX_TO_SPELL: dict[int, "Spell"] = {
    v: k for k, v in SPELL_ACTION_INDEX.items()
}


def legal_action_mask(
    arena: CombatArena,
    member_idx: int,
    asset_mgr: Any = None,
) -> list[bool]:
    """Return a 23-element boolean mask of legal actions for the active member."""
    mask = [False] * NUM_COMBAT_ACTIONS
    mask[PASS_INDEX] = True  # PASS is always legal

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
        for sp, sp_idx in SPELL_ACTION_INDEX.items():
            free = sp in _FREE_SPELLS
            if not _can_cast_spell(member, sp, check_free=free):
                continue
            if sp in _DIRECTED_SPELLS:
                # Directed bolts need a clear line of sight, mechanically
                # selected the way index_to_action does.
                direction = _find_ranged_attack_dir(
                    arena, px, py, max_range=5, attack_through=False,
                    visible_positions=visible_positions,
                )
                if direction is None:
                    continue
            if sp == Spell.ALCORT and not any(
                getattr(m, "status", None) is not None
                and getattr(m.status, "name", "") in ("POISON", "POISONED")
                for m in arena.party.members
            ):
                continue  # nothing to cure
            mask[sp_idx] = True

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
        creature_id = MONSTER_TYPE_ORDINAL.get(str(getattr(mon, "tile", "")).lower())
        if creature_id is not None:
            grid[10][my][mx] = creature_id / _MONSTER_TYPE_NORM

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
    # v2 encoder (2026-11-20): dropped moon phases, wind and ship hull —
    # combat-irrelevant noise the net could only overfit on (user ruling).
    # Added the acting member's level and a one-hot of the armed weapon,
    # the two capability signals the old encoding could not see at all.
    context = [
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
        1.0 if any(mask[SPELL_ACTION_INDEX[sp]] for sp in _HEAL_SPELLS) else 0.0,
        1.0 if any(
            mask[_idx]
            for _idx in _PROFESSION_SPELL_INDICES.get(
                _member_book(member), ()
            )
        ) else 0.0,
        1.0 if mask[SPELL_ACTION_INDEX[Spell.ALCORT]] else 0.0,
        float(getattr(arena, "turn_count", 0)) / 60.0,
        1.0 if getattr(arena.party, "transport", Transport.FOOT) == Transport.SHIP else 0.0,
        (float(member.level) / 25.0) if member is not None else 0.0,
        *_weapon_onehot(member),
    ]
    return grid, context
