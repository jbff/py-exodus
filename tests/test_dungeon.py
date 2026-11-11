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
    WanderingCreature,
    get_relative_offsets,
    turn_left_dir,
    turn_right_dir,
)
from py_exodus.entities.defs import CreatureDef
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import DungeonMap, DungeonTile
from py_exodus.screens.dungeon_screen import DungeonScreen


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


# --- Dungeon creatures in the 3D view (Java DungeonScreen renders the
# wandering-creature meshes approaching the party) ---


def _wc(level=0):
    return WanderingCreature(
        CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=level),
        5, 4, 0,
    )


def _creature_pixels(surf):
    """Bounding box (x0, y0, x1, y1) of the monster's drawn pixels in the
    central viewport, or None when it did not render."""
    yellowish = []
    for px in range(0, 176):
        for py in range(0, 176):
            col = surf.get_at((px, py))[:3]
            if col == (255, 255, 85):
                yellowish.append((px, py))
    if not yellowish:
        return None
    xs = [p[0] for p in yellowish]
    ys = [p[1] for p in yellowish]
    return (min(xs), min(ys), max(xs), max(ys))


def test_creature_renders_in_3d_view(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()
    cam.render_wireframe(
        surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
        creatures=[_wc()],
    )
    box = _creature_pixels(surf)
    assert box is not None, "creature one tile ahead did not render in the 3D view"
    # A monster one tile ahead stands in the center of the corridor.
    assert box[0] < 88 < box[2]


def test_creature_absent_from_3d_view_without_argument(empty_dmap):
    """No creatures argument — no creature pixels (view unchanged, so the
    geometry-lock baselines and conventions hold)."""
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()
    cam.render_wireframe(surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True)
    assert _creature_pixels(surf) is None


def test_creature_farther_is_smaller_and_high(empty_dmap):
    """A monster two tiles ahead must be visibly smaller than one one tile
    ahead (depth-scaled like the wall geometry), so the party reads distance."""
    pygame.init()
    cam = DungeonCamera()
    sizes = []
    for wy in (4, 3):
        surf = pygame.Surface((176, 176))
        wc = _wc()
        wc.y = wy
        cam.render_wireframe(
            surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
            creatures=[wc],
        )
        box = _creature_pixels(surf)
        assert box is not None, f"creature at distance {5 - wy} did not render"
        sizes.append((box[2] - box[0]) * (box[3] - box[1]))
    assert sizes[0] > sizes[1], "creature two tiles ahead not visibly smaller"


def test_creature_off_axis_positions_with_facing(empty_dmap):
    """A monster one tile ahead in the party's right-hand opening renders on
    the correct screen side (Java places the mesh at the world position)."""
    pygame.init()
    cam = DungeonCamera()
    surf = pygame.Surface((176, 176))
    wc = _wc()
    wc.x = 6  # one right of the party facing NORTH
    cam.render_wireframe(
        surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
        creatures=[wc],
    )
    box = _creature_pixels(surf)
    assert box is not None, "side monster did not render"
    assert box[0] > 88, "a monster to the east must appear in the right half"


def test_dungeon_wireframe_all_directions(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()

    for direction in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
        cam.render_wireframe(surf, empty_dmap, 5, 5, 0, direction, torch_lit=True)
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
    cam.render_wireframe(surf_dark, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=False)
    # Lit: 50 torch rounds
    cam.render_wireframe(surf_lit, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True)

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
        cam.render_wireframe(surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True)
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

class RemainingRng:
    """Stub RNG whose randrange(n) always returns a fixed remainder."""

    def __init__(self, remainder: int = 0) -> None:
        self.remainder = remainder

    def randrange(self, n: int) -> int:
        return min(self.remainder, n - 1)


def test_pit_trap(empty_dmap, test_party):
    """Pit! deals the LAVA tile effect per member; no level change; tile cleared.

    Java truth: DungeonScreen.checkTileAffects (DungeonScreen.java:1090-1095)
    applies TileEffect.LAVA, clears the tile to NOTHING and never changes
    level. The old z+1 and flat-25 behaviors were invented.
    """
    empty_dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    state = DungeonState(
        empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH,
        party=test_party, rng=RemainingRng(0),
    )

    ev = state.move_forward()

    assert ev.type == DungeonEventType.PIT_TRAP
    assert ev.message == "Pit!"
    assert state.z == 0  # no level change
    assert test_party.dungeon_level == 0
    # LAVA effect: 16 + rand(32)==0 → 16 damage to each living member.
    assert test_party.members[0].hp == test_party.members[0].max_hp - 16
    assert test_party.members[1].hp == test_party.members[1].max_hp - 16
    # Trap tile consumed/replaced with NOTHING
    assert empty_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING


def test_wind_trap(empty_dmap, test_party):
    """Java DungeonScreen.java:1080-1085 — wind sets isTorchOn = False and
    nothing else (torchduration is unused in Java)."""
    empty_dmap.set_tile(5, 4, 0, DungeonTile.WIND_TRAP)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    state.is_torch_on = True

    ev = state.move_forward()
    assert ev.type == DungeonEventType.WIND_TRAP
    assert state.is_torch_on is False
    assert not hasattr(state, "torch_rounds")


def test_gremlins_trap(empty_dmap, test_party):
    empty_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    test_party.food = 200

    ev = state.move_forward()
    # Java Party.applyEffect fan-out: food -2 per non-DEAD member, "Gremlins!".
    assert ev.type == DungeonEventType.GREMLINS
    assert ev.message == "Gremlins!"
    assert test_party.food == 200 - 2 * len(test_party.members)
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


def test_orb_removed(empty_dmap, test_party):
    """Kept-Divergence #2: orbs are gone entirely — no touch handler, no event
    type, and the ORB tile is plain scenery. See tests/test_dungeon_specials.py."""
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)
    assert not hasattr(state, "touch_orb")
    assert not hasattr(DungeonEventType, "ORB")


# --- Chests Tests ---

def test_open_chest(empty_dmap, test_party):
    empty_dmap.set_tile(5, 5, 0, DungeonTile.CHEST)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)

    gold_before = test_party.members[0].gold
    ev = state.open_chest(member_index=0, disarm=True)
    assert ev.type == DungeonEventType.CHEST
    # Java Party.getChestGold: rand(50) + rand(8) + 10 credited to the opener.
    assert ev.gold == test_party.members[0].gold - gold_before
    assert 10 <= ev.gold <= 66
    # Chest replaced with NOTHING
    assert empty_dmap.get_tile(5, 5, 0) == DungeonTile.NOTHING


