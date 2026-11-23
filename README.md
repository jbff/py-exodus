# py-exodus

A Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, with **Auto-Combat** (`TAB`) and a **Full Autoplay / Watch Mode** (`F9`) that plays the whole game, from party creation to Exodus.

---

## Reference Implementations & Assets

- **Original game**: [*Ultima III: Exodus*](https://wiki.ultimacodex.com/wiki/Ultima_III:_Exodus) (1983) by Richard Garriott / Origin Systems.
- **Port base: [pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus)**. `py-exodus` started as a port of Paul Antinori's LibGDX Java implementation, which also supplied the sound effects, `.ogg` soundtrack (transcoded from MIDI), XML definitions (`maps.xml`, `vendor.xml`, `creatures.xml`, `weapons.xml`, `armors.xml`) and the world maps/rosters (now JSON).
- **Graphics: the LairWare Mac port's tile sheets** (its PC EGA set by default; LairWare's own, Apple II, C64, MCGA and Ultima V sets with `--tiles`), animated the way LairWare animates them: people and monsters swap frames, water and lava scroll, Exodus blinks. Text is set in [Barlow Semi Condensed](https://github.com/jpt/barlow) (SIL Open Font License, `assets/fonts/OFL-Barlow.txt`).
- **Rules authority: the LairWare Mac port** (`UltimaMain.c`, `UltimaMisc.c`, `UltimaSpellCombat.c`, ...). Where the Java port and the classic releases disagree, **LairWare is the correct implementation**. Recent LairWare ports include:
  - **People move in towns and castles** (`MoveMonsters`): wanderers wander, shopkeepers follow, attackers close in and start a fight; in Castle Exodus the defenders come to you.
  - **The dead leave the combat board** and no longer block the living.
  - **Wind** steers ships on Ambrosia as on Sosaria, and is shown there too.
  - **Monster attacks**: hit chance by armor (`RandNum(0, armor+16) < 8`), damage that grows with the target's max HP, and a location bonus (+16 dungeon, +32 town, +48 castles and Ambrosia). Castle Exodus is a real fight now. Dragon fire always hits.
  - **Monsters move and attack diagonally** on Sosaria (the party still can't).
  - **Chest traps** are dodged by DEX, with a big bonus for Thieves; nobody is trap-proof.
  - **UNSPEAKABLE** kills like ZXKUQYB: each monster has a 75% chance to die outright.
  - **Shrines**: no shrine screen. Enter on an Ambrosia shrine, name who enters, offer 0-9 hundred gold; LairWare's shrine picture covers the map meanwhile. The stat goes up by the offering, capped by race (the cap lifts after Exodus, never past 99).
  - **Opening**: LairWare's intro (EXODUS and the Ultima III logo dissolving in, "by Lord British" written stroke by stroke, the duel), then the View, a scripted scene of Sosaria cycling the songs, until a key. Any key skips the intro; the main menu has "Return to the View". Never in headless or autoplay runs.
  - **Party panel**: a card per member (race, class, sex and level in words; HP and MP bars; food, gold, stats, experience, weapon and armor; a colored edge and tag when poisoned, dead or ashes), then party supplies, quest chips for marks, cards and exotics, and location, turn, autoplay (with its goal) and autocombat.
  - **Ship cannons** (`F`, aboard ship): any of the four directions, up to 3 tiles, wrapping round the map; the first monster in the path is destroyed half the time (a pirate a quarter). No heading, no broadsides-only rule.
  - **Pirates and dragons fire back**: each turn, half the time, one within 3 tiles along a row, column or diagonal hits the whole party for 8-127 HP each; mountains and walls stop the shot. Ships have no hull and cannot sink.
  - **Monster variants**: half of Sosaria's wanderers come as a named variant: Brigands and Cutpurses, Goblins and Trolls, Ghouls and Zombies, Golems and Titans, Gargoyles and Manes, Snatches and Bradles, Griffons and Wyverns, Orcuses and Devils. Same stats, new name, their own art.
- **Other classic references**: the Game Boy Color port (`u3gbc`) for moongate routing, ship-battle cannon barrages, meal-crossing starvation/regen and the `QUICKNESS` aura; the NES `MoonGateTbl` for the 8-site moongate table.

---

## Auto-Combat (`TAB`)

Borrowed in concept from the LairWare port: **`TAB`** (or `F2`) during any battle toggles tactical Auto-Combat. Each living member picks healing and cures when needed, offensive magic, or ranged/melee attacks; you can take back control at any moment.

## Full Autoplay / Watch Mode (`F9`)

**`F9`** (or `--autoplay`) hands the game to `AutoPlayController`, which presses real keys through the live UI, so everything it does goes through the same rules you play by. **`[`** / **`]`** slow it down or speed it up. What it does, in order:

- **Tested party only**: autoplay has been tested and tuned with one party alone, the one `scripts/reset_new_game.py` writes to the roster and the headless batches build: SHADOW, Elf Thief (STR 15, DEX 25, INT 5, WIS 5); GRUMM, Dwarf Fighter (25/15/5/5); SERENA, Bobbit Cleric (15/5/5/25); ZIRCON, Fuzzy Wizard (15/5/25/5), 50 points each as LairWare allows. Batches before 2026-11-22 (up to `775884a`) gave the same four 60 points each. Started on an empty roster, autoplay creates this same party. How it fares with any other party is untested.
- **Party & outfitting**: creates a Thief / Fighter / Cleric / Wizard party, buys starter gear and armor upgrades, keeps food and gold balanced across members.
- **Marks & exotics**: levels for the Mark of Kings, captures a frigate, sails (wind- and pirate-aware) to dig the Exotic weapons and armor, and clears the dungeons for the Marks of Fire, Force and Snake. It buys gems and peers one on every dungeon level it visits, which is how it can know exactly where to go. That is a conceit, and a small one: the rest of autoplay already knows plenty a new player wouldn't. In dungeons it steps around gremlins where it can (each one eats 100 food from a member), opens chests it walks over only the safe way (APPAR UNEM, or the Thief when no caster lives), and heads for the exit the moment anyone's food reaches 0.
- **Gold**: raids Death Gulch (with 4 keys for its doors, bought first if short, and 400 gold for the guards' bribes, and only with the Cleric's MP full: it waits at the gate, where MP returns four times faster than inside), opening chests safely with APPAR UNEM (waiting in place for MP), routing patiently around the moving townspeople, and bribing guards only where they block the way. With the Cleric dead, the Thief opens chests (then the Fighter, the Wizard last) so the party can still earn the gold to resurrect.
- **Ambrosia**: sails into the whirlpool for the four Cards, then makes return trips for shrine stats in plan order (Cleric WIS to its race maximum first, for ALCORT and the biggest APPAR UNEM pool; DEX 40 for all; Wizard INT 50/75/99; Fighter and Thief STR). A return trip raids only for what the remaining stats cost (at most about 8,500), and buys only the entry food, so stocking up doesn't send it back to raid. Each trip, cards or stats, budgets the gold, the food and 8 keys (Ambrosia's doors relock between visits, and the Moons card alone is behind three), and leaves while it still has a key for the water door.
- **Levels**: grinds every member to 25, starting on a loop near Britain's healer and Lord British and widening to the whole continent when nothing shows up for 150 moves. A Cleric below level 5 steps away from melee at half HP. Below level 8 the grind doesn't go after dragons (a chased party still fights them); from level 8, at full strength, it walks up to a dragon instead of dodging its fire. The Mark of Kings (needed to pass level 5) waits for three of the four at level 5, not all four. Lagging casters open fights with their strongest area spell so they earn the kills. Chests dropped on the surface are picked up straight away, errands included, unless that would court disaster: a weak party with no safe opener, a chest inside a firing lane, a poisoned member near death on the way to the cure, or a badly hurt party with monsters closing in. Hurt, it takes only chests within four steps; healthy and grinding, it fetches any it can reach.
- **The dead first**: with a member dead, food waits (until someone is down to 40) so the gold goes to the resurrection.
- **Poison**: a Cleric or Druid who can reach ALCORT's 35 MP cures on the spot once the MP is back, as long as the poisoned can afford the wait; otherwise a healer (100 gold).
- **Endgame**: only once every planned stat is bought, yells `EVOCARE` past the Great Earth Serpent, fights through Castle Exodus and inserts the four Cards.

### Status

- **Wins from a fresh game, no cheats.** The latest 100-seed batch (`775884a`, LairWare combat rules, the final castle fighting back) won **58**, wiped 37 and hit the step cap 5 times, matching the easier-rules batch before it (`bbceab3`: 58 won, 39 wiped, 3 step caps). 34 of the 37 wipes are parties at level 10 or below. Live runs on 2026-11-22 won with every member at level 25.
- **Open fronts**: early-game wipes (being measured by the next 100-seed batch).

---

## Controls & Hotkeys

- **Movement**: arrow keys or numpad (ships sail straight off in any direction the wind allows; in dungeons `DOWN` steps backward). **Enter** / **Space** confirm and advance; **Esc** cancels.
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
| `--tiles NAME` | Tile set, from LairWare's sheets: `ega` (default), `lairware`, `apple2`, `c64`, `mcga`, `ultima5` (`--tiles list` prints them). |
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

1. **Wireframe dungeons**: a classic first-person wireframe view instead of Java's 3D pipeline (mechanics match). The wireframe makes depth hard to judge accurately, so the dungeon map overlay stays on by default (`P` hides it), even though the original has no such map.
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

py-exodus's own code is [MIT](LICENSE). Material from elsewhere keeps its own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): LairWare's port (MIT), the Barlow font (OFL), and assets still derived from gdx-exodus, which publishes no license and which are being replaced with LairWare-derived equivalents. *Ultima III: Exodus* itself remains copyright © Richard Garriott / Origin Systems; this is an unofficial, non-commercial fan port.
