"""LairWare parity, batch A (auto-combat): pins LairWare AutoCombat rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "A - Auto-combat".
"""
from __future__ import annotations

from py_exodus.combat.arena import ActionType, CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
import pytest

from py_exodus.constants import Direction, Profession, Race, Spell, Status, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.map import ConflictMap


def _arena(*profs: Profession, creature: str = "orc", count: int = 1, mp: int = 0,
           grass=None) -> CombatArena:
    party = Party(transport=Transport.FOOT)
    for i, prof in enumerate(profs):
        party.add_member(Character(f"C{i}", "M", Race.HUMAN, prof, mp=mp, hp=300, max_hp=300,
                                   intelligence=50, wisdom=50))
    cmap = ConflictMap(width=11, height=11, tiles=[grass] * (11 * 11))
    arena = CombatArena(party=party, combat_map=cmap, creature_tile=creature, monster_count=count)
    for i in range(len(profs)):
        arena.player_positions[i] = (2 + 2 * i, 9)
        party.members[i].combat_x, party.members[i].combat_y = 2 + 2 * i, 9
    for j, mon in enumerate(arena.monsters):
        mon.x, mon.y = 8, 1 + j
    return arena


# --- A-02 (user ruling 2026-11-25): Repond / Pontori one try per battle ---------


def test_autocombat_repond_asked_only_while_latch_clear():
    """UltimaAutocombat.c:98-104: ``if ((gMonType == 0x30) && (g5521 == 0)
    && isWiz)`` -- asked while the battle latch is 0, by any wizard-book
    member; once any caster's try set it, no one asks again."""
    arena = _arena(Profession.WIZARD, Profession.WIZARD)
    assert choose_auto_combat_action(arena, 0).spell == Spell.REPOND
    assert choose_auto_combat_action(arena, 1).spell == Spell.REPOND
    arena.repond_latch = True
    for i in (0, 1):
        assert choose_auto_combat_action(arena, i).spell != Spell.REPOND


def test_autocombat_pontori_asked_only_while_latch_clear():
    """UltimaAutocombat.c:106-112: ``(gMonType == 0x32) && (g56E7 == 0) &&
    isCler``."""
    arena = _arena(Profession.CLERIC, Profession.PALADIN, creature="skeleton")
    assert choose_auto_combat_action(arena, 1).spell == Spell.PONTORI
    arena.pontori_latch = True
    for i in (0, 1):
        assert choose_auto_combat_action(arena, i).spell != Spell.PONTORI


# --- A-07 (user ruling 2026-11-25): wizards cast Mittar instead of closing in ----


def _wiz(asset_mgr, prof=Profession.WIZARD, mp=10, weapon=WeaponType.DAGGER, at=(5, 5),
         monsters=((5, 4),)):
    """One caster on an all-grass board; monsters at the given squares."""
    grass = asset_mgr.tile_defs_by_name["grass"]
    arena = _arena(prof, creature="orc", count=len(monsters), mp=mp, grass=grass)
    m = arena.party.members[0]
    m.weapon = weapon
    arena.player_positions[0] = at
    m.combat_x, m.combat_y = at
    for mon, (x, y) in zip(arena.monsters, monsters):
        mon.x, mon.y = x, y
    arena.repond_latch = True  # Repond (asked first, A-02) already tried
    return arena


@pytest.mark.parametrize(
    "prof", [Profession.WIZARD, Profession.LARK, Profession.ALCHEMIST, Profession.DRUID,
             Profession.RANGER])
def test_autocombat_wizard_casts_mittar_at_adjacent_monster(asset_mgr, prof):
    """UltimaAutocombat.c:151-166: ``if ((magic >= 5) && isWiz && (wpn != 9)
    && (wpn != 13)) castMittar = TRUE;`` then ``dir = MonsterLinedUp(...);
    if (dir != 0 ...) { if (castMittar) { AddMacro(dir); AddMacro('B'); ...``
    -- an adjacent monster is lined up too, so the caster casts, never
    melees (the hand-to-hand branch is the else, 175)."""
    arena = _wiz(asset_mgr, prof=prof)
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST and action.spell == Spell.MITTAR
    assert action.direction == Direction.NORTH


