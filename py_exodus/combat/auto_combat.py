"""Auto-combat tactical AI decision engine (inspired by Lairware UltimaAutocombat.c)."""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from py_exodus.aura import AuraType
from py_exodus.combat.arena import Action
from py_exodus.combat.resolver import trace_projectile_path
from py_exodus.constants import Direction, Spell, TileAttrib, WeaponType

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

# LairWare UltimaAutocombat.c:153: only weapons 9 and 13 (Bow +2, Bow +4)
# stop the Mittar habit; an Exotic holder casts it too (A-07).
_NO_MITTAR_WEAPONS: frozenset[WeaponType] = frozenset(
    {
        WeaponType.BOW_P2,
        WeaponType.BOW_P4,
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

    # LairWare UltimaAutocombat.c:155 (A-09, user ruling 2026-11-25): only
    # weapons 3, 5, 9, 13 (sling, bow, Bow +2, Bow +4) are projectile
    # weapons; a dagger is a hand weapon, never thrown, spares or not.
    if wt == WeaponType.DAGGER:
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


# LairWare NearlyDead (UltimaAutocombat.c:268-291): under 50 HP, absolute.
NEARLY_DEAD_HP = 50

# LairWare AutoCombat (UltimaAutocombat.c:57-91), classic mode (no
# diagonals, A-13): the flee squares are tried S, W, E, N.
_FLEE_ORDER: tuple[Direction, ...] = (
    Direction.SOUTH,
    Direction.WEST,
    Direction.EAST,
    Direction.NORTH,
)


def _monster_can_attack(monsters: list[CombatMonster], x: int, y: int) -> bool:
    """LairWare MonsterCanAttack (UltimaAutocombat.c:237-266): a living
    monster on one of the 8 squares round ``(x, y)``."""
    return any(max(abs(m.x - x), abs(m.y - y)) == 1 for m in monsters)


def _someone_else_can_fight(arena: CombatArena, member_idx: int) -> bool:
    """Another living member is at NEARLY_DEAD_HP or more. Without one, a
    nearly dead member acts as the last one does (fights, closes in): with
    every member under 50 HP and monsters that never close in, all of them
    used to pass forever (review 2026-11-25)."""
    return any(
        i != member_idx and not _is_member_dead(m) and getattr(m, "hp", 0) >= NEARLY_DEAD_HP
        for i, m in enumerate(arena.party.members)
    )


def _try_low_hp_retreat(
    arena: CombatArena,
    member_idx: int,
    member: Any,
    pos: tuple[int, int],
    visible_monsters: list[CombatMonster],
) -> Action | None:
    """LairWare flee (UltimaAutocombat.c:56-91, A-01, user ruling
    2026-11-25): a member under 50 HP with a monster next to it steps S, W,
    E or N (first that works) onto a free square no monster neighbours. No
    such square: ``None``, and it fights on."""
    # User ruling 2026-11-25: the last living member never flees (batch
    # 1c7525f seed 17: a lone Fighter stepped back and in from step 45,791
    # to the cap).
    if not _someone_else_can_fight(arena, member_idx):
        return None
    if getattr(member, "hp", 0) >= NEARLY_DEAD_HP:
        return None
    living = [m for m in arena.monsters if not m.is_dead]
    px, py = pos
    if not _monster_can_attack(living, px, py):
        return None
    for d in _FLEE_ORDER:
        nx, ny = px + d.dx, py + d.dy
        if not _is_walkable_unoccupied(arena, member_idx, nx, ny):
            continue
        if _monster_can_attack(living, nx, ny):
            continue
        return Action.move(d)
    return None


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


# LairWare AutoCombat Sanctu (UltimaAutocombat.c:130-149): heal only a
# member under 75 HP, absolute.
SANCTU_BELOW_HP = 75


def _find_lowest_hp_heal_target(party: Any) -> Any | None:
    """LairWare (UltimaAutocombat.c:132-141, A-06/A-12): the living member
    with the lowest HP, first slot on a tie, if that HP is under 75."""
    living = [m for m in getattr(party, "members", ()) if not _is_member_dead(m)]
    if not living:
        return None
    lowest = min(living, key=lambda m: m.hp)
    return lowest if lowest.hp < SANCTU_BELOW_HP else None


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

    # LairWare UltimaAutocombat.c:130-149 (A-06, user ruling 2026-11-25):
    # Sanctu only, never Sanctu Mani, in combat.
    if _can_cast_spell(member, Spell.SANCTU):
        lowest_member = _find_lowest_hp_heal_target(arena.party)
        if lowest_member is not None:
            return Action.cast(Spell.SANCTU, target_member=lowest_member)

    return None


def _monster_lined_up_dir(
    px: int, py: int, monsters: list[CombatMonster]
) -> Direction | None:
    """LairWare MonsterLinedUp (UltimaAutocombat.c:457-506), classic mode
    (no diagonals, user ruling): the nearest monster on the caster's row or
    column by ``|dx| + |dy|``, first slot on ties, at any range. No wall
    test: the port's Mittar flies over walls to the edge (P-23)."""
    best: CombatMonster | None = None
    best_dist = 128
    for m in monsters:
        if m.x != px and m.y != py:
            continue
        dist = abs(m.x - px) + abs(m.y - py)
        if 0 < dist < best_dist:
            best, best_dist = m, dist
    if best is None:
        return None
    if best.x == px:
        return Direction.NORTH if best.y < py else Direction.SOUTH
    return Direction.WEST if best.x < px else Direction.EAST


def _line_up_step(
    arena: CombatArena,
    member_idx: int,
    px: int,
    py: int,
    monsters: list[CombatMonster],
) -> Direction | None:
    """First step to the nearest square that shares a row or column with a
    living monster (user ruling 2026-11-25, brief item A): a Mittar caster
    with nothing lined up walks there and casts, since the bolt flies over
    walls and the rail (LW Shoot, UltimaSpellCombat.c:708-731). The square
    is walkable and free; one no monster stands next to (any of its 8
    neighbours) wins over a nearer one beside a monster. ``None`` when no
    such square can be reached: the caller keeps today's moves, so a caster
    never paces."""
    if not monsters:
        return None
    visited: set[tuple[int, int]] = {(px, py)}
    queue: deque[tuple[int, int, Direction]] = deque()
    for d in _CARDINAL_DIRS:
        nx, ny = px + d.dx, py + d.dy
        if _is_walkable_unoccupied(arena, member_idx, nx, ny):
            visited.add((nx, ny))
            queue.append((nx, ny, d))
    nearest_any: Direction | None = None
    while queue:
        cx, cy, first_dir = queue.popleft()
        if _monster_lined_up_dir(cx, cy, monsters) is not None:
            if not _monster_can_attack(monsters, cx, cy):
                return first_dir
            if nearest_any is None:
                nearest_any = first_dir
        for d in _CARDINAL_DIRS:
            nx, ny = cx + d.dx, cy + d.dy
            if (nx, ny) not in visited and _is_walkable_unoccupied(arena, member_idx, nx, ny):
                visited.add((nx, ny))
                queue.append((nx, ny, first_dir))
    return nearest_any


# Brief item B (user ruling 2026-11-25): a member whose weapon is the Exotic
# carries a plain Bow (LW weapon 5, a projectile weapon, UltimaAutocombat.c:
# 155) for fights where nothing can be reached.
_SPARE_BOW = WeaponType.BOW


def _can_ready(member: Any, wt: WeaponType, asset_mgr: Any) -> bool:
    """``member`` holds a ``wt`` in its pack and its class may ready it
    (the test ``Character.ready_weapon`` makes)."""
    if getattr(member, "weapons", {}).get(wt, 0) <= 0:
        return False
    if asset_mgr is not None:
        w_def = asset_mgr.get_weapon(wt.name.lower())
        if w_def is not None and not w_def.can_use(member.profession):
            return False
    return True


def _monster_in_reach(
    arena: CombatArena, px: int, py: int, monsters: list[CombatMonster]
) -> bool:
    """A living monster is next to ``(px, py)`` (a cardinal side, where a
    hand weapon strikes, A-13) or a walk over open ground leads to a square
    next to one. Members are no obstacle (they move); monsters are."""
    if not monsters:
        return False
    occupied = {(m.x, m.y) for m in monsters}
    goals = {(m.x + d.dx, m.y + d.dy) for m in monsters for d in _CARDINAL_DIRS}
    width, height = arena.combat_map.width, arena.combat_map.height
    seen = {(px, py)}
    queue: deque[tuple[int, int]] = deque([(px, py)])
    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) in goals:
            return True
        for d in _CARDINAL_DIRS:
            nx, ny = cx + d.dx, cy + d.dy
            if (nx, ny) in seen or (nx, ny) in occupied:
                continue
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            tile = arena.combat_map.get_tile(nx, ny)
            if tile is not None and bool(getattr(tile, "attribs", TileAttrib.NONE) & TileAttrib.UNWALKABLE):
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return False


def _holds_spare_bow(member: Any) -> bool:
    """The spare Bow is readied and the Exotic waits in the pack."""
    return (
        getattr(member, "weapon", WeaponType.NONE) == _SPARE_BOW
        and getattr(member, "weapons", {}).get(WeaponType.EXOTIC, 0) > 0
    )


def _spare_bow_switch(
    arena: CombatArena,
    member: Any,
    px: int,
    py: int,
    monsters: list[CombatMonster],
    asset_mgr: Any,
) -> Action | None:
    """Brief item B (user ruling 2026-11-25). An Exotic holder with a Bow in
    the pack readies the Bow (R, which takes the turn, as in LW) only when
    no monster is next to it and no walk brings one within reach; it readies
    the Exotic again once a monster is next to it. In Castle Exodus only
    Exotics hit (B-21), so the Bow is never readied there and put away if
    held. The two tests never hold at once, so a member switches at most
    once each time the fight changes, never back and forth every turn."""
    is_exodus = getattr(arena, "_is_exodus_map", None)
    in_exodus = bool(is_exodus()) if callable(is_exodus) else False
    adjacent = any(
        (px + d.dx, py + d.dy) == (m.x, m.y) for m in monsters for d in _CARDINAL_DIRS
    )
    if _holds_spare_bow(member):
        if (in_exodus or adjacent) and _can_ready(member, WeaponType.EXOTIC, asset_mgr):
            return Action.ready(WeaponType.EXOTIC)
        return None
    if (
        not in_exodus
        and getattr(member, "weapon", WeaponType.NONE) == WeaponType.EXOTIC
        and _can_ready(member, _SPARE_BOW, asset_mgr)
        and not _monster_in_reach(arena, px, py, monsters)
    ):
        return Action.ready(_SPARE_BOW)
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

    # LairWare UltimaAutocombat.c:150-166 (A-07): a wizard-book caster with
    # 5+ MP not holding a Bow +2 or +4 never melees; it casts Mittar at the
    # nearest monster lined up with it, at any range, adjacent included.
    can_cast_mittar = (
        not negated
        and _can_cast_spell(member, Spell.MITTAR)
        and getattr(member, "weapon", WeaponType.NONE) not in _NO_MITTAR_WEAPONS
    )
    effective_asset_mgr = asset_mgr if asset_mgr is not None else getattr(arena, "asset_mgr", None)
    if not can_cast_mittar:
        switch = _spare_bow_switch(
            arena, member, px, py, [m for m in arena.monsters if not m.is_dead], effective_asset_mgr
        )
        if switch is not None:
            return switch

    if can_cast_mittar:
        # MonsterLinedUp counts every monster with HP (UltimaAutocombat.c:
        # 465-467: ``if (MonsterHP[mon] != 0)``), seen or not.
        living_monsters = [m for m in arena.monsters if not m.is_dead]
        spell_dir = _monster_lined_up_dir(px, py, living_monsters)
        if spell_dir is not None:
            # Port habit (A-08, deferred): Fulgar first in a ship battle.
            if getattr(arena, "ship_battle", False) and _can_cast_spell(member, Spell.FULGAR):
                return Action.cast(Spell.FULGAR, direction=spell_dir)
            return Action.cast(Spell.MITTAR, direction=spell_dir)
    elif getattr(member, "weapon", WeaponType.NONE) in _RANGED_WEAPON_TYPES:
        # LairWare UltimaAutocombat.c:155-169 (A-09, user ruling
        # 2026-11-25): a sling or bow shoots the nearest monster lined up on
        # its row or column, any range, adjacent included; missiles fly over
        # walls (B-06), so no wall test.
        living_monsters = [m for m in arena.monsters if not m.is_dead]
        shot_dir = _monster_lined_up_dir(px, py, living_monsters)
        if shot_dir is not None:
            return Action.attack(shot_dir)
    else:
        # Adjacent cardinal melee attack
        for d in _CARDINAL_DIRS:
            if (px + d.dx, py + d.dy) in visible_positions:
                return Action.attack(d)

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

    # LairWare UltimaAutocombat.c:177-180 (A-11, review 2026-11-25): a
    # member under 50 HP doesn't advance. Having fled (or found no square)
    # it attacks or shoots what it can from where it stands, and otherwise
    # passes, instead of stepping straight back in. The last living member
    # still closes in (nobody else can end the fight), and so does everyone
    # when no living member has 50 HP or more.
    if getattr(member, "hp", 0) < NEARLY_DEAD_HP and _someone_else_can_fight(arena, member_idx):
        return Action.pass_turn()

    # Brief item A (user ruling 2026-11-25): a Mittar caster with nothing
    # lined up steps toward the nearest square that lines one up (its bolt
    # flies over walls), rather than closing on the nearest monster: a Man-
    # O-War beside the hull is never reached that way. No such square:
    # the moves below, as before.
    # A member holding its spare Bow (item B) lines up the same way.
    if can_cast_mittar or _holds_spare_bow(member):
        line_dir = _line_up_step(
            arena, member_idx, px, py, [m for m in arena.monsters if not m.is_dead]
        )
        if line_dir is not None:
            return Action.move(line_dir)

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
