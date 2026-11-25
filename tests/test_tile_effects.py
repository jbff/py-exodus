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
  change (no invented z+1, no flat 25). Tasks 5-7 carry the port's GBC-rule
  deviations on top of this Java truth — notably the pit (Task 7): see the
  deviation comments in the pit tests below; ``tile_effects`` keeps the Java
  parity semantics for the 2D-map and chest callers.
"""
from __future__ import annotations

import random

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


class FixedRollRng:
    """Stub for the GBC pit-trap rolls (Task 7 deviation).

    ``randrange(100)`` always returns a fixed high remainder so a zero-dex
    member fails the ``dex + 25 >= randrange(100)`` evade; ``randint(a, b)``
    returns a fixed remainder inside the range for the damage roll.
    """

    def __init__(self, randrange_value: int = 99, randint_value: int = 1) -> None:
        self.randrange_value = randrange_value
        self.randint_value = randint_value

    def randrange(self, n: int) -> int:
        return min(max(self.randrange_value, 0), n - 1)

    def randint(self, low: int, high: int) -> int:
        return min(max(self.randint_value, low), high)


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


def test_lava_burns_on_the_step_onto_it_not_off_it(pygame_setup, asset_mgr):
    """LairWare ValidDir (UltimaMain.c:3194-3207) burns the party as it steps
    ONTO lava; stepping off it (Java's effect of the tile being left) does
    nothing. Flat 50 per member (GBC funcs5.c:1287-1310, LW the same)."""
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

    ow._move_avatar(Direction.NORTH)  # off the lava onto grass
    assert (party.x, party.y) == (44, 19)
    assert all(m.hp == 100 for m in party.members)

    ow._move_avatar(Direction.SOUTH)  # back onto the lava
    assert (party.x, party.y) == (44, 20)
    assert all(m.hp == 100 - 50 for m in party.members)


def test_overworld_pass_turn_consumes_turn_without_standing_effect(
    pygame_setup, asset_mgr
):
    """Java GameScreen.java:624-628: the pass key finishes the turn at the
    party's tile. LairWare applies terrain only on the step onto it
    (ValidDir, UltimaMain.c:3169-3220), so passing on a field does nothing."""
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

    assert (party.x, party.y) == (0, 0)
    assert party.moves == moves_before + 2
    assert all(m.status == Status.GOOD for m in party.members)
    assert all(m.hp == 100 for m in party.members)


def test_ambrosia_eats_every_fourth_turn(pygame_setup, asset_mgr):
    """LairWare AgeChars (UltimaMisc.c:1405-1410): on Ambrosia (Party[3] >
    0) it acts every 4th turn, on Sosaria every turn, 40 of the pool each.
    With 30 submorsels banked, Ambrosia's first turn ticks and crosses; its
    next three do nothing. Sosaria crosses on its first turn too."""
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
        ow.creatures = []  # no fight (a combat runs AgeChars too)
        party.x, party.y = 0, 0
        return ow, party

    ow, party = _screen_and_party(13)
    food_before = party.food
    ow._pass_turn()
    assert all(m.submorsels == 400 for m in party.members)
    assert party.food == food_before - len(party.members)
    for _ in range(3):
        ow._pass_turn()
    assert [m.submorsels for m in party.members] == [400, 400]  # no tick
    for _ in range(1):
        ow._pass_turn()
    assert all(m.submorsels == 360 for m in party.members)  # 5th turn ticks

    ow0, party0 = _screen_and_party(0)
    ow0._pass_turn()
    assert all(m.submorsels == 400 for m in party0.members)  # 40 drain: crossed, reset
    assert party0.food == food_before - len(party0.members)  # -1 food per member


def test_town_pass_turn_consumes_turn_without_standing_effect(
    pygame_setup, asset_mgr
):
    """Town pass routes through the same _finish_turn flow; standing on lava
    does nothing (LairWare ValidDir burns on entry, UltimaMain.c:3194-3207)."""
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
    tw.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))

    assert (tw.avatar_x, tw.avatar_y) == (0, 0)
    assert party.moves == moves_before + 1
    assert all(m.hp == 100 for m in party.members)


# --- applyEffect port (Party.java:279-283 + 342-368 unconditional;
#     Party.java:285-306 rolled, combat-only) ---


def test_lava_effect_flat_50_and_mark_of_fire_immunity():
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): LAVA via the
    unconditional fan-out is flat 50 damage unless marks[1]
    (GBC funcs5.c:1287-1310; LW corroborates flat 50)."""
    party = make_party()
    party.members[0].marks[1] = 1  # Mark of Fire
    party.members[1].marks[1] = 0

    tile_effects.apply_effect(party, TileEffect.LAVA)
    assert party.members[0].hp == 100

    party = make_party()
    party.members[0].marks[1] = 0
    party.members[1].marks[1] = 0
    tile_effects.apply_effect(party, TileEffect.LAVA)
    assert all(m.hp == 100 - 50 for m in party.members)


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
    # The strike, when it lands, is flat 50 (GBC funcs5.c:1287-1310).
    party = make_party()
    party.members[0].marks[1] = 1
    tile_effects.apply_effect_rolled(party, TileEffect.LAVA, rng=RemainderRng(0))
    assert party.members[0].hp == 100
    assert party.members[1].hp == 100 - 50
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


def test_energy_field_passes_only_when_every_member_marked(asset_mgr):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the force field's
    passage decision (GBC postexo1.c:1861-1880 ``forceOK``) demands EVERY
    living member carry the Mark of Force — one marked member is no longer
    enough."""
    grass = asset_mgr.get_tile_by_name("grass")
    energy = asset_mgr.get_tile_by_name("energy_field")
    gmap = GameMap(id=0, name="T", width=2, height=1, tiles=[grass, energy])

    party = make_party()
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is False
    party.members[0].marks[3] = 1  # one mark of Force
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is False
    party.members[1].marks[3] = 1  # every member marked
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is True


def test_fire_field_keeps_any_marked_passage(asset_mgr):
    """Java gate is the rule attribute, not the walkable flag: fire fields
    (walkable, dispelable) keep the ANY-marked (BaseMap.java:719-744)
    passage — the GBC all-marked refusal is the ENERGY field specifically."""
    grass = asset_mgr.get_tile_by_name("grass")
    fire = asset_mgr.get_tile_by_name("fire")
    gmap = GameMap(id=0, name="T", width=2, height=1, tiles=[grass, fire])

    party = make_party()
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is False
    party.members[0].marks[3] = 1  # any single mark opens a fire field
    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is True


# --- GBC force field: 99 damage on the refused entry
#     (USER-DIRECTED GBC-RULES DEVIATION 2026-11-14,
#     GBC postexo1.c:1861-1880) ---


def _force_field_screen(pygame_setup, asset_mgr, n: int = 2, hp: int = 100):
    grass = asset_mgr.get_tile_by_name("grass")
    energy = asset_mgr.get_tile_by_name("energy_field")
    gmap = GameMap(
        id=0, name="T", width=2, height=1, border_behavior="wrap",
        tiles=[grass, energy],
    )
    party = make_party(n=n, hp=hp)
    for m in party.members:
        m.food = 400
    ow = OverworldScreen(
        party=party, map_id=0, asset_mgr=asset_mgr, random_encounters=False
    )
    ow.game_map = gmap
    party.x, party.y = 0, 0
    return ow, party


def test_force_field_refused_move_deals_99_to_unmarked_members(
    pygame_setup, asset_mgr
):
    """A refused energy-field entry writes 'FORCE FIELD!' and strikes every
    living member lacking the Mark of Force for 99; the marked member is
    untouched and the party does not move."""
    ow, party = _force_field_screen(pygame_setup, asset_mgr)
    party.members[0].marks[3] = 1

    ow._move_avatar(Direction.EAST)

    assert any(m == "FORCE FIELD!" for m in ow.text_log.history)
    assert party.members[0].hp == 100
    assert party.members[0].status == Status.GOOD
    assert party.members[1].hp == 100 - 99
    assert party.members[1].status == Status.GOOD
    assert (party.x, party.y) == (0, 0)


def test_force_field_refusal_wipes_solo_party(pygame_setup, asset_mgr):
    """The 99 strike routes a wiped party through the death flow
    (PartyDeathException → check_party_death → StartScreen game over)."""
    from py_exodus.screens.start import StartScreen

    ow, party = _force_field_screen(pygame_setup, asset_mgr, n=1, hp=10)

    ow._move_avatar(Direction.EAST)

    assert party.members[0].status == Status.DEAD
    assert party.members[0].hp == 0
    assert party.is_party_dead()
    assert isinstance(ow.next_screen, StartScreen)
    assert (party.x, party.y) == (0, 0)


def test_force_field_all_marked_party_passes(pygame_setup, asset_mgr):
    """Every member marked: the entry succeeds and nobody takes the 99."""
    ow, party = _force_field_screen(pygame_setup, asset_mgr)
    for m in party.members:
        m.marks[3] = 1

    ow._move_avatar(Direction.EAST)

    assert (party.x, party.y) == (1, 0)
    assert all(m.hp == 100 for m in party.members)


def test_force_field_strike_skips_dead_and_strikes_living_unmarked(asset_mgr):
    """A DEAD unmarked member neither blocks the gate nor takes the strike —
    the living, unmarked members take the 99 (strike-helper pin)."""
    energy = asset_mgr.get_tile_by_name("energy_field")
    party = make_party(n=3)
    party.members[0].status = Status.DEAD
    party.members[0].hp = 0
    lines: list[str] = []

    refused = tile_effects.apply_force_field_strike(party, energy, lines.append)

    assert refused is True
    assert lines == ["FORCE FIELD!"]
    assert party.members[0].hp == 0
    assert party.members[0].status == Status.DEAD
    assert party.members[1].hp == 100 - 99
    assert party.members[1].status == Status.GOOD
    assert party.members[2].hp == 100 - 99
    assert party.members[2].status == Status.GOOD


def test_force_field_dead_member_does_not_block_passage(asset_mgr):
    """Vacuous-gate pin: a DEAD unmarked member does not block the all-marked
    passage; every LIVING member marked opens the field."""
    grass = asset_mgr.get_tile_by_name("grass")
    energy = asset_mgr.get_tile_by_name("energy_field")
    gmap = GameMap(id=0, name="T", width=2, height=1, tiles=[grass, energy])
    party = make_party(n=3)
    party.members[0].status = Status.DEAD
    party.members[0].hp = 0
    party.members[1].marks[3] = 1
    party.members[2].marks[3] = 1

    assert can_move_to(gmap, 1, 0, transport=Transport.FOOT, party=party) is True


# --- GBC force field, town-screen move path (review fix round 1) ---------


def _british_screen(asset_mgr, party):
    """TownScreen on the real british.json map, avatar on the floor west of
    the energy field at (42, 17) (tile index 32)."""
    from py_exodus.screens.town import TownScreen

    tw = TownScreen(
        party=party, map_id=1, asset_mgr=asset_mgr, start_x=41, start_y=17
    )
    energy = tw.game_map.get_tile(42, 17)
    assert tw.game_map is not None and energy is not None
    assert energy.rule == "energy" and energy.dispelable
    return tw


def test_town_force_field_refusal_strikes_unmarked(pygame_setup, asset_mgr):
    """The movement validator fires in any context: a refused energy-field
    entry on the town screen writes "FORCE FIELD!" and strikes the living
    unmarked members for 99; the move is refused."""
    tw = _british_screen(asset_mgr, make_party())

    tw._try_move(Direction.EAST)

    assert any(m == "FORCE FIELD!" for m in tw.text_log.history)
    assert (tw.avatar_x, tw.avatar_y) == (41, 17)
    assert all(m.hp == 100 - 99 for m in tw.party.members)
    assert all(m.status == Status.GOOD for m in tw.party.members)


def test_town_force_field_refusal_skips_dead_and_strikes_living(
    pygame_setup, asset_mgr
):
    """Same vacuous-gate case from the town angle: a DEAD unmarked member
    takes nothing; the living unmarked members take the 99."""
    party = make_party(n=3)
    party.members[0].status = Status.DEAD
    party.members[0].hp = 0
    tw = _british_screen(asset_mgr, party)

    tw._try_move(Direction.EAST)

    assert any(m == "FORCE FIELD!" for m in tw.text_log.history)
    assert (tw.avatar_x, tw.avatar_y) == (41, 17)
    assert tw.party.members[0].hp == 0
    assert tw.party.members[1].hp == 100 - 99
    assert tw.party.members[2].hp == 100 - 99


def test_town_force_field_all_marked_passes(pygame_setup, asset_mgr):
    """Every living member marked: the town entry onto the real british.json
    energy cell (42, 17) succeeds and nobody takes the 99."""
    party = make_party()
    for m in party.members:
        m.marks[3] = 1
        m.food = 400  # the stepped turn's town regen/meal tick stays clean
    tw = _british_screen(asset_mgr, party)

    tw._try_move(Direction.EAST)

    assert (tw.avatar_x, tw.avatar_y) == (42, 17)
    assert all(m.hp == 100 for m in tw.party.members)


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
    assert party.members[1].hp == 100 - 50  # flat 50 (GBC funcs5.c:1287-1310)
    assert dmap.get_tile(5, 4, 0) is DungeonTile.FIELD_FIRE


# USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): pit trap dex-evade +
# per-member rnd(level+1)<<3 (GBC dungfunc.c:1190-1232) — supersedes the
# Java unconditional LAVA fan-out below.


def test_dungeon_pit_trap_gbc_high_dex_evades():
    """GBC pit: a high-dex member evades every level; no damage, tile cleared.

    The evade convention is the chest-trap roll (dex + 25 >= randrange(100)):
    dex 99 succeeds against any roll, so damage never lands on any dungeon
    level and the pit tile still clears to NOTHING.
    """
    for z in range(8):
        dmap = make_dmap()
        dmap.set_tile(5, 4, z, DungeonTile.PIT_TRAP)
        party = make_party()
        for m in party.members:
            m.dex = 99
        state = DungeonState(
            dmap,
            start_x=5,
            start_y=5,
            start_z=z,
            start_dir=Direction.NORTH,
            party=party,
            rng=FixedRollRng(99, 1),
            random_encounters=False,
        )
        evt = state.move_forward()
        assert evt.type == DungeonEventType.PIT_TRAP
        assert evt.message == "Pit!"
        assert all(m.hp == 100 for m in party.members)
        assert dmap.get_tile(5, 4, z) is DungeonTile.NOTHING


def test_dungeon_pit_trap_gbc_zero_dex_damage_bounded():
    """GBC pit: zero-dex fails the evade ~always; failures take <= (z+1)*8.

    Each living member rolls its own evade; a failure deals
    randint(0, z + 1) << 3 — zero damage is possible per roll, so the assert
    is a bound (hp within [100 - (z+1)*8, 100]) across seeded runs, with some
    run actually taking damage.
    """
    for z in (0, 3):
        damage_seen = False
        for seed in range(20):
            dmap = make_dmap()
            dmap.set_tile(5, 4, z, DungeonTile.PIT_TRAP)
            party = make_party()
            for m in party.members:
                m.dex = 0
            state = DungeonState(
                dmap,
                start_x=5,
                start_y=5,
                start_z=z,
                start_dir=Direction.NORTH,
                party=party,
                rng=random.Random(seed),
                random_encounters=False,
            )
            evt = state.move_forward()
            assert evt.type == DungeonEventType.PIT_TRAP
            assert dmap.get_tile(5, 4, z) is DungeonTile.NOTHING
            for m in party.members:
                assert 100 - (z + 1) * 8 <= m.hp <= 100
                if m.hp < 100:
                    damage_seen = True
        assert damage_seen


def test_dungeon_pit_trap_gbc_mark_of_fire_no_protection():
    """Mark of Fire absorbs lava, not pits: a marked member takes the fall.

    GBC dungfunc.c:1190-1232 gives the pit no mark immunity — the Java
    LAVA-effect Mark-of-Fire branch does not apply here.
    """
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.PIT_TRAP)
    party = make_party()
    party.members[0].marks[1] = 1
    for m in party.members:
        m.dex = 0
    state = DungeonState(
        dmap,
        start_x=5,
        start_y=5,
        start_z=0,
        start_dir=Direction.NORTH,
        party=party,
        rng=FixedRollRng(99, 1),  # evade fails for dex 0; damage 1<<3 = 8
        random_encounters=False,
    )
    evt = state.move_forward()
    assert evt.type == DungeonEventType.PIT_TRAP
    assert party.members[0].hp == 100 - 8  # the mark does not protect a pit
    assert party.members[1].hp == 100 - 8
    assert dmap.get_tile(5, 4, 0) is DungeonTile.NOTHING
