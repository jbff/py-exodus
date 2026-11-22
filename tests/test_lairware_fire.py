"""LairWare's ship cannon and sailing (UltimaMain.c Fire, North()/ValidTrans).

User 2026-11-22: "allow fire in any of 4 directions and not bother to track
heading". LairWare's Fire: only aboard a ship ("Fire <-WHAT?" otherwise),
any direction, up to three tiles wrapping round the map, the first monster in
the path is hit half the time (a Balron shrugs off half of those) and
"destroyed!"; empty ships don't stop the shot. Ships sail straight off in any
direction the wind allows, with no turn-to-face press.
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.overworld import OverworldScreen


@pytest.fixture
def ow(monkeypatch):
    pygame.init()
    am = AssetManager(assets_dir="assets")
    am.load_tiles()
    am.load_xml_definitions()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100)
    party = Party([PartyMember(hero)], x=20, y=20, gold=500, transport=Transport.SHIP)
    o = OverworldScreen(party=party, map_id=0, asset_mgr=am, start_x=20, start_y=20,
                        random_encounters=False)
    o.creatures = []
    monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
    o._check_moongates = lambda: None  # type: ignore[method-assign]
    return o


def _rolls(monkeypatch, *values):
    seq = list(values)
    monkeypatch.setattr(overworld_module.random, "randint", lambda a, b: seq.pop(0))


@pytest.mark.parametrize("d", [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST])
def test_fires_in_any_direction_and_destroys_on_a_high_roll(ow, monkeypatch, d):
    ow.creatures = [{"tile_name": "orc", "x": 20 + 2 * d.dx, "y": 20 + 2 * d.dy}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(d)
    assert ow.creatures == []
    assert "Orcs destroyed!" in ow.text_log.history
    assert ow.cannon_fx[0]["hit"] is True


def test_a_low_roll_misses_silently_and_stops_the_shot(ow, monkeypatch):
    orc = {"tile_name": "orc", "x": 21, "y": 20}
    behind = {"tile_name": "orc", "x": 22, "y": 20}
    ow.creatures = [orc, behind]
    _rolls(monkeypatch, 10)
    ow._fire_cannons(Direction.EAST)
    assert ow.creatures == [orc, behind]
    assert not any("destroyed" in m for m in ow.text_log.history)


def test_balron_shrugs_off_half_the_hits(ow, monkeypatch):
    ow.creatures = [{"tile_name": "balron", "x": 21, "y": 20}]
    _rolls(monkeypatch, 10)  # Balron's own roll: shot shrugged off
    ow._fire_cannons(Direction.EAST)
    assert len(ow.creatures) == 1
    _rolls(monkeypatch, 200, 200)
    ow._fire_cannons(Direction.EAST)
    assert ow.creatures == [] and "Balrons destroyed!" in ow.text_log.history


def test_range_is_three_tiles(ow, monkeypatch):
    ow.creatures = [{"tile_name": "serpent", "x": 24, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.EAST)
    assert len(ow.creatures) == 1
    assert ow.cannon_fx[0]["path"] == [(21, 20), (22, 20), (23, 20)]


def test_the_shot_wraps_round_the_map_edge(ow, monkeypatch):
    ow.party.x = 1
    ow.creatures = [{"tile_name": "squid", "x": 63, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.WEST)
    assert ow.creatures == [] and "Man-O-Wars destroyed!" in ow.text_log.history


def test_empty_ships_do_not_stop_the_shot(ow, monkeypatch):
    frigate = {"tile": "frigate", "x": 21, "y": 20, "hull": 50}
    ow.party.dynamic_objects.append(frigate)
    ow.creatures = [{"tile_name": "pirate", "x": 22, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.EAST)
    assert frigate["hull"] == 50 and ow.creatures == []


def test_a_variant_is_named_in_the_plural(ow, monkeypatch):
    ow.creatures = [{"tile_name": "thief", "variant": 2, "x": 21, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.EAST)
    assert "Cutpurses destroyed!" in ow.text_log.history


def test_fire_on_foot_is_what(ow):
    ow.party.transport = Transport.FOOT
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f, unicode="f"))
    assert "Fire <-WHAT?" in ow.text_log.history


def test_cannon_fx_flies_and_clears(ow):
    ow._fire_cannons(Direction.NORTH)
    fx = ow.cannon_fx[0]
    assert fx["path"] == [(20, 19), (20, 18), (20, 17)] and fx["hit"] is False
    ow.update(0.40)
    assert ow.cannon_fx == []


def test_a_ship_sails_straight_off_without_turning(ow):
    ow.party.wind_direction = Direction.NORTH
    for d, (x, y) in ((Direction.EAST, (21, 20)), (Direction.NORTH, (21, 19)),
                      (Direction.WEST, (20, 19))):
        ow._move_avatar(d)
        assert (ow.party.x, ow.party.y) == (x, y)
    assert not hasattr(ow, "heading")
