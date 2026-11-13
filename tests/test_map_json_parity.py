"""Differential parity: JSON map assets match the binary decoders' structs.

The binary path and the JSON path coexisted only for this task; the test pins
JSON == binary decoder output (struct dicts, with "source" set on both sides)
before the runtime is rewired.
"""
from pathlib import Path

import pytest

from py_exodus.assets import AssetManager
from py_exodus.world.loader import (
    decode_conflict_bytes,
    decode_dungeon_bytes,
    decode_grid_bytes,
    decode_shrine_bytes,
)
from py_exodus.world.map_json import read_map_struct

# kind, decoder, decoder extra args (None for grid = (width, height) of the
# map def), keyed by literal map ids from asset_mgr.map_defs
KIND: dict[int, tuple[str, object, tuple[int, ...] | None]] = {
    **{i: ("combat", decode_conflict_bytes, ()) for i in range(33, 42)},
    **{i: ("dungeon", decode_dungeon_bytes, ()) for i in range(14, 21)},
    **{i: ("shrine", decode_shrine_bytes, ()) for i in range(55, 59)},
    **{i: ("grid", decode_grid_bytes, None) for i in range(0, 14)},
}


@pytest.fixture
def asset_mgr():
    am = AssetManager()
    am.load_tiles()
    am.load_xml_definitions()
    return am


def test_all_31_maps_roundtrip_identical(asset_mgr):
    """Every map def's JSON file equals its binary decode (structs, not objects)."""
    json_names: set[str] = set()
    for m_def in asset_mgr.map_defs.values():
        kind, decode, extra = KIND[m_def.id]
        if extra is None:
            extra = (m_def.width, m_def.height)
        raw = asset_mgr.resolve_path("data", m_def.fname).read_bytes()
        data = decode(raw, *extra)
        data["source"] = Path(m_def.fname).name
        json_name = f"{Path(m_def.fname).stem.lower()}.json"
        json_names.add(json_name)
        from_json = read_map_struct(asset_mgr.resolve_path("maps", json_name))
        assert from_json == data, m_def.id
    # 31 distinct map files: 31 unique fnames across map_defs
    assert len(json_names) == 31


def test_read_map_struct_missing_file_raises(asset_mgr):
    with pytest.raises(FileNotFoundError):
        read_map_struct(asset_mgr.resolve_path("maps", "does_not_exist.json"))
