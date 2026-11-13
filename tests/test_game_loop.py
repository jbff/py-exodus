"""Integration tests for State Machine, Audio Manager, Screens, and Game Loop."""
from __future__ import annotations

import os
import random
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pygame

from py_exodus.__main__ import GameApp
from py_exodus.assets import AssetManager
from py_exodus.audio import AudioManager
from py_exodus.aura import AuraType
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
from py_exodus.save_system import SaveSystem
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.start import StartScreen
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


def _build_test_party() -> Party:
    """Explicit 4-member party assembled from roster-created-style records.

    The default/starter party was removed by user ruling (2026-11-09) —
    Java ships none — so tests build parties explicitly. Members carry the
    user-directed original-rules starting MP (compute_max_mp; SaveGame.java:
    340-376 formula) and per-member gold/food totalling the classic 200/400.
    """
    specs = [
        ("Fighter", Sex.MALE, Race.HUMAN, Profession.PALADIN, 20, 15, 10, 15, 150,
         WeaponType.SWORD, ArmorType.LEATHER, 50, 100),
        ("Cleric", Sex.FEMALE, Race.BOBIT, Profession.CLERIC, 12, 14, 10, 24, 100,
         WeaponType.MACE, ArmorType.CLOTH, 50, 100),
        ("Wizard", Sex.MALE, Race.ELF, Profession.WIZARD, 10, 14, 25, 11, 100,
         WeaponType.DAGGER, ArmorType.CLOTH, 50, 100),
        ("Thief", Sex.FEMALE, Race.FUZZY, Profession.THIEF, 12, 25, 12, 11, 120,
         WeaponType.SLING, ArmorType.LEATHER, 50, 100),
    ]
    members = []
    for name, sex, race, prof, st, dx, in_, wi, hp, weapon, armor, gold, food in specs:
        c = Character(
            name=name,
            sex=sex,
            race=race,
            profession=prof,
            strength=st,
            dexterity=dx,
            intelligence=in_,
            wisdom=wi,
            hp=hp,
            max_hp=hp,
            weapon=weapon,
            armor=armor,
            gold=gold,
            food=food,
        )
        c.mp = c.compute_max_mp()
        members.append(c)
    return Party(
        members=members,
        # Default new-game start (Java SaveGame.java:164-169): (45, 19).
        x=45,
        y=19,
    )


@pytest.fixture
def sample_party():
    """Create a sample 4-character party."""
    return _build_test_party()


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


def test_start_screen_journey_onward(pygame_setup, asset_mgr, sample_party, monkeypatch, tmp_path):
    """Java StartScreen.java:100-117 — Journey Onward reads the on-disk party
    save; a valid save launches the overworld."""
    monkeypatch.chdir(tmp_path)
    SaveSystem.save_game(sample_party, tmp_path / "saves" / "party.json")

    sm = StateMachine(asset_mgr)
    scr = StartScreen(asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(scr)

    # Press Enter on Journey Onward
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert isinstance(sm.current_screen, OverworldScreen)
    assert [m.name for m in sm.current_screen.party.members] == [
        m.name for m in sample_party.members
    ]


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

    # Press 'X' — Task 9 parity: X only dismounts to FOOT; leaving a town is
    # border-walking only (Java GameScreen.java:584-596).
    sample_party.transport = Transport.HORSE
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x))
    assert sample_party.transport == Transport.FOOT
    assert sm.current_screen is town and not town.is_finished


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
    # Java truth: the vendor charges the shopping member's own purse (gold
    # lives on each CharacterRecord; Party.gold is a derived sum).
    from py_exodus.constants import WeaponType

    buyer = sample_party.active_member or sample_party.members[0]
    for m in sample_party.members:
        m.gold = 0
    buyer.gold = 50

    town._start_vendor_shopping(vendor)
    assert town.text_log.is_waiting_for_input

    # Task 8: WEAPON vendors run the WeaponVendor state machine (Java
    # WeaponVendor.java), not the generic menu. Wrapped log lines rejoin.
    log = " ".join(" ".join(town.text_log.history).split())
    assert "Art thou here to Buy or Sell?" in log

    # Buy Dagger (choice 'a') from the catalog ("b" = Buy); single-char
    # prompts auto-commit on handle_char.
    town.text_log.handle_char("b")
    town.text_log.handle_char("a")
    # gold 50 > 2 * 5 -> the multi-char how-many prompt
    town.text_log.handle_char("1")
    town.text_log.handle_enter()

    assert sample_party.gold == 45
    assert buyer.weapons.get(WeaponType.DAGGER, 0) == 1
    log = " ".join(" ".join(town.text_log.history).split())
    assert "A fine choice! anything else?" in log


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
    c_map = loader.load_conflict_map("cnflct_g.json")

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
    c_map = loader.load_conflict_map("cnflct_g.json")

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
    c_map = loader.load_conflict_map("cnflct_g.json")

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

    # Use torch (Java DungeonScreen.java:988-1004 — I is the torch key)
    sample_party.members[0].character.torches = 2
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i))
    assert dungeon.state.is_torch_on is True
    assert sample_party.members[0].character.torches == 1


