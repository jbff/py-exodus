"""JSON map loader for Ultima III (world, city, CNFLCT_*, dungeon, shrine)."""
from __future__ import annotations

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
from py_exodus.world.map_json import read_map_struct


class MapLoader:
    """Loads world, city, combat, dungeon, and shrine maps from JSON assets.

    Map names match case-insensitively by stem: legacy-style caller strings
    such as ``CNFLCT_A.ULT`` or ``perinian.ult`` resolve against the maps.xml
    fnames (``cnflct_a.json``, ``perinian.json``) by ``Path(fname).stem``.
    """

    def __init__(self, asset_mgr: AssetManager) -> None:
        self.asset_mgr = asset_mgr
        if not self.asset_mgr.tile_defs:
            self.asset_mgr.load_tiles()
        if not self.asset_mgr.map_defs:
            self.asset_mgr.load_xml_definitions()

    def _resolve_json_file(self, fname: str) -> Path:
        """Resolve the JSON map asset for a map fname, matched by stem."""
        stem = Path(fname).stem
        return self.asset_mgr.resolve_path("maps", f"{stem}.json")

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
                # Search by filename stem or type
                name_lower = map_id_or_name.strip().lower()
                name_stem = Path(name_lower).stem.lower()
                for md in self.asset_mgr.map_defs.values():
                    md_stem = Path(md.fname).stem.lower()
                    if md.fname.lower() == name_lower or md_stem == name_stem:
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
        """Load 2D world or city grid map (64x64)."""
        file_path = self._resolve_json_file(m_def.fname)
        map_struct = read_map_struct(file_path)
        map_struct.setdefault("width", m_def.width)
        map_struct.setdefault("height", m_def.height)
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
                or f"cnflct_{map_id}.json"
            )
        else:
            fname = fname_or_id
            if m_def is None:
                fname_stem = Path(fname).stem.lower()
                for md in self.asset_mgr.map_defs.values():
                    if Path(md.fname).stem.lower() == fname_stem:
                        m_def = md
                        break

        file_path = self._resolve_json_file(fname)
        map_struct = read_map_struct(file_path)
        map_struct["source"] = fname
        return build_conflict_map(m_def, map_struct, self.asset_mgr)

    def load_dungeon_map(
        self, fname_or_id: str | int, m_def: MapDef | None = None
    ) -> DungeonMap:
        """Load 3D wireframe dungeon map (16x16x8 levels) with text messages."""
        if isinstance(fname_or_id, int):
            map_id = fname_or_id
            m_def = m_def or self.asset_mgr.map_defs.get(map_id)
            fname = m_def.fname if m_def else f"{map_id}.json"
        else:
            fname = fname_or_id
            if m_def is None:
                fname_stem = Path(fname).stem.lower()
                for md in self.asset_mgr.map_defs.values():
                    if Path(md.fname).stem.lower() == fname_stem:
                        m_def = md
                        break

        file_path = self._resolve_json_file(fname)
        map_struct = read_map_struct(file_path)
        map_struct["source"] = fname
        return build_dungeon_map(m_def, map_struct, self.asset_mgr)

    def load_shrine_map(
        self, fname_or_id: str | int = "shrine.json", m_def: MapDef | None = None
    ) -> GameMap:
        """Load 11x11 shrine map with special index remappings."""
        if isinstance(fname_or_id, int):
            map_id = fname_or_id
            m_def = m_def or self.asset_mgr.map_defs.get(map_id)
            fname = m_def.fname if m_def else "shrine.json"
        else:
            fname = fname_or_id
            if m_def is None:
                fname_stem = Path(fname).stem.lower()
                for md in self.asset_mgr.map_defs.values():
                    if Path(md.fname).stem.lower() == fname_stem:
                        m_def = md
                        break

        file_path = self._resolve_json_file(fname)
        map_struct = read_map_struct(file_path)
        map_struct["source"] = fname
        return build_shrine_map(m_def, map_struct, self.asset_mgr)


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
