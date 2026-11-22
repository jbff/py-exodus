# py-exodus

A Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, with **Auto-Combat** (`TAB`) and a **Full Autoplay / Watch Mode** (`F9`) that plays the whole game, from party creation to Exodus.

---

## Reference Implementations & Assets

- **Original game**: [*Ultima III: Exodus*](https://wiki.ultimacodex.com/wiki/Ultima_III:_Exodus) (1983) by Richard Garriott / Origin Systems.
- **Port base: [pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus)**. `py-exodus` started as a port of Paul Antinori's LibGDX Java implementation, which also supplied the sound effects, `.ogg` soundtrack (transcoded from MIDI), XML definitions (`maps.xml`, `vendor.xml`, `creatures.xml`, `weapons.xml`, `armors.xml`) and the world maps/rosters (now JSON).
- **Graphics: the LairWare Mac port's tile sheets** (LairWare Standard by default, any of its 12 sets with `--tiles`), animated the way LairWare animates them: people and monsters swap frames, water and lava scroll, Exodus blinks. Text is set in [Barlow Semi Condensed](https://github.com/jpt/barlow) (SIL Open Font License, `assets/fonts/OFL-Barlow.txt`).
- **Rules authority: the LairWare Mac port** (`UltimaMain.c`, `UltimaMisc.c`, `UltimaSpellCombat.c`, ...). Where the Java port and the classic releases disagree, **LairWare is the correct implementation**. Recent LairWare ports include:
  - **People move in towns and castles** (`MoveMonsters`): wanderers wander, shopkeepers follow, attackers close in and start a fight; in Castle Exodus the defenders come to you.
  - **The dead leave the combat board** and no longer block the living.
  - **Wind** steers ships on Ambrosia as on Sosaria, and is shown there too.
  - **Monster attacks**: hit chance by armor (`RandNum(0, armor+16) < 8`), damage that grows with the target's max HP, and a location bonus (+16 dungeon, +32 town, +48 castles and Ambrosia). Castle Exodus is a real fight now. Dragon fire always hits.
  - **Monsters move and attack diagonally** on Sosaria (the party still can't).
  - **Chest traps** are dodged by DEX, with a big bonus for Thieves; nobody is trap-proof.
  - **UNSPEAKABLE** kills like ZXKUQYB: each monster has a 75% chance to die outright.
  - **Monster variants**: half of Sosaria's wanderers come as a named variant: Brigands and Cutpurses, Goblins and Trolls, Ghouls and Zombies, Golems and Titans, Gargoyles and Manes, Snatches and Bradles, Griffons and Wyverns, Orcuses and Devils. Same stats, new name, their own art.
- **Other classic references**: the Game Boy Color port (`u3gbc`) for moongate routing, ship-battle cannon barrages, meal-crossing starvation/regen and the `QUICKNESS` aura; the NES `MoonGateTbl` for the 8-site moongate table.

---

## Auto-Combat (`TAB`)

Borrowed in concept from the LairWare port: **`TAB`** (or `F2`) during any battle toggles tactical Auto-Combat. Each living member picks healing and cures when needed, offensive magic, or ranged/melee attacks; you can take back control at any moment.

## Full Autoplay / Watch Mode (`F9`)

**`F9`** (or `--autoplay`) hands the game to `AutoPlayController`, which presses real keys through the live UI, so everything it does goes through the same rules you play by. **`[`** / **`]`** slow it down or speed it up. What it does, in order:

- **Party & outfitting**: creates a Thief / Fighter / Cleric / Wizard party, buys starter gear and armor upgrades, keeps food and gold balanced across members.
- **Marks & exotics**: levels for the Mark of Kings, captures a frigate, sails (wind- and pirate-aware) to dig the Exotic weapons and armor, and clears the dungeons for the Marks of Fire, Force and Snake.
- **Gold**: raids Death Gulch, opening chests safely with APPAR UNEM (waiting in place for MP), routing patiently around the moving townspeople, and bribing guards only where they block the way. With the Cleric dead, the Thief opens chests (then the Fighter, the Wizard last) so the party can still earn the gold to resurrect.
- **Ambrosia**: sails into the whirlpool for the four Cards, then makes return trips for shrine stats in plan order (Cleric WIS 35; DEX 40 for all; Cleric WIS 50/70/99, Wizard INT 50/75/99; Fighter and Thief STR). Each trip budgets the gold, the food and the keys it needs (Ambrosia's doors relock between visits), and leaves while it still has a key for the water door.
- **Levels**: grinds every member to 25. Lagging casters open fights with their strongest area spell so they earn the kills.
- **Endgame**: only once every planned stat is bought, yells `EVOCARE` past the Great Earth Serpent, fights through Castle Exodus and inserts the four Cards.

### Status

- **Wins from a fresh game, no cheats.** The last full 100-seed batch (`bbceab3`) won **58**, wiped 39 and hit the step cap 3 times; most wipes are level 1-5 parties early on. A new 100-seed run on the LairWare combat rules (`775884a`, 10 batches of 10) is in progress: 12 won, 7 wiped, 1 step cap after the first 20 seeds. Live runs on 2026-11-22 won with every member at level 25.
- **Open fronts**: early-game wipes (the Cleric usually dies first), resurrecting the dead as a real goal, and a town re-entry loop when no path out exists.

---

## Controls & Hotkeys

- **Movement**: arrow keys or numpad (a ship must first face its heading; in dungeons `DOWN` steps backward). **Enter** / **Space** confirm and advance; **Esc** cancels.
- **`F1`**: Book of Lore, spell books and command reference, from any screen.
- **`TAB`** (or **`F2`**): Auto-Combat on/off in battle.
- **`F9`**: Full Autoplay on/off (**`[`** slower, **`]`** faster).
- **`F10`** *(with `--debug`)*: debug cheat menu.

---

## Installation & Running

Managed with [uv](https://docs.astral.sh/uv/) and a committed `uv.lock` (Python 3.10+, tested through 3.14):

```bash
git clone https://github.com/jbff/py-exodus.git
cd py-exodus
uv sync
uv run exodus          # or: uv run py-exodus
```

Without `uv`:

```bash
pip install pygame-ce sounddevice soundfile
python3 -m py_exodus
```

### Command-line options

| Flag | Effect |
|---|---|
| `--autoplay` | Start in Full Autoplay (Watch Mode); `F9` still toggles it. |
| `--trace` | Record the run to `traces/trace_<time>.jsonl.gz` (written when the game exits). |
| `--tiles NAME` | Draw with one of LairWare's tile sets (default `standard`): `standard`, `apple2`, `apple2-tv`, `apple2-mono`, `c64`, `mac-bw`, `nes`, `cga`, `ega`, `mcga`, `vga`, `ultima5` (`--tiles list` prints them). |
| `--debug` | Enable the debug cheat harness (`F10`). |

Live play runs on wall-clock time and the `[` / `]` speed keys change it, so a live run can't be replayed exactly. There is no `--seed` flag.

### Headless batches and traces

Reproducible autoplay runs, one trace per seed, no window:

```bash
uv run python -m py_exodus.autoplay.batch --seeds 0-99 --workers 2 --out-dir traces/batch
```

Each seed prints `WON@<steps>`, `WIPED@<steps>` or `STEP_CAP@<steps>`. A trace row records position, goal, party state, the key pressed and **`why`**: the autoplay functions and lines that chose it. In towns it also lists the people within 4 tiles. So a loop in a trace names the code that caused it.

### Tests

```bash
uv run python -m pytest
```

About **1,350 tests** covering mechanics, LairWare/Java/GBC parity, vendors, dungeons, combat, rendering and autoplay regressions (most autoplay fixes come with a test that fails on the old code).

---

## Deliberate Deviations

1. **Wireframe dungeons**: a classic first-person wireframe view instead of Java's 3D pipeline (mechanics match).
2. **Fixed spell letters (A–P)**: spell menus keep the original A–P slots; an invalid cast refuses with `"Not Here!"` or the MP message.
3. **Classic GBC/LairWare rulings**: slow/fast moongate table, party-wide ship cannon barrage, meal-crossing `-5 HP` starvation / `+1 HP` regen, `QUICKNESS` stop-time.
4. **Quality of life**: no quick-start party; `Q` saves only on the Sosaria overworld; `APPAR UNEM` opens the chest underfoot without a direction prompt; saves and rosters are JSON only.
5. **Wind display**: reads `Wind NORTH` etc. in words, without arrow glyphs.

## Known Open Items

1. **Audio**: the poison/fire field sound cues (`Sound.POISON_EFFECT`, `Sound.FIREFIELD`) aren't wired yet.
2. **Input**: keyboard only.
3. **`H` (Hand Equipment)**: hands weapons and armor only, not food (autoplay evens out food when it buys).
4. **Combat regen**: MP regen and meal-crossing `+1 HP` don't tick during combat rounds.
5. **Autoplay**: early-game wipes are the main loss; see Status above.

---

## Utilities

- `scripts/render_maps.py`: renders the JSON maps to top-down PNGs in `maps_rendered/`.
- `scripts/autoplay_atlas.py`: summarizes autoplay traces.

---

## License

Educational, preservation and non-commercial archival use. Original *Ultima III: Exodus* content, design and assets remain copyright © their respective owners and Richard Garriott / Origin Systems.
