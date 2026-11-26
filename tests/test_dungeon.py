"""Tests for the Stone first-person dungeon view and navigation."""
import random

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.aura import AuraType
from py_exodus.constants import Direction, Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException
from py_exodus.world.dungeon import (
    COLOR_BLACK,
    FOUNTAIN_TILES,
    MARK_TILES,
    DungeonCamera,
    DungeonEventType,
    DungeonState,
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
    return loader.load_dungeon_map("perinian.json")


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


# --- Rendering Tests (the Stone view) ---


def _view(dmap, x=5, y=5, d=Direction.NORTH, lit=True, creatures=None, cam=None, closeup=False):
    """One 176x176 frame from (x, y) on level 0."""
    pygame.init()
    surf = pygame.Surface((176, 176))
    (cam or DungeonCamera()).render_view(
        surf, dmap, x, y, 0, d, torch_lit=lit, creatures=creatures, closeup=closeup
    )
    return surf


def _diff_box(a, b):
    """Bounding box (x0, y0, x1, y1) of the pixels where two frames differ,
    or None when they are the same picture."""
    pts = [
        (px, py)
        for px in range(176)
        for py in range(176)
        if a.get_at((px, py)) != b.get_at((px, py))
    ]
    if not pts:
        return None
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _lit_pixels(surf):
    return sum(
        1 for px in range(176) for py in range(176) if surf.get_at((px, py))[:3] != COLOR_BLACK
    )


def test_dungeon_view_render(asset_mgr, perinian_dmap):
    pygame.init()
    surf = pygame.Surface((176, 176))
    state = DungeonState(perinian_dmap, start_x=1, start_y=1, start_z=0, start_dir=Direction.NORTH)
    cam = DungeonCamera(asset_mgr=asset_mgr)
    cam.render_view(surf, perinian_dmap, state.x, state.y, state.z, state.dir, torch_lit=True)
    assert _lit_pixels(surf) > 0


# --- Dungeon creatures in the view (the ``creatures`` argument) ---


def _wc(level=0):
    from types import SimpleNamespace

    return SimpleNamespace(
        creature=CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=level),
        x=5, y=4, level=0,
    )


def _creature_pixels(dmap, wc, **kw):
    """Where the monster changed the picture, or None when it did not show."""
    return _diff_box(_view(dmap, **kw), _view(dmap, creatures=[wc], **kw))


def test_creature_renders_in_3d_view(empty_dmap):
    box = _creature_pixels(empty_dmap, _wc())
    assert box is not None, "creature one tile ahead did not render in the 3D view"
    # A monster one tile ahead stands in the center of the corridor.
    assert box[0] < 88 < box[2]


def test_creature_uses_its_sprite_when_assets_are_loaded(asset_mgr, empty_dmap):
    bare = _view(empty_dmap, creatures=[_wc()])
    with_sprite = _view(empty_dmap, creatures=[_wc()], cam=DungeonCamera(asset_mgr=asset_mgr))
    assert _diff_box(bare, with_sprite) is not None


def test_creature_on_another_level_is_not_drawn(empty_dmap):
    wc = _wc()
    wc.level = 3
    assert _creature_pixels(empty_dmap, wc) is None


def test_creature_farther_is_smaller(empty_dmap):
    """A monster two tiles ahead must be visibly smaller than one one tile
    ahead (depth-scaled like the walls), so the party reads distance."""
    sizes = []
    for wy in (4, 3):
        wc = _wc()
        wc.y = wy
        box = _creature_pixels(empty_dmap, wc)
        assert box is not None, f"creature at distance {5 - wy} did not render"
        sizes.append((box[2] - box[0]) * (box[3] - box[1]))
    assert sizes[0] > sizes[1], "creature two tiles ahead not visibly smaller"


def test_creature_off_axis_positions_with_facing(empty_dmap):
    """A monster ahead and to the party's right shows in the right half,
    one to the left in the left half."""
    wc = _wc()
    wc.x, wc.y = 6, 3  # two ahead, one right of the party facing NORTH
    box = _creature_pixels(empty_dmap, wc)
    assert box is not None, "side monster did not render"
    assert box[0] > 88, "a monster to the east must appear in the right half"
    wc.x = 4
    box = _creature_pixels(empty_dmap, wc)
    assert box is not None and box[2] < 88


def test_creature_occluded_by_shallow_side_wall(empty_dmap):
    """A block at a shallower depth along the sightline hides a creature
    behind it in a side column."""
    empty_dmap.set_tile(6, 4, 0, DungeonTile.WALL)
    wc = _wc()
    wc.x = 6
    wc.y = 3  # depth=2, lateral=1 behind the wall at (6, 4)
    assert _creature_pixels(empty_dmap, wc) is None


def test_creature_beside_the_first_tile_stays_inside_the_view(empty_dmap):
    """At depth 1, two tiles off the axis is outside the view; one tile off
    shows at that edge."""
    wc = _wc()
    wc.x, wc.y = 7, 4
    assert _creature_pixels(empty_dmap, wc) is None
    wc.x = 6
    box = _creature_pixels(empty_dmap, wc)
    assert box is not None and 88 < box[0] and box[2] < 176
    wc.x = 4
    box = _creature_pixels(empty_dmap, wc)
    assert box is not None and 0 <= box[0] and box[2] < 88


def test_dungeon_view_all_directions(empty_dmap):
    for direction in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
        assert _lit_pixels(_view(empty_dmap, d=direction)) > 0, (
            f"Nothing rendered facing {direction.name}"
        )


def test_dungeon_render_torch_vs_dark(empty_dmap):
    """The light rule: no torch, no picture."""
    assert _lit_pixels(_view(empty_dmap, lit=False)) == 0
    assert _lit_pixels(_view(empty_dmap, lit=True)) > 0


@pytest.mark.parametrize("tile", [
    DungeonTile.CHEST, DungeonTile.FOUNTAIN_HEAL, DungeonTile.MARK_FIRE,
    DungeonTile.LADDER_UP, DungeonTile.TIME_LORD, DungeonTile.PIT_TRAP,
])
def test_no_torch_shows_nothing_ahead(empty_dmap, tile):
    """Dark is dark: nothing ahead and no monster."""
    empty_dmap.set_tile(5, 4, 0, tile)
    assert _lit_pixels(_view(empty_dmap, lit=False, creatures=[_wc()])) == 0