def test_autocombat_mittar_any_range_over_walls(asset_mgr):
    """UltimaAutocombat.c:457-470: MonsterLinedUp takes any monster on the
    caster's row or column, at any distance, and tests no walls; the port's
    Mittar flies over walls to the edge (P-23), so a wall between is no
    reason to skip the shot."""
    arena = _wiz(asset_mgr, at=(1, 5), monsters=((9, 5),))
    wall = asset_mgr.tile_defs_by_name["wall"]
    for x in range(3, 8):
        arena.combat_map.set_tile(x, 5, wall)
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST and action.spell == Spell.MITTAR
    assert action.direction == Direction.EAST


def test_autocombat_mittar_nearest_lined_up_monster(asset_mgr):
    """UltimaAutocombat.c:470-476: the nearest by ``Absolute(dx) +
    Absolute(dy)``, first slot on ties (strict ``<``)."""
    arena = _wiz(asset_mgr, monsters=((5, 0), (8, 5)))  # N at 5, E at 3
    assert choose_auto_combat_action(arena, 0).direction == Direction.EAST
    arena = _wiz(asset_mgr, monsters=((2, 5), (8, 5)))  # W at 3, E at 3: slot 0
    assert choose_auto_combat_action(arena, 0).direction == Direction.WEST


def test_autocombat_mittar_lines_up_every_living_monster(asset_mgr):
    """UltimaAutocombat.c:465-467: ``if (MonsterHP[mon] != 0)`` -- every
    monster with HP counts for MonsterLinedUp, seen or not; the port
    passed only the visible ones. A hidden lined-up monster nearer than a
    visible one draws the shot; a dead one never does."""
    arena = _wiz(asset_mgr, monsters=((5, 0), (8, 5)))  # N at 5, E at 3
    arena.monsters[1].visible = False
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST and action.direction == Direction.EAST
    arena.monsters[1].hp = 0
    assert choose_auto_combat_action(arena, 0).direction == Direction.NORTH


def test_autocombat_mittar_rows_and_columns_only(asset_mgr):
    """User ruling (classic mode, U3PrefNoDiagonals, UltimaAutocombat.c:
    468-469): a diagonal monster is not lined up, so no cast; the port's
    route-finding moves instead (A-10)."""
    arena = _wiz(asset_mgr, monsters=((7, 3),))
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.MOVE


@pytest.mark.parametrize("weapon, casts", [
    (WeaponType.EXOTIC, True), (WeaponType.SWORD, True),
    (WeaponType.BOW_P2, False), (WeaponType.BOW_P4, False)])
def test_autocombat_mittar_skipped_only_for_magic_bows(asset_mgr, weapon, casts):
    """UltimaAutocombat.c:153: only weapons 9 and 13 (Bow +2, Bow +4) stop
    the Mittar habit; an Exotic holder casts it too."""
    arena = _wiz(asset_mgr, weapon=weapon)
    action = choose_auto_combat_action(arena, 0)
    assert (action.type == ActionType.CAST and action.spell == Spell.MITTAR) is casts


def test_autocombat_mittar_needs_5_mp(asset_mgr):
    """UltimaAutocombat.c:153 ``magic >= 5``: at 4 MP the caster melees."""
    arena = _wiz(asset_mgr)
    arena.party.members[0].mp = 4  # after combat start's MP tick
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.ATTACK and action.direction == Direction.NORTH


# --- A-01 (user ruling 2026-11-25): flee under 50 HP, absolute -------------------


