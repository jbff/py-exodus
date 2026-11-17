# Full Autoplay ("Watch Mode") Strategy & Implementation Plan (2026-11-17)

## Goal
Add an optional **Full Autoplay** mode (`python -m py_exodus --autoplay` or in-game hotkey `F9`) that drives the real `GameApp` / `StateMachine` loop from Level 1 through **Exodus Victory** (`FinalScreen`), so the player can watch the game play itself end-to-end on screen at a configurable pace.

---

## Architecture: Live Input-Driver Controller
Hook an `AutoPlayController` into `GameApp.run()` (`py_exodus/__main__.py`):
- **Non-invasive**: `AutoPlayController` never mutates `Party`, `GameMap`, or `DungeonState` directly. It inspects `state_machine.current_screen` and emits real `pygame.KEYDOWN` events into `state_machine.handle_event(...)` (with `unicode` populated), paced by a wall-clock step timer (e.g., `0.10s` per step, adjustable with `[` / `]`).
- **Combat delegation**: Whenever `CombatScreen` appears, `AutoPlayController` presses `K_TAB` once if `not screen.auto_combat`, letting the existing Lairware-style **Auto-Combat** AI + animation sequencer fight the battle visually, then presses `K_RETURN` at `"Victory! / Press Enter to continue."`.
- **Resilient recovery**: Every navigation leg uses live state predicates (checking current `map_id`, `(x, y, z)`, `marks`, `cards`, `levels`, `weapons`/`armors`, `gold`, `hp`) rather than brittle hardcoded step counts—so random encounters, wandering NPCs, wind shifts, and chest traps naturally pause, resolve, heal, and resume toward the current milestone.

---

## Walkthrough Strategy (Classic Ultima III Progression)

Based on the Ultima III: Exodus walkthrough (UltimaCodex / StrategyWiki) mapped onto `py_exodus`'s exact coordinates and rules:

### Phase 0 — Boot & Party Setup (`StartScreen` / `RosterScreen`)
- **Start**: On `StartScreen`, press `J` (`Journey Onward`) if a valid living `saves/party.json` exists, else `R` (`Form Party`) -> select/create balanced 4-member party (`SHADOW` Thief, `GRUMM` Fighter, `SERENA` Cleric, `ZIRCON` Wizard) -> `J` to enter Sosaria (`map_id=0`).

### Phase 1 — Outfitting & Early Grinding (Level 1 -> Level 3)
1. **Britain (`map_id=3`, Sosaria `(46, 19)`)**:
   - Walk to Weaponry `(39, 19)` (`T -> N`) to buy Sling/Mace/Dagger; Armoury `(50, 20)` (`T -> N`) to buy Cloth; Grocery `(48, 49)` (`T -> S`) for extra food if low (`food < 200`).
   - Ready (`R`) and Wear (`W`) purchased gear on all 4 members.
2. **Grind EXP & Gold on Sosaria grass** (`(42..46, 20..26)` near Castle British):
   - Patrol open grass tiles triggering/fighting low-tier encounters (Auto-Combat handles fights; Cleric heals via `SANCTU`, or `C -> SANCTU` / `R`est (`P`ass) on overworld if needed; visit Castle British Healer `(46, 26)` if anyone is poisoned/dead).
   - Loot chests with `APPAR_UNEM` (`C -> B` on Cleric) or `G`et on Thief (`SHADOW`) for gold.
   - Return to **Castle of Lord British** (`map_id=1`, `(45, 18)` -> bridge `(30, 33)` -> `(32, 15)`, `T -> N`) whenever `min(member.exp) >= next_level_threshold` until Level 5 (`exp >= 500`, `max_hp=550`).

### Phase 2 — Mark of Kings & Level 6/7
1. **Dardin's Pit (`map_id=15`, Sosaria `(46, 7)`)** *(or Perinian Depths `map_id=14` at `(56, 6)`)*:
   - Enter dungeon (`E`), cast `LORUM` (`C -> D` on Cleric) for light.
   - Use 3D-grid BFS (`DungeonMap` passability, avoiding traps/pits or healing after) to descend `D`own ladders to `z=1` -> step onto `MARK_KINGS` (`(11, 3, z=1)` in Dardin), touch/trigger mark for all 4 members (`marks[0] == 1`), heal if HP < 50%, and climb `K`limb back to Sosaria.
2. **Advance at Lord British** to Level 6+ (`max_hp >= 650`).

### Phase 3 — Naval Capture, Whirlpool & Ambrosia
1. **Capture a Ship**:
   - Patrol Sosaria coast near `(46..54, 10..20)` until engaging a `pirate` creature (or board an existing unmanned `frigate` via `B`).
   - Win ship-to-ship combat -> step onto the dropped `frigate` -> press `B` (`Board Frigate!`).
2. **Whirlpool -> Ambrosia (`map_id=13`)**:
   - Sail toward the Sosaria whirlpool (`(50, 13)` or `(17, 48)`), respecting wind direction (`heading` turns first, waits/passes or tacks if headwind blocks until wind shifts every 20 moves).
   - Step onto whirlpool -> engulfed to Ambrosia `(32, 54)` (`Transport.FOOT`).