@pytest.mark.parametrize("tile", [
    DungeonTile.CHEST, DungeonTile.LADDER_UP, DungeonTile.TIME_LORD,
    DungeonTile.FOUNTAIN_HEAL, DungeonTile.MARK_FIRE,
])
def test_no_torch_shows_nothing_underfoot_outside_an_event(empty_dmap, tile):
    empty_dmap.set_tile(5, 5, 0, tile)
    assert _lit_pixels(_view(empty_dmap, lit=False)) == 0


_CLOSEUP_TILES = sorted(FOUNTAIN_TILES | MARK_TILES | {DungeonTile.TIME_LORD}, key=lambda t: t.value)


@pytest.mark.parametrize("tile", _CLOSEUP_TILES)
def test_closeup_shows_without_a_torch(empty_dmap, tile):
    """LairWare's ImageDisplay(5/6/8) has no gTorch check (UltimaDngn.c:
    212-318, UltimaMacIF.c:1980-2003): during the event the close-up is
    the same picture in the dark as with a torch."""
    cam = DungeonCamera()
    empty_dmap.set_tile(5, 5, 0, tile)
    lit = _view(empty_dmap, lit=True, cam=cam, closeup=True)
    dark = _view(empty_dmap, lit=False, cam=cam, closeup=True)
    assert _lit_pixels(dark) > 0
    assert _diff_box(lit, dark) is None
    # the event over, the dark is back
    assert _lit_pixels(_view(empty_dmap, lit=False, cam=cam)) == 0


def test_torchlight_reaches_six_tiles():
    """User ruling 2026-11-26: the light thins with distance but nothing the
    light rule shows goes dark. A wall two tiles off is brighter than one
    four off, and the sixth tile is faint but still there."""
    cam = DungeonCamera
    assert cam.MAX_DEPTH == 6
    assert cam.fog(0.5) == 1.0
    assert cam.fog(1.5) > cam.fog(3.5) > cam.fog(5.5) > cam.fog(6.0) > 0
    assert cam._shade(cam.FRONT, 5.5) != COLOR_BLACK
    assert min(cam._shade(cam.FRONT, 6.0)) >= 8


@pytest.mark.parametrize("tile", [
    DungeonTile.CHEST, DungeonTile.PIT_TRAP, DungeonTile.LADDER_DOWN,
    DungeonTile.FOUNTAIN_HEAL, DungeonTile.MARK_FIRE, DungeonTile.WALL,
])
@pytest.mark.parametrize("steps", [5, 6])
def test_tiles_five_and_six_ahead_are_drawn_faintly(tile, steps):
    """With a torch, a chest (pit, ladder...) five or six tiles ahead shows,
    dimmer than the same thing two tiles ahead; seven ahead is out of sight."""
    dmap = _flat_dmap()
    base = _view(dmap, 8, 8)
    dmap.set_tile(8, 8 - steps, 0, tile)
    far = _view(dmap, 8, 8)
    box = _diff_box(base, far)
    assert box is not None, f"{tile.name} {steps} ahead is not drawn"
    assert box[0] <= 88 <= box[2]
    brightest = max(
        sum(far.get_at((px, py))[:3])
        for px in range(box[0], box[2] + 1)
        for py in range(box[1], box[3] + 1)
        if far.get_at((px, py)) != base.get_at((px, py))
    )
    assert brightest > 0
    dmap.set_tile(8, 8 - steps, 0, DungeonTile.NOTHING)
    dmap.set_tile(8, 8 - 2, 0, tile)
    near = _view(dmap, 8, 8)
    nbox = _diff_box(base, near)
    assert max(
        sum(near.get_at((px, py))[:3])
        for px in range(nbox[0], nbox[2] + 1)
        for py in range(nbox[1], nbox[3] + 1)
    ) > brightest


def test_seven_tiles_ahead_is_out_of_sight():
    dmap = _flat_dmap()
    base = _view(dmap, 8, 8)
    dmap.set_tile(8, 8 - (DungeonCamera.MAX_DEPTH + 1), 0, DungeonTile.CHEST)
    assert _diff_box(base, _view(dmap, 8, 8)) is None


#: Every tile the old wireframe drew: blocks, doors and the floor features.
_DRAWN_TILES = [
    DungeonTile.WALL,
    DungeonTile.DOOR,
    DungeonTile.LOCKED_DOOR,
    DungeonTile.SECRET_DOOR,
    DungeonTile.LADDER_UP,
    DungeonTile.LADDER_DOWN,
    DungeonTile.LADDER_UP_DOWN,
    DungeonTile.CHEST,
    DungeonTile.PIT_TRAP,
    DungeonTile.TIME_LORD,
    *sorted(FOUNTAIN_TILES, key=lambda t: t.value),
    *sorted(MARK_TILES, key=lambda t: t.value),
]


@pytest.mark.parametrize("tile", _DRAWN_TILES)
def test_every_tile_the_wireframe_drew_is_drawn(empty_dmap, tile):
    """Each one changes the picture of an open corridor, one and two tiles
    ahead, in the middle of the view."""
    base = _view(empty_dmap)
    for steps in (1, 2):
        empty_dmap.set_tile(5, 5 - steps, 0, tile)
        box = _diff_box(base, _view(empty_dmap))
        assert box is not None, f"{tile.name} {steps} ahead is not drawn"
        assert box[0] <= 88 <= box[2]
        empty_dmap.set_tile(5, 5 - steps, 0, DungeonTile.FLOOR)


@pytest.mark.parametrize("tile", _DRAWN_TILES[4:])
def test_floor_features_show_with_and_without_sprites(asset_mgr, empty_dmap, tile):
    cam = DungeonCamera(asset_mgr=asset_mgr)
    base = _view(empty_dmap, cam=cam)
    empty_dmap.set_tile(5, 3, 0, tile)
    assert _diff_box(base, _view(empty_dmap, cam=cam)) is not None