def _melee(asset_mgr, hp: int, at=(5, 5), monsters=((5, 4),), partners: int = 1,
           max_hp: int = 2550):
    """A Fighter with a sword at ``at`` on grass, plus ``partners`` living
    Fighters parked far away."""
    grass = asset_mgr.tile_defs_by_name["grass"]
    arena = _arena(*([Profession.FIGHTER] * (1 + partners)), count=len(monsters), grass=grass)
    m = arena.party.members[0]
    m.weapon = WeaponType.SWORD
    m.hp, m.max_hp = hp, max_hp
    arena.player_positions[0] = at
    m.combat_x, m.combat_y = at
    for i in range(1, 1 + partners):
        arena.player_positions[i] = (10, 10 - i)
    for mon, (x, y) in zip(arena.monsters, monsters):
        mon.x, mon.y = x, y
    return arena


def test_autocombat_flee_under_50_hp_absolute(asset_mgr):
    """UltimaAutocombat.c:57 ``if (NearlyDead(chnum + 1) && MonsterCanAttack
    (x, y))`` and :276-278 ``if (hp < 50) nearlyDead = TRUE`` -- absolute,
    whatever the max HP: 49 steps away, 50 fights."""
    arena = _melee(asset_mgr, hp=49, max_hp=100)
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.MOVE and action.direction == Direction.SOUTH
    arena = _melee(asset_mgr, hp=50, max_hp=2550)
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.ATTACK and action.direction == Direction.NORTH


def test_autocombat_flee_on_a_diagonal_neighbour(asset_mgr):
    """UltimaAutocombat.c:246-253: MonsterCanAttack looks at all 8 squares
    round the member, so a diagonal monster triggers the flee."""
    arena = _melee(asset_mgr, hp=20, monsters=((6, 4),))
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.MOVE and action.direction == Direction.SOUTH


def test_autocombat_flee_order_south_west_east_north(asset_mgr):
    """UltimaAutocombat.c:59-84, classic mode: '2' (S), '4' (W), '6' (E),
    '8' (N), the first square no monster neighbours and no member holds."""
    # Monster S: S is taken, W (4,5) still neighbours it, so is E; N is free.
    arena = _melee(asset_mgr, hp=20, monsters=((5, 6),))
    assert choose_auto_combat_action(arena, 0).direction == Direction.NORTH
    # Monster SE: S (5,6) and E (6,5) neighbour it; W (4,5) is free.
    arena = _melee(asset_mgr, hp=20, monsters=((6, 6),))
    assert choose_auto_combat_action(arena, 0).direction == Direction.WEST


def test_autocombat_flee_blocked_fights(asset_mgr):
    """UltimaAutocombat.c:89-91: with no safe square the auto-combat-off
    lines are commented out, so the member falls through and fights."""
    arena = _melee(asset_mgr, hp=20, monsters=((5, 4), (5, 6), (4, 5), (6, 5)))
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.ATTACK


def test_autocombat_last_living_member_never_flees(asset_mgr):
    """User ruling 2026-11-25 (port keep, e3dade6): the last one standing
    fights; LW would flee, and the step back and in loops."""
    arena = _melee(asset_mgr, hp=20, partners=1)
    arena.party.members[1].hp = 0
    arena.party.members[1].status = Status.DEAD
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.ATTACK and action.direction == Direction.NORTH


# --- A-06 (user ruling 2026-11-25): Sanctu under 75 HP, never Sanctu Mani --------


def _healer(asset_mgr, hps: tuple[int, ...], mp: int = 99):
    grass = asset_mgr.tile_defs_by_name["grass"]
    arena = _arena(Profession.CLERIC, *([Profession.FIGHTER] * (len(hps) - 1)),
                   mp=mp, grass=grass)
    for m, hp in zip(arena.party.members, hps):
        m.hp, m.max_hp = hp, 2550
    arena.party.members[0].mp = mp
    arena.pontori_latch = True
    return arena


