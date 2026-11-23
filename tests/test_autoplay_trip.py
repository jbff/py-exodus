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
    return {"tile_name": "pirate", "tile": "pirate", "x": x, "y": y}


# ---------------------------------------------------------------------------
# Lane geometry (LairWare moveshoot: row, column or diagonal, 2 or 3 away)
# ---------------------------------------------------------------------------


def test_lane_tiles_are_rows_columns_and_diagonals_at_distance_2_and_3():
    lane = lane_tiles_for(64, 64, (10, 10))
    assert len(lane) == 16
    assert {(12, 10), (13, 10), (10, 7), (12, 12), (13, 13), (7, 13), (8, 8)} <= lane
    assert (11, 10) not in lane and (11, 11) not in lane  # distance 1: the battle
    assert (14, 10) not in lane and (12, 11) not in lane  # off every ray


def test_lane_stops_at_mountains(sosaria):
    """The shot stops at mountains, walls and the void (UltimaMisc.c:1265);
    by the moongate strip a mountain ridge at x=59 shields (58, 44)."""
    lane = lane_tiles_for(64, 64, (60, 44), sosaria)
    assert (58, 44) not in lane and (62, 44) in lane


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

    @staticmethod
    def get_tile(x, y):
        return "water"  # nothing stops a shot


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


def test_ship_escape_sails_out_of_the_lane_any_open_way():
    """LairWare ships have no heading: any direction the wind allows."""
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = Direction.WEST  # blows west -> can't sail east
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    move = ship_escape(_Grid, party, (13, 10), th, lambda x, y: True, prefer_engage=False)
    assert move.key == "move" and move.direction in (Direction.NORTH, Direction.SOUTH)
    assert not th.unsafe_end(((13 + move.direction.dx), 10 + move.direction.dy))


def test_ship_escape_fires_when_becalmed():
    """A becalmed ship can't sail; LairWare fires any of four directions."""
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = None
    th = compute_threats(_Grid, party, [_pirate(10, 10)])
    move = ship_escape(_Grid, party, (13, 10), th, lambda x, y: True, prefer_engage=False)
    assert move.key == "fire" and move.direction == Direction.WEST


def test_ship_escape_fires_along_any_line_when_boxed_in():
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = Direction.EAST
    th = compute_threats(_Grid, party, [_pirate(13, 8)])  # due north, 2 tiles
    move = ship_escape(_Grid, party, (13, 10), th, lambda x, y: False, prefer_engage=False)
    assert move.key == "fire" and move.direction == Direction.NORTH


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


def test_hand_transfer_never_ping_pongs_a_spare():
    """Batch 1c7525f seed 17: on a ship (ranged preferred) a spare Exotic
    went Thief -> Fighter -> Thief every step for 16,500 steps; both kept
    their bows, the party sat still and starved. The hand-off scores the
    weapon the way the receiver will choose what to ready."""
    from py_exodus.autoplay.equipment import best_hand_transfer, best_owned_weapon

    for prefer_ranged in (True, False):
        p = _make_party(level=12)
        thief, fighter = p.members[0], p.members[1]
        thief.weapons.clear()
        thief.weapons[WeaponType.EXOTIC] = 1
        thief.weapon = WeaponType.BOW
        fighter.weapons.clear()
        fighter.weapon = WeaponType.BOW
        for m in p.members[2:]:
            m.weapons.clear()
            m.weapon = WeaponType.EXOTIC
        seen = []
        for _ in range(6):
            for m in p.members:
                best = best_owned_weapon(m, prefer_ranged)
                if best is not None:  # R: ready it, old weapon to the pack
                    m.weapons[m.weapon] = m.weapons.get(m.weapon, 0) + 1
                    m.weapons[best] -= 1
                    m.weapon = best
            t = best_hand_transfer(p, prefer_ranged)
            if t is None:
                break
            giver, taker = p.members[t[0] - 1], p.members[t[1] - 1]
            w = next(w for w, c in giver.weapons.items() if c > 0 and w != giver.weapon)
            giver.weapons[w] -= 1
            taker.weapons[w] = taker.weapons.get(w, 0) + 1
            seen.append(t)
        assert len(seen) <= 1, (prefer_ranged, seen)


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
    # A G opener: with the Cleric dead the Thief takes chests (user ruling
    # 2026-11-22; no DEX is trap-proof under LairWare).
    from py_exodus.constants import Profession, Status

    for m in party.members:
        if m.profession == Profession.CLERIC:
            m.status = Status.DEAD
            m.hp = 0
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


def test_first_ambrosia_trip_saves_the_full_shrine_budget(pygame_setup):
    """User ruling (2026-11-22, replacing the early ALCORT trip of
    2026-11-21): the first trip waits for the 4500 shrine budget plus the
    food and keys still to buy; with every stat capped, 1500."""
    from py_exodus.autoplay.planner import alcort_wisdom_gap, ambrosia_trip_gold
    from py_exodus.constants import Profession

    party = _make_party(level=5, marks=[1, 1, 1, 1])
    cleric = next(m for m in party.members if m.profession == Profession.CLERIC)
    cleric.wisdom = 25
    cleric.max_mp = None  # derived from wisdom
    for m in party.members:
        m.food = 300
        m.keys = 2  # 8 together: the card-trip key budget
    assert alcort_wisdom_gap(party) == 10
    assert ambrosia_trip_gold(party, 2) == 4500
    for m in party.members:
        m.food = 100  # 4 x 100 food still to buy at ~1.2 gp
    assert ambrosia_trip_gold(party, 2) == 4500 + 480
    for m in party.members:
        m.food = 300
        for stat in ("strength", "dexterity", "intelligence", "wisdom"):
            setattr(m, stat, getattr(m, "max_" + stat[:3], 99))
    assert ambrosia_trip_gold(party, 2) == 1500


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
        m.dex = 74  # no DEX is trap-proof under LairWare: wait for mana
    assert ctrl._chest_opener(party) is None


