"""Town and castle rests start under 70% of max HP (user ruling 2026-11-25).

Lord British raises max HP by 100 a level and heals nothing (LairWare
Transact, UltimaMain.c:2373-2380). With the old 85% line a level-up alone
sent the party into a rest beside him: about 30 visits and 2,100 still steps
in the user's trace_20261125-184644.
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.autoplay import batch
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import Profession
from py_exodus.screens.town import TownScreen
from py_exodus.state_machine import StateMachine


@pytest.fixture(scope="module")
def am():
    return batch._assets()


def _castle_after_level_up(am, frac_after: float):
    """The canonical party at level 3 with the Mark of Kings, in Castle
    British facing Lord British. The Fighter has the experience for level 4
    and, once raised, holds ``frac_after`` of the new 450 max HP; everyone
    else is whole. Steps the controller until the level-up has happened."""
    party = batch.build_party()
    for m in party.members:
        m.level, m.exp, m.food, m.gold = 3, 250, 300, 100
        m.max_hp = m.hp = 350
        m.marks = [1, 0, 0, 0]
    cleric = next(m for m in party.members if m.profession == Profession.CLERIC)
    cleric.mp = 0  # no heal spell to spend: the decision shows as a rest
    fighter = party.members[1]
    fighter.exp = 350
    fighter.hp = int(450 * frac_after)
    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=1, start_x=32, start_y=15)
    sm.set_screen(ts)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(20):
        ctrl.step(sm)
        if fighter.level == 4 and not ts.text_log.is_waiting_for_input:
            break
    assert fighter.level == 4 and fighter.max_hp == 450
    return ctrl, sm, ts, party


def test_a_level_up_to_75_percent_does_not_rest_beside_lord_british(pygame_setup, am):
    """74.9% after the level-up: the party walks out (it may wait a turn
    for a townsperson in its way, but never rests or casts a heal)."""
    ctrl, sm, ts, party = _castle_after_level_up(am, 0.75)
    for _ in range(15):
        key = ctrl.step(sm)
        why = ctrl._last_why or ""
        assert not (key == pygame.K_SPACE and why.startswith("_step_town:")), why
        assert not (key == pygame.K_c and why.startswith("_step_2d:")), why
        assert why.startswith("_walk_out_of_town:"), why


def test_a_member_at_65_percent_rests_in_castle_british(pygame_setup, am):
    ctrl, sm, ts, party = _castle_after_level_up(am, 0.65)
    assert ctrl.step(sm) == pygame.K_SPACE


def test_a_town_rest_once_started_goes_on_to_85_percent(pygame_setup, am):
    """Started under 70%, the rest carries on to the old 85% line for the
    visit, so the party doesn't walk out at 70% and straight back in."""
    ctrl, sm, ts, party = _castle_after_level_up(am, 0.65)
    assert ctrl.step(sm) == pygame.K_SPACE
    party.members[1].hp = int(450 * 0.80)
    assert ctrl.step(sm) == pygame.K_SPACE
    party.members[1].hp = int(450 * 0.86)
    assert ctrl.step(sm) != pygame.K_SPACE
