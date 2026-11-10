"""Task 5: tile effects, tile speeds, and energy-field passage.

Java truth:
- ``exodus/Party.java:279-283`` — ``Party.applyEffect`` fans out
  unconditionally: every non-DEAD member takes the effect (GREMLINS food −2
  clamped, LAVA/FIRE 16+rand(32) w/ Mark-of-Fire immunity, POISON sets
  status). This is what the standing tile-effect path uses.
- ``exodus/Party.java:285-306`` — the per-member ROLLED overload
  (1-in-2 FIRE/LAVA/GREMLINS, 1-in-5 POISON/POISONFIELD) is combat-only
  (CombatScreen.java:372); ported as ``apply_effect_rolled`` for Task 12.
- ``exodus/GameScreen.java:706-754`` — every turn (move, blocked move, pass)
  runs ``finishTurn``: endTurn tick, then the tile-rule effect of the tile the
  party occupies at the start of the turn.
- ``exodus/Context.java:212-240`` — ``slowedByTile``: SLOW 1-in-8, VSLOW
  1-in-4, VVSLOW 1-in-2 — but combat-creatures-only (CombatScreen.java:937);
  exploration movement is never slowed.
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


def test_exploration_movement_is_never_slowed():
    """Java exploration movement never rolls slowedByTile — its only caller
    is CombatScreen.java:937 (combat creatures). The 2D move paths contain
    no speed roll."""
    import inspect

    from py_exodus.screens import overworld, town

    src = inspect.getsource(overworld.OverworldScreen._move_avatar)
    assert "slowed_by_tile" not in src
    src_town = inspect.getsource(town.TownScreen._try_move)
    assert "slowed_by_tile" not in src_town


# --- Standing tile effect + pass turn (GameScreen.java:706-754, 624-628) ---


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

    # Moved off the lava onto grass; the turn spent on the lava tile applied
    # the LAVA effect unconditionally: 16 + rand(32)==0 → 16 damage each.
    assert (party.x, party.y) == (44, 19)
    assert all(m.hp == 100 - 16 for m in party.members)


def test_overworld_pass_turn_applies_standing_effect_and_consumes_turn(
    pygame_setup, asset_mgr
):
    """Java GameScreen.java:624-628: the pass key finishes the turn at the
    party's tile — endTurn tick plus the standing tile effect, no movement."""
    grass = asset_mgr.get_tile_by_name("grass")
    poison_field = grass.__class__(  # a walkable, rule-"poison" field tile
        index=200, name="poison_field", rule="poison"
    )
    gmap = GameMap(
        id=0,
        name="Sosaria",
        width=2,
        height=1,
        border_behavior="wrap",
        tiles=[poison_field, grass],
    )

    party = make_party()
    # Feed both members: Character defaults food to 0 and Party(food=400)
    # seeds only one member. With food > 0 the original-rules regen tick
    # (user-directed deviation 2026-11-10) never starves across the two
    # passes, and the poison tick below is the only HP loss.
    for m in party.members:
        m.food = 400
    ow = OverworldScreen(
        party=party, map_id=0, asset_mgr=asset_mgr, random_encounters=False
    )
    ow.game_map = gmap
    party.x, party.y = 0, 0

    moves_before = party.moves
    ow._pass_turn()
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))

    # Both passes consumed a turn without moving, and the unconditional
    # POISONFIELD fan-out (Party.java:279-283 — no 1-in-5 roll) poisoned
    # every non-DEAD member.
    assert (party.x, party.y) == (0, 0)
    assert party.moves == moves_before + 2
    assert all(m.status == Status.POISONED for m in party.members)
    # Original-rules poison tick (deviation 2026-11-10): the FIRST pass ran
    # its regen tick BEFORE the tile effect poisoned the party (no damage
    # that turn); the SECOND pass is a poisoned turn — "Every step the
    # character takes, lowers the character's hit level by one" — so each
    # member is −1 HP.
    assert all(m.hp == 99 for m in party.members)


def test_ambrosia_drains_at_the_10_interval(pygame_setup, asset_mgr):
    """Java Party.java:598-600: the 40-submorsel interval is Sosaria (0) and
    Exodus (2) only — Ambrosia (13) drains at 10. With 30 submorsels banked,
    a 10-per-move turn survives; a 40 turn crosses and takes the food."""
    def _screen_and_party(map_id: int):
        grass = asset_mgr.get_tile_by_name("grass")
        gmap = GameMap(
            id=map_id,
            name="Ambrosia" if map_id == 13 else "Sosaria",
            width=2,
            height=1,
            border_behavior="wrap",
            tiles=[grass, grass],
        )
        party = make_party()
        for m in party.members:
            m.submorsels = 30
        ow = OverworldScreen(
            party=party, map_id=map_id, asset_mgr=asset_mgr, random_encounters=False
        )
        ow.game_map = gmap
        party.x, party.y = 0, 0
        return ow, party

    ow, party = _screen_and_party(13)
    food_before = party.food
    ow._pass_turn()
    assert all(m.submorsels == 20 for m in party.members)
    assert party.food == food_before  # 10 drain: no crossing

    ow0, party0 = _screen_and_party(0)
    ow0._pass_turn()
    assert all(m.submorsels == 400 for m in party0.members)  # 40 drain: crossed, reset
    assert party0.food == food_before - len(party0.members)  # -1 food per member


