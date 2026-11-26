"""Fleeing a dragon's breath in a straight line (batch 67c0de5 b6, seed 57).

Levels 10/9/6/8 with Exotics, 4,475 gold, at full health, just out of
Castle British. A dragon came down column 44 from the north while the grind
paced (44-48, 22). The Cleric is under level 8, so dragons count as firing
lanes (``_strong_vs_pirates`` false) and ``foot_escape`` ran: straight south
from (44, 21) to (44, 33), the dragon three tiles behind the whole way,
breathing on about every other turn (LairWare MoveMonsters + moveshoot: it
moves as fast as the party). About 2,000 HP were lost, the Cleric was left
at 25 of 650, orcs and a pack of 7 dragons finished the party.

Britain's gate (46, 19) was four steps away. The dragon could not follow:
LairWare's greedy step (diagonal, vertical, horizontal) parks it at (45, 17)
between the castle wall and the moat, out of line with the walk in.
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from py_exodus.autoplay import batch
from py_exodus.autoplay import controller as ctl
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import ArmorType, Transport, WeaponType
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import tile_effects

PARTY_AT = (44, 21)
DRAGON_AT = (44, 16)  # five tiles north, as at step 23,783
HP = (916, 815, 557, 777)
MAX_HP = (1050, 950, 650, 850)
K = getattr(ctl, "_ESCAPE_CAP_TURNS", 4)


def _cheb(a, b, n=64):
    dx = abs(a[0] - b[0]) % n
    dy = abs(a[1] - b[1]) % n
    return max(min(dx, n - dx), min(dy, n - dy))


def _seed57_state(dragon=DRAGON_AT, pos=PARTY_AT, hp=HP):
    """Step 23,783 of seed 57: levels 10/9/6/8, K mark, all Exotics, 4,475
    gold, on foot at (44, 21) with one dragon in view."""
    pygame.init()
    pygame.font.init()
    am = batch._assets()
    party = batch.build_party()
    for m, lv, h, mh, mp, gold in zip(
        party.members, (10, 9, 6, 8), hp, MAX_HP, (0, 0, 25, 25), (1200, 1100, 1100, 1075)
    ):
        m.level, m.hp, m.max_hp, m.mp, m.gold = lv, h, mh, mp, gold
        m.food = 167
        m.weapon, m.armor = WeaponType.EXOTIC, ArmorType.EXOTIC
        m.marks = [1, 0, 0, 0]
        m.torches = 2
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am)
    sm.set_screen(ow)
    party.x, party.y = pos
    party.transport = Transport.FOOT
    ow.creatures = [
        c for c in ow.creatures
        if c.get("tile_name") == "whirlpool" or _cheb((c["x"], c["y"]), pos) > 14
    ]
    ow.creatures.append(
        {"name": "Dragon", "tile_name": "dragon", "tile": "dragon", "variant": 0,
         "x": dragon[0], "y": dragon[1]}
    )
    ow._spawn_wandering_creature = lambda: None  # just this dragon
    ctrl = AutoPlayController(enabled=True, step_interval=0.08)
    sm.autoplay_enabled = True
    return sm, ow, party, ctrl


def _run(seed, until, max_steps=60, **kw):
    """Drive the real loop from the seed-57 state until ``until(sm, party)``."""
    rng, trng = random.getstate(), tile_effects._rng.getstate()
    try:
        random.seed(seed)
        tile_effects._rng.seed(seed)
        batch._seed_dungeon_rngs()
        sm, ow, party, ctrl = _seed57_state(**kw)
        steps = 0
        orig = ctrl.step
        trail = []

        def counted(s):
            nonlocal steps
            steps += 1
            scr = s.current_screen
            trail.append((type(scr).__name__, party.x, party.y, sum(m.hp for m in party.members)))
            return orig(s)

        ctrl.step = counted
        while steps < max_steps and not until(sm, party):
            ctrl.update(batch.FRAME_DT, sm)
            sm.update(batch.FRAME_DT)
        return sm, ow, party, ctrl, trail
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)


def _indoors(sm, _party):
    return type(sm.current_screen).__name__ == "TownScreen"


def _fought_or_indoors(sm, _party):
    return type(sm.current_screen).__name__ in ("TownScreen", "CombatScreen")


def _lost(party, hp=HP):
    return sum(hp) - sum(m.hp for m in party.members)


def test_party_walks_into_britain_when_the_dragon_shows_up():
    """Step 23,781: the party at (45, 22), the dragon just come down to
    (44, 15), eight tiles off. Today the grind walks on, the escape runs
    south down column 44 and the dragon follows. Now the party walks the
    four steps into Britain (the dragon is held at the castle wall) and
    loses at most about a quarter of its HP on the way."""
    for seed in (57, 1, 2):
        sm, _ow, party, _ctrl, trail = _run(
            seed, _fought_or_indoors, dragon=(44, 15), pos=(45, 22)
        )
        assert _indoors(sm, party), (seed, trail)
        assert _lost(party) <= sum(MAX_HP) // 4, (seed, _lost(party), trail)
        assert max(y for _s, _x, y, _hp in trail if _s == "OverworldScreen") <= 22, (seed, trail)


def test_no_in_and_out_loop_at_the_gate_while_the_dragon_waits():
    """The party walks into Castle British with a dragon in line north of
    the gate, and the dragon stays there (pinned). Coming out it is in the
    lane at once. Without a bound it would step back in, and out, for
    ever. Now it enters once, then fights the dragon on the way out."""
    rng, trng = random.getstate(), tile_effects._rng.getstate()
    try:
        random.seed(57)
        tile_effects._rng.seed(57)
        batch._seed_dungeon_rngs()
        sm, ow, party, ctrl = _seed57_state(dragon=(44, 15), pos=(44, 20))
        real_step = ow._lw_monster_step

        def pinned(c, cr_def, w, h):
            step = real_step(c, cr_def, w, h)
            return "attack" if step == "attack" else None

        ow._lw_monster_step = pinned
        entries = 0
        last = "OverworldScreen"
        steps = 0
        while steps < 600 and type(sm.current_screen).__name__ != "CombatScreen":
            ctrl.update(batch.FRAME_DT, sm)
            sm.update(batch.FRAME_DT)
            now = type(sm.current_screen).__name__
            if now == "TownScreen" and last != "TownScreen":
                entries += 1
            last = now
            steps += 1
        assert 1 <= entries <= 2, entries
        assert type(sm.current_screen).__name__ == "CombatScreen", ((party.x, party.y), entries)
    finally:
        random.setstate(rng)
        tile_effects._rng.setstate(trng)
