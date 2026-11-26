"""Tab/F2 auto-combat carries into the next fight, as the sidebar shows.

CombatScreen defined on_enter twice; the second hid the first, so the
remembered StateMachine.auto_combat_enabled never reached a new fight.
Full Autoplay fights its own way and does not switch auto-combat on.
"""
import pytest

from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.state_machine import StateMachine
from py_exodus.world.loader import MapLoader


@pytest.fixture
def conflict_map(asset_mgr):
    return MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT")


def _combat(asset_mgr, conflict_map):
    from py_exodus.screens.combat_screen import CombatScreen

    party = Party([PartyMember(Character("A", "M", Race.HUMAN, Profession.FIGHTER))])
    return CombatScreen(party=party, combat_map=conflict_map, creature_tile="orc", asset_mgr=asset_mgr)


def test_remembered_auto_combat_starts_the_next_fight_on(asset_mgr, conflict_map, pygame_setup):
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.auto_combat_enabled = True
    screen = _combat(asset_mgr, conflict_map)
    sm.push_screen(screen)
    assert screen.auto_combat is True


def test_autoplay_alone_leaves_auto_combat_off(asset_mgr, conflict_map, pygame_setup):
    sm = StateMachine(asset_mgr=asset_mgr)
    sm.autoplay_enabled = True
    screen = _combat(asset_mgr, conflict_map)
    sm.push_screen(screen)
    assert screen.auto_combat is False