# --- Combat Encounter & Torch Mechanics ---

def test_random_combat_encounter(empty_dmap, asset_mgr, test_party):
    """Task 13: the invented direct-ambush roll is replaced by persistent
    wandering creatures (see tests/test_dungeon_specials.py); the creature
    pool still honours the level/deepness rules."""
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
    for _ in range(30):
        cr = state._pick_dungeon_creature()
        assert cr is not None
        assert cr.level > 0
        assert cr.level <= state.z + 1
        assert cr.name != ""


def test_torch_boolean_toggle_model(empty_dmap, test_party):
    """Java DungeonScreen.java:81 + 988-1005 — the torch is one boolean.

    I with the torch out burns the first member's torches to light it; I
    with the torch lit just extinguishes it (no consumption, no expiry).
    Movement no longer decrements anything.
    """
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    assert state.is_torch_on is False
    assert not hasattr(state, "torch_rounds")

    # Light torch from inventory
    torches_before = test_party.members[0].torches
    state.is_torch_on = True
    test_party.members[0].torches -= 1
    assert test_party.members[0].torches == torches_before - 1

    # Move forward: no torch rounds to decrement
    state.move_forward()
    assert state.is_torch_on is True

    # Extinguish: no consumption
    state.is_torch_on = False
    assert test_party.members[0].torches == torches_before - 1

    # Spell light shares the same boolean (Java SpellUtil LORUM/LUMINAE)
    state.light_spell = True
    assert state.is_torch_on is True


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


