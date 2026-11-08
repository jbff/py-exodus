# Java vs Python Exodus Parity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all behavioral, mechanical, and feature gaps identified during the complete 83-file audit between the Java LibGDX reference (`src/main/java`) and the Python implementation (`py_exodus`).

**Architecture:** Implement modular parity improvements across four core game domains:
1. Vehicle lifecycle & naval combat (`Transport.SHIP` broadside cannons, frigate victory drops, disembark/embark parking).
2. Spells & chest mechanics (`APPAR_UNEM` auto-collect, 0-MP spell combat quotas).
3. World exploration, labels, and celestial conjunctions (Exotic arms/cards labels search, Dawn dual-new-moon conjunction, Ambrosia whirlpool warp, moongate routing).
4. Specialty town vendor dialogues (Tavern food/ale tipping clues, Oracle prophecy offerings) and dungeon tile hazards/fountains.

**Tech Stack:** Python 3.14+, Pygame-CE, Pytest.

**Spec:** `docs/superpowers/java-python-audit.md` (audit matrix comparing all 83 Java files to Python equivalents).

## Global Constraints

- Never break existing 217 passing tests in `tests/`.
- Maintain single-key auto-commit prompts (`single_char=True`) for all direction, member, choice, and spell inputs.
- Keyboard movement must remain Arrow keys / keypad only; letters are reserved for commands.
- Preserve save compatibility for `PARTY.SAV` and JSON save files.

## Review Focus

1. Defeating pirate ships at sea drops a boardable frigate object, never a chest.
2. Casting `APPAR_UNEM` disarms, opens, and grants gold from a chest in one action across overworld, towns, and dungeons.
3. Firing ship cannons ('F') is strictly restricted to broadsides (perpendicular to heading), damaging target ships or sea creatures.
4. Searching ('S') on overland map tiles with XML labels awards the item (Exotic Armor, Exotic Weapon, Cards) and 100 XP to the searching member.
5. City of Dawn entrance only admits party when both moons are in phase 0 (new moon).

---

### Task 1: Pirate Victory Frigate Drops & Vehicle Boarding/Exiting

**Files:**
- Modify: `py_exodus/combat/arena.py:880-905`
- Modify: `py_exodus/screens/overworld.py:300-340, 580-600`
- Modify: `py_exodus/screens/combat_screen.py:425-445`
- Test: `tests/test_vehicles_and_naval.py`

- [ ] **Step 1: Write failing tests for pirate drops, boarding, and disembarking**
  - Verify defeating pirate encounter spawns a `frigate` dynamic object at the encounter tile, not a chest.
  - Verify Board ('B') next to/on a frigate sets transport to `SHIP` and initial hull to 50.
  - Verify eXit ('X') while sailing parks a frigate on the water/shore and reverts party to `FOOT`.
  - Verify eXit ('X') while mounted on a horse leaves a horse on the map.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_vehicles_and_naval.py`

- [ ] **Step 3: Implement vehicle lifecycle matching Java GameScreen.java:582-597, 945-985**
  - In `CombatArena.check_end_conditions()`, ensure encounters where `creature_tile == "pirate"` always spawn `{"tile": "frigate", "x": x, "y": y}` into `party.dynamic_objects`.
  - In `OverworldScreen.board()`, if `frigate` object is on or adjacent to party, remove frigate object, set `party.transport = Transport.SHIP`, set `party.ship_hull = 50`.
  - In `OverworldScreen.exit_transport()` (mapped to 'X'), if transport is `SHIP`, spawn `{"tile": "frigate", "x": party.x, "y": party.y}` into `dynamic_objects`, reset transport to `FOOT`. If `HORSE`, spawn `{"tile": "horse", ...}` and reset to `FOOT`.

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_vehicles_and_naval.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement pirate frigate drops and board/exit vehicle mechanics"`

---

### Task 2: Broadside Ship Cannons

**Files:**
- Modify: `py_exodus/screens/overworld.py:150-155, 340-370`
- Modify: `py_exodus/combat/resolver.py`
- Test: `tests/test_vehicles_and_naval.py`