3. **Four Cards & Four Shrines on Ambrosia**:
   - BFS across Ambrosia land/unlocked paths to each of the 4 Card/Shrine sites:
     - `(55, 27)`: `O -> SEARCH` (`CARD_OF_DEATH`) + `E` -> Wisdom Shrine (raise `SERENA` WIS toward `75` if gold allows).
     - `(45, 52)`: `O -> SEARCH` (`CARD_OF_SOL`) + `E` -> Dexterity Shrine.
     - `(6, 6)`: `O -> SEARCH` (`CARD_OF_MOONS`) + `E` -> Intelligence Shrine (raise `ZIRCON` INT toward `75`).
     - `(4, 36)`: `O -> SEARCH` (`CARD_OF_LOVE`) + `E` -> Strength Shrine.
4. **Return to Sosaria**:
   - Head east to the Ambrosia pirate ship/door route, unlock door (`L` if keys available, or buy keys in Dawn/Death Gulch beforehand), defeat pirates, board ship, and sail to `(32, 57) -> (32, 58)` (`WHIRLPOOL` portal -> Sosaria coast).

### Phase 4 — Remaining Marks & Exotic Equipment
1. **Dungeon of Fire (`map_id=17`, Sosaria `(49, 34)`)**:
   - Descend to `z=7` via BFS -> touch `MARK_FIRE` `(5, 14, 7)` and `MARK_FORCE` `(4, 10, 7)` -> climb/exit (`EXODUS` spell or `K`limb).
2. **Dungeon of the Snake (`map_id=19`, Sosaria `(58, 44)`)**:
   - Descend to `z=7` -> touch `MARK_SNAKE` `(6, 15, 7)` -> exit.
3. **Exotic Weapons & Armor (`O -> DIG`)**:
   - Navigate to `(33, 3)` on Sosaria -> `O -> DIG` for all 4 members -> `R`eady `EXOTIC` weapon.
   - Navigate to `(19, 44)` on Sosaria -> `O -> DIG` for all 4 members -> `W`ear `EXOTIC` armor.

### Phase 5 — Castle of Death (`EXODUS`) & Ending
1. **Reach `(10, 53)`**: Sail/walk to Castle of Death (`map_id=2`), `Y`ell `EVOCARE` if blocked by snake barrier, `E`nter `EXODUS`.
2. **Navigate `exodus.json` to Machine Region**:
   - BFS through `exodus.json` from `(32, 62)` to `(30..33, 12)` (Auto-Combat clears invisible/guard encounters with `EXOTIC` gear + `ZXKUQYB`/`UNSPEAKABLE`).
3. **Insert 4 Cards & Win**:
   - At `(30, 12)` `O -> INSERT -> L` (Love)
   - At `(31, 12)` `O -> INSERT -> S` (Sol)
   - At `(32, 12)` `O -> INSERT -> M` (Moons)
   - At `(33, 12)` `O -> INSERT -> D` (Death)
   - Transition to `FinalScreen` -> victory ending!

---

## Modular Implementation Breakdown

1. **`py_exodus/autoplay/planner.py`**:
   - Milestone state machine (`Goal` enum: `SETUP_PARTY`, `OUTFIT_BRITAIN`, `GRIND_TO_LEVEL`, `GET_MARK_KINGS`, `CAPTURE_SHIP`, `SAIL_WHIRLPOOL`, `AMBROSIA_CARDS_SHRINES`, `EXIT_AMBROSIA`, `GET_REMAINING_MARKS`, `DIG_EXOTICS`, `CONQUER_EXODUS`, `DONE`) + `next_goal(party, screen)` predicate evaluator.
2. **`py_exodus/autoplay/nav.py`**:
   - **2D BFS pathfinder** (`find_overworld_path` / `find_town_path`): wraps on `64x64` Sosaria/Ambrosia, respects `Transport.FOOT`/`SHIP`/`HORSE`, avoids force fields without Mark of Force, handles ship heading-turn-before-move and wind tacking/waiting.
   - **3D Dungeon BFS pathfinder** (`find_dungeon_path`): searches `(x, y, z, dir)` across `LADDER_DOWN` / `LADDER_UP` to target `(tx, ty, tz)` or exit `(1, 1, 0)`, emitting `UP`/`DOWN`/`LEFT`/`RIGHT`/`D`/`K` keys.
3. **`py_exodus/autoplay/controller.py`**:
   - `AutoPlayController`: dispatches key sequences (`_key_queue`), handles modal prompts (`Yell`, `Other Command?`, `Talk`, `Vendor`, `Shrine`, `CombatScreen` `K_TAB` auto-combat toggle), monitors party HP/poison/MP/food for survival detours (cast `SANCTU`/`ALCHOR`, buy food, visit Healer).
4. **`py_exodus/__main__.py`**:
   - Add `--autoplay` CLI flag and `F9` runtime toggle in `GameApp`, plus `[` / `]` speed controls.
5. **Verification (`tests/test_autoplay.py`)**:
   - Unit tests for 2D/3D BFS pathfinders, goal evaluator, prompt-queue handling, and an end-to-end headless smoke test driving segments (Level 1 -> Britain -> Combat -> Dardin -> Ambrosia -> EXODUS victory).
