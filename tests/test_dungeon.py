"""Tests for 3D wireframe dungeon corridor renderer and navigation."""
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
    from types import SimpleNamespace

    return SimpleNamespace(
        creature=CreatureDef(id=10, name="Orc", tile="orc", basehp=30, level=level),
        x=5, y=4, level=0,
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


def test_creature_occluded_by_shallow_side_wall(empty_dmap):
    """A solid wall at a shallower depth along the sightline occludes a
    creature behind it in a side column."""
    pygame.init()
    cam = DungeonCamera()
    surf = pygame.Surface((176, 176))
    empty_dmap.set_tile(6, 4, 0, DungeonTile.WALL)
    wc = _wc()
    wc.x = 6
    wc.y = 3  # depth=2, lateral=1 behind wall at (6, 4)
    cam.render_wireframe(
        surf, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
        creatures=[wc],
    )
    assert _creature_pixels(surf) is None


def test_creature_depth1_off_axis_clipping(empty_dmap):
    """At depth=1, |lateral|>=2 is outside the viewport and skipped;
    |lateral|==1 is clamped within [0, 176)."""
    pygame.init()
    cam = DungeonCamera()

    # depth=1, lateral=2 -> outside horizontal viewport, skipped
    surf_far_lat = pygame.Surface((176, 176))
    wc_out = _wc()
    wc_out.x = 7
    wc_out.y = 4
    cam.render_wireframe(
        surf_far_lat, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
        creatures=[wc_out],
    )
    assert _creature_pixels(surf_far_lat) is None

    # depth=1, lateral=1 -> clamped within [0, 176) on right half
    surf_right = pygame.Surface((176, 176))
    wc_r = _wc()
    wc_r.x = 6
    wc_r.y = 4
    cam.render_wireframe(
        surf_right, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
        creatures=[wc_r],
    )
    box_r = _creature_pixels(surf_right)
    assert box_r is not None
    assert 88 < box_r[0] and box_r[2] < 176

    # depth=1, lateral=-1 -> clamped within [0, 176) on left half
    surf_left = pygame.Surface((176, 176))
    wc_l = _wc()
    wc_l.x = 4
    wc_l.y = 4
    cam.render_wireframe(
        surf_left, empty_dmap, 5, 5, 0, Direction.NORTH, torch_lit=True,
        creatures=[wc_l],
    )
    box_l = _creature_pixels(surf_left)
    assert box_l is not None
    assert 0 <= box_l[0] and box_l[2] < 88


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
    assert dark_pixels == 0
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


class _GbcPitRng:
    """Stub RNG for the GBC pit rolls.

    randrange(100) always returns 99 so the dex + 25 >= randrange(100) evade
    fails at dex 0 (25 < 99); randint(a, b) always returns its high bound so
    the damage roll lands.
    """

    def randrange(self, n: int) -> int:
        return min(99, n - 1)

    def randint(self, low: int, high: int) -> int:
        return high


def test_pit_trap(empty_dmap, test_party):
    """Pit! rolls a per-member dex evade, then rnd(dunglevel+1)<<3 damage.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): pit trap dex-evade +
    per-member rnd(level+1)<<3 (GBC dungfunc.c:1190-1232) — supersedes the
    Java LAVA fan-out this test asserted previously. No level change; the
    tile still clears to NOTHING.
    """
    empty_dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    for m in test_party.members:
        m.dex = 0
    state = DungeonState(
        empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH,
        party=test_party, rng=_GbcPitRng(),
    )

    ev = state.move_forward()

    assert ev.type == DungeonEventType.PIT_TRAP
    assert ev.message == "Pit!"
    assert state.z == 0  # no level change
    assert test_party.dungeon_level == 0
    # Evade failed for every member: randint(0, z+1) == 1 → (0+1)<<3 damage.
    assert test_party.members[0].hp == test_party.members[0].max_hp - 8
    assert test_party.members[1].hp == test_party.members[1].max_hp - 8
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
    """Gremlins drain 100 food from ONE random LIVING member (floor 0).

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): gremlins drain 100 food
    from one member (GBC dungfunc.c:1177-1189; LW corroborates) — supersedes
    the Java -2-per-member fan-out this test asserted previously.
    """
    empty_dmap.set_tile(5, 4, 0, DungeonTile.GREMLINS)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=test_party)
    test_party.members[0].food = 90
    test_party.members[1].food = 110
    foods_before = [m.food for m in test_party.members]

    ev = state.move_forward()

    assert ev.type == DungeonEventType.GREMLINS
    assert ev.message == "Gremlins!"
    drained = [
        i
        for i, m in enumerate(test_party.members)
        if m.food != foods_before[i]
    ]
    assert len(drained) == 1
    i = drained[0]
    assert test_party.members[i].food == max(0, foods_before[i] - 100)
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