class _AudioSpy:
    def __init__(self):
        self.played = []

    def play_sfx(self, name, volume=None):
        self.played.append(name)
        return True


@pytest.mark.parametrize(
    "tile, expected_sfx",
    [
        (DungeonTile.WIND_TRAP, "tornado"),  # Java Sounds.play(Sound.WIND)
        (DungeonTile.PIT_TRAP, "boom"),  # Sound.BOOM
        (DungeonTile.GREMLINS, "giggle"),  # Sound.GIGGLE
    ],
)
def test_walkover_trap_sounds_play(empty_dmap, test_party, tile, expected_sfx):
    """Java checkTileAffects (DungeonScreen.java:1080-1097) plays WIND / BOOM
    / GIGGLE as the trap fires; the port played the walk-over specials
    silently — the user heard and saw nothing on stepping onto the tile."""
    pygame.init()
    dmap = empty_dmap
    dmap.set_tile(5, 4, 0, tile)
    audio = _AudioSpy()
    screen = DungeonScreen(
        party=test_party,
        dungeon_map=dmap,
        audio=audio,
        start_x=5,
        start_y=5,
        start_z=0,
    )
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    assert expected_sfx in audio.played


def test_door_rendering_and_traversal(empty_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    cam = DungeonCamera()

    # Front door at (5, 4), left door at (4, 5), right door at (6, 5)
    empty_dmap.set_tile(5, 4, 0, DungeonTile.DOOR)
    empty_dmap.set_tile(4, 5, 0, DungeonTile.DOOR)
    empty_dmap.set_tile(6, 5, 0, DungeonTile.DOOR)

    # Render with front and side doors
    cam.render_wireframe(surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True)
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
    """Java getRandomDungeonInstance (CreatureSet.java:42-56) invents no
    fallback table: nothing eligible means no spawn (None)."""
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, asset_manager=None)
    assert state._pick_dungeon_creature() is None


def test_deepest_level_klimb_down_clamps(empty_dmap):
    """Java DungeonScreen.java:973-981 — D on a down-ladder increments
    currentLevel and only clamps when it exceeds DUNGEON_LVLS (8); a descent
    off the deepest playable grid is accepted at 8 (world-audit #23)."""
    empty_dmap.set_tile(5, 5, 7, DungeonTile.LADDER_DOWN)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=7)
    ev = state.klimb_down()
    assert ev.type == DungeonEventType.LADDER_DOWN
    assert state.z == 8



# --- Renderer geometry locks (2026-11-10 dungeon-render fix) ---
#
# Pixel-level regression checks for the projected wireframe renderer:
# a wall one corridor column ahead must paint its FRONT face in the centre
# region, a wall one tile EAST must paint its SIDE face along that screen
# edge, and doors must paint a distinct panel. Coordinates follow from
# DungeonCamera's pinhole projection (FOCAL 132.53 on the 176px viewport):

FRONT_FILL = (85, 85, 85)
SIDE_FILL = (55, 55, 55)
SHADOW_FILL = (25, 25, 25)
FLOOR_FILL = (38, 38, 38)
CEILING_FILL = (30, 30, 30)
SEAM = (120, 120, 120)
DOOR_CYAN = (0, 255, 255)


def _flat_dmap() -> DungeonMap:
    """Empty 16x16 level: all NOTHING, party can see the full depth."""
    dmap = DungeonMap(id=98, name="GeomTest", width=16, height=16, levels=1)
    dmap.tiles = [[[DungeonTile.NOTHING] * 16 for _ in range(16)]]
    return dmap


def _render_geom(dmap, x, y, d=Direction.NORTH):
    pygame.init()
    surf = pygame.Surface((176, 176))
    DungeonCamera().render_wireframe(surf, dmap, x, y, 0, d, torch_lit=True)
    return surf


