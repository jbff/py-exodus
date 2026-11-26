"""Builders that turn pure decoded map structs into GameMap/DungeonMap objects."""
from __future__ import annotations

from py_exodus.assets import MAP_ID_TO_NAME, AssetManager, TileDef
from py_exodus.constants import MapType
from py_exodus.entities.defs import MapDef
from py_exodus.world.map import (
    ConflictMap,
    DungeonMap,
    DungeonTile,
    GameMap,
    MapNpc,
)


def build_grid_map(m_def: MapDef, struct: dict, asset_mgr: AssetManager) -> GameMap:
    """Build 2D world or city grid map (64x64, tile index = byte // 4)."""
    width = struct["width"]
    height = struct["height"]
    tiles: list[TileDef] = []
    for tile_row in struct["tiles"]:
        for tile_idx in tile_row:
            tile = asset_mgr.tile_defs.get(tile_idx)
            if tile is None:
                tile = asset_mgr.tile_defs.get(36)
            tiles.append(tile)

    # Replace tile 46 (character 'I') with locked_door when surrounded by non-signs
    locked_door = asset_mgr.get_tile_by_name("locked_door")
    if locked_door is not None:
        for y in range(height):
            for x in range(width):
                idx = y * width + x
                tile = tiles[idx]
                if tile and tile.index == 46:
                    left = tiles[idx - 1] if x > 0 else None
                    right = tiles[idx + 1] if x < width - 1 else None
                    if (
                        left is not None
                        and left.rule != "signs"
                        and right is not None
                        and right.rule != "signs"
                    ):
                        tiles[idx] = locked_door

    # Ambrosia locked doors (map ID 13)
    if m_def.id == 13 and locked_door is not None:
        for ox in (34, 35, 36):
            idx = 5 * width + ox
            if idx < len(tiles):
                tiles[idx] = locked_door

    # City NPCs (32 characters placed at 0x1180, 0x11A0, 0x11C0, 0x11E0, 0x1200)
    npcs: list[MapNpc] = []
    if m_def.map_type.lower() == "city" and struct["npcs"]:
        texts = struct["conversations"]

        # Vendors defined for this map
        vendors = (
            asset_mgr.get_vendors_for_map(m_def.id)
            if asset_mgr is not None
            else []
        )

        for npc_struct in struct["npcs"]:
            t_idx = npc_struct["tile"]
            t_def = asset_mgr.tile_defs.get(t_idx) or asset_mgr.tile_defs.get(36)
            t_name = t_def.name if t_def else ""
            nx = npc_struct["x"]
            ny = npc_struct["y"]

            ctrl = npc_struct["ctrl"]
            dialog_id = ctrl & 0x0F
            m = (ctrl >> 4) & 0x0F
            movement = "FIXED"
            if m == 4:
                movement = "WANDER"
            elif m == 8:
                movement = "FOLLOW_AVATAR"
            elif m == 12:
                movement = "ATTACK_AVATAR"

            conv = None
            if 1 <= dialog_id <= 8 and (dialog_id - 1) < len(texts):
                t_val = texts[dialog_id - 1]
                if t_val:
                    conv = t_val

            # Match vendor by starting position
            matched_vendor = None
            for v in vendors:
                if v.start_x == nx and v.start_y == ny:
                    matched_vendor = v
                    break

            # Skip empty / null person objects (e.g. 0, 0 water)
            if nx == 0 and ny == 0 and (t_name == "water" or t_idx == 0):
                continue

            npcs.append(
                MapNpc(
                    tile_index=t_idx,
                    tile_name=t_name,
                    x=nx,
                    y=ny,
                    start_x=nx,
                    start_y=ny,
                    tile_def=t_def,
                    dialog_id=dialog_id,
                    movement=movement,
                    conversation=conv,
                    vendor=matched_vendor,
                )
            )

            # Replace tile on the map grid with the underlying floor tile
            under_idx = npc_struct["underlying"]
            under_tile = asset_mgr.tile_defs.get(under_idx) or asset_mgr.tile_defs.get(36)
            if under_tile is not None and 0 <= nx < width and 0 <= ny < height:
                tiles[ny * width + nx] = under_tile

    map_type = (
        MapType(m_def.map_type.lower())
        if m_def.map_type.lower() in MapType._value2member_map_
        else MapType.WORLD
    )

    return GameMap(
        id=m_def.id,
        name=MAP_ID_TO_NAME.get(m_def.id, m_def.fname),
        fname=m_def.fname,
        map_type=map_type,
        width=width,
        height=height,
        levels=m_def.levels,
        border_behavior=m_def.border_behavior,
        music=m_def.music,
        no_line_of_sight=m_def.no_line_of_sight,
        tiles=tiles,
        npcs=npcs,
        portals=list(m_def.portals),
        moongates=list(m_def.moongates),
        labels=list(m_def.labels),
    )


