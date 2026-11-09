# Java-Parity Fix Plan for PyExodus

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Python port to behavioral parity with the Java source at `/sto/src/gdx-exodus/` (17k lines vs Python's 14k), fixing 6 game-blocking bugs and ~60 divergences found by a 5-agent audit.

**Architecture:** Fix in dependency order: shared core systems first (party tick, tile effects, aura, chest pipeline), then per-screen consumers (commands, vendors, combat, dungeons, endgame). New small modules: `world/tile_effects.py`, `world/chests.py`, `py_exodus/aura.py`, `screens/vendor_dialog.py`. Java code is truth — when a finding lists Java lines, the implementer MUST read them before coding.

**Tech Stack:** Python 3.14, pytest (240 tests currently green — they must stay green; a task that breaks existing tests fixes the tests too, only if the test encoded the divergent behavior being reverted).

**Spec:** the 5 audit reports summarized in `docs/superpowers/plans/2026-11-08-audit-findings.md` (companion file). The audit reports are the spec; this plan decomposes them.

## Global Constraints

- **Java is truth.** Do not "improve" Java behavior. Port bugs like ZXKUQYB's integer division and the `TileRule.monster` bitwise quirk are ported faithfully.
- **Do not fix tests that assert divergent behavior without changing them.** If a test asserts, e.g., `sanctuary heals randint(10,25)`, update the test to the Java value as part of the task.
- **Shared data XMLs (weapons/armors/creatures/tileset/maps/vendor) are byte-identical — never edit them.**
- Every command that Java routes through `finishTurn` consumes a turn; Python must match (see Global rule in Task 6).
- All new player-visible strings must match the Java strings verbatim (audit reports quote them).
- Commit after each task; message prefix `parity:`.

## Kept Divergences (do NOT "fix" these)

1. **Starter/quick-start party** stays (usability scaffolding; Java requires manual creation only). Task 14 fixes creation rules themselves.
2. **Magical Orbs removed entirely** (user decision 2026-11-08): orbs are dead code in the Java port, and the user wants no touch-me-and-nothing-happens prop. Task 13 must delete Python's +5-stat orb grant AND the "You find a Magical Orb...Who touches?" prompt — search results never mention orbs, and any orb rendering is dropped.
3. **Peer gem stays text-only** (Java renders an image; the survey data is what matters).
4. **Text log / prompt engine** conventions (ESC cancels, arrow-key commit) stay; Java's "non-number → Nobody selected!" is noted, not replicated.
5. **FOV edge-wrapping on city borders** stays (edge case only).
6. **`dynamic_monsters` for overworld saves** — population path is out of scope unless a task touches it.

## Review Focus

- A member buys/turns in gold with gold=0 → must never produce negative gold, and Java's cap of 9999 per member (`SaveGame.adjustGold`) applies everywhere gold is credited.
- All four members dead in the overworld (e.g., poison/starvation tick) → game over → start screen, even outside combat.
- Inserting a card in the wrong Exodus panel → member loses ALL HP (lethal), save bit `exodusCardsStatus` preserved on reload.
- Food = 0 for many turns with a poisoned member → poison tick damage, not heal, and starvation damage stacks.
- A party member with Mark of Force walks onto an energy field → passes; without it → blocked.
- Casting while NEGATE aura active → "Spell is negated!" and no effect, mana not spent (Java `SpellUtil.java:73-76` — implementer must verify order against source).

---

# Phase 1 — Critical blockers

## Task 1: Shared chest pipeline (gold, traps, direction targeting) + dungeon G crash

**Files:**
- Create: `py_exodus/world/chests.py`, `tests/test_chests.py`
- Modify: `py_exodus/screens/overworld.py:250-284`, `py_exodus/screens/town.py:604-673`, `py_exodus/screens/dungeon_screen.py:252-282`
- Java truth: `exodus/Context.java:248-285` (trap), `exodus/Party.java:273-277` (gold), `exodus/GameScreen.java:1036-1074` (getChest), `exodus/DungeonScreen.java:1007,395-417`, `exodus/SecondaryInputProcessor.java:308-311`

**Interfaces:**
- Produces: `open_chest(party, member, dungeon: bool, disarmed: bool = False) -> list[str]` in `world/chests.py` — mutates `member.gold`/`member.hp`/status, returns log lines. `ChestNotFound` exception for "Not Here!".

The dungeon G command currently crashes (`UnboundLocalError`: `evt` referenced at `dungeon_screen.py:272` outside its defining callback). The fix makes G take a direction (checks only the target tile), and unifies trap/gold: gold = `rand(50)+rand(8)+10` (10–66) credited to the opening member capped at 9999, message "The Chest Holds: %d Gold". Trap: 50% chance; evasion `dex + 25 >= rand(100)`; on hit — Acid = FIRE effect to that member (immune with Mark of Fire), Gas = LAVA effect to a random member, Poison = poison that member. `disarmed=True` (APPAR_UNEM path) skips traps. Also fixes the "Last One!"-style `evt` bug by removing the stray check.

- [ ] Step 1: Failing tests in `tests/test_chests.py`: chest credit goes to `member.gold` not party pool (value range 10–66); dex=200 always evades; trap hit with Mark of Fire makes acid trap a no-op; disarmed chest yields gold, no trap roll.
- [ ] Step 2: `pytest tests/test_chests.py` → fails (module missing)
- [ ] Step 3: Implement `world/chests.py` + rewire all three call sites; dungeon G first fixes the crash (press G with no chest → prompt still completes, "Not Here!" logged, turn consumed).
- [ ] Step 4: `pytest tests/test_chests.py tests/test_search_and_labels.py` → pass
- [ ] Step 5: Commit `parity: unified chest pipeline, fix dungeon G crash`

## Task 2: Party death flow → game over

**Files:**
- Modify: `py_exodus/entities/party.py:409-427`, `py_exodus/screens/overworld.py`, `py_exodus/screens/town.py`, `py_exodus/screens/dungeon_screen.py`, `py_exodus/combat/arena.py:865-881`, `py_exodus/screens/combat_screen.py:440-480`, `py_exodus/screens/start.py`
- Test: `tests/test_death_flow.py` (new)
- Java truth: `exodus/Party.java:556-577` (`PartyDeathException`), `exodus/GameScreen.java:433-446` (`partyDeath()` → StartScreen), `exodus/CombatScreen.java:562-589`

Today nothing kills a fully-dead party outside combat and `combat_screen._handle_defeat_exit` **warps to Castle British and revives everyone** (defeat is survivable). Implement: a `PartyDeathException`-style signal — screens catch "all dead" after any damage application (tile effects, starvation, chest traps, monster attacks, spells) and transition to the start screen with game-over messaging; combat defeat ends combat as a loss → game over (no auto-revive). `kill_all`/`is_party_dead` already exist; they must actually be called on every damage path created by Tasks 5/6/13.

- [ ] Step 1: Failing tests: applyDamage to last living member in overworld context → `state_machine` transitions to start screen; combat defeat → start screen (no revival); damage that leaves ≥1 alive → no transition.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement the guard at the single damage chokepoint used by Task 5's tick engine + each direct-damage path.
- [ ] Step 4: pytest full suite → pass
- [ ] Step 5: Commit `parity: party death cascade and game over`

## Task 3: Exodus endgame — INSERT wiring, card indices, FinalScreen reachable

**Files:**
- Modify: `py_exodus/screens/overworld.py:524-526,619-650`, `py_exodus/screens/final.py:38-45,135-160,170`, `py_exodus/screens/town.py:772-794`, `py_exodus/ui/stats_panel.py:110-175`
- Test: `tests/test_endgame.py` (new)
- Java truth: `exodus/SecondaryInputProcessor.java:613-731` (INSERT + `InsertCardInputAdapter`), `exodus/Party.java:703-715` (zstats marks/cards), `exodus/GameScreen.java:299-311` (persist/reload)

Fixes commands-audit F1/F2 (CRITICAL) and screens-audit #6/#7: (a) card index order is `[DEATH, SOL, MOONS, LOVE] = cards[0..3]` — swap Love/Death in `CARD_NAME_TO_INDEX`; (b) remove the invented forced Love→Sol→Moons→Death order (each panel independent); (c) insertion requires the member to be at the EXODUS-map panel coordinates Love x=30, Sol x=31, Moons x=32, Death x=33, all y=12; (d) wrong panel → member takes `health + 1` damage (lethal), correct panel sets the `exodusCardsStatus` bit, decrements `member.cards[i]`; (e) when all 4 bits set → `FinalScreen` is instantiated and shown (the win path exists nowhere today); (f) `FinalScreen.insert_card` is the entry point consumed by a new INSERT flow on the overworld (typed "INSERT" at the machine region) and from the town "Other command" path; (g) Zstats shows MARK KINGS/FIRE/SNAKE/FORCE and CARD DEATH/SOL/MOONS/LOVE rows (`Party.java:703-715`).

- [ ] Step 1: Failing tests: inserting Love card sets `cards[3]`/bit 0x1 not `cards[0]`; insert at x=29 y=12 → lethal damage, no bit; all four → FinalScreen reachable; stats panel renders card/marks rows.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement (rewire the stub at `overworld.py:524-526`; delete forced-order code in `final.py`).
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: exodus machine insert flow and win path`

---

# Phase 2 — Core turn engine & world systems

## Task 4: endTurn tick — submorsels, per-member food/gold, regen

**Files:**
- Modify: `py_exodus/entities/party.py:378-397,132-133`, `py_exodus/entities/character.py:160-161`, `py_exodus/screens/overworld.py:807-814,1024-1034`, `py_exodus/screens/town.py`, `py_exodus/screens/shrine.py:94-122` (gold source)
- Test: `tests/test_turn_tick.py` (new)
- Java truth: `exodus/Party.java:592-639`, `SaveGame.java:308-310,390-392`

Java stores food and gold **per member** (`CharacterRecord`). Python has a party pool plus dead per-member fields. Switch consumption and crediting to per-member (Character already has `food`/`gold` fields — delete the party-level pools or keep them as derived sums for the HUD). Tick mechanics per move: `submorsels -= 40` on Sosaria/Exodus maps, `-= 10` in towns; crossing 0 → reset 400, `food -= 1`, then each living member: poisoned → 1 dmg, else +1 HP (cap max) and +1 mana (+2 for Druid, extra only for Druid on the map-level check), mana only if alive and not disabled; food ≤ 0 → 2 dmg per member. Ship repair belongs to Task 6.

- [ ] Step 1: Failing tests: moves tick submorsels (4 moves in town = 1 food unit decrement... actually 40 submorsels/move → food −1 every 10 moves in towns, every 1 per 400 main-map moves as in Java); poisoned member takes tick damage instead of heal; druid gains 2 mana; per-member gold spent by Task 8 vendors (assert `member.gold` drops, pool unaffected).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement `Party.end_turn(surface: bool)` consumed by every screen's turn advance; wire per-member model through shop/shrine/food code paths.
- [ ] Step 4: full pytest → pass
- [ ] Step 5: Commit `parity: per-member food/gold and endTurn tick`

## Task 5: Tile effects, tile speeds, energy-field passage

**Files:**
- Create: `py_exodus/world/tile_effects.py`, `tests/test_tile_effects.py`
- Modify: `py_exodus/world/dungeon.py:705-723,730-750`, `py_exodus/screens/overworld.py`, `py_exodus/ui/renderer.py:63-65`, `py_exodus/assets.py` (expose rule speed), `py_exodus/entities/party.py` or Task 4 module for slowed movement
- Java truth: `exodus/Party.java:279-306,342-368` (applyEffect), `exodus/GameScreen.java:716-722` (per-turn rule effect), `exodus/Constants.java:137-143` + `exodus/Context.java:215-240` (slowedByTile), `objects/BaseMap.java:719-744` (canAvatarMoveOn / dispelable)

Implements screens-audit #5, world-audit #3/#4/#5/#6: (a) per-turn tile effects — POISON/POISONFIELD: 1-in-5 per member → poisoned; FIRE/LAVA: 50% × 16+rand(32) dmg unless Mark of Fire; GREMLINS: 50% per member food −2; (b) tile speeds — swamp 1/8, brush/hills 1/4, poison/fire/lava/energy 1/2 chance the move consumes a turn without moving; (c) `dispelable` (energy field) tiles passable only when some member has `marks[3]` (Mark of Force); for dungeons Java blocks only WALL + FIELD_ENERGY (without Force) and applies POISONFIELD/LAVA on FIELD_POISON/FIELD_FIRE — replace Python's current dungeon block set and add field application; (d) pit trap per world-audit #7: "Pit!", LAVA-effect to each member, tile cleared to NOTHING, **no level change** (drop the invented z+1 and flat 25).

- [ ] Step 1: Failing tests listed per row above (e.g., Mark of Fire member stands on lava 100 turns → no damage; slow-tile move consumes turn without displacement).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement `tile_effects.py` + movement integration.
- [ ] Step 4: pytest `tests/test_tile_effects.py tests/test_dungeon_mechanics.py` → pass
- [ ] Step 5: Commit `parity: overworld and dungeon tile effects and speeds`

## Task 6: Ship hull lifecycle, boarding parity, ship facing movement

**Files:**
- Modify: `py_exodus/screens/overworld.py:324-353,784-824,484-503` (N fixed here per Task 9? no — N stays), `py_exodus/entities/party.py`, `py_exodus/ui/stats_panel.py` (hull display parity check)
- Test: `tests/test_ship.py` (new)
- Java truth: `exodus/GameScreen.java:945-979` (board), `1181-1197` (checkHullIntegrity), `461-529` (facing), `exodus/Party.java:633-638` (repair), `exodus/Context.java:242-246` (damageShip)

(a) hull: damaged where Java damages it (collision with blocking creatures/whirlpool etc. — port `Context.damageShip` call sites), sinks at ≤ 0 ("Thy ship sinks!" → killAll → party death via Task 2), passive repair 1-in-4 per turn on Sosaria (from Task 4's tick), boarding a *fresh* frigate resets hull to 50; (b) boarding requires the transport **exactly on the party's tile** (no Chebyshev-1); B with nothing boardable → "Board What?" / B while already mounted → "Board: Can't!"; no auto-mounting a horse that isn't there (commands-audit F3); (c) facing: on a ship, an arrow first *turns* the ship (turn consumed, no move); second press moves. Horses do not need facing (Java).

- [ ] Step 1: Failing tests per behavior (sink path goes through Task 2's game over).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: ship hull, boarding adjacency, sailing facing`

---

# Phase 3 — Vendors

## Task 7: Vendor framework + food/tavern/oracle/horse

**Files:**
- Create: `py_exodus/screens/vendor_dialog.py`, `tests/test_vendor_flows.py`
- Modify: `py_exodus/screens/town.py:370-570` (replace generic menu), `py_exodus/entities/party.py` (per-member gold from Task 4)
- Java truth: `vendor/BaseVendor.java, FoodVendor.java, TavernService.java, OracleService.java, HorseService.java`

Framework: per-class dialog state machines keyed by `InventoryType` (fixes root cause of the vendor CRITICALs), loop until "bye" ("anything else?" prompts), charge `member.gold` not party gold, quantity prompt when gold > 2×price else "Take it?"; full Java message strings ("You have not the funds for even one!", "How many would you like?", multi-pack "I fear you have not the funds...", FoodVendor's "You can only afford N packs.", Oracle 0-offering rhyme "And so the sage said unto thee...", horse: spawn an actual horse creature at the vendor and board it (no permanent flag), insufficient-gold per-vendor strings). Tavern: food credited to the member's *consumed* food field, 1gp payment → silent FAREWELL, "It seems that you have not the gold. Good Day!".

- [ ] Step 1: Failing tests: FOOD item purchasable (choice-keyed bug), packs of 25 × count, horse purchase spawns a boardable creature, oracle offering 0 → rhyme string, member purse charged.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement framework + the four vendor classes (read Java files first).
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: vendor framework, food/tavern/oracle/horse`

## Task 8: Armor/Weapon/Guild + Healer

**Files:**
- Modify: `py_exodus/screens/vendor_dialog.py` (Task 7), `py_exodus/screens/town.py:551-562`
- Test: `tests/test_vendor_flows.py` (extend)
- Java truth: `vendor/ArmorVendor.java:46-102, WeaponVendor.java:48-79, GuildVendor.java, HealerService.java:44-158, exodus/Party.java:381-433` (pm.heal)

(a) sell flow ("Buy or Sell?" → catalog at half price, "I will give you %dgp each.", "You don't have that many swine!"); (b) full catalog — remove `town.py:499` `items[:6]` truncation; (c) Guild strings ("What? Can't pay! Buzz off swine!"); (d) Healer: per-class "Who is in need?" member selection; need-checks from `Party.heal` — CURE only when POISONED, FULLHEAL rejected when DEAD/full HP, RESURRECT only when DEAD (sets hp **1**, not full), RECALL only when ASH (hp 1), `wis -= 5` unclamped; **no charge when the heal returns false** (Java `HealerService.java:58-64`); blood donation (health ≥ 400 and declined help → offer −100 blood, "Thou art a great help. We are in dire need!").

- [ ] Step 1: Failing tests per behavior (resurrect sets hp=1; refusing a non-applicable heal charges nothing).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement per Java.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: sell flow, full catalogs, healer need-checks`

---

# Phase 4 — Commands

## Task 9: Overworld/town command parity (B done in 6; ship in 6)

**Files:**
- Modify: `py_exodus/screens/overworld.py:295-307,386-398,400-447,484-503,678-680,743-755`, `py_exodus/screens/town.py:139-148,153-154,166,572-602,679-726,884-896`, `py_exodus/screens/overworld.py:222-228`
- Test: `tests/test_command_parity.py` (new)
- Java truth: `exodus/GameScreen.java:538-597,1089-1100`, `exodus/SecondaryInputProcessor.java:152-277,522-577`

(a) **E in town** (missing entirely) + whirlpool trigger on *step-in* (world-audit #13: engulf at distance ≤1 of a whirlpool → 4 log lines, transport→FOOT, ship lost, party → Ambrosia (32,54); Ambrosia→Sosaria exit portal uses fixed (1,1) not randomized); (b) **X** = dismount/set FOOT everywhere, never exits a town (town exit is border-walk only); (c) **J** prompts member 1–4 → `pool_gold(index)` merges members' gold into that member, party pool untouched (commands-audit F6 + screens-audit #21); (d) **N** (negate time) = consumes first member's powder → quickness aura 6 turns (Task 11's Aura), "Stop time with a powder!"/"None!"; town must check powder before printing "None owned!"; remove the invented 15-turn foe-freeze; (e) **L** on the overworld/dungeon = OPEN (direction prompt, "Opened!"/"Can't!") — keep the invented Look on no other key... Java has no Look; remove `_look` mapping; (f) **U** unlocks only with `member.keys > 0` and decrements; (g) **G** direction-targeting (Task 1); (h) **S** in town = real member prompt + `searchLocation` flow (labels etc.), not the "cobblestones" stub; **T** on the overworld routes to the real talk flow (stub removed), Java's pass-through rule = `signs` only (drop Python's tile 36–57 counter widening); (i) **Y** = member prompt + word prompt; "EVOCARE" adjacent to snake tiles replaces them with water **only if `marks[2]` (Mark of Snake)**, else "No effect."; "What?" for unknown; (j) **H** hand dialog transfers any unequipped weapon **or armor**.

- [ ] Step 1: Failing tests, one per command row (use the prompt engine from `ui/text_log.py`).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: overworld and town command semantics`

## Task 10: Dungeon command surface + movement

**Files:**
- Modify: `py_exodus/screens/dungeon_screen.py:111-153`, `py_exodus/world/dungeon.py:864,851-886`, `py_exodus/screens/overworld.py:1183-1191` (save restriction)
- Test: `tests/test_dungeon_commands.py` (new)
- Java truth: `exodus/DungeonScreen.java:859-1052,1012-1043,1087-1092`, `exodus/GameScreen.java:557-563`

(a) add R (ready weapon), W (wear armor), M (modify order), V (music), P (peer gem/minimap where Java has it), Q (save — allowed in dungeons; and restrict overworld save to Sosaria only, "Cannot save here!"); (b) DOWN arrow = one step *backward* in current facing (with wrap), not a 180° turn; (c) torch = boolean toggle (lit torch press extinguishes, no consumption), remove the rounds/dim model; (d) unhandled keys in the dungeon consume a turn (Java falls through to finishTurn) — apply globally where Java does (overworld too); (e) dungeon D/K ladder bounds follow Java's clamp behavior (world-audit #23 — Java clamps at 8; replicate the clamping semantics).

- [ ] Step 1: Failing tests: R/W usable in dungeon; Q saves with "Saved Game."; DOWN backsteps z/facing state; torch toggles off without consuming inventory; overworld save on Ambrosia refused.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: dungeon commands and movement keys`

---

# Phase 5 — Combat & magic

## Task 11: Aura system + spell mechanics

**Files:**
- Create: `py_exodus/aura.py`, `tests/test_aura.py`
- Modify: `py_exodus/combat/magic.py` (per-spell fixes below), `py_exodus/combat/arena.py` (quickness turn skip `CombatScreen.finishTurn:481`), `py_exodus/entities/party.py` (aura carrier), `py_exodus/screens/overworld.py:484-503`
- Java truth: `objects/Aura.java`, `exodus/SpellUtil.java` (whole file), `exodus/Constants.java:693-762` (Spell enum + getCastables)

Aura: `AuraType {QUICKNESS, NEGATE, PROTECTION, JINX}`, `set(type, turns)`, decrement per turn (Task 4 tick; combat rounds), NEGATE blocks all casting ("Spell is negated!", mana unspent), quickness skips monster turns for N rounds. Spell fixes (combat-audit Part 1 table, all Java lines cited there): SANCTU heal 75–99 (`75 + rand(256) % 25`); MENTAR/NOXUM/DAG_MENTAR remove the `max` floor (Java falls through to `maxDamage` when `minDamage >= maxDamage`); ZXKUQYB ports Java's bug — `rand(3)==0 → 255`, else hp ≤ 23 → 15, else **0** damage; PONTORI/REPOND: once-per-combat free, per-creature turn chance 50/65/80/100% by caster level, kills only `tile=="orc"` (REPOND) / `undead` (PONTORI), awards XP; PABULUM food 5–9 all members; LORUM/LUMINAE set the boolean torch flag (with Task 10's torch model), SOMINAE loses its invented effect; ALTAIR quickness **5**; DAG_ACRON castable on the world map only (`constants.py:253` mask 0x03 → 0x01) — remove the combat special-case and teleport; APPAR_UNEM: direction prompt then opens the chest **at the player's tile** (`disarmed=True` → Task 1 pipeline), gold `rand(50,200)`;
combat key **N** (negate time in combat, `CombatScreen.negateTime:503-514`): consumes powder → QUICKNESS 6; dungeon spells to full parity — DOR/SUR_ACRON level ±1 + random valid-spot relocation (32 tries) + climb-out exit at level −1, LIB_REC random teleport *within* the level, SEQUITU leaves the dungeon (screen transition + label log), VIEDA activates the peer-gem view input, spell projectiles pass over all tiles (resolve the `resolver.py:152-159` wall-stop), free-spell check ordered after the mana check.

- [ ] Step 1: Failing tests: one per spell row for the changed rows (assert the exact dice/flags above); NEGATE blocks casting without spending mana.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest `tests/test_aura.py tests/test_magic_system.py tests/test_spell_mechanics.py` → pass
- [ ] Step 5: Commit `parity: aura system and spell mechanics`

## Task 12: Combat mechanics parity

**Files:**
- Modify: `py_exodus/combat/arena.py:256-282,410-455,440-480,457-569,661-759,793-823,865-908`, `py_exodus/combat/resolver.py:52-159,164-299`, `py_exodus/screens/combat_screen.py`, `py_exodus/screens/overworld.py:1142-1154`
- Test: `tests/test_combat_parity.py` (new)
- Java truth: `exodus/CombatScreen.java` (creatureAction 696-713, rangedAttackAt 646-677, finishTurn 481, endCombat 562-589, moveCreature 886-957), `exodus/Context.java:303-326` (getCombatMap), `util/Utils.java:50-52,592-602,299-312`

(a) ranged attack probability — 26% teleport, then 34% ranged **regardless of distance**, else melee (advance if dist > 1); ranged with `rangedhittile="fire"/"energy"` deals damage twice (Java's double `dealDamage`); (b) arena map selection via tile-rule combat maps + swim/sail variants (`Context.getCombatMap`; sea creatures on land must not force BOTH_SHIPS); (c) damage rolls `rand.nextInt(high-low)+low` (high **exclusive**) — player damage, steals (food 0–9, gold 0–39), everywhere `getRandomBetween` appears; (d) monster melee cannot poison (remove `resolve_monster_attack:264-267`), no per-round combat poison tick (`arena.py:855-863` removal), monster damage may be 0 (drop `max(1,_)`); (e) weapon loss on ranged attacks (`lose`/`losewhenranged`, "Last One!"); (f) **flee removed** (Python's `f` key and FLEE action are deleted — Java commented it out) and off-edge moves are blocked, not escapes; (g) XP for **every** creature death caused by a player including spells, capped 9999; (h) victory chest at the *creature's* overworld tile, walkability-checked; (i) Castle of Death (EXODUS map) rules: non-exotic player attack refused (NEGATIVE_EFFECT, turn passes), melee/ranged creature attacks auto-hit exotic-armor-less defenders; (j) monster count: guards = party.size×2 (all members incl. dead count), else `rand(min(8,size*2))+1`; (k) monster movement randomizes among valid toward-directions (port `getRandomValidDirection`), can never step off-map (edge = blocked, not fled).

- [ ] Step 1: Failing tests per row (e.g., stat the ranged-fire double damage over N trials ranges; flee key asserts nothing/unknown-key).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest `tests/test_combat_parity.py tests/test_combat_arena.py` → pass
- [ ] Step 5: Commit `parity: combat mechanics`

---

# Phase 6 — Dungeon specials & extras

## Task 13: Dungeon wandering monsters, doors, fields, gremlins, chests

**Files:**
- Modify: `py_exodus/world/dungeon.py:1230-1275,1262-1272,705-750,770-785,1184-1213` (plus Task 5 overlap)
- Test: `tests/test_dungeon_specials.py` (new)
- Java truth: `exodus/DungeonScreen.java:1054-1103,1255-1330,1140-1160`, `objects/CreatureSet.java:42-56`

(a) wandering monsters: ≤ 2 per level, spawn `rand(32 - level*2)==0` per relevant tick, they path toward the avatar, battle triggers on contact, cleaned up on level change (replacing the direct-ambush roll); (a2) **remove orbs entirely** per Kept-Divergence #2 — delete the +5-stat grant/damage block (`dungeon.py:1134-1168`) AND the "You find a Magical Orb..." prompt line; search results never mention orbs; (b) DOOR/LOCKED_DOOR/SECRET_DOOR tiles are **passable** in dungeons (Python currently blocks them); (c) creature pool: creatures without `level` attr default to 0 and are excluded (Fighter/Wizard), remove the `defs.py:99` default-1 and the fallback table's mismatched levels; (d) gremlins steal 2 food at 50% *per member*; (e) dungeon chest uses Task 1's pipeline (10–66 gold, dex-evadable traps, APPAR_UNEM disarm path actually reachable). Note: field application/pit were set in Task 5.

- [ ] Step 1: Failing tests per row.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: dungeon wandering monsters and special tiles`

---

# Phase 7 — Screens, flow, characters

## Task 14: Character creation, Lord British, roster, shrine gold

**Files:**
- Modify: `py_exodus/screens/roster_screen.py:301-398,267-280`, `py_exodus/entities/character.py:309-335,343-391`, `py_exodus/screens/town.py:340-368`, `py_exodus/screens/shrine.py:94-122`, `py_exodus/save_system.py:97-102`
- Test: `tests/test_creation_parity.py` (new)
- Java truth: `exodus/ManagePartyScreen.java:165-199,355-367`, `exodus/SecondaryInputProcessor.java:179-202`, `exodus/ShrineScreen.java:200-257`, `objects/SaveGame.java:394-433`, `objects/Roster.java`

(a) creation: per-stat allocation 5–25, total ≤ 50 enforced (rejection on over-budget), name up to 16 chars, start `health/food/gold = 150`, portrait index, NO starting weapon/armor — wire the existing unused `validate_creation`; (b) Lord British: **no resurrection** (Java's loop is commented out) — only `meetLordBritish()` level-advance of the talking member with the "Welcome my child../Experience more!" flow; (c) remove-from-party returns the member to a roster slot; (d) shrine donation debits the chosen member's gold; insufficient → "You cannot cheat the gods!" (screen stays); 0 → "Begone then!" then exit; success message just "Shazam!"; (e) Mark-of-Kings gate: requires the mark at `expLvl >= 5` (Java `SaveGame.java:394-411`, level 6+ — Python currently blocks level 5); (f) save/load: `max_mp` must be recomputed on load, not deserialized (delete the serialized field round-trip); (g) fix the binary parser's marks decode order to [Kings, Fire, Snake, Force] (`save_system.py:97-102` currently swaps Force/Snake); (h) default new-game start position (45, 19) (`SaveGame.java:164-169` — reconcile the three inconsistent Python values).

- [ ] Step 1: Failing tests per row (creation budget rejects 6×25; LB does not resurrect a DEAD member).
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: character creation, roster, shrine, level gate, load semantics`

## Task 15: Book of Lore

**Files:**
- Modify: `py_exodus/screens/book.py` (repurpose), `py_exodus/screens/start.py` (Book button), `py_exodus/screens/base.py`
- Test: `tests/test_book_of_lore.py` (new)
- Java truth: `exodus/BookScreen.java:53,150-174` (loads `/assets/data/ultima3.txt`, two-column paging), `exodus/BaseScreen.java:86-97`

Replace the spellbook browser with the Book of Lore: read `assets/data/ultima3.txt` (already present in `py-exodus/assets/data/`), render as a paged text view from the title screen and each game screen. Keep the spell reference as a section or drop it — it is an invention; keep only if it fits after the lore text as Python-only content (decision: keep, appended last, it is useful and harmless).

- [ ] Step 1: Failing test: BookScreen loads ultima3.txt, total page count stable, paging forward/backward works.
- [ ] Step 2: pytest → fails
- [ ] Step 3: Implement.
- [ ] Step 4: pytest → pass
- [ ] Step 5: Commit `parity: book of lore from ultima3.txt`

---

## Deliberately out of scope (flagged, not fixed)

- **Java binary save/roster interop** (`party.sav`/80-byte records) — Python saves JSON; full interop is a separate project. Task 14 fixes only the marks-order bug in the existing `SaveSystem` binary loader.
- Peer-gem image rendering, telescope, idle 20-second auto-pass timer, prompt-cancel niceties, FOV edge wrap — minor/cosmetic; not worth regression risk now.

## Suggested execution order

Tasks 1–3 (blockers) → 4–6 (core systems; 4 before 7) → 7–8 (vendors; depend on 4's per-member gold) → 9–10 (commands; 9 depends on 1's chest pipeline and 11's aura for N — implement N's aura behind the Task 11 interface, so 9 before 11 is fine with a stub) → 11–12 (combat) → 13 (dungeon specials) → 14–15 (flow/screens). Tasks are individually committed; the suite must stay green after each.
