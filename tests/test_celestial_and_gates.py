"""Tests for moon phases, Dawn double-new-moon conjunction, moongates, and Ambrosia whirlpool."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.overworld import OverworldScreen


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def party():
    members = [
        PartyMember(Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER, hp=100)),
    ]
    return Party(members, x=37, y=53, gold=500, transport=Transport.FOOT)


def test_dawn_portal_conjunction_restriction(asset_mgr, party):
    """Entering Dawn (dest_map_id 11) is permitted only during double new moon (0, 0)."""
    # Dawn portal on Sosaria is at (37, 53)
    party.x = 37
    party.y = 53
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=37, start_y=53)

    # When moons are NOT (0, 0), e.g. moon_phase = 10 (Trammel 3, Felucca 2)
    ow.moon_phase = 10
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))
    assert not ow.is_finished
    assert any("Dawn" in msg for msg in ow.text_log.history)

    # When moons ARE (0, 0), e.g. moon_phase = 0
    ow.moon_phase = 0
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))
    # Portal transition occurs
    assert ow.is_finished or ow.next_screen is not None


def test_moongate_destination_routing_by_felucca(asset_mgr, party):
    """Active moongate teleports party to destination determined by Felucca phase."""
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=7, start_y=8)

    # Gate 0 is at (7, 8) with phase 0, d1=0, d2=1, d3=2
    # At moon_phase = 1: Trammel is 0 (gate 0 active), Felucca is 1 (dest is gate 1)
    ow.moon_phase = 1
    party.x = 7
    party.y = 8

    ow._check_moongates()

    # Destination should be gate 1 at (57, 46)
    assert party.x == 57
    assert party.y == 46
    assert any("moongate" in msg.lower() for msg in ow.text_log.history)


def test_ambrosia_whirlpool_routes_to_sosaria_coast(asset_mgr, party):
    """Entering the whirlpool in Ambrosia transports party to Sosaria coast (x=48..53, y=0..8)."""
    # Ambrosia map 13, whirlpool portal is at (32, 58)
    party.x = 32
    party.y = 58
    ow = OverworldScreen(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=58)

    # Press 'E' to enter portal
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))

    # Party should be in Sosaria (map_id 0) at coast
    assert 48 <= party.x <= 53
    assert 0 <= party.y <= 8
