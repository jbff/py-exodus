"""Auto-combat tactical AI decision engine (inspired by Lairware UltimaAutocombat.c)."""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from py_exodus.aura import AuraType
from py_exodus.combat.arena import Action
from py_exodus.combat.resolver import trace_projectile_path
from py_exodus.constants import Direction, Profession, Spell, TileAttrib, WeaponType

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

_NO_MITTAR_WEAPONS: frozenset[WeaponType] = frozenset(
    {
        WeaponType.BOW_P2,
        WeaponType.BOW_P4,
        WeaponType.EXOTIC,
    }
)

_UNDEAD_TILES: frozenset[str] = frozenset({"skeleton", "ghoul", "zombie"})


def _get_weapon_info(member: Any, asset_mgr: Any) -> tuple[int, bool]:
    """Return ``(range, attack_through_objects)`` for ``member``'s equipped weapon."""
    weapon = getattr(member, "weapon", WeaponType.NONE)
    if isinstance(weapon, WeaponType):
        wt = weapon
    else:
        try:
            wt = WeaponType(str(weapon))
        except ValueError:
            wt = WeaponType.NONE

    # Never throw the last Dagger (no spare in member.weapons) in auto-combat;
    # throwing it disarms the character for a single low-damage ranged shot.
    if wt == WeaponType.DAGGER:
        weapons = getattr(member, "weapons", None)
        spare_daggers = weapons.get(WeaponType.DAGGER, 0) if isinstance(weapons, dict) else 0
        if spare_daggers <= 0:
            return (1, False)

    if asset_mgr is not None:
        w_name = weapon.value if isinstance(weapon, WeaponType) else str(weapon)
        w_def = asset_mgr.get_weapon(w_name)
        if w_def is not None:
            return (
                max(1, int(getattr(w_def, "range", 1))),
                bool(getattr(w_def, "attack_through_objects", False)),
            )

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


# A Cleric below this level is the party's healer and its weakest body:
# batch 775884a's early wipes lost the Cleric first in 26 of 34, often a
# level behind with 200 fewer max HP. It steps away at half HP. (Holding it
# out of melee entirely, 243d2e9, starved it of kills: batch 3bb71ce b1 sat
# at levels 5/5/2/5 until it starved.)
HEALER_BACK_LEVEL = 5


def _held_back_healer(arena: CombatArena, member: Any) -> bool:
    """A low-level Cleric with another living, non-Cleric member to fight."""
    if getattr(member, "profession", None) != Profession.CLERIC:
        return False
    if getattr(member, "level", 25) >= HEALER_BACK_LEVEL:
        return False
    return any(
        m is not member and not _is_member_dead(m) and getattr(m, "profession", None) != Profession.CLERIC
        for m in getattr(arena.party, "members", ())
    )


def _try_low_hp_retreat(
    arena: CombatArena,
    member_idx: int,
    member: Any,
    pos: tuple[int, int],
    visible_monsters: list[CombatMonster],
) -> Action | None:
    """Retreat one cardinal step if HP is critical (half, for a held-back
    healer) and an enemy is adjacent."""
    # The last one standing gains nothing by stepping back: nobody comes to
    # heal, and the step back and in again can go on forever (batch 1c7525f
    # seed 17: a lone Fighter and one Goblin from step 45,791 to the cap).
    if not any(
        i != member_idx and not _is_member_dead(m) for i, m in enumerate(arena.party.members)
    ):
        return None
    max_hp = getattr(member, "max_hp", 0)
    floor = max_hp // 2 if _held_back_healer(arena, member) else max(15, max_hp // 5)
    if getattr(member, "hp", 0) > floor:
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


def _is_member_dead(member: Any) -> bool:
    """Return True if ``member`` is dead (handling both method and bool attr)."""
    is_dead_attr = getattr(member, "is_dead", False)
    return is_dead_attr() if callable(is_dead_attr) else bool(is_dead_attr)


def _is_magic_negated(arena: CombatArena) -> bool:
    """Return True if the party is currently under an active NEGATE aura."""
    aura = getattr(arena.party, "aura", None)
    return aura is not None and aura.get_type() == AuraType.NEGATE


def _can_cast_spell(member: Any, spell: Spell) -> bool:
    """Return True if ``member`` can cast ``spell`` with current MP."""
    prof = getattr(member, "profession", None)
    if prof is None or not spell.can_cast(prof):
        return False
    if getattr(member, "mp", 0) < spell.cost:
        return False
    return True


def _is_undead(monster: CombatMonster) -> bool:
    """Return True if ``monster`` is undead by definition flag or tile."""
    definition = getattr(monster, "definition", None)
    if definition is not None and getattr(definition, "undead", False):
        return True
    return getattr(monster, "tile", None) in _UNDEAD_TILES


def _is_poisonous(monster: CombatMonster) -> bool:
    """Return True if ``monster`` inflicts poison."""
    if getattr(monster, "poisons", False):
        return True
    definition = getattr(monster, "definition", None)
    if definition is None:
        return False
    return bool(getattr(definition, "poisons", False) or getattr(definition, "poison", False))


