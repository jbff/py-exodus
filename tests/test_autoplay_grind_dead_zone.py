"""Grinding in a dead zone until broke (batch 67c0de5 b7, seed 61).

Levels 25/25/24/25 with everything; the goal stays GRIND_AND_LEVEL for the
Cleric's last level. After the last fight (about step 100,625) the grind
paced (40, 41)-(40, 42) for ~3,400 turns at a time with nothing within 8
tiles: at (40, 42) the chase stepped north, the first step of the 20-step
walk round the water inlet (29-32, 41-44) to a monster snagged at (28, 42),
12 tiles off; at (40, 41) that monster was 13 off, past the chase's reach,
and the patrol stepped south again. Each chase step reset the quiet count,
so the wide patrol never took over. Food runs spent 5,379 gold, and the
party starved at step 120,628.

LairWare never despawns and walks every monster toward the party each
turn, so nothing came: Sosaria's 32 slots were full of snagged monsters
(spawning is switched off here to stand for that).
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from py_exodus.autoplay import batch
from py_exodus.autoplay import controller as ctl
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.planner import Goal, evaluate_goal, stat_cap
from py_exodus.constants import ArmorType, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import tile_effects

N = getattr(AutoPlayController, "_GRIND_DEAD_LIMIT", 150)
SNAGGED = (28, 42)


def _seed61_state():
    """Step 106,001: on foot at (40, 41), nothing within 8 tiles."""
    pygame.init()
    pygame.font.init()
    am = batch._assets()
    party = batch.build_party()
    for m, lv, hp in zip(party.members, (25, 25, 24, 25), (2550, 2542, 2435, 2550)):
        m.level, m.hp = lv, hp
        m.max_hp = 2450 if lv == 24 else 2550
        m.food = 369
        m.keys = 1
        m.torches = 2
        m.gold = 995
        m.marks = [1, 1, 1, 1]
        m.cards = [1, 1, 1, 1]
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
    party.members[2].mp = party.members[3].mp = 99
    for m in party.members:
        for stat, cap in (("dexterity", "max_dex"), ("strength", "max_str"),
                          ("intelligence", "max_int"), ("wisdom", "max_wis")):
            setattr(m, stat, stat_cap(m, cap))
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am)
    sm.set_screen(ow)
    party.x, party.y = 40, 41
    party.transport = Transport.FOOT
    ow.creatures = [c for c in ow.creatures if c.get("tile_name") == "whirlpool"]
    ow.creatures.append(
        {"name": "Orc", "tile_name": "orc", "tile": "orc", "variant": 0,
         "x": SNAGGED[0], "y": SNAGGED[1]}
    )
    ow._spawn_wandering_creature = lambda: None
    ctrl = AutoPlayController(enabled=True, step_interval=0.08)
    # The wide patrol heading for (38, 48), south, as in the trace.
    ctrl._patrol_idx = ctl._SOSARIA_PATROL.index((38, 48))
    sm.autoplay_enabled = True
    return sm, ow, party, ctrl


def test_grind_leaves_the_dead_zone():
    """Today the party paces (40, 41)-(40, 42) for good. Now, within N
    turns plus a margin, it has fought or walked well away."""
    rng, trng = random.getstate(), tile_effects._rng.getstate()
    try:
        random.seed(61)
        tile_effects._rng.seed(61)
        batch._seed_dungeon_rngs()
        sm, ow, party, ctrl = _seed61_state()
        assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
        steps = 0
        orig = ctrl.step

        def counted(s):
            nonlocal steps
            steps += 1
            return orig(s)

        ctrl.step = counted
        spots = set()
        left = False
        while steps < N + 60:
            ctrl.update(batch.FRAME_DT, sm)
            sm.update(batch.FRAME_DT)
            name = type(sm.current_screen).__name__
            if name == "CombatScreen":
                break
            if name == "OverworldScreen":
                spots.add((party.x, party.y))
                if abs(party.x - 40) + abs(party.y - 41) > 6:
                    left = True
                    break
        assert left or type(sm.current_screen).__name__ == "CombatScreen", (steps, sorted(spots))
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)
