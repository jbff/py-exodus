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
    # Check portals and moongates loaded from maps.xml
    assert len(sosaria.portals) > 0
    assert len(sosaria.moongates) > 0
    # Test border wrap
    assert sosaria.get_tile(-1, 0) == sosaria.get_tile(63, 0)
    assert sosaria.get_tile(64, 64) == sosaria.get_tile(0, 0)


def test_sosaria_data_has_no_baked_moongate():
    """The moongate tile (34) must never be baked into sosaria.json.

    GBC sosaria.c has plain grass (0x04) at (15, 29); NES and LairWare also
    have no gate there. Gates in this port are code-spawned from maps.xml
    (game_map.moongates), so a baked tile-34 cell is dead data AND would
    duplicate the gate model if it ever rendered from the grid.
    """
    import json

    with open("assets/maps/sosaria.json") as f:
        data = json.load(f)
    flat = [v for row in data["tiles"] for v in row]
    assert 34 not in flat


def test_load_conflict_case_insensitive(asset_mgr):
    loader = MapLoader(asset_mgr)
    # Test canonical lowercase name
    conflict = loader.load_conflict_map("cnflct_a.json")
    assert isinstance(conflict, ConflictMap)
    assert conflict.width == 11 and conflict.height == 11
    assert conflict.map_type == MapType.COMBAT
    assert len(conflict.monster_starts) == 8
    assert len(conflict.player_starts) == 4
    assert conflict.monster_starts[0] == (3, 3)
    assert conflict.player_starts[0] == (3, 7)

    # Test legacy uppercase filename (resolved case-insensitively by stem)
    conflict_lower = loader.load_conflict_map("CNFLCT_A.JSON")
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

    # Verify underlying floor tile replacement from offset 0x11A0
    # Lord British is NPC 31 at (32, 14); the tile beneath him in grid must be floor (index 8)
    lb = british.npcs[31]
    assert lb.x == 32 and lb.y == 14
    tile_under_lb = british.get_tile(lb.x, lb.y)
    assert tile_under_lb is not None
    assert tile_under_lb.name == "floor"
    assert tile_under_lb.index == 8


def test_all_conflict_maps_by_id(asset_mgr):
    loader = MapLoader(asset_mgr)
    for map_id in range(33, 42):
        cmap = loader.load_conflict_map(map_id)
        assert isinstance(cmap, ConflictMap)
        assert cmap.width == 11 and cmap.height == 11
        assert len(cmap.monster_starts) == 8
        assert len(cmap.player_starts) == 4
        assert cmap.id == map_id


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
    dmap = loader.load_dungeon_map("perinian.json")
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

    # Test legacy uppercase filename
    dmap_upper = loader.load_dungeon_map("PERINIAN.JSON")
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
    combat_by_name = loader.load_map("cnflct_a.json")
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


def test_dungeon_fountain_typed_by_x_coordinate():
    """A raw 0x02 dungeon byte is no longer a blanket FOUNTAIN_HEAL.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the builder re-types
    every untyped fountain by its tile x coordinate (x & 3: 0=poison,
    1=heal, 2=acid, 3=cure) right after load (GBC dungfunc.c:1277-1310).
    """
    from py_exodus.world.map_build import build_dungeon_map

    tiles = [
        [[0x00 for _ in range(16)] for _ in range(16)] for _ in range(8)
    ]
    # Raw 0x02 fountain bytes on level 3 at consecutive x 3 and 4 per the
    # brief, plus x 1 and 2 to cover the full x&3 table.
    for x in (1, 2, 3, 4):
        tiles[3][5][x] = 0x02
    # Another raw 0x02 on level 6 at x=0 to cover the mod-0 case twice.
    tiles[6][2][0] = 0x02

    dmap = build_dungeon_map(
        None,
        {"source": "test.ult", "level_texts": [""], "tiles": tiles},
        None,
    )

    assert dmap.get_tile(1, 5, 3) is DungeonTile.FOUNTAIN_HEAL  # x=1
    assert dmap.get_tile(2, 5, 3) is DungeonTile.FOUNTAIN_ACID  # x=2
    assert dmap.get_tile(3, 5, 3) is DungeonTile.FOUNTAIN_CURE  # x=3
    assert dmap.get_tile(4, 5, 3) is DungeonTile.FOUNTAIN_POISON  # x=4
    assert dmap.get_tile(0, 2, 6) is DungeonTile.FOUNTAIN_POISON  # x=0


def test_dungeon_asset_fountains_typed_by_x(asset_mgr):
    """The shipped dungeon JSON stores RAW bytes; no FOUNTAIN_UNTYPED leaks.

    dardin.json has a raw 0x02 at (x=15, y=15, z=7) with no maps.xml label:
    15 & 3 == 3 must type it FOUNTAIN_CURE (was FOUNTAIN_HEAL before the fix).
    """
    loader = MapLoader(asset_mgr)
    dardin = loader.load_dungeon_map("dardin.json")

    assert dardin.get_tile(15, 15, 7) is DungeonTile.FOUNTAIN_CURE
    # dardin (4,4,4) carries a FOUNTAIN_POISON label that agrees with x&3
    # (4 & 3 == 0): same result either way.
    assert dardin.get_tile(4, 4, 4) is DungeonTile.FOUNTAIN_POISON

    for z in dardin.tiles:
        for row in z:
            for tile in row:
                assert tile is not DungeonTile.FOUNTAIN_UNTYPED