@pytest.mark.parametrize("tile", [
    DungeonTile.WIND_TRAP, DungeonTile.GREMLINS, DungeonTile.MISTY_WRITINGS,
    DungeonTile.ORB, DungeonTile.NOTHING,
])
def test_tiles_the_wireframe_hid_stay_hidden(empty_dmap, tile):
    """The wind trap, the gremlins and the writings never showed: they look
    like open floor still."""
    base = _view(empty_dmap)
    empty_dmap.set_tile(5, 4, 0, tile)
    assert _diff_box(base, _view(empty_dmap)) is None


@pytest.mark.parametrize("spot", [(5, 4), (5, 3), (4, 4), (6, 4), (6, 3), (4, 2)])
def test_secret_door_renders_the_same_as_a_wall(empty_dmap, spot):
    """Ahead, on a side wall or through an opening: pixel for pixel a wall."""
    empty_dmap.set_tile(*spot, 0, DungeonTile.WALL)
    wall = _view(empty_dmap)
    empty_dmap.set_tile(*spot, 0, DungeonTile.SECRET_DOOR)
    assert _diff_box(wall, _view(empty_dmap)) is None


@pytest.mark.parametrize("spot", [(5, 4), (5, 3), (4, 4), (6, 4)])
def test_doors_look_like_doors(empty_dmap, spot):
    """A door and a locked door each differ from plain wall, ahead and on
    the side walls, and from each other."""
    pics = {}
    for tile in (DungeonTile.WALL, DungeonTile.DOOR, DungeonTile.LOCKED_DOOR):
        empty_dmap.set_tile(*spot, 0, tile)
        pics[tile] = _view(empty_dmap)
    assert _diff_box(pics[DungeonTile.WALL], pics[DungeonTile.DOOR]) is not None
    assert _diff_box(pics[DungeonTile.WALL], pics[DungeonTile.LOCKED_DOOR]) is not None
    assert _diff_box(pics[DungeonTile.DOOR], pics[DungeonTile.LOCKED_DOOR]) is not None


@pytest.mark.parametrize("tile", [
    DungeonTile.LADDER_UP, DungeonTile.LADDER_DOWN, DungeonTile.LADDER_UP_DOWN,
    DungeonTile.CHEST, DungeonTile.TIME_LORD,
])
def test_feature_under_the_party_is_drawn(empty_dmap, tile):
    """The wireframe drew what the party stands on; so does Stone."""
    base = _view(empty_dmap)
    empty_dmap.set_tile(5, 5, 0, tile)
    assert _diff_box(base, _view(empty_dmap)) is not None


def test_view_follows_the_map_when_it_changes(empty_dmap):
    """The camera keeps its last picture; a taken chest must still vanish."""
    cam = DungeonCamera()
    base = _view(empty_dmap, cam=cam)
    empty_dmap.set_tile(5, 3, 0, DungeonTile.CHEST)
    with_chest = _view(empty_dmap, cam=cam)
    assert _diff_box(base, with_chest) is not None
    empty_dmap.set_tile(5, 3, 0, DungeonTile.FLOOR)
    assert _diff_box(base, _view(empty_dmap, cam=cam)) is None
    # and a still frame is the same picture again
    assert _diff_box(base, _view(empty_dmap, cam=cam)) is None
    assert _diff_box(base, _view(empty_dmap, cam=cam, d=Direction.SOUTH, y=10)) is None


# --- Close-ups: standing on a fountain or a Mark ---


def test_closeup_pictures_are_lairwares_three():
    """ImageDisplay 5 (fountain), 6 (rod) and 8 (Time Lord), nothing else."""
    for tile in DungeonTile:
        kind = DungeonCamera.closeup_for(tile)
        if tile in FOUNTAIN_TILES:
            assert kind == "fountain"
        elif tile in MARK_TILES:
            assert kind == "rod"
        elif tile == DungeonTile.TIME_LORD:
            assert kind == "timelord"
        else:
            assert kind is None, tile.name


@pytest.mark.parametrize("tile", _CLOSEUP_TILES)
def test_closeup_replaces_the_corridor_only_when_asked(empty_dmap, tile):
    """While the screen asks for it the picture is the close-up: the same
    whichever way the party faces and whatever stands ahead. Not asked,
    the party sees the corridor though it still stands on the tile."""
    empty_dmap.set_tile(5, 5, 0, tile)
    north = _view(empty_dmap, closeup=True)
    assert _diff_box(north, _view(empty_dmap, d=Direction.EAST, closeup=True)) is None
    empty_dmap.set_tile(5, 4, 0, DungeonTile.WALL)
    assert _diff_box(north, _view(empty_dmap, closeup=True)) is None
    # standing there with no event: a corridor, which the wall ahead changes
    walled = _view(empty_dmap)
    assert _diff_box(north, walled) is not None
    empty_dmap.set_tile(5, 4, 0, DungeonTile.FLOOR)
    assert _diff_box(walled, _view(empty_dmap)) is not None


@pytest.mark.parametrize("tile", [
    DungeonTile.CHEST, DungeonTile.LADDER_UP, DungeonTile.FLOOR, DungeonTile.PIT_TRAP,
])
def test_no_closeup_on_other_tiles_even_when_asked(empty_dmap, tile):
    empty_dmap.set_tile(5, 5, 0, tile)
    assert _diff_box(_view(empty_dmap), _view(empty_dmap, closeup=True)) is None


