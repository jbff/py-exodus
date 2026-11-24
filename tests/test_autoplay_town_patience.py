"""Autoplay waits out a crowd in town instead of leaving (user 2026-11-22).

Grey's guild is behind a pub full of wandering thieves. With no lane open on
arrival, autoplay used to give up on the guild and walk straight back out,
re-enter, and leave again forever. People move now (LW MoveMonsters), so a
patient party gets through.
"""
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.dirname(__file__))
from test_autoplay import _make_party  # noqa: E402

from py_exodus.autoplay import batch
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.planner import Goal, evaluate_goal
from py_exodus.constants import ArmorType, WeaponType
from py_exodus.screens.town import TownScreen
from py_exodus.state_machine import StateMachine


def test_grey_guild_reached_through_the_crowded_pub():
    pygame.init()
    rng = random.getstate()
    try:
        random.seed(0)
        am = batch._assets()
        p = _make_party(
            level=5, exp=500, marks=[0, 0, 0, 0],
            weapon=WeaponType.EXOTIC, armor=ArmorType.EXOTIC, gold=1500,
        )
        for m in p.members:
            m.keys = 0
            m.food = 400
        p.map_id = 6
        sm = StateMachine(asset_mgr=am, audio=None)
        ts = TownScreen(party=p, asset_mgr=am, map_id=6, start_x=1, start_y=32)
        sm.set_screen(ts)
        assert evaluate_goal(p, 6) == Goal.BUY_TORCHES
        ctrl = AutoPlayController(enabled=True)
        for _ in range(400):
            ctrl.step(sm)
            sm.update(0.1)
            if sum(m.torches for m in p.members) > 0 or sm.current_screen is not ts:
                break
        assert sum(m.torches for m in p.members) > 0, (ts.avatar_x, ts.avatar_y)
    finally:
        random.setstate(rng)


def test_transact_faces_the_merchant_not_a_passing_guard():
    """User 2026-11-22 at De Grocer: a guard wandered up north of the party
    while the grocer stood south; autoplay Transacted north forever."""
    from py_exodus.world.map import MapNpc

    class _Map:
        npcs = [
            MapNpc(tile_index=0, tile_name="guard", x=10, y=9, start_x=10, start_y=9, movement="WANDER"),
            MapNpc(tile_index=0, tile_name="merchant", x=10, y=12, start_x=10, start_y=12,
                   movement="FOLLOW_AVATAR"),
        ]

    assert AutoPlayController._direction_to_npc(_Map(), 10, 10) == pygame.K_DOWN


def _party_on_a_chest(dead_cleric: bool, level: int):
    from py_exodus.constants import Status, Transport
    from py_exodus.screens.overworld import OverworldScreen

    am = batch._assets()
    p = batch.build_party()
    for m in p.members:
        m.level = level
        m.max_hp = m.hp = 100 * level
        m.food = 300
        m.mp = 0  # no APPAR UNEM
    if dead_cleric:
        cleric = next(m for m in p.members if m.profession.name == "CLERIC")
        cleric.status = Status.DEAD
        cleric.hp = 0
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=p, asset_mgr=am)
    ow.creatures = []  # a random pirate nearby changes the plan (seeds 266, 353)
    sm.set_screen(ow)
    p.transport = Transport.FOOT
    p.dynamic_objects = list(getattr(p, "dynamic_objects", []) or []) + [
        {"tile": "chest", "x": p.x, "y": p.y}
    ]
    return sm, p


def test_dead_cleric_party_takes_dropped_chests_with_the_thief():
    """User ruling 2026-11-22 (replaces the 2026-11-22 leave-it rule): with
    the Cleric dead a party that skips chests never gets the 500 gold to
    resurrect and stalls, so the Thief opens them with G and takes the
    trap risk. A living Cleric out of MP still waits for mana when weak."""
    pygame.init()
    pygame.font.init()
    sm, p = _party_on_a_chest(dead_cleric=True, level=5)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame.K_g
    thief = next(i + 1 for i, m in enumerate(p.members) if m.profession.name == "THIEF")
    assert ctrl._chest_opener(p) == ("get", thief)
    sm, p = _party_on_a_chest(dead_cleric=False, level=5)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(5):
        assert ctrl.step(sm) not in (pygame.K_g, pygame.K_c)
    sm, p = _party_on_a_chest(dead_cleric=False, level=10)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame.K_g  # strong, all alive: still takes the gamble


def test_guild_see_more_is_declined():
    """Live trace 2026-11-22: after one key the guild asked "See more?" /
    "Buy? (y or n)"; autoplay said y until the buyer was broke (44 keys)."""
    from types import SimpleNamespace

    pygame.init()
    log = SimpleNamespace(current_prompt="Buy? (y or n)", lines=["Shamino says: See more?"])
    screen = SimpleNamespace(text_log=log)
    sm = StateMachine(asset_mgr=None, audio=None)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl._handle_town_prompt(sm, screen) == pygame.K_n
    log.lines = ["Avast ye mate!"]  # the opening offer is still accepted
    assert ctrl._handle_town_prompt(sm, screen) == pygame.K_y