def test_autocombat_sanctu_only_under_75_hp(asset_mgr):
    """UltimaAutocombat.c:142 ``if (lowestHP < 75)`` -- absolute; 75 HP of
    2550 gets no heal, 74 does."""
    arena = _healer(asset_mgr, (2550, 75))
    assert getattr(choose_auto_combat_action(arena, 0), "spell", None) is None
    arena = _healer(asset_mgr, (2550, 74))
    action = choose_auto_combat_action(arena, 0)
    assert action.spell == Spell.SANCTU and action.target_member is arena.party.members[1]


def test_autocombat_never_sanctu_mani(asset_mgr):
    """UltimaAutocombat.c:143-147: the macro is always 'C' (Sanctu), never
    Sanctu Mani, even with MP for it."""
    arena = _healer(asset_mgr, (2550, 10), mp=99)
    assert choose_auto_combat_action(arena, 0).spell == Spell.SANCTU


def test_autocombat_sanctu_needs_10_mp(asset_mgr):
    """UltimaAutocombat.c:131 ``if (magic >= 10 && isCler)``."""
    arena = _healer(asset_mgr, (2550, 10), mp=9)
    assert getattr(choose_auto_combat_action(arena, 0), "spell", None) != Spell.SANCTU


def test_autocombat_sanctu_lowest_hp_first_slot_on_tie(asset_mgr):
    """UltimaAutocombat.c:134-140: ``hp < lowestHP`` (strict), slots 0-3,
    the caster included."""
    arena = _healer(asset_mgr, (2550, 40, 40))
    assert choose_auto_combat_action(arena, 0).target_member is arena.party.members[1]
    arena = _healer(asset_mgr, (30, 40, 40))
    assert choose_auto_combat_action(arena, 0).target_member is arena.party.members[0]


# --- A-09 (user ruling 2026-11-25): missile weapons ------------------------------


@pytest.mark.parametrize("weapon", [WeaponType.SLING, WeaponType.BOW, WeaponType.BOW_P2,
                                    WeaponType.BOW_P4])
def test_autocombat_missile_shoots_nearest_lined_up(asset_mgr, weapon):
    """UltimaAutocombat.c:155-166: ``if (wpn == 3 || wpn == 5 || wpn == 9 ||
    wpn == 13 ...) { dir = MonsterLinedUp(...); ... AddMacro(dir);
    AddMacro('A');`` -- the nearest lined-up monster (Manhattan, first slot
    on ties), any range."""
    arena = _melee(asset_mgr, hp=2550, monsters=((5, 0), (9, 5)))  # N at 5, E at 4
    arena.party.members[0].weapon = weapon
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.ATTACK and action.direction == Direction.EAST
    arena = _melee(asset_mgr, hp=2550, monsters=((1, 5), (9, 5)))  # tie at 4: slot 0
    arena.party.members[0].weapon = weapon
    assert choose_auto_combat_action(arena, 0).direction == Direction.WEST


def test_autocombat_missile_shoots_adjacent_nearest(asset_mgr):
    """MonsterLinedUp takes distance 1 too; the nearest wins over a monster
    the port's old N, S, E, W scan found first."""
    arena = _melee(asset_mgr, hp=2550, monsters=((5, 1), (6, 5)))  # N at 4, E at 1
    arena.party.members[0].weapon = WeaponType.BOW
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.ATTACK and action.direction == Direction.EAST


def test_autocombat_never_throws_a_dagger(asset_mgr):
    """UltimaAutocombat.c:155: weapon 1 (dagger) is not a projectile weapon
    for auto-combat, so the hand-to-hand branch runs: it closes in, never
    throws, spares or not."""
    arena = _melee(asset_mgr, hp=2550, monsters=((5, 1),))
    m = arena.party.members[0]
    m.weapon = WeaponType.DAGGER
    m.weapons = {WeaponType.DAGGER: 5}
    arena.asset_mgr = asset_mgr
    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE and action.direction == Direction.NORTH
