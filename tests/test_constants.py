"""Tests for py_exodus constants and enums."""
from enum import Enum, IntFlag

from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_SIZE,
    VIEWPORT_TILES,
    ArmorType,
    Direction,
    MapType,
    Profession,
    Race,
    Spell,
    Status,
    TileAttrib,
    WeaponType,
)


def test_constants_basic():
    assert Direction.NORTH.dx == 0 and Direction.NORTH.dy == -1
    assert Direction.SOUTH.dx == 0 and Direction.SOUTH.dy == 1
    assert Direction.WEST.dx == -1 and Direction.WEST.dy == 0
    assert Direction.EAST.dx == 1 and Direction.EAST.dy == 0
    assert MapType.WORLD.value == "world"
    assert MapType.COMBAT.value == "combat"
    assert TileAttrib.UNWALKABLE in TileAttrib


def test_screen_dimensions():
    assert SCREEN_WIDTH == 960
    assert SCREEN_HEIGHT == 600
    assert BASE_WIDTH == 320
    assert BASE_HEIGHT == 200
    assert TILE_SIZE == 16
    assert VIEWPORT_TILES == 11


def test_direction_helpers():
    assert Direction.NORTH.reverse() == Direction.SOUTH
    assert Direction.SOUTH.reverse() == Direction.NORTH
    assert Direction.WEST.reverse() == Direction.EAST
    assert Direction.EAST.reverse() == Direction.WEST


def test_map_types():
    expected = {"world", "combat", "city", "dungeon", "shrine"}
    actual = {m.value for m in MapType}
    assert expected.issubset(actual)


def test_tile_attribs():
    assert issubclass(TileAttrib, IntFlag)
    assert TileAttrib.UNWALKABLE in TileAttrib
    assert TileAttrib.SWIMMABLE in TileAttrib
    assert TileAttrib.SAILABLE in TileAttrib
    combined = TileAttrib.UNWALKABLE | TileAttrib.SWIMMABLE
    assert TileAttrib.UNWALKABLE in combined
    assert TileAttrib.SAILABLE not in combined


def test_professions():
    assert len(Profession) == 11
    names = {p.name for p in Profession}
    assert "FIGHTER" in names
    assert "CLERIC" in names
    assert "WIZARD" in names
    assert "THIEF" in names
    assert "PALADIN" in names
    assert "BARBARIAN" in names
    assert "DRUID" in names
    assert "ALCHEMIST" in names
    assert "RANGER" in names
    assert "ILLUSIONIST" in names
    assert "LARK" in names


def test_races():
    assert len(Race) == 5
    names = {r.name for r in Race}
    assert names == {"HUMAN", "ELF", "DWARF", "BOBIT", "FUZZY"}
    assert Race.HUMAN.code == "H"
    assert Race.HUMAN.max_str == 75
    assert Race.ELF.max_dex == 99
    assert Race.DWARF.max_str == 99
    assert Race.BOBIT.max_wis == 99
    assert Race.FUZZY.max_int == 99


def test_spells():
    assert len(Spell) == 32
    # Verify cleric heal spell SANCTU
    sanctu = Spell.SANCTU
    assert sanctu.cost == 10
    assert sanctu.spell_type == "cleric"
    # Verify wizard fireball spell FULGAR
    fulgar = Spell.FULGAR
    assert fulgar.cost == 25
    assert fulgar.spell_type == "wizard"


def test_weapon_and_armor_types():
    assert len(WeaponType) >= 16
    assert WeaponType.NONE in WeaponType
    assert WeaponType.DAGGER in WeaponType
    assert WeaponType.EXOTIC in WeaponType

    assert len(ArmorType) >= 8
    assert ArmorType.NONE in ArmorType
    assert ArmorType.LEATHER in ArmorType
    assert ArmorType.EXOTIC in ArmorType


def test_status():
    assert Status.GOOD.value == "G"
    assert Status.POISONED.value == "P"
    assert Status.ASH.value == "A"
    assert Status.DEAD.value == "D"
