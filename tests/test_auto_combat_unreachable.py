"""Fights where no monster can be reached (user-approved brief 2026-11-25).

The user's trace_20261125-184644: a ship fight from step 76,564, five
Man-O-Wars (squids) at Sosaria (31, 5), lasted about 3,200 autoplay steps.
A squid sat in the water beside the hull at (7, 8), the deck edge (7, 7) a
wall; the Exotic-armed melee members could not reach it and passed, and the
Wizard never lined up its Mittar. LW Shoot (UltimaSpellCombat.c:708-731)
has no terrain test: missiles and Mittar fly over walls and the rail.
"""
from __future__ import annotations

import random

import pytest

from py_exodus.autoplay.batch import _assets
from py_exodus.combat.arena import ActionType
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.constants import Spell, Transport
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from tests.test_autoplay_trip import _all_cards_party

THIEF, FIGHTER, CLERIC, WIZARD = range(4)


@pytest.fixture(scope="module")
def am():
    return _assets()


def _squid_fight(am, seed: int):
    """The trace's state at combat_start: the canonical party, level 25,
    Exotics, at sea at Sosaria (31, 5), HP and MP as the trace had them."""
    random.seed(seed)
    party = _all_cards_party(keys=8, gold=5000)
    for m, hp, mp in zip(party.members, (2138, 1997, 1818, 2078), (0, 0, 8, 25)):
        m.max_hp, m.hp, m.mp, m.food = 2550, hp, mp, 211
    party.x, party.y = 31, 5
    party.transport = Transport.SHIP
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(
        party=party, map_id=0, asset_mgr=am, start_x=31, start_y=5, random_encounters=False
    )
    sm.set_screen(ow)
    ow.creatures = []
    ow._trigger_combat("squid", {"tile_name": "squid", "tile": "squid", "x": 31, "y": 4})
    cs = sm.current_screen
    assert type(cs).__name__ == "CombatScreen" and cs.arena.ship_battle
    return sm, cs, party


def _one_squid_by_the_hull(arena, members_at: dict[int, tuple[int, int]]):
    """One Man-O-War left, in the water at (7, 8) under the deck edge (7, 7)."""
    squid = arena.monsters[0]
    arena.monsters = [squid]
    squid.x, squid.y = 7, 8
    assert arena.combat_map.get_tile(7, 7).name == "wall"
    for i in list(arena.player_positions):
        if i not in members_at:
            arena.player_positions.pop(i)
    arena.player_positions.update(members_at)
    return squid


def test_the_wizard_walks_to_line_up_mittar_on_a_squid_by_the_hull(pygame_setup, am):
    """Item A: from (3, 5) the old moves paced (3, 6) <-> (3, 7) at the
    rail for ever; now the Wizard walks to a deck square on the squid's
    column and casts."""
    sm, cs, party = _squid_fight(am, 3)
    arena = cs.arena
    _one_squid_by_the_hull(arena, {WIZARD: (3, 5)})
    party.members[WIZARD].mp = 25
    for _ in range(10):
        action = choose_auto_combat_action(arena, WIZARD)
        if action.type == ActionType.CAST:
            break
        assert action.type == ActionType.MOVE
        x, y = arena.player_positions[WIZARD]
        arena.player_positions[WIZARD] = (x + action.direction.dx, y + action.direction.dy)
    assert action.type == ActionType.CAST
    assert action.spell in (Spell.MITTAR, Spell.FULGAR)
    assert arena.player_positions[WIZARD][0] == 7


def test_the_line_up_square_avoids_a_monster_where_it_can(pygame_setup, am):
    """Item A: of the squares that line up a shot, one no monster stands
    next to wins over a nearer one beside a monster."""
    from py_exodus.combat.auto_combat import _line_up_step

    sm, cs, party = _squid_fight(am, 3)
    arena = cs.arena
    squid = _one_squid_by_the_hull(arena, {WIZARD: (6, 6)})
    # A second squid in the water east of the hull, at (9, 7). South, (6, 7)
    # lines it up but is next to the squid at (7, 8); east, (7, 6) lines up
    # the squid at (7, 8) and no monster stands next to it.
    arena.monsters.append(squid.__class__(squid.definition, 9, 7))
    d = _line_up_step(arena, WIZARD, 6, 6, arena.monsters)
    assert (6 + d.dx, 6 + d.dy) == (7, 6)


def test_no_line_up_square_keeps_the_old_moves(pygame_setup, am):
    """Item A: with no square that lines up a shot, no new move (never pace)."""
    from py_exodus.combat.auto_combat import _line_up_step

    sm, cs, party = _squid_fight(am, 3)
    arena = cs.arena
    squid = _one_squid_by_the_hull(arena, {WIZARD: (3, 5)})
    squid.x, squid.y = 0, 1  # open water, no deck square on its row or column
    assert _line_up_step(arena, WIZARD, 3, 5, arena.monsters) is None
