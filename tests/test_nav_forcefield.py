"""Force-field routing parity tests (2026-11-20 nav fix).

Bug: `nav.find_2d_step` treated the energy/force field as passable when ANY
member had marks[2] — the Mark of the SNAKE — while the movement validator
(tile_effects, Java BaseMap.partyHasMarkOfForce + GBC postexo1.c) only
allows passage when EVERY living member holds the Mark of Force (marks[3]).
Result: the planner routed through walls the walk refused, and the autoplay
controller oscillated against the refusal (walk-into-field loops).

These tests pin the parity: routing through a field is only planned when
all living members carry marks[3].
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.autoplay.nav import find_2d_step
from py_exodus.constants import Transport
from py_exodus.entities.party import Party
from py_exodus.world.loader import MapLoader
from py_exodus.world.tile_effects import apply_force_field_strike


class _Tile:
    def __init__(self, name: str, attribs: int = 0) -> None:
        self.name = name
        self.attribs = attribs

    # can_move_to duck-type surface
    walkable: bool = True
    sailable: bool = False
    dispelable: bool = False
    rule: str = ""


class _Map:
    def __init__(self, rows: list[list]) -> None:
        self.rows = rows
        self.width = len(rows[0])
        self.height = len(rows)
        self.border_behavior = "fixed"
        self.npcs: list = []

    def get_tile(self, x: int, y: int):
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.rows[y][x]
        return None


@pytest.fixture(scope="module")
def castle_am():
    am = AssetManager("data")
    am.load_all()
    return am


@pytest.fixture(scope="module")
def field_corridor(castle_am):
    """3-tile corridor built from REAL engine tiles: grass, energy field.

    The energy field tiles are Castle Britannia's own throne-room field
    (map 1) — same Tile class with real attribs (DISPELABLE), rule, etc.
    """
    britain = MapLoader(castle_am).load_map(1)
    field = britain.get_tile(42, 17)
    assert getattr(field, "dispelable", False), "fixture: expected a dispelable field tile"
    grass = britain.get_tile(40, 17)
    assert grass.walkable
    return _Map([[grass, field, grass]])


def _party(marks3: tuple[int, ...]) -> Party:
    import random

    random.seed(3)
    from py_exodus.constants import Profession, Race
    from py_exodus.entities.character import Character

    party = Party()
    for i, m3 in enumerate(marks3):
        c = Character(f"M{i}", "M", Race.HUMAN, Profession.FIGHTER)
        c.marks = [1, 0, 0, m3]
        party.add_member(c)
    return party


def test_validation_blocks_party_without_force_mark(field_corridor, castle_am):
    """Movement truth: entry refuses and strikes the unmarked (99)."""
    party = _party((1, 0, 0, 0))
    britain_field = field_corridor.get_tile(1, 0)
    strike = apply_force_field_strike(party, britain_field, message_logger=lambda m: None)
    assert strike is True


def test_validation_allows_all_force_marked(field_corridor):
    party = _party((1, 1, 1, 1))
    britain_field = field_corridor.get_tile(1, 0)
    strike = apply_force_field_strike(party, britain_field, message_logger=lambda m: None)
    assert strike is False


def test_nav_refuses_to_plan_through_field_when_not_all_marked(field_corridor):
    """Regression: planner must NOT route through a field the walk refuses.

    With only some members marked, the only route crosses the validator-
    refused field — the planner must refuse (return None) rather than plan
    into the wall and have the controller oscillate against the refusal.
    """
    party = _party((1, 0, 0, 0))
    assert find_2d_step(field_corridor, (0, 0), {(2, 0)}, Transport.FOOT, party=party) is None


def test_nav_routes_through_field_when_all_marked(field_corridor):
    party = _party((1, 1, 1, 1))
    step = find_2d_step(field_corridor, (0, 0), {(2, 0)}, Transport.FOOT, party=party)
    assert step is not None  # the field is crossable for an all-marked party
