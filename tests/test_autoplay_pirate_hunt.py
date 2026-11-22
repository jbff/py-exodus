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
        party.members[2].wisdom = 35
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
