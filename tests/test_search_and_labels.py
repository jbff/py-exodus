"""Town chest looting. (The Java S Search of map labels was removed: S is
Steal in LairWare, UltimaMain.c:1186; ledger C-23.)"""
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
        PartyMember(Character("Wizard", "M", Race.BOBBIT, Profession.WIZARD, hp=100)),
        PartyMember(Character("Thief", "M", Race.FUZZY, Profession.THIEF, hp=100)),
    ]
    return Party(members, x=79, y=176, gold=500, transport=Transport.FOOT)


def test_town_get_chest_party_tile_only(asset_mgr, party_four, monkeypatch):
    """Fix round 2 (final): G opens the chest at the PARTY'S OWN TILE only
    (SIP x/y is the unshifted per-event copy; arrows never reach getChest) —
    an adjacent chest is "Not Here!" (no adjacency scan), a chest tile under
    the party loots and converts to floor."""
    town = TownScreen(party=party_four, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)

    # A chest tile one tile WEST: not looted ("Not Here!")
    chest_tile = asset_mgr.get_tile_by_name("chest") or asset_mgr.get_tile_by_index(64)
    assert chest_tile is not None
    town.game_map.set_tile(9, 10, chest_tile)

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, unicode="g"))
    assert town.text_log.is_waiting_for_input
    town.text_log.handle_char("1")
    town.text_log.handle_enter()

    assert any(m == "Not Here!" for m in town.text_log.history)
    assert town.game_map.get_tile(9, 10).name == "chest"

    # A chest tile directly under the party loots
    town.game_map.set_tile(10, 10, chest_tile)
    # No trap: a sprung Bomb pays no booty (LW), which made this flaky.
    from py_exodus.world import chests

    monkeypatch.setattr(chests, "_chest_trap", lambda party, member: ([], False))
    opening_member = party_four.members[0]
    member_gold_before = opening_member.gold
    party_gold_before = party_four.gold

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, unicode="g"))
    assert town.text_log.is_waiting_for_input
    town.text_log.handle_char("1")
    town.text_log.handle_enter()

    # Chest gold is credited to the opening member, not the party pool
    opening_gold_delta = opening_member.gold - member_gold_before
    assert 30 <= opening_gold_delta <= 100  # LW GetChestBooty
    assert party_four.gold == party_gold_before + opening_gold_delta  # gold is per member (Task 4)
    assert town.game_map.get_tile(10, 10).name != "chest"
    assert opening_member.gold <= 9999
    assert any("The Chest Holds: " in msg for msg in town.text_log.history)
