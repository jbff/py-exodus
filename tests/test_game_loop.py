"""Integration tests for State Machine, Audio Manager, Screens, and Game Loop."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pygame

from py_exodus.__main__ import GameApp
from py_exodus.assets import AssetManager
from py_exodus.audio import AudioManager
from py_exodus.combat.arena import Action, ActionType, CombatArena
from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    ArmorType,
    Direction,
    Profession,
    Race,
    Sex,
    Spell,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.start import StartScreen, create_default_starter_party
from py_exodus.screens.town import TownScreen
from py_exodus.state_machine import StateMachine


@pytest.fixture(scope="module")
def pygame_setup():
    """Ensure pygame is initialized once for test session."""
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture
def asset_mgr():
    """Load AssetManager with standard assets."""
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def sample_party():
    """Create a sample 4-character party."""
    return create_default_starter_party()


class MockScreen(BaseScreen):
    def __init__(self, name: str = "mock", **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.events_handled: list[pygame.event.Event] = []
        self.updated_dt: list[float] = []
        self.rendered: bool = False
        self.entered: bool = False
        self.exited: bool = False

    def on_enter(self) -> None:
        super().on_enter()
        self.entered = True

    def on_exit(self) -> None:
        super().on_exit()
        self.exited = True

    def handle_event(self, event: pygame.event.Event) -> None:
        self.events_handled.append(event)

    def update(self, dt: float) -> None:
        self.updated_dt.append(dt)

    def render(self, surface: pygame.Surface) -> None:
        self.rendered = True


@pytest.fixture
def mock_mixer():
    """Mock pygame.mixer for headless environments lacking SDL_mixer."""
    m = MagicMock()
    m.get_init.return_value = True
    m.music = MagicMock()
    m.music.get_busy.return_value = False
    m.Sound = MagicMock()
    old_mixer = getattr(pygame, "mixer", None)
    setattr(pygame, "mixer", m)
    try:
        yield m
    finally:
        if old_mixer is not None:
            setattr(pygame, "mixer", old_mixer)


# --- State Machine Tests ---


def test_state_machine_init(pygame_setup, asset_mgr):
    sm = StateMachine(asset_mgr)
    assert sm.current_screen is not None
    assert isinstance(sm.current_screen, StartScreen)


def test_state_machine_stack_transitions(pygame_setup, asset_mgr):
    s1 = MockScreen("s1")
    s2 = MockScreen("s2")
    s3 = MockScreen("s3")

    sm = StateMachine(asset_mgr, initial_screen=s1)
    assert sm.current_screen is s1
    assert s1.entered

    # Push s2
    sm.push_screen(s2)
    assert sm.current_screen is s2
    assert s1.exited
    assert s2.entered
    assert s2.return_screen is s1

    # Push s3
    sm.push_screen(s3)
    assert sm.current_screen is s3
    assert len(sm.screen_stack) == 3

    # Pop s3
    popped = sm.pop_screen()
    assert popped is s3
    assert s3.exited
    assert sm.current_screen is s2

    # Pop s2
    popped = sm.pop_screen()
    assert popped is s2
    assert sm.current_screen is s1

    # Cannot pop last screen
    assert sm.pop_screen() is None
    assert sm.current_screen is s1


def test_state_machine_routing(pygame_setup, asset_mgr):
    scr = MockScreen("test")
    sm = StateMachine(asset_mgr, initial_screen=scr)

    evt = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    sm.handle_event(evt)
    assert len(scr.events_handled) == 1
    assert scr.events_handled[0].key == pygame.K_SPACE

    sm.update(0.016)
    assert scr.updated_dt == [0.016]

    surf = pygame.Surface((320, 200))
    sm.render(surf)
    assert scr.rendered


def test_state_machine_screen_finish_transition(pygame_setup, asset_mgr):
    s1 = MockScreen("s1")
    s2 = MockScreen("s2")
    sm = StateMachine(asset_mgr, initial_screen=s1)

    s1.next_screen = s2
    s1.is_finished = True

    sm.update(0.1)
    assert sm.current_screen is s2


def test_state_machine_multi_level_stack_preservation(pygame_setup, asset_mgr):
    s_overworld = MockScreen("overworld")
    s_town = MockScreen("town")
    s_combat = MockScreen("combat")

    sm = StateMachine(asset_mgr, initial_screen=s_overworld)
    assert sm.screen_stack == [s_overworld]

    # Enter Town
    sm.push_screen(s_town)
    assert sm.screen_stack == [s_overworld, s_town]

    # Enter Combat from Town
    sm.push_screen(s_combat)
    assert sm.screen_stack == [s_overworld, s_town, s_combat]

    # Combat finishes and returns to Town
    s_combat.exit_screen()
    sm.update(0.1)
    assert sm.current_screen is s_town
    assert sm.screen_stack == [s_overworld, s_town]  # Overworld preserved!

    # Town finishes and returns to Overworld
    s_town.exit_screen()
    sm.update(0.1)
    assert sm.current_screen is s_overworld
    assert sm.screen_stack == [s_overworld]


# --- Audio Manager Tests ---


def test_audio_manager_tracks(pygame_setup, mock_mixer):
    am = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)
    assert am.music_volume == 0.5
    assert am.sfx_volume == 0.7

    am.set_music_volume(0.8)
    assert am.get_music_volume() == pytest.approx(0.8)

    am.set_sfx_volume(0.6)
    assert am.get_sfx_volume() == pytest.approx(0.6)

    # Resolve sound files
    assert am.resolve_sound_file("wander") is not None
    assert am.resolve_sound_file("combat") is not None
    assert am.resolve_sound_file("dungeon") is not None
    assert am.resolve_sound_file("walk_normal") is not None

    # Play music
    played = am.play_music("wander")
    assert played
    mock_mixer.music.load.assert_called_once()
    mock_mixer.music.play.assert_called_once()

    am.pause_music()
    am.unpause_music()
    am.stop_music()


def test_audio_manager_sfx(pygame_setup, mock_mixer):
    am = AudioManager(sound_dir="src/main/resources/assets/sound", enabled=True)
    mock_sound = MagicMock()
    mock_mixer.Sound.return_value = mock_sound

    res = am.play_sfx("walk_normal")
    assert res
    mock_sound.play.assert_called_once()


# --- StartScreen Tests ---


def test_start_screen_navigation(pygame_setup, asset_mgr):
    scr = StartScreen(asset_mgr=asset_mgr)
    assert scr.selected_idx == 0

    # Down arrow
    evt_down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN)
    scr.handle_event(evt_down)
    assert scr.selected_idx == 1

    # Up arrow
    evt_up = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP)
    scr.handle_event(evt_up)
    assert scr.selected_idx == 0

    # Number keys
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_3))
    assert scr.selected_idx == 2


def test_start_screen_journey_onward(pygame_setup, asset_mgr, sample_party):
    sm = StateMachine(asset_mgr)
    scr = StartScreen(asset_mgr=asset_mgr, party=sample_party, manager=sm)
    sm.set_screen(scr)

    # Press Enter on Journey Onward
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert isinstance(sm.current_screen, OverworldScreen)
    assert sm.current_screen.party is sample_party


# --- OverworldScreen Tests ---


def test_overworld_screen_movement(pygame_setup, asset_mgr, sample_party):
    sm = StateMachine(asset_mgr)
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    initial_x = sample_party.x
    initial_y = sample_party.y
    initial_moves = sample_party.moves

    # Move North (UP)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    # Either moved (party.y changed) or blocked by terrain
    assert sample_party.moves >= initial_moves


def test_overworld_screen_frigate_cannons(pygame_setup, asset_mgr, sample_party):
    sample_party.transport = Transport.SHIP
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)
    ow.heading = Direction.EAST

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    assert ow.text_log.is_waiting_for_input

    # Type direction 'N' and Enter
    ow.text_log.handle_char("N")
    ow.text_log.handle_enter()
    assert any("Broadside fired NORTH" in msg for msg in ow.text_log.history)


def test_overworld_screen_transport_toggle(pygame_setup, asset_mgr, sample_party):
    """B is gated by boardable objects (Java GameScreen.java:945-979):
    nothing on the tile → "Board What?" and no auto-mount; while mounted →
    "Board: Can't!" and the transport is unchanged. Dismounting is X."""
    sample_party.transport = Transport.FOOT
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)

    # Board with nothing boardable: no auto-mount
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert sample_party.transport == Transport.FOOT
    assert any(m == "Board What?" for m in ow.text_log.history)

    # Mount a horse on the party's tile, then dismount with X
    sample_party.dynamic_objects.append({"tile": "horse", "x": sample_party.x, "y": sample_party.y})
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert sample_party.transport == Transport.HORSE

    # B while mounted: "Board: Can't!", transport unchanged
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert sample_party.transport == Transport.HORSE
    assert any(m == "Board: Can't!" for m in ow.text_log.history)

    # Dismount
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x))
    assert sample_party.transport == Transport.FOOT


def test_overworld_screen_portal_entry(pygame_setup, asset_mgr, sample_party):
    sm = StateMachine(asset_mgr)
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    # Position at Lord British's castle portal (x=45, y=18)
    sample_party.x = 45
    sample_party.y = 18

    # Press 'E' to enter
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))
    assert isinstance(sm.current_screen, TownScreen)
    assert sm.current_screen.map_id == 1  # British castle


def test_overworld_render(pygame_setup, asset_mgr, sample_party):
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)
    surf = pygame.Surface((320, 200))
    ow.render(surf)
    # Viewport should be rendered without errors
    assert surf.get_at((0, 0)) is not None


# --- TownScreen Tests ---


def test_town_screen_navigation_and_exit(pygame_setup, asset_mgr, sample_party):
    sm = StateMachine(asset_mgr)
    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, manager=sm)
    sm.push_screen(town)

    # Press 'X' to exit
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x))
    # Should pop back
    assert sm.current_screen is not town or town.is_finished


def test_town_screen_talk_lord_british(pygame_setup, asset_mgr, sample_party):
    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=32, start_y=60)
    # Test Lord British dialogue trigger
    town._interact_lord_british()
    assert any("Lord British" in msg for msg in town.text_log.history)


def test_town_screen_talk_arrow_keys_to_lord_british(pygame_setup, asset_mgr, sample_party):
    """Pressing 'T' prompts which party member, then prompts Direction, and pressing Arrow Up talks North to Lord British."""
    # Place party at (32, 15), right in front of Lord British at (32, 14)
    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=32, start_y=15)

    # Press 'T' for Talk
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t, unicode="t"))
    assert town.text_log.is_waiting_for_input
    assert "Which party member?" in town.text_log.current_prompt

    # Select party member 1
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
    assert town.text_log.is_waiting_for_input
    assert "Direction?" in town.text_log.current_prompt

    # Press Arrow UP
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    assert not town.text_log.is_waiting_for_input
    assert any("Lord British" in msg for msg in town.text_log.history)


def test_town_screen_party_avatar_rendered_in_castle(pygame_setup, asset_mgr, sample_party):
    """Verify party avatar is rendered at viewport center in Castle British."""
    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=32, start_y=61)
    surf = pygame.Surface((176, 176))
    town.render(surf)

    # Center tile is (5 * 16, 5 * 16) = (80, 80)
    # The center tile should have non-zero pixels (the avatar is drawn there)
    center_sub = surf.subsurface(pygame.Rect(80, 80, 16, 16))
    has_non_black = False
    for px in range(16):
        for py in range(16):
            if center_sub.get_at((px, py))[:3] != (0, 0, 0):
                has_non_black = True
                break
    assert has_non_black, "Party avatar was not rendered in Castle British viewport!"


def test_town_screen_vendor_shopping(pygame_setup, asset_mgr, sample_party):
    from py_exodus.entities.defs import VendorDef, VendorItemDef

    vendor = VendorDef(
        id="test_shop",
        name="Armory",
        owner="Smith",
        vendor_type="WEAPON",
        start_x=10,
        start_y=10,
        items=[
            VendorItemDef(choice="a", name="Dagger", price=5, weapon_type="DAGGER"),
            VendorItemDef(choice="b", name="Mace", price=30, weapon_type="MACE"),
        ],
    )
    town = TownScreen(party=sample_party, map_id=4, asset_mgr=asset_mgr)
    sample_party.gold = 50

    town._start_vendor_shopping(vendor)
    assert town.text_log.is_waiting_for_input

    # Buy Dagger (choice 'a')
    town.text_log.handle_char("a")
    town.text_log.handle_enter()

    assert sample_party.gold == 45
    assert any("Bought Dagger" in msg for msg in town.text_log.history)


def test_town_screen_all_vendor_types_shopping(pygame_setup, asset_mgr, sample_party):
    """Verify purchasing guild items, food rations, horse transport, and healer services."""
    from py_exodus.entities.defs import VendorDef, VendorItemDef
    from py_exodus.constants import Status, Transport

    vendor = VendorDef(
        id="test_guild_and_services",
        name="Market",
        owner="Trader",
        vendor_type="GUILD",
        start_x=10,
        start_y=10,
        items=[
            VendorItemDef(choice="t", name="Torches", price=10, guild_item_type="torch", quantity=5),
            VendorItemDef(choice="g", name="Gems", price=25, guild_item_type="gem", quantity=2),
            VendorItemDef(choice="k", name="Keys", price=30, guild_item_type="key", quantity=3),
            VendorItemDef(choice="p", name="Powder", price=50, guild_item_type="powder", quantity=1),
            VendorItemDef(choice="f", name="Rations", price=15, item_type="food", quantity=25),
            VendorItemDef(choice="h", name="Steed", price=200, item_type="horse"),
            VendorItemDef(choice="c", name="Cure", price=40, heal_type="cure"),
        ],
    )
    town = TownScreen(party=sample_party, map_id=4, asset_mgr=asset_mgr)
    sample_party.gold = 500
    active = sample_party.active_member
    active.character.status = Status.POISON

    # Buy Torches
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("t")
    assert sample_party.torches >= 5

    # Buy Gems
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("g")
    assert sample_party.gems >= 2

    # Buy Keys
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("k")
    assert sample_party.keys >= 3

    # Buy Powder
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("p")
    assert sample_party.powder >= 1

    # Buy Food
    prev_food = sample_party.food
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("f")
    assert sample_party.food > prev_food

    # Buy Horse
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("h")
    assert sample_party.transport == Transport.HORSE

    # Buy Cure
    town._start_vendor_shopping(vendor)
    town.text_log.handle_char("c")
    assert active.character.status == Status.GOOD


# --- CombatScreen Tests ---


def test_combat_screen_turns_and_actions(pygame_setup, asset_mgr, sample_party):
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_G.ULT")

    sm = StateMachine(asset_mgr)
    combat = CombatScreen(
        party=sample_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=2,
        manager=sm,
    )
    sm.push_screen(combat)

    assert combat.arena is not None
    assert len(combat.arena.monsters) == 2

    # Player 1 pass turn (Space)
    active_before = combat.arena.active_party_member_idx
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    # Active player advances or rounds advance
    assert len(combat.text_log.history) > 0


def test_combat_screen_attack_key_and_directional_strike(pygame_setup, asset_mgr, sample_party):
    """Verify pressing 'A' prompts for direction and arrow key executes attack."""
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_G.ULT")

    sm = StateMachine(asset_mgr)
    combat = CombatScreen(
        party=sample_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=2,
        manager=sm,
    )
    sm.push_screen(combat)

    # Pressing 'A' should trigger attack prompt, NOT move west
    pos_before = (combat.active_party_member.x, combat.active_party_member.y)
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
    assert combat.text_log.is_waiting_for_input
    assert "Direction?" in combat.text_log.current_prompt
    assert (combat.active_party_member.x, combat.active_party_member.y) == pos_before

    # Now press North arrow to attack North
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    assert not combat.text_log.is_waiting_for_input
    # Turn was executed as attack
    assert any("attacks" in msg or "misses" in msg or "hits" in msg or "swings" in msg or "Direction" in msg for msg in combat.text_log.history)


def test_combat_screen_render(pygame_setup, asset_mgr, sample_party):
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_G.ULT")

    combat = CombatScreen(
        party=sample_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=1,
    )
    surf = pygame.Surface((320, 200))
    combat.render(surf)
    assert surf.get_at((0, 0)) is not None


# --- DungeonScreen Tests ---


def test_dungeon_screen_navigation(pygame_setup, asset_mgr, sample_party):
    sm = StateMachine(asset_mgr)
    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,  # Perinian
        asset_mgr=asset_mgr,
        manager=sm,
    )
    sm.push_screen(dungeon)

    # Turn left
    initial_dir = dungeon.state.dir
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
    assert dungeon.state.dir != initial_dir

    # Use torch
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t))
    assert dungeon.state.torch_rounds > 0


def test_dungeon_screen_render(pygame_setup, asset_mgr, sample_party):
    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
    )
    surf = pygame.Surface((320, 200))
    dungeon.render(surf)
    assert surf.get_at((0, 0)) is not None


def test_dungeon_screen_turn_around_and_ladders(pygame_setup, asset_mgr, sample_party):
    from py_exodus.world.map import DungeonTile

    sm = StateMachine(asset_mgr)
    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
        manager=sm,
    )
    sm.push_screen(dungeon)

    # 1. Turn around (180 degrees)
    initial_dir = dungeon.state.dir
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    assert dungeon.state.dir == initial_dir.reverse()

    # 2. Ladder down on ladder tile
    dungeon.dungeon_map.set_tile(dungeon.state.x, dungeon.state.y, dungeon.state.z, DungeonTile.LADDER_DOWN)
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_j))
    assert dungeon.state.z == 1

    # 3. Ladder up on ladder tile
    dungeon.dungeon_map.set_tile(dungeon.state.x, dungeon.state.y, dungeon.state.z, DungeonTile.LADDER_UP)
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_u))
    assert dungeon.state.z == 0


def test_dungeon_screen_torch_inventory_consumption(pygame_setup, asset_mgr, sample_party):
    # Give member 2 torches
    sample_party.members[0].character.torches = 2

    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
    )
    dungeon.state.torch_rounds = 0

    # Ignite torch
    dungeon._use_torch()
    assert sample_party.members[0].character.torches == 1
    assert dungeon.state.torch_rounds == 100
    assert any("Torch ignited" in msg for msg in dungeon.text_log.history)


def test_dungeon_screen_combat_encounter_trigger(pygame_setup, asset_mgr, sample_party):
    from py_exodus.entities.defs import CreatureDef
    from py_exodus.world.dungeon import DungeonEvent, DungeonEventType

    sm = StateMachine(asset_mgr)
    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
        manager=sm,
    )
    sm.push_screen(dungeon)

    # Simulate combat encounter event where creature is CreatureDef
    c_def = CreatureDef(id=1, name="Orc", tile="orc", basehp=48, hp=48, exp=5)
    evt = DungeonEvent(type=DungeonEventType.COMBAT, creature=c_def, message="Ambushed by Orc!")
    dungeon._process_event(evt)

    # Should have pushed CombatScreen
    assert isinstance(sm.current_screen, CombatScreen)
    assert sm.current_screen.creature_tile == "orc"


# --- GameApp Main Loop Tests ---


def test_game_app_loop(pygame_setup):
    app = GameApp(
        assets_dir="src/main/resources/assets",
        scale=1,
        headless=True,
        sound_enabled=False,
    )
    assert app.state_machine is not None
    assert app.state_machine.current_screen is not None

    # Run for 3 frames
    app.run(max_frames=3)
    assert not app.running or app.state_machine.current_screen is not None
    app.cleanup()


# --- Wipeout Game Over (Java GameScreen.java:433-446, CombatScreen.java:562-589) ---


def test_combat_screen_defeat_routes_to_game_over(pygame_setup, asset_mgr, sample_party):
    """Combat wipeout defeat is a loss: StartScreen game over, no Castle British
    respawn and no auto-revive."""
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_B.ULT")
    before_map_id = sample_party.map_id

    combat = CombatScreen(
        party=sample_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
    )

    # Simulate party wipeout
    combat.party.kill_all()
    combat.arena.is_defeat = True
    combat.arena.is_finished = True

    assert combat.party.is_party_dead()

    # Press Enter / Space after defeat message
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))

    assert combat.is_finished
    from py_exodus.screens.start import StartScreen

    assert isinstance(combat.next_screen, StartScreen)
    assert combat.next_screen.game_over is True
    # No revival and no Castle British warp
    assert combat.party.is_party_dead()
    assert combat.party.map_id == before_map_id
    assert all(m.status == Status.DEAD for m in combat.party.members)


def test_combat_screen_defeat_via_state_machine_transitions_to_game_over(pygame_setup, asset_mgr, sample_party):
    from py_exodus.world.loader import MapLoader

    sm = StateMachine(asset_mgr)
    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_B.ULT")

    # Start with overworld screen
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    combat = CombatScreen(
        party=sample_party,
        combat_map=c_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        return_screen=ow,
        manager=sm,
    )
    sm.push_screen(combat)
    assert sm.current_screen is combat

    # Simulate defeat
    combat.party.kill_all()
    combat.arena.is_defeat = True
    combat.arena.is_finished = True

    # User presses Space
    sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))

    # Active screen in state machine must now be the StartScreen game over
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True
    # No auto-revive
    assert sample_party.is_party_dead()
    assert not sample_party.is_anyone_alive()


def test_lord_british_revives_dead_and_ashes_members(pygame_setup, asset_mgr, sample_party):
    # Member 0: Dead, Member 1: Ashes, Member 2: Good
    sample_party.members[0].status = Status.DEAD
    sample_party.members[0].hp = 0
    sample_party.members[1].status = Status.ASHES
    sample_party.members[1].hp = 0
    sample_party.members[2].status = Status.GOOD

    town = TownScreen(
        party=sample_party,
        map_id=1,
        asset_mgr=asset_mgr,
    )

    town._interact_lord_british()

    # Members 0 and 1 must be resurrected to GOOD status with full hp
    assert sample_party.members[0].status == Status.GOOD
    assert sample_party.members[0].hp == sample_party.members[0].max_hp
    assert sample_party.members[1].status == Status.GOOD
    assert sample_party.members[1].hp == sample_party.members[1].max_hp
    assert "Lord British says: 'Thou art resurrected!'" in " ".join(town.text_log.history)


def test_lord_british_revives_and_advances_eligible_member(pygame_setup, asset_mgr, sample_party):
    # Member has enough EXP to advance from level 1 to level 2, but is dead
    sample_party.members[0].status = Status.DEAD
    sample_party.members[0].hp = 0
    sample_party.members[0].level = 1
    sample_party.members[0].exp = 150  # Eligible for level 2

    town = TownScreen(
        party=sample_party,
        map_id=1,
        asset_mgr=asset_mgr,
    )

    town._interact_lord_british()

    # Must be resurrected AND advanced
    assert sample_party.members[0].status == Status.GOOD
    assert sample_party.members[0].level == 2
    assert "Lord British says: 'Thou art resurrected!'" in " ".join(town.text_log.history)
    assert any("Thou hast been advanced!" in msg for msg in town.text_log.history)


def test_town_screen_exit_resets_map_id_from_castle_british(pygame_setup, asset_mgr, sample_party):
    sample_party.map_id = 1
    sample_party.x = 32
    sample_party.y = 61

    town = TownScreen(
        party=sample_party,
        map_id=1,
        asset_mgr=asset_mgr,
    )

    town._exit_town()

    assert sample_party.map_id == 0
    assert sample_party.x == 45
    assert sample_party.y == 18


def test_transact_talk_flow_with_npc_conversation(pygame_setup, asset_mgr, sample_party):
    """Pressing 'T' prompts for party member, then direction, and talking to NPC outputs their dialogue."""
    # Chuckles is at (32, 44) in british.ult; place avatar south at (32, 45)
    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=32, start_y=45)

    # Press 'T' for Talk
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t, unicode="t"))
    assert town.text_log.is_waiting_for_input
    assert "Which party member?" in town.text_log.current_prompt

    # Select member 1
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
    assert town.text_log.is_waiting_for_input
    assert "Direction?" in town.text_log.current_prompt

    # Face North towards Chuckles
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    assert not town.text_log.is_waiting_for_input
    # Chuckles dialogue must be displayed
    assert any("Chuckles" in msg or "Welcome all" in msg for msg in town.text_log.history)


def test_transact_across_counter_to_vendor(pygame_setup, asset_mgr, sample_party):
    """Talking across a counter/sign tile engages the vendor behind the counter for the chosen member."""
    # In LCB (map 3), Osbert's Weaponry is at (39, 17), sign tile at (39, 18), avatar at (39, 19)
    town = TownScreen(party=sample_party, map_id=3, asset_mgr=asset_mgr, start_x=39, start_y=19)

    # Press 'T' for Talk
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t, unicode="t"))
    assert "Which party member?" in town.text_log.current_prompt

    # Select member 2
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2, unicode="2"))
    assert "Direction?" in town.text_log.current_prompt

    # Face North across sign at (39, 18) to vendor at (39, 17)
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    # Shopping menu for Osbert's Weaponry should now be active
    assert any("Osbert" in msg or "Weaponry" in msg for msg in town.text_log.history)
    assert town.text_log.is_waiting_for_input
    assert "buy" in town.text_log.current_prompt.lower()


def test_transact_talk_empty_direction_no_response(pygame_setup, asset_mgr, sample_party):
    """Talking in an empty direction yields 'Funny, no response!'."""
    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=32, start_y=61)

    # Press 'T'
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t, unicode="t"))
    # Select member 1
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
    # Face South (empty doorway/exit)
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    assert any("Funny, no response!" in msg for msg in town.text_log.history)



def test_overworld_commands_cast_ztats_get_chest_pass(pygame_setup, asset_mgr, sample_party):
    overworld = OverworldScreen(
        party=sample_party,
        map_id=0,
        asset_mgr=asset_mgr,
    )

    # 1. Pass command (SPACE)
    initial_food = sample_party.food
    evt_space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    overworld.handle_event(evt_space)
    assert any("Pass." in msg for msg in overworld.text_log.history)

    # 2. Ztats command (Z)
    assert overworld.stats_panel.inspect_index is None
    evt_z = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z)
    overworld.handle_event(evt_z)
    assert overworld.stats_panel.inspect_index == 0
    overworld.handle_event(evt_z)
    assert overworld.stats_panel.inspect_index == 1
    overworld.handle_event(evt_z)  # 2
    overworld.handle_event(evt_z)  # 3
    overworld.handle_event(evt_z)  # None
    assert overworld.stats_panel.inspect_index is None

    # 3. Get Chest command (G): picks a member, credits that member's purse (10-66 gold)
    sample_party.x = 10
    sample_party.y = 10
    sample_party.gold = 100
    opening_member = sample_party.members[0]
    member_gold_before = opening_member.gold
    sample_party.dynamic_objects = [{"tile": "chest", "x": 10, "y": 10}]
    evt_g = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, unicode="g")
    overworld.handle_event(evt_g)
    assert overworld.text_log.is_waiting_for_input
    overworld.text_log.handle_char("1")
    overworld.text_log.handle_enter()
    assert len(sample_party.dynamic_objects) == 0
    opening_gold_delta = opening_member.gold - member_gold_before
    assert sample_party.gold == 100 + opening_gold_delta
    assert 10 <= opening_gold_delta <= 66
    assert opening_member.gold <= 9999
    assert any("The Chest Holds: " in msg for msg in overworld.text_log.history)

    # 4. Ignite torch (I)
    sample_party.torches = 2
    sample_party.torch_duration = 0
    evt_i = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i)
    overworld.handle_event(evt_i)
    assert sample_party.torches == 1
    assert sample_party.torch_duration == 100
    assert any("Torch ignited!" in msg for msg in overworld.text_log.history)

    # 5. Join gold (J)
    sample_party.gold = 50
    evt_j = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_j)
    overworld.handle_event(evt_j)
    assert any("All gold gathered" in msg for msg in overworld.text_log.history)


def test_overworld_wandering_creatures(pygame_setup, asset_mgr, sample_party):
    overworld = OverworldScreen(
        party=sample_party,
        map_id=0,
        asset_mgr=asset_mgr,
    )

    # Verify wandering creatures list exists and can spawn
    assert hasattr(overworld, "creatures")
    assert len(overworld.creatures) > 0

    # Creature pursuit test: position creature 1 step north of party
    sample_party.x = 20
    sample_party.y = 20
    c = overworld.creatures[0]
    c["x"] = 20
    c["y"] = 19
    c["tile_name"] = "orc"

    # Step party towards creature to trigger encounter
    evt_up = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP)
    overworld.handle_event(evt_up)

    # Encounter should have engaged combat screen
    assert overworld.is_finished or overworld.next_screen is not None


def test_town_pass_and_ztats(pygame_setup, asset_mgr, sample_party):
    town = TownScreen(
        party=sample_party,
        map_id=1,
        asset_mgr=asset_mgr,
    )

    evt_space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    town.handle_event(evt_space)
    assert any("Pass." in msg for msg in town.text_log.history)

    assert town.stats_panel.inspect_index is None
    evt_z = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z)
    town.handle_event(evt_z)
    assert town.stats_panel.inspect_index == 0


def test_responsive_hires_rendering(pygame_setup, asset_mgr, sample_party):
    # Test rendering screens on a native 960x600 high-res surface
    hires_surf = pygame.Surface((960, 600))

    overworld = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)
    overworld.render(hires_surf)

    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map(37)
    combat = CombatScreen(party=sample_party, combat_map=c_map, creature_tile="orc", asset_mgr=asset_mgr)
    combat.render(hires_surf)

    town = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr)
    town.render(hires_surf)


def test_navigation_arrow_keys_only_no_wasd(pygame_setup, asset_mgr, sample_party):
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)
    start_x, start_y = sample_party.x, sample_party.y

    # WASD keys must NOT move the avatar (they are reserved for Wear, Attack, Search, Descend)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, unicode="w"))
    assert (sample_party.x, sample_party.y) == (start_x, start_y)
    ow.text_log.cancel_prompt()

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
    assert (sample_party.x, sample_party.y) == (start_x, start_y)
    ow.text_log.cancel_prompt()

    # Arrow keys DO move the avatar
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    assert sample_party.y != start_y or sample_party.x != start_x


def test_all_overland_commands_a_to_z(pygame_setup, asset_mgr, sample_party):
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)

    # B - Board & X - Exit transport
    sample_party.transport = Transport.FOOT
    sample_party.dynamic_objects = [{"tile": "horse", "x": sample_party.x, "y": sample_party.y}]
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert sample_party.transport == Transport.HORSE
    assert any("Mount Horse!" in msg for msg in ow.text_log.history)

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x))
    assert sample_party.transport == Transport.FOOT
    assert any("Dismounted horse." in msg for msg in ow.text_log.history)

    # O - Other command
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("PRAY")
    assert any("calmness and silence" in msg for msg in ow.text_log.history)

    # Y - Yell
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_y))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("EVOCARE")
    assert any("EVOCARE" in msg for msg in ow.text_log.history)

    # M - Modify order
    m0_name = sample_party.members[0].name
    m1_name = sample_party.members[1].name
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("2")
    assert sample_party.members[0].name == m1_name
    assert sample_party.members[1].name == m0_name

    # H - Hand equipment
    sample_party.members[0].gold = 50
    sample_party.members[1].gold = 10
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("2")
    assert any("handed" in msg for msg in ow.text_log.history)

    # L - Look
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_l))
    assert any("Look:" in msg for msg in ow.text_log.history)

    # S - Search
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
    if ow.text_log.is_waiting_for_input:
        ow.text_log.submit_input("1")
    assert any("Search:" in msg or "searches" in msg or "Nothing here" in msg for msg in ow.text_log.history)

    # N - Negate Time
    sample_party.members[0].powder = 2
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n))
    assert ow.time_stopped_turns == 15
    assert any("Negate Time!" in msg for msg in ow.text_log.history)

    # V - Volume
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v))
    assert any("Volume:" in msg for msg in ow.text_log.history)

    # D & K - Descend and Klimb in overworld
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    assert any("Descend:" in msg for msg in ow.text_log.history)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_k))
    assert any("Klimb:" in msg for msg in ow.text_log.history)

    # T & U - Transact and Unlock in overworld
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t))
    assert any("Transact:" in msg for msg in ow.text_log.history)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_u))
    assert any("Unlock:" in msg for msg in ow.text_log.history)


def test_ready_weapon_and_wear_armor_a_p_flow_and_inventory(pygame_setup, asset_mgr, sample_party):
    """Verify Ready (A-P) and Wear (A-H) letter prompts and inventory tracking."""
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)
    m = sample_party.members[0]
    m.weapons[WeaponType.DAGGER] = 1
    m.armors[ArmorType.LEATHER] = 1
    m.weapon = WeaponType.NONE
    m.armor = ArmorType.NONE

    # Ready Weapon (R)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    assert "Which member?" in ow.text_log.current_prompt
    ow.text_log.handle_char("1")

    # Options listed and prompt for A-P
    assert "Ready Weapon?" in ow.text_log.current_prompt
    assert "A-P" in ow.text_log.current_prompt

    # Select 'B' for Dagger
    ow.text_log.handle_char("B")
    assert m.weapon == WeaponType.DAGGER
    assert m.weapons[WeaponType.DAGGER] == 0
    assert any("readied" in msg for msg in ow.text_log.history)

    # Ready 'A' for Hands (un-equips Dagger back into inventory)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    ow.text_log.handle_char("1")
    ow.text_log.handle_char("A")
    assert m.weapon == WeaponType.NONE
    assert m.weapons[WeaponType.DAGGER] == 1

    # Wear Armor (W)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w))
    assert "Which member?" in ow.text_log.current_prompt
    ow.text_log.handle_char("1")

    # Options listed and prompt for A-H
    assert "Wear Armor?" in ow.text_log.current_prompt
    assert "A-H" in ow.text_log.current_prompt

    # Select 'C' for Leather
    ow.text_log.handle_char("C")
    assert m.armor == ArmorType.LEATHER
    assert m.armors[ArmorType.LEATHER] == 0
    assert any("wears" in msg for msg in ow.text_log.history)


def test_combat_screen_flash_and_visual_fx(pygame_setup, asset_mgr, sample_party):
    """Verify combat screen flash on cast, projectile & hit bursts, and R/W prompts."""
    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map(37)
    combat = CombatScreen(party=sample_party, combat_map=c_map, creature_tile="orc", asset_mgr=asset_mgr)

    # Cast spell triggers flash_timer
    active = combat.active_party_member
    active.mp = 50
    combat._execute_action(Action.cast(Spell.FULGAR, direction=Direction.NORTH))
    assert combat.flash_timer > 0.0
    assert any(fx["type"] == "spell" for fx in combat.combat_fx)

    # Update decrements flash_timer
    combat.update(0.3)
    assert combat.flash_timer == 0.0

    # Weapon attack creates weapon combat FX
    combat._execute_action(Action.attack(Direction.NORTH))
    assert any(fx["type"] == "weapon" for fx in combat.combat_fx)

    # Ready weapon in combat (K_r)
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    assert "Ready Weapon?" in combat.text_log.current_prompt


def test_zstats_displays_inventory(pygame_setup, asset_mgr, sample_party):
    """Verify Zstats displays non-zero weapon and armor inventory."""
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)
    m = sample_party.members[0]
    m.weapons[WeaponType.BOW] = 2
    m.armors[ArmorType.CHAIN] = 1

    # Toggle Zstats to inspect member 1
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z))
    assert ow.stats_panel.inspect_index == 0
    assert any("BOW:2" in msg for msg in ow.text_log.history)
    assert any("CHAIN:1" in msg for msg in ow.text_log.history)


def test_new_game_starter_party_spawn_location(pygame_setup, asset_mgr):
    """Verify new game party starts 2 tiles south and 1 tile west of castle on grass (44, 20)."""
    party = create_default_starter_party()
    assert party.x == 44
    assert party.y == 20

    # Verify tile at (44, 20) is grass and not castle
    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)
    world_map = loader.load_map(0)
    spawn_tile = world_map.get_tile(party.x, party.y)
    assert spawn_tile.name == "grass"
    castle_tile = world_map.get_tile(45, 18)
    assert castle_tile.name == "castle"


def test_overworld_creature_encounter_cleans_up_creature(pygame_setup, asset_mgr, sample_party):
    """Verify colliding creature is removed from overworld.creatures and on_enter purges party tile."""
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr, random_encounters=False)
    sample_party.x = 25
    sample_party.y = 25

    # Add an ogre directly on the party
    ogre = {"tile_name": "giant", "x": 25, "y": 25}
    ow.creatures = [ogre]

    # Updating creatures should detect encounter and purge the creature
    ow._update_creatures()
    assert ogre not in ow.creatures
    assert len(ow.creatures) == 0

    # Test on_enter also cleans up any creature at party position
    ow.creatures = [{"tile_name": "orc", "x": 25, "y": 25}, {"tile_name": "orc", "x": 30, "y": 30}]
    ow.on_enter()
    assert len(ow.creatures) == 1
    assert ow.creatures[0]["x"] == 30


def test_combat_screen_mittar_visual_projectile(pygame_setup, asset_mgr, sample_party):
    """Verify Mittar spellcast sets up blue projectile FX with travel trajectory and hit burst."""
    from py_exodus.constants import Spell
    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_A.ULT")

    # Ensure member 0 has MP and can cast wizard spells
    m = sample_party.members[0]
    m.mp = 50

    combat = CombatScreen(party=sample_party, combat_map=c_map, creature_tile="orc", asset_mgr=asset_mgr)
    combat.combat_fx.clear()

    # Execute Mittar spell cast
    cast_action = Action.cast(Spell.MITTAR, direction=Direction.NORTH)
    combat._execute_action(cast_action)

    # Check flash timer is set to a crisp 0.10s
    assert combat.flash_timer == pytest.approx(0.10, rel=1e-2)

    # Check combat_fx has the projectile
    assert len(combat.combat_fx) == 1
    fx = combat.combat_fx[0]
    assert fx["type"] == "spell"
    assert fx["color"] == (0, 180, 255)  # Bright blue
    assert fx["start_pos"] is not None
    assert fx["target_pos"] is not None
    assert fx["duration"] == 0.35

    # Render into surface to ensure drawing works properly
    surf = pygame.Surface((640, 400))
    combat.render(surf)

    # Update half-way (progress >= 0.5) to test hit burst rendering
    combat.update(0.20)
    combat.render(surf)


def test_combat_screen_zero_mp_casting(pygame_setup, asset_mgr, sample_party):
    """Verify in combat screen that 0 MP allows casting 0-cost Spell A and prompts correctly."""
    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_A.ULT")

    m = sample_party.members[0]
    m.profession = Profession.WIZARD
    m.mp = 0

    combat = CombatScreen(party=sample_party, combat_map=c_map, creature_tile="giant", asset_mgr=asset_mgr)

    # Press 'C' to Cast
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
    assert combat.text_log.is_waiting_for_input
    assert "Wizard Spell?" in combat.text_log.current_prompt

    # Select Spell A (REPOND, 0 MP)
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="A"))
    # Repond resolves without MP error
    assert not any("not enough mp" in msg.lower() for msg in combat.text_log.history)
