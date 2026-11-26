"""Castle Exodus's enclosure: the moongate (12, 55) and the 5-tile pond.

The pond south of the castle is (9..11, 54), (10, 55) and (10, 56); the
castle (10, 53) is entered from the water at (10, 54), so the party ferries
across in a frigate. West of the pond lie (8, 54), (8, 55), (9, 55); east,
(11, 55), moongate 5 at (12, 55) and (12, 54). EVOCARE drops a ship at
(10, 56).

* Live check seed 2 at bdbd73a (WIPED@111,111): going for food through
  gate 5, the gate leg's patrol walked (12, 54) -> (12, 55) -> (11, 55) and
  back, across the gate site. Every 96 turns it stood on the site as the
  phase turned to trammel 5 / felucca 7, was carried to (58, 31), waited
  there for gate 7 back, and was home in time for the next wrong opening:
  ~1,250 steps, starved with 6,223 gold.
* Batch bdbd73a b1 seeds 4 and 10 (WIPED): back from the grocer, the new
  ship came in at (10, 56) with the old frigate parked at (10, 55). A ship
  can't sail onto a frigate and (10, 56) touches no land, so neither
  CONQUER_EXODUS nor BUY_FOOD had a trip; the party passed ~3,300 turns
  there, then ~1,500 more, and starved with ~6,000 gold. LairWare lets a
  ship be left on any water (UltimaMain.c:2523-2538) and a frigate's tile
  is walkable on foot (Java hasShipObjectAt), so the way is X, step onto
  the frigate, B, and on.
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from py_exodus.autoplay import batch
from py_exodus.autoplay.controller import _DIR_TO_KEY, AutoPlayController
from py_exodus.autoplay import planner
from py_exodus.autoplay.planner import Goal, evaluate_goal
from py_exodus.autoplay.trip import Destination, Leg, plan_trip
from py_exodus.constants import ArmorType, Direction, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import tile_effects

GATE5 = (12, 55)
POND_FRIGATE = (10, 55)


@pytest.fixture(autouse=True)
def _rng():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    st, tst = random.getstate(), tile_effects._rng.getstate()
    yield
    random.setstate(st)
    tile_effects._rng.setstate(tst)


def _ready_party(food: int, gold_each: int = 1556):
    """The live check's party: level 25, all marks, cards and Exotics, the
    shrine stats bought (no return trip left), ~6,223 gold."""
    from py_exodus.autoplay.planner import return_trip_cost, stat_cap

    party = batch.build_party()
    for m in party.members:
        m.level = 25
        m.exp = 2400
        m.max_hp = 2550
        m.hp = 2550
        m.food = food
        m.keys = 5
        m.gold = gold_each
        m.marks = [1, 1, 1, 1]
        m.cards = [1, 1, 1, 1]
        m.weapon = WeaponType.EXOTIC
        m.armor = ArmorType.EXOTIC
        m.weapons[WeaponType.EXOTIC] = 1
        m.armors[ArmorType.EXOTIC] = 1
        for stat, cap in (("strength", "max_str"), ("dexterity", "max_dex"),
                          ("intelligence", "max_int"), ("wisdom", "max_wis")):
            setattr(m, stat, stat_cap(m, cap))
    m = party.members[3]
    m.mp = m.max_mp = max(m.max_mp, 0)
    assert return_trip_cost(party) == 0
    return party


def _world(party, seed: int):
    random.seed(seed)
    tile_effects._rng.seed(seed)
    batch._seed_dungeon_rngs()
    am = batch._assets()
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am)
    sm.set_screen(ow)
    return sm, ow


def _run(sm, party, ctrl, max_steps: int, stop) -> int:
    steps = 0
    orig = ctrl.step

    def counted(s):
        nonlocal steps
        steps += 1
        return orig(s)

    ctrl.step = counted
    sm.autoplay_enabled = True
    while steps < max_steps and not stop() and not party.is_party_dead():
        ctrl.update(batch.FRAME_DT, sm)
        sm.update(batch.FRAME_DT)
    return steps


# ---------------------------------------------------------------------------
# The moongate (12, 55)
# ---------------------------------------------------------------------------


def test_gate_patrol_never_crosses_the_gate_site():
    """From (12, 54) the only other roam tile is (11, 55), and the way there
    is over the site (12, 55). With gate 5 -> 0 two phases off (trammel 4,
    felucca 6), the patrol stepped SOUTH onto the site; the phase turned to
    5/7 on that step and the party was carried to (58, 31)."""
    party = _ready_party(food=37)
    party.x, party.y = 12, 54
    party.moon_phase = 14  # trammel 4, felucca 6: gate 5 -> 0 opens at 16
    sm, ow = _world(party, 2)
    ow.creatures = []
    gmap = ow.game_map
    assert (gmap.moongates[5].x, gmap.moongates[5].y) == GATE5
    ctrl = AutoPlayController(enabled=True)
    keys: list[int] = []
    ctrl._emit_key = lambda _sm, key, **_kw: keys.append(key) or 0
    leg = Leg(Transport.FOOT, GATE5, "GATE", gate_src=5, gate_dest=0)
    for _ in range(3):
        keys.clear()
        ctrl._drive_gate(sm, ow, gmap, party, (12, 54), leg)
        assert keys and keys[-1] != _DIR_TO_KEY[Direction.SOUTH]


@pytest.mark.parametrize("phase", [3, 7])
def test_hungry_party_by_the_exodus_gate_reaches_food(phase):
    """The live check's state: (12, 55), food 37, 6,223 gold, the ferry
    frigate parked at (10, 55). Seed 2 / phase 3 walked over the site into
    a wrong opening; now the party never lands anywhere but the gate's
    planned destination and is in a town well before it starves."""
    party = _ready_party(food=37)
    party.x, party.y = GATE5
    party.moon_phase = phase
    party.dynamic_objects = [{"tile": "frigate", "x": POND_FRIGATE[0], "y": POND_FRIGATE[1]}]
    sm, _ow = _world(party, 2)
    ctrl = AutoPlayController(enabled=True)
    wrong: list[tuple[int, int]] = []
    orig_update = sm.update

    def watch(dt):
        orig_update(dt)
        if (party.x, party.y) in ((58, 31), (57, 46), (31, 31), (36, 58)):
            wrong.append((party.x, party.y))

    sm.update = watch
    steps = _run(sm, party, ctrl, 700, lambda: type(sm.current_screen).__name__ == "TownScreen")
    assert not wrong, wrong
    assert type(sm.current_screen).__name__ == "TownScreen", (steps, party.x, party.y)
    assert min(m.food for m in party.members) > 0


# ---------------------------------------------------------------------------
# The pond: a ship at (10, 56) behind a parked frigate at (10, 55)
# ---------------------------------------------------------------------------


def test_plan_from_a_ship_behind_the_parked_frigate_reaches_the_castle():
    party = _ready_party(food=400)
    party.x, party.y = 10, 56
    party.transport = Transport.SHIP
    party.dynamic_objects = [{"tile": "frigate", "x": POND_FRIGATE[0], "y": POND_FRIGATE[1]}]
    _sm, ow = _world(party, 4)
    dest = Destination(frozenset({(10, 53)}), Transport.FOOT, "exodus")
    plan = plan_trip(ow.game_map, party, 0, (10, 56), Transport.SHIP, dest, {POND_FRIGATE: 0.0})
    assert plan is not None
    assert [(leg.action, leg.end) for leg in plan.legs][:2] == [("X", (10, 56)), ("B", POND_FRIGATE)]


def test_ship_behind_the_parked_frigate_enters_castle_exodus():
    """Batch bdbd73a b1 seed 4: in a ship at (10, 56) after EVOCARE, food
    405, the old frigate at (10, 55): no trip, ~3,300 turns passing."""
    party = _ready_party(food=400)
    party.x, party.y = 10, 56
    party.transport = Transport.SHIP
    party.dynamic_objects = [{"tile": "frigate", "x": POND_FRIGATE[0], "y": POND_FRIGATE[1]}]
    sm, ow = _world(party, 4)
    ow.creatures = []
    assert evaluate_goal(party, 0) == Goal.CONQUER_EXODUS
    ctrl = AutoPlayController(enabled=True)
    steps = _run(sm, party, ctrl, 400, lambda: getattr(sm.current_screen, "map_id", 0) == 2
                 or type(sm.current_screen).__name__ == "TownScreen")
    assert type(sm.current_screen).__name__ == "TownScreen", (steps, party.x, party.y, party.transport)


def test_hungry_ship_behind_the_parked_frigate_reaches_food():
    """Seeds 4 and 10 after the wait: BUY_FOOD in the ship at (10, 56)."""
    party = _ready_party(food=60)
    party.x, party.y = 10, 56
    party.transport = Transport.SHIP
    party.dynamic_objects = [{"tile": "frigate", "x": POND_FRIGATE[0], "y": POND_FRIGATE[1]}]
    sm, _ow = _world(party, 10)
    assert evaluate_goal(party, 0) == Goal.BUY_FOOD
    ctrl = AutoPlayController(enabled=True)
    steps = _run(sm, party, ctrl, 900, lambda: type(sm.current_screen).__name__ == "TownScreen")
    assert type(sm.current_screen).__name__ == "TownScreen", (steps, party.x, party.y, party.transport)
    assert min(m.food for m in party.members) > 0


# ---------------------------------------------------------------------------
# Food before setting out for the castle
# ---------------------------------------------------------------------------


def test_castle_trip_sets_out_with_the_food_reserve():
    """Seed 2 set out from Britain with 134 food, reached the door with 104,
    rested to full HP and fell under the 75 bar there: back out through the
    gate for food. Seeds 4 and 10 likewise (126 and 104 at the start)."""
    party = _ready_party(food=134)
    party.x, party.y = 45, 18
    assert evaluate_goal(party, 0) == Goal.BUY_FOOD
    for m in party.members:
        m.food = planner.EXODUS_ENTRY_FOOD
    assert evaluate_goal(party, 0) == Goal.CONQUER_EXODUS

    # Never once at the castle: inside, or past the serpent, a food run is
    # the moongate out and back.
    for m in party.members:
        m.food = 134
    party.x, party.y = 10, 55
    assert evaluate_goal(party, 0) == Goal.CONQUER_EXODUS
    assert evaluate_goal(party, 2) == Goal.CONQUER_EXODUS

    # Under 700 gold the grocer fills to 150 only (controller
    # _food_shop_target), under the reserve: asking for it would loop.
    party.x, party.y = 45, 18
    for m in party.members:
        m.gold = 150
    assert evaluate_goal(party, 0) == Goal.CONQUER_EXODUS
