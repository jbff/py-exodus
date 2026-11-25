"""Pirate hunt commits to one land tile (batch bbceab3 seeds 79/85).

A level-25 party on Ambrosia wanting a ship for the dexterity shrine hunted
a pirate that shadows it along the coast. Re-aiming at the tiles next to the
pirate every turn flipped between the routes north and south of a ridge, so
the party paced (6,56)-(6,59) for 33k steps and starved.
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from py_exodus.autoplay import batch
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.planner import next_shrine_goal
from py_exodus.constants import ArmorType, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import tile_effects


def test_pirate_hunt_on_ambrosia_reaches_the_pirate_instead_of_pacing():
    pygame.init()
    pygame.font.init()
    rng = random.getstate()
    trng = tile_effects._rng.getstate()
    try:
        random.seed(1)
        tile_effects._rng.seed(1)
        batch._seed_dungeon_rngs()
        am = batch._assets()
        party = batch.build_party()
        for m in party.members:
            m.level = 25
            m.max_hp = m.hp = 2500
            m.food = 300
            m.keys = 2
            m.gold = 2604
            m.marks = [1, 1, 1, 1]
            m.cards = [1, 1, 1, 1]
            m.weapon = WeaponType.EXOTIC
            m.armor = ArmorType.EXOTIC
        from py_exodus.autoplay.planner import stat_cap
        party.members[2].wisdom = stat_cap(party.members[2], "max_wis")  # plan step 1 done
        sm = StateMachine(asset_mgr=am, audio=None)
        scr = OverworldScreen(party=party, asset_mgr=am)
        sm.set_screen(scr)
        party.x, party.y = 50, 13
        party.transport = Transport.SHIP
        scr._check_whirlpool_engulf()
        assert next_shrine_goal(party)[1] == "dexterity"  # needs a ship
        party.x, party.y = 6, 57  # where seeds 79/85 paced
        ctrl = AutoPlayController(enabled=True, step_interval=0.08)
        sm.autoplay_enabled = True
        steps = 0
        orig = ctrl.step

        def counted(s):
            nonlocal steps
            steps += 1
            return orig(s)

        ctrl.step = counted
        while steps < 600 and party.transport != Transport.SHIP:
            ctrl.update(batch.FRAME_DT, sm)
            sm.update(batch.FRAME_DT)
        assert party.transport == Transport.SHIP, (steps, party.x, party.y)
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)


def test_open_moongate_is_taken_even_from_a_pirate_lane():
    """Live trace 2026-11-22: a level-5 party on the strip reachable only by
    moongate (57,46) needed food; a pirate offshore put the tile beside the
    gate in its firing lane, the threat escape stepped out of the lane at
    every opening, and the party paced for 1,800 steps until it starved."""
    pygame.init()
    pygame.font.init()
    rng = random.getstate()
    try:
        random.seed(1)
        am = batch._assets()
        p = batch.build_party()
        for m in p.members:
            m.level = 5
            m.max_hp = 550
            m.hp = 500
            m.food = 70
            m.gold = 88
            m.marks = [1, 1, 1, 1]
            m.gems = 2
            m.keys = 0
            m.weapon = WeaponType.EXOTIC
            m.armor = ArmorType.EXOTIC
        sm = StateMachine(asset_mgr=am, audio=None)
        ow = OverworldScreen(party=p, asset_mgr=am)
        sm.set_screen(ow)
        p.x, p.y = 58, 44  # Dungeon 19's door, on the gate-only strip
        p.transport = Transport.FOOT
        ow.creatures = [c for c in ow.creatures if abs(c["x"] - 58) + abs(c["y"] - 44) > 12] + [
            {"tile_name": "pirate", "tile": "pirate", "x": 61, "y": 44}
        ]
        ctrl = AutoPlayController(enabled=True)
        sm.autoplay_enabled = True
        for _ in range(200):
            ctrl.step(sm)
            sm.update(0.1)
            if not (54 <= p.x <= 59 and 43 <= p.y <= 47):
                break
        assert not (54 <= p.x <= 59 and 43 <= p.y <= 47), (p.x, p.y)
    finally:
        random.setstate(rng)


def test_capture_crosses_lanes_to_a_pinned_pirate_instead_of_pacing():
    """Live trace 2026-11-24 (trace_20261124-111105): on Ambrosia, on foot,
    for the intelligence shrine, the trip captures a ship in the north bay.
    Two pirates sit at the bay's east tip, (35,10) and (36,11). Under
    LairWare's MoveMonsters (UltimaMisc.c:1191-1236) each tries the diagonal,
    vertical and horizontal step toward the party, onto water only
    (ValidMonsterDir, 263-272); from the tip all three are land, so they
    never come closer and fire instead (moveshoot). Every way to a tile next
    to them crosses a lane. The capture stepped (38,8) -> (38,9) into a lane,
    the lane escape found no lane-free walk on and stepped back north, and
    so on for 7,000 steps under fire until the user quit."""
    pygame.init()
    pygame.font.init()
    rng = random.getstate()
    trng = tile_effects._rng.getstate()
    try:
        random.seed(1)
        tile_effects._rng.seed(1)
        batch._seed_dungeon_rngs()
        am = batch._assets()
        party = batch.build_party()
        from py_exodus.autoplay.planner import stat_cap
        for m, lv in zip(party.members, (20, 16, 7, 13)):  # the trace's party
            m.level = lv
            m.max_hp = m.hp = lv * 100 + 50
            m.food = 300
            m.keys = 2
            m.gold = 1425
            m.marks = [1, 1, 1, 1]
            m.cards = [1, 1, 1, 1]
            m.weapon = WeaponType.EXOTIC
            m.armor = ArmorType.EXOTIC
            m.wisdom = stat_cap(m, "max_wis")
            m.dexterity = stat_cap(m, "max_dex")
        sm = StateMachine(asset_mgr=am, audio=None)
        scr = OverworldScreen(party=party, asset_mgr=am)
        sm.set_screen(scr)
        pool = next(c for c in scr.creatures if c["tile_name"] == "whirlpool")
        party.x, party.y = pool["x"], pool["y"]
        party.transport = Transport.SHIP
        scr._check_whirlpool_engulf()
        assert next_shrine_goal(party)[1] == "intelligence"  # (6,6): by ship
        scr.creatures = [c for c in scr.creatures if (c["x"], c["y"]) != (35, 10)] + [
            {"tile_name": "pirate", "tile": "pirate", "x": 35, "y": 10},
            {"tile_name": "pirate", "tile": "pirate", "x": 36, "y": 11},
        ]
        party.x, party.y = 38, 8
        fights = []
        orig_fight = scr._trigger_combat

        def fight(name, creature=None):
            fights.append((name, (creature["x"], creature["y"]), (party.x, party.y)))
            return orig_fight(name, creature)

        scr._trigger_combat = fight
        ctrl = AutoPlayController(enabled=True)
        sm.autoplay_enabled = True
        seen = []
        for _ in range(40):
            ctrl.step(sm)
            sm.update(0.1)
            seen.append((party.x, party.y))
            if fights:
                break
        assert fights, seen
        name, (cx, cy), (fx, fy) = fights[0]
        assert name == "pirate", fights
        assert max(abs(cx - fx), abs(cy - fy)) == 1, fights  # adjacent
        # The fight won, the party boards the pirate's frigate.
        for _ in range(400):
            ctrl.step(sm)
            sm.update(0.1)
            if party.transport == Transport.SHIP:
                break
        assert party.transport == Transport.SHIP, (party.x, party.y)
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)


def _shadow_run(cleric_hp: int, steps: int = 40):
    """Live trace 2026-11-25 (trace_20261125-163401, steps 16258-25469): on
    Sosaria, on foot, capturing a ship for DIG_EXOTICS, the party paced
    (45,35)-(46,35) for ~9,000 steps. A pirate on the bay at row 39 shadows
    the party's column; the straight walk south to the engage tiles (45/46,38)
    is its firing lane, the off-lane route sidesteps one column, the pirate
    follows, and the party sidesteps back, forever. Runs the overworld tick
    order (threat escape, then the capture driver) with the pirate mirroring
    the party's x along row 39. Returns (trail, attacked)."""
    from py_exodus.autoplay.trip import Destination, Leg, TripPlan

    pygame.init()
    pygame.font.init()
    rng = random.getstate()
    try:
        random.seed(1)
        am = batch._assets()
        p = batch.build_party()
        for m, lv, hp, mx in zip(
            p.members, (12, 12, 3, 9), (1145, 1149, 344, 893), (1250, 1250, 350, 950)
        ):
            m.level, m.hp, m.max_hp = lv, hp, mx
        p.members[2].hp = cleric_hp
        sm = StateMachine(asset_mgr=am, audio=None)
        ow = OverworldScreen(party=p, asset_mgr=am, random_encounters=False)
        sm.set_screen(ow)
        gm = ow.game_map
        sent: list[int] = []
        sm.handle_event = lambda e: sent.append(e.key)
        ctrl = AutoPlayController(enabled=True)
        leg = Leg(Transport.FOOT, (45, 38), "CAPTURE")
        ctrl._trip = TripPlan(Destination(frozenset({(45, 38)}), Transport.SHIP, "capture"), [leg], 0.0, 0)
        p.x, p.y = 45, 35
        p.transport = Transport.FOOT
        trail = []
        moves = {pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1), pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0)}
        for _ in range(steps):
            px = p.x if gm.get_tile(p.x, 39).name == "water" else 45
            ow.creatures = [{"tile_name": "pirate", "tile": "pirate", "x": px, "y": 39}]
            sent.clear()
            ctrl._key_queue.clear()
            if ctrl._threat_escape(sm, ow, p, p.x, p.y) is None:
                ctrl._ow_turn += 1
                # As _monster_avoid sets it for the trip: lanes and barred tiles.
                ctrl._overworld_avoid = ctrl._threats.hard_avoid() | ctrl._active_blocks()
                ctrl._drive_capture(sm, ow, gm, p, (p.x, p.y), leg, 0)
            if pygame.K_a in sent:
                return trail, True
            for k in sent:
                if k in moves:
                    p.x += moves[k][0]
                    p.y += moves[k][1]
            trail.append((p.x, p.y))
        return trail, False
    finally:
        random.setstate(rng)


