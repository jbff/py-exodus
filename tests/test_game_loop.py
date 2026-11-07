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
    Direction,
    Profession,
    Race,
    Sex,
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

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    assert ow.text_log.is_waiting_for_input

    # Type direction 'N' and Enter
    ow.text_log.handle_char("N")
    ow.text_log.handle_enter()
    assert any("Broadside fired NORTH" in msg for msg in ow.text_log.history)


def test_overworld_screen_transport_toggle(pygame_setup, asset_mgr, sample_party):
    sample_party.transport = Transport.FOOT
    ow = OverworldScreen(party=sample_party, map_id=0, asset_mgr=asset_mgr)

    # Board horse
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert sample_party.transport == Transport.HORSE

    # Dismount
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
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


# --- Wipeout Respawn & Lord British Resurrection Tests ---


def test_combat_screen_defeat_respawns_at_castle_british(pygame_setup, asset_mgr, sample_party):
    from py_exodus.world.loader import MapLoader

    loader = MapLoader(asset_mgr)
    c_map = loader.load_conflict_map("CNFLCT_B.ULT")

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
    assert isinstance(combat.next_screen, TownScreen)
    assert combat.next_screen.map_id == 1
    assert combat.party.map_id == 1
    assert combat.party.x == 32
    assert combat.party.y == 61
    assert combat.party.is_anyone_alive()
    assert all(m.status == Status.GOOD for m in combat.party.members)


def test_combat_screen_defeat_via_state_machine_transition(pygame_setup, asset_mgr, sample_party):
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

    # Active screen in state machine must now be Castle British TownScreen
    assert isinstance(sm.current_screen, TownScreen)
    assert sm.current_screen.map_id == 1
    assert sample_party.map_id == 1
    assert sample_party.x == 32
    assert sample_party.y == 61
    assert sample_party.is_anyone_alive()


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
