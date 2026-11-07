"""Tests for binary map loaders (world, city, conflict, dungeon, shrine)."""
import pytest
from py_exodus.assets import AssetManager
from py_exodus.constants import MapType
from py_exodus.world.loader import (
    MapLoader,
    load_conflict_map,
    load_dungeon_map,
    load_map,
    load_shrine_map,
)
from py_exodus.world.map import ConflictMap, DungeonMap, DungeonTile, GameMap


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


def test_load_sosaria(asset_mgr):
    loader = MapLoader(asset_mgr)
    sosaria = loader.load_map(0)
    assert isinstance(sosaria, GameMap)
    assert sosaria.width == 64 and sosaria.height == 64
    assert sosaria.map_type == MapType.WORLD
    assert len(sosaria.tiles) == 64 * 64
    assert sosaria.get_tile(0, 0) is not None
    # Verify moongate replacement at (15, 29) to grass (index 1)
    tile_at_moongate = sosaria.get_tile(15, 29)
    assert tile_at_moongate.index == 1
    # Check portals and moongates loaded from maps.xml
    assert len(sosaria.portals) > 0
    assert len(sosaria.moongates) > 0
    # Test border wrap
    assert sosaria.get_tile(-1, 0) == sosaria.get_tile(63, 0)
    assert sosaria.get_tile(64, 64) == sosaria.get_tile(0, 0)


def test_load_conflict_case_insensitive(asset_mgr):
    loader = MapLoader(asset_mgr)
    # Test uppercase
    conflict = loader.load_conflict_map("CNFLCT_A.ULT")
    assert isinstance(conflict, ConflictMap)
    assert conflict.width == 11 and conflict.height == 11
    assert conflict.map_type == MapType.COMBAT
    assert len(conflict.monster_starts) == 8
    assert len(conflict.player_starts) == 4
    assert conflict.monster_starts[0] == (3, 3)
    assert conflict.player_starts[0] == (3, 7)

    # Test lowercase case-insensitivity on Linux
    conflict_lower = loader.load_conflict_map("cnflct_a.ult")
    assert conflict_lower.width == 11 and conflict_lower.height == 11
    assert conflict_lower.monster_starts == conflict.monster_starts
    assert conflict_lower.player_starts == conflict.player_starts


def test_load_city_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    british = loader.load_map(1)
    assert isinstance(british, GameMap)
    assert british.width == 64 and british.height == 64
    assert british.map_type == MapType.CITY
    assert len(british.npcs) == 32
    assert british.people == british.npcs
    assert british.npcs[0].x == 11 and british.npcs[0].y == 53
    assert british.npcs[0].tile_index == 18
    # Test non-wrapping out of bounds
    assert british.get_tile(-1, 0) is None
    assert british.get_tile(64, 0) is None


def test_load_ambrosia_doors(asset_mgr):
    loader = MapLoader(asset_mgr)
    ambrosia = loader.load_map(13)
    assert isinstance(ambrosia, GameMap)
    door_34 = ambrosia.get_tile(34, 5)
    door_35 = ambrosia.get_tile(35, 5)
    door_36 = ambrosia.get_tile(36, 5)
    assert door_34.name == "locked_door"
    assert door_35.name == "locked_door"
    assert door_36.name == "locked_door"


def test_load_dungeon_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    # Test lowercase and uppercase loading
    dmap = loader.load_dungeon_map("perinian.ult")
    assert isinstance(dmap, DungeonMap)
    assert dmap.width == 16 and dmap.height == 16
    assert dmap.levels == 8
    assert dmap.map_type == MapType.DUNGEON

    # Entrance ladder up at (1, 1, 0)
    assert dmap.get_tile(1, 1, 0) == DungeonTile.LADDER_UP

    # Level texts loaded from 0x800
    assert len(dmap.level_texts) == 8
    assert dmap.level_texts[0] == "Perinian depths"

    # Label override from maps.xml (e.g. MARK_KINGS at (15, 11, 0))
    assert dmap.get_tile(15, 11, 0) == DungeonTile.MARK_KINGS

    # Out-of-bounds safety check
    assert dmap.get_tile(-1, 0, 0) == DungeonTile.WALL
    assert dmap.get_tile(0, 0, 10) == DungeonTile.WALL

    # Dynamic tile mutation
    dmap.set_tile(1, 1, 0, DungeonTile.CHEST)
    assert dmap.get_tile(1, 1, 0) == DungeonTile.CHEST

    # Test uppercase filename
    dmap_upper = loader.load_dungeon_map("PERINIAN.ULT")
    assert dmap_upper.get_tile(1, 1, 0) == DungeonTile.LADDER_UP


