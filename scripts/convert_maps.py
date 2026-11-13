#!/usr/bin/env python
"""One-time converter: binary assets -> JSON (output committed).

The map mode generated ``assets/maps/*.json`` from the binary maps; those
JSON assets are committed and the runtime now loads them directly, so the
map mode's binary decoders no longer exist in the codebase and it errors
out if re-run. The ``--roster`` mode converts ``assets/data/roster.ult``.

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


def convert_maps(force: bool = False) -> int:
    """Regenerate assets/maps/*.json — historical mode.

    The JSON map assets are committed and the runtime loads them; the binary
    map decoders this mode used were deleted with the binary loading path.
    """
    print(
        "map conversion already completed (assets/maps/*.json committed); "
        "the binary map decoders were deleted — use --roster instead"
    )
    return 1


def convert_roster(force: bool = False) -> int:
    """Convert assets/data/roster.ult to assets/data/roster.json.

    Decodes the binary roster with SaveSystem.load_binary_roster (the same
    byte-level record decoder the deleted loader used) and writes the named
    characters in SaveSystem.save_roster's exact JSON format — the same file
    shape the runtime reads back with SaveSystem.load_roster.
    """
    from py_exodus.save_system import SaveSystem

    root = Path(__file__).resolve().parents[1]
    src = root / "assets" / "data" / "roster.ult"
    out_path = root / "assets" / "data" / "roster.json"

    if not src.exists():
        print(f"MISSING {src} (nothing to convert)")
        return 1
    if out_path.exists() and not force:
        print(f"REFUSING to overwrite {out_path} (use --force)")
        return 1

    records = SaveSystem.load_binary_roster(src)
    named = [char for char in records if char.name.strip()]
    SaveSystem.save_roster(named, out_path)
    print(f"WROTE {out_path.name}: {len(records)} record(s) decoded, "
          f"{len(named)} named character(s)")
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
        help="convert assets/data/roster.ult to assets/data/roster.json",
    )
    args = parser.parse_args()

    if args.roster:
        return convert_roster(force=args.force)
    return convert_maps(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