def test_thief_then_fighter_then_wizard_open_chests_once_the_cleric_is_dead(pygame_setup):
    """User report (2026-11-22): the Cleric died early, nobody could cast
    APPAR UNEM, the party never opened a chest, never had the 500 gold to
    resurrect, and stalled. With no living APPAR UNEM caster the Thief takes
    chests with G, then the Fighter, the Wizard last."""
    from py_exodus.constants import Profession, Status

    party = _make_party(level=3)
    ctrl = AutoPlayController(enabled=True)
    idx = {m.profession: i + 1 for i, m in enumerate(party.members)}
    party.members[idx[Profession.CLERIC] - 1].status = Status.DEAD
    assert ctrl._chest_opener(party) == ("get", idx[Profession.THIEF])
    assert not ctrl._chest_too_risky(party)
    party.members[idx[Profession.THIEF] - 1].status = Status.DEAD
    assert ctrl._chest_opener(party) == ("get", idx[Profession.FIGHTER])
    party.members[idx[Profession.FIGHTER] - 1].status = Status.DEAD
    assert ctrl._chest_opener(party) == ("get", idx[Profession.WIZARD])


def test_no_capture_planned_in_a_pond_pirates_never_reach(sosaria):
    """rules-c84c7c6 batch: parties took the moongate onto Exodus island and
    paced the 5-tile inner pond's shore for a pirate that can never appear
    there, until they starved. Capture waits need open water."""
    from py_exodus.autoplay.trip import terrain_for

    party = _make_party(level=25, marks=[1, 1, 1, 1], cards=[1, 1, 1, 1])
    terr = terrain_for(sosaria, party, 0)
    pond = terr.sea_comp[(10, 56)]
    assert terr.sea_comp_size[pond] < 100
    island = {(8, 54), (8, 55), (9, 55), (11, 55), (12, 54), (12, 55)}
    dest = Destination(frozenset({(10, 59)}), Transport.SHIP, "snake")
    plan = plan_trip(sosaria, party, 0, (12, 55), Transport.FOOT, dest, {},
                     pirates=frozenset(), pirates_spawn=True)
    assert plan is None or not any(
        leg.action == "CAPTURE" and leg.end in island for leg in plan.legs
    )


def test_capture_leg_hands_control_to_the_hunt_off_its_end_tile(
    pygame_setup, asset_mgr, monkeypatch
):
    """rules-c84c7c6 batch: the trip pulled the party back to the planned
    capture tile every turn, undoing each hunt/patrol step (pacing two
    tiles for thousands of turns). Off that tile but on the same land, the
    capture driver steers."""
    from py_exodus.autoplay.trip import Leg, TripPlan

    party = _make_party(level=10)
    party.x, party.y = 45, 20
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, random_encounters=False)
    ow.creatures = []
    ctrl = AutoPlayController(enabled=True)
    dest = Destination(frozenset({(33, 3)}), Transport.FOOT, "dig")
    end = (44, 20)
    assert end in ctrl._foot_reachable(ow.game_map, party, (45, 20))
    ctrl._trip = TripPlan(dest, [Leg(Transport.FOOT, end, "CAPTURE"), Leg(Transport.FOOT, (33, 3), "ARRIVE")], 0.0, 0)
    ctrl._trip_frigates = frozenset(ctrl._frigate_costs(party, ow))
    ctrl._trip_planned_at = ctrl._ow_turn
    calls = []
    monkeypatch.setattr(ctrl, "_off_route", lambda *a, **k: False)
    monkeypatch.setattr(ctrl, "_drive_capture", lambda *a, **k: calls.append(a[4]) or pygame.K_SPACE)
    ctrl._trip_drive(None, ow, ow.game_map, party, 45, 20, 0, dest)
    assert calls == [(45, 20)]


def test_terrain_sees_the_snake_turn_to_water_after_evocare():
    """rules-f162646: the terrain cache keyed on id(gmap) kept the serpent
    after EVOCARE, so 4-card parties found no route to Exodus and starved."""
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    pygame.init()
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.trip import terrain_for
    from py_exodus.screens.overworld import OverworldScreen

    import random

    rng_state = random.getstate()  # later tests depend on the global RNG
    try:
        am = batch._assets()
        party = batch.build_party()
        ow = OverworldScreen(party=party, map_id=0, asset_mgr=am)
        gmap = ow.game_map
        assert (10, 58) not in terrain_for(gmap, party, 0).sea_comp
        ow._replace_tile("water", 10, 57)
        ow._replace_tile("water", 10, 58)
        assert (10, 58) in terrain_for(gmap, party, 0).sea_comp
    finally:
        random.setstate(rng_state)