- [ ] **Step 1: Write failing tests for broadside cannon firing**
  - Verify firing ship cannons perpendicular to ship heading succeeds (e.g. heading North fires East or West).
  - Verify firing parallel to heading (e.g. heading North fires North) fails with `"Broadsides only!"`.
  - Verify cannon shot damages targeted enemy ship / sea monster within range.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_vehicles_and_naval.py -k test_broadside`

- [ ] **Step 3: Implement broadside cannon firing matching Java GameScreen.java:980-1035 and Utils.java:423-496**
  - In `OverworldScreen._prompt_fire_cannons()`, determine valid firing directions based on last move direction (`heading`):
    - Heading NORTH or SOUTH -> only WEST or EAST valid.
    - Heading EAST or WEST -> only NORTH or SOUTH valid.
  - If player chooses invalid direction, log `"Broadsides only!"`.
  - Trace projectile in direction; if a sea creature or enemy ship is within 3 tiles, deal cannon damage (e.g. 20-50) and play explosion sound/fx.

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_vehicles_and_naval.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement broadside cannon rules and naval attack resolution"`

---

### Task 3: APPAR_UNEM Auto-Collect & Free Spell Combat Limits

**Files:**
- Modify: `py_exodus/combat/magic.py:556-590`
- Modify: `py_exodus/combat/arena.py`
- Modify: `py_exodus/screens/town.py:125-130`
- Modify: `py_exodus/screens/dungeon_screen.py:140-145`
- Test: `tests/test_spell_mechanics.py`

- [ ] **Step 1: Write failing tests for APPAR_UNEM auto-collect and free spell limits**
  - Verify casting `APPAR_UNEM` removes the chest and grants gold immediately across overworld, town, and dungeon screens without needing 'G' (Get).
  - Verify `REPOND` and `PONTORI` allow only 1 cast per member per combat engagement (`used_free_spell = True`), logging `"Can't!"` on subsequent attempts.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_spell_mechanics.py`

- [ ] **Step 3: Implement spell updates matching Java SpellUtil.java:62-71, 140-149**
  - In `magic.py`, update `cast_spell()` for `APPAR_UNEM` to inspect overworld dynamic objects, town map chest tiles, and dungeon chest tiles, removing them, disarming traps, and granting gold directly to the party.
  - In `CombatArena`, add `used_free_spell` per `CombatPlayer`. In `cast_spell()`, if spell is `REPOND` or `PONTORI` and `player.used_free_spell` is True, reject with `"Can't!"`. Otherwise set `player.used_free_spell = True`.

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_spell_mechanics.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement APPAR_UNEM auto-collect and free spell limits per combat"`

---

### Task 4: Map Labels Search (Exotic Weapons, Exotic Armor, Cards) & Town Chest Looting

**Files:**
- Modify: `py_exodus/screens/overworld.py:560-585`
- Modify: `py_exodus/screens/town.py:125-130`
- Test: `tests/test_search_and_labels.py`

- [ ] **Step 1: Write failing tests for label searching and town chest looting**
  - Place party at (79, 176) on overworld and search -> receives EXOTIC_ARMOR + 100 XP.
  - Place party at (134, 14) on overworld and search -> receives EXOTIC_WEAPON + 100 XP.
  - Place party at Ambrosia card locations and search -> receives corresponding CARD + 100 XP.
  - Stand next to a chest in town and press 'G' -> prompts member, opens chest, awards gold.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_search_and_labels.py`

- [ ] **Step 3: Implement label searching matching Java BaseMap.java:855-930**
  - In `OverworldScreen._search()`, prompt for searching member (1-4).
  - Check `self.game_map.labels` for any label matching `(party.x, party.y)`.
  - If `EXOTIC_ARMOR`: award Exotic Armor to member, +100 XP, log `"Found Exotic Armor!"`.
  - If `EXOTIC_WEAPON`: award Exotic Weapon to member, +100 XP, log `"Found Exotic Weapon!"`.
  - If `CARD_OF_DEATH / SOL / MOONS / LOVE`: award card to member, +100 XP, log `"Found the Card of ...!"`.
  - In `TownScreen._get_chest()`, check adjacent tile for `rule == "chest"` or chest dynamic object, handle trap, award gold, and replace tile with floor.

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_search_and_labels.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement map label search for exotic gear/cards and town chest looting"`

---

### Task 5: Moon Conjunctions, Moongates & Ambrosia Whirlpool