def test_closeups_differ_by_kind_and_every_mark_gets_the_rod(empty_dmap):
    pics = {}
    for tile in (DungeonTile.FOUNTAIN_HEAL, DungeonTile.FOUNTAIN_POISON, DungeonTile.TIME_LORD,
                 *sorted(MARK_TILES, key=lambda t: t.value)):
        empty_dmap.set_tile(5, 5, 0, tile)
        pics[tile] = _view(empty_dmap, closeup=True)
    assert _diff_box(pics[DungeonTile.FOUNTAIN_HEAL], pics[DungeonTile.FOUNTAIN_POISON]) is None
    assert _diff_box(pics[DungeonTile.FOUNTAIN_HEAL], pics[DungeonTile.MARK_FIRE]) is not None
    assert _diff_box(pics[DungeonTile.TIME_LORD], pics[DungeonTile.MARK_FIRE]) is not None
    assert _diff_box(pics[DungeonTile.TIME_LORD], pics[DungeonTile.FOUNTAIN_HEAL]) is not None
    # The rod and its glow are the same picture on every Mark (only the
    # word under it changes): compare the rows above the word.
    for tile in MARK_TILES:
        box = _diff_box(pics[DungeonTile.MARK], pics[tile])
        assert box is None or box[1] >= 150, tile.name


def test_time_lord_closeup_uses_his_sprite_when_assets_are_loaded(asset_mgr, empty_dmap):
    empty_dmap.set_tile(5, 5, 0, DungeonTile.TIME_LORD)
    bare = _view(empty_dmap, closeup=True)
    drawn = _view(empty_dmap, closeup=True, cam=DungeonCamera(asset_mgr=asset_mgr))
    assert _diff_box(bare, drawn) is not None


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


class ZeroRNG(random.Random):
    """RNG whose randrange always returns the first masked direction."""

    def randrange(self, *args, **kwargs):  # noqa: D401
        return 0


# USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): ladders consume a turn
# (GBC ult3.c:1388-1429; LW free-action ladders disagree, no LW+NES
# agreement — GBC retained). The tests below pin the consumed-turn
# pipeline (moon clock + encounter roll) that K/D now shares with a
# normal dungeon move.

def _age_calls(party) -> list:
    """Count AgeChars calls: the dungeon's turn meter (LairWare dungeonmech,
    UltimaDngn.c:183-189, runs it once per command)."""
    calls: list = []
    real = party.age_chars
    party.age_chars = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    return calls


def test_ladder_consume_turn_moon_tick(empty_dmap, test_party):
    """A real climb ticks the turn like a normal move (one AgeChars call
    in _tick_turn)."""
    empty_dmap.set_tile(5, 5, 0, DungeonTile.LADDER_DOWN)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)
    calls = _age_calls(test_party)

    assert len(calls) == 0
    ev_down = state.klimb_down()
    assert ev_down.type == DungeonEventType.LADDER_DOWN
    assert len(calls) == 1

    empty_dmap.set_tile(5, 5, 1, DungeonTile.LADDER_UP)
    ev_up = state.klimb_up()
    assert ev_up.type == DungeonEventType.LADDER_UP
    assert len(calls) == 2


def test_ladder_no_turn_blocked_and_exit(empty_dmap, test_party):
    """A blocked K/D is InvalCmd and still ends in one dungeonmech pass
    (LairWare UltimaDngn.c:410-438, 183-209); the K-exit to the overworld
    is a map transition, not a dungeon move."""
    # No ladder here: BLOCKED, one tick.
    state = DungeonState(
        empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party,
        random_encounters=False,
    )
    calls = []
    real_tick = state._tick_turn
    state._tick_turn = lambda *a, **k: (calls.append(1), real_tick(*a, **k))[1]
    ev_blocked = state.klimb_up()
    assert ev_blocked.type == DungeonEventType.BLOCKED
    assert len(calls) == 1
    ages = _age_calls(test_party)

    # K at level 0 on a ladder up: exits to the surface, no tick.
    empty_dmap.set_tile(5, 5, 0, DungeonTile.LADDER_UP)
    ev_exit = state.klimb_up()
    assert ev_exit.type == DungeonEventType.EXIT_DUNGEON
    assert len(ages) == 0


class RemainingRng:
    """Stub RNG whose randrange(n) always returns a fixed remainder."""

    def __init__(self, remainder: int = 0) -> None:
        self.remainder = remainder

    def randrange(self, n: int) -> int:
        return min(self.remainder, n - 1)


class _ScriptRng:
    """randint answers from a script (LairWare RandNum is inclusive), then 0."""

    def __init__(self, *values: int) -> None:
        self.values = list(values)

    def randint(self, low: int, high: int) -> int:
        return self.values.pop(0) if self.values else low

    def randrange(self, n: int) -> int:
        return 0


def test_pit_trap(empty_dmap, test_party):
    """LairWare trap (UltimaDngn.c:285-294) and BombTrap (UltimaMain.c:
    1728-1740), ledger D-13: the first member's StealDisarmFail fails (255 >
    DEX + bonus) and each living member takes (RandNum(0, 255) & 0x77) + 8.
    No level change; the tile clears to NOTHING."""
    empty_dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    state = DungeonState(
        empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH,
        party=test_party, rng=_ScriptRng(255, 0x10, 0x01),
    )

    ev = state.move_forward()

    assert ev.type == DungeonEventType.PIT_TRAP
    assert ev.message == "Pit!"
    assert state.z == 0  # no level change
    assert test_party.dungeon_level == 0
    assert test_party.members[0].hp == test_party.members[0].max_hp - (0x10 + 8)
    assert test_party.members[1].hp == test_party.members[1].max_hp - (0x01 + 8)
    # Trap tile consumed/replaced with NOTHING
    assert empty_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING


def test_wind_trap(empty_dmap, test_party):
    """Java DungeonScreen.java:1080-1085 — wind sets isTorchOn = False and
    nothing else (torchduration is unused in Java). LairWare dungeonmech
    (UltimaDngn.c:280-283) runs it after the step's command (D-12)."""
    empty_dmap.set_tile(5, 4, 0, DungeonTile.WIND_TRAP)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    state.is_torch_on = True

    state.move_forward()
    ev = state.take_fixture()
    assert ev.type == DungeonEventType.WIND_TRAP
    assert state.is_torch_on is False
    assert not hasattr(state, "torch_rounds")