def test_strong_party_walks_up_to_a_pirate_and_attacks(pygame_setup, asset_mgr):
    """User report 2026-11-22: a 25/25/19/25 party two tiles west of a
    castle stepped out of a pirate's lane and straight back in, taking hits,
    instead of walking round and killing it. A strong party now hunts any
    pirate it can reach from land within a few steps."""
    party = _make_party(level=25, marks=[1, 1, 1, 1], gold=9000, food=1000, x=44, y=20)
    sm, ow = _overworld(asset_mgr, party)
    gmap = ow.game_map
    # A pirate on water whose nearest land neighbour is 3+ steps away.
    spot = None
    for y in range(5, 60):
        for x in range(5, 60):
            if not can_move_to(gmap, x, y, Transport.SHIP):
                continue
            for lx, ly in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not can_move_to(gmap, lx, ly, Transport.FOOT):
                    continue
                # a land tile 3 steps away along land
                for sx, sy in ((lx - 3, ly), (lx + 3, ly), (lx, ly - 3), (lx, ly + 3)):
                    line = [((lx * (3 - i) + sx * i) // 3, (ly * (3 - i) + sy * i) // 3) for i in range(4)]
                    if all(can_move_to(gmap, a, b, Transport.FOOT) for a, b in line):
                        spot = ((x, y), (sx, sy))
                        break
                if spot:
                    break
            if spot:
                break
        if spot:
            break
    assert spot is not None
    (pxr, pyr), (party.x, party.y) = spot
    ow.creatures = [_pirate(pxr, pyr)]
    ctrl = AutoPlayController(enabled=True)
    arrows = (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT)
    for _ in range(8):  # ctrl.step delivers each key, so the party moves
        ctrl._key_queue.clear()
        before = (party.x, party.y)
        key = ctrl.step(sm)
        if key == pygame.K_a:
            assert abs(before[0] - pxr) + abs(before[1] - pyr) == 1
            return
        assert key in arrows, pygame.key.name(key)
    raise AssertionError("never closed on the pirate")


def test_shrine_caps_come_from_the_members_race():
    """Stat caps live on the race (Race.max_wis...). Reading member.max_wis
    defaulted every cap to 99: a Human Cleric at WIS 75 kept paying the
    shrine 100 gold a point for nothing, and the Thief dex-74 rule never
    fired (max_dex read as 0)."""
    from py_exodus.autoplay.planner import member_needs_shrine_stat, stat_cap
    from py_exodus.constants import Race
    from py_exodus.entities.character import Character

    cleric = Character("C", None, Race.HUMAN, Profession.CLERIC, strength=15, dexterity=15, intelligence=15, wisdom=75)
    assert stat_cap(cleric, "max_wis") == 75
    assert not member_needs_shrine_stat(cleric, "wisdom", "max_wis")
    bobbit = Character("B", None, Race.BOBBIT, Profession.CLERIC, strength=15, dexterity=15, intelligence=15, wisdom=75)
    assert member_needs_shrine_stat(bobbit, "wisdom", "max_wis")
    thief = Character("T", None, Race.HUMAN, Profession.THIEF, strength=15, dexterity=25, intelligence=15, wisdom=15)
    assert stat_cap(thief, "max_dex") >= 74


def test_shrine_plan_order_for_the_batch_party():
    """User request 2026-11-22: one buying order for every Ambrosia visit.
    ALCORT wisdom, DEX 40 for all (always hit), the 50-MP spells, the
    multi-death bolts, STR, the rest of the MP pools, trap-proof DEX last;
    every target clamped to the member's race cap."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import next_shrine_goal

    party = batch.build_party()  # Elf Thief, Dwarf Fighter, Bobbit Cleric, Fuzzy Wizard
    steps = []
    while (g := next_shrine_goal(party)) is not None:
        idx, stat, _cap, target = g
        steps.append((party.members[idx].profession.name, stat, target))
        setattr(party.members[idx], stat, target)
    assert steps == [
        # Cleric WIS to the race cap first (user ruling 2026-11-22): ALCORT
        # and the biggest APPAR UNEM pool for faster raids.
        ("CLERIC", "wisdom", 99),
        ("FIGHTER", "dexterity", 40),
        ("THIEF", "dexterity", 40),
        ("CLERIC", "dexterity", 40),
        ("WIZARD", "dexterity", 40),
        ("WIZARD", "intelligence", 50),
        ("WIZARD", "intelligence", 75),
        ("FIGHTER", "strength", 99),
        ("THIEF", "strength", 75),
        ("WIZARD", "intelligence", 99),
        ("CLERIC", "strength", 75),
        ("WIZARD", "strength", 25),
        ("THIEF", "dexterity", 74),
    ]


def test_return_trips_for_stats_and_no_pointless_raids():
    """User ruling 2026-11-22: with all cards, raid Death Gulch and sail
    back to Ambrosia for the plan's return-trip steps (DEX 40 all, caster
    MP maxed, in plan order); once those are bought, stop raiding."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import (
        RETURN_TRIP_STEPS,
        SHRINE_PLAN,
        gold_has_a_use,
        next_shrine_goal,
        return_trip_gold,
    )

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys = 20, 300, 2
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        m.gold = 0
    assert gold_has_a_use(party)
    need = return_trip_gold(party)
    assert 0 < need <= 8500  # always reachable under the 9000 raid cap
    party.members[0].gold = need - 1
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
    party.members[0].gold = need
    assert evaluate_goal(party, 0) == Goal.SAIL_WHIRLPOOL
    for m in party.members:
        m.food = 100
    # The food to buy is part of the target (so buying it never drops the
    # party back under): with that gold too, it stocks up.
    party.members[0].gold = return_trip_gold(party)
    assert evaluate_goal(party, 0) == Goal.BUY_FOOD
    # Buy every return-trip step: no more trips, no more raiding.
    while (g := next_shrine_goal(party, RETURN_TRIP_STEPS)) is not None:
        setattr(party.members[g[0]], g[1], g[3])
    assert return_trip_gold(party) == 0
    assert not gold_has_a_use(party)
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL  # levels, not stats
    assert SHRINE_PLAN[RETURN_TRIP_STEPS - 1][1:] == ("intelligence", "max_int", 99)