def test_dungeon_screen_render(pygame_setup, asset_mgr, sample_party):
    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
    )
    surf = pygame.Surface((320, 200))
    dungeon.render(surf)
    assert surf.get_at((0, 0)) is not None


def test_dungeon_screen_backstep_and_ladders(pygame_setup, asset_mgr, sample_party):
    from py_exodus.world.map import DungeonTile

    sm = StateMachine(asset_mgr)
    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
        manager=sm,
    )
    sm.push_screen(dungeon)

    # 1. DOWN steps backward in the current facing (Java
    #    DungeonScreen.java:933-957) — the facing never changes.
    initial_dir = dungeon.state.dir
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    assert dungeon.state.dir == initial_dir

    # 2. Ladder down on ladder tile (Java keys: K up, D down)
    dungeon.dungeon_map.set_tile(dungeon.state.x, dungeon.state.y, dungeon.state.z, DungeonTile.LADDER_DOWN)
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    assert dungeon.state.z == 1

    # 3. Ladder up on ladder tile
    dungeon.dungeon_map.set_tile(dungeon.state.x, dungeon.state.y, dungeon.state.z, DungeonTile.LADDER_UP)
    dungeon.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_k))
    assert dungeon.state.z == 0


def test_dungeon_screen_torch_toggle(pygame_setup, asset_mgr, sample_party):
    """Java DungeonScreen.java:988-1004 — I lights once, I again extinguishes
    with no consumption, I with no torches logs "No Torches!"."""
    sample_party.members[0].character.torches = 2

    dungeon = DungeonScreen(
        party=sample_party,
        map_id=14,
        asset_mgr=asset_mgr,
    )

    # Ignite torch
    dungeon._use_torch()
    assert dungeon.state.is_torch_on is True
    assert sample_party.members[0].character.torches == 1

    # Extinguish: no torch consumed
    dungeon._use_torch()
    assert dungeon.state.is_torch_on is False
    assert sample_party.members[0].character.torches == 1

    # No torches owned: "No Torches!"
    sample_party.members[0].character.torches = 0
    dungeon._use_torch()
    assert dungeon.state.is_torch_on is False
    assert any("No Torches!" in msg for msg in dungeon.text_log.history)


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
    c_map = loader.load_conflict_map("cnflct_b.json")
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
    c_map = loader.load_conflict_map("cnflct_b.json")

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


def test_lord_british_does_not_resurrect_dead_members(pygame_setup, asset_mgr, sample_party):
    """Java truth: SecondaryInputProcessor.java:190-197 — Lord British only
    advances the talking member; the resurrection loop (ConversationDialog
    .java:133-160) is commented out in Java, so DEAD/ASHES stay as they are."""
    sample_party.members[0].status = Status.DEAD
    sample_party.members[0].hp = 0
    sample_party.members[0].exp = 0
    sample_party.members[1].status = Status.ASHES
    sample_party.members[1].hp = 0
    sample_party.members[1].exp = 0
    sample_party.members[2].status = Status.GOOD
    sample_party.members[2].exp = 0

    town = TownScreen(
        party=sample_party,
        map_id=1,
        asset_mgr=asset_mgr,
    )

    town._interact_lord_british()

    # No resurrection: statuses are untouched
    assert sample_party.members[0].status == Status.DEAD
    assert sample_party.members[1].status == Status.ASHES
    joined = " ".join(town.text_log.history)
    assert "resurrected" not in joined.lower()
    # No advance -> the welcome flow
    assert "Experience more!" in joined


