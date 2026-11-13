# Assets to Open Formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Python port loads zero binary/proprietary files — all 31 maps, the roster, and nothing else binary; every unused asset deleted.

**Architecture:** Refactor `MapLoader`'s decode logic into pure byte-decoders producing JSON-shaped structures plus independent builders; add a JSON reader for the same structures; generate `assets/maps/*.json` from the binaries once; differential-test JSON vs binary; switch load paths to JSON and delete the binary path; convert the roster; sweep the asset tree against an added load-graph test.

**Tech Stack:** Python 3.14, Pygame-CE, stdlib `json`/`struct` (struct confined to the decoders, deleted in Task 3).

**Spec:** `docs/superpowers/specs/2026-11-13-maps-to-json-design.md`

## Global Constraints

- Java source is truth, bugs included: every load-time transform (tile 46 → locked_door when not flanked by signs; Ambrosia id-13 locked doors at row 5 x 34–36; Sosaria id-0 moongate reset; NPC ctrl→movement decode; null-NPC skip rule `nx==0 and ny==0 and (name=="water" or idx==0)`; shrine `.con` index remap; dungeon label overrides from maps.xml) stays in **loader/builder code**, applied identically on both paths.
- No new dependencies. JSON written with `indent=2`.
- Full test suite runs headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests -q`.
- Every commit message ends `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- Test suite must be green before each commit.

## Review Focus

- **SFX deletions must not break playing sounds.** `audio.py:resolve_sound_file` resolves 20 literal `play_sfx` names case-insensitively across `.ogg`/`.mp3`/`.mid`; 14 resolve today, 6 already resolve to nothing (`lightning`, `negative`, `negative_effect`, `rocks`, `wave`, `whirlpool`). Deletion must keep the 14 resolving and add no new failures. Pinned by `test_play_sfx_literals_resolve` (Task 5).
- **Name matching is stem- and case-insensitive.** Tests pass legacy-style names (`"CNFLCT_A.ULT"`, `"PERINIAN.ULT"`) that no longer exist on disk after conversion; `MapLoader.load_map` / `load_conflict_map` must match `maps.xml` entries by `Path(fname).stem` case-insensitively. Pinned by existing updated tests (Task 3).
- **A missing map file still raises `FileNotFoundError`** (`tests/test_map_loader.py:223` uses `does_not_exist.ult`) — the JSON path must preserve that. Pinned in Task 3.
- **Null NPC slots stay runtime-filtered.** JSON stores all 32 raw entries; the skip rule runs in the builder, so a hand-edited JSON with fewer entries yields exactly those NPCs. Pinned by parity test (Task 2) and city-loading tests.
- **Shrine remap and dungeon label overrides stay load-time.** JSON holds raw values; behavior identical to binary reading. Pinned by parity test and `tests/test_dungeon.py`, `tests/test_search_and_labels.py`.

---

### Task 1: Extract pure struct decoders and builders from `MapLoader`

**Files:**
- Create: `py_exodus/world/map_build.py`
- Modify: `py_exodus/world/loader.py`
- Test: existing suite (no behavior change — regression only)

**Interfaces:**
- Consumes: nothing new (existing `AssetManager`, `MapDef`, `TileDef`, `DungeonTile`).
- Produces (Tasks 2–3 rely on exact signatures):
  ```python
  # py_exodus/world/map_build.py
  def build_grid_map(m_def: MapDef, struct: dict, asset_mgr: AssetManager) -> GameMap
  def build_conflict_map(m_def: MapDef, struct: dict, asset_mgr: AssetManager) -> ConflictMap
  def build_dungeon_map(m_def: MapDef, struct: dict, asset_mgr: AssetManager) -> DungeonMap
  def build_shrine_map(m_def: MapDef, struct: dict, asset_mgr: AssetManager) -> GameMap
  # py_exodus/world/loader.py — pure, asset_mgr-free byte decoders:
  def decode_grid_bytes(data: bytes, width: int, height: int) -> dict
  def decode_conflict_bytes(data: bytes) -> dict
  def decode_dungeon_bytes(data: bytes) -> dict
  def decode_shrine_bytes(data: bytes) -> dict
  ```

