"""Tests for 3D wireframe dungeon corridor renderer and navigation."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.dungeon import (
    COLOR_BLACK,
    DungeonCamera,
    DungeonEventType,
    DungeonState,
    get_relative_offsets,
    turn_left_dir,
    turn_right_dir,
)
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def perinian_dmap(asset_mgr):
    loader = MapLoader(asset_mgr)
    return loader.load_dungeon_map("perinian.ult")


@pytest.fixture
def test_party():
    p = Party(food=200, gold=100)
    c1 = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100, torches=5)
    c2 = Character("Mage", "F", Race.ELF, Profession.WIZARD, hp=80, max_hp=80, torches=0)
    p.add_member(c1)
    p.add_member(c2)
    return p


@pytest.fixture
def empty_dmap():
    """Create a 16x16x8 dungeon map enclosed by walls with an open interior corridor."""
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = []
    for z in range(8):
        grid = []
        for y in range(16):
            row = []
            for x in range(16):
                if x == 0 or x == 15 or y == 0 or y == 15:
                    row.append(DungeonTile.WALL)
                else:
                    row.append(DungeonTile.FLOOR)
            grid.append(row)
        tiles.append(grid)
    dmap.tiles = tiles
    dmap.level_texts = [f"Message for level {z + 1}" for z in range(8)]
    return dmap


# --- Rendering Tests ---

def test_dungeon_wireframe_render(asset_mgr, perinian_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    state = DungeonState(perinian_dmap, start_x=1, start_y=1, start_z=0, start_dir=Direction.NORTH)
    cam = DungeonCamera()
    cam.render_wireframe(surf, perinian_dmap, state.x, state.y, state.z, state.dir)
    assert surf.get_at((88, 88)) is not None


def test_dungeon_wireframe_all_directions(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()

    for direction in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
        cam.render_wireframe(surf, empty_dmap, 5, 5, 0, direction, torch_rounds=50)
        # Verify surface has drawn lines (non-black pixels)
        non_black = False
        for px in range(0, 176, 8):
            for py in range(0, 176, 8):
                col = surf.get_at((px, py))
                if (col.r, col.g, col.b) != COLOR_BLACK:
                    non_black = True
                    break
            if non_black:
                break
        assert non_black, f"No wireframe lines rendered facing {direction.name}"


def test_dungeon_render_torch_vs_dark(empty_dmap):
    pygame.init()
    surf_dark = pygame.Surface((176, 176))
    surf_lit = pygame.Surface((176, 176))
    cam = DungeonCamera()

    # Dark: 0 torch rounds, no light spell
    cam.render_wireframe(surf_dark, empty_dmap, 5, 5, 0, Direction.NORTH, torch_rounds=0, light_spell=False)
    # Lit: 50 torch rounds
    cam.render_wireframe(surf_lit, empty_dmap, 5, 5, 0, Direction.NORTH, torch_rounds=50)

    # Lit view should render more wireframe details/depth than dark view
    dark_pixels = sum(
        1 for x in range(176) for y in range(176) if surf_dark.get_at((x, y))[:3] != COLOR_BLACK
    )
    lit_pixels = sum(
        1 for x in range(176) for y in range(176) if surf_lit.get_at((x, y))[:3] != COLOR_BLACK
    )
    assert lit_pixels > dark_pixels


def test_dungeon_render_fixtures(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()

    # Place various fixtures at (5, 4) in front of camera at (5, 5) facing NORTH
    fixtures = [
        DungeonTile.LADDER_UP,
        DungeonTile.LADDER_DOWN,
        DungeonTile.LADDER_UP_DOWN,
        DungeonTile.CHEST,
        DungeonTile.FOUNTAIN_HEAL,
        DungeonTile.FOUNTAIN_CURE,
        DungeonTile.FOUNTAIN_ACID,
        DungeonTile.FOUNTAIN_POISON,
        DungeonTile.PIT_TRAP,
        DungeonTile.ORB,
        DungeonTile.MARK_KINGS,
        DungeonTile.DOOR,
        DungeonTile.TIME_LORD,
    ]

    for fix in fixtures:
        empty_dmap.set_tile(5, 4, 0, fix)
        cam.render_wireframe(surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_rounds=50)
        # Check non-black fixture pixels exist
        colored = sum(
            1 for x in range(30, 146) for y in range(30, 146) if surf.get_at((x, y))[:3] != COLOR_BLACK
        )
        assert colored > 0, f"Fixture {fix.name} did not produce visible wireframe pixels"


# --- Navigation & Turning Tests ---

def test_relative_offsets_and_turning():
    assert turn_left_dir(Direction.NORTH) == Direction.WEST
    assert turn_left_dir(Direction.WEST) == Direction.SOUTH
    assert turn_left_dir(Direction.SOUTH) == Direction.EAST
    assert turn_left_dir(Direction.EAST) == Direction.NORTH

    assert turn_right_dir(Direction.NORTH) == Direction.EAST
    assert turn_right_dir(Direction.EAST) == Direction.SOUTH
    assert turn_right_dir(Direction.SOUTH) == Direction.WEST
    assert turn_right_dir(Direction.WEST) == Direction.NORTH

    fwd, left, right = get_relative_offsets(Direction.NORTH)
    assert fwd == (0, -1)
    assert left == (-1, 0)
    assert right == (1, 0)


def test_dungeon_state_navigation(empty_dmap):
    state = DungeonState(
        empty_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        random_encounters=False,
    )
    assert state.x == 5 and state.y == 5

    # Move forward NORTH -> (5, 4)
    ev = state.move_forward()
    assert ev.type == DungeonEventType.MOVED
    assert state.x == 5 and state.y == 4

    # Turn right -> EAST
    ev_turn = state.turn_right()
    assert ev_turn.type == DungeonEventType.TURNED
    assert state.dir == Direction.EAST

    # Move forward EAST -> (6, 4)
    ev2 = state.move_forward()
    assert ev2.type == DungeonEventType.MOVED
    assert state.x == 6 and state.y == 4

    # Move backward -> back to (5, 4) while facing EAST
    ev_back = state.move_backward()
    assert ev_back.type == DungeonEventType.MOVED
    assert state.x == 5 and state.y == 4
    assert state.dir == Direction.EAST

    # Step method with specific Direction
    ev_step = state.step(Direction.SOUTH)
    assert ev_step.type == DungeonEventType.MOVED
    assert state.dir == Direction.SOUTH
    assert state.x == 5 and state.y == 5


def test_dungeon_wall_collision(empty_dmap):
    # Wall is at y=0, player at (5, 1) facing NORTH
    state = DungeonState(empty_dmap, start_x=5, start_y=1, start_z=0, start_dir=Direction.NORTH)
    ev = state.move_forward()
    assert ev.type == DungeonEventType.BLOCKED
    assert not ev.success
    assert state.x == 5 and state.y == 1  # Unchanged


# --- Ladders & Climbing Tests ---

def test_dungeon_ladder_climbing(empty_dmap, test_party):
    # Place ladder down at (5, 5, 0) and ladder up at (5, 5, 1)
    empty_dmap.set_tile(5, 5, 0, DungeonTile.LADDER_DOWN)
    empty_dmap.set_tile(5, 5, 1, DungeonTile.LADDER_UP)

    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)

    # Cannot climb up on level 0 ladder down
    ev_up_fail = state.klimb_up()
    assert ev_up_fail.type == DungeonEventType.BLOCKED

    # Climb down to level 1
    ev_down = state.klimb_down()
    assert ev_down.type == DungeonEventType.LADDER_DOWN
    assert state.z == 1
    assert test_party.dungeon_level == 1

    # Climb back up to level 0
    ev_up = state.klimb_up()
    assert ev_up.type == DungeonEventType.LADDER_UP
    assert state.z == 0
    assert test_party.dungeon_level == 0

    # On level 0 with ladder up: exits dungeon to surface
    empty_dmap.set_tile(5, 5, 0, DungeonTile.LADDER_UP)
    ev_exit = state.klimb_up()
    assert ev_exit.type == DungeonEventType.EXIT_DUNGEON


# --- Traps Tests (Pit, Wind, Gremlins) ---

def test_pit_trap(empty_dmap, test_party):
    empty_dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)

    hp_before = test_party.members[0].hp
    ev = state.move_forward()

    assert ev.type == DungeonEventType.PIT_TRAP
    assert state.z == 1  # Fell to level 1
    assert test_party.members[0].hp < hp_before
    # Trap tile on level 0 consumed/replaced with NOTHING
    assert empty_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING


def test_wind_trap(empty_dmap, test_party):
    empty_dmap.set_tile(5, 4, 0, DungeonTile.WIND_TRAP)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    state.torch_rounds = 40
    test_party.torch_duration = 40

    ev = state.move_forward()
    assert ev.type == DungeonEventType.WIND_TRAP
    assert state.torch_rounds == 0
    assert test_party.torch_duration == 0


def test_gremlins_trap(empty_dmap, test_party):
    empty_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    test_party.food = 200

    ev = state.move_forward()
    assert ev.type == DungeonEventType.GREMLINS
    assert test_party.food < 200
    assert empty_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING


# --- Fountains Tests ---

def test_fountains(empty_dmap, test_party):
    m = test_party.members[0]
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)

    # Heal fountain
    m.hp = 30
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_HEAL)
    ev_heal = state.drink_fountain(member_index=0)
    assert ev_heal.type == DungeonEventType.FOUNTAIN
    assert m.hp == m.max_hp

    # Poison fountain
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_POISON)
    ev_pois = state.drink_fountain(member_index=0)
    assert ev_pois.type == DungeonEventType.FOUNTAIN
    assert m.status == Status.POISONED

    # Cure fountain
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_CURE)
    ev_cure = state.drink_fountain(member_index=0)
    assert ev_cure.type == DungeonEventType.FOUNTAIN
    assert m.status == Status.GOOD

    # Acid fountain
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_ACID)
    hp_prev = m.hp
    ev_acid = state.drink_fountain(member_index=0)
    assert ev_acid.type == DungeonEventType.FOUNTAIN
    assert m.hp == hp_prev - 25

    # Plain fountain
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_PLAIN)
    ev_plain = state.drink_fountain(member_index=0)
    assert not ev_plain.success


# --- Magical Marks & Orbs Tests ---

def test_marks_interaction(empty_dmap, test_party):
    m = test_party.members[0]
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)

    # Mark of Kings
    empty_dmap.set_tile(5, 5, 0, DungeonTile.MARK_KINGS)
    ev_kings = state.touch_mark(member_index=0)
    assert ev_kings.type == DungeonEventType.MARK
    assert m.marks[0] == 1

    # Mark of Fire
    empty_dmap.set_tile(5, 5, 0, DungeonTile.MARK_FIRE)
    ev_fire = state.touch_mark(member_index=0)
    assert ev_fire.type == DungeonEventType.MARK
    assert m.marks[1] == 1

    # Mark of Snake
    empty_dmap.set_tile(5, 5, 0, DungeonTile.MARK_SNAKE)
    ev_snake = state.touch_mark(member_index=0)
    assert ev_snake.type == DungeonEventType.MARK
    assert m.marks[2] == 1

    # Mark of Force
    empty_dmap.set_tile(5, 5, 0, DungeonTile.MARK_FORCE)
    ev_force = state.touch_mark(member_index=0)
    assert ev_force.type == DungeonEventType.MARK
    assert m.marks[3] == 1


def test_orb_interaction(empty_dmap, test_party):
    m = test_party.members[0]
    str_before = m.strength
    empty_dmap.set_tile(5, 5, 0, DungeonTile.ORB)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)

    ev_orb = state.touch_orb(member_index=0)
    assert ev_orb.type == DungeonEventType.ORB
    assert m.strength == str_before + 5
    assert ev_orb.damage == 50


# --- Chests Tests ---

def test_open_chest(empty_dmap, test_party):
    empty_dmap.set_tile(5, 5, 0, DungeonTile.CHEST)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)

    gold_before = test_party.gold
    ev = state.open_chest(member_index=0, disarm=True)
    assert ev.type == DungeonEventType.CHEST
    assert test_party.gold > gold_before
    # Chest replaced with NOTHING
    assert empty_dmap.get_tile(5, 5, 0) == DungeonTile.NOTHING


# --- Combat Encounter & Torch Mechanics ---

def test_random_combat_encounter(empty_dmap, asset_mgr, test_party):
    import random
    rng = random.Random(42)
    state = DungeonState(
        empty_dmap,
        start_x=5,
        start_y=5,
        start_z=3,
        start_dir=Direction.NORTH,
        party=test_party,
        asset_manager=asset_mgr,
        rng=rng,
    )
    # Force combat check
    encounter = state._check_random_encounter()
    assert encounter is None or hasattr(encounter, "name")

    # Force creature pick
    cr = state._pick_dungeon_creature()
    assert cr is not None
    assert cr.level <= state.z + 1
    assert cr.name != ""


def test_torch_lighting_and_consumption(empty_dmap, test_party):
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    assert state.torch_rounds == 0

    # Light torch from inventory
    torches_before = test_party.members[0].torches
    ok = state.light_torch(duration=10)
    assert ok
    assert state.torch_rounds == 10
    assert test_party.members[0].torches == torches_before - 1

    # Move forward consumes 1 round
    state.move_forward()
    assert state.torch_rounds == 9
    assert test_party.torch_duration == 9

    # Spell light
    state.cast_light_spell(duration=30)
    assert state.light_spell
    assert state.torch_rounds == 30


def test_misty_writings_and_time_lord(empty_dmap):
    empty_dmap.set_tile(5, 4, 0, DungeonTile.MISTY_WRITINGS)
    empty_dmap.set_tile(5, 3, 0, DungeonTile.TIME_LORD)

    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, random_encounters=False)

    ev_writings = state.move_forward()
    assert ev_writings.type == DungeonEventType.MESSAGE
    assert "Misty Writings" in ev_writings.message

    ev_tl = state.move_forward()
    assert ev_tl.type == DungeonEventType.MESSAGE
    assert "Time Lord" in ev_tl.message


def test_door_rendering_and_traversal(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()

    # Front door at (5, 4), left door at (4, 5), right door at (6, 5)
    empty_dmap.set_tile(5, 4, 0, DungeonTile.DOOR)
    empty_dmap.set_tile(4, 5, 0, DungeonTile.DOOR)
    empty_dmap.set_tile(6, 5, 0, DungeonTile.DOOR)

    # Render with front and side doors
    cam.render_wireframe(surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_rounds=50)
    non_black = sum(1 for x in range(176) for y in range(176) if surf.get_at((x, y))[:3] != COLOR_BLACK)
    assert non_black > 0

    # Door is traversable by player
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, random_encounters=False)
    ev = state.move_forward()
    assert ev.type == DungeonEventType.MOVED
    assert state.x == 5 and state.y == 4


def test_camera_validation_and_dng_alias(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()

    # dng alias support
    cam.render_wireframe(surf, dng=empty_dmap, x=5, y=5, z=0, dir=Direction.NORTH)
    assert surf.get_at((88, 88)) is not None

    # Error if neither dmap nor dng provided
    with pytest.raises(ValueError):
        cam.render_wireframe(surf)


def test_fallback_monsters_no_assets(empty_dmap):
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, asset_manager=None)
    cr = state._pick_dungeon_creature()
    assert cr is not None
    assert cr.level <= 1


def test_deepest_level_klimb_down(empty_dmap):
    empty_dmap.set_tile(5, 5, 7, DungeonTile.LADDER_DOWN)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=7)
    ev = state.klimb_down()
    assert ev.type == DungeonEventType.BLOCKED
    assert not ev.success