def test_gremlins_trap(empty_dmap, test_party):
    """LairWare gremlins (UltimaDngn.c:319-333), ledger D-14: a random slot
    loses one hundreds of food (110 -> 10); under 100 keeps it all."""
    empty_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0,
                         start_dir=Direction.NORTH, party=test_party,
                         rng=_ScriptRng(1))
    test_party.members[0].food = 90
    test_party.members[1].food = 110

    ev = state.move_forward()

    assert ev.type == DungeonEventType.GREMLINS
    assert ev.message == "Gremlins!"
    assert [m.food for m in test_party.members] == [90, 10]
    assert empty_dmap.get_tile(5, 4, 0) == DungeonTile.NOTHING

    empty_dmap.set_tile(5, 3, 0, DungeonTile.GREMLINS)
    state.rng = _ScriptRng(0)
    state.move_forward()
    assert [m.food for m in test_party.members] == [90, 10]  # under 100


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


def test_fountain_poison_status_only(empty_dmap, test_party):
    """GBC poison fountains inflict POISONED and NOTHING else.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): poison branch is
    status-only — no damage roll (GBC dungfunc.c:1277-1310 sets status 0->1
    and never touches HP).
    """
    m = test_party.members[0]
    m.hp = 40
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_POISON)

    ev = state.drink_fountain(member_index=0)
    assert ev.type == DungeonEventType.FOUNTAIN
    assert m.status == Status.POISONED
    assert m.hp == 40
    assert ev.damage == 0

    # Already-poisoned drinker: no effect, again no damage.
    ev2 = state.drink_fountain(member_index=0)
    assert ev2.success is False
    assert ev2.damage == 0
    assert m.hp == 40


def test_fountain_acid_flat_25_no_randomness(empty_dmap, test_party):
    """GBC acid fountains deal exactly 25 — never a random roll.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): flat 25 damage through
    apply_damage (GBC dungfunc.c:1277-1310; LairWare corroborates x&3 and
    acid=25).
    """
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=test_party)
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_ACID)

    for seed in (1, 2, 3, 99):
        member = test_party.members[0]
        member.status = Status.GOOD
        member.hp = 80
        random.seed(seed)
        ev = state.drink_fountain(member_index=0)
        assert ev.damage == 25
        assert member.hp == 80 - 25
        assert member.status == Status.GOOD


def test_fountain_acid_kills_solo_drinker(empty_dmap):
    """An acid fountain kill routes through the party-death chokepoint."""
    solo = Party(food=100, gold=0)
    c = Character("Solo", "M", Race.HUMAN, Profession.FIGHTER, hp=10, max_hp=10, torches=0)
    solo.add_member(c)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=solo)
    empty_dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_ACID)

    with pytest.raises(PartyDeathException):
        state.drink_fountain(member_index=0)
    assert solo.members[0].is_dead()


# --- Magical Marks & Orbs Tests ---

def test_marks_interaction(empty_dmap, test_party):
    m = test_party.members[0]
    # Alive through four 50-HP burns: a dead member takes no mark (D-26).
    m.max_hp = m.hp = 500
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


def test_generic_mark_typed_by_tile_x(empty_dmap, test_party):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): generic MARK (0x05)
    tiles type by tile x&3 in GBC order 0=Force, 1=Fire, 2=Snake, 3=Kings
    (GBC dungfunc.c:1355-1371), not by dungeon level z%4. x=6 -> Snake,
    x=15 -> Kings on the SAME level. Storage stays in the Java marks array
    order (0=Kings, 1=Fire, 2=Snake, 3=Force).
    """
    m = test_party.members[0]
    state = DungeonState(empty_dmap, start_x=6, start_y=5, start_z=0, party=test_party)

    empty_dmap.set_tile(6, 5, 0, DungeonTile.MARK)
    m.hp = m.max_hp
    ev_snake = state.touch_mark(member_index=0)
    assert ev_snake.type == DungeonEventType.MARK
    assert "Mark of the Snake" in ev_snake.message
    assert m.marks[2] == 1

    state.x = 15
    empty_dmap.set_tile(15, 5, 0, DungeonTile.MARK)
    m.hp = m.max_hp
    ev_kings = state.touch_mark(member_index=0)
    assert ev_kings.type == DungeonEventType.MARK
    assert "Mark of Kings" in ev_kings.message
    assert m.marks[0] == 1


def test_generic_mark_x0_is_force_on_every_level(empty_dmap, test_party):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): a generic MARK at x=0
    (x&3 == 0) grants Mark of Force on EVERY level — the type is
    depth-independent (GBC dungfunc.c:1355-1371)."""
    m = test_party.members[0]
    for z in range(8):
        state = DungeonState(empty_dmap, start_x=0, start_y=5, start_z=z, party=test_party)
        empty_dmap.set_tile(0, 5, z, DungeonTile.MARK)
        m.hp = m.max_hp  # refresh so repeated brandings do not kill the member
        m.marks = [0, 0, 0, 0]
        ev = state.touch_mark(member_index=0)
        assert ev.type == DungeonEventType.MARK
        assert "Mark of Force" in ev.message, f"level {z}: {ev.message}"
        assert m.marks[3] == 1, f"level {z}: marks={m.marks}"


def test_touch_mark_exact_zero_hp_is_dead(empty_dmap):
    """Item 45: touch_mark routes damage through apply_damage, so exact 0 HP
    is dead (LairWare HPSubtract `hp < 1`, UltimaMain.c:3254; user ruling Q18)."""
    party = Party(food=200, gold=100)
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=50, max_hp=100)
    party.add_member(c)
    # A second member lives, so the death is not a party wipe.
    party.add_member(Character("Two", "M", Race.HUMAN, Profession.FIGHTER, hp=50, max_hp=100))
    empty_dmap.set_tile(5, 5, 0, DungeonTile.MARK_KINGS)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=party)

    ev = state.touch_mark(member_index=0)

    assert ev.type == DungeonEventType.MARK
    assert party.members[0].marks[0] == 1
    assert party.members[0].hp == 0
    assert party.members[0].status == Status.DEAD
    assert party.members[0].is_dead()


