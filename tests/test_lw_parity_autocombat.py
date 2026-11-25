"""LairWare parity, batch A (auto-combat): pins LairWare AutoCombat rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "A - Auto-combat".
"""
from __future__ import annotations

from py_exodus.combat.arena import ActionType, CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
import pytest

from py_exodus.constants import Direction, Profession, Race, Spell, Transport, WeaponType
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
