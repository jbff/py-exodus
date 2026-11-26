"""The sidebar location in combat names the map the fight started on.

The combat screen has no map of its own; it used to fall back to
``party.map_id`` (0 on Ambrosia), so a fight on Ambrosia read "Sosaria".
"""
import pytest

from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.world.loader import MapLoader


@pytest.fixture
def conflict_map(asset_mgr):
    return MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT")


class _Parent:
    """Stand-in for the screen the fight was raised from."""

    def __init__(self, map_id, **attrs):
        self.map_id = map_id
        for k, v in attrs.items():
            setattr(self, k, v)


def _location(screen, monkeypatch):
    import pygame

    seen = {}
    monkeypatch.setattr(
        screen.stats_panel, "render",
        lambda *a, **kw: seen.update(kw),
    )
    screen._render_stats_panel(pygame.Surface((200, 200)), pygame.Rect(0, 0, 200, 200))
    return seen["location_text"]


def _combat(asset_mgr, conflict_map, parent):
    from py_exodus.screens.combat_screen import CombatScreen

    party = Party([PartyMember(Character("A", "M", Race.HUMAN, Profession.FIGHTER))])
    party.map_id = 0
    party.x, party.y = 20, 30
    return CombatScreen(party=party, combat_map=conflict_map, creature_tile="orc",
                        asset_mgr=asset_mgr, return_screen=parent)


def test_combat_on_ambrosia_names_ambrosia(asset_mgr, conflict_map, pygame_setup, monkeypatch):
    screen = _combat(asset_mgr, conflict_map, _Parent(13))
    assert _location(screen, monkeypatch) == "Ambrosia (20,30)"


def test_combat_in_town_names_town_and_avatar_tile(asset_mgr, conflict_map, pygame_setup, monkeypatch):
    screen = _combat(asset_mgr, conflict_map, _Parent(12, avatar_x=5, avatar_y=7))
    assert _location(screen, monkeypatch) == "Fawn (5,7)"


def test_combat_without_parent_keeps_party_map(asset_mgr, conflict_map, pygame_setup, monkeypatch):
    screen = _combat(asset_mgr, conflict_map, None)
    assert _location(screen, monkeypatch) == "Sosaria (20,30)"