def test_front_face_wall_two_ahead():
    """Wall 2 tiles ahead facing NORTH: its front face sits at depth 1.5,
    projecting to the box (44..132) — fill in the centre, shadow of the
    ceiling-box face above it, black past the box bounds."""
    dmap = _flat_dmap()
    dmap.set_tile(8, 6, 0, DungeonTile.WALL)  # party (8,8) facing NORTH
    surf = _render_geom(dmap, 8, 8)
    assert surf.get_at((80, 80))[:3] == FRONT_FILL
    assert surf.get_at((70, 70))[:3] == FRONT_FILL
    # rays above the wall's top edge hit the corridor ceiling before the
    # wall plane (java's floor/ceiling boxes tile the whole plane — no void)
    assert surf.get_at((80, 20))[:3] == CEILING_FILL
    # past the box on the far side: darkness before the box ring ends
    assert surf.get_at((150, 88))[:3] == (0, 0, 0)


def test_side_face_wall_one_east():
    """Wall 1 tile EAST of the party facing NORTH: its inner face at the
    corridor plane spans screen-left/right of the centre — side-shaded, not
    front-shaded, so left/right reading is unambiguous."""
    dmap = _flat_dmap()
    dmap.set_tile(9, 7, 0, DungeonTile.WALL)  # one EAST, one NORTH of party
    surf = _render_geom(dmap, 8, 8)
    # side strip on the right: fill at the screen edge of the wall plane
    strip = surf.get_at((130, 70))[:3]
    assert strip == SIDE_FILL
    # and the same wall is NOT painted as a front face in the centre column
    assert surf.get_at((80, 20))[:3] != FRONT_FILL


def test_side_face_wall_one_west():
    """Mirror of the east case: wall one WEST paints the left side strip."""
    dmap = _flat_dmap()
    dmap.set_tile(7, 8, 0, DungeonTile.WALL)  # adjacent, party's own column
    surf = _render_geom(dmap, 8, 8)
    assert surf.get_at((26, 70))[:3] == SIDE_FILL


def test_front_door_panel_is_distinct():
    """A DOOR on the terminating wall paints a cyan panel inside the front
    face box (Java door slab, DungeonScreen.java:574-589), unlike plain WALL."""
    dmap = _flat_dmap()
    dmap.set_tile(8, 6, 0, DungeonTile.DOOR)
    surf = _render_geom(dmap, 8, 8)
    cyan = 0
    for px in range(44, 133, 3):
        for py in range(44, 133, 3):
            if surf.get_at((px, py))[:3] == DOOR_CYAN:
                cyan += 1
    assert cyan > 0
    assert surf.get_at((88, 30))[:3] != DOOR_CYAN


def test_opening_reads_different_from_wall():
    """An opening where the wall-side strip would be leaves that region
    dark (side corridor), while the wall-side render paints the side fill."""
    dmap = DungeonMap(id=98, name="GeomTest2", width=16, height=16, levels=1)
    dmap.tiles = [[[DungeonTile.NOTHING] * 16 for _ in range(16)]]
    # enclose the level's north edge so the corridor terminates at depth 4
    for gx in range(16):
        dmap.set_tile(gx, 0, 0, DungeonTile.WALL)
    dmap.set_tile(7, 8, 0, DungeonTile.WALL)  # west wall, party column
    surf_wall = _render_geom(dmap, 8, 8)

    dmap.set_tile(7, 8, 0, DungeonTile.NOTHING)  # swap the wall for an opening
    surf_open = _render_geom(dmap, 8, 8)

    assert surf_wall.get_at((16, 70))[:3] == SIDE_FILL
    # through the opening the eye sees the side corridor's ceiling plane
    # (Java draws floor/ceiling boxes for every tile) — clearly darker
    assert surf_open.get_at((16, 70))[:3] == CEILING_FILL


def test_front_face_occludes_deeper_geometry():
    """The terminating front face occludes fixtures beyond it: a chest one
    tile past the wall paints no green anywhere."""
    dmap = _flat_dmap()
    dmap.set_tile(8, 6, 0, DungeonTile.WALL)
    dmap.set_tile(8, 5, 0, DungeonTile.CHEST)
    surf = _render_geom(dmap, 8, 8)
    for px in range(0, 176, 4):
        for py in range(0, 176, 4):
            assert surf.get_at((px, py))[:3] != (0, 255, 0)