def build_conflict_map(
    m_def: MapDef | None, struct: dict, asset_mgr: AssetManager
) -> ConflictMap:
    """Build 11x11 conflict map with player and monster spawn positions."""
    fname = struct["source"]
    tiles: list[TileDef] = []
    for tile_row in struct["tiles"]:
        for b in tile_row:
            tile = asset_mgr.tile_defs.get(b)
            if tile is None:
                tile = asset_mgr.tile_defs.get(36)
            tiles.append(tile)

    monster_starts = [tuple(ms) for ms in struct["monster_starts"]]
    player_starts = [tuple(ps) for ps in struct["player_starts"]]

    map_id = m_def.id if m_def else 33
    name = MAP_ID_TO_NAME.get(map_id, fname)
    music = m_def.music if m_def else "COMBAT"

    return ConflictMap(
        id=map_id,
        name=name,
        fname=fname,
        map_type=MapType.COMBAT,
        width=11,
        height=11,
        levels=1,
        border_behavior="fixed",
        music=music,
        no_line_of_sight=True,
        tiles=tiles,
        monster_starts=monster_starts,
        player_starts=player_starts,
    )


def build_dungeon_map(
    m_def: MapDef | None, struct: dict, asset_mgr: AssetManager
) -> DungeonMap:
    """Build a dungeon map (16x16x8 levels) with text messages."""
    fname = struct["source"]
    tiles: list[list[list[DungeonTile]]] = []
    for z in range(8):
        level_grid: list[list[DungeonTile]] = []
        for y in range(16):
            row: list[DungeonTile] = []
            for x in range(16):
                byte_val = struct["tiles"][z][y][x]
                tile = DungeonTile.get_tile_by_value(byte_val)
                row.append(tile)
            level_grid.append(row)
        tiles.append(level_grid)

    # LairWare reads every fixture from the dungeon's own bytes (GetXYDng,
    # UltimaDngn.c:196, 212-338): a fountain (2) is typed by x & 3
    # (UltimaDngn.c:243: 0 poison, 1 heal, 2 acid, 3 cure; GBC
    # dungfunc.c:1277-1310 agrees) and a mark (5) by x & 3 (UltimaDngn.c:311:
    # 0 Force, 1 Fire, 2 Snake, 3 Kings). The maps.xml labels (the 2015
    # labeler's) no longer retype tiles: one turned the Snake dungeon's
    # writing at (9, 9, 4) into a fountain and one called the Time
    # dungeon's Kings mark at (11, 15, 7) Fire. They stay on the map as
    # data only (LairWare has no Search letter, ledger C-23).
    fountain_by_x_mod = (
        DungeonTile.FOUNTAIN_POISON,
        DungeonTile.FOUNTAIN_HEAL,
        DungeonTile.FOUNTAIN_ACID,
        DungeonTile.FOUNTAIN_CURE,
    )
    mark_by_x_mod = (
        DungeonTile.MARK_FORCE,
        DungeonTile.MARK_FIRE,
        DungeonTile.MARK_SNAKE,
        DungeonTile.MARK_KINGS,
    )
    labels = list(m_def.labels) if m_def else []

    for level_grid in tiles:
        for row in level_grid:
            for x in range(len(row)):
                if row[x] is DungeonTile.FOUNTAIN_UNTYPED:
                    row[x] = fountain_by_x_mod[x & 3]
                elif row[x] is DungeonTile.MARK:
                    row[x] = mark_by_x_mod[x & 3]

    level_texts = struct["level_texts"]

    map_id = m_def.id if m_def else 14
    name = MAP_ID_TO_NAME.get(map_id, fname)
    music = m_def.music if m_def else "DUNGEON"

    return DungeonMap(
        id=map_id,
        name=name,
        fname=fname,
        map_type=MapType.DUNGEON,
        width=16,
        height=16,
        levels=8,
        border_behavior="exit",
        music=music,
        level_texts=level_texts,
        labels=labels,
        tiles=tiles,
    )
