# py-exodus

A Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus* (1983), by Richard Garriott and Origin Systems. It plays the whole game, from forming a party to the fall of Exodus. It adds two helpers: **Auto-Combat**, which fights battles for you, and **Full Autoplay**, a watch mode that plays the entire game on its own.

### Lineage

- **[pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus):** py-exodus began as a port of Paul Antinori's LibGDX version in Java. It supplied the sound effects, the soundtrack, the XML definitions, and the maps and rosters (now JSON).
- **LairWare's Mac port of Ultima III (MIT):** the rules authority. The game logic has since been brought in line with it, and it supplies the tile sheets, some sounds and the intro data.
- **Honourable mentions:** the Game Boy Color port and the NES version were consulted early on, for the moongates and ship combat. Little of it remains: those rules now follow LairWare.

---

## Features

- **The complete game:** Sosaria and Ambrosia, the towns and castles, the dungeons, the moongates, ships and the whirlpool, the Marks, the Exotics, the Cards, and Castle Exodus.
- **LairWare's rules.** The game logic follows LairWare's Mac port: monster movement and attacks, combat maths, spells, shops, wind, time and food, dungeon fixtures, autosaves and more. Where the Java port or the classic releases disagree with it, LairWare wins, apart from a few deliberate changes (listed below).
- **Classic graphics:** LairWare's tile sheets, with the PC EGA set by default. The LairWare, Apple II, C64, MCGA and Ultima V sets are also available. Tiles animate as they do in LairWare.
- **Its own look:** its own title art and intro, a party panel with cards for each member, and a quest tracker. The look and UI are deliberately not LairWare's.
- **Auto-Combat (`TAB`):** each living member heals, cures, casts or attacks as LairWare's auto-combat would. You can take back control at any moment.
- **Full Autoplay (`F9`):** plays the whole game through the real UI, pressing the same keys you would.

## Installation & running