def test_card_trip_carries_keys_enough_to_reach_the_moons_card():
    """User live trace 2026-11-22: card trips sailed in with 4 keys; the
    Moons card is behind (45,17), (50,6) and (11,6), the exit rule fired on
    the last key five tiles short, and four visits in a row came back empty."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import ambrosia_trip_gold

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys, m.gold = 25, 300, 0, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 0, 1]  # Moons missing
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    party.members[0].gold = ambrosia_trip_gold(party)
    party.members[0].keys = 4
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS
    party.members[0].keys = 8
    assert evaluate_goal(party, 0) == Goal.SAIL_WHIRLPOOL


def test_grind_patrol_widens_when_nothing_shows_up(pygame_setup):
    """User 2026-11-22: circling Britain forever starves the party when no
    monster comes (batch 775884a seeds 35, 50, 60: ~1,900 patrol steps, no
    fight, food to 0). After _GRIND_QUIET_LIMIT quiet moves the level-1 party
    takes the wide Sosaria patrol; a monster in range resets it."""
    from py_exodus.autoplay.controller import _SOSARIA_PATROL, AutoPlayController
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager(assets_dir="assets")
    am.load_tiles()
    am.load_xml_definitions()
    party = _make_party(level=1)
    party.x, party.y = 42, 18  # the first point of the Britain loop
    ow = OverworldScreen(party=party, asset_mgr=am, start_x=42, start_y=18, random_encounters=False)
    ow.creatures = []
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    living = list(party.members)

    key = ctrl._grind_local(sm, ow, ow.game_map, party, 42, 18, living)
    assert key in (pygame.K_LEFT, pygame.K_UP)  # toward (38,17)
    assert ctrl._grind_quiet == 1
    ctrl._grind_quiet = ctrl._GRIND_QUIET_LIMIT
    ctrl._patrol_idx = 0
    key = ctrl._grind_local(sm, ow, ow.game_map, party, 42, 18, living)
    assert _SOSARIA_PATROL[0] == (44, 22) and key in (pygame.K_RIGHT, pygame.K_DOWN)
    ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 44, "y": 22}]  # reachable
    ctrl._grind_local(sm, ow, ow.game_map, party, 42, 18, living)
    assert ctrl._grind_quiet == 0

    # A hurt party skips the chase, but its patrol moves still count (user
    # live trace 2026-11-22: a hurt level-2 Cleric kept the count at 0).
    ow.creatures = []
    party.members[2].hp = party.members[2].max_hp // 2
    ctrl._grind_quiet = 0
    for _ in range(3):
        ctrl._grind_local(sm, ow, ow.game_map, party, 42, 18, living)
    assert ctrl._grind_quiet == 3


def test_resurrection_money_comes_before_food_that_can_wait():
    """Batch 775884a seed 3: the Cleric dead, 490 gold of the 500 to raise
    her, food 74 each: the party bought food, fell further short, and wiped.
    Food waits until someone is close to starving."""
    from py_exodus.constants import Status

    party = _make_party(level=3)
    for m in party.members:
        m.food, m.gold = 74, 0
    cleric = next(m for m in party.members if m.profession == Profession.CLERIC)
    cleric.status, cleric.hp = Status.DEAD, 0
    party.members[0].gold = 490
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
    party.members[0].food = 30  # close to starving: food first
    assert evaluate_goal(party, 0) == Goal.BUY_FOOD
    party.members[0].food = 74
    party.members[0].gold = 500
    assert evaluate_goal(party, 0) == Goal.RESURRECT_DEAD


def test_fawn_is_not_castle_exodus_for_the_planner():
    """Batch 775884a seed 16 (STEP_CAP, all level 25): the planner took map
    12 (Fawn) for the castle, so inside Fawn the goal was CONQUER_EXODUS and
    outside it BUY_KEYS for a return trip; the party walked in and out of
    Fawn's west edge for 11k steps. Only Castle Exodus (map 2) holds the
    party to the conquest."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import return_trip_gold

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys, m.gold = 25, 300, 0, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    party.members[0].gold = return_trip_gold(party)
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS
    assert evaluate_goal(party, 12) == Goal.BUY_KEYS
    assert evaluate_goal(party, 2) == Goal.CONQUER_EXODUS
    party.members[1].level = 20
    party.members[0].gold = 0
    assert evaluate_goal(party, 12) == Goal.GRIND_AND_LEVEL
    assert evaluate_goal(party, 2) == Goal.CONQUER_EXODUS