def test_dungeon_x3_arbitration_wins_over_transposed_labels(asset_mgr):
    """The 10 raw-0x02 cells the 2015 labeler transposed: x&3 wins.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): controller ruling —
    fountain typing on any raw 0x02 byte is governed by x&3
    (GBC dungfunc.c:1277-1310; LW UltimaDngn.c:240-276; NES per-map
    tables), overriding the transposed FOUNTAIN_* maps.xml labels.
    """
    loader = MapLoader(asset_mgr)
    cases = [
        ("mine.json", (7, 7, 6), DungeonTile.FOUNTAIN_CURE),
        ("mine.json", (8, 7, 6), DungeonTile.FOUNTAIN_POISON),
        ("mine.json", (7, 8, 0), DungeonTile.FOUNTAIN_CURE),
        ("mine.json", (8, 7, 0), DungeonTile.FOUNTAIN_POISON),
        ("fire.json", (12, 9, 7), DungeonTile.FOUNTAIN_POISON),
        ("fire.json", (10, 9, 7), DungeonTile.FOUNTAIN_ACID),
        ("m.json", (7, 2, 7), DungeonTile.FOUNTAIN_CURE),
        ("m.json", (8, 2, 7), DungeonTile.FOUNTAIN_POISON),
        ("p.json", (8, 2, 3), DungeonTile.FOUNTAIN_POISON),
        ("p.json", (2, 8, 3), DungeonTile.FOUNTAIN_ACID),
    ]
    for fname, (x, y, z), expected in cases:
        dmap = loader.load_dungeon_map(fname)
        assert dmap.get_tile(x, y, z) is expected, (fname, x, y, z)


def test_dungeon_label_only_fountain_keeps_label(asset_mgr):
    """A label on a NON-0x02 raw byte keeps its maps.xml typing.

    p.json (x=9, y=9, z=4) raw byte is 0x08 (a label-only fountain), not
    a transposed 0x02 cell: FOUNTAIN_POISON there must survive the x&3
    arbitration (controller ruling 2026-11-14).
    """
    loader = MapLoader(asset_mgr)
    p = loader.load_dungeon_map("p.json")
    assert p.get_tile(9, 9, 4) is DungeonTile.FOUNTAIN_POISON


def test_module_level_helpers(asset_mgr):
    sosaria = load_map(0, asset_mgr)
    assert sosaria.width == 64
    conflict = load_conflict_map("cnflct_b.json", asset_mgr)
    assert conflict.width == 11
    dungeon = load_dungeon_map("dardin.json", asset_mgr)
    assert dungeon.width == 16
    shrine = load_shrine_map("shrine.json", asset_mgr)
    assert shrine.width == 11


def test_invalid_map_errors(asset_mgr):
    loader = MapLoader(asset_mgr)
    with pytest.raises(ValueError):
        loader.load_map(9999)

    with pytest.raises(FileNotFoundError):
        loader.load_conflict_map("does_not_exist.json")

    with pytest.raises(FileNotFoundError):
        loader.load_dungeon_map("does_not_exist.json")


def test_city_npc_dialogues_and_movement(asset_mgr):
    """Verify city NPC dialogues, movement behaviors, and vendor bindings are loaded from JSON map files."""
    loader = MapLoader(asset_mgr)
    british = loader.load_map(1)
    assert len(british.npcs) > 0

    # In Castle British, check specific NPCs with known dialogues from original .ULT
    # NPC 16 (Chuckles): "Chuckles: Welcome all!"
    # NPC 18: "West 8, South 35 and await Dawn!"
    # NPC 20: "Phantom Fighter: The food stinks!"
    dialogues = [npc.conversation for npc in british.npcs if npc.conversation is not None]
    assert len(dialogues) > 0
    assert any("Welcome all" in d for d in dialogues)
    assert any("West 8, South 35" in d for d in dialogues)

    # Check movement behaviors (FIXED, WANDER, FOLLOW_AVATAR, ATTACK_AVATAR)
    movements = {npc.movement for npc in british.npcs}
    assert "FIXED" in movements
    assert "WANDER" in movements
    assert "FOLLOW_AVATAR" in movements

    # Check that city vendors in LCB (map 3) are bound to MapNpc.vendor
    lcb = loader.load_map(3)
    vendors = [npc.vendor for npc in lcb.npcs if npc.vendor is not None]
    assert len(vendors) > 0
    assert any("Osbert" in v.name or "Weaponry" in v.name for v in vendors)