def test_touch_mark_kills_solo_below_zero_raises_party_death(empty_dmap):
    """Item 45: touch_mark driving a solo member below 0 HP raises PartyDeathException."""
    party = Party(food=200, gold=100)
    c = Character("Solo", "M", Race.HUMAN, Profession.FIGHTER, hp=49, max_hp=100)
    party.add_member(c)
    empty_dmap.set_tile(5, 5, 0, DungeonTile.MARK_KINGS)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, party=party)

    with pytest.raises(PartyDeathException):
        state.touch_mark(member_index=0)

    assert party.members[0].marks[0] == 1
    assert party.members[0].hp == 0
    assert party.members[0].status == Status.DEAD
    assert party.is_party_dead()


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

    # LairWare dungeonmech (UltimaDngn.c:211-223, 334-338): the fixture
    # speaks after the command that put the party there (D-12).
    state.move_forward()
    ev_writings = state.take_fixture()
    assert ev_writings.type == DungeonEventType.MESSAGE
    assert "Misty Writings" in ev_writings.message

    state.move_forward()
    ev_tl = state.take_fixture()
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
        start_dir=Direction.NORTH,
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
    cam.render_view(surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True)
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
    cam.render_view(surf, dng=empty_dmap, x=5, y=5, z=0, dir=Direction.NORTH)
    assert surf.get_at((88, 88)) is not None

    # Error if neither dmap nor dng provided
    with pytest.raises(ValueError):
        cam.render_view(surf)


def test_deepest_level_klimb_down_clamps(empty_dmap):
    """There is no ninth level: a down ladder on the deepest level is
    refused (LairWare dDescend, UltimaDngn.c:410-422, has no bound, but no
    shipped level 8 holds a down ladder; batch D guard, D-02)."""
    empty_dmap.set_tile(5, 5, 7, DungeonTile.LADDER_DOWN)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=7)
    ev = state.klimb_down()
    assert ev.type == DungeonEventType.BLOCKED
    assert state.z == 7


# --- Renderer geometry locks (the Stone view) ---
#
# The eye is at the centre of the party tile with FOCAL 88 on the 176px view:
# the near face of the tile d steps ahead is at z = d - 0.5 and projects to
# the box 88 +/- 44 / z.  The pixels below sit inside a block, off its mortar.


def _flat_dmap() -> DungeonMap:
    """Empty 16x16 level: all NOTHING, party can see the full depth."""
    dmap = DungeonMap(id=98, name="GeomTest", width=16, height=16, levels=1)
    dmap.tiles = [[[DungeonTile.NOTHING] * 16 for _ in range(16)]]
    return dmap


def _render_geom(dmap, x, y, d=Direction.NORTH):
    return _view(dmap, x, y, d)


def _stone(z, side=False):
    cam = DungeonCamera
    return cam._shade(cam.SIDE if side else cam.FRONT, z)


def test_front_face_wall_two_ahead():
    """Wall 2 tiles ahead: its front face is at depth 1.5 and fills the box
    59..117; outside the box the eye sees past it."""
    dmap = _flat_dmap()
    open_view = _render_geom(dmap, 8, 8)
    dmap.set_tile(8, 6, 0, DungeonTile.WALL)  # party (8,8) facing NORTH
    surf = _render_geom(dmap, 8, 8)
    assert surf.get_at((70, 70))[:3] == _stone(1.5)
    assert surf.get_at((100, 110))[:3] == _stone(1.5)
    # above and beside the block: the same ceiling and floor as without it
    assert surf.get_at((80, 20)) == open_view.get_at((80, 20))
    assert surf.get_at((150, 120)) == open_view.get_at((150, 120))


def test_side_face_wall_one_east():
    """A block ahead and to the right shows its side face on the right:
    side-shaded, not front-shaded, so left and right read unambiguously."""
    dmap = _flat_dmap()
    dmap.set_tile(9, 7, 0, DungeonTile.WALL)  # one EAST, one NORTH of party
    surf = _render_geom(dmap, 8, 8)
    assert surf.get_at((150, 80))[:3] == _stone(0.5, side=True)
    assert surf.get_at((26, 80))[:3] != _stone(0.5, side=True)


def test_side_face_wall_one_west():
    """Mirror of the east case."""
    dmap = _flat_dmap()
    dmap.set_tile(7, 7, 0, DungeonTile.WALL)
    surf = _render_geom(dmap, 8, 8)
    assert surf.get_at((26, 80))[:3] == _stone(0.5, side=True)
    assert surf.get_at((150, 80))[:3] != _stone(0.5, side=True)


def test_front_door_panel_is_distinct():
    """A DOOR in the wall ahead paints wood in the middle of the face,
    reaching the floor; a plain WALL does not."""
    dmap = _flat_dmap()
    door = DungeonCamera._shade(DungeonCamera.DOOR, 1.5)
    dmap.set_tile(8, 6, 0, DungeonTile.DOOR)
    surf = _render_geom(dmap, 8, 8)
    assert surf.get_at((88, 100))[:3] == door
    assert surf.get_at((88, 62))[:3] != door  # stone above the lintel
    dmap.set_tile(8, 6, 0, DungeonTile.WALL)
    assert _render_geom(dmap, 8, 8).get_at((88, 100))[:3] != door


def test_opening_reads_different_from_wall():
    """A side opening is a real gap: where the wall's side face would be,
    the eye sees on into the side passage."""
    dmap = _flat_dmap()
    for gx in range(16):
        dmap.set_tile(gx, 0, 0, DungeonTile.WALL)
    dmap.set_tile(7, 7, 0, DungeonTile.WALL)
    surf_wall = _render_geom(dmap, 8, 8)
    dmap.set_tile(7, 7, 0, DungeonTile.NOTHING)  # swap the wall for an opening
    surf_open = _render_geom(dmap, 8, 8)
    assert surf_wall.get_at((26, 80))[:3] == _stone(0.5, side=True)
    assert surf_open.get_at((26, 80))[:3] != _stone(0.5, side=True)
    # and a chest standing in the side passage shows through the gap only
    dmap.set_tile(7, 6, 0, DungeonTile.CHEST)
    assert _diff_box(surf_open, _render_geom(dmap, 8, 8)) is not None
    dmap.set_tile(7, 7, 0, DungeonTile.WALL)
    assert _diff_box(surf_wall, _render_geom(dmap, 8, 8)) is None


