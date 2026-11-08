"""Tests for map label searching (exotic items, cards) and town chest looting."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import ArmorType, Direction, Profession, Race, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.defs import LabelDef
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.town import TownScreen
from py_exodus.world.loader import MapLoader


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def party_four():
    members = [
        PartyMember(Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER, hp=100)),
        PartyMember(Character("Cleric", "M", Race.HUMAN, Profession.CLERIC, hp=100)),
        PartyMember(Character("Wizard", "M", Race.BOBIT, Profession.WIZARD, hp=100)),
        PartyMember(Character("Thief", "M", Race.FUZZY, Profession.THIEF, hp=100)),
    ]
    return Party(members, x=79, y=176, gold=500, transport=Transport.FOOT)


def test_search_exotic_armor(asset_mgr, party_four):
    """Searching at (79, 176) awards Exotic Armor and 100 XP to the searching member."""
    party_four.x = 79
    party_four.y = 176
    ow = OverworldScreen(party=party_four, map_id=0, asset_mgr=asset_mgr, start_x=79, start_y=176)

    m1 = party_four.members[0]
    initial_xp = m1.exp
    initial_armor_count = m1.armors.get(ArmorType.EXOTIC, 0)

    # Press 'S' to search
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    assert ow.text_log.is_waiting_for_input

    # Select member 1
    ow.text_log.handle_char("1")
    ow.text_log.handle_enter()

    assert m1.armors.get(ArmorType.EXOTIC, 0) == initial_armor_count + 1
    assert m1.exp == initial_xp + 100
    assert any("Exotic" in msg for msg in ow.text_log.history)


def test_search_exotic_weapon(asset_mgr, party_four):
    """Searching at (134, 14) awards Exotic Weapon and 100 XP to the searching member."""
    party_four.x = 134
    party_four.y = 14
    ow = OverworldScreen(party=party_four, map_id=0, asset_mgr=asset_mgr, start_x=134, start_y=14)

    m2 = party_four.members[1]
    initial_xp = m2.exp
    initial_weapon_count = m2.weapons.get(WeaponType.EXOTIC, 0)

    # Press 'S' and select member 2
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    ow.text_log.handle_char("2")
    ow.text_log.handle_enter()

    assert m2.weapons.get(WeaponType.EXOTIC, 0) == initial_weapon_count + 1
    assert m2.exp == initial_xp + 100
    assert any("Exotic" in msg for msg in ow.text_log.history)


def test_search_card_of_death(asset_mgr, party_four):
    """Searching at Ambrosia Card of Death (55, 27) awards the card and 100 XP."""
    party_four.x = 55
    party_four.y = 27
    # Ambrosia is map_id 13
    ow = OverworldScreen(party=party_four, map_id=13, asset_mgr=asset_mgr, start_x=55, start_y=27)

    m3 = party_four.members[2]
    initial_xp = m3.exp
    assert m3.cards[0] == 0

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    ow.text_log.handle_char("3")
    ow.text_log.handle_enter()

    assert m3.cards[0] == 1
    assert m3.exp == initial_xp + 100
    assert any("Death" in msg for msg in ow.text_log.history)


def test_town_get_chest_adjacent(asset_mgr, party_four):
    """Pressing 'G' in town adjacent to a chest loots it and converts tile to floor."""
    town = TownScreen(party=party_four, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)

    # Place a chest tile east at (11, 10)
    chest_tile = asset_mgr.get_tile_by_name("chest") or asset_mgr.get_tile_by_index(64)
    assert chest_tile is not None
    town.game_map.set_tile(11, 10, chest_tile)

    opening_member = party_four.members[0]
    member_gold_before = opening_member.gold
    party_gold_before = party_four.gold

    # Press 'G' to get chest
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, unicode="g"))
    assert town.text_log.is_waiting_for_input
    town.text_log.handle_char("1")
    town.text_log.handle_enter()

    # Chest gold is credited to the opening member, not the party pool
    opening_gold_delta = opening_member.gold - member_gold_before
    assert 10 <= opening_gold_delta <= 66
    assert party_four.gold == party_gold_before + opening_gold_delta  # gold is per member (Task 4)
    assert town.game_map.get_tile(11, 10).name != "chest"
    assert opening_member.gold <= 9999
    assert any("The Chest Holds: " in msg for msg in town.text_log.history)
