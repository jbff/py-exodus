# py-exodus

A Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, featuring **Auto-Combat** (`TAB`), an experimental autonomous **Full Autoplay / Watch Mode** (`F9`), and — on the `neural-net` branch — a **neural-net combat policy** that `Full Autoplay` uses by default.

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
> - **FIRST FULL AUTOPLAY WIN on this branch (2026-11-20, live, unassisted)**: NN combat + the symbolic strategy doctrine (early Ambrosia -> cleric Wis 99 + all 4 cards + ALCORT self-sufficiency -> Death Gulch bribe raids -> Ambrosia stat-max returns -> Exodus castle). Combat was the neural net; strategy was the symbolic ladder. All symbolic doctrine now also merged to `master` (af2ece1).
> - **`neural-net` Hybrid Policy**:
>   - **Phase 0**: Shared 35-feature macro extractor (`py_exodus/autoplay/features.py`) + EV/utility `score_goals` (`py_exodus/autoplay/planner.py`); `900–909` holdout baseline `1 / 10` (`seed=908 WON@111,905`).
>   - **Phases 1–2 (Combat) — v3 full-battlefield net, wired into live autoplay**: `CombatPolicyNet` (`868k` params, v3 encoder: member level, armed weapon, monster types; combat-irrelevant moon/wind/hull dropped) trained via BC + PPO over the FULL reachable encounter space — 13 battle creatures x every reachable conflict map (incl. ship maps 39/40/41, shore 38, boarding 33) x party transports x monster counts 1–8 x levels 3–25, with diverse parties (MP pools up to 75+, wounded squads, level-shaped gear). Holdout (`900–999`, 3,168 episodes): NN `95.2%` overall / `99.2%` ship battles vs symbolic `96.1%` / `98.7%` — ship-vs-serpent looping (the v1 OOD failure) fixed. The v3 action space lets the net choose every combat-castable spell individually.
>   - **NN Strategy Layer — explored and removed (2026-11-20)**: a hazard critic and an economy critic were built, measured, and stripped from the tree after three attribution attempts found no learnable signal in symbolic rollout data (the hazard A/B moved nothing — pathing deaths aren't the failure mode; the economy critic's rank-corr stayed at noise — combat gold is too sparse). The symbolic ladder is the strategy of record; `rollout_recorder.py` remains for future corpus work, and `scripts/rollout_atlas.py` produces the 100-seed failure atlas on demand.
>   - **Phase 3 (Macro Critic + Overworld Policy — offline evaluation only, not wired into autoplay)**: `MacroCriticNet` BC achieves `99%+` val accuracy, but on full-game `900–909` holdout runs no NN configuration beat the symbolic baseline (`1/10`): macro-BC residual-EV ties it (`1/10`, `seed=905 WON@84,535`), while macro-PPO (`macro_rl.pt`, `macro_rl_res.pt`) and the 3-net overworld variants (`overworld_ppo*.pt`) all scored `0 / 10` (reward-hacking loitering, early wipes on foot near Britain, economy stalls). Full-game PPO remains gated; see the handoff report for diagnosed failure modes and next steps.

### NN Combat Policy (`neural-net` branch)

`Full Autoplay` no longer plays combat with the symbolic `auto_combat` heuristic: it drives the arena directly through the trained `CombatPolicyNet` (`py_exodus/autoplay/nn_policy.py`). The shipped checkpoint (weighted/oversampled-BC v3 net, `combat_ppo.pt`) measures `96.1%` overall (`95.3%` land / `99.2%` ship) vs symbolic `96.1%` / `98.7%` (`900–999`, 3,168 episodes) — and unlike the v1 net it stays competent in ship battles, with the class-rebalanced free-spell openings restored (Repond/Pontorri fire at combat start vs orcs/undead; they were 0.2% of BC samples and never fired under the unweighted net). It is loaded **once** at startup and kept resident for the whole session (never reloaded per encounter).

