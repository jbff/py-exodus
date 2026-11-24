"""Parked ships/horses and dropped chests belong to one surface map
(user ruling 2026-11-22: nothing parked on one map may show through on
another). Unscoped, a frigate on Sosaria at (54,31) made Death Gulch's pub
counter at (54,31) walkable, and town fights dropped chests on Sosaria."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from py_exodus.assets import MAP_NAME_TO_ID, AssetManager
from py_exodus.combat.arena import Action, CombatArena
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, objects_on
from py_exodus.world.loader import MapLoader


class _Map:
    def __init__(self, map_id):
        self.id = map_id


def test_objects_show_only_on_their_own_surface_map():
    p = Party()
    p.dynamic_objects = [{"tile": "frigate", "x": 54, "y": 31}]
    assert p.objects_map_id == 0
    assert objects_on(p, _Map(0)) == p.dynamic_objects
    # Every other place: each town, castle, dungeon, and Ambrosia.
    others = sorted(set(MAP_NAME_TO_ID.values()) - {0})
    assert len(others) > 15
    for map_id in others:
        assert objects_on(p, _Map(map_id)) == [], map_id


@pytest.fixture
def asset_mgr():
    pygame.init()
    return AssetManager("data")


def _won_fight(asset_mgr, context_map_id):
    party = Party(transport=Transport.FOOT)
    party.x, party.y = 56, 31  # Sosaria, Death Gulch's gate
    party.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, dexterity=99, strength=50))
    cmap = MapLoader(asset_mgr).load_conflict_map("cnflct_c.json")
    arena = CombatArena(party, cmap, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1,
                        context_map_id=context_map_id)
    arena.monsters[0].hp = 1
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x, arena.monsters[0].y = 5, 4
    arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert arena.is_victory
    return arena, party


def test_a_town_fight_drops_no_chest_on_sosaria(asset_mgr):
    arena, party = _won_fight(asset_mgr, context_map_id=10)
    assert not arena.chest_spawned
    assert party.dynamic_objects == []
    arena, party = _won_fight(asset_mgr, context_map_id=0)  # the overworld still drops one
    assert arena.chest_spawned and party.dynamic_objects
