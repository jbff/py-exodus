"""Tests for vehicle lifecycle (ships, horses, boarding, disembarking) and naval cannons."""
import pytest
import pygame
from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.combat.arena import CombatArena


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def sample_party():
    c1 = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)
    party = Party([PartyMember(c1)], x=10, y=10, gold=500, transport=Transport.FOOT)
    return party


def test_pirate_victory_drops_frigate_not_chest(asset_mgr, sample_party):
    """Defeating pirate ship leaves behind a boardable frigate, not a chest."""
    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)
    cmap = loader.load_conflict_map(41)

    arena = CombatArena(
        party=sample_party,
        combat_map=cmap,
        creature_tile="pirate",
        asset_mgr=asset_mgr,
        monster_count=1,
    )

    # Trigger victory
    arena.monsters[0].hp = 0
    arena._handle_victory()

    assert arena.is_finished
    assert arena.is_victory
    assert not arena.chest_spawned
    # Frigate should be placed in party dynamic_objects
    frigates = [obj for obj in sample_party.dynamic_objects if obj.get("tile") == "frigate"]
    chests = [obj for obj in sample_party.dynamic_objects if obj.get("tile") == "chest"]
    assert len(frigates) == 1
    assert len(chests) == 0


def test_board_and_exit_frigate(asset_mgr, sample_party):
    """Boarding a frigate sets transport to SHIP with full hull; exiting drops frigate and sets FOOT."""
    overworld = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, start_x=10, start_y=10)

    # Place frigate exactly on the party tile at (10, 10) — boarding requires
    # the exact tile (Java GameScreen.java:952, board(x, y) with cx == x && cy == y).
    sample_party.dynamic_objects.append({"tile": "frigate", "x": 10, "y": 10})

    # Press 'B' to board
    overworld.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b, unicode="b"))
    assert sample_party.transport == Transport.SHIP
    assert sample_party.ship_hull == 50
    assert len([o for o in sample_party.dynamic_objects if o.get("tile") == "frigate"]) == 0
    assert any("Board Frigate" in m for m in overworld.text_log.history)

    # Press 'X' to exit transport
    overworld.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x"))
    assert sample_party.transport == Transport.FOOT
    assert len([o for o in sample_party.dynamic_objects if o.get("tile") == "frigate"]) == 1
    assert any("Disembarked" in m for m in overworld.text_log.history)


def test_board_and_exit_horse(asset_mgr, sample_party):
    """Mounting a horse sets transport to HORSE; exiting leaves horse behind."""
    overworld = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, start_x=10, start_y=10)

    sample_party.dynamic_objects.append({"tile": "horse", "x": 10, "y": 10})

    # Press 'B'
    overworld.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b, unicode="b"))
    assert sample_party.transport == Transport.HORSE
    assert len([o for o in sample_party.dynamic_objects if o.get("tile") == "horse"]) == 0

    # Press 'X'
    overworld.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x"))
    assert sample_party.transport == Transport.FOOT
    assert len([o for o in sample_party.dynamic_objects if o.get("tile") == "horse"]) == 1


def test_ship_broadside_cannons_restrictions_and_hits(asset_mgr, sample_party):
    """Firing cannons is broadsides only; hits sea creatures in range."""
    sample_party.transport = Transport.SHIP
    overworld = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, start_x=10, start_y=10)
    overworld.heading = Direction.NORTH

    # When facing NORTH, firing NORTH is invalid (broadsides only)
    overworld._fire_cannons(Direction.NORTH)
    assert any("Broadsides only" in m for m in overworld.text_log.history)

    # Place a sea serpent 2 tiles EAST at (12, 10)
    overworld.creatures = [{"tile_name": "serpent", "x": 12, "y": 10, "hp": 40}]

    # When facing NORTH, firing EAST is a valid broadside
    overworld._fire_cannons(Direction.EAST)
    assert any("BOOM" in m for m in overworld.text_log.history)
    assert any("Direct hit" in m for m in overworld.text_log.history)