def test_return_trip_buys_keys_first_and_keeps_one_to_leave_ambrosia():
    """Live run 2026-11-22: a return trip sailed in with no keys; the last
    one went on the way in, the intelligence shrine (behind (10,6)) and the
    exit basin (behind the water door (39,61)) were both locked, and the
    party was stranded on Ambrosia."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import needs_shrine_stats, return_trip_gold

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys = 25, 300, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        m.gold = 0
    party.members[0].gold = return_trip_gold(party)
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS
    party.members[0].keys = 7
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS  # a visit can spend 5
    party.members[0].keys = 8
    assert evaluate_goal(party, 0) == Goal.SAIL_WHIRLPOOL
    # On Ambrosia, shopping left to do: shop while keys remain, leave on the last.
    assert needs_shrine_stats(party)
    party.members[0].keys = 2
    assert evaluate_goal(party, 13) == Goal.AMBROSIA_CARDS_SHRINES
    party.members[0].keys = 1
    assert evaluate_goal(party, 13) == Goal.EXIT_AMBROSIA


def test_ship_escape_sails_on_through_the_lane_rather_than_sit_under_fire():
    """Batch be64d73 seed 0: in Ambrosia's water door (walls N and S), the
    pirate 2 tiles astern and upwind, the only open tile still in its lane:
    the ship waited and was sunk with the party aboard."""
    party = _make_party(level=5, transport=Transport.SHIP)
    party.wind_direction = Direction.WEST  # can't sail east, toward the pirate
    th = compute_threats(_Grid, party, [_pirate(12, 10)])
    pos = (10, 10)
    open_water = {(9, 10), (11, 10)}  # walls north and south
    move = ship_escape(_Grid, party, pos, th, lambda x, y: (x, y) in open_water,
                       prefer_engage=True)
    assert th.unsafe_end((9, 10))  # the only way out is still in the lane
    # Never wait under fire: LairWare's cannon bears on the pirate astern
    # (any direction), so the ship shoots back rather than sit.
    assert move.key == "fire" and move.direction == Direction.EAST


def test_the_tested_party_is_lairware_legal_and_shared_with_the_reset_script(tmp_path):
    """User 2026-11-22: live runs start from scripts/reset_new_game.py; the
    batches built the same four with 60 points each, over LairWare's 50
    (UltimaMacIF.c:2373). One definition now serves both."""
    import importlib.util

    from py_exodus.autoplay.batch import PARTY_SETUP, build_party
    from py_exodus.save_system import SaveSystem

    assert all(sum(row[4:]) == 50 for row in PARTY_SETUP)
    spec = importlib.util.spec_from_file_location("reset_new_game", "scripts/reset_new_game.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.reset_new_game(tmp_path)
    roster = SaveSystem.load_roster(tmp_path / "roster.json")
    stats = lambda c: (c.name, c.race, c.profession, c.strength, c.dexterity, c.intelligence, c.wisdom)
    assert [stats(c) for c in roster] == [stats(m) for m in build_party().members]


def test_autoplay_on_an_empty_roster_creates_the_tested_party(pygame_setup):
    """User 2026-11-22: with no roster, autoplay creates the same party as
    scripts/reset_new_game.py (it used to roll four Human Fighters)."""
    from py_exodus.autoplay.batch import build_party
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.entities.party import Party
    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager(assets_dir="assets")
    am.load_tiles()
    am.load_xml_definitions()
    party = Party()
    rs = RosterScreen(party=party, roster=[], asset_mgr=am)
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(rs)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(600):
        if len(party.members) == 4:
            break
        ctrl.step(sm)
    stats = lambda c: (c.name, c.race, c.profession, c.strength, c.dexterity, c.intelligence, c.wisdom)
    assert [stats(m) for m in party.members] == [stats(m) for m in build_party().members]


def test_a_cleric_who_can_alcort_cures_poison_instead_of_the_healer(pygame_setup):
    """User 2026-11-22: a poisoned party walked to a healer although its
    Cleric had WIS 35 (ALCORT's 35 MP). With the MP coming back before the
    poison bites, the party carries on and ALCORT is cast on the spot."""
    from py_exodus.constants import Status

    party = _make_party(level=5, food=300, gold=500, marks=[1, 0, 0, 0])
    cleric = next(m for m in party.members if m.profession == Profession.CLERIC)
    cleric.max_mp, cleric.mp = 35, 20  # 15 turns of MP on the surface
    victim = party.members[0]
    victim.status, victim.hp = Status.POISONED, 200
    assert evaluate_goal(party, 0) != Goal.CURE_POISON
    victim.hp = 30  # would drop under the margin before the MP is back
    assert evaluate_goal(party, 0) == Goal.CURE_POISON
    victim.hp = 200
    cleric.max_mp = 30  # can't reach ALCORT: the healer
    assert evaluate_goal(party, 0) == Goal.CURE_POISON


def test_one_laggard_does_not_hold_the_party_from_the_mark_of_kings(pygame_setup):
    """Batch 3bb71ce b1: the planner ground until all four were level 5;
    past 5 needs the Mark of Kings, so the three at 5 earned nothing while
    the Cleric's rare kills crawled, and 9 of 10 seeds starved at 5/5/2/5."""
    party = _make_party(level=5, food=300, gold=60)
    cleric = next(m for m in party.members if m.profession == Profession.CLERIC)
    cleric.level = 2
    assert evaluate_goal(party, 0) in (Goal.GET_MARK_KINGS, Goal.BUY_GEMS, Goal.BUY_TORCHES)
    party.members[0].level = 4  # two below 5: keep grinding
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL


def test_a_finished_party_short_of_stat_gold_buys_keys_and_raids(pygame_setup):
    """User live trace 2026-11-22 (trace_20261122-151023): all cards and
    marks, level 25+, 3 keys. Death Gulch needs 4, so it never raided again;
    the return trip needed more gold and the castle waits for the stat plan,
    so 5,549 gold went on food until the party was broke. A raid needs
    keys and the guards' bribe gold."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.autoplay.planner import return_trip_cost, return_trip_gold

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys, m.gold = 25, 300, 0, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    assert return_trip_cost(party) > 0
    party.members[0].keys = 3
    party.members[0].gold = 2000
    assert party.gold < return_trip_gold(party)
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS
    party.members[0].keys = 4
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
    living = list(party.members)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl._wants_death_gulch(party, living, 0, Goal.GRIND_AND_LEVEL)
    # A raid needs gold too: 400 for the guards' bribes (user 2026-11-22).
    party.members[0].gold = 399
    assert not ctrl._wants_death_gulch(party, living, 0, Goal.GRIND_AND_LEVEL)
    # Keys are bought only while the bribe gold survives the purchase.
    party.members[0].keys = 3
    party.members[0].gold = 449
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
    party.members[0].gold = 450
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS


def test_return_trip_raids_only_for_what_the_stats_cost(pygame_setup):
    """User live run 2026-11-22: 11 INT points (1,100 gold) short of the
    plan, 4,000 gold in hand, still raiding Death Gulch toward 8,500. The
    raid stops at what the rest of the plan costs, and buying the trip's
    keys doesn't drop the party back under that."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.controller import _DEATH_GULCH_GOLD_CAP, AutoPlayController
    from py_exodus.autoplay.planner import (
        raid_gold_target, return_trip_cost, return_trip_gold, stat_cap,
    )

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys, m.gold = 25, 300, 0, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        for attr, cap in (("strength", "max_str"), ("dexterity", "max_dex"),
                          ("intelligence", "max_int"), ("wisdom", "max_wis")):
            setattr(m, attr, stat_cap(m, cap))
    wizard = party.members[3]
    wizard.intelligence -= 11
    assert return_trip_cost(party) == 1100
    party.members[0].keys = 4
    party.members[0].gold = 4000
    target = return_trip_gold(party)
    assert target < 2000
    assert raid_gold_target(party, _DEATH_GULCH_GOLD_CAP) == target
    living = list(party.members)
    ctrl = AutoPlayController(enabled=True)
    assert not ctrl._wants_death_gulch(party, living, 0, Goal.GRIND_AND_LEVEL)
    # Short of keys: buys them, and the purchase keeps it over the target.
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS
    party.members[0].keys = 8
    party.members[0].gold -= 200
    assert party.gold >= return_trip_gold(party)
    assert evaluate_goal(party, 0) != Goal.GRIND_AND_LEVEL


def test_return_trip_food_run_stays_over_the_trip_gold(pygame_setup):
    """User live trace 2026-11-22 (trace_20261122-154730): 1,752 gold was
    enough for the last return trip, but the food run filled everyone to
    400 and left 762, so the party went back to Death Gulch. A return-trip
    food run buys only the entry food the target counts."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import AMBROSIA_ENTRY_FOOD, return_trip_gold, stat_cap
    from py_exodus.screens.town import TownScreen

    am = AssetManager("data")
    am.load_all()
    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys, m.gold = 25, 150, 2, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        for attr, cap in (("strength", "max_str"), ("dexterity", "max_dex"),
                          ("intelligence", "max_int"), ("wisdom", "max_wis")):
            setattr(m, attr, stat_cap(m, cap))
    party.members[3].intelligence -= 11
    party.members[0].gold = return_trip_gold(party) + 100
    assert evaluate_goal(party, 3) == Goal.BUY_FOOD

    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=3, start_x=48, start_y=49)
    sm.set_screen(ts)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(300):
        ctrl.step(sm)
        if evaluate_goal(party, 3) != Goal.BUY_FOOD:
            break
    assert all(m.food >= AMBROSIA_ENTRY_FOOD for m in party.members)
    assert all(m.food < AMBROSIA_ENTRY_FOOD + 50 for m in party.members)
    assert party.gold >= return_trip_gold(party)


def test_death_gulch_raid_starts_with_a_full_caster(pygame_setup, asset_mgr):
    """User 2026-11-22: raids stand still waiting for APPAR UNEM MP, which
    comes back +1 every 4 turns inside and +1 a turn on the surface. At the
    Death Gulch gate the party passes turns until the caster is full."""
    from py_exodus.autoplay import batch

    party = batch.build_party()
    party.x, party.y = 56, 31
    sm, ow = _overworld(asset_mgr, party)
    ctrl = AutoPlayController(enabled=True)
    keys: list[int] = []
    ctrl._emit_key = lambda _sm, key: keys.append(key) or 0
    _dest, enter = ctrl._portal_dest(sm, ow, {(56, 31)}, "death_gulch")
    cleric = party.members[2]
    cleric.max_mp, cleric.mp = 70, 6
    enter()
    assert keys[-1] == pygame.K_SPACE
    cleric.mp = 70
    enter()
    assert keys[-1] == pygame.K_e


def _walk_dungeon(dmap, start, facing, goals, penalty):
    """Follow find_dungeon_step on one level; return the tiles entered."""
    from py_exodus.autoplay.nav import find_dungeon_step
    from py_exodus.world.dungeon import turn_left_dir, turn_right_dir

    x, y, z = start
    entered = []
    for _ in range(100):
        if (x, y, z) in goals:
            return entered
        key = find_dungeon_step(dmap, x, y, z, facing, goals, penalty_tiles=penalty)
        if key == pygame.K_UP:
            x, y = x + facing.dx, y + facing.dy
            entered.append((x, y, z))
        elif key == pygame.K_LEFT:
            facing = turn_left_dir(facing)
        elif key == pygame.K_RIGHT:
            facing = turn_right_dir(facing)
        else:
            raise AssertionError(f"unexpected key {key}")
    raise AssertionError("never arrived")


def test_dungeon_route_goes_around_gremlins():
    """Gremlins take 100 food from a member per tile (batch 1c7525f: about
    13 of 49 wipes starved after the Fire dungeon). With a way around, the
    party takes it; with none, it crosses as few as it must."""
    from py_exodus.world.map import DungeonMap, DungeonTile

    dmap = DungeonMap(id=99, name="TestDungeon", width=8, height=8, levels=8)
    dmap.tiles = [
        [
            [DungeonTile.WALL if x in (0, 7) or y in (0, 7) else DungeonTile.FLOOR for x in range(8)]
            for y in range(8)
        ]
        for _z in range(8)
    ]
    gremlins = {(3, 3, 0), (4, 3, 0)}
    for gx, gy, gz in gremlins:
        dmap.set_tile(gx, gy, gz, DungeonTile.GREMLINS)
    start, goal = (1, 3, 0), {(6, 3, 0)}
    # Plain BFS walks straight through both.
    assert gremlins <= set(_walk_dungeon(dmap, start, Direction.EAST, goal, None))
    # With them as penalties: around, none entered.
    assert not gremlins & set(_walk_dungeon(dmap, start, Direction.EAST, goal, gremlins))
    # A corridor with no way around: still arrives, crossing only those.
    for y in range(1, 7):
        if y != 3:
            for x in (3, 4):
                dmap.set_tile(x, y, 0, DungeonTile.WALL)
    entered = _walk_dungeon(dmap, start, Direction.EAST, goal, gremlins)
    assert entered[-1] == (6, 3, 0) and set(entered) & gremlins == gremlins


def _room_dungeon(party, x=2, y=2):
    from py_exodus.screens.dungeon_screen import DungeonScreen
    from py_exodus.world.map import DungeonMap, DungeonTile

    dmap = DungeonMap(id=99, name="TestDungeon", width=8, height=8, levels=8)
    dmap.tiles = [
        [
            [DungeonTile.WALL if xx in (0, 7) or yy in (0, 7) else DungeonTile.FLOOR for xx in range(8)]
            for yy in range(8)
        ]
        for _z in range(8)
    ]
    ds = DungeonScreen(party=party, dungeon_map=dmap, start_x=x, start_y=y, start_z=0)
    ds.state.is_torch_on = True
    return ds, dmap


def test_dungeon_chest_underfoot_is_opened_with_appar_unem(pygame_setup):
    """User 2026-11-22: chests the party walks over in dungeons are opened
    (the safe way), never searched for. A Cleric with MP casts APPAR UNEM."""
    from py_exodus.autoplay import batch
    from py_exodus.world.map import DungeonTile

    party = batch.build_party()
    for m in party.members:
        m.food = 300
    cleric = party.members[2]
    cleric.max_mp, cleric.mp = 40, 40
    ds, dmap = _room_dungeon(party)
    dmap.set_tile(2, 2, 0, DungeonTile.CHEST)
    sm = StateMachine(asset_mgr=None, audio=None)
    sm.set_screen(ds)
    ctrl = AutoPlayController(enabled=True)
    ctrl._mapped_dungeon_levels.add((99, 0))
    gold0 = party.gold
    for _ in range(10):
        if dmap.get_tile(2, 2, 0) != DungeonTile.CHEST:
            break
        ctrl.step(sm)
    assert dmap.get_tile(2, 2, 0) != DungeonTile.CHEST
    assert cleric.mp == 35
    assert party.gold >= gold0
    assert all(m.status.name == "GOOD" for m in party.members)


def test_dungeon_chest_is_left_while_the_cleric_lacks_mp(pygame_setup):
    """With the APPAR UNEM caster alive but under 5 MP, the party walks on:
    no G (traps), no waiting for MP."""
    from py_exodus.autoplay import batch
    from py_exodus.world.map import DungeonTile

    party = batch.build_party()
    for m in party.members:
        m.food = 300
    party.members[2].max_mp, party.members[2].mp = 40, 2
    ds, dmap = _room_dungeon(party)
    dmap.set_tile(2, 2, 0, DungeonTile.CHEST)
    sm = StateMachine(asset_mgr=None, audio=None)
    sm.set_screen(ds)
    ctrl = AutoPlayController(enabled=True)
    ctrl._mapped_dungeon_levels.add((99, 0))
    keys: list[int] = []
    ctrl._emit_key = lambda _sm, key, **_kw: keys.append(key) or 0
    ctrl._step_dungeon(sm, ds)
    assert keys and keys[-1] not in (pygame.K_g, pygame.K_c)


def test_a_starving_member_turns_the_party_for_the_exit(pygame_setup, monkeypatch):
    """Batch 1c7525f: members hit 0 food on the Fire dungeon's level 4 and
    the party went on to level 7 for the Mark. Anyone at 0 food: leave."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay import controller as ctl
    from py_exodus.autoplay.nav import find_dungeon_step
    from py_exodus.world.map import DungeonTile

    party = batch.build_party()
    for m in party.members:
        m.food = 300
    ds, dmap = _room_dungeon(party, x=3, y=1)
    dmap.set_tile(6, 6, 0, DungeonTile.MARK_FIRE)
    monkeypatch.setattr(ctl, "evaluate_goal", lambda *_a, **_k: Goal.GET_REMAINING_MARKS)
    sm = StateMachine(asset_mgr=None, audio=None)
    sm.set_screen(ds)
    ctrl = AutoPlayController(enabled=True)
    ctrl._mapped_dungeon_levels.add((99, 0))
    keys: list[int] = []
    ctrl._emit_key = lambda _sm, key, **_kw: keys.append(key) or 0
    st = ds.state
    to_mark = find_dungeon_step(dmap, st.x, st.y, st.z, st.dir, {(6, 6, 0)})
    to_exit = find_dungeon_step(dmap, st.x, st.y, st.z, st.dir, {(1, 1, 0)})
    assert to_mark != to_exit
    ctrl._step_dungeon(sm, ds)
    assert keys[-1] == to_mark
    party.members[1].food = 0
    ctrl._step_dungeon(sm, ds)
    assert keys[-1] == to_exit


def test_no_flee_into_a_town_the_party_would_walk_straight_out_of(pygame_setup, asset_mgr):
    """Batch 1c7525f seed 38: hurt and chased beside the Exotic dig site,
    the party fled into town 12 (30, 2) to rest. Near the site the food
    check waits; inside the town it fires, BUY_FOOD walks out (town 12 sells
    none), and in and out it went for 3,600 steps until it starved."""
    party = _make_party(level=5, marks=[1, 0, 0, 0], gold=40, food=224, x=30, y=2)  # at town 12
    for m in party.members:
        m.food = 56
    _hurt(party)
    assert evaluate_goal(party, 0) != Goal.BUY_FOOD
    assert evaluate_goal(party, 12) == Goal.BUY_FOOD
    sm, ow = _overworld(asset_mgr, party)
    ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 30, "y": 8}]
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert not ctrl._fleeing
    assert ctrl._trip is None or ctrl._trip.dest.label != "rest"


