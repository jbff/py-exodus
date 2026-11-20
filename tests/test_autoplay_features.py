"""Unit tests for the shared Phase 0 / Phase 3 macro feature extractor."""
from __future__ import annotations

from types import SimpleNamespace

from py_exodus.autoplay.features import (
    MACRO_FEATURE_NAMES,
    extract_macro_features,
    macro_feature_vector,
)
from py_exodus.constants import Direction, Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party


def _party_with_four() -> Party:
    p = Party()
    p.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, gold=100, food=50))
    p.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, gold=100, food=100))
    p.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, gold=100, food=100))
    p.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, gold=100, food=100))
    p.members[2].mp = 40
    p.members[2].max_mp = 50
    return p


def test_macro_feature_vector_matches_names_length():
    feats = extract_macro_features(_party_with_four(), map_id=0)
    assert len(macro_feature_vector(feats)) == len(MACRO_FEATURE_NAMES)


def test_macro_features_moon_phases_and_dawn_open():
    screen = SimpleNamespace(trammel_phase=0, felucca_phase=0, creatures=[], game_map=None)
    feats = extract_macro_features(_party_with_four(), map_id=0, screen=screen)
    assert feats["dawn_open"] == 1.0


def test_macro_features_pirate_distance_and_ship_hull():
    p = _party_with_four()
    p.x, p.y = 10, 10
    p.transport = Transport.SHIP
    p.wind_direction = Direction.EAST
    screen = SimpleNamespace(
        trammel_phase=3,
        felucca_phase=2,
        ship_hull=30,
        game_map=SimpleNamespace(width=64, height=64),
        creatures=[{"x": 12, "y": 11, "tile_name": "pirate"}],
    )
    feats = extract_macro_features(p, map_id=0, screen=screen)
    assert feats["nearest_pirate_dist"] == 3.0


def test_macro_features_poison_and_food_runway():
    p = _party_with_four()
    p.members[0].status = Status.POISONED
    feats = extract_macro_features(p, map_id=0)
    assert feats["food_runway_turns"] == 500.0