def test_lord_british_advances_active_member_without_mark_at_level_5(pygame_setup, asset_mgr, sample_party):
    # Active member has enough EXP to reach level 5 (exp 450 / expLvl 4);
    # no Mark of Kings is needed below level 6.
    sample_party.members[0].level = 1
    sample_party.members[0].exp = 450
    sample_party.members[0].marks = [0, 0, 0, 0]

    town = TownScreen(
        party=sample_party,
        map_id=1,
        asset_mgr=asset_mgr,
    )

    town._interact_lord_british()

    assert sample_party.members[0].level == 5
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
    assert any(m == "Pass" for m in overworld.text_log.history)  # Java GameScreen.java:626-627

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

    # 3. Get Chest command (G): member digit opens the chest at the PARTY'S
    # OWN tile, credited to that member (fix round 2, final ruling)
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

    # 4. Ignite torch (I) — Java: I is NOT handled on the overworld
    #    (GameScreen.keyUp has no Keys.I branch) — it falls through to
    #    finishTurn silently, consuming no torches.
    sample_party.torches = 2
    sample_party.torch_duration = 0
    moves_before = sample_party.moves
    evt_i = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i)
    overworld.handle_event(evt_i)
    assert sample_party.torches == 2
    assert sample_party.torch_duration == 0
    assert not any("Torch ignited" in msg for msg in overworld.text_log.history)
    assert sample_party.moves == moves_before + 1

    # 5. Join gold (J) — Task 9 parity: member prompt + pool_gold(index)
    total_before_join = sample_party.gold  # derived: the members' purses sum
    evt_j = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_j, unicode="j")
    overworld.handle_event(evt_j)
    assert overworld.text_log.is_waiting_for_input
    overworld.text_log.submit_input("1")
    assert opening_member.gold == total_before_join
    assert all(m.gold == 0 for m in sample_party.members[1:])