def test_green_parties_dont_chase_dragons(pygame_setup):
    """Batch 1c7525f: about 15 of 49 wipes were level 1-5 parties walking up
    to dragons while grinding. Below level 8 the grind leaves them alone
    (user OK 2026-11-22); from level 8 a dragon is a target like any other."""
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    am = AssetManager(assets_dir="assets")
    am.load_tiles()
    am.load_xml_definitions()
    for level, chased in ((5, False), (8, True)):
        party = _make_party(level=level)
        party.x, party.y = 42, 18
        ow = OverworldScreen(party=party, asset_mgr=am, start_x=42, start_y=18, random_encounters=False)
        ow.creatures = [{"tile_name": "dragon", "tile": "dragon", "x": 44, "y": 22}]
        sm = StateMachine(asset_mgr=am, audio=None)
        sm.set_screen(ow)
        ctrl = AutoPlayController(enabled=True)
        ctrl._grind_quiet = 5
        ctrl._grind_local(sm, ow, ow.game_map, party, 42, 18, list(party.members))
        assert (ctrl._grind_quiet == 0) is chased, level


def test_pirate_capture_escape_keeps_its_progress(pygame_setup, asset_mgr):
    """Batch 1c7525f seed 2: a pirate at (6, 28), the party four tiles south
    on the coast. A mountain at (7, 32) leaves (6, 31), in the lane, as the
    only way north. The capture stepped in, the lane escape broke a tie back
    to (6, 32), and in and out it went, a broadside each time, until the
    party died. The escape now keeps going (7, 31) toward the hunt target."""
    from py_exodus.autoplay.controller import _DIR_TO_KEY

    party = _make_party(level=5, x=6, y=32)
    sm, ow = _overworld(asset_mgr, party)
    gmap = ow.game_map
    ow.creatures = [_pirate(6, 28)]
    th = compute_threats(gmap, party, ow.creatures)
    assert th.unsafe_end((6, 31)) and not th.unsafe_end((6, 32)) and not th.unsafe_end((7, 31))
    ctrl = AutoPlayController(enabled=True)
    keys: list[int] = []
    ctrl._emit_key = lambda _sm, key, **_kw: keys.append(key) or 0
    ctrl._move_toward_off_lanes(sm, gmap, party, (6, 32), {(6, 29)}, th)
    assert keys[-1] == _DIR_TO_KEY[Direction.NORTH]  # the one way on
    party.x, party.y = 6, 31
    ctrl._threat_escape(sm, ow, party, 6, 31)
    assert keys[-1] == _DIR_TO_KEY[Direction.EAST]  # on toward (6, 29), not back


