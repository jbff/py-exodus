"""Tests for dungeon hazards, marks branding, fountain effects, and traps."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def party():
    c1 = Character("Warrior", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100, torches=5)
    c2 = Character("Cleric", "M", Race.HUMAN, Profession.CLERIC, hp=100, max_hp=100)
    return Party([PartyMember(c1), PartyMember(c2)], x=1, y=1, gold=500, food=100)


@pytest.fixture
def test_dmap():
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = [[[DungeonTile.FLOOR for _ in range(16)] for _ in range(16)] for _ in range(8)]
    dmap.tiles = tiles
    return dmap


def test_dungeon_touch_mark_kings(asset_mgr, party, test_dmap):
    """Touching Mark of Kings gives mark, deals 50 branding damage."""
    test_dmap.set_tile(1, 1, 0, DungeonTile.MARK_KINGS)
    state = DungeonState(test_dmap, start_x=1, start_y=1, start_z=0, party=party)
    screen = DungeonScreen(party=party, map_id=14, asset_mgr=asset_mgr)
    screen.state = state

    m1 = party.members[0]
    initial_hp = m1.hp
    assert m1.marks[0] == 0

    # Press 'S' to search / touch
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    assert screen.text_log.is_waiting_for_input
    # Choose member 1
    screen.text_log.handle_char("1")

    assert m1.marks[0] == 1
    assert m1.hp == initial_hp - 50
    assert any("Mark of Kings" in msg for msg in screen.text_log.history)


def test_dungeon_drink_fountain_heal(asset_mgr, party, test_dmap):
    """Drinking from a Healing fountain restores full HP."""
    test_dmap.set_tile(1, 1, 0, DungeonTile.FOUNTAIN_HEAL)
    state = DungeonState(test_dmap, start_x=1, start_y=1, start_z=0, party=party)
    screen = DungeonScreen(party=party, map_id=14, asset_mgr=asset_mgr)
    screen.state = state

    m1 = party.members[0]
    m1.hp = 20

    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    screen.text_log.handle_char("1")

    assert m1.hp == m1.max_hp
    assert any("Refreshing" in msg or "healed" in msg.lower() for msg in screen.text_log.history)


def test_dungeon_drink_fountain_acid(asset_mgr, party, test_dmap):
    """Drinking from an Acid fountain deals 25 damage."""
    test_dmap.set_tile(1, 1, 0, DungeonTile.FOUNTAIN_ACID)
    state = DungeonState(test_dmap, start_x=1, start_y=1, start_z=0, party=party)
    screen = DungeonScreen(party=party, map_id=14, asset_mgr=asset_mgr)
    screen.state = state

    m1 = party.members[0]
    initial_hp = m1.hp

    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    screen.text_log.handle_char("1")

    assert m1.hp == initial_hp - 25
    assert any("Nasty" in msg or "Acid" in msg or "damage" in msg.lower() for msg in screen.text_log.history)


def test_dungeon_drink_fountain_poison_and_cure(asset_mgr, party, test_dmap):
    """Drinking Poison fountain poisons; drinking Cure fountain cures."""
    test_dmap.set_tile(1, 1, 0, DungeonTile.FOUNTAIN_POISON)
    state = DungeonState(test_dmap, start_x=1, start_y=1, start_z=0, party=party)
    screen = DungeonScreen(party=party, map_id=14, asset_mgr=asset_mgr)
    screen.state = state

    m1 = party.members[0]
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    screen.text_log.handle_char("1")

    assert m1.status in (Status.POISON, Status.POISONED)

    # Now change tile to Cure fountain
    test_dmap.set_tile(1, 1, 0, DungeonTile.FOUNTAIN_CURE)
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    screen.text_log.handle_char("1")

    assert m1.status == Status.GOOD


def test_dungeon_hazard_wind_trap_and_gremlins(asset_mgr, party, test_dmap):
    """Stepping into wind trap turns off torch; gremlins take 2 food per member."""
    test_dmap.set_tile(1, 2, 0, DungeonTile.WIND_TRAP)
    test_dmap.set_tile(1, 3, 0, DungeonTile.GREMLINS)
    state = DungeonState(test_dmap, start_x=1, start_y=1, start_z=0, start_dir=Direction.SOUTH, party=party)
    state.is_torch_on = True

    # Step forward onto (1, 2) WIND_TRAP — Java DungeonScreen.java:1080-1085
    # sets the torch boolean off (no torchduration bookkeeping in Java).
    evt1 = state.move_forward()
    assert evt1.type == DungeonEventType.WIND_TRAP
    assert state.is_torch_on is False
    assert not hasattr(state, "torch_rounds")

    # Java Party.applyEffect (Party.java:279-283, 347-352): food -2 per
    # non-DEAD member, floored at 0 — there is no party-sum halving.
    foods_before = [m.food for m in party.members]

    # Step forward onto (1, 3) GREMLINS
    evt2 = state.move_forward()
    assert evt2.type == DungeonEventType.GREMLINS
    for i, m in enumerate(party.members):
        assert m.food == max(0, foods_before[i] - 2)