def test_front_face_occludes_deeper_geometry():
    """The wall ahead hides what is behind it: a chest one tile past it
    changes nothing."""
    dmap = _flat_dmap()
    dmap.set_tile(8, 6, 0, DungeonTile.WALL)
    surf = _render_geom(dmap, 8, 8)
    dmap.set_tile(8, 5, 0, DungeonTile.CHEST)
    assert _diff_box(surf, _render_geom(dmap, 8, 8)) is None


def test_distant_walls_are_darker():
    """A wall four tiles ahead is the same stone, dimmer than one two ahead."""
    dmap = _flat_dmap()
    dmap.set_tile(8, 4, 0, DungeonTile.WALL)
    far_col = _render_geom(dmap, 8, 8).get_at((86, 86))[:3]
    assert far_col == _stone(3.5)
    assert (0, 0, 0) < far_col < _stone(1.5)


# --- Task 24: GBC finite torch durations --------------------------------
# USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): finite torch durations
# (GBC dungfun2.c:852-853,962,1128,1168-1191; dungfunc.c:719-734; LW
# UltimaDngn.c:282,192-194). `torchtime` (0-255) replaces the boolean
# internals; `is_torch_on` stays as a boolean alias for the screen reads.


def _torch_state(empty_dmap, test_party, heading=Direction.EAST):
    return DungeonState(
        empty_dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=heading,
        party=test_party,
    )


def test_ignite_consumes_one_torch_and_sets_255(empty_dmap, test_party):
    """GBC dungfun2.c:1168-1191 (doignite): torches-- , then the counter
    loads 255 (the port's lightnum)."""
    state = _torch_state(empty_dmap, test_party)
    state.party.members[0].torches = 5
    assert state.ignite() is True
    assert state.party.members[0].torches == 4
    assert state.torchtime == 255
    assert state.is_torch_on is True


def test_ignite_with_no_torches_fails(empty_dmap, test_party):
    state = _torch_state(empty_dmap, test_party)
    for m in state.party.members:
        m.torches = 0
    assert state.ignite() is False
    assert state.torchtime == 0
    assert state.is_torch_on is False


def test_torchtime_decrements_per_consumed_turn(empty_dmap, test_party):
    """GBC dungfunc.c:719-734 — torchtime-- once per consumed dungeon turn."""
    state = _torch_state(empty_dmap, test_party)
    state.torchtime = 255
    state.move_forward()
    assert state.torchtime == 254
    state.move_forward()
    assert state.torchtime == 253


def test_blocked_move_still_burns_torchtime(empty_dmap, test_party):
    """A blocked move still consumes a turn (Java finishTurn runs
    DungeonScreen.java:1052-1076) — the counter follows."""
    state = _torch_state(empty_dmap, test_party, heading=Direction.NORTH)
    state.torchtime = 140
    state.move_forward()  # (5, 4) is a WALL in the hulled map
    assert state.torchtime == 139


def test_torchtime_1_goes_dark_after_next_move(empty_dmap, test_party):
    state = _torch_state(empty_dmap, test_party)
    state.torchtime = 1
    state.move_forward()
    assert state.torchtime == 0
    assert state.is_torch_on is False


def test_wind_trap_sets_torchtime_to_0(empty_dmap, test_party):
    """GBC dungfunc.c:719-734 — strange winds load the counter to 0; the
    view then renders dark through the unchanged screen lighting read."""
    empty_dmap.set_tile(5, 4, 0, DungeonTile.WIND_TRAP)
    state = _torch_state(empty_dmap, test_party, heading=Direction.NORTH)
    state.torchtime = 140
    state.move_forward()
    ev = state.take_fixture()  # dungeonmech after the step (D-12)
    assert ev.type == DungeonEventType.WIND_TRAP
    assert state.torchtime == 0
    assert state.is_torch_on is False


def test_torch_save_round_trip_new_field(empty_dmap, test_party):
    """New saves carry the counter under `torchtime`."""
    state = _torch_state(empty_dmap, test_party)
    state.torchtime = 137
    data = state.torch_save_data()
    assert data == {"torchtime": 137}
    fresh = _torch_state(empty_dmap, test_party)
    fresh.apply_torch_state(data)
    assert fresh.torchtime == 137
    assert fresh.is_torch_on is True


def test_torch_load_maps_old_boolean_saves(empty_dmap, test_party):
    """Old boolean saves (Java `isTorchOn`) map: True -> 255, False -> 0."""
    state = _torch_state(empty_dmap, test_party)
    state.apply_torch_state({"is_torch_on": True})
    assert state.torchtime == 255
    state.apply_torch_state({"is_torch_on": False})
    assert state.torchtime == 0
    assert state.is_torch_on is False


# --- Dungeon meal cadence: LairWare dungeonmech (UltimaDngn.c:183-189)
# runs AgeChars after every dungeon command; with Party[3] = 1 it acts every
# 4th call (ledger D-01, user ruling 2026-11-25). No move is counted.