def test_stalled_capture_dashes_through_a_shadowing_pirates_lane():
    """Every living member can take two broadsides (hp > 2 x (0x77 + 8);
    LairWare moveshoot hits each member for (rand & 0x77) + 8): once the
    hunt stops closing in, the party walks the lane and attacks."""
    trail, attacked = _shadow_run(cleric_hp=344)
    assert attacked, trail


def test_stalled_capture_too_weak_for_the_lane_goes_elsewhere():
    """The level-3 Cleric at 200 HP can't take two broadsides: no dash, but
    no pacing either; the capture drops the pirate for a while and walks
    on along the coast."""
    trail, attacked = _shadow_run(cleric_hp=200, steps=30)
    assert not attacked, trail
    assert any(abs(x - 45) + abs(y - 35) > 3 for x, y in trail), trail


def test_capture_dash_unlocks_a_locked_door_on_its_route():
    """Batch seed 1 (round 1 report, steps 97,134-104,400): on Ambrosia the
    shrine trip's capture stalled, the dash's foot route to a pirate at
    (35, 10) went west through the locked door (50, 6), and the dash pressed
    West into the door from (51, 6) ~7,300 steps, 7 keys in hand, until the
    food ran low. The dash unlocks it (U, member, direction) instead."""
    from py_exodus.autoplay.planner import evaluate_goal
    from py_exodus.autoplay.threats import compute_threats
    from py_exodus.autoplay.trip import Destination, Leg, TripPlan, terrain_for

    pygame.init()
    am = batch._assets()
    p = batch.build_party()
    p.map_id = 13
    for m in p.members:
        m.keys = 2
        m.max_hp = m.hp = 2550
    ow = OverworldScreen(party=p, asset_mgr=am, random_encounters=False, map_id=13)
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(ow)
    gm = ow.game_map
    p.x, p.y, p.transport = 51, 6, Transport.FOOT
    ctrl = AutoPlayController(enabled=True)
    th = compute_threats(gm, p, [{"tile_name": "pirate", "tile": "pirate", "x": 35, "y": 10}])
    comp = terrain_for(gm, p, 13).sea_comp[(35, 10)]
    leg = Leg(Transport.FOOT, (34, 55), "CAPTURE")
    ctrl._trip = TripPlan(Destination(frozenset({(45, 52)}), Transport.FOOT, "shrine"), [leg], 0.0, 0)
    ctrl._dash = (frozenset({comp}), 13, "shrine", evaluate_goal(p, 13))
    assert ctrl._capture_dash(sm, ow, gm, p, (51, 6), th) == pygame.K_u
    assert list(ctrl._key_queue) == [pygame.K_1, pygame.K_w]


