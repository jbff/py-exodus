"""Unit tests for Phase 3 Overworld tactical survival override."""
from __future__ import annotations

from types import SimpleNamespace

import pygame

from py_exodus.constants import Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.overworld_survival import choose_survival_override_key


def _make_survival_party(gold: int = 200, food: int = 200) -> Party:
    p = Party()
    for name, race, prof in (
        ("SHADOW", Race.ELF, Profession.THIEF),
        ("GRUMM", Race.DWARF, Profession.FIGHTER),
        ("SERENA", Race.BOBIT, Profession.CLERIC),
        ("ZIRCON", Race.FUZZY, Profession.WIZARD),
    ):
        m = Character(name, "M", race, prof, gold=gold // 4, food=food)
        m.level = 5
        m.hp = m.max_hp = 500
        p.add_member(m)
    p.x, p.y = 10, 10
    p.transport = Transport.FOOT
    return p


def test_survival_override_evades_nearby_monster_when_vulnerable(pygame_setup):
    p = _make_survival_party()
    p.members[1].status = Status.DEAD
    p.members[2].status = Status.DEAD
    p.members[3].status = Status.DEAD
    tile = SimpleNamespace(name="grass", swimmable=False, walkable=True, passable=True, dispelable=False)
    gmap = SimpleNamespace(id=0, width=64, height=64, border_behavior="wrap", npcs=(), get_tile=lambda x, y: tile)
    scr = SimpleNamespace(creatures=[{"x": 10, "y": 11, "tile_name": "orc"}])
    assert choose_survival_override_key(gmap, p, scr) == pygame.K_UP
