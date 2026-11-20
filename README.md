# py-exodus

A Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, featuring **Auto-Combat** (`TAB`) and an experimental autonomous **Full Autoplay / Watch Mode** (`F9`).

---

## Reference Implementations & Assets

- **Original Game**: [*Ultima III: Exodus*](https://wiki.ultimacodex.com/wiki/Ultima_III:_Exodus) (1983) by Richard Garriott / Origin Systems.
- **Primary Logic, Maps & Audio/Graphics Source — [pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus)**:
  `py-exodus` was ported from Paul Antinori's LibGDX Java implementation, which also supplied the tile atlases, sound effects, `.ogg` soundtrack (transcoded from MIDI), XML definitions (`maps.xml`, `vendor.xml`, `creatures.xml`, `weapons.xml`, `armors.xml`), and JSON world maps/rosters.
- **Classic Port References (GBC / LairWare / NES)**:
  Where the Java port invented rules or differed from classic releases, several mechanics were intentionally aligned with:
  - **Game Boy Color (`u3gbc`: `funcs5.c`, `battle3.c`, `menucmd2.c`)**: dual-moon slow/fast moongate routing, ship-battle party-wide cannonfire barrage, meal-crossing starvation (`-5 HP`) and fed HP regen (`+1 HP`), `QUICKNESS` stop-time aura gating, underground meal cadence, and 9999 pooled gold cap.
  - **LairWare Mac port (`UltimaMisc.c`, `UltimaMain.c`)**: inspiration for **Auto-Combat**, plus cross-checking starvation/regen, moon cadence, and spell/combat edge cases.
  - **NES (`MoonGateTbl`)**: cross-reference for the 8-site slow/fast moongate table.

---

## What Makes `py-exodus` Special

### Auto-Combat (`TAB`)
Borrowed in concept from the LairWare Mac port, pressing **`TAB`** during any battle toggles tactical **Auto-Combat** on or off. Each living party member automatically selects healing/cure spells when needed, offensive magic or ranged/melee attacks, and chest-safe positioning—letting you breeze through routine encounters or step back into manual control at any moment.

### Full Autoplay / Watch Mode (`F9`)
Pressing **`F9`** (with **`[`** / **`]`** to adjust step speed) hands the entire game over to `AutoPlayController`, which drives real keyboard inputs through the live UI (`StateMachine`, `OverworldScreen`, `TownScreen`, `DungeonScreen`, `CombatScreen`, `ShrineScreen`) from party creation all the way toward Exodus:
- **Party setup & outfitting**: creates a balanced 4-member party (Thief / Fighter / Cleric / Wizard), buys starter gear and `Chain`/`Plate` armor upgrades in Britain/Dawn, and keeps per-member food and gold reserves balanced.
- **Progression & navigation**: levels to 5+ for the Mark of Kings, captures a frigate, uses wind-hold / sea-monster-avoiding BFS sailing to dig Exotic Weapons & Armor, clears remaining dungeon Marks (`Fire`, `Force`, `Snake`), raids Death Gulch for gold (`>= 4500g` target via locked doors & chokepoint guard bribing), sails Whirlpools into Ambrosia for all 4 Cards and Shrine stat upgrades (prioritizing Cleric `Wis`, Wizard `Int`, Fighter `Str`, Thief `Dex`), levels to 25+, yells `EVOCARE` to pass the Great Earth Serpent, clears Exodus Castle defenders, and inserts all 4 Cards to win.

> **Status (`neural-net` branch)**:
> - **Pre-NN Symbolic Baseline (`master` / `pre-nn` tag)**: End-to-end A-to-Z victory from a fresh game both under `--debug` `NOHURT` (`seed=417 WON@142,845`, `seed=418 WON@114,926`) and **unassisted (no cheat flags)** (`seed=437 WON@112,074`, `seed=471 WON@149,406`, `seed=472 WON@134,745`, `seed=522 WON@112,667`, `seed=525 WON@102,913`, `seed=543 WON@132,678`).
> - **`neural-net` Hybrid Policy**:
>   - **Phase 0**: Shared 35-feature macro extractor (`py_exodus/autoplay/features.py`) + EV/utility `score_goals` (`py_exodus/autoplay/planner.py`); `900–909` holdout baseline `1 / 10` (`seed=908 WON@111,905`).
>   - **Phases 1–2 (Combat)**: `CombatPolicyNet` (`1.74M` params, `76.18 MB` peak VRAM) trained via outcome-filtered BC (`94.87%` val accuracy, `193/200 = 96.5%` on `900–999` holdout) and PPO (`194/200 = 97.0%`, `0` ally deaths vs symbolic `auto_combat` `190/200 = 95.0%`).
>   - **Phase 3 (Macro Critic — gated)**: `MacroCriticNet` (`1.23M` params, `32.87 MB` peak VRAM, `98.25%` val accuracy on `seed=554`) + `DisagreementLogger`; `900–909` hybrid holdout gate scored `0 / 10` WON (`4` survived), so full-game PPO remains gated until trained on a broader set of `0–899` winning trajectories.

---

## Controls & Hotkeys

- **Movement / Navigation**: **Arrow keys** or **Numpad** (ships must first face the heading; in dungeons `DOWN` steps backward). **Enter** / **Space** confirm menus and advance pages; **Esc** cancels prompts or exits subscreens.
- **`F1` — Book of Lore, Spell Books & Command Reference**: Opens/closes the full in-game documentation from any screen (also accessible from the **Main Menu**), covering all A–Z Ultima III commands, race max stats, profession tables, and the complete Wizard & Cleric spell books.
- **`TAB` (or `F2`) — Auto-Combat**: Toggles tactical Auto-Combat on/off during battle.
- **`F9` — Full Autoplay / Watch Mode**: Toggles autonomous autoplay on/off (**`[`** slower, **`]`** faster).
- **`F10`** *(with `--debug`)*: Debug tools.

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

### Test Suite
```bash
uv run python -m pytest
```
The suite currently runs **1,293 tests** covering mechanics, Java/GBC parity, vendors, dungeons, combat, rendering, autoplay regressions, and the `neural-net` hybrid modules.

---

## Known Bugs, Open Items & Deliberate Deviations

### Deliberate Deviations
1. **Wireframe dungeon renderer**: Classic 1st-person software wireframe projection instead of Java LibGDX's 3D pipeline (mechanics match).
2. **Fixed spell letters (A–P)**: Spell menus always keep the full original A–P slot indices instead of compacting letters by mana/context; invalid attempts refuse with `"Not Here!"` or the canonical MP message.
3. **Classic GBC/LW mechanic rulings**: Slow/fast moon moongate table (`trammel` visible site -> `felucca` destination), ship-battle party-wide `"Cannonball barrage!"`, meal-crossing `-5 HP` starvation / `+1 HP` regen, and `QUICKNESS` stop-time gating.
4. **Quality-of-life & save rulings**: No quick-start party (create in party formation); `Q` save is Sosaria-overworld only (disabled in dungeons); `APPAR_UNEM` casts without a direction prompt to open the chest underfoot; saves/rosters are JSON-only (legacy binary `.ult` loader removed).

### Known Open Items
1. **Audio**: `Sound.POISON_EFFECT` and `Sound.FIREFIELD` cues are not yet wired to poison/fire field triggers.
2. **Input**: Keyboard only (no gamepad mapping yet).
3. **`H` (Hand Equipment)**: Transfers unequipped weapons and armor only (per Java `HandDialog.java`), not food—autoplay compensates by equalizing food at purchase time.
4. **Combat regen**: Passive MP (`tick_regen`) and meal-crossing `+1 HP` do not tick during combat rounds (only healing spells restore HP mid-battle).
5. **Autoplay & `neural-net` Hybrid Branch**: End-to-end A-to-Z victory on the `pre-nn` symbolic baseline (`master` tag `pre-nn`) is verified both under `NOHURT` (`seed=417 WON@142845`, `seed=418 WON@114926`) and unassisted (`nohurt=False`: `seed=437 WON@112074`, `seed=471 WON@149406`, `seed=472 WON@134745`, `seed=522 WON@112667`, `seed=525 WON@102913`, `seed=543 WON@132678`). On this `neural-net` branch (implementing `docs/superpowers/plans/2026-11-19-nn-hybrid-policy.md`, `<= 5M` params / `< 500 MB` VRAM on RTX 3050):
   - **Phase 0**: Shared 35-feature macro extractor (`py_exodus/autoplay/features.py`) and EV/utility `score_goals` (`py_exodus/autoplay/planner.py`); `900–909` holdout baseline `1 / 10` (`seed=908 WON@111905`).
   - **Phases 1–2 (Combat)**: `CombatPolicyNet` (`1.74M` params, `76.18 MB` peak VRAM) trained via outcome-filtered BC (`94.87%` val accuracy, `193/200 = 96.5%` on `900–999` holdout encounters) and PPO (`194/200 = 97.0%`, `0` ally deaths vs symbolic `auto_combat` `190/200 = 95.0%`).
   - **Phase 3 (Macro Critic — evaluating)**: `MacroCriticNet` (`1.23M` params, `32.87 MB` peak VRAM, `98.25%` val accuracy) + `DisagreementLogger`, gating full-game holdout performance on `900–999` before any full-game PPO fine-tuning.

---

## Utilities

- `scripts/render_maps.py`: Renders `assets/maps/*.json` to top-down PNGs in `maps_rendered/`.

---

## License

Educational, preservation, and non-commercial archival use. Original *Ultima III: Exodus* content, design, and assets remain copyright © their respective owners and Richard Garriott / Origin Systems.