Managed with [uv](https://docs.astral.sh/uv/) and a committed `uv.lock`. Needs Python 3.10 or later, tested through 3.14.

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
| `--autoplay` | Start in Full Autoplay. `F9` still toggles it. |
| `--trace` | Record the run to `traces/trace_<time>.jsonl.gz`, written when the game exits. |
| `--tiles NAME` | Tile set: `ega` (default), `lairware`, `apple2`, `c64`, `mcga` or `ultima5`. `--tiles list` prints them. |
| `--debug` | Enable the debug cheat menu (`F10`). |

## Controls

- **Movement:** arrow keys or the numpad. In dungeons, `DOWN` steps backward.
- **Commands:** the classic single-letter commands, as in LairWare. Examples are `A`ttack, `B`oard, `C`ast, `E`nter, `G`et, `H`and, `I`gnite, `J`oin gold, `K`limb, `L`ook, `N`egate time, `O`ther, `P`eer, `Q`uit & save, `R`eady, `S`teal, `T`ransact, `U`nlock, `W`ear, `X`-it, `Y`ell and `Z`tats.
- **Confirming and cancelling:** `Enter` or `Space` confirms, and `Esc` cancels.
- **`F1`:** the Book of Lore, the spell books and the command reference, from any screen.
- **`F3`:** a quick-reference card of the letter commands, with where each one works (Sosaria, towns, dungeons, combat). The game is paused while it is open; any key closes it.
- **`F4`:** quick-reference cards of the Wizard and Cleric spells, with cost, where they work and what they do. `Tab` switches between the two; `F3` shows the commands.
- **`TAB`** (or `F2`): Auto-Combat on or off during a battle.
- **`F9`:** Full Autoplay on or off. `[` slows it down and `]` speeds it up.
- **`F10`:** the debug menu, with `--debug` only.

Saving follows LairWare's classic AutoSave, with one save slot. The game saves when you enter or leave a town, castle or dungeon, on the whirlpool trip, and when a member dies. `Q` also saves, on Sosaria only. Nothing is saved while autoplay is on, or after the ending.

## Autoplay

**Auto-Combat** follows LairWare's rules:
- casters cast Mittar along rows and columns;
- a member under 50 HP steps away from adjacent monsters;
- healers cast Sanctu on anyone under 75 HP;
- bows and slings shoot the nearest monster in line.

**Full Autoplay** runs a goal planner. It works through these steps:
1. outfits the party;
2. earns gold by raiding Death Gulch;
3. levels the party, including Lord British's level-ups;
4. captures a frigate and digs up the Exotics;
5. clears the dungeons for the Marks;
6. sails through the whirlpool to Ambrosia for the Cards and shrine stats;
7. passes the Great Earth Serpent and wins in Castle Exodus.

It only knows what a seasoned player would know, such as the dungeon layouts and where the treasure is. When the four Cards are in, it switches itself off and leaves the ending to you.

- **Tested party:** autoplay is tuned and tested with one party: a Thief, a Fighter, a Cleric and a Wizard. `scripts/reset_new_game.py` writes this party to the roster. Autoplay is meant to run without crashing or looping with any party, but other parties are untested.
- **Results:** 77 of 100 headless runs won from a fresh game, with no cheats. The 100 seeds ran as ten batches of ten while fixes landed (November 2026). Most of the losses were early-game wipes at levels 1–5.

### Headless batches and traces

```bash
uv run python -m py_exodus.autoplay.batch --seeds 0-99 --workers 2 --out-dir traces/batch
```

- **Output:** each seed prints `WON@<steps>`, `WIPED@<steps>` or `STEP_CAP@<steps>`, and writes a trace.
- **Trace rows:** each row records the position, the game turn, the goal, the party's state, the key pressed, and `why`, which names the autoplay code that chose that key. A loop or stall in a trace therefore points at the code that caused it.
- **Utilities:**
  - `scripts/autoplay_atlas.py` summarizes traces.
  - `scripts/render_maps.py` renders the JSON maps to PNGs in `maps_rendered/`.

### Tests

```bash
uv run python -m pytest
```

There are **2,183 tests**. They cover the mechanics, parity with LairWare, Java and the Game Boy Color port, the shops, the dungeons, combat, rendering and autoplay. Most autoplay fixes come with a test that fails on the old code.

---

## Deliberate deviations from LairWare

The rest of the rules follow LairWare. Every rule decision, with its LairWare source lines, is recorded in the parity ledger, [`docs/superpowers/plans/lw-parity-ledger.md`](docs/superpowers/plans/lw-parity-ledger.md); its "User rulings" section lists the deliberate changes.

1. **The game ends when Exodus falls,** as in the 8-bit originals. LairWare's play after the win is not ported.
2. **No starter party:** the roster starts empty. The Magical Orbs are gone.
3. **Dungeons:** they are drawn as a first-person wireframe, with a map overlay on by default (`P` hides it).
4. **Spells:** spell menus keep fixed A–P letters.
5. **Druids:** they regain 2 MP per tick, as the Book of Lore says.
6. **LairWare bugs not copied:**
   - a dungeon trap is avoided by a *good* DEX roll;
   - a force field needs the Mark of Force on every living member;
   - a cancelled Fal Divi charges nothing more;
   - the red-hot rod doesn't mark the dead.
7. **Quality of life:**
   - `Q` saves only on Sosaria;
   - `APPAR UNEM` opens the chest underfoot without asking for a direction;
   - saves and rosters are JSON;
   - a shopkeeper asks each question once;
   - the wind is named in words.

## Planned (look & feel)

- **The victory ending:** LairWare-style colour flashes, an "EXODUS VANQUISHED" page with the move count, then the epilogue in serif lettering. The design is chosen.
- **A new dungeon view:** "Stone" style, with solid torchlit walls, fog with distance, and close-up pictures for fountains and the red-hot rod. The map overlay will then be off by default. The design is chosen.
- **A Ztats window** over the map. The design is chosen.
- **The Book of Lore** reformatted, so it is no longer about 128 pages in a giant font.

## Possible loose ends

These are small things noted in development and left for now. Some of them may already be moot.

**Autoplay**
- **The Death Gulch strip:** a party stranded there with no ship and fewer than 2 keys can only wait for a pirate to capture. It can starve waiting.
- **A stuck pirate:** a pirate pinned somewhere the party can't reach may still keep a capture hunt waiting on the coast.
- **The Cleric falls behind in level:** in most combat losses the Cleric is the lowest-level member and dies first. Changing this would mean changing autoplay tactics.
- **Odd parties:** without a Cleric, Thief or Wizard, some routines use rough fallbacks.
- **Batch seeds** don't always replay exactly the same game. One replay went a different way at a sell choice.
- **Small autoplay edge cases:**
  - joining gold just before a bribe costs a turn;
  - the "not enough room" check reads 25 lines of message history;
  - the Grey exit walk ignores the roaming thief's reach after a second pass.

**Rules**
- **Missed turns:** LairWare runs a turn on entering a new map, and after a fight or an entry that a command started. The port skips both.
- **The town exit step** ages the party at town pace. LairWare uses Sosaria's pace, so an Exodus fireball is possible on that step.
- **Moongate sites:** LairWare wipes objects on the eight gate sites every Sosaria turn, and the port doesn't.
- **Stopped time:** the overworld countdown may be off by one turn, and some commands skip it.
- **Food:** the food clock resets and loses a fraction of a ration, so rations last about 10% longer than in LairWare.
- **Hand (`H`)** accepts a negative amount.
- **The oracle and the pub:** an empty or non-digit answer to the oracle counts as an offering of 1. An empty answer in the pub pays 7 gold; LairWare treats it as 0 and throws you out.
- **Dor Acron and Rec Du:** refused on a dungeon's lowest level, they print no "Failed".
- **Yell in a dungeon** doesn't check for a living member.
- **Join gold (`J`)** says nothing for an invalid member.
- **`Z` on Sosaria and in towns** ends the turn before the stats close. LairWare ends it after.
- **The roster:** a free roster slot can collide with a party member's slot, which is rare. Disperse hides save errors.

**Housekeeping**
- **The parity ledger's close-out:** a few rows still need their final status, and some cites need correcting.
- **Untested cases:**
  - a member holding a Card dies inside Castle Exodus;
  - fights on horseback in ship-battle code.
- **Stale comments and tests:**
  - old two-whirlpool notes;
  - a camouflage test that asserts nothing;
  - outdated test names and cites.
- **Audio:** the poison and fire field sound cues aren't wired up.
- **The `.venv` torch and triton packages** were removed by a `uv sync`. Only the `neural-net` branch needs them; reinstall them there.

---

## Credits

- **Original game:** [*Ultima III: Exodus*](https://wiki.ultimacodex.com/wiki/Ultima_III:_Exodus) (1983) by Richard Garriott and Origin Systems.
- **Ports:** gdx-exodus and LairWare's port, as described under Lineage at the top.
- **Font:** [Barlow Semi Condensed](https://github.com/jpt/barlow) (SIL Open Font License).
- **Project history:** design notes, plans and the parity ledger are in [`docs/`](docs/). The git history holds the reasoning behind each change. Earlier versions of this README describe every ported rule in detail.

## License

py-exodus's own code is [MIT](LICENSE). Material from elsewhere keeps its own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). That covers LairWare's port (MIT), the Barlow font (OFL), and the assets still derived from gdx-exodus. gdx-exodus publishes no license, and those assets are being replaced with LairWare-derived ones. *Ultima III: Exodus* itself remains copyright © Richard Garriott / Origin Systems. This is an unofficial, non-commercial fan port.
