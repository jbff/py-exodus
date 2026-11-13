#!/usr/bin/env python
"""One-time converter: binary map files -> assets/maps/*.json (output committed).

Decodes each maps.xml fname with the same pure byte-decoders the binary loader
uses, adds "source" (the original filename), and writes
``assets/maps/<Path(fname).stem.lower()>.json`` with indent=2. Refuses to
overwrite existing files unless --force. Nothing is rewired to JSON by this
script; it only generates the assets.

Usage:
    python scripts/convert_maps.py [--force] [--roster]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Run from anywhere: import the package relative to this script's repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from py_exodus.assets import AssetManager  # noqa: E402
from py_exodus.world.loader import (  # noqa: E402
    decode_conflict_bytes,
    decode_dungeon_bytes,
    decode_grid_bytes,
    decode_shrine_bytes,
)
from py_exodus.world.map_json import MAP_KIND_BY_TYPE  # noqa: E402


def _decode_grid(raw: bytes, width: int, height: int) -> dict:
    return decode_grid_bytes(raw, width, height)


def _decode_conflict(raw: bytes, width: int, height: int) -> dict:
    return decode_conflict_bytes(raw)


def _decode_dungeon(raw: bytes, width: int, height: int) -> dict:
    return decode_dungeon_bytes(raw)


def _decode_shrine(raw: bytes, width: int, height: int) -> dict:
    return decode_shrine_bytes(raw)


DECODERS: dict[str, object] = {
    "grid": _decode_grid,
    "combat": _decode_conflict,
    "dungeon": _decode_dungeon,
    "shrine": _decode_shrine,
}


def convert_maps(force: bool = False) -> int:
    asset_mgr = AssetManager()
    asset_mgr.load_tiles()
    asset_mgr.load_xml_definitions()

    out_dir = asset_mgr.resolve_path("maps")
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    seen: set[Path] = set()
    for m_def in sorted(asset_mgr.map_defs.values(), key=lambda md: md.id):
        kind = MAP_KIND_BY_TYPE.get(m_def.map_type.lower())
        if kind is None:
            print(f"SKIP id={m_def.id}: unknown map_type {m_def.map_type!r}")
            continue
        decode = DECODERS.get(kind)
        if decode is None:
            print(f"SKIP id={m_def.id}: no decoder for kind {kind!r}")
            continue

        out_path = out_dir / f"{Path(m_def.fname).stem.lower()}.json"
        if out_path in seen:
            # maps.xml may repeat a fname (e.g. shrine.con); one file, no rewrite
            continue
        if out_path.exists() and not force:
            print(f"REFUSING to overwrite {out_path} (use --force)")
            continue

        raw = asset_mgr.resolve_path("data", m_def.fname).read_bytes()
        map_struct = decode(raw, m_def.width, m_def.height)
        map_struct["source"] = Path(m_def.fname).name
        out_path.write_text(
            json.dumps(map_struct, indent=2) + "\n", encoding="utf-8"
        )
        seen.add(out_path)
        written += 1
        print(f"WROTE {out_path.name}")

    print(f"{written} JSON file(s) written to {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing JSON files",
    )
    parser.add_argument(
        "--roster",
        action="store_true",
        help="convert assets/data/roster.ult to assets/data/roster.json "
        "(roster mode lands in the roster task)",
    )
    args = parser.parse_args()

    if args.roster:
        print("--roster: roster conversion is implemented in the roster task")
        return 1
    return convert_maps(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
