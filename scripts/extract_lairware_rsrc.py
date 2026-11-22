"""Extract LairWare resources the port needs from MainResources.rsrc.

Run once: python3 scripts/extract_lairware_rsrc.py
Writes assets/data/lairware_intro.json with:
  DEMO  the View's 512-step script: 512 "where" bytes then 512 "what" bytes
  SGNT  the "by Lord British" signature stroke data
The .rsrc is a data-fork Mac resource file (Inside Macintosh: More Toolbox
Essentials, Resource Manager file format).
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

SRC = Path("refs/ultima3/Resources/English.lproj/MainResources.rsrc")
OUT = Path("assets/data/lairware_intro.json")
BASERES = 400


def read_resources(data: bytes) -> dict[tuple[str, int], bytes]:
    data_off, map_off, _data_len, _map_len = struct.unpack(">IIII", data[:16])
    type_list_off, name_list_off = struct.unpack(">HH", data[map_off + 24 : map_off + 28])
    tl = map_off + type_list_off
    (n_types,) = struct.unpack(">H", data[tl : tl + 2])
    out: dict[tuple[str, int], bytes] = {}
    for t in range(n_types + 1):
        rtype, n, ref_off = struct.unpack(">4sHH", data[tl + 2 + 8 * t : tl + 10 + 8 * t])
        for r in range(n + 1):
            ref = tl + ref_off + 12 * r
            rid, _name, attr_off = struct.unpack(">hhI", data[ref : ref + 8])
            off = data_off + (attr_off & 0xFFFFFF)
            (length,) = struct.unpack(">I", data[off : off + 4])
            out[(rtype.decode("mac_roman"), rid)] = data[off + 4 : off + 4 + length]
    return out


def main() -> int:
    res = read_resources(SRC.read_bytes())
    want = {}
    for kind in ("DEMO", "SGNT"):
        ids = sorted(rid for (t, rid) in res if t == kind)
        if not ids:
            print(f"no {kind} resource", file=sys.stderr)
            return 1
        rid = BASERES if BASERES in ids else ids[0]
        want[kind] = list(res[(kind, rid)])
        print(kind, rid, len(want[kind]), "bytes")
    OUT.write_text(json.dumps(want, separators=(",", ":")) + "\n")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