Struct shapes (exactly the JSON schema; `"source"` is added by the JSON writer, not the decoders):
- grid: `{"width": int, "height": int, "tiles": [[int] × width] × height` (indices = raw byte // 4), `"npcs": [{"tile": idx, "underlying": idx, "x": int, "y": int, "ctrl": int}] × 32` (all raw slots, never filtered), `"conversations": (str | None) × 8`}
- combat: `{"tiles": [[int] × 11] × 11` (raw byte values), `"monster_starts": [x, y] × 8`, `"player_starts": [x, y] × 4`}
- dungeon: `{"tiles": [[int × 16] × 16] × 8` (raw dungeon-tile byte values), `"level_texts": (str | None) × 8`}
- shrine: `{"tiles": [[int] × 11] × 11` (raw `.con` byte values; remap happens in `build_shrine_map`)

`build_*` absorb every load-time transform listed in Global Constraints, verbatim from today's `_load_grid_map` / `load_conflict_map` / `load_dungeon_map` / `load_shrine_map` bodies.

- [ ] **Step 1: Run the full suite before touching anything, confirm green** (`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests -q`). Expected: PASS.
- [ ] **Step 2:** Move the four decode bodies in `loader.py` into the pure `decode_*_bytes` functions and move the GameMap/DungeonMap/ConflictMap construction code into the four `map_build.build_*` functions; `MapLoader.load_map` and friends now call `decode_*_bytes` → `build_*`. No logic edits — line-for-line motion. `load_binary_*` save-system functions are untouched.
- [ ] **Step 3: Run the full suite.** Expected: PASS (identical to Step 1 failures — none).
- [ ] **Step 4: Commit**
  ```bash
  git add py_exodus/world/loader.py py_exodus/world/map_build.py
  git commit -m "refactor: pure map struct decoders and builders, no behavior change"
  ```

### Task 2: JSON reader, converter script, and differential parity test

**Files:**
- Create: `py_exodus/world/map_json.py`, `scripts/convert_maps.py`, `tests/test_map_json_parity.py`, `assets/maps/*.json` (31 generated files, committed)
- Test: `tests/test_map_json_parity.py`

**Interfaces:**
- Consumes: Task 1's `decode_*_bytes` / `build_*`; `AssetManager.resolve_path("maps", name)`.
- Produces:
  ```python
  # py_exodus/world/map_json.py
  MAP_KIND_BY_TYPE: {"world": "grid", "city": "grid", "castle": "grid", "combat": "combat", "dungeon": "dungeon", "shrine": "shrine"}
  def read_map_struct(path: Path) -> dict   # json.load; FileNotFoundError if path missing
  # scripts/convert_maps.py
  python scripts/convert_maps.py [--force] [--roster]   # writes assets/maps/<lowercase stem>.json
  ```

`read_map_struct` validates the shape minimally: requires `tiles`, and for grid maps `npcs`/`conversations`, for combat `monster_starts`/`player_starts`, for dungeon `level_texts`. The converter decodes each `maps.xml` fname via Task 1 decoders, adds `"source"`, and writes `assets/maps/<Path(fname).stem.lower()>.json`; refuses to overwrite unless `--force`.

Parity test core (compare structures, not objects — avoids vendor object-identity traps):

```python
KIND = {
    33-41: ("combat", decode_conflict_bytes, ()),
    14-20: ("dungeon", decode_dungeon_bytes, ()),
    55-58: ("shrine", decode_shrine_bytes, ()),
    all other ids: ("grid", decode_grid_bytes, (m_def.width, m_def.height)),
}  # ranges expanded to literal ids from asset_mgr.map_defs

def test_all_31_maps_roundtrip_identical(asset_mgr):
    for m_def in asset_mgr.map_defs.values():
        kind, decode, extra = KIND[m_def.id]
        raw = data file bytes for m_def.fname          # assets/data/<fname>
        data = decode(raw, *extra)
        data["source"] = Path(m_def.fname).name
        from_json = read_map_struct(asset_mgr.resolve_path(
            "maps", f"{Path(m_def.fname).stem.lower()}.json"))
        assert from_json == data, m_def.id
```

