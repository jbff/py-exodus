"""Binary map loader for Ultima III (.ult, CNFLCT_*.ULT, shrine.con)."""
from __future__ import annotations

import struct
from pathlib import Path

from py_exodus.assets import COMBAT_MAPS, MAP_ID_TO_NAME, MAP_NAME_TO_ID, AssetManager, TileDef
from py_exodus.constants import MapType
from py_exodus.entities.defs import MapDef
from py_exodus.world.map import (
    ConflictMap,
    DungeonMap,
    DungeonTile,
    GameMap,
    MapNpc,
)


class MapLoader:
    """Loads binary world, city, combat, dungeon, and shrine maps case-insensitively."""

    def __init__(self, asset_mgr: AssetManager) -> None:
        self.asset_mgr = asset_mgr
        if not self.asset_mgr.tile_defs:
            self.asset_mgr.load_tiles()
        if not self.asset_mgr.map_defs:
            self.asset_mgr.load_xml_definitions()

    def _resolve_data_file(self, fname: str) -> Path:
        """Resolve binary map file inside data/ directory case-insensitively."""
        p = Path(fname)
        parts = list(p.parts)
        if any(part.lower() == "data" for part in parts):
            return self.asset_mgr.resolve_path(*parts)
        return self.asset_mgr.resolve_path("data", fname)

    def load_map(
        self, map_id_or_name: int | str
    ) -> GameMap | ConflictMap | DungeonMap:
        """Load any map by integer ID, enum name, or filename."""
        m_def: MapDef | None = None
        if isinstance(map_id_or_name, int):
            m_def = self.asset_mgr.map_defs.get(map_id_or_name)
        else:
            name_upper = map_id_or_name.strip().upper()
            map_id = MAP_NAME_TO_ID.get(name_upper)
            if map_id is not None:
                m_def = self.asset_mgr.map_defs.get(map_id)
            else:
                # Search by filename or type
                name_lower = map_id_or_name.strip().lower()
                for md in self.asset_mgr.map_defs.values():
                    if md.fname.lower() == name_lower:
                        m_def = md
                        break

        if m_def is None:
            raise ValueError(f"Unknown map identifier or definition: {map_id_or_name}")

        m_type = m_def.map_type.lower()
        if m_type == "combat":
            return self.load_conflict_map(m_def.fname, m_def=m_def)
        if m_type == "dungeon":
            return self.load_dungeon_map(m_def.fname, m_def=m_def)
        if m_type == "shrine":
            return self.load_shrine_map(m_def.fname, m_def=m_def)

        return self._load_grid_map(m_def)

    def _load_grid_map(self, m_def: MapDef) -> GameMap:
        """Load 2D world or city grid map (64x64, tile index = byte // 4)."""
        file_path = self._resolve_data_file(m_def.fname)
        if not file_path.exists():
            raise FileNotFoundError(f"Map file not found: {file_path}")

        data = file_path.read_bytes()
        width = m_def.width
        height = m_def.height
        num_tiles = width * height
        if len(data) < num_tiles:
            raise ValueError(
                f"Map file {m_def.fname} has {len(data)} bytes, expected at least {num_tiles}"
            )

        raw_bytes = struct.unpack(f"{num_tiles}B", data[:num_tiles])
        tiles: list[TileDef] = []
        for b in raw_bytes:
            tile_idx = b // 4
            tile = self.asset_mgr.tile_defs.get(tile_idx)
            if tile is None:
                tile = self.asset_mgr.tile_defs.get(36)
            tiles.append(tile)

        # Replace tile 46 (character 'I') with locked_door when surrounded by non-signs
        locked_door = self.asset_mgr.get_tile_by_name("locked_door")
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

        # Reset moongate tile to grass on Sosaria (map ID 0)
        if m_def.id == 0:
            grass = self.asset_mgr.tile_defs.get(1)
            if grass is not None:
                tiles[29 * width + 15] = grass

        # City NPCs (32 characters placed at 0x1180, 0x11C0, 0x11E0)
        npcs: list[MapNpc] = []
        if m_def.map_type.lower() == "city" and len(data) >= 0x1200:
            npc_tiles = struct.unpack("32B", data[0x1180:0x11A0])
            npc_xs = struct.unpack("32B", data[0x11C0:0x11E0])
            npc_ys = struct.unpack("32B", data[0x11E0:0x1200])

            for i in range(32):
                t_idx = npc_tiles[i] // 4
                t_def = self.asset_mgr.tile_defs.get(t_idx) or self.asset_mgr.tile_defs.get(36)
                t_name = t_def.name if t_def else ""
                npcs.append(
                    MapNpc(
                        tile_index=t_idx,
                        tile_name=t_name,
                        x=npc_xs[i],
                        y=npc_ys[i],
                        start_x=npc_xs[i],
                        start_y=npc_ys[i],
                        tile_def=t_def,
                    )
                )

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

    def load_conflict_map(
        self, fname_or_id: str | int, m_def: MapDef | None = None
    ) -> ConflictMap:
        """Load 11x11 conflict map with player and monster spawn positions."""
        if isinstance(fname_or_id, int):
            map_id = fname_or_id
            m_def = m_def or self.asset_mgr.map_defs.get(map_id)
            fname = (
                COMBAT_MAPS.get(map_id)
                or (m_def.fname if m_def else f"CNFLCT_{map_id}.ULT")
            )
        else:
            fname = fname_or_id
            if m_def is None:
                fname_lower = fname.lower()
                for md in self.asset_mgr.map_defs.values():
                    if md.fname.lower() == fname_lower:
                        m_def = md
                        break

        file_path = self._resolve_data_file(fname)
        if not file_path.exists():
            raise FileNotFoundError(f"Conflict map file not found: {file_path}")

        data = file_path.read_bytes()
        if len(data) < 176:
            raise ValueError(
                f"Invalid conflict map file {fname}: expected at least 176 bytes, found {len(data)}"
            )

        raw_tiles = struct.unpack("121B", data[:121])
        tiles: list[TileDef] = []
        for b in raw_tiles:
            tile = self.asset_mgr.tile_defs.get(b)
            if tile is None:
                tile = self.asset_mgr.tile_defs.get(36)
            tiles.append(tile)

        monster_xs = struct.unpack("8B", data[0x80:0x88])
        monster_ys = struct.unpack("8B", data[0x88:0x90])
        monster_starts = list(zip(monster_xs, monster_ys))

        player_xs = struct.unpack("4B", data[0xA0:0xA4])
        player_ys = struct.unpack("4B", data[0xA4:0xA8])
        player_starts = list(zip(player_xs, player_ys))

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

    def load_dungeon_map(
        self, fname_or_id: str | int, m_def: MapDef | None = None
    ) -> DungeonMap:
        """Load 3D wireframe dungeon map (16x16x8 levels) with text messages."""
        if isinstance(fname_or_id, int):
            map_id = fname_or_id
            m_def = m_def or self.asset_mgr.map_defs.get(map_id)
            fname = m_def.fname if m_def else f"{map_id}.ult"
        else:
            fname = fname_or_id
            if m_def is None:
                fname_lower = fname.lower()
                for md in self.asset_mgr.map_defs.values():
                    if md.fname.lower() == fname_lower:
                        m_def = md
                        break

        file_path = self._resolve_data_file(fname)
        if not file_path.exists():
            raise FileNotFoundError(f"Dungeon map file not found: {file_path}")

        data = file_path.read_bytes()
        if len(data) < 2048:
            raise ValueError(
                f"Invalid dungeon map file {fname}: expected at least 2048 bytes, found {len(data)}"
            )

        raw_tiles = struct.unpack(f"{16 * 16 * 8}B", data[:2048])
        tiles: list[list[list[DungeonTile]]] = []
        pos = 0
        for z in range(8):
            level_grid: list[list[DungeonTile]] = []
            for y in range(16):
                row: list[DungeonTile] = []
                for x in range(16):
                    byte_val = raw_tiles[pos]
                    pos += 1
                    tile = DungeonTile.get_tile_by_value(byte_val)
                    row.append(tile)
                level_grid.append(row)
            tiles.append(level_grid)

        # Apply labels from maps.xml definitions (marks, special fountains, etc.)
        labels = list(m_def.labels) if m_def else []
        for label in labels:
            override = DungeonTile.from_name(label.name)
            if override and 0 <= label.z < 8 and 0 <= label.y < 16 and 0 <= label.x < 16:
                tiles[label.z][label.y][label.x] = override

        # Extract 8 level text messages from 0x800
        level_texts: list[str] = []
        if len(data) >= 0x810:
            text_offsets = struct.unpack("<8H", data[0x800:0x810])
            for off in text_offsets:
                start = 0x800 + off
                end = data.find(b"\x00", start)
                if end == -1:
                    end = min(start + 64, len(data))
                raw_text = data[start:end].decode("utf-8", errors="replace")
                cleaned = (
                    raw_text.strip()
                    .replace("<", "")
                    .replace(">", "")
                    .replace("\r", " ")
                    .replace("\n", " ")
                    .strip()
                )
                level_texts.append(cleaned)
        else:
            level_texts = [""] * 8

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

    def load_shrine_map(
        self, fname_or_id: str | int = "shrine.con", m_def: MapDef | None = None
    ) -> GameMap:
        """Load 11x11 shrine map with special index remappings."""
        if isinstance(fname_or_id, int):
            map_id = fname_or_id
            m_def = m_def or self.asset_mgr.map_defs.get(map_id)
            fname = m_def.fname if m_def else "shrine.con"
        else:
            fname = fname_or_id
            if m_def is None:
                fname_lower = fname.lower()
                for md in self.asset_mgr.map_defs.values():
                    if md.fname.lower() == fname_lower:
                        m_def = md
                        break

        file_path = self._resolve_data_file(fname)
        if not file_path.exists():
            raise FileNotFoundError(f"Shrine map file not found: {file_path}")

        data = file_path.read_bytes()
        if len(data) < 121:
            raise ValueError(
                f"Invalid shrine map file {fname}: expected at least 121 bytes, found {len(data)}"
            )

        raw_tiles = struct.unpack("121B", data[:121])
        tiles: list[TileDef] = []
        for b in raw_tiles:
            idx = b
            if idx == 4:
                idx = 1
            elif idx in (55, 57):
                idx = 102
            elif idx == 61:
                idx = 101
            elif idx == 31:
                idx = 103
            tile = self.asset_mgr.tile_defs.get(idx)
            if tile is None:
                tile = self.asset_mgr.tile_defs.get(36)
            tiles.append(tile)

        map_id = m_def.id if m_def else 55
        name = MAP_ID_TO_NAME.get(map_id, "SHRINE")
        music = m_def.music if m_def else "ALIVE"

        return GameMap(
            id=map_id,
            name=name,
            fname=fname,
            map_type=MapType.SHRINE,
            width=11,
            height=11,
            levels=1,
            border_behavior="fixed",
            music=music,
            no_line_of_sight=False,
            tiles=tiles,
            portals=list(m_def.portals) if m_def else [],
            moongates=list(m_def.moongates) if m_def else [],
            labels=list(m_def.labels) if m_def else [],
        )


def load_map(map_id: int, asset_mgr: AssetManager) -> GameMap:
    """Convenience module function to load a map by ID."""
    loader = MapLoader(asset_mgr)
    return loader.load_map(map_id)


def load_conflict_map(fname: str, asset_mgr: AssetManager) -> ConflictMap:
    """Convenience module function to load a conflict map by filename."""
    loader = MapLoader(asset_mgr)
    return loader.load_conflict_map(fname)


def load_dungeon_map(fname: str, asset_mgr: AssetManager) -> DungeonMap:
    """Convenience module function to load a dungeon map by filename."""
    loader = MapLoader(asset_mgr)
    return loader.load_dungeon_map(fname)


def load_shrine_map(fname: str, asset_mgr: AssetManager) -> GameMap:
    """Convenience module function to load a shrine map by filename."""
    loader = MapLoader(asset_mgr)
    return loader.load_shrine_map(fname)
