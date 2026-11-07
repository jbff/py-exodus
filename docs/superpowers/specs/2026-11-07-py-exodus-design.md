# Design Document: py-exodus (Ultima III: Exodus Reimplementation in Python)

**Date**: 2026-11-07  
**Status**: Ready for Approval  
**Target Platform**: Linux (Python 3.10+ / `pygame-ce`)

---

## 1. Intent and Why

*Ultima III: Exodus* (1983) is a foundational tactical party-based RPG. The existing Java reimplementation ([gdx-exodus](file:///sto/src/gdx-exodus)) is ~18,200 lines of complex LibGDX code with multiple layers of abstractions, boilerplate JAXB XML adapters, and platform-specific bugs (such as Linux filesystem case-sensitivity crashes in combat). 

The goal of this project (**py-exodus**) is to produce a clean, simple, robust, and fully playable reimplementation of Ultima III in Python using `pygame-ce`. It leverages the existing cleaned asset package (original binary maps/data, XML rule definitions, EGA sprite sheets, and music) while replacing the bulky Java engine with an elegant, idiomatic, and maintainable Python codebase estimated at ~2,500–3,500 lines.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Full Gameplay Parity with Ultima III / gdx-exodus**:
  - Party creation and management (4-character party, 11 classes, 5 races, stats, inventory).
  - Overworld (Sosaria, 64×64), Ambrosia, and Castle/Town navigation (13 towns/castles).
  - Turn-based tactical grid combat (11×11 conflict arenas from `CNFLCT_*.ULT`) with line-of-sight, ranged weapons, monster AI, and spellcasting.
  - 8 Dungeons across 8 levels (16×16 per level) with marks, fountains, traps, and chests.
  - Magic system: Clerical (Prayer) and Wizard (Sorcery) spells.
  - Moon gates, whirlpools, wind direction, pirate frigate ship sailing and broadside cannon fire.
  - NPC dialogue, vendors (weapons, armor, food, tavern, healers, oracle, horse).
  - End-game Exodus fortress mechanics and completion sequence.
- **Direct Asset Reuse**: Read directly from the existing `assets/` directory (XML tables, EGA sprite sheets, binary `.ult` files, sound effects, and music).
- **Native Linux Experience**: Effortless installation and run on standard Linux (`pip install pygame-ce && python -m py_exodus`).
- **Flawless Turn-Based Combat**: Resolve the combat crashes and input state bugs present in the Java version.
- **Classic Keyboard-Driven Text Interface**: An authentic, responsive keyboard/text prompt stream inside the scrolling text log for dialogue, vendor interactions, and commands.

### Non-Goals
- **3D Textured Wall Meshes**: We are not building or maintaining an OpenGL 3D perspective pipeline with texture-mapped stone wall assets.
- **Floating GUI Windows**: We are not building a desktop-style window/button widget toolkit; interaction is streamlined through the HUD text prompt stream.
- **Multiplayer / Networking**: Purely single-player local RPG.
- **Save Game Compatibility with 1983 Floppy Disks**: JSON-based human-readable modern save games (though reading the `party.ult` / `roster.ult` format for initial rosters is supported).

### Anti-Goals
- **Over-Engineered Architecture**: No heavy external frameworks, complex ECS (Entity-Component-System) libraries, or redundant abstraction layers. A clear state machine and data-driven game loop is strictly preferred.
- **Silent Failures**: Avoid Java-style silent catch blocks that mask missing assets or uninitialized state.

---

## 3. Constraints

- **Language**: Python 3.10+ (using type hints and standard library features).
- **Core Dependency**: `pygame-ce` (>= 2.5.0) exclusively for windowing, 2D blitting, audio playback, and keyboard events.
- **Standard Library Modules**:
  - `struct`: For decoding binary map files (`.ult`, `CNFLCT_*.ULT`, `shrine.con`).
  - `xml.etree.ElementTree`: For parsing game rules and entity tables (`maps.xml`, `creatures.xml`, etc.).
  - `json`: For save game serialization and configuration.
  - `pathlib`: Case-insensitive and cross-platform asset path resolution.

---

## 4. Approaches Considered & Trade-offs

### Approach 1: Data-Driven Retro Engine with Wireframe Dungeons & Keyboard Stream (Selected)
- **Architecture**: A clean finite state machine (`StartScreen`, `OverworldScreen`, `TownScreen`, `CombatScreen`, `DungeonScreen`, `RosterScreen`, `ShrineScreen`, `BookScreen`, `FinalScreen`). 2D tiled rendering for overworld, towns, and tactical combat. Dungeons rendered using classic authentic Ultima III stepped wireframe/flat-shaded corridor projection via `pygame.draw.lines` and `pygame.draw.polygon`. All interactions driven via the text prompt stream.
- **Why Chosen**: Maximum fidelity to classic Ultima III, lowest codebase complexity (~2,500–3,500 LOC), completely native to Pygame with zero 3D dependencies, and trivial to debug and test.

### Approach 2: Textured 3D Hybrid Port with GUI Modals (Rejected)
- **Architecture**: Replicates the Java LibGDX version’s textured stone dungeon walls and floating GUI modal windows.
- **Why Rejected**: Adds substantial 3D math and requires writing a custom Pygame GUI widget toolkit, nearly doubling the codebase size without improving gameplay.

---

## 5. Architectural & System Design

```
py-exodus/
├── py_exodus/
│   ├── __init__.py
│   ├── __main__.py          # Entrypoint & main game loop
│   ├── constants.py         # Directions, Spells, Stats, Weapons, Armors, TileAttribs
│   ├── assets.py            # Loads tilesets, sprite sheets, XMLs, audio, maps
│   ├── state_machine.py     # Base Screen and state switcher
│   ├── world/
│   │   ├── map.py           # Map data structures (World, City, Combat, Dungeon)
│   │   ├── loader.py        # Binary .ult and XML map loading logic
│   │   ├── dungeon.py       # 8-level wireframe dungeon renderer & corridor logic
│   │   └── field_of_view.py # Shadowcasting / line of sight calculations
│   ├── entities/
│   │   ├── party.py         # Party & PartyMember data, leveling, stats, food
│   │   ├── roster.py        # Character creation & roster management
│   │   └── creature.py      # Monsters, guards, NPCs, movement & AI
│   ├── combat/
│   │   ├── arena.py         # 11x11 combat grid, turns, action queues
│   │   ├── resolver.py      # Attack calculation, ranged weapons, damage formulas
│   │   └── magic.py         # Spellcasting formulas and effects (Prayer & Sorcery)
│   ├── ui/
│   │   ├── renderer.py      # EGA viewport blitter (scaled nearest-neighbor)
│   │   ├── text_log.py      # Scrolling HUD message log & interactive command prompt
│   │   └── stats_panel.py   # Party status sidebar (HP, MP, Food, Status)
│   ├── audio.py             # Music & sound effect playback (OGG streaming)
│   └── save_system.py       # JSON save/load with 24-object dynamic overworld delta
└── assets/                  # Existing assets referenced from gdx-exodus
```

### 5.1 Asset & Data Ingestion
1. **Tileset & Atlases**:
   - `latest-atlas.txt` and `ultima-ega.png`: Slice 16×16 tile surfaces into a cached dictionary `tiles[name][frame]`.
2. **Binary Maps**:
   - Sosaria (`sosaria.ult`): 64×64 bytes. Tile indices are `byte // 4`.
   - Cities (`*.ult`): 64×64 bytes.
   - Conflict Maps (`CNFLCT_*.ULT`): 176 bytes (0x00–0x78: 11×11 tiles; 0x80–0x87: monster start X; 0x88–0x8F: monster start Y; 0xA0–0xA3: player start X; 0xA4–0xA7: player start Y).
   - Dungeons (`*.ult`): 16×16 × 8 levels (4096 bytes per dungeon).
   - Ambrosia Shrines (`shrine.con`): 192 bytes (11×11 tiles).
3. **XML Data Models**:
   - Ingested on startup into lightweight dataclasses (`CreatureDef`, `WeaponDef`, `ArmorDef`, `VendorDef`).
4. **Audio Subsystem**:
   - Sound effects via `pygame.mixer.Sound(path)` (`.ogg` files).
   - Background music: The 10 `.mid` files will be transcoded to `.ogg` upfront so they stream seamlessly via `pygame.mixer.music` without external SoundFont or OS package dependencies.

### 5.2 UI & Keyboard Stream
- Screen layout:
  - Top-Left: Viewport (11×11 tiles or 3D wireframe dungeon view).
  - Right: Party Status Sidebar (Character names, HP, MP, Food, Status, active transport).
  - Bottom: Scrolling HUD Text Log and interactive input prompt (`Talk > Direction? > Vendor > Buy what?`).
- Keyboard input:
  - Single-key commands: `(A)`ttack, `(C)`ast, `(T)`alk, `(U)`nlock, `(S)`earch, `(O)`ther, `(G)`et chest, `(B)`ribe, `(P)`eer gem, `(N)`egate time, `(H)`orse/board, `(K)`limb/descend, `(Z)`tats, Space (Pass).
  - Prompt states capture text strings (e.g. typing a name, yell phrase, or gold amount) without popup windows.

### 5.3 Combat System (Resolving Java Bugs)
- **Turn Sequence**:
  1. Each living party member takes an action in order: Move, Attack (direction / ranged), Cast Spell, Use Item, or Pass.
  2. Each monster on the combat grid takes an action: Pathfind towards closest party member, perform melee attack, cast spell, or fire missile.
  3. Poison/status ticks and end-of-round check.
- **Robust Map Resolution**: Case-insensitive and normalized loading of `CNFLCT_*.ULT` arenas ensures 100% reliable initialization of combat maps.

### 5.4 Dungeon System
- Dungeons consist of 16×16 grids across 8 floors (Z-levels 0 to 7).
- A 3D wireframe camera projects walls up to 4 steps ahead using classic 2.5D perspective vector line drawing.
- Fixtures (ladders up/down, chests, fountains, doors) are rendered with classic vector graphics.
- Monster encounters in dungeons trigger immediate transitions to the tactical 11×11 combat screen.

### 5.5 World & Save Game Persistence
- Saves are serialized as clean JSON (`savegame.json`).
- Persists:
  - Party state (roster attributes, HP, MP, equipment, food, gold, torces, gems, keys, marks, cards).
  - Current location, map ID, coordinates, and active transport (Foot, Horse, Ship).
  - Dynamic Overworld Delta: Up to 24 mutable objects on Sosaria (e.g., parked frigate ships, chests), matching `SaveGame.java`.
- Town and dungeon maps reset upon exit, as in classic Ultima III.

---

## 6. What's Left to the Builder

The builder has full discretion over:
1. **Window Scaling**: Standard 960×600 (3× integer scaling from 320×200 base) with nearest-neighbor interpolation to preserve crisp EGA pixel art.
2. **Animation Timing**: Tile frame oscillation between 200ms–350ms per frame.
3. **Internal Test Suite**: Unit tests for binary decoders, map loaders, combat roll calculations, and spell mechanics.
4. **Packaging**: Standard `pyproject.toml` configuration for `pip install -e .`.