- [ ] **Step 1: Write the failing test** `tests/test_map_json_parity.py` with the round-trip above over exactly the 31 map ids present in `asset_mgr.map_defs` whose fnames end in `.ult`/`.ULT`/`.con`. Run: `pytest tests/test_map_json_parity.py -v`. Expected: FAIL (no `assets/maps/` yet).
- [ ] **Step 2:** Implement `py_exodus/world/map_json.py` and `scripts/convert_maps.py`; run the converter; confirm 31 files in `assets/maps/`.
  Run: `python -c "import pathlib; print(len(list(pathlib.Path('assets/maps').glob('*.json'))))"`. Expected: 31.
- [ ] **Step 3: Run parity test.** `pytest tests/test_map_json_parity.py -v`. Expected: PASS.
- [ ] **Step 4: Run full suite** (existing tests must stay green — nothing rewired yet). Expected: PASS.
- [ ] **Step 5: Commit**
  ```bash
  git add py_exodus/world/map_json.py scripts/convert_maps.py tests/test_map_json_parity.py assets/maps
  git commit -m "feat: JSON map assets generated from binaries, differential loader"
  ```

### Task 3: Load maps from JSON only; delete the binary map path

**Files:**
- Modify: `py_exodus/world/loader.py`, `py_exodus/assets.py` (COMBAT_MAPS values + `TileDef.combat_map_fname` default + fallback at `_load_tileset_xml`), `assets/xml/maps.xml` (31 `fname` values), `py_exodus/screens/dungeon_screen.py:81,419`, `py_exodus/screens/shrine.py:85,90`, tests: `test_map_loader.py`, `test_dungeon.py:36`, `test_music_invariant.py:156`, `test_game_loop.py`, `test_magic_system.py:37`, `test_dungeon_specials.py:681`, `test_death_flow.py:526`, `test_xml_defs.py:16,102,188`
- Delete: `tests/test_map_json_parity.py`, the binary decode functions, the 31 binaries in `assets/data/`
- Test: existing suite

**Interfaces:**
- Consumes: Task 2's `read_map_struct`, Task 1's `build_*`.
- Produces: `MapLoader.load_map(map_id_or_name)` resolves `asset_mgr.resolve_path("maps", f"{stem}.json")` where `stem = Path(m_def.fname).stem`; fname lookups match by `Path(fname).stem.lower()` both when scanning `asset_mgr.map_defs` and in `AssetManager.get_map_def`. Missing file → `FileNotFoundError`.

The 31 `maps.xml` fname updates: `.ult` → `.json` lowercased (`sosaria.ult` → `sosaria.json`, `CNFLCT_A.ULT` → `cnflct_a.json`, `m.ult` → `m.json`, …), `shrine.con` → `shrine.json`. Test filename literals get the same replacement (`"PERINIAN.ULT"` → `"perinian.json"`, `"does_not_exist.ult"` → `"does_not_exist.json"`, …). `test_map_json_parity.py` is deleted here: its guarantee (JSON ≡ binary decode) was pinned while both paths existed and lives in commit history.

- [ ] **Step 1:** Rewire `MapLoader` per Interfaces; delete `decode_*_bytes`, `_resolve_data_file`, and all binary-path reading; apply the stem-matching change in `load_map`, `load_conflict_map`, `load_dungeon_map`, `load_shrine_map`, and `AssetManager.get_map_def`. Update `maps.xml`, code strings, and test literals to the new names.
- [ ] **Step 2:** Delete the 31 binary map files: `git rm assets/data/*.ult assets/data/*.ULT assets/data/shrine.con` and `git rm tests/test_map_json_parity.py`.
- [ ] **Step 3: Run the full suite.** Expected: PASS.
- [ ] **Step 4: Verify with the `struct` grep: no `struct` import outside `save_system.py` remains in map code**
  Run: `grep -rn "struct" py_exodus/world/`
  Expected: no import hits (docstring mentions only).
- [ ] **Step 5: Commit**
  ```bash
  git add -A
  git commit -m "feat: load all maps from JSON; delete binary map decoding path"
  ```

### Task 4: JSON roster; delete binary roster/party loading

