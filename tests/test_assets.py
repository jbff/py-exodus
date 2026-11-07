"""Tests for asset management, texture atlas parsing, and EGA tile slicing."""
import pytest
import pygame

from py_exodus.assets import AssetManager, TileDef
from py_exodus.constants import TileAttrib


def test_asset_manager_tiles():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    water_surf = am.get_tile_surface("water", frame=0)
    assert water_surf.get_width() == 16 and water_surf.get_height() == 16
    grass_def = am.get_tile_by_index(1)
    assert grass_def.name == "grass"
    assert "grass" in am.tiles


def test_tile_frames():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()

    # Water has 4 animation frames
    assert len(am.tiles["water"]) == 4
    for i in range(4):
        f = am.get_tile_surface("water", frame=i)
        assert f.get_width() == 16 and f.get_height() == 16

    # Test modulo wrap-around for animation frames
    f_wrapped = am.get_tile_surface("water", frame=4)
    assert f_wrapped == am.tiles["water"][0]


def test_tile_attributes_and_rules():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()

    # Grass (index 1) - replacement tile, walkable
    grass = am.get_tile_by_index(1)
    assert grass.name == "grass"
    assert grass.walkable is True
    assert TileAttrib.REPLACEMENT in grass.attribs
    assert grass.opaque is False

    # Water (index 0) - unwalkable, swimmable, sailable
    water = am.get_tile_by_index(0)
    assert water.name == "water"
    assert water.walkable is False
    assert TileAttrib.UNWALKABLE in water.attribs
    assert TileAttrib.SWIMMABLE in water.attribs
    assert TileAttrib.SAILABLE in water.attribs

    # Mountains (index 4) - unwalkable, unflyable, creature unwalkable, opaque
    mountains = am.get_tile_by_index(4)
    assert mountains.name == "mountains"
    assert mountains.walkable is False
    assert mountains.opaque is True
    assert TileAttrib.UNWALKABLE in mountains.attribs
    assert TileAttrib.UNFLYABLE in mountains.attribs
    assert TileAttrib.CREATUREUNWALKABLE in mountains.attribs

    # Forest (index 3) - opaque
    forest = am.get_tile_by_index(3)
    assert forest.opaque is True


def test_combat_map_associations():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()

    # Water -> conflict map 41 (CNFLCT_W.ULT / CONFLICT_BOTH_SHIPS)
    water = am.get_tile_by_index(0)
    assert water.combat_map == 41
    assert "CNFLCT_W" in water.combat_map_fname

    # Grass -> conflict map 37 (CNFLCT_G.ULT / CONFLICT_GRASS)
    grass = am.get_tile_by_index(1)
    assert grass.combat_map == 37
    assert "CNFLCT_G" in grass.combat_map_fname

    # Brush -> conflict map 34 (CNFLCT_B.ULT / CONFLICT_GRASS_BRUSH)
    brush = am.get_tile_by_index(2)
    assert brush.combat_map == 34
    assert "CNFLCT_B" in brush.combat_map_fname

    # Forest -> conflict map 36 (CNFLCT_F.ULT / CONFLICT_GRASS_FOREST)
    forest = am.get_tile_by_index(3)
    assert forest.combat_map == 36
    assert "CNFLCT_F" in forest.combat_map_fname


def test_case_insensitive_path_resolution():
    am = AssetManager(assets_dir="src/main/resources/assets")

    # Lowercase requested, file on disk is CNFLCT_A.ULT
    resolved = am.resolve_path("data", "cnflct_a.ult")
    assert resolved.exists()
    assert resolved.name == "CNFLCT_A.ULT"

    # Mixed case requested
    resolved_xml = am.resolve_path("XML", "TILESET-BASE.XML")
    assert resolved_xml.exists()
    assert resolved_xml.name == "tileset-base.xml"


def test_error_handling():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()

    with pytest.raises(KeyError):
        am.get_tile_by_index(9999)

    with pytest.raises(KeyError):
        am.get_tile_surface("non_existent_tile_name")
