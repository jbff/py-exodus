"""Autoplay trip layer (single owner of B/X) and the pirate firing-lane rule."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.autoplay import controller as controller_mod
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.planner import Goal, evaluate_goal
from py_exodus.autoplay.threats import (
    compute_threats,
    foot_escape,
    lane_tiles_for,
    party_has_alcort,
    ship_escape,
)
from py_exodus.autoplay.trip import Destination, gate_hops, plan_trip
from py_exodus.constants import ArmorType, Direction, Profession, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.ui.renderer import can_move_to
from py_exodus.world.loader import load_map
from tests.test_autoplay import _make_party


@pytest.fixture(scope="module")
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield


@pytest.fixture(scope="module")
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture(scope="module")
def sosaria(asset_mgr):
    return load_map(0, asset_mgr)


def _pirate(x, y):
    return {"tile_name": "pirate", "tile": "pirate", "x": x, "y": y, "sail_dir": "EAST"}


# ---------------------------------------------------------------------------
# Lane geometry (engine: same row/column, movement distance 2 or 3)
# ---------------------------------------------------------------------------


def test_lane_tiles_are_row_and_column_at_distance_2_and_3():
    lane = lane_tiles_for(64, 64, (10, 10))
    assert {(12, 10), (13, 10), (8, 10), (7, 10), (10, 12), (10, 13), (10, 8), (10, 7)} == lane
    assert (11, 10) not in lane  # distance 1 is the battle, not the lane
    assert (11, 11) not in lane  # diagonal: never fired upon
    assert (14, 10) not in lane


def test_lane_tiles_wrap_the_map_seam():
    lane = lane_tiles_for(64, 64, (0, 5))
    assert (62, 5) in lane and (61, 5) in lane


def test_squid_reach_only_until_alcort(sosaria):
    party = _make_party(level=5)
    squid = [{"tile_name": "squid", "x": 30, "y": 30}]
    th = compute_threats(sosaria, party, squid)
    assert not party_has_alcort(party)
    assert (31, 30) in th.squid_engage and (32, 30) not in th.squid_engage
    assert (32, 31) in th.squid_coast
    for m in party.members:
        if m.profession == Profession.CLERIC:
            m.max_mp = 35
    th2 = compute_threats(sosaria, party, squid)
    assert th2.squid_engage == set()


# ---------------------------------------------------------------------------
# Escapes
# ---------------------------------------------------------------------------


class _Grid:
    """A tiny open map for escape decisions."""

    width = 64
    height = 64


def test_foot_escape_steps_off_the_line():
    party = _make_party(level=5)
    pirate = (10, 10)
    pos = (13, 10)  # distance 3, same row
    th = compute_threats(_Grid, party, [_pirate(*pirate)])
    assert th.in_lane(pos)
    move = foot_escape(_Grid, party, pos, th, lambda x, y: True, prefer_engage=False)
    assert move.key == "move"
    nxt = (pos[0] + move.direction.dx, pos[1] + move.direction.dy)
    assert not th.in_lane(nxt)


def test_foot_escape_closes_to_melee_when_it_can():
    party = _make_party(level=5)
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    move = foot_escape(_Grid, party, (12, 10), th, lambda x, y: True, prefer_engage=True)
    assert move.key == "move" and move.direction == Direction.WEST  # to (11, 10), next to the pirate


def test_foot_escape_attacks_an_adjacent_pirate():
    party = _make_party(level=5)
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    move = foot_escape(_Grid, party, (10, 11), th, lambda x, y: True, prefer_engage=True)
    assert move.key == "attack" and move.direction == Direction.NORTH


def test_ship_escape_sails_on_when_heading_leads_out():
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = Direction.WEST  # blows west -> can't sail east
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    move = ship_escape(_Grid, party, (13, 10), Direction.NORTH, th, lambda x, y: True, prefer_engage=False)
    assert move.key == "move" and move.direction == Direction.NORTH


def test_ship_escape_fires_back_when_it_cannot_leave_this_turn():
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = Direction.SOUTH  # blocks NORTH
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    # Heading north (blocked by wind): broadside faces east/west, the pirate is west.
    move = ship_escape(_Grid, party, (13, 10), Direction.NORTH, th, lambda x, y: True, prefer_engage=False)
    assert move.key == "fire" and move.direction == Direction.WEST


def test_ship_escape_turns_when_nothing_else_works():
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = Direction.EAST  # blocks WEST
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    # Heading west (blocked), pirate west in the same row: broadside (N/S) can't bear.
    move = ship_escape(_Grid, party, (13, 10), Direction.WEST, th, lambda x, y: True, prefer_engage=False)
    assert move.key == "move" and move.direction in (Direction.NORTH, Direction.SOUTH)


# ---------------------------------------------------------------------------
# Trip planner on the real Sosaria map
# ---------------------------------------------------------------------------


def test_gate_hops_follow_the_moon_phases():
    hops = gate_hops(8)
    assert hops[0] == [1, 2]
    assert hops[1] == [3, 4, 5]
    assert hops[7] == [5, 6]


def test_plan_walks_when_destination_is_on_the_same_land(sosaria):
    party = _make_party(level=5)
    dest = Destination(frozenset({(46, 19)}), Transport.FOOT, "britain")
    plan = plan_trip(sosaria, party, 0, (44, 20), Transport.FOOT, dest, {}, allow_capture=False)
    assert plan is not None
    assert [leg.action for leg in plan.legs] == ["ARRIVE"]
    assert all(m == Transport.FOOT for _, _, m in plan.path)


def test_plan_boards_a_coastal_frigate_to_reach_an_island(sosaria):
    party = _make_party(level=5)
    # (33, 3) is the exotic-weapon island. A frigate waits on the mainland coast.
    terr_dest = Destination(frozenset({(33, 3)}), Transport.FOOT, "dig")
    frigate = (46, 12)  # water next to the mainland's east coast
    assert not can_move_to(sosaria, *frigate, Transport.FOOT)
    assert can_move_to(sosaria, *frigate, Transport.SHIP)
    plan = plan_trip(sosaria, party, 0, (44, 20), Transport.FOOT, terr_dest, {frigate: 0.0}, allow_capture=False)
    assert plan is not None
    actions = [leg.action for leg in plan.legs]
    assert actions == ["B", "X", "ARRIVE"]
    assert plan.legs[0].end == frigate and plan.legs[0].mode == Transport.FOOT
    assert plan.legs[1].mode == Transport.SHIP


def test_plan_captures_a_ship_when_none_is_available(sosaria):
    party = _make_party(level=5)
    dest = Destination(frozenset({(33, 3)}), Transport.FOOT, "dig")
    plan = plan_trip(sosaria, party, 0, (44, 20), Transport.FOOT, dest, {})
    assert plan is not None
    assert plan.legs[0].action == "CAPTURE"
    assert [leg.action for leg in plan.legs][-2:] == ["X", "ARRIVE"]


def test_plan_lands_from_a_ship_for_a_town(sosaria):
    party = _make_party(level=5, transport=Transport.SHIP)
    dest = Destination(frozenset({(46, 19)}), Transport.FOOT, "britain")
    plan = plan_trip(sosaria, party, 0, (47, 12), Transport.SHIP, dest, {}, allow_capture=False)
    assert plan is not None
    assert [leg.action for leg in plan.legs] == ["X", "ARRIVE"]


def test_plan_needs_a_ship_at_a_sea_destination(sosaria):
    party = _make_party(level=5)
    dest = Destination(frozenset({(50, 13)}), Transport.SHIP, "whirlpool", moving=True)
    plan = plan_trip(sosaria, party, 0, (44, 20), Transport.FOOT, dest, {(46, 12): 0.0}, allow_capture=False)
    assert plan is not None
    assert [leg.action for leg in plan.legs] == ["B", "ARRIVE"]
    assert plan.legs[-1].mode == Transport.SHIP


def test_recent_reverse_transition_is_penalised(sosaria):
    """Re-boarding the ship we just left costs extra (no B/X ping-pong)."""
    from py_exodus.autoplay.trip import REVERSE_TRANSITION_PENALTY, Transition

    party = _make_party(level=5)
    dest = Destination(frozenset({(50, 13)}), Transport.SHIP, "whirlpool")
    plain = plan_trip(sosaria, party, 0, (46, 12), Transport.FOOT, dest, {(46, 12): 0.0}, allow_capture=False)
    pen = plan_trip(
        sosaria, party, 0, (46, 12), Transport.FOOT, dest, {(46, 12): 0.0},
        allow_capture=False, last_transition=Transition("X", (46, 12), 10), turn=20,
    )
    assert pen.cost == pytest.approx(plain.cost + REVERSE_TRANSITION_PENALTY)


# ---------------------------------------------------------------------------
# Planner: the goal never depends on the transport mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"level": 5, "marks": [1, 0, 0, 0], "gold": 0},
        {"level": 5, "marks": [1, 0, 0, 0], "gold": 0, "food": 100},
        {"level": 6, "marks": [1, 1, 1, 1], "cards": [1, 1, 1, 1], "gold": 0},
        {"level": 5, "marks": [1, 1, 1, 1], "gold": 1500, "weapon": WeaponType.EXOTIC, "armor": ArmorType.EXOTIC},
        {"level": 3, "gold": 500, "food": 500},
    ],
)
def test_goal_is_independent_of_transport(kwargs):
    foot = _make_party(transport=Transport.FOOT, **kwargs)
    ship = _make_party(transport=Transport.SHIP, **kwargs)
    for p in (foot, ship):
        for m in p.members:
            m.keys = 1
    assert evaluate_goal(foot) == evaluate_goal(ship)


def test_capture_ship_is_no_longer_a_goal():
    assert not hasattr(Goal, "CAPTURE_SHIP")
    p = _make_party(level=5, marks=[1, 0, 0, 0], gold=0)
    assert evaluate_goal(p) == Goal.DIG_EXOTICS


# ---------------------------------------------------------------------------
# Single owner: only the trip follower emits B or X
# ---------------------------------------------------------------------------


def _emit_sites(key_attr: str) -> list[str]:
    src = Path(inspect.getsourcefile(controller_mod)).read_text()
    tree = ast.parse(src)
    owners: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_emit_key"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Attribute)
                and node.args[1].attr == key_attr
            ):
                owners.append(fn.name)
    return owners


def test_only_the_trip_follower_boards():
    sites = [s for s in _emit_sites("K_b") if s != "_handle_town_prompt"]
    assert sites == ["_trip_drive"]


def test_only_the_trip_follower_leaves_the_ship():
    assert _emit_sites("K_x") == ["_trip_drive"]


# ---------------------------------------------------------------------------
# Controller integration: the lane rule beats everything that spends a turn
# ---------------------------------------------------------------------------


def _overworld(asset_mgr, party):
    sm = StateMachine(asset_mgr=asset_mgr, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=asset_mgr, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)
    return sm, ow


def test_controller_never_rests_in_a_pirate_lane(pygame_setup, asset_mgr):
    """Hurt party on the coast would rest (SPACE); a pirate lane forces a step instead."""
    party = _make_party(level=5, marks=[1, 0, 0, 0], gold=0, food=500, x=44, y=20)
    for m in party.members:
        m.hp = m.max_hp // 2
        if m.profession == Profession.CLERIC:
            m.max_mp = 20
            m.mp = 0
    sm, ow = _overworld(asset_mgr, party)
    # Find a coastal tile with water two tiles to its east (pirate on water).
    gmap = ow.game_map
    spot = None
    for y in range(5, 60):
        for x in range(5, 60):
            if (
                can_move_to(gmap, x, y, Transport.FOOT)
                and can_move_to(gmap, x + 2, y, Transport.SHIP)
                and can_move_to(gmap, x - 1, y, Transport.FOOT)
            ):
                spot = (x, y)
                break
        if spot:
            break
    assert spot is not None
    party.x, party.y = spot
    ow.creatures = [_pirate(spot[0] + 2, spot[1])]
    ctrl = AutoPlayController(enabled=True)
    key = ctrl.step(sm)
    assert key != pygame.K_SPACE
    if key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT):
        assert not ctrl._threats.in_lane((party.x, party.y)) or (party.x, party.y) != spot


def test_lane_guard_blocks_a_step_into_a_lane(pygame_setup, asset_mgr):
    party = _make_party(level=5)
    sm, ow = _overworld(asset_mgr, party)
    ctrl = AutoPlayController(enabled=True)
    ctrl._threats = compute_threats(ow.game_map, party, [_pirate(party.x + 4, party.y)])
    # User rule (2026-11-21): a healthy party may step into the lane only
    # while advancing on the pirate (east, distance 4 -> 3).
    assert ctrl._lane_guard(sm, pygame.K_RIGHT) == pygame.K_RIGHT
    assert ctrl._lane_guard(sm, pygame.K_UP) == pygame.K_UP
    # A badly hurt party refuses, bars the tile and re-plans: no waiting.
    for m in party.members:
        m.hp = max(1, m.max_hp // 5)
    assert ctrl._lane_guard(sm, pygame.K_RIGHT) == pygame.K_SPACE
    assert (party.x + 1, party.y) in ctrl._active_blocks()
    assert ctrl._trip is None


def test_lane_guard_refuses_backing_along_a_lane(pygame_setup, asset_mgr):
    """Moving within a lane away from the pirate (distance 2 -> 3) is not
    advancing: refused, the tile is barred and the trip re-plans."""
    party = _make_party(level=5)
    sm, ow = _overworld(asset_mgr, party)
    ctrl = AutoPlayController(enabled=True)
    ctrl._threats = compute_threats(ow.game_map, party, [_pirate(party.x + 2, party.y)])
    assert ctrl._lane_guard(sm, pygame.K_LEFT) == pygame.K_SPACE
    assert (party.x - 1, party.y) in ctrl._active_blocks()


def test_dead_member_without_exotics_does_not_pin_dig_exotics():
    """Seed-1 smoke stall: a dead member can't dig, so the goal moves on once
    every LIVING member holds exotic weapon and armor."""
    from py_exodus.constants import Status

    p = _make_party(level=8, marks=[1, 0, 0, 0], gold=0, weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC)
    dead = p.members[3]
    dead.status = Status.DEAD
    dead.hp = 0
    dead.weapons.clear()
    dead.armors.clear()
    dead.weapon = WeaponType.NONE
    dead.armor = ArmorType.NONE
    p.x, p.y = 33, 3  # standing on the weapon dig site
    assert evaluate_goal(p) != Goal.DIG_EXOTICS


def test_hand_transfer_never_gives_a_duplicate():
    """Smoke seed 1 looped at the dig site: the Thief's dug exotic was handed to
    the Fighter (who already owned one but had a +2 bow readied), so the Thief
    dug again forever. A member who owns the item never receives another."""
    from py_exodus.autoplay.equipment import best_hand_transfer

    p = _make_party(level=8)
    thief, fighter = p.members[0], p.members[1]
    thief.weapons.clear()
    thief.weapons[WeaponType.EXOTIC] = 1  # dug, unequipped
    thief.weapon = WeaponType.BOW
    fighter.weapons.clear()
    fighter.weapons[WeaponType.EXOTIC] = 1  # owned, unequipped
    fighter.weapon = WeaponType.BOW_P2
    for m in p.members[2:]:
        m.weapons[WeaponType.EXOTIC] = 1
    transfer = best_hand_transfer(p)
    assert transfer is None or transfer[1] != 2


# ---------------------------------------------------------------------------
# Being chased (user rule 2026-11-21): outrun a deadly fight to a town, else
# fight; never dodge in circles.
# ---------------------------------------------------------------------------


def _hurt(party, frac=0.25):
    for m in party.members:
        m.hp = max(1, int(m.max_hp * frac))


def test_deadly_chase_outrunnable_flees_to_town(pygame_setup, asset_mgr):
    party = _make_party(level=5)
    party.x, party.y = 46, 22  # 3 steps south of the Britain portal (46, 19)
    _hurt(party)
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 46, "y": 29}]
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert ctrl._fleeing
    assert ctrl._trip is not None and ctrl._trip.dest.label == "rest"


def test_deadly_chase_not_outrunnable_fights(pygame_setup, asset_mgr):
    party = _make_party(level=5)
    party.x, party.y = 46, 22
    _hurt(party)
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 47, "y": 19}]  # by the portal
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert not ctrl._fleeing


def test_healthy_party_does_not_flee(pygame_setup, asset_mgr):
    party = _make_party(level=5)
    party.x, party.y = 46, 22
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 46, "y": 29}]
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert not ctrl._fleeing


def test_squid_fought_on_foot_when_healthy(pygame_setup, asset_mgr):
    """User rule (2026-11-21): the squid by Castle British is fought on foot
    by a healthy party (no keep-away zone); a poisoned party keeps clear."""
    from py_exodus.constants import Status

    party = _make_party(level=5)
    party.x, party.y = 45, 20
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "squid", "tile": "squid", "x": 44, "y": 22}]
    ctrl = AutoPlayController(enabled=True)
    ctrl._threat_escape(sm, ow, party, party.x, party.y)
    assert not ctrl._threats.squid_engage
    party.members[0].status = Status.POISONED
    ctrl._threat_escape(sm, ow, party, party.x, party.y)
    assert ctrl._threats.squid_engage


def test_chest_in_a_lane_is_looted_before_escaping(pygame_setup, asset_mgr):
    """User report (2026-11-21): stepping onto a chest in a pirate lane, the
    party stepped off before looting and walked back in, forever. Now it
    loots first."""
    party = _make_party(level=5)
    sm, ow = _overworld(asset_mgr, party)
    party.dynamic_objects.append({"tile": "chest", "x": party.x, "y": party.y})
    ow.creatures = [_pirate(party.x + 3, party.y)]
    for m in party.members:
        m.mp = 0  # no APPAR_UNEM: plain Get
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame.K_g


def test_no_flee_to_town_when_town_cannot_heal(pygame_setup, asset_mgr):
    """User report (2026-11-21): a hurt level-3 party ran into Yew and
    straight back out, over and over: the town rests only with a healer who
    can cast (Cleric/Paladin/Druid, max MP >= 10). Without one, fight."""
    from py_exodus.constants import Profession

    party = _make_party(level=3)
    party.x, party.y = 46, 22
    _hurt(party)
    for m in party.members:
        if m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID):
            m.max_mp = 5
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 46, "y": 29}]
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert not ctrl._fleeing
    assert ctrl._trip is None or ctrl._trip.dest.label != "rest"


def test_town_rest_matches_the_flee_decision(pygame_setup, asset_mgr):
    """Whatever sends the party indoors to rest, the town handler rests."""
    from py_exodus.autoplay.planner import evaluate_goal
    from py_exodus.screens.town import TownScreen

    party = _make_party(level=5)
    _hurt(party, 0.6)
    ctrl = AutoPlayController(enabled=True)
    goal = evaluate_goal(party, 4)
    assert ctrl._can_rest_indoors(party, goal)
    sm = StateMachine(asset_mgr=asset_mgr, audio=None)
    ts = TownScreen(party=party, asset_mgr=asset_mgr, map_id=4, start_x=32, start_y=62)
    sm.set_screen(ts)
    assert ctrl.step(sm) == pygame.K_SPACE


def test_healthy_party_chased_by_dragons_does_not_hide_in_town(pygame_setup, asset_mgr):
    """User report (2026-11-21): dragons outside Yew; the healthy low-level
    party ran in, had nothing to do, ran out, ran back in. Fight instead."""
    party = _make_party(level=3)
    party.x, party.y = 46, 22
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "dragon", "tile": "dragon", "x": 46, "y": 29}]
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert not ctrl._fleeing


def test_poisoned_party_without_alcort_does_not_rest_in_town(pygame_setup, asset_mgr):
    """User report (2026-11-21): resting in a town to regain MP for heal
    spells while poisoned loses to the poison. Without ALCORT in reach the
    party does not rest; with it, it rests (for the MP to cure)."""
    from py_exodus.constants import Profession, Status
    from py_exodus.screens.town import TownScreen

    party = _make_party(level=3, gold=20)
    _hurt(party, 0.6)
    party.members[0].status = Status.POISONED
    for m in party.members:
        if m.profession in (Profession.CLERIC, Profession.DRUID):
            m.max_mp = 20
    ctrl = AutoPlayController(enabled=True)
    goal = evaluate_goal(party, 4)
    assert not ctrl._can_rest_indoors(party, goal)
    sm = StateMachine(asset_mgr=asset_mgr, audio=None)
    ts = TownScreen(party=party, asset_mgr=asset_mgr, map_id=4, start_x=32, start_y=62)
    sm.set_screen(ts)
    assert ctrl.step(sm) != pygame.K_SPACE
    for m in party.members:
        if m.profession in (Profession.CLERIC, Profession.DRUID):
            m.max_mp = 40
    assert ctrl._can_rest_indoors(party, evaluate_goal(party, 4))


def test_early_ambrosia_trip_targets_alcort_wisdom(pygame_setup):
    """User ruling (2026-11-21): before ALCORT the Ambrosia gold target is
    the Cleric's missing wisdom (100 gold a point) plus food and keys still
    to buy; the 4500 shrine budget only after ALCORT."""
    from py_exodus.autoplay.planner import alcort_wisdom_gap, ambrosia_trip_gold
    from py_exodus.constants import Profession

    party = _make_party(level=5, marks=[1, 1, 1, 1])
    cleric = next(m for m in party.members if m.profession == Profession.CLERIC)
    cleric.wisdom = 25
    cleric.max_mp = None  # derived from wisdom
    for m in party.members:
        m.food = 300
        m.keys = 2
    assert alcort_wisdom_gap(party) == 10
    assert ambrosia_trip_gold(party, 2) == 10 * 100 + 200
    for m in party.members:
        m.food = 100  # 4 x 100 food still to buy at ~1.2 gp
    assert ambrosia_trip_gold(party, 2) == 1200 + 480
    cleric.wisdom = 35
    assert alcort_wisdom_gap(party) == 0
    assert ambrosia_trip_gold(party, 2) >= 1500


def test_chest_opener_never_risks_a_trap_when_it_can_avoid_it(pygame_setup):
    """User report (2026-11-21): Death Gulch raids poisoned the party once
    the healer's MP ran out and a 25-dex Thief took chests with G. Open with
    APPAR UNEM (5 MP) or a dex-74+ member (dex+25 >= rand(100) always
    dodges); with neither, the raid is off."""
    from py_exodus.constants import Profession

    party = _make_party(level=10)
    ctrl = AutoPlayController(enabled=True)
    healer = next(
        i + 1 for i, m in enumerate(party.members)
        if m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
    )
    party.members[healer - 1].mp = 5
    assert ctrl._chest_opener(party) == ("cast", healer)
    for m in party.members:
        m.mp = 4
        m.dex = 25
    assert ctrl._chest_opener(party) is None
    party.members[0].dex = 74
    assert ctrl._chest_opener(party) == ("get", 1)