**Files:**
- Create: `assets/data/roster.json` (via `scripts/convert_maps.py --roster`)
- Modify: `scripts/convert_maps.py` (add `--roster` mode), `py_exodus/save_system.py` (delete `load_binary_party` at :266, `load_binary_roster` at :303, the `.ult`/`.sav` branch in `load_roster` at :91-97 — JSON only), `py_exodus/screens/roster_screen.py:88-110` (candidates → `saves/roster.json`, `assets/data/roster.json`; update the roster.ult comment), `tests/test_creation_parity.py:501-503` (rewrite the `party.ult` round-trip to call `SaveSystem.parse_binary_character_record` directly on the record bytes and assert the same fields)
- Delete: `assets/data/roster.ult`
- Test: `tests/test_roster_screen.py`, `tests/test_party_save.py`, `tests/test_creation_parity.py`

**Interfaces:**
- Consumes: `SaveSystem.load_binary_roster` (decode source — run before deleting), `SaveSystem.save_roster` JSON record format.
- Produces: `SaveSystem.load_roster(path)` loads JSON arrays of `"characters"` records only; `parse_binary_character_record` stays (Java-format parity helper used by `test_creation_parity.py`, no file reads).

`--roster` decodes `assets/data/roster.ult` via `SaveSystem.load_binary_roster` and writes `assets/data/roster.json` in `save_roster`'s exact format — the file is all-zero, so the result is an empty character array; assert that in the script run output.

- [ ] **Step 1: Add the `--roster` mode; run it**
  Run: `python scripts/convert_maps.py --roster && python -c "import json; d=json.load(open('assets/data/roster.json')); print(d)"`
  Expected: prints an array with no named characters (empty roster per Java truth, `roster_screen.py:85-99`).
- [ ] **Step 2: Update `roster_screen.py` and `save_system.py` per Files; rewrite the `test_creation_parity.py` party round-trip; delete `roster.ult`.**
- [ ] **Step 3: Run suite (and roster/save tests explicitly first)**
  Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_roster_screen.py tests/test_party_save.py tests/test_creation_parity.py -v && SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests -q`
  Expected: PASS.
- [ ] **Step 4: Commit**
  ```bash
  git add -A
  git commit -m "feat: JSON roster only; remove binary roster/party save loading"
  ```

### Task 5: Asset sweep, load-graph test, and final verification

**Files:**
- Create: `tests/test_asset_load_graph.py`
- Delete (each verified unreferenced by full-name grep before `git rm`; `py_exodus/`, `tests/`, `scripts/` are the reference corpora):
  - `assets/data/` dead files: `bootup.bin`, `exodus.bin`, `ultima.com`, `animate.dat`, `dungeon.dat`, `name.dat`, `blank.ibm`, `exod.ibm`, `brand.img`, `fountain.img`, `time.img`, `charset.ult`, `shapes.ult`, `moves.ult`, `demo.ult`, `party.ult`
  - `assets/tmx/` (entire directory, 23 files)
  - `assets/graphics/`: `Metal_Embossed.jpg`, `Stone_Brushed_Khaki.jpg`, `Stone_Masonry.jpg`, `Stone_Vein_Gray.jpg`, `Water_Sparkling.jpg`, `Wood_Cherry.jpg`, `Wood__Floor.jpg`, `Portraits.gif`, `Exp_type_B.atlas`, `Exp_type_B.png`, `cloud-atlas.txt`, `cloud.png`, `dirt.png`, `door.png`, `explosion-atlas.txt`, `explosion.png`, `frame.png`, `grass.png`, `latest.png`, `map.png`, `moon-atlas.txt`, `moonPhases.png`, `mortar.png`, `rock.png`, `scroll.png`, `u3ega-shapes.png`, `warrior.png`, `altar.g3db`, `chest.g3db`, `fountain2.g3db`, `ladder.g3db`, `orb.g3db`, `wizard.g3db`
  - `assets/fonts/`: `Arial_12.fnt`, `Arial_12.png`, `babas.otf`, `exodus.fnt`, `exodus1.png`, `exodus2.png`, `lindberg.ttf`, `sansblack.ttf`
  - `assets/skin/` (entire directory)
  - `assets/sound/`: all 10 `.mid` files and every `.ogg` not in this keep list: `Alive.ogg`, `Castles.ogg`, `Combat.ogg`, `Dungeon.ogg`, `Exodus.ogg`, `Fanfare.ogg`, `Rule Britannia.ogg`, `Rule Brittania.ogg`, `Shopping.ogg`, `Towns.ogg`, `Wander.ogg`, `title_fade.ogg` (MUSIC_TRACKS), `AncientSpirits.ogg`, `DivineMed.ogg`, `blocked.ogg`, `boom.ogg`, `enemy_magic_proj.ogg`, `magic.ogg`, `moongate_flash.ogg`, `pc_attack.ogg`, `tornado.ogg`, `trigger.ogg`, `walk_normal.ogg` (resolving SFX), `cannon.mp3`, `giggle.mp3`.
  - Kept in `assets/data/`: only `ultima3.txt` (read by `screens/book.py`).
- Modify: `README.md:13` (asset-paragraph wording: JSON maps instead of binary `.ult`), `README.md:132` (drop "legacy binary roster import is read-only", note save/roster JSON-only)
- Test: `tests/test_asset_load_graph.py`

Load-graph test (the deletion guard — write it FIRST, before deleting):

```python
"""Every file the game loads by name exists after the asset sweep."""

