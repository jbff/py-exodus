"""Binary map loader for Ultima III (.ult, CNFLCT_*.ULT, shrine.con)."""
from __future__ import annotations

import struct
from pathlib import Path

from py_exodus.assets import COMBAT_MAPS, MAP_NAME_TO_ID, AssetManager
from py_exodus.entities.defs import MapDef
from py_exodus.world.map import (
    ConflictMap,
    DungeonMap,
    GameMap,
)
from py_exodus.world.map_build import (
    build_conflict_map,
    build_dungeon_map,
    build_grid_map,
    build_shrine_map,
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
    ) -> GameMap | DungeonMap:
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
        num_tiles = m_def.width * m_def.height
        if len(data) < num_tiles:
            raise ValueError(
                f"Map file {m_def.fname} has {len(data)} bytes, expected at least {num_tiles}"
            )

        map_struct = decode_grid_bytes(data, m_def.width, m_def.height)
        map_struct["source"] = m_def.fname
        return build_grid_map(m_def, map_struct, self.asset_mgr)

    def load_conflict_map(
        self, fname_or_id: str | int, m_def: MapDef | None = None
    ) -> ConflictMap:
        """Load 11x11 conflict map with player and monster spawn positions."""
        if isinstance(fname_or_id, int):
            map_id = fname_or_id
            m_def = m_def or self.asset_mgr.map_defs.get(map_id)
            fname = (
                (m_def.fname if m_def else COMBAT_MAPS.get(map_id))
                or f"CNFLCT_{map_id}.ULT"
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

        map_struct = decode_conflict_bytes(data)
        map_struct["source"] = fname
        return build_conflict_map(m_def, map_struct, self.asset_mgr)

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

        map_struct = decode_dungeon_bytes(data)
        map_struct["source"] = fname
        return build_dungeon_map(m_def, map_struct, self.asset_mgr)

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

        map_struct = decode_shrine_bytes(data)
        map_struct["source"] = fname
        return build_shrine_map(m_def, map_struct, self.asset_mgr)


def decode_grid_bytes(data: bytes, width: int, height: int) -> dict:
    """Decode a grid .ult file into a pure struct (tiles are indices = byte // 4)."""
    num_tiles = width * height
    raw_bytes = struct.unpack(f"{num_tiles}B", data[:num_tiles])
    tiles: list[list[int]] = [
        list(raw_bytes[y * width:(y + 1) * width]) for y in range(height)
    ]
    # b // 4 on each raw tile byte
    tiles = [[b // 4 for b in row] for row in tiles]

    # City NPCs (32 characters placed at 0x1180, 0x11A0, 0x11C0, 0x11E0, 0x1200);
    # all 32 raw slots, never filtered by the runtime null-slot skip rule
    npcs: list[dict] = []
    if len(data) >= 0x1200:
        npc_tiles = struct.unpack("32B", data[0x1180:0x11A0])
        underlying_tiles = struct.unpack("32B", data[0x11A0:0x11C0])
        npc_xs = struct.unpack("32B", data[0x11C0:0x11E0])
        npc_ys = struct.unpack("32B", data[0x11E0:0x1200])
        npc_ctrl = (
            struct.unpack("32B", data[0x1200:0x1220])
            if len(data) >= 0x1220
            else (0,) * 32
        )
        for i in range(32):
            npcs.append(
                {
                    "tile": npc_tiles[i] // 4,
                    "underlying": underlying_tiles[i] // 4,
                    "x": npc_xs[i],
                    "y": npc_ys[i],
                    "ctrl": npc_ctrl[i],
                }
            )

    # Extract 8 conversation texts from 0x1000
    texts: list[str] = []
    if len(data) >= 0x1010:
        text_offsets: list[int] = []
        for t_i in range(8):
            pos = 0x1000 + t_i * 2
            off = (data[pos] & 0xFF) + 0x1000
            text_offsets.append(off)

        for os in text_offsets:
            if 0 <= os < len(data):
                end = data.find(b"\x00", os)
                if end == -1:
                    end = min(os + 64, len(data))
                raw_str = data[os:end].decode("ascii", errors="replace")
                clean_str = (
                    raw_str.replace("<", "")
                    .replace(">", "")
                    .replace("\r", " ")
                    .replace("\n", " ")
                    .strip()
                )
                texts.append(clean_str)
            else:
                texts.append("")

    return {
        "width": width,
        "height": height,
        "tiles": tiles,
        "npcs": npcs,
        "conversations": texts,
    }


def decode_conflict_bytes(data: bytes) -> dict:
    """Decode a conflict .ult file into a pure struct (tiles are raw byte values)."""
    raw_tiles = struct.unpack("121B", data[:121])
    tiles: list[list[int]] = [
        list(raw_tiles[k * 11:(k + 1) * 11]) for k in range(11)
    ]

    monster_xs = struct.unpack("8B", data[0x80:0x88])
    monster_ys = struct.unpack("8B", data[0x88:0x90])
    monster_starts = [list(ms) for ms in zip(monster_xs, monster_ys)]

    player_xs = struct.unpack("4B", data[0xA0:0xA4])
    player_ys = struct.unpack("4B", data[0xA4:0xA8])
    player_starts = [list(ps) for ps in zip(player_xs, player_ys)]

    return {
        "tiles": tiles,
        "monster_starts": monster_starts,
        "player_starts": player_starts,
    }


def decode_dungeon_bytes(data: bytes) -> dict:
    """Decode a dungeon .ult file into a pure struct (tiles are raw dungeon-tile byte values)."""
    raw_tiles = struct.unpack(f"{16 * 16 * 8}B", data[:2048])
    tiles: list[list[list[int]]] = []
    pos = 0
    for z in range(8):
        level_grid: list[list[int]] = []
        for y in range(16):
            row: list[int] = []
            for x in range(16):
                byte_val = raw_tiles[pos]
                pos += 1
                row.append(byte_val)
            level_grid.append(row)
        tiles.append(level_grid)

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

    return {
        "tiles": tiles,
        "level_texts": level_texts,
    }


def decode_shrine_bytes(data: bytes) -> dict:
    """Decode a shrine .con file into a pure struct (tiles are raw .con byte values)."""
    raw_tiles = struct.unpack("121B", data[:121])
    tiles: list[list[int]] = [
        list(raw_tiles[k * 11:(k + 1) * 11]) for k in range(11)
    ]

    return {
        "tiles": tiles,
    }


def load_map(map_id: int, asset_mgr: AssetManager) -> GameMap | DungeonMap:
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
