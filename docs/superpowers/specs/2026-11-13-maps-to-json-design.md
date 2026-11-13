# No Binary / Proprietary Assets in the Python Port (design)

Date: 2026-11-13. Status: approved.

## Intent

Every file the Python port loads must be an open, editable format — no binary
or proprietary assets in the runtime load path at all. This means: convert the
31 map binaries (and the binary character roster) to JSON, rewire the loaders,
and delete every unused, unreferenced asset along with the dead originals.

## Goals

- Maps stored as JSON, one file per map, plainly editable (integer grids, named
  fields) — same spirit the JSON saves already established.
- Character roster as JSON (`assets/data/roster.json`), replacing the binary
  `roster.ult` import source.
- Zero behavioral change: a map loaded from JSON produces exactly the
  `GameMap` / `DungeonMap` / `ConflictMap` object the binary path produced.
- Asset directory contains no unused files: everything not reachable from the
  loader graphs is deleted.

## Non-goals

- No re-conversion of the XML defs (creatures/weapons/armors/maps/vendors/
  tileset-base). They are already open and byte-match the Java edition's
  resources, which the parity workflow depends on.
- No TMX or Tiled *support* (the unused TMX folder is deleted); no gameplay
  changes.

## Approaches considered

- **A. JSON per map (chosen).** `assets/maps/<name>.json` holding a plain
  integer grid + named side data. Matches the save precedent, single file per
  map, trivially testable, no new schema tooling.
- **B. TMX grids + sidecar JSON.** Tiled-editor editable, but tiles live as
  merged CSV/base64, NPCs and spawns don't fit the schema, two conventions
  everywhere.
- **C. Grids inside existing XML.** Same family as `maps.xml`, but a 4096-int
  grid is bulky XML and grids are data, not definitions.

## Constraints

- Java source is truth, bugs included. All load-time *transformations stay in
  loader code*, applied exactly as today:
  - tile 46 → `locked_door` when not flanked by signs
  - Ambrosia (id 13) fixed locked doors at row 5, x 34–36
  - Sosaria (id 0) moongate reset to grass
  - city NPC decode rules (ctrl byte → movement; conversation texts)
  - shrine `.con` tile-index remapping
- The JSON therefore is a faithful *structural dump* of each file's content —
  not a dump of post-transform game state.

## File layout and schema

New directory `assets/maps/`. One JSON per live map, lowercased basename:
`sosaria.json`, `british.json`, … `cnflct_a.json` … `shrine.json`,
`death.json`, `perinian.json`, …

Common envelope:

```json
{
  "source": "sosaria.ult",
  "width": 64,
  "height": 64
}
```

- **Grid maps** (world/city): `tiles` = rows of integers = resolved tile
  indices (original byte // 4; the Java loader ignores the low 2 bits). City
  maps add:
  - `npcs`: all 32 raw entries `{tile, underlying, x, y, ctrl}` (resolved
    indices + raw ctrl byte) — the runtime null-slot skip rule stays in
    loader code, so the JSON is a pure file-content dump.
  - `conversations`: the decoded conversation strings (up to 8), `null` where
    the original had none; offsets and NUL-terminators are gone at this layer.
- **Combat maps**: `tiles` = 11x11 indices, `monster_starts` = 8 `[x, y]`
  pairs, `player_starts` = 4 `[x, y]` pairs (raw values as stored, including
  unused zero slots).
- **Dungeon maps**: `tiles` = 8 x 16 x 16 raw dungeon-tile values,
  `level_texts` = up to 8 decoded strings.
- **Shrine**: plain 11x11 indices; the remap stays in loader code.

`maps.xml` `fname` values and the `COMBAT_MAPS` table in `assets.py` are
updated to the new names, keeping the XML the single index of which file holds
which map.

## Roster conversion

`roster.ult` (1280 bytes, up to 20 characters) is decoded with the existing
`save_system` binary-reading logic and written to `assets/data/roster.json`
(array of character records). `roster_screen.py` loads JSON. The binary party
(`party.ult`, 274 bytes) and roster loading paths in `save_system.py` are
removed — saves and rosters are JSON-only going forward.

## Conversion and rewiring

- New `scripts/convert_maps.py`: reads each original, writes JSON
  deterministically; refuses to overwrite. Run once, output committed.
- `scripts/convert_roster.py` (or a mode of the same script) for `roster.json`.
- `MapLoader` reads JSON; after differential tests pass, the binary decoding
  path and the originals are removed outright — no preservation copies on
  disk (git history keeps them, and they may drop out of tracking naturally).

## Deletion: unused assets (full sweep)

Deleting files with *no reference anywhere in `py_exodus/`, `tests/`,
`scripts/`* (each stem verified against dynamic reference patterns before
deletion):

- The dead binaries: `ultima.com`, `bootup.bin`, `exodus.bin`, `animate.dat`,
  `dungeon.dat`, `name.dat`, `charset.ult`, `shapes.ult`, `moves.ult`,
  `demo.ult`, `party.ult`, `blank.ibm`, `exod.ibm`, `brand.img`,
  `fountain.img`, `time.img`.
- `roster.ult` after conversion.
- The 31 map originals after JSON verification.
- The entire unused `assets/tmx/` folder.
- Anything else the sweep finds: unused sound files, `.mid` rippers, LibGDX
  `.g3db` models, `.img`, `.atlas`/`uiskin` skins, unused image/font strays —
  with the sweep list reviewed in the implementation plan before deletion.
- Kept: `ultima3.txt` (read by `book.py`), plus every file the code or the
  atlas index references.

## Verification

- Differential verification: load every map through the old binary path and
  the new JSON path, assert equal resulting objects (tiles, npcs, starts,
  texts) before any deletion; same for the roster (JSON records must equal the
  binary decode).
- Full existing test suite passes.
- A smoke run of the game boots fully (world + city + dungeon entry) from JSON
  only, with the originals deleted.

## Builder's discretion

Final JSON key names inside the schema above, internal code structure of the
JSON branch, and test file naming.