def test_music_tracks_exist():
    for v in set(MUSIC_TRACKS.values()):
        assert (sound_dir / v).exists(), v

def test_play_sfx_literals_resolve():
    LITERAL_SFX = ["AncientSpirits", "blocked", "boom", "cannon", "DivineMed",
                   "enemy_magic_proj", "Fanfare", "giggle", "lightning", "magic",
                   "moongate_flash", "negative", "negative_effect", "pc_attack",
                   "rocks", "tornado", "trigger", "walk_normal", "wave", "whirlpool"]
    ALREADY_UNRESOLVED = {"lightning", "negative", "negative_effect", "rocks", "wave", "whirlpool"}
    am = AudioManager(enabled=False)
    for name in LITERAL_SFX:
        assert name in ALREADY_UNRESOLVED or am.resolve_sound_file(name) is not None, name

def test_all_map_defs_resolve(asset_mgr):
    for m_def in asset_mgr.map_defs.values():
        assert asset_mgr.resolve_path("maps", f"{Path(m_def.fname).stem}.json").exists(), m_def.id

def test_atlas_and_text_assets_exist():
    assert AssetManager().resolve_path("graphics", "latest-atlas.txt").exists()
    assert AssetManager().resolve_path("data", "ultima3.txt").exists()
```

(Use the shared `AssetManager` fixture pattern from existing tests, e.g. `tests/test_assets.py`; `sound_dir` may be taken from `AudioManager(enabled=False).sound_dir` in the same style.)

- [ ] **Step 1: Write `tests/test_asset_load_graph.py` and run it against the current tree.** Run: `pytest tests/test_asset_load_graph.py -v`. Expected: PASS (nothing deleted yet — proves the graph was intact before sweeping).
- [ ] **Step 2: Delete per Files list.** For each file, first `grep -rln <filename> py_exodus tests scripts` and confirm no hits outside this deletion list's documentation; then `git rm`. Verify directories left non-empty where expected: `assets/graphics` retains `latest-atlas.txt`, `ultima-ega.png`, `splash_border.png`, `demon.png`; `assets/fonts` retains `gnuolane.ttf`, `ultima.ttf`; `assets/sound` retains 25 files; `assets/data` retains `ultima3.txt`.
- [ ] **Step 3: Run load-graph test, then full suite.**
  Run: `pytest tests/test_asset_load_graph.py -q && SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests -q`
  Expected: PASS.
- [ ] **Step 4: Smoke-run the dungeon 3D renderer against JSON maps**
  Run: `python scripts/render_dungeon_samples.py` and confirm it exits 0 (it loads perinian + combat maps through the JSON path).
- [ ] **Step 5: Update README asset and parity notes (README.md lines 13 and 132).**
- [ ] **Step 6: Commit**
  ```bash
  git add -A
  git commit -m "chore: delete unused assets; add load-graph test; JSON-only runtime"
  ```