def _find_lowest_hp_heal_target(party: Any) -> Any | None:
    """Return the lowest-HP living party member needing urgent healing, or None."""
    candidates = [
        m
        for m in getattr(party, "members", ())
        if not _is_member_dead(m)
        and m.hp * 4 < m.max_hp * 3
        and m.hp < m.max_hp
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: m.hp)


_TRAINING_SPELLS = (Spell.UNSPEAKABLE, Spell.ZXKUQYB, Spell.NECORP, Spell.DAG_MENTAR, Spell.NOXUM)


def _caster_in_training(party: Any, member: Any) -> bool:
    """A caster below level 25 while another living member is already 25."""
    if getattr(member, "level", 25) >= 25:
        return False
    return any(
        m is not member and not _is_member_dead(m) and getattr(m, "level", 0) >= 25
        for m in getattr(party, "members", ())
    )


def _try_pre_attack_spell(
    arena: CombatArena,
    member: Any,
    visible_monsters: list[CombatMonster],
) -> Action | None:
    """Evaluate Lairware-style priority spellcasting before melee/ranged attacks."""
    # LairWare UltimaAutocombat.c:98-113: Repond and Pontori are asked only
    # while the battle's latch (g5521 / g56E7) is still 0: one try per
    # battle, whichever member makes it (A-02).
    if not getattr(arena, "repond_latch", False) and _can_cast_spell(member, Spell.REPOND):
        if any(getattr(m, "tile", None) == "orc" for m in visible_monsters):
            return Action.cast(Spell.REPOND)

    if not getattr(arena, "pontori_latch", False) and _can_cast_spell(member, Spell.PONTORI):
        if any(_is_undead(m) for m in visible_monsters):
            return Action.cast(Spell.PONTORI)

    # Training (user idea 2026-11-22): experience goes to whoever kills, so
    # once a fighter is level 25 a lagging caster opens every 2+ monster
    # fight with its strongest area spell, whatever the threat, unless
    # someone needs healing first.
    if (
        len(visible_monsters) >= 2
        and _caster_in_training(arena.party, member)
        and _find_lowest_hp_heal_target(arena.party) is None
    ):
        for spell in _TRAINING_SPELLS:
            if _can_cast_spell(member, spell):
                return Action.cast(spell)

    if len(visible_monsters) >= 2:
        threat = sum(
            getattr(m, "exp", 10) * (2 if _is_poisonous(m) else 1)
            for m in visible_monsters
        )
        if threat > 60 and _can_cast_spell(member, Spell.UNSPEAKABLE):
            return Action.cast(Spell.UNSPEAKABLE)
        if threat > 80 and _can_cast_spell(member, Spell.ZXKUQYB):
            return Action.cast(Spell.ZXKUQYB)
        if len(visible_monsters) >= 3 and threat >= 45:
            if _can_cast_spell(member, Spell.NOXUM):
                return Action.cast(Spell.NOXUM)
            if _can_cast_spell(member, Spell.DAG_MENTAR):
                return Action.cast(Spell.DAG_MENTAR)
            if _can_cast_spell(member, Spell.NECORP):
                return Action.cast(Spell.NECORP)

    lowest_member = _find_lowest_hp_heal_target(arena.party)
    if lowest_member is not None:
        if _can_cast_spell(member, Spell.SANCTU_MANI):
            return Action.cast(Spell.SANCTU_MANI, target_member=lowest_member)
        if _can_cast_spell(member, Spell.SANCTU):
            return Action.cast(Spell.SANCTU, target_member=lowest_member)

    return None


def _find_ranged_attack_dir(
    arena: CombatArena,
    px: int,
    py: int,
    max_range: int,
    attack_through: bool,
    visible_positions: set[tuple[int, int]],
) -> Direction | None:
    """Return the first cardinal direction with a clear LoS hit on a visible monster."""
    for d in _CARDINAL_DIRS:
        path = trace_projectile_path(
            combat_map=arena.combat_map,
            start_x=px,
            start_y=py,
            direction=d,
            max_range=max_range,
            attack_through_objects=attack_through,
            monsters=arena.monsters,
            players=arena.player_positions,
        )
        if path and path[-1] in visible_positions:
            return d
    return None