def test_load_shrine_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    shrine = loader.load_map(55)  # Shrine of Wisdom
    assert isinstance(shrine, GameMap)
    assert shrine.width == 11 and shrine.height == 11
    assert shrine.map_type == MapType.SHRINE
    assert len(shrine.tiles) == 121


def test_load_by_name_and_id_variants(asset_mgr):
    loader = MapLoader(asset_mgr)
    # Load by map name string
    sosaria_by_name = loader.load_map("SOSARIA")
    assert sosaria_by_name.id == 0

    # Load combat map via load_map
    combat_by_name = loader.load_map("CNFLCT_A.ULT")
    assert isinstance(combat_by_name, ConflictMap)

    # Load combat map by integer ID
    combat_by_id = loader.load_conflict_map(33)
    assert combat_by_id.width == 11

    # Load dungeon map by integer ID
    dungeon_by_id = loader.load_dungeon_map(14)
    assert dungeon_by_id.levels == 8

    # Load shrine by integer ID
    shrine_by_id = loader.load_shrine_map(55)
    assert shrine_by_id.width == 11


def test_map_queries_and_helpers(asset_mgr):
    loader = MapLoader(asset_mgr)
    sosaria = loader.load_map(0)

    # Portals query
    portal = sosaria.portals[0]
    found_portal = sosaria.get_portal(portal.x, portal.y)
    assert found_portal == portal
    assert sosaria.get_portal(-99, -99) is None

    # Moongates query by phase and name
    mg = sosaria.moongates[0]
    assert sosaria.get_moongate(mg.phase) == mg
    assert sosaria.get_moongate(mg.name) == mg
    assert sosaria.get_moongate(999) is None

    # Label query
    assert sosaria.get_label("non_existent") is None

    # Mutate tile on GameMap
    grass_tile = asset_mgr.get_tile_by_index(1)
    sosaria.set_tile(0, 0, grass_tile)
    assert sosaria.get_tile(0, 0) == grass_tile


def test_dungeon_tile_methods():
    assert DungeonTile.WALL.byte_value == 0x80
    assert DungeonTile.from_name("WALL") == DungeonTile.WALL
    assert DungeonTile.from_name("wall") == DungeonTile.WALL
    assert DungeonTile.from_name("non_existent") is None
    assert DungeonTile.get_tile_by_value(0x80) == DungeonTile.WALL
    assert DungeonTile.get_tile_by_value(0xFE) == DungeonTile.FLOOR


def test_module_level_helpers(asset_mgr):
    sosaria = load_map(0, asset_mgr)
    assert sosaria.width == 64
    conflict = load_conflict_map("CNFLCT_B.ULT", asset_mgr)
    assert conflict.width == 11
    dungeon = load_dungeon_map("dardin.ult", asset_mgr)
    assert dungeon.width == 16
    shrine = load_shrine_map("shrine.con", asset_mgr)
    assert shrine.width == 11


def test_invalid_map_errors(asset_mgr):
    loader = MapLoader(asset_mgr)
    with pytest.raises(ValueError):
        loader.load_map(9999)

    with pytest.raises(FileNotFoundError):
        loader.load_conflict_map("does_not_exist.ult")

    with pytest.raises(FileNotFoundError):
        loader.load_dungeon_map("does_not_exist.ult")
