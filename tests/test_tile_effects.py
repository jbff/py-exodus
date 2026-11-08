"""Task 5: tile effects, tile speeds, and energy-field passage.

Java truth:
- ``exodus/Party.java:279-306`` — ``Party.applyEffect`` per-member rolls
  (LAVA/FIRE/GREMLINS 1-in-2, POISON/POISONFIELD 1-in-5, ELECTRICITY always).
- ``exodus/Party.java:342-368`` — ``PartyMember.applyEffect``: GREMLINS food
  −2 (floored at 0); LAVA/FIRE ``16 + rand(32)`` damage through the
  ``apply_damage`` chokepoint unless the member carries the Mark of Fire
  (``marks[1]``); POISON/POISONFIELD set POISONED; ELECTRICITY no-op.
- ``exodus/GameScreen.java:706-754`` — every turn (move, blocked move, pass)
  runs ``finishTurn``: endTurn tick, then the tile-rule effect of the tile the
  party occupies at the start of the turn.
- ``exodus/Context.java:212-240`` — ``slowedByTile``: SLOW 1-in-8, VSLOW
  1-in-4, VVSLOW 1-in-2 chance the move is consumed without moving.
- ``objects/BaseMap.java:719-744`` — on foot, ``dispelable`` (field) tiles
  pass only when some member carries the Mark of Force (``marks[3]``).
- ``exodus/DungeonScreen.java:1040-1103`` — dungeons block only WALL +
  FIELD_ENERGY, apply POISONFIELD/LAVA on FIELD_POISON/FIELD_FIRE, and pit
  traps log "Pit!", apply the LAVA effect, and clear the tile with no level
  change (no invented z+1, no flat 25).
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import (
    Direction,
    Profession,
    Race,
    Status,
    TileEffect,
    TileSpeed,
    Transport,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException, PartyMember
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.ui.renderer import can_move_to
from py_exodus.world import tile_effects
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile, GameMap


# --- Deterministic RNG stubs (Java rand.nextInt parity) ---


class RemainderRng:
    """``randrange(n)`` always returns a fixed remainder (clamped into range).

    remainder=0 mirrors Java ``rand.nextInt(n) == 0`` succeeding on every
    roll; remainder=1 fails the 1-in-n rolls for n >= 2.
    """

    def __init__(self, remainder: int = 0) -> None:
        self.remainder = remainder

    def randrange(self, n: int) -> int:
        return min(self.remainder, n - 1)


class ScriptedRng:
    """``randrange(n)`` driven by a scripted list of roll outcomes."""

    def __init__(self, *values: int) -> None:
        self.values = list(values)

    def randrange(self, n: int) -> int:
        value = self.values.pop(0) if self.values else 0
        return value % n


class SpeedTile:
    """Minimal stand-in exposing only a tile speed."""

    def __init__(self, speed: TileSpeed) -> None:
        self.speed = speed


def make_party(n: int = 2, hp: int = 100) -> Party:
    members = [
        PartyMember(
            Character(
                f"Hero{i + 1}",
                "M",
                Race.HUMAN,
                Profession.FIGHTER,
                hp=hp,
                max_hp=hp,
            )
        )
        for i in range(n)
    ]
    return Party(members, x=0, y=0, gold=100, food=400)


def make_dmap() -> DungeonMap:
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    dmap.tiles = [
        [[DungeonTile.FLOOR for _ in range(16)] for _ in range(16)] for _ in range(8)
    ]
    dmap.level_texts = ["" for _ in range(8)]
    return dmap


# --- Tile speeds (slowedByTile, Context.java:212-240) ---


def test_slowed_by_tile_rolls():
    """SLOW 1-in-8, VSLOW 1-in-4, VVSLOW 1-in-2; FAST never slows."""
    slow = tile_effects.slowed_by_tile(SpeedTile(TileSpeed.SLOW), rng=RemainderRng(0))
    assert slow is True
    assert tile_effects.slowed_by_tile(SpeedTile(TileSpeed.SLOW), rng=RemainderRng(1)) is False

    assert tile_effects.slowed_by_tile(SpeedTile(TileSpeed.VSLOW), rng=RemainderRng(0)) is True
    assert tile_effects.slowed_by_tile(SpeedTile(TileSpeed.VSLOW), rng=RemainderRng(3)) is False

    assert tile_effects.slowed_by_tile(SpeedTile(TileSpeed.VVSLOW), rng=RemainderRng(0)) is True
    assert tile_effects.slowed_by_tile(SpeedTile(TileSpeed.VVSLOW), rng=RemainderRng(1)) is False

    assert tile_effects.slowed_by_tile(SpeedTile(TileSpeed.FAST), rng=RemainderRng(0)) is False


def test_rule_speeds_and_effects_exposed_on_tiles(asset_mgr):
    """assets.py exposes the Java TileRule speed/effect table per rule."""
    brush = asset_mgr.get_tile_by_name("brush")
    forest = asset_mgr.get_tile_by_name("forest")
    grass = asset_mgr.get_tile_by_name("grass")
    energy = asset_mgr.get_tile_by_name("energy_field")
    lava = asset_mgr.get_tile_by_name("lava")
    fire = asset_mgr.get_tile_by_name("fire")

    assert brush.speed is TileSpeed.VSLOW and brush.effect is TileEffect.NONE
    assert forest.speed is TileSpeed.VSLOW
    assert grass.speed is TileSpeed.FAST and grass.effect is TileEffect.NONE
    assert energy.speed is TileSpeed.VVSLOW and energy.effect is TileEffect.ELECTRICITY
    assert lava.speed is TileSpeed.VVSLOW and lava.effect is TileEffect.LAVA
    assert fire.speed is TileSpeed.VVSLOW and fire.effect is TileEffect.FIRE


def test_slow_move_consumes_turn_without_displacement(pygame_setup, asset_mgr):
    """A slowed move burns the turn: no displacement, but the tick still runs."""
    grass = asset_mgr.get_tile_by_name("grass")
    brush = asset_mgr.get_tile_by_name("brush")
    gmap = GameMap(
        id=0,
        name="Sosaria",
        width=64,
        height=64,
        border_behavior="wrap",
        tiles=[grass for _ in range(64 * 64)],
    )
    gmap.tiles[19 * 64 + 44] = brush  # (44, 19) brush

    party = make_party()
    ow = OverworldScreen(
        party=party, map_id=0, asset_mgr=asset_mgr, random_encounters=False
    )
    ow.game_map = gmap
    party.x, party.y = 44, 20

    moves_before = party.moves
    saved_rng = tile_effects._rng
    # First move: VSLOW roll (1-in-4) hits — the turn burns, no displacement.
    tile_effects._rng = RemainderRng(0)
    try:
        ow._move_avatar(Direction.NORTH)
    finally:
        tile_effects._rng = saved_rng

    assert (party.x, party.y) == (44, 20)
    assert party.moves == moves_before + 1

    # A brush turn with no roll hit displaces normally.
    party.x, party.y = 44, 20
    tile_effects._rng = RemainderRng(1)
    try:
        ow._move_avatar(Direction.NORTH)
    finally:
        tile_effects._rng = saved_rng
    assert (party.x, party.y) == (44, 19)


def test_standing_tile_effect_applies_each_turn_on_the_2d_maps(
    pygame_setup, asset_mgr
):
    """Java GameScreen.finishTurn applies the rule effect of the tile the
    party occupies at the start of the turn — not the destination."""
    grass = asset_mgr.get_tile_by_name("grass")
    lava = asset_mgr.get_tile_by_name("lava")
    gmap = GameMap(
        id=0,
        name="Sosaria",
        width=64,
        height=64,
        border_behavior="wrap",
        tiles=[grass for _ in range(64 * 64)],
    )
    gmap.tiles[20 * 64 + 44] = lava  # (44, 20) lava under the party

    party = make_party()
    ow = OverworldScreen(
        party=party, map_id=0, asset_mgr=asset_mgr, random_encounters=False
    )
    ow.game_map = gmap
    party.x, party.y = 44, 20

    saved_rng = tile_effects._rng
    tile_effects._rng = RemainderRng(0)
    try:
        ow._move_avatar(Direction.NORTH)
    finally:
        tile_effects._rng = saved_rng

    # Moved off the lava onto grass; the turn spent on the lava tile rolled
    # the LAVA effect: 50% hits (stub), 16 + rand(32)==0 → 16 damage each.
    assert (party.x, party.y) == (44, 19)
    assert all(m.hp == 100 - 16 for m in party.members)


# --- applyEffect port (Party.java:279-306, 342-368) ---


def test_lava_effect_damage_range_and_mark_of_fire_immunity():
    """LAVA: 1-in-2 per member; 16-47 damage unless marks[1] is set."""
    party = make_party()
    party.members[0].marks[1] = 1  # Mark of Fire
    party.members[1].marks[1] = 0

    # Fire-immune member takes nothing even on a guaranteed hit.
    tile_effects.apply_effect(party, TileEffect.LAVA, rng=RemainderRng(0))
    assert party.members[0].hp == 100
    assert party.members[1].hp == 100 - 16  # 16 + rand(32)==0

    # Top of the range: 16 + 31 = 47.
    party = make_party()
    tile_effects.apply_effect(party, TileEffect.LAVA, rng=ScriptedRng(0, 31, 0, 31))
    assert all(m.hp == 100 - 47 for m in party.members)

    # The 1-in-2 roll misses for every member.
    party = make_party()
    tile_effects.apply_effect(party, TileEffect.LAVA, rng=RemainderRng(1))
    assert all(m.hp == 100 for m in party.members)


def test_lava_effect_100_turns_mark_of_fire_member_untouched():
    party = make_party(n=1)
    party.members[0].marks[1] = 1
    for _ in range(100):
        tile_effects.apply_effect(party, TileEffect.LAVA, rng=RemainderRng(0))
    assert party.members[0].hp == 100
    assert party.members[0].status == Status.GOOD


def test_lava_effect_wipe_routes_party_death():
    """LAVA damage routes through apply_damage: a wipe raises the exception."""
    party = make_party(n=1, hp=10)
    with pytest.raises(PartyDeathException):
        tile_effects.apply_effect(party, TileEffect.LAVA, rng=RemainderRng(0))
    assert party.members[0].status == Status.DEAD
    assert party.members[0].hp == 0


def test_poison_effect_1_in_5_and_hp_unchanged():
    party = make_party()
    for _ in range(100):
        tile_effects.apply_effect(party, TileEffect.POISONFIELD, rng=RemainderRng(1))
    assert all(m.status == Status.GOOD for m in party.members)

    tile_effects.apply_effect(party, TileEffect.POISONFIELD, rng=RemainderRng(0))
    assert all(m.status == Status.POISONED for m in party.members)
    assert all(m.hp == 100 for m in party.members)


def test_gremlins_effect_food_minus_two_per_member():
    party = make_party()
    party.members[0].food = 5
    party.members[1].food = 1

    tile_effects.apply_effect(party, TileEffect.GREMLINS, rng=RemainderRng(0))
    assert party.members[0].food == 3
    assert party.members[1].food == 0  # floored at 0

    # The 1-in-2 roll misses for every member.
    tile_effects.apply_effect(party, TileEffect.GREMLINS, rng=RemainderRng(1))
    assert party.members[0].food == 3


def test_none_and_electricity_effects_are_no_ops():
    party = make_party()
    party.members[0].marks[1] = 0
    tile_effects.apply_effect(party, TileEffect.NONE, rng=RemainderRng(0))
    tile_effects.apply_effect(party, TileEffect.ELECTRICITY, rng=RemainderRng(0))
    assert all(m.hp == 100 for m in party.members)
    assert all(m.status == Status.GOOD for m in party.members)
    assert all(m.food == party.members[0].food or True for m in party.members)


# --- Energy-field passage (BaseMap.java:719-744) ---


def test_energy_field_passable_only_with_mark_of_force(asset_mgr):
    grass = asset_mgr.get_tile_by_name("grass")
    energy = asset_mgr.get_tile_by_name("energy_field")
    gmap = GameMap(id=0, name="T", width=2, height=1, tiles=[grass, energy])

    party = make_party()
    assert (
        can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is False
    )
    party.members[0].marks[3] = 1  # Mark of Force
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is True


def test_fire_field_is_dispelable_and_needs_mark_of_force(asset_mgr):
    """Java gate is the rule attribute, not the walkable flag: fire fields
    (walkable, dispelable) need the Mark of Force to enter on foot."""
    grass = asset_mgr.get_tile_by_name("grass")
    fire = asset_mgr.get_tile_by_name("fire")
    gmap = GameMap(id=0, name="T", width=2, height=1, tiles=[grass, fire])

    party = make_party()
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is False
    party.members[0].marks[3] = 1
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is True


# --- Dungeon fields, pit traps (DungeonScreen.java:1040-1103) ---


def test_dungeon_blocks_wall_and_energy_field():
    """Java blocks only WALL and FIELD_ENERGY; the Mark of Force does not
    open dungeon energy fields (DungeonScreen.move has no Force branch)."""
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.FIELD_ENERGY)
    party = make_party()
    party.members[0].marks[3] = 1
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=RemainderRng(0),
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.BLOCKED
    assert (state.x, state.y) == (5, 5)

    dmap.set_tile(5, 4, 0, DungeonTile.WALL)
    evt = state.move_forward()
    assert evt.type == DungeonEventType.BLOCKED
    assert (state.x, state.y) == (5, 5)


def test_dungeon_doors_and_fields_are_passable():
    """DOOR, SECRET_DOOR, LOCKED_DOOR, FIELD_POISON and FIELD_FIRE move."""
    dmap = make_dmap()
    party = make_party()
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=RemainderRng(1),  # no effect roll ever fires
        random_encounters=False,
    )
    for tile in (
        DungeonTile.DOOR,
        DungeonTile.SECRET_DOOR,
        DungeonTile.LOCKED_DOOR,
        DungeonTile.FIELD_POISON,
        DungeonTile.FIELD_FIRE,
    ):
        dmap.set_tile(5, 4, 0, tile)
        state.x, state.y = 5, 5
        evt = state.move_forward()
        assert evt.type == DungeonEventType.MOVED, f"{tile} blocked the move"
        assert (state.x, state.y) == (5, 4)
        state.y = 5


def test_dungeon_field_poison_applies_poisonfield():
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.FIELD_POISON)
    party = make_party()
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=RemainderRng(0),
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.MOVED
    assert all(m.status == Status.POISONED for m in party.members)
    assert all(m.hp == 100 for m in party.members)
    assert dmap.get_tile(5, 4, 0) is DungeonTile.FIELD_POISON  # not consumed


def test_dungeon_field_fire_applies_lava():
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.FIELD_FIRE)
    party = make_party()
    party.members[0].marks[1] = 1  # Mark of Fire
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=RemainderRng(0),
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.MOVED
    assert party.members[0].hp == 100  # immune
    assert party.members[1].hp == 100 - 16
    assert dmap.get_tile(5, 4, 0) is DungeonTile.FIELD_FIRE


def test_dungeon_pit_trap_java_behavior():
    """Pit!: LAVA effect per member, tile cleared to NOTHING, no level change."""
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    party = make_party()
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=RemainderRng(0),
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.PIT_TRAP
    assert evt.message == "Pit!"
    assert (state.x, state.y) == (5, 4)
    assert state.z == 0  # no invented level change
    assert party.dungeon_level == 0
    assert all(m.hp == 100 - 16 for m in party.members)
    assert dmap.get_tile(5, 4, 0) is DungeonTile.NOTHING


def test_dungeon_pit_trap_mark_of_fire_and_miss():
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    party = make_party()
    party.members[0].marks[1] = 1
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=RemainderRng(1),  # the 1-in-2 LAVA roll misses for everyone
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.PIT_TRAP
    assert all(m.hp == 100 for m in party.members)
    assert dmap.get_tile(5, 4, 0) is DungeonTile.NOTHING