def choose_auto_combat_action(
    arena: CombatArena, member_idx: int, asset_mgr: Any = None
) -> Action:
    """Choose a tactical combat ``Action`` for ``arena.party.members[member_idx]``."""
    if member_idx < 0 or member_idx >= len(arena.party.members):
        return Action.pass_turn()

    member = arena.party.members[member_idx]
    if _is_member_dead(member) or member_idx not in arena.player_positions:
        return Action.pass_turn()

    pos = arena.player_positions[member_idx]
    visible_monsters = [m for m in arena.monsters if not m.is_dead and m.visible]
    if not visible_monsters:
        return Action.pass_turn()

    retreat = _try_low_hp_retreat(arena, member_idx, member, pos, visible_monsters)
    if retreat is not None:
        return retreat

    negated = _is_magic_negated(arena)
    if not negated:
        spell_action = _try_pre_attack_spell(arena, member, visible_monsters)
        if spell_action is not None:
            return spell_action

    px, py = pos
    visible_positions = {(m.x, m.y) for m in visible_monsters}

    # Adjacent cardinal melee attack
    for d in _CARDINAL_DIRS:
        if (px + d.dx, py + d.dy) in visible_positions:
            return Action.attack(d)

    can_cast_mittar = (
        not negated
        and _can_cast_spell(member, Spell.MITTAR)
        and getattr(member, "weapon", WeaponType.NONE) not in _NO_MITTAR_WEAPONS
    )
    if not negated and getattr(member, "weapon", WeaponType.NONE) not in _NO_MITTAR_WEAPONS:
        spells = (Spell.FULGAR, Spell.MITTAR) if getattr(arena, "ship_battle", False) else (Spell.MITTAR,)
        for spell in spells:
            if _can_cast_spell(member, spell):
                spell_dir = _find_ranged_attack_dir(
                    arena, px, py, max_range=5, attack_through=False, visible_positions=visible_positions
                )
                if spell_dir is not None:
                    return Action.cast(spell, direction=spell_dir)

    effective_asset_mgr = asset_mgr if asset_mgr is not None else getattr(arena, "asset_mgr", None)
    weapon_range, attack_through = _get_weapon_info(member, effective_asset_mgr)

    # Cardinal ranged attack with clear line of sight
    if weapon_range > 1:
        ranged_dir = _find_ranged_attack_dir(
            arena,
            px,
            py,
            max_range=weapon_range,
            attack_through=attack_through,
            visible_positions=visible_positions,
        )
        if ranged_dir is not None:
            return Action.attack(ranged_dir)

    # Advance toward nearest visible living monster.
    # For melee fighters, prefer BFS shortest path first so obstacles (like ship masts)
    # don't cause greedy-Manhattan orbiting loops.
    if weapon_range <= 1 and not can_cast_mittar:
        bfs_dir = _find_bfs_move_dir(
            arena,
            member_idx,
            px,
            py,
            visible_positions=visible_positions,
            weapon_range=weapon_range,
            attack_through=attack_through,
            can_cast_mittar=can_cast_mittar,
        )
        if bfs_dir is not None:
            return Action.move(bfs_dir)

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
        if weapon_range > 1 or can_cast_mittar:
            score = (new_dist, min(abs(target.x - nx), abs(target.y - ny)))
        else:
            score = (new_dist, max(abs(target.x - nx), abs(target.y - ny)))
        if best_move_score is None or score < best_move_score:
            best_move_score = score
            best_move_dir = d

    if best_move_dir is not None:
        return Action.move(best_move_dir)

    bfs_dir = _find_bfs_move_dir(
        arena,
        member_idx,
        px,
        py,
        visible_positions=visible_positions,
        weapon_range=weapon_range,
        attack_through=attack_through,
        can_cast_mittar=can_cast_mittar,
    )
    if bfs_dir is not None:
        return Action.move(bfs_dir)

    return Action.pass_turn()


def _find_bfs_move_dir(
    arena: CombatArena,
    member_idx: int,
    px: int,
    py: int,
    *,
    visible_positions: set[tuple[int, int]],
    weapon_range: int,
    attack_through: bool,
    can_cast_mittar: bool,
) -> Direction | None:
    """BFS on the 11x11 arena to route around masts/walls/allies to an attack position."""
    queue: deque[tuple[int, int, Direction]] = deque()
    visited: set[tuple[int, int]] = {(px, py)}
    best_score = min(
        ((abs(px - mx) + abs(py - my), (px - mx) ** 2 + (py - my) ** 2) for mx, my in visible_positions),
        default=(9999, 9999),
    )
    best_dir: Direction | None = None
    for d in _CARDINAL_DIRS:
        nx, ny = px + d.dx, py + d.dy
        if (nx, ny) not in visited and _is_walkable_unoccupied(arena, member_idx, nx, ny):
            visited.add((nx, ny))
            queue.append((nx, ny, d))

    while queue:
        cx, cy, first_dir = queue.popleft()
        score = min(
            ((abs(cx - mx) + abs(cy - my), (cx - mx) ** 2 + (cy - my) ** 2) for mx, my in visible_positions),
            default=(9999, 9999),
        )
        if score[0] == 1:
            return first_dir
        if score < best_score:
            best_score = score
            best_dir = first_dir
        if weapon_range > 1 and _find_ranged_attack_dir(
            arena,
            cx,
            cy,
            max_range=weapon_range,
            attack_through=attack_through,
            visible_positions=visible_positions,
        ) is not None:
            return first_dir
        if can_cast_mittar and _find_ranged_attack_dir(
            arena,
            cx,
            cy,
            max_range=5,
            attack_through=False,
            visible_positions=visible_positions,
        ) is not None:
            return first_dir

        for d in _CARDINAL_DIRS:
            nx, ny = cx + d.dx, cy + d.dy
            if (nx, ny) not in visited and _is_walkable_unoccupied(arena, member_idx, nx, ny):
                visited.add((nx, ny))
                queue.append((nx, ny, first_dir))

    return best_dir
