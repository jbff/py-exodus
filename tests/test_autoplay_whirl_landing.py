"""The whirlpool sinks a parked ship (batch 67c0de5 b5, seed 44).

The party stopped its ship at (31, 3) to dig the Exotics on the two-tile
island (32-33, 3) with Sosaria's whirlpool at (29, 6), heading (1, -1):
three moves from the ship. It left the ship at once, dug, fought a serpent
and a squid from the shore, and the whirlpool moved onto the empty frigate
(LairWare WhirlPool, UltimaMain.c:2959-2996: a 0x2C tile is overwritten,
"Sink", message 110). No pirate ever came (all 32 monster slots filled
with land monsters on the mainland) and everyone starved with 1,666 gold.
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from py_exodus.autoplay import batch
from py_exodus.autoplay import controller as ctl
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import ArmorType, Direction, Transport, WeaponType
from py_exodus.screens import overworld
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import tile_effects

SHIP = (31, 3)
WHIRL = (29, 6)
# Read with defaults so the tests fail on the old code by behaviour.
CLEAR = getattr(ctl, "_WHIRL_LANDING_CLEAR", 2)
HOLD = getattr(ctl, "_WHIRL_HOLD_TURNS", 32)


def _cheb(a, b, n=64):
    dx = abs(a[0] - b[0]) % n
    dy = abs(a[1] - b[1]) % n
    return max(min(dx, n - dx), min(dy, n - dy))


def _seed44_state(whirl=WHIRL):
    """Step 12,576 of seed 44: levels 5/5/3/5, K mark, 1,666 gold, no
    exotics, aboard at (31, 3), the whirlpool at (29, 6) heading (1, -1)."""
    pygame.init()
    pygame.font.init()
    am = batch._assets()
    party = batch.build_party()
    gear = [
        (5, 483, 550, 0, 0, WeaponType.BOW, ArmorType.LEATHER, 0),
        (5, 481, 550, 0, 1191, WeaponType.BOW, ArmorType.PLATE, 0),
        (3, 307, 350, 8, 475, WeaponType.MACE, ArmorType.CHAIN, 2),
        (5, 468, 550, 25, 0, WeaponType.DAGGER, ArmorType.CLOTH, 0),
    ]
    for m, (lv, hp, mhp, mp, gold, wpn, arm, torches) in zip(party.members, gear):
        m.level, m.hp, m.max_hp, m.mp, m.gold = lv, hp, mhp, mp, gold
        m.food = 175
        m.weapon, m.armor = wpn, arm
        m.torches = torches
        m.marks = [1, 0, 0, 0]
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am)
    sm.set_screen(ow)
    party.x, party.y = SHIP
    party.transport = Transport.SHIP
    party.wind_direction = Direction.NORTH
    # Only the whirlpool near the island, as in the trace at step 12,576.
    ow.creatures = [
        c for c in ow.creatures
        if c.get("tile_name") != "whirlpool" and _cheb((c["x"], c["y"]), SHIP) > 12
    ]
    ow.creatures.append(
        {"name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool",
         "x": whirl[0], "y": whirl[1], "dir": [1, -1]}
    )
    ctrl = AutoPlayController(enabled=True, step_interval=0.08)
    sm.autoplay_enabled = True
    return sm, ow, party, ctrl


def _whirl(ow):
    return next((c["x"], c["y"]) for c in ow.creatures if c.get("tile_name") == "whirlpool")


def _exotic_weapons(party):
    """The island (33, 3) is the Exotic weapon site."""
    return sum(
        1 for m in party.members
        if m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0
    )


def _scripted_whirlpool(ow, course):
    """Drive the whirlpool's first moves (LairWare WhirlPool ticks) from
    ``course``: a heading to move along, or None to stay (a re-head off
    land). Afterwards the real WhirlPool takes over."""
    real = ow._move_whirlpool
    ticks = iter(course)

    def move():
        step = next(ticks, "real")
        if step == "real":
            return real()
        if step is None:
            return None
        c = next(c for c in ow.creatures if c.get("tile_name") == "whirlpool")
        c["dir"] = list(step)
        saved = overworld.random.randint
        overworld.random.randint = lambda a, b: 1  # keep the heading
        try:
            real()
        finally:
            overworld.random.randint = saved

    ow._move_whirlpool = move


# The whirlpool's course in the trace after the landing: (30, 5), then
# (31, 4) next to the ship, then north onto it. (The trace re-headed off
# the island for a few ticks first, while a serpent and a squid fight kept
# the party ashore; without those fights the sinking comes a tick after it
# arrives next to the ship.)
TRACE_COURSE = [(1, -1), (1, -1), (0, -1)]


def _run(seed, course=None, pin_whirlpool=False, max_steps=600, whirl=WHIRL):
    rng, trng = random.getstate(), tile_effects._rng.getstate()
    try:
        random.seed(seed)
        tile_effects._rng.seed(seed)
        batch._seed_dungeon_rngs()
        sm, ow, party, ctrl = _seed44_state(whirl)
        if pin_whirlpool:
            ow._move_whirlpool = lambda: None
        elif course is not None:
            _scripted_whirlpool(ow, course)
        steps = 0
        orig = ctrl.step

        def counted(s):
            nonlocal steps
            steps += 1
            return orig(s)

        ctrl.step = counted
        landings = []  # (step, ship tile, whirlpool)
        sunk = []
        log_add = ow.text_log.add_message

        def logged(msg):
            if "ship was destroyed" in str(msg):
                sunk.append(steps)
            return log_add(msg)

        ow.text_log.add_message = logged
        last = (party.transport, party.x, party.y)
        while steps < max_steps and _exotic_weapons(party) < 4 and not party.is_party_dead():
            ctrl.update(batch.FRAME_DT, sm)
            sm.update(batch.FRAME_DT)
            now = (party.transport, party.x, party.y)
            if now != last:
                if last[0] == Transport.SHIP and now[0] == Transport.FOOT and str(ow.map_id) == "0":
                    landings.append((steps, (now[1], now[2]), _whirl(ow)))
                last = now
        return steps, landings, party, ow, sunk
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)


def test_party_boards_again_when_the_whirlpool_comes_next_to_its_ship():
    """Today the ship sinks at the third tick with the party digging two
    steps away, and the party is stranded on the island. Now it walks back
    and boards when the whirlpool comes next to the ship, waits it off, and
    still digs every Exotic weapon."""
    steps, landings, party, ow, sunk = _run(seed=44, course=TRACE_COURSE, max_steps=300)
    assert not sunk, (sunk, landings)
    assert len(landings) >= 2, landings  # went ashore, back aboard, ashore again
    assert _exotic_weapons(party) == 4, (steps, landings, (party.x, party.y), party.transport)
    assert str(ow.map_id) == "0"


def test_party_does_not_land_with_the_whirlpool_two_tiles_off():
    """The step-12,576 state with the whirlpool two tiles from the ship
    (29, 5): no landing until it is farther off or the bounded wait ends,
    and the Exotic weapons are still dug."""
    steps, landings, party, _ow, sunk = _run(seed=44, whirl=(29, 5), max_steps=400)
    assert landings, "never went ashore"
    step, tile, whirl = landings[0]
    assert _cheb(tile, whirl) > CLEAR or step >= HOLD, landings
    assert step > 1, landings
    assert not sunk, sunk
    assert _exotic_weapons(party) == 4, (steps, landings)


def test_landing_wait_and_reboard_are_bounded_when_the_whirlpool_never_leaves():
    """A whirlpool pinned next to the landing (30, 4): the wait lasts
    _WHIRL_HOLD_TURNS, the reboard runs once, then the party lands for good
    and digs. No land-board-land loop."""
    steps, landings, party, _ow, _sunk = _run(seed=44, whirl=(30, 4), pin_whirlpool=True, max_steps=400)
    assert landings, "never went ashore"
    assert HOLD <= landings[0][0] <= HOLD + 10, landings
    assert len(landings) <= 2, landings
    assert _exotic_weapons(party) == 4, (steps, landings)


def test_landing_wait_does_not_restart_within_its_cooldown():
    ctrl = AutoPlayController(enabled=True)
    ctrl._ow_turn = 1000
    assert ctrl._whirl_hold_step(near=True) is True
    ctrl._ow_turn += ctl._WHIRL_HOLD_TURNS
    assert ctrl._whirl_hold_step(near=True) is False
    ctrl._ow_turn += 5
    assert ctrl._whirl_hold_step(near=True) is False
    ctrl._ow_turn += ctl._WHIRL_HOLD_COOLDOWN
    assert ctrl._whirl_hold_step(near=True) is True


def test_landing_wait_budget_is_not_renewed_by_a_whirlpool_drifting_in_and_out():
    """89c1bf4 review: leaving the 2-tile zone for a turn reset the hold, so
    a whirlpool drifting in and out held the ship for ever. The window is
    _WHIRL_HOLD_TURNS from the hold's start, out-of-reach turns included."""
    ctrl = AutoPlayController(enabled=True)
    ctrl._ow_turn = 1000
    held = 0
    for i in range(4 * HOLD):
        near = i % 3 != 2  # two turns in reach, one out
        if ctrl._whirl_hold_step(near=near):
            held += 1
        ctrl._ow_turn += 1
    assert held < HOLD, held
    # Then the cooldown, counted from the window's end.
    assert ctrl._whirl_hold_until == 1000 + HOLD + ctl._WHIRL_HOLD_COOLDOWN


def test_failed_reboard_passes_without_driving_the_trip_twice():
    """89c1bf4 review: a reboard whose trip gave no key fell through to the
    goal's trip in the same step, driving the trip (and its counters) twice."""
    from py_exodus.autoplay.trip import Transition

    rng, trng = random.getstate(), tile_effects._rng.getstate()
    try:
        random.seed(44)
        tile_effects._rng.seed(44)
        sm, ow, party, ctrl = _seed44_state(whirl=(30, 4))
        ow._move_whirlpool = lambda: None
        ctrl._emit_key(sm, pygame.K_x)  # leave the ship at (31, 3)
        assert party.transport == Transport.FOOT
        party.x, party.y = 32, 3
        ctrl._last_transition = Transition("X", SHIP, ctrl._ow_turn)
        drives = []
        real = ctrl._trip_drive

        def drive(state_machine, screen, gmap, party_, px, py, map_id, dest):
            drives.append(dest.label)
            if dest.label == "whirl_reboard":
                return None
            return real(state_machine, screen, gmap, party_, px, py, map_id, dest)

        ctrl._trip_drive = drive
        ctrl.step(sm)
        assert drives == ["whirl_reboard"], drives
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)
