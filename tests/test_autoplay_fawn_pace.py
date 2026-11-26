"""A pirate stuck behind the party's own ship outside Fawn (batch 89c1bf4 b9,
seed 90).

The party sailed to Fawn's gate (30, 2) for keys and left its frigate at
(31, 2). Fawn stands on a strip of brush (27-29, 2) with water all round.
While it shopped a pirate came along row 2 to (32, 2), next to the empty
frigate. LairWare's MoveMonsters steps it only toward the party, west onto
(31, 2), and a parked frigate (0x2C) is no tile ValidMonsterDir allows
(UltimaMisc.c:263-272, 1191-1236), so the pirate never moves again; its
shot along the row reaches (29, 2) and (30, 2).

From step 34,452 the trip stepped toward the frigate (or patrolled) onto
(29, 2), the lane escape stepped back to (28, 2), and so on for ~3,700 steps
through SAIL_WHIRLPOOL, GRIND_AND_LEVEL and BUY_FOOD until everyone starved
with 4,665 gold and the ship three steps away.
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from py_exodus.autoplay import batch
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import ArmorType, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import tile_effects

SHIP = (31, 2)
PIRATE = (32, 2)
FAWN_GATE = (30, 2)
PARTY_AT = (29, 2)
HP = (1301, 1272, 573, 1036)
MAX_HP = (1650, 1650, 650, 1250)


def _cheb(a, b, n=64):
    dx = abs(a[0] - b[0]) % n
    dy = abs(a[1] - b[1]) % n
    return max(min(dx, n - dx), min(dy, n - dy))


def _seed90_state(pos=PARTY_AT, hp=HP, ship=True, pirate=PIRATE):
    """Step 34,452 of seed 90: levels 16/16/6/12, K mark, all Exotics,
    4,665 gold, 8 keys, on foot at (29, 2) beside Fawn's gate, the party's
    frigate at (31, 2) and a pirate at (32, 2) behind it."""
    pygame.init()
    pygame.font.init()
    am = batch._assets()
    party = batch.build_party()
    for m, lv, h, mh, mp, gold in zip(
        party.members, (16, 16, 6, 12), hp, MAX_HP, (0, 0, 25, 25), (1200, 1200, 1200, 1065)
    ):
        m.level, m.hp, m.max_hp, m.mp, m.gold = lv, h, mh, mp, gold
        m.food = 293
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        m.marks = [1, 0, 0, 0]
        m.torches = 2
        m.keys = 2
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am)
    sm.set_screen(ow)
    party.x, party.y = pos
    party.transport = Transport.FOOT
    if ship:
        party.dynamic_objects.append({"tile": "frigate", "x": SHIP[0], "y": SHIP[1]})
    ow.creatures = [
        c for c in ow.creatures
        if c.get("tile_name") == "whirlpool" or _cheb((c["x"], c["y"]), pos) > 14
    ]
    if pirate is not None:
        ow.creatures.append(
            {"name": "Pirate", "tile_name": "pirate", "tile": "pirate", "variant": 0,
             "x": pirate[0], "y": pirate[1]}
        )
    ow._spawn_wandering_creature = lambda: None  # just this pirate
    ctrl = AutoPlayController(enabled=True, step_interval=0.08)
    sm.autoplay_enabled = True
    return sm, ow, party, ctrl


def _run(seed, until, max_steps=80, warmup=None, **kw):
    """Drive the real loop from the seed-90 state until ``until(sm, party)``.
    ``warmup`` (a callable on the controller) runs first."""
    rng, trng = random.getstate(), tile_effects._rng.getstate()
    try:
        random.seed(seed)
        tile_effects._rng.seed(seed)
        batch._seed_dungeon_rngs()
        sm, ow, party, ctrl = _seed90_state(**kw)
        if warmup is not None:
            warmup(ctrl)
        steps = 0
        orig = ctrl.step
        trail = []

        def counted(s):
            nonlocal steps
            steps += 1
            scr = s.current_screen
            trail.append((type(scr).__name__, party.x, party.y))
            return orig(s)

        ctrl.step = counted
        while steps < max_steps and not until(sm, party):
            ctrl.update(batch.FRAME_DT, sm)
            sm.update(batch.FRAME_DT)
        return sm, ow, party, ctrl, trail
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)


def _aboard_or_in_town(sm, party):
    return party.transport == Transport.SHIP or type(sm.current_screen).__name__ == "TownScreen"


def _paces(trail):
    """Overworld moves between (28, 2) and (29, 2)."""
    tiles = [(x, y) for scr, x, y in trail if scr == "OverworldScreen"]
    return sum(
        1 for a, b in zip(tiles, tiles[1:]) if {a, b} == {(28, 2), (29, 2)}
    )


@pytest.mark.parametrize("seed", [90, 1, 2, 3])
def test_party_boards_its_own_ship_past_the_stuck_pirate(seed):
    sm, ow, party, ctrl, trail = _run(seed, _aboard_or_in_town, max_steps=300)
    assert _aboard_or_in_town(sm, party), trail
    # The first turn's escape (no trip planned yet) and the walk back: no pace.
    assert _paces(trail) <= 2, trail
    assert all(not m.is_dead() for m in party.members)


@pytest.mark.parametrize("seed", [90, 1, 2])
def test_the_pace_ends_once_it_has_started(seed):
    """Start from inside the pace: the trace's state ~200 steps in, Cleric
    hurt, the lane tile (29, 2) refused and barred, the trip on a capture."""
    def warmup(ctrl):
        ctrl._blocked_tiles[(29, 2)] = 10_000

    sm, ow, party, ctrl, trail = _run(
        seed, _aboard_or_in_town, max_steps=400, warmup=warmup,
        pos=(28, 2), hp=(798, 781, 233, 552),
    )
    assert _aboard_or_in_town(sm, party), trail[-40:]
    assert _paces(trail) <= 6, trail
    assert all(not m.is_dead() for m in party.members)
