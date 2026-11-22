"""Town and castle people move every turn (LW MoveMonsters, UltimaMisc.c
1191-1330; user report 2026-11-22: dragons in Castle Exodus stood still,
and Grey's thief blocked the key shop forever).

Behaviour (ctrl & 0xC0): FIXED stays; WANDER steps randomly half the time;
FOLLOW_AVATAR steps toward the party; ATTACK_AVATAR steps toward it and
battles when its step would land on the party. Land people walk only on
grass/brush/forest/floor.
"""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from py_exodus.autoplay import batch
from py_exodus.screens.town import TownScreen
from py_exodus.world.map import MapNpc


@pytest.fixture
def town():
    pygame.init()
    rng = random.getstate()
    random.seed(5)
    am = batch._assets()
    party = batch.build_party()
    scr = TownScreen(party=party, asset_mgr=am, map_id=2, start_x=32, start_y=62)
    yield scr
    random.setstate(rng)


def _floor_spot(scr, need=4):
    """A floor tile with `need` floor tiles to its east."""
    gm = scr.game_map
    for y in range(1, gm.height - 1):
        for x in range(1, gm.width - need - 1):
            if all(gm.get_tile(x + i, y).name == "floor" for i in range(need + 1)) and not any(
                n.y == y and x <= n.x <= x + need for n in gm.npcs
            ):
                return x, y
    raise AssertionError("no floor run")


def _person(kind, x, y, movement):
    return MapNpc(tile_index=0, tile_name=kind, x=x, y=y, start_x=x, start_y=y, movement=movement)


def test_attacker_closes_in_then_battles(town, monkeypatch):
    scr = town
    x, y = _floor_spot(scr)
    scr.game_map.npcs = [_person("dragon", x + 3, y, "ATTACK_AVATAR")]
    scr.avatar_x, scr.avatar_y = x, y
    fought = []
    monkeypatch.setattr(scr, "_start_exodus_combat", lambda npc: fought.append(npc))
    scr._move_people()
    assert (scr.game_map.npcs[0].x, scr.game_map.npcs[0].y) == (x + 2, y)
    scr._move_people()
    assert (scr.game_map.npcs[0].x, scr.game_map.npcs[0].y) == (x + 1, y)
    assert not fought
    scr._move_people()
    assert fought and fought[0] is scr.game_map.npcs[0]


def test_fixed_stays_and_follower_never_attacks(town, monkeypatch):
    scr = town
    x, y = _floor_spot(scr)
    fixed = _person("guard", x + 4, y, "FIXED")
    follower = _person("cleric", x + 2, y, "FOLLOW_AVATAR")
    scr.game_map.npcs = [fixed, follower]
    scr.avatar_x, scr.avatar_y = x, y
    monkeypatch.setattr(scr, "_start_exodus_combat", lambda npc: pytest.fail("follower attacked"))
    for _ in range(3):
        scr._move_people()
    assert (fixed.x, fixed.y) == (x + 4, y)
    assert (follower.x, follower.y) == (x + 1, y)  # next to the party, never on it


def test_wanderer_moves_and_land_people_stay_on_walkable_tiles(town):
    scr = town
    x, y = _floor_spot(scr)
    wanderer = _person("thief", x + 2, y, "WANDER")
    scr.game_map.npcs = [wanderer]
    scr.avatar_x, scr.avatar_y = 1, 1
    seen = set()
    for _ in range(40):
        scr._move_people()
        seen.add((wanderer.x, wanderer.y))
        assert scr.game_map.get_tile(wanderer.x, wanderer.y).name in ("grass", "brush", "forest", "floor")
    assert len(seen) > 1
