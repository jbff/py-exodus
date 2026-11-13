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

    # Water -> conflict map 41 (cnflct_s.json / CONFLICT_BOTH_SHIPS)
    water = am.get_tile_by_index(0)
    assert water.combat_map == 41
    assert "cnflct_s" in water.combat_map_fname

    # Grass -> conflict map 37 (cnflct_g.json / CONFLICT_GRASS)
    grass = am.get_tile_by_index(1)
    assert grass.combat_map == 37
    assert "cnflct_g" in grass.combat_map_fname

    # Brush -> conflict map 34 (cnflct_b.json / CONFLICT_GRASS_BRUSH)
    brush = am.get_tile_by_index(2)
    assert brush.combat_map == 34
    assert "cnflct_b" in brush.combat_map_fname

    # Forest -> conflict map 36 (cnflct_f.json / CONFLICT_GRASS_FOREST)
    forest = am.get_tile_by_index(3)
    assert forest.combat_map == 36
    assert "cnflct_f" in forest.combat_map_fname


def test_case_insensitive_path_resolution():
    am = AssetManager(assets_dir="src/main/resources/assets")

    # Lowercase requested, file on disk is cnflct_a.json
    resolved = am.resolve_path("maps", "cnflct_a.json")
    assert resolved.exists()
    assert resolved.name == "cnflct_a.json"

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


def test_entity_colorkey_and_aliases():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()

    # Alias check: troll maps to giant, player/avatar maps to fighter
    troll_surf = am.get_tile_surface("troll")
    giant_surf = am.get_tile_surface("giant")
    assert troll_surf is not None
    assert troll_surf.get_size() == (16, 16)
    assert giant_surf is not None

    avatar_surf = am.get_tile_surface("avatar")
    fighter_surf = am.get_tile_surface("fighter")
    assert avatar_surf is not None
    assert fighter_surf is not None

    # Colorkey transparency check on entity sprites
    ranger_surf = am.get_tile_surface("ranger")
    orc_surf = am.get_tile_surface("orc")
    assert ranger_surf.get_colorkey() is not None
    assert ranger_surf.get_colorkey()[:3] == (0, 0, 0)
    assert orc_surf.get_colorkey() is not None
    assert orc_surf.get_colorkey()[:3] == (0, 0, 0)

    # Terrain tiles (e.g. grass) should have no colorkey transparency
    grass_surf = am.get_tile_surface("grass")
    assert grass_surf.get_colorkey() is None
