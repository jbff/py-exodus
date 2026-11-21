"""Ambrosia follows LairWare (user ruling 2026-11-21).

- Sosaria's parked ships/horses stay on Sosaria (PushSosaria/PullSosaria,
  refs/ultima3/Sources/UltimaMisc.c:923-968); Ambrosia starts empty.
- Ambrosia's monster table is live (behaviour byte 0xC0 = the Sosaria
  "moveoutside" chase/attack/fire branch, UltimaMisc.c:1276-1330) and
  reloads on every visit; nothing spawns there (UltimaMisc.c:1144).
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from py_exodus.autoplay import batch
from py_exodus.constants import Transport
from py_exodus.entities.party import Party
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.world import portal_entry


@pytest.fixture
def world():
    pygame.init()
    random.seed(3)
    am = batch._assets()
    party = batch.build_party()
    scr = OverworldScreen(party=party, asset_mgr=am)
    return scr, party


def _engulf(scr, party):
    party.x, party.y = 50, 13  # Sosaria whirlpool fixture
    party.transport = Transport.SHIP
    scr._check_whirlpool_engulf()
    assert scr.map_id == 13


def test_sosaria_ships_never_appear_on_ambrosia(world):
    scr, party = world
    party.dynamic_objects.append({"tile": "frigate", "x": 50, "y": 60})
    _engulf(scr, party)
    assert party.dynamic_objects == []
    assert party.sosaria_objects == [{"tile": "frigate", "x": 50, "y": 60}]


def test_return_restores_sosaria_objects_and_drops_ambrosias(world):
    scr, party = world
    party.dynamic_objects.append({"tile": "frigate", "x": 50, "y": 60})
    _engulf(scr, party)
    party.dynamic_objects.append({"tile": "chest", "x": 30, "y": 50})
    party.transport = Transport.SHIP
    assert portal_entry.step_in_whirlpool_portal(scr, 32, 58)
    assert scr.map_id == 0
    assert party.dynamic_objects == [{"tile": "frigate", "x": 50, "y": 60}]
    assert party.transport == Transport.SHIP


def test_ambrosia_monsters_are_live_creatures(world):
    scr, party = world
    _engulf(scr, party)
    pirates = sorted((c["x"], c["y"]) for c in scr.creatures if c["tile_name"] == "pirate")
    assert pirates == [(18, 56), (35, 10), (43, 60)]
    assert len(scr.creatures) == 16
    assert scr.game_map.npcs == []  # no frozen town people left behind
    start = {id(c): (c["x"], c["y"]) for c in scr.creatures}
    for _ in range(10):
        scr._update_creatures()
    assert any((c["x"], c["y"]) != start[id(c)] for c in scr.creatures)


def test_no_wanderers_spawn_on_ambrosia(world, monkeypatch):
    scr, party = world
    _engulf(scr, party)
    n = len(scr.creatures)
    monkeypatch.setattr(random, "randint", lambda a, b: b)  # pass every gate
    scr._spawn_wandering_creature()
    assert len(scr.creatures) == n


def test_surface_objects_round_trip_through_save():
    p = Party()
    p.dynamic_objects = [{"tile": "frigate", "x": 1, "y": 2}]
    p.enter_surface_map(13)
    q = Party.from_dict(p.to_dict())
    assert q.objects_map_id == 13 and q.dynamic_objects == []
    q.enter_surface_map(0)
    assert q.dynamic_objects == [{"tile": "frigate", "x": 1, "y": 2}]