def test_overworld_wanderer_spawn_never_lands_on_occupied_tile(pygame_setup, asset_mgr):
    """Occupancy guard on the wandering-creature spawn (2026-11-10 robustness
    fix): Java GameScreen.spawnCreature (GameScreen.java:769-818) re-samples
    a spawn tile up to maxTries but only rejects rule-less tiles — it never
    checks whether a creature already stands there. The port keeps the same
    random candidate shape but re-picks until the tile holds no creature and
    no party (capped at Java's 10 tries). Without the guard a fresh spawn
    can trample a restored save fixture (e.g. the Sosaria whirlpool at
    (50,13)) and the Journey Onward restore test flakes. Seeded regression:
    400 spawns against 8 fixed occupants inside the candidate ring."""
    random.seed(1234)

    party = Party()
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
    party.x, party.y = 20, 20
    overworld = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr)
    overworld.creatures.clear()

    # The spawn candidate ring around (20,20) is dist 8..12 (either sign, on
    # each axis): x in {8..12, 28..32}, y the same. 7 occupants seeded there
    # give ~7% occupancy per candidate (7 < the 8-creature spawn cap, so the
    # attempts are not short-circuited), so a spawn without the guard hits an
    # occupied tile many times across 400 attempts.
    for ox, oy in ((28, 28), (12, 12), (28, 12), (12, 28), (32, 32),
                   (8, 8), (20, 30)):
        overworld.creatures.append({
            "name": "Orc", "tile_name": "orc", "tile": "orc", "x": ox, "y": oy,
        })

    recorded: list = []
    for _ in range(400):
        before = len(overworld.creatures)
        overworld._spawn_wandering_creature()
        if len(overworld.creatures) > before:
            # Record the spawn, then vacate it so the 8 fixed occupants stay
            # the only standing creatures for the next attempt (the 8-cap
            # would otherwise starve the loop of spawns).
            spawned = overworld.creatures[-1]
            recorded.append((spawned["x"], spawned["y"]))
            overworld.creatures.pop()

    assert recorded, "no spawn succeeded in 400 attempts"
    permanent = {(c["x"], c["y"]) for c in overworld.creatures}
    for pos in recorded:
        assert pos not in permanent, f"spawn trampled occupant at {pos}"


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
    assert any(m == "Pass" for m in town.text_log.history)  # Java GameScreen.java:626-627

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

    # Y - Yell — Task 9 parity: member prompt, then word prompt
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_y))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("EVOCARE")
    assert any("No effect." in msg for msg in ow.text_log.history)

    # M - Modify order
    m0_name = sample_party.members[0].name
    m1_name = sample_party.members[1].name
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("2")
    assert sample_party.members[0].name == m1_name
    assert sample_party.members[1].name == m0_name

    # H - Hand equipment — Task 9 parity: any unequipped weapon OR armor
    # transfers; there is no gold handoff (HandDialog.java:114-146).
    sample_party.members[0].gold = 50
    sample_party.members[1].gold = 10
    sample_party.members[0].weapons[WeaponType.AXE] = 1
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h))
    assert ow.text_log.is_waiting_for_input
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("2")
    assert any("handed" in msg for msg in ow.text_log.history)
    assert sample_party.members[1].weapons[WeaponType.AXE] == 1

    # L - OPEN with a direction (Java SIP:212-219; there is no Look command)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_l))
    assert ow.text_log.is_waiting_for_input
    assert "OPEN" in ow.text_log.current_prompt
    ow.text_log.submit_input("N")
    assert any(m in ("Opened!", "Can't!") for m in ow.text_log.history)

    # S - Search
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
    if ow.text_log.is_waiting_for_input:
        ow.text_log.submit_input("1")
    assert any("Search:" in msg or "searches" in msg or "Nothing here" in msg for msg in ow.text_log.history)

    # N - Negate Time — Task 9 parity: powder → 6-turn QUICKNESS aura
    sample_party.members[0].powder = 2
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n))
    assert sample_party.members[0].powder == 1
    assert sample_party.aura.get_type() == AuraType.QUICKNESS
    # Java GameScreen.java:604-628 — N falls through to finishTurn, whose
    # aura.passTurn ticks once at the press, so 6 becomes 5 immediately.
    assert sample_party.aura.get_duration() == 5
    assert any("Stop time with a powder!" in msg for msg in ow.text_log.history)

    # V - Volume
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v))
    assert any("Volume:" in msg for msg in ow.text_log.history)

    # D & K - unhandled on the overworld (Java GameScreen.keyUp has no
    # Keys.D/Keys.K branch): they fall through to finishTurn with no message.
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_k))
    assert not any("Descend:" in msg or "Klimb:" in msg for msg in ow.text_log.history)

    # T & U - Talk and Unlock in overworld (Task 9 parity: real member flows,
    # Java SIP:152-238; "Transact:" stub is gone)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t))
    assert ow.text_log.is_waiting_for_input
    assert "TALK" in ow.text_log.current_prompt
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("N")
    assert any("Funny, no response!" in msg for msg in ow.text_log.history)

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_u))
    assert ow.text_log.is_waiting_for_input
    assert "UNLOCK" in ow.text_log.current_prompt
    ow.text_log.submit_input("1")
    ow.text_log.submit_input("N")
    assert any(m in ("Unlocked!", "Can't!") for m in ow.text_log.history)


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
    assert any("Success!" in msg for msg in ow.text_log.history)

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
    assert any("Success!" in msg for msg in ow.text_log.history)


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


def test_new_game_party_spawn_location(pygame_setup, asset_mgr):
    """Verify new game party starts at (45, 19) — Java SaveGame.java:164-169
    seeds the default position to (45, 19), just south of the castle portal."""
    party = _build_test_party()
    assert party.x == 45
    assert party.y == 19

    # Verify tile at (45, 19) is grass and not castle
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
    c_map = loader.load_conflict_map("cnflct_a.json")

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
    c_map = loader.load_conflict_map("cnflct_a.json")

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