- **Canonical-party enforcement (hard rule on this branch)**: Full Autoplay — and TAB/F2 Tactical Auto-Combat, for human players too — works **only** for the canonical 4-member **Thief + Fighter + Cleric + Wizard** party. `F9` refuses to engage on any other composition, autoplay silently disables at the first gameplay step of a wrong-party save, and `StateMachine` swallows TAB/F2 on combat screens with non-canonical parties. This matches both the controller's tested paths and the net's training distribution (profession permutations are out of scope by design).
- **Spell-level decisions**: the v3 action space (23 actions) gives the net its own learnable index for every combat-castable spell (REPOND, MITTAR, FULGAR, NOXUM, DAG_MENTAR, NECORP, DECORP, UNSPEAKABLE, PONTORI, SANCTU, SANCTU_MANI, ALCORT, EXCUUN, ZXKUQYB); directions and heal targets are chosen mechanically by engine helpers, exactly as the symbolic teacher does. The symbolic teacher itself now cures poison (ALCORT) during auto-combat.
- **`--autoplay`**: enables the NN combat policy by default.
- **`--nn-combat` / `--no-nn-combat`**: force it on or off when running autoplay.
- **`--nn-device auto|cuda|cpu`**: torch device for the net (default `auto` = CUDA when available, e.g. an RTX 3050).
- **No symbolic fallback**: if the checkpoint or torch/CUDA is broken, the game errors out at startup rather than silently degrading (`autoplay/nn_policy.py` raises on load failure; inference errors propagate). Autoplay also no longer plays at manual combat pacing — combat FX runs at the symbolic auto-combat cadence, scaled by the same `[` / `]` speed control.
- **Robustness layers (2026-11-20)**: a loop-breaker memory layer detects repeating board/disembark cycles and locks the goal-wrong transport out until the pattern stops (the B/X starvation oscillation class); heal/cure actions in the v3 mask are gated on a wounded/poisoned target actually existing (the engine refuses full-health heals *without advancing the turn*, which livelocked a deterministic net mid-reheal); and the pathfinder now mirrors movement-validator force-field rules exactly (all-living Mark of Force).
- **Training & evaluation** (`scripts/train_combat_fullspace.py`): enumerates the full reachable encounter space (13 battle creatures × reachable conflict maps incl. ship maps 39/40/41 × foot/ship × monster counts 1–8 × levels 3–25, diverse parties with MP pools up to 75+ and wounded squads), collects outcome-filtered symbolic-teacher episodes on train seeds `0–899`, trains BC then PPO (CUDA-aware), and evaluates vs the symbolic baseline on holdout seeds `900–999`, split land/ship. All 32 spells are contract-tested in both overland and combat contexts (`tests/test_spells_all.py`); only the production `combat_ppo.pt` checkpoint is tracked in git.

---

## Controls & Hotkeys

- **Movement / Navigation**: **Arrow keys** or **Numpad** (ships must first face the heading; in dungeons `DOWN` steps backward). **Enter** / **Space** confirm menus and advance pages; **Esc** cancels prompts or exits subscreens.
- **`F1` — Book of Lore, Spell Books & Command Reference**: Opens/closes the full in-game documentation from any screen (also accessible from the **Main Menu**), covering all A–Z Ultima III commands, race max stats, profession tables, and the complete Wizard & Cleric spell books.
- **`TAB` (or `F2`) — Auto-Combat**: Toggles tactical Auto-Combat on/off during battle. On the `neural-net` branch this is restricted to the canonical Thief + Fighter + Cleric + Wizard party (see **NN Combat Policy**).
- **`F9` — Full Autoplay / Watch Mode**: Toggles autonomous autoplay on/off (**`[`** slower, **`]`** faster). Also restricted to the canonical party composition.
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
The suite currently runs **1,420 tests** covering mechanics, Java/GBC parity, vendors, dungeons, combat, rendering, autoplay regressions, and the `neural-net` hybrid modules.

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
   - **Phases 1–2 (Combat — wired into live autoplay)**: `CombatPolicyNet` (v3, `868k` params) trained via full-battlefield BC + PPO (`scripts/train_combat_fullspace.py`): 13 battle creatures × every reachable conflict map (incl. ship maps 39/40/41) × party transports × monster counts 1–8 × levels 3–25, diverse parties (MP to 75+, wounded squads, level-shaped gear). Holdout (`900–999`, 3,168 episodes): NN `95.2%` overall / `99.2%` ship vs symbolic `96.1%` / `98.7%` — the v1 ship-vs-serpent OOD loop is fixed. Ships at `py_exodus/nn/checkpoints/combat_ppo.pt`; `--autoplay` enables it (`--no-nn-combat` disables; `--nn-device` selects `auto|cuda|cpu`); loaded once at startup, resident for the session; **no symbolic fallback on this branch** — a broken NN setup raises at startup. Autoplay AND TAB/F2 auto-combat are restricted to canonical Thief+Fighter+Cleric+Wizard parties.
   - **Phase 0 (macro features/EV planner)**: shared 35-feature macro extractor (`py_exodus/autoplay/features.py`) and `score_goals` (`py_exodus/autoplay/planner.py`); `900–909` full-game baseline `1 / 10` (`seed=908 WON@111905`).
   - **Phase 3 (Macro Critic + Overworld Policy — offline only)**: `MacroCriticNet` (`1.23M` params, `32.87 MB` peak VRAM) BC reaches `99%+` val accuracy and `OverworldPolicyNet` (`1.48M` params) BC hits `1.0` val accuracy, but no macro/overworld configuration has beaten the symbolic full-game baseline (`1/10` holdout): macro-BC residual-EV ties it (`1/10`, `seed=905 WON@84535`); macro-PPO and 3-net overworld variants scored `0 / 10` (reward-hacking loitering, early on-foot wipes near Britain, economy stalls). These nets remain deliberately unwired from autoplay on this branch.

---

## Utilities

- `scripts/render_maps.py`: Renders `assets/maps/*.json` to top-down PNGs in `maps_rendered/`.

---

## License

Educational, preservation, and non-commercial archival use. Original *Ultima III: Exodus* content, design, and assets remain copyright © their respective owners and Richard Garriott / Origin Systems.