def test_town_pass_turn_applies_standing_effect_and_consumes_turn(
    pygame_setup, asset_mgr
):
    """Town pass routes through the same _finish_turn flow."""
    from py_exodus.screens.town import TownScreen

    grass = asset_mgr.get_tile_by_name("grass")
    lava = grass.__class__(index=201, name="lava", rule="lava")
    gmap = GameMap(
        id=1, name="British", width=2, height=2, border_behavior="exit",
        tiles=[lava, grass, grass, grass],
    )

    party = make_party()
    tw = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr)
    tw.game_map = gmap
    tw.avatar_x, tw.avatar_y = 0, 0

    moves_before = party.moves
    saved_rng = tile_effects._rng
    tile_effects._rng = RemainderRng(0)
    try:
        tw.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    finally:
        tile_effects._rng = saved_rng

    assert (tw.avatar_x, tw.avatar_y) == (0, 0)
    assert party.moves == moves_before + 1
    # Unconditional LAVA fan-out: 16 + rand(32)==0 → 16 damage each.
    assert all(m.hp == 100 - 16 for m in party.members)


# --- applyEffect port (Party.java:279-283 + 342-368 unconditional;
#     Party.java:285-306 rolled, combat-only) ---


def test_lava_effect_damage_range_and_mark_of_fire_immunity():
    """LAVA via the unconditional fan-out: 16-47 damage unless marks[1]."""
    party = make_party()
    party.members[0].marks[1] = 1  # Mark of Fire
    party.members[1].marks[1] = 0

    tile_effects.apply_effect(party, TileEffect.LAVA)
    assert party.members[0].hp == 100

    # Top of the range: 16 + 31 = 47.
    party = make_party()
    party.members[0].marks[1] = 0
    party.members[1].marks[1] = 0
    tile_effects.apply_effect(party, TileEffect.LAVA, rng=ScriptedRng(31, 31))
    assert all(m.hp == 100 - 47 for m in party.members)


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


def test_poison_effect_unconditional_and_hp_unchanged():
    party = make_party()
    tile_effects.apply_effect(party, TileEffect.POISONFIELD)
    assert all(m.status == Status.POISONED for m in party.members)
    assert all(m.hp == 100 for m in party.members)


def test_gremlins_effect_food_minus_two_per_member():
    party = make_party()
    party.members[0].food = 5
    party.members[1].food = 1

    tile_effects.apply_effect(party, TileEffect.GREMLINS)
    assert party.members[0].food == 3
    assert party.members[1].food == 0  # floored at 0


def test_rolled_party_overload_keeps_the_java_dice():
    """Party.java:285-306 (combat-only) — 1-in-2 LAVA/GREMLINS, 1-in-5 POISON."""
    party = make_party()
    party.members[0].food = 5
    party.members[1].food = 5
    # RemainderRng(1): randrange(2) == 1 → the 1-in-2 roll misses everyone.
    tile_effects.apply_effect_rolled(party, TileEffect.GREMLINS, rng=RemainderRng(1))
    assert party.members[0].food == 5
    assert party.members[1].food == 5
    # randrange(2) == 0 → hits; 5 → −2 food, 1 → floored at 0.
    party.members[0].food = 5
    party.members[1].food = 1
    tile_effects.apply_effect_rolled(party, TileEffect.GREMLINS, rng=RemainderRng(0))
    assert party.members[0].food == 3
    assert party.members[1].food == 0

    # 1-in-5 POISONFIELD: RemainderRng(1) misses; RemainderRng(0) hits.
    party = make_party()
    tile_effects.apply_effect_rolled(party, TileEffect.POISONFIELD, rng=RemainderRng(1))
    assert all(m.status == Status.GOOD for m in party.members)
    tile_effects.apply_effect_rolled(party, TileEffect.POISONFIELD, rng=RemainderRng(0))
    assert all(m.status == Status.POISONED for m in party.members)

    # LAVA: the mark gate still applies; the miss leaves hp untouched.
    party = make_party()
    party.members[0].marks[1] = 1
    tile_effects.apply_effect_rolled(party, TileEffect.LAVA, rng=RemainderRng(0))
    assert party.members[0].hp == 100
    assert party.members[1].hp == 100 - 16
    party = make_party()
    tile_effects.apply_effect_rolled(party, TileEffect.LAVA, rng=RemainderRng(1))
    assert all(m.hp == 100 for m in party.members)


def test_none_and_electricity_effects_are_no_ops():
    party = make_party()
    party.members[0].food = 7
    party.members[1].food = 7
    party.members[0].marks[1] = 0
    tile_effects.apply_effect(party, TileEffect.NONE)
    tile_effects.apply_effect(party, TileEffect.ELECTRICITY)
    assert all(m.hp == 100 for m in party.members)
    assert all(m.status == Status.GOOD for m in party.members)
    assert all(m.food == 7 for m in party.members)


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
    # Feed both members (Character defaults food to 0; see the overworld
    # poison-field pass test) so the deviation tick neither starves nor
    # heals — poison is the only HP change on this turn.
    for m in party.members:
        m.food = 400
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
    # Original-rules poison tick (deviation 2026-11-10): the field poisons
    # on entry, then the move's tick runs — a poisoned turn is −1 HP.
    assert all(m.hp == 99 for m in party.members)
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


def test_dungeon_pit_trap_mark_of_fire_immune():
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
        rng=RemainderRng(1),  # rand(32)==1 → 17 damage without the mark
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.PIT_TRAP
    assert party.members[0].hp == 100  # Mark of Fire absorbs the pit
    assert party.members[1].hp == 100 - 17
    assert dmap.get_tile(5, 4, 0) is DungeonTile.NOTHING