class TestDungeonMealCadence:
    @pytest.fixture
    def state(self, empty_dmap, test_party):
        return DungeonState(
            empty_dmap,
            start_x=6,
            start_y=6,
            start_z=0,
            start_dir=Direction.NORTH,
            party=test_party,
            random_encounters=False,
        )

    def test_meal_cadence_underground_carries_the_residual(self, state):
        """Underground cadence: AgeChars acts on every 4th dungeon command
        (the first included), 40 of the pool each. EatFood carries the
        residual (UltimaMisc.c:1472-1474; a ration is 396 of the pool, 9.9
        ticks), so after the first crossing (0 - 40 + 396 = 356) the next
        comes 9 ticks (36 commands) later."""
        m = state.party.members[0]
        m.submorsels = 0
        state._tick_turn()  # tick 1 crosses: -40 + 396
        assert m.submorsels == 356
        assert m.food == 149
        for _ in range(35):  # calls 2-36: ticks on 5, 9, ..., 33
            state._tick_turn()
        assert m.submorsels == 356 - 8 * 40  # 36 left
        assert m.food == 149
        state._tick_turn()  # call 37 = tick 10: the next ration
        assert m.submorsels == 36 - 40 + 396
        assert m.food == 148

    def test_dungeon_tick_does_not_increment_party_moves(self, state):
        state._tick_turn()
        assert state.party.moves == 0


    def test_starvation_crossing_wipes_party_through_dungeon_tick(
        self, empty_dmap
    ):
        """A food-0 member at a dungeon meal crossing takes the 5 HP blow
        through apply_damage; a wiped party leaves is_party_dead() True —
        the tick swallows PartyDeathException the same way the aura pass
        does, and the screen's post-move check routes the wipe."""
        party = Party()
        for name in ("Hero", "Mage"):
            char = Character(
                name, "M", Race.HUMAN, Profession.FIGHTER, hp=4, max_hp=100
            )
            char.food = 0
            char.submorsels = 9
            party.add_member(char)
        dungeon_state = DungeonState(
            empty_dmap,
            start_x=6,
            start_y=6,
            start_z=0,
            start_dir=Direction.NORTH,
            party=party,
            random_encounters=False,
        )
        dungeon_state._tick_turn()
        assert party.is_party_dead()

    def test_quickness_does_not_freeze_dungeon_meals(self, state):
        """LairWare (ledger T-13): stopped time is read only by FinishAll and
        combat, so AgeChars in dungeonmech (UltimaDngn.c:188) eats and
        starves on, and the dungeon step does not count the stop down."""
        m = state.party.members[0]
        m.submorsels = 9
        m.food = 0
        state.party.aura.set(AuraType.QUICKNESS, 5)
        state._tick_turn()
        assert m.submorsels == 0
        assert m.hp == 95
        assert state.party.aura.get_duration() == 5

    def test_age_chars_matches_end_turn_without_the_move_counter(
        self,
    ):
        """Party.age_chars(sosaria=False) alone reproduces
        end_turn(sosaria=False) off Sosaria: same tick, no move count."""
        via_end_turn = Party()
        via_end_turn.add_member(
            Character("A", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100)
        )
        via_end_turn.add_member(
            Character("B", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100)
        )
        via_end_turn.members[1].submorsels = 10
        via_end_turn.end_turn(sosaria=False)

        via_meals = Party()
        via_meals.add_member(
            Character("A", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100)
        )
        via_meals.add_member(
            Character("B", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100)
        )
        via_meals.members[1].submorsels = 10
        via_meals.age_chars(sosaria=False)

        for m1, m2 in zip(via_end_turn.members, via_meals.members):
            assert m1.food == m2.food
            assert m1.submorsels == m2.submorsels
            assert m1.hp == m2.hp
        assert via_meals.moves == 0


def test_dungeon_entry_prints_lairware_enter_dungeon(pygame_setup, asset_mgr, test_party, empty_dmap):
    """LairWare Enter (UltimaMain.c:1424-1434): "Enter dungeon!" for every
    dungeon, loaded, injected or without assets (user ruling 2026-11-25;
    replaces the port's "Entering <label>!")."""
    for scr in (
        DungeonScreen(party=test_party, map_id=15, asset_mgr=asset_mgr),
        DungeonScreen(party=test_party, dungeon_map=empty_dmap, asset_mgr=asset_mgr),
        DungeonScreen(party=test_party, map_id=15, asset_mgr=None),
        DungeonScreen(party=test_party, dungeon_map=DungeonMap(id=None, name="X"), asset_mgr=asset_mgr),
    ):
        assert scr.text_log.history == ["Enter dungeon!"]


def test_dungeon_climb_out_logs_exit_message_once(pygame_setup, asset_mgr, test_party, empty_dmap):
    """Item 48: climbing out of a dungeon at z=0 logs the exit line exactly once."""
    empty_dmap.set_tile(1, 1, 0, DungeonTile.LADDER_UP)
    screen = DungeonScreen(
        party=test_party,
        dungeon_map=empty_dmap,
        asset_mgr=asset_mgr,
        start_x=1,
        start_y=1,
        start_z=0,
    )

    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_k))

    assert screen.is_finished is True
    joined = " ".join(" ".join(screen.text_log.history).split())
    assert joined.count("You climb out of the dungeon to the surface!") == 1
    assert screen.text_log.history.count("You climb out of the dungeon to the surface!") == 1


def test_spell_exit_uses_java_map_label(asset_mgr, test_party):
    """Item 35: DungeonState.spell_exit logs MAP_ID_TO_LABEL ('Leaving Dardin's Pit!'),
    falling back to dmap.name for custom/unmapped ids."""
    from py_exodus.world.loader import MapLoader

    dardin_map = MapLoader(asset_mgr).load_map(15)
    state = DungeonState(dmap=dardin_map, party=test_party)
    ev = state.spell_exit()
    assert ev.message == "Leaving Dardin's Pit!"
    assert "Leaving DARDIN" not in ev.message

    custom_map = DungeonMap(id=99, name="Custom", width=16, height=16, levels=1)
    custom_state = DungeonState(dmap=custom_map, party=test_party)
    custom_ev = custom_state.spell_exit()
    assert custom_ev.message == "Leaving Custom!"


@pytest.mark.parametrize("tile", sorted(
    __import__("py_exodus.world.dungeon", fromlist=["FOUNTAIN_TILES"]).FOUNTAIN_TILES, key=lambda t: t.value
))
def test_every_fountain_tile_is_drawn_as_a_fountain(empty_dmap, tile):
    """One fountain set (dungeon.FOUNTAIN_TILES, fix round 1): the camera
    draws each of them as the same fountain, FOUNTAIN_UNTYPED included."""
    empty_dmap.set_tile(5, 4, 0, DungeonTile.FOUNTAIN_HEAL)
    heal = _view(empty_dmap)
    empty_dmap.set_tile(5, 4, 0, tile)
    assert _diff_box(heal, _view(empty_dmap)) is None
    empty_dmap.set_tile(5, 4, 0, DungeonTile.FLOOR)
    assert _diff_box(heal, _view(empty_dmap)) is not None