def test_buying_trip_keys_never_drops_a_capped_trip_back_to_raiding():
    """Batch ccd5f52 seeds 100, 101, 105, 108: stats costing more than one
    trip capped the target at 8,500; with 8,516 gold and 3 keys the party
    bought one key (8,466), fell under, raided (using keys), came back short
    of keys, and so on for ~100,000 steps."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.planner import return_trip_cost, return_trip_gold

    party = batch.build_party()
    for m in party.members:
        m.level, m.food, m.keys, m.gold = 25, 300, 0, 0
        m.marks, m.cards = [1, 1, 1, 1], [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    assert return_trip_cost(party) > 9000  # capped
    party.members[0].keys = 3
    party.members[0].gold = return_trip_gold(party)
    for _ in range(5):
        assert evaluate_goal(party, 0) == Goal.BUY_KEYS
        party.members[0].keys += 1
        party.members[0].gold -= 50
        assert party.gold >= return_trip_gold(party)
    assert evaluate_goal(party, 0) != Goal.GRIND_AND_LEVEL


def test_lane_escape_leaves_a_frigate_about_to_be_boarded_to_the_trip(pygame_setup, asset_mgr):
    """Batch ccd5f52 seed 107: the frigate at (31, 3) beside the Exotic dig
    site sat in a dragon's lane. Each arrival the lane escape stepped back
    off it before the trip could board; off and on for ~1,000 steps, the
    party stranded on the island until it starved. Boarding is the way out."""
    party = _make_party(level=5, x=31, y=3)
    party.dynamic_objects = [{"tile": "frigate", "x": 31, "y": 3}]
    party.objects_map_id = 0
    sm, ow = _overworld(asset_mgr, party)
    gmap = ow.game_map
    ow.creatures = [{"tile_name": "dragon", "tile": "dragon", "x": 31, "y": 6}]
    th = compute_threats(gmap, party, ow.creatures)
    assert th.unsafe_end((31, 3))
    ctrl = AutoPlayController(enabled=True)
    ctrl._threats = th
    dest = Destination(frozenset({(30, 2)}), Transport.FOOT, "guild")
    ctrl._replan(gmap, party, ow, 0, (31, 3), Transport.FOOT, dest)
    assert ctrl._trip is not None and ctrl._trip.legs[0].action == "B"
    keys: list[int] = []
    ctrl._emit_key = lambda _sm, key, **_kw: keys.append(key) or 0
    assert ctrl._threat_escape(sm, ow, party, 31, 3) is None
    assert not keys