def test_deepest_level_klimb_down_clamps(empty_dmap):
    """There is no ninth level: a down ladder on the deepest level is
    refused (LairWare dDescend, UltimaDngn.c:410-422, has no bound, but no
    shipped level 8 holds a down ladder; batch D guard, D-02)."""
    empty_dmap.set_tile(5, 5, 7, DungeonTile.LADDER_DOWN)
    state = DungeonState(empty_dmap, start_x=5, start_y=5, start_z=7)
    ev = state.klimb_down()
    assert ev.type == DungeonEventType.BLOCKED
    assert state.z == 7


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


def test_navigation_depth_darkening_and_clean_planes():
    """Open floor/ceiling planes have no noisy longitudinal seam lines, and
    distant terminating walls (s >= 3) are depth-darkened."""
    dmap = _flat_dmap()
    # Wall 4 tiles ahead (stop_depth=4, s=3) facing NORTH from (8, 8)
    dmap.set_tile(8, 4, 0, DungeonTile.WALL)
    surf = _render_geom(dmap, 8, 8)
    # Centre floor and ceiling have no longitudinal seam at x=88
    assert surf.get_at((88, 160))[:3] == (38, 38, 38)
    assert surf.get_at((88, 16))[:3] == CEILING_FILL
    # Distant front face at s=3 is darkened below FRONT_FILL (85, 85, 85)
    far_col = surf.get_at((88, 88))[:3]
    assert (0, 0, 0) < far_col < FRONT_FILL


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
    ev = state.move_forward()
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

    def test_meal_crosses_every_41_dungeon_moves(self, state):
        """Underground cadence: AgeChars acts on every 4th dungeon command
        (the first included), 40 of the pool each: a fresh 400 pool sits at
        0 after 40 commands (ten ticks) and crosses on the 41st (the 11th),
        spending one unit of food."""
        m = state.party.members[0]
        for _ in range(40):
            state._tick_turn()
        assert m.submorsels == 0
        assert m.food == 150
        state._tick_turn()
        assert m.submorsels == 400
        assert m.food == 149

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


def test_dungeon_entry_uses_java_map_label(pygame_setup, asset_mgr, test_party, empty_dmap):
    """Item 38: DungeonScreen logs Java MAP_ID_TO_LABEL ('Entering Dardin's Pit!'),
    and falls back to dungeon_map.name when an injected map has no label entry."""
    dardin = DungeonScreen(party=test_party, map_id=15, asset_mgr=asset_mgr)
    joined_dardin = " ".join(" ".join(dardin.text_log.history).split())
    assert "Entering Dardin's Pit!" in joined_dardin
    assert "Entering DARDIN" not in joined_dardin

    # Injected dungeon_map with id=99 and default map_id=14 must NOT leak Perinian Depths.
    injected = DungeonScreen(party=test_party, dungeon_map=empty_dmap, asset_mgr=asset_mgr)
    joined_injected = " ".join(" ".join(injected.text_log.history).split())
    assert "Entering TestDungeon!" in joined_injected
    assert "Perinian Depths" not in joined_injected

    # Fallback map when asset_mgr is None still uses map_id's Java label (not Sosaria).
    fallback_dardin = DungeonScreen(party=test_party, map_id=15, asset_mgr=None)
    joined_fallback = " ".join(" ".join(fallback_dardin.text_log.history).split())
    assert "Entering Dardin's Pit!" in joined_fallback
    assert "Sosaria" not in joined_fallback

    # Injected DungeonMap with default id=0 or id=None uses its own name.
    custom_default = DungeonScreen(
        party=test_party,
        dungeon_map=DungeonMap(name="CustomDefaultId"),
        asset_mgr=asset_mgr,
    )
    assert "Entering CustomDefaultId!" in " ".join(
        " ".join(custom_default.text_log.history).split()
    )
    custom_none = DungeonScreen(
        party=test_party,
        dungeon_map=DungeonMap(id=None, name="CustomNoneId"),
        asset_mgr=asset_mgr,
    )
    assert "Entering CustomNoneId!" in " ".join(
        " ".join(custom_none.text_log.history).split()
    )


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