**Files:**
- Modify: `py_exodus/screens/overworld.py:800-840, 920-960`
- Test: `tests/test_celestial_and_gates.py`

- [ ] **Step 1: Write failing tests for Dawn conjunction, moongates, and whirlpool**
  - Verify portal to Dawn (map 11) is blocked unless `trammel_phase == 0 and felucca_phase == 0`.
  - Verify moongate entry routes to destination gate determined by `felucca_phase` (`d1`, `d2`, `d3`).
  - Verify whirlpool in Ambrosia transports party to Sosaria coast (x=48..53, y=0..8).

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_celestial_and_gates.py`

- [ ] **Step 3: Implement celestial rules matching Java GameScreen.java:544-547, 661-670, 922-944**
  - In `OverworldScreen._check_portals()`: if destination is Dawn (`dest_id == 11`), only permit entry when `self.party.moons == (0, 0)`.
  - In `OverworldScreen._check_moongates()`: active gate opens at `trammel_phase`; destination is determined by matching `felucca_phase` with gate's `d1`, `d2`, `d3`.
  - In Ambrosia map handling: entering Whirlpool portal warps party to Sosaria at random x in [48..53], y in [0..8].

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_celestial_and_gates.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement Dawn conjunction, moongate routing, and Ambrosia whirlpool"`

---

### Task 6: Specialty Vendors (Tavern Clues & Oracle Prophecies)

**Files:**
- Modify: `py_exodus/screens/town.py:320-410`
- Test: `tests/test_specialty_vendors.py`

- [ ] **Step 1: Write failing tests for Tavern and Oracle dialogues**
  - Verify speaking with a Tavern vendor prompts `"Food or Ale?"`.
  - Verify buying Ale with a tip (e.g. paying 20 gp on 5 gp ale) prints the corresponding rumor clue from `vendor.xml` (`TAVERNINFO`).
  - Verify speaking with Oracle vendor prompts for offering in hundreds of gp (100-900) and prints the prophecy from `vendor.xml` (`ORACLEINFO`).

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_specialty_vendors.py`

- [ ] **Step 3: Implement Tavern and Oracle services matching TavernService.java & OracleService.java**
  - In `TownScreen._start_vendor_shopping()`, check `vendor.vendor_type`:
    - If `TAVERNINFO`: prompt `"What'll it be, Food er Ale?"`. If Food, buy specialty plates. If Ale, prompt payment amount; if `payment > ale.price`, find item in `vendor.items` where `tip // 10 == item.price // 10`, and print the clue description.
    - If `ORACLEINFO`: prompt `"How many 100 gp is your offering? (1-9):"`. Deduct `amt * 100` gold, find item with `price == amt * 100`, and log the prophecy.

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_specialty_vendors.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement Tavern clue tipping and Oracle prophecy services"`

---

### Task 7: Dungeon Hazards, Marks & Fountains

**Files:**
- Modify: `py_exodus/screens/dungeon_screen.py:200-320`
- Modify: `py_exodus/world/dungeon.py`
- Test: `tests/test_dungeon_mechanics.py`

- [ ] **Step 1: Write failing tests for marks, fountains, and dungeon traps**
  - Touching a Mark (Kings/Fire/Force/Snake) sets mark on member and applies 50 branding damage.
  - Drinking from fountains: Plain (no effect), Heal (full heal), Acid (25 damage), Cure (cures poison), Poison (poisons member).
  - Gremlins trap steals half of party's food.
  - Wind trap extinguishes torch.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run `pytest tests/test_dungeon_mechanics.py`

- [ ] **Step 3: Implement dungeon tile effects matching DungeonScreen.java:1080-1205**
  - In `DungeonScreen`, implement:
    - `get_mark(tile, member)`: set `member.marks[mark_idx] = 1`, deal 50 damage, play lightning SFX.
    - `drink_fountain(tile, member)`: apply fountain effect based on type, play corresponding sound and log message.
    - Step-on hazard triggers: `WIND_TRAP` turns off torch; `GREMLINS` halves `party.food`; `PIT_TRAP` deals lava damage.

- [ ] **Step 4: Run pytest to confirm tests pass**
  - Run `pytest tests/test_dungeon_mechanics.py`

- [ ] **Step 5: Commit changes**
  - `git commit -am "Implement dungeon marks branding, fountain effects, and hazard traps"`