def test_a_ship_never_sails_onto_a_parked_frigate_on_ambrosia():
    """Live trace 2026-11-25 (trace_20261125-180541, ~3,200 turns): the
    party had landed from a ship at (34, 56) for the wisdom shrine, later
    came back in a captured one, and the plan's landing tile was its own
    parked frigate. Each move north was refused. Now a ship never plans
    onto a frigate: it lands elsewhere and walks on toward the shrine."""
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    pygame.init()
    am = batch._assets()
    p = batch.build_party()
    p.map_id = 13
    for m, lv in zip(p.members, (14, 12, 6, 10)):
        m.level, m.max_hp, m.hp = lv, lv * 100 + 50, lv * 100 + 50
        m.cards = [1, 1, 1, 1]
        m.marks = [1, 0, 0, 0]
        m.food = 153
        m.keys = 1
    p.gold = 4402
    ow = OverworldScreen(party=p, asset_mgr=am, random_encounters=False, map_id=13)
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(ow)
    p.objects_map_id = 13
    p.dynamic_objects = [{"tile": "frigate", "x": 34, "y": 56}]
    p.x, p.y, p.transport = 34, 57, Transport.SHIP
    from py_exodus.constants import Direction

    p.wind_direction = Direction.SOUTH  # blocks sailing south only
    assert evaluate_goal(p, 13) == Goal.AMBROSIA_CARDS_SHRINES
    ctrl = AutoPlayController(enabled=True)
    seen = {(p.x, p.y)}
    for _ in range(40):
        ow.creatures = []
        p.wind_direction = Direction.SOUTH
        ctrl.step(sm)
        seen.add((p.x, p.y))
        if p.transport == Transport.FOOT:
            break
    assert p.transport == Transport.FOOT, seen
    assert (34, 56) not in seen


def test_a_trip_leg_that_never_moves_bars_its_end_and_replans():
    """No-progress guard: 60 turns (twice the replan threshold) on one tile
    with the leg's moves refused bars the leg's end for a while."""
    from py_exodus.autoplay import controller as ctl
    from py_exodus.autoplay.trip import Destination, Leg, TripPlan

    c = AutoPlayController(enabled=True)
    leg = Leg(Transport.SHIP, (34, 56), "X")
    dest = Destination(frozenset({(55, 27)}), Transport.FOOT, "shrine55,27")
    c._trip = TripPlan(dest, [leg, Leg(Transport.FOOT, (55, 27), "ARRIVE")], 0.0, 13)
    c._trip_last_pos = (34, 57)
    c._trip_stuck = 2 * ctl._TRIP_STUCK_TURNS - 1
    c._replan = lambda *a, **k: None  # the outcome of the replan is not the point
    p = batch.build_party()
    p.transport = Transport.SHIP
    screen = type("S", (), {"game_map": None})()
    c._trip_drive(None, screen, None, p, 34, 57, 13, dest)
    assert (34, 56) in c._active_blocks()
