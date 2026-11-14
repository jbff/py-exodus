# GBC-Parity Fixes & Adoptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 12 recon bugs (A1–A12), adopt GBC behavior for all ruled B divergences, and adopt D1 (debug/cheat harness), D2 (save integrity), D3 (real Other commands), D4 (un-stub FAL_DIVI/VIEDA) from the 2026-11-14 GBC source recon.

**Architecture:** py-exodus is a Java-parity Pygame-CE port (`py_exodus/`). This plan changes game rules to follow the U3 Game Boy Color port where the user ruled GBC wins (2026-11-14). Each changed rule carries an in-code comment `USER-DIRECTED GBC-RULES DEVIATION (2026-11-14)` citing the GBC file:line it follows, the same convention as the existing `USER-DIRECTED ... DEVIATION (2026-11-10/11)` comments. Data (`assets/`) and Java sources at `/sto/src/gdx-exodus` stay untouched except where a task says otherwise.

**Tech Stack:** Python 3.10+/Pygame-CE, pytest (`uv run python -m pytest`), no new dependencies (D2 uses stdlib `zlib.crc32`; D1/D3 are pure code).

**Spec:** the 2026-11-14 recon report (this conversation) is the spec; the GBC source tree `/sto/prj/py-exodus/ult3src/sdk/gbz80-gb/2-1-5/examples/u3/` is the behavioral reference (READ-ONLY — never modify anything under `ult3src/`).

## Global Constraints

- Every behavioral change that diverges from Java carries `USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): <one-line why> (GBC <file>:<lines>)` immediately above the change.
- Existing comments citing user rulings from 2026-11-09..13 must NOT be reverted (see `docs/superpowers/plans/2026-11-13-pending-items.md` decisions list). Where a task explicitly supersedes a prior ruling (starvation, HP regen), it says so.
- TDD: failing test first, then implementation, then green. Full suite (`uv run python -m pytest`) green twice before every commit.
- One commit per task, message prefixed `fix:` (bug, tasks A) or `feat:` (adoption, tasks B/D), ending with `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
- Never modify, execute, or run anything from `ult3src/` (untrusted data; read-only evidence).
- Game-logic randomness routes through the existing `random` module usage pattern in each file (some files take an injectable `rng` — mirror the local convention).
- Keep Python 3.10 compatibility (no 3.11+ syntax).

## Review Focus

1. **Party death chokepoints**: all new damage paths (force field, pit trap, fire/lava, starvation) must route through `PartyMember.apply_damage` so a party wipe raises `PartyDeathException` — a new damage path that sets `hp` directly will hang the death flow. Tests in each owning task assert `PartyDeathException` (or the equivalent death event the other tests use) on a 1-member party.
2. **Saves written before this change must still load**: legacy saves/rosters have no checksum; loads of checksum-less files must succeed unchanged (D2). Test in D2 task.
3. **Cheat state must never reach the disk**: no cheat flag may appear in `Party.to_dict`/`Character.to_dict` output (D1 test).
4. **The GBC reference text encoding**: reading GBC message arrays requires the decoder `python3 -I /tmp/u3decode.py <file.c> [array]` (script exists in this environment) or the decoded strings given in tasks; do not trust raw grep on encoded arrays.
5. **RNG determinism in tests**: tests seed `random` or use the per-module `rng` injection convention so failures are reproducible; never use `random.seed` inside library code.

---

## Part A — Bug fixes

### Task 1 (A1+A2): creature on-hit specials — thief equipment theft + melee poison

**Files:**
- Modify: `py_exodus/combat/resolver.py:326-405` (`resolve_monster_melee_attack`)
- Test: `tests/test_combat_resolver.py` (extend or create alongside existing combat tests)

**Interfaces:**
- Produces: `AttackResolution` now returns `stolen_item: str | None` (`"weapon" | "armor" | None`) and sets `poisoned=True` for 25%-rolled poison hits. `AttackResult`/`AttackResolution` field additions only — no signature changes.

GBC truth: thief (tile `thief`) steals armor (1-in-8 slot, if owned) or weapon (1-in-16) 50/50 (`battle3.c:279-301`). Man-o-war/pincher/balron poison on any hit, 25% (`make_rnd(0)&3==0`, `battle3.c:267-277`).

- [ ] **Step 1: Write failing tests** — thief case: party member with armor indexes and weapon indexes; monkeypatch `random.randrange` sequence or run 200 seeded trials and assert at least one `stolen_item in ("weapon","armor")` and that the owning slot was decremented. Pincher case: assert `poisoned` is True in ~25% of 200 seeded trials and that a poisoned hit sets `Status.POISONED` on the target when it survives. Assert food/gold theft paths still behave (regression).
- [ ] **Step 2: Run** `uv run python -m pytest tests/test_combat_resolver.py -v` — expected FAIL (no `stolen_item`/`poisoned` behavior).
- [ ] **Step 3: Implement** in `resolve_monster_melee_attack`: after the applied-hit block, keep Java food/gold branches; add the GBC branches above them with the deviation comment: `steals=="equipment"` → pick armor 1-in-8: decrement one owned armor stack (lowest non-empty index first) then weapon 1-in-16 similarly (choose order by the 50/50 `random.randrange(2)`); poison: if `getattr(monster,"poisons",False)` and `random.randrange(4)==0` → set target status POISONED (only if target alive and not already poisoned) + `poisoned=True` result field.
- [ ] **Step 4: Run** full test file — PASS.
- [ ] **Step 5: Commit** `fix: thief equipment theft and melee poison (GBC battle3.c:267-301)`.

### Task 2 (A3): encounter size follows GBC rules

**Files:**
- Modify: `py_exodus/combat/arena.py:286-316` (`_spawn_monsters`)
- Test: `tests/test_combat_arena.py` (extend)

**Interfaces:** no signature change; behavior: guard → 8; battle on the EXODUS map (`context_map_id == assets.MAP_NAME_TO_ID["EXODUS"]`) → 8; otherwise `random.randint(1, 8)`; all still clamped to `max_slots`. Party size no longer affects count; the `encounterSize` XML attr stays parsed-but-unused (dead data in Java AND GBC) — add a comment saying so.

- [ ] **Step 1: Failing test** — 9-member party battle vs non-guard: over 200 seeded runs every `count` ∈ 1..8; party size has no effect (same distribution for size 1 and 4 — assert observed ranges, not seeds). Guard battle → always 8 (clamped by available `monster_starts`; use a fixture with ≥8 starts). Exodus-map battle → 8.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with `USER-DIRECTED GBC-RULES DEVIATION (2026-11-14)` comment citing `funcs5.c:1573-1608` (note `inexodus≡EXODUS map`).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `fix: GBC encounter-size rules (funcs5.c:1573-1608)`.

### Task 3 (B-combat): rolled monster HP, LB/guard attack immunity, terrain damage bonus

**Files:**
- Modify: `py_exodus/combat/arena.py` (`CombatMonster.__init__`), `py_exodus/combat/resolver.py` (`resolve_monster_melee_attack` damage + a new context helper)
- Test: `tests/test_combat_arena.py`, `tests/test_combat_resolver.py`

**Interfaces:**
- Produces: `CombatMonster.hp`/`max_hp` are now per-battle rolls; helper `monster_damage_bonus(context_map_id: int | None) -> int` exported from `resolver.py` (used in tests); player attack resolution returns damage 0 vs guard/`lord_british` tiles.

GBC truth: HP = `make_rnd(cap) | 0x0F` per monster (floor 15, cap = creature basehp here — creatures.xml `basehp` is the per-tile cap; comment this mapping decision) (`funcs5.c:1546-1554`). Player attacks deal 0 damage vs guard tile 0x18 (hard mode only in GBC; we exempt normal guards too — GBC's `extragame` does not exist here, decision documented) and vs Lord British (`battle.c:646-648`). Monster damage gets `+10` dungeon, `+30` world-surface (Sosaria/Ambrosia), `+20` towns/castles/other interiors (`battle3.c:337-350`; GBC map-id table maps to py `MAP_NAME_TO_ID`).

- [ ] **Step 1: Failing tests** — monster HP: 200 seeded spawns show all HP ≥15, never > `basehp|0x0F`, and distribution varies per instance (not all equal). Immunity: player-vs-guard attack does 0 damage and the monster survives. Bonus: `monster_damage_bonus(EXODUS)`... assert 10 for a dungeon map id, 30 for `SOSARIA`/`AMBROSIA`, 20 for a town map id.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** — in `CombatMonster.__init__`: `self.hp = randrange(0, self.basehp + 1) | 0x0F` (keep `definition.hp` override path intact when it is set explicitly — check existing tests). Melee damage adds the bonus. Player-attack resolution: if target tile is `"guard"` or `"lord_british"` → damage 0 with message (no kill).
- [ ] **Step 4: Run** full suite — PASS (expect test-count to grow).
- [ ] **Step 5: Commit** `feat: GBC rolled HP, guard/LB immunity, terrain damage bonus`.

### Task 4 (B-combat): no-LOS magic poke + cannonfire in ship battles

**Files:**
- Modify: `py_exodus/combat/resolver.py` (`resolve_monster_ranged_attack` and the ship-battle branch)
- Test: `tests/test_combat_resolver.py`

**Interfaces:** `resolve_monster_ranged_attack(...)` accepts the same args plus optional `context_map_id`; when the monster has a magic attribute (creature tile in `{"serpent","man-o-war","wizard","daemon","dragon","balron"}` — mirror `creatures.xml` tile names) and no target is adjacent, a 34% branch (`random.randrange(193) & 0x80` semantics == `random.randrange(193) >= 129`… implement as `random.randrange(3) != 0 | GBC make_rnd(0xC1)&0x80` — use `random.randrange(193) & 0x80 == 0` for fail) attacks a RANDOM living member directly with the normal single-target damage roll, message "Magic Blast!" — no LOS check, no bolt trace. In ship-battle context (party transport SHIP at battle start — mirror how the arena already encodes battle-map context; add a `ship_battle: bool = False` kwarg), the monster ranged branch instead deals party-wide damage `random.randrange(78)` to every living member once (message "Cannonball barrage!").

- [ ] **Step 1: Failing tests** — adjacency blocks the bolt path into the poke branch statistically; ship_battle context damages all members; non-magic creatures unaffected; adjacent magic creatures unaffected.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with deviation comment citing `battle3.c:856-866` and `battle3.c:507-536`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: GBC magic poke and cannonfire party damage`.

### Task 5 (A4): fountain typing at load

**Files:**
- Modify: `py_exodus/world/map.py:86-99` (`DungeonTile.get_tile_by_value`)
- Test: `tests/test_map_loader.py` or the dungeon map test file — locate with `grep -rn "get_tile_by_value\|FOUNTAIN_HEAL" tests/`

**Interfaces:** no signature change; behavior: a `.ult` dungeon byte `0x02` previously always became `FOUNTAIN_HEAL`; now `FOUNTAIN_HEAL` and the other fountain types are distinguished by the *x coordinate of the tile* per GBC (`dungfunc.c:1277-1310`): `x & 3` → 0=`FOUNTAIN_POISON` (status only, no damage), 1=`FOUNTAIN_HEAL`, 2=`FOUNTAIN_ACID` (25 dmg, can kill), 3=`FOUNTAIN_CURE`. **The byte→enum mapping is in the loader, but x is not available there** — so the mapping returns a new neutral `FOUNTAIN` placeholder enum? NO — keep the API: change `get_tile_by_value` to return `FOUNTAIN_UNTYPED` (new member) and let `DungeonWorld` (or wherever `dmap` is built — implementer locates the post-load pass with `grep -n "get_tile_by_value" py_exodus/`) re-type each fountain to its `x & 3` enum immediately after load. `drink_fountain` (`dungeon.py:1741+`) already implements the four effects; verify the POISON branch poisons only (no damage) and the ACID branch does exactly 25 (`dungeon.py` currently applies `16+rand(32)` — change acid to flat 25 per GBC) and can kill.

- [ ] **Step 1: Failing tests** — build a small dungeon map fixture with two 0x02 tiles at x=3 and x=4; after load they are `FOUNTAIN_ACID`... assert per the x&3 table; drink tests: acid = exactly 25 damage to the drinking member (can kill), poison = status POISONED only.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** loader change + post-load re-typing pass in `DungeonWorld.__init__`/dmap builder.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `fix: fountain typing by x coordinate (GBC dungfunc.c:1277-1310)`.

### Task 6 (A5): mark typing by tile x-coordinate

**Files:**
- Modify: `py_exodus/world/dungeon.py:1870-1890` (generic `MARK` branch)
- Test: dungeon marks test file (`grep -rn "Mark of" tests/`)

**Interfaces:** no change. Generic MARK type = `x & 3`: 0=Force, 1=Fire, 2=Snake, 3=Kings (`dungfunc.c:1355-1371`), replacing `self.z % 4`.

- [ ] **Step 1: Failing test** — two `MARK` tiles (0x05) on the SAME level at x=6 and x=15 grant different marks (Snake, Kings); a mark at x=0 grants Force on every level (depth-independence).
- [ ] **Step 2: Run** — FAIL. **Step 3:** one-line change + comment. **Step 4:** PASS. **Step 5:** Commit `fix: mark typing by tile x (GBC dungfunc.c:1355-1371)`.

### Task 7 (B-dungeon): pit trap + gremlins GBC rules

**Files:**
- Modify: `py_exodus/world/dungeon.py:1303-1370` (pit + gremlin branches)
- Test: dungeon effects test file

**Interfaces:** no change.

GBC: pit = dex evade first (reuse the chest evade convention: `dex + 25 >= randrange(100)` — document that GBC `testplayerdex` maps to the port's existing evade roll); on fail, every LIVING member takes `randint(0, self.z + 1) << 3` damage (`dungfunc.c:1190-1232` — rnd(dunglevel+1)<<3), tile cleared (kept). Gremlins = ONE random living member loses 100 food (floor 0), tile cleared (`dungfunc.c:1177-1189`) — **supersedes** the Java −2-each rule.

- [ ] **Step 1: Failing tests** — high-dex member evades pit (no damage, tile cleared); zero-dex member fails ~always: all living members damaged by `<= (z+1)*8`; gremlins: exactly one member loses food (amount 100, floored at 0), others untouched.
- [ ] **Step 2: Run** — FAIL. **Step 3:** implement both with the deviation comment. **Step 4:** PASS. **Step 5:** Commit `feat: GBC pit-trap and gremlin rules`.

### Task 8 (A12): chest Gas trap poisons the party

**Files:**
- Modify: `py_exodus/world/chests.py:88-108` (`_chest_trap`)
- Test: chest test file

**Interfaces:** no change. GBC Gas trap = poison every living member; Bomb trap = area blast — implement Gas per GBC (`menucmd.c:1077-1147`); **skip Bomb** (GBC's bomb is cannonfire reuse; py has no party-wide projectile path — record in the deviation comment that Bomb is deferred with the pending-items ledger).

- [ ] **Step 1: Failing test** — Gas trap: all living members get `Status.POISONED`; Acid still damages only the opener.
- [ ] **Step 2: Run** — FAIL. **Step 3:** one-line branch change + comment. **Step 4:** PASS. **Step 5:** Commit `fix: Gas trap poisons whole party (GBC menucmd.c:1077-1147)`.

### Task 9 (A7): Unlock consumes a key

**Files:**
- Modify: `py_exodus/world/doors.py:41-53` (`unlock_door`), callers found via `grep -rn "unlock_door" py_exodus/`
- Test: door test file

**Interfaces:** `unlock_door(game_map, x, y, party) -> bool` — new `party` arg; requires some member holding keys (GBC uses the acting member's `keys` — the active member; caller passes the member, decide: pass `member: PartyMember`); decrements `keys`. Returns False (and changes nothing) at 0 keys. Message "You need a key!" is the caller's concern; add it in the screen callers (town/overworld/dungeon `U` handlers).

- [ ] **Step 1: Failing tests** — unlock with keys>0 decrements to keys−1 and converts tile; with 0 keys tile unchanged, returns False.
- [ ] **Step 2: Run** — FAIL. **Step 3:** implement + update callers' signatures. **Step 4:** PASS. **Step 5:** Commit `fix: Unlock consumes a key (GBC menucmd2.c:1595-1650)`.

### Task 10 (A6): JOIN GOLD clamps to 9999

**Files:**
- Modify: `py_exodus/entities/party.py:555-570` (`pool_gold`)
- Test: party test file

**Interfaces:** no change; behavior: receiving purse clamped to 9999 (`menucmd2.c:965-987`).

- [ ] **Step 1: Failing test** — 4000+4000+2500 pooled into one member → 9999. **Step 2:** FAIL. **Step 3:** one line. **Step 4:** PASS. **Step 5:** Commit `fix: pool gold cap 9999`.

### Task 11 (A11): roster delete confirm + in-party guard

**Files:**
- Modify: `py_exodus/screens/roster_screen.py:267-274` (`_delete_selected_roster`)
- Test: roster screen test file

**Interfaces:** `DeletePrompt` behavior: first `Delete` press on a character in a party → message "In a party!" refusal; otherwise a confirm prompt (`Delete? (Y/N)`) — Y deletes, N/Esc cancels. Mirror the roster screen's existing prompt engine (`grep -n "prompt(" py_exodus/screens/roster_screen.py`).

- [ ] **Step 1: Failing tests** — simulated key events: delete without party → confirm gate; Y → deleted; N → kept; in-party member → refusal message.
- [ ] **Step 2: Run** — FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `fix: roster delete confirm and in-party guard (GBC intro.c:1455-1490)`.

### Task 12 (A8): whirlpool same-tile, ships only

**Files:**
- Modify: `py_exodus/screens/overworld.py:1359-1395` (`_check_whirlpool_engulf`)
- Test: overworld test file

**Interfaces:** no change. GBC: engulf ONLY on same-tile contact (no radius ring) and ONLY when `party.transport == SHIP` (`ult3.c:2418`, `menucmd3.c:1544-1548`). **Supersedes** the Chebyshev≤1 scan (this also closes pending-item 1). Keep Java's destination (32,54)→map 13 and the QUICKNESS aura skip.

- [ ] **Step 1: Failing tests** — foot party ON the whirlpool tile: NO engulf; ship party adjacent (Chebyshev 1): NO engulf; ship party ON the tile: engulf (transport→FOOT, map 13, position (32,54)).
- [ ] **Step 2: Run** — FAIL. **Step 3:** implement (drop the wrap-aware dx/dy; equality test) + deviation comment superseding the old scan comment.
- [ ] **Step 4:** PASS. **Step 5:** Commit `fix: whirlpool engulfs ships only on same tile`.

### Task 13 (A10): remove baked static moongate from sosaria.json

**Files:**
- Modify: `assets/maps/sosaria.json` (cell (29,15) tile 34 → 1 grass)
- Test: `tests/test_maps.py` (extend — assert no tile 34 in sosaria.json)

**Interfaces:** data change only. GBC has grass there; moongates are code-spawned. First VERIFY the port renders map tile 34 (`grep -rn "moongate" py_exodus/world/ py_exodus/screens/overworld.py | head`) — if tile 34 never renders from map data (dynamic gates only), instead delete the cell anyway and keep the test asserting the data is clean, with a comment.

- [ ] **Steps:** test asserting `34 not in flattened tiles` (FAIL), edit JSON cell (29,15) from 34→1, run, commit `fix: remove baked moongate tile from sosaria map data`.

### Task 14 (A9): card survives a wrong INSERT

**Files:**
- Modify: `py_exodus/screens/final.py:263-293` (`insert_card`)
- Test: final/insert test file

**Interfaces:** no change. GBC reads `markcard` and never decrements on a wrong panel (`menucmd3.c:959`). Move `char.cards[card_idx] -= 1` to AFTER the panel check (correct branch only).

- [ ] **Step 1: Failing test** — wrong panel: member killed AND `cards[card_idx]` still 1. Correct panel: card decremented, bit set (existing test keeps passing).
- [ ] **Step 2: Run** — FAIL. **Step 3:** reorder + comment. **Step 4:** PASS. **Step 5:** Commit `fix: wrong-card insert no longer consumes the card`.

---

## Part B — GBC-ruled behavior (all carry the 2026-11-14 deviation comment)

### Task 15: SANCTU 10–30, SANCTU_MANI 20–100, SURMANDUM 75% / ashes

**Files:**
- Modify: `py_exodus/combat/magic.py:435-472`
- Test: magic test file

**Interfaces:** no change. GBC (`menucmd.c:1337-1420`): SANCTU `randint(0,20)+10`; SANCTU_MANI `randint(0,80)+20` capped at max; SURMANDUM `random.random() < .75` success → status GOOD, hp=1; failure → status **ASHES** (py `Status.ASHES` exists? verify `grep -n "ASHES" py_exodus/constants.py` — if absent, add to the enum following the Status pattern) with message "The spell fails! …turns to ashes!".

- [ ] **Step 1: Failing tests** — heal band 10..30 over 100 seeded runs; mani band 20..100; surmandum success leaves GOOD/hp=1, failure leaves ASHES.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4:** PASS. **Step 5:** Commit `feat: GBC heal/raise dice`.

### Task 16: APPAR_UNEM 25% disarm failure

**Files:**
- Modify: `py_exodus/combat/magic.py:690-707` (the APPAR_UNEM chest branch)
- Test: magic test file

**Interfaces:** no change. GBC: `(make_rnd(0)&3)==0` → outright failure "Fail!" with no chest opening (`menucmd.c:1311-1313`); mana already spent (py spends at cast — verify order; if py refunds on `success=False`, keep the refund consistent with other failed casts).

- [ ] **Step 1: Failing test** — seeded 100 casts: ~25% return `success=False` + no chest lines. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: APPAR_UNEM 25% failure`.

### Task 17: NECORP weakens, DECORP kills, ALTAIR 10 turns

**Files:**
- Modify: `py_exodus/combat/magic.py` (`_apply_group_damage` NECORP branch; `_apply_projectile_attack` DECORP branch; ALTAIR branch at ~549)
- Test: magic test file

**Interfaces:** no change. GBC: NECORP sets every living monster `hp=5` and its `monsterpower` low (py: halve `basehp`-derived damage — decision: set `m.hp = min(m.hp, 5)` and weaken to `max(3, m.basehp // 16)`; document the py-side reading of `monsterpower` as the damage bonus used in Task 3's terrain formula) (`battle.c:1361-1373`). DECORP = guaranteed kill on hit (`battle.c:1285-1296`: `kill=1`) instead of 128–255 damage. ALTAIR `AuraType.QUICKNESS` duration **10** (`menucmd.c:1551`, supersedes both the spell's 5 and the N-powder's 6 at `overworld.py:960-966` and `combat_screen.py:186-199` — update all three call sites).

- [ ] **Step 1: Failing tests** — NECORP leaves monsters alive at hp 5; DECORP hit kills any single monster; QUICKNESS duration 10 for spell and N.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: GBC NECORP/DECORP/ALTAIR semantics`.

### Task 18: mass-kill first-strike flag

**Files:**
- Modify: `py_exodus/combat/arena.py` (battle init), `py_exodus/combat/magic.py:492-570` (PONTORI/REPOND)
- Test: magic test file

**Interfaces:** `CombatArena` gains `masskill: bool` set at battle start (`random.randrange(2) == 0`, `funcs5.c:1354-1358`); PONTORI/REPOND only operate when `arena.masskill`; then each eligible (undead / orc) living monster is killed with 75% probability, **level-independent** (`battle.c:1043-1053, 1225-1239, 821-844`).

- [ ] **Step 1: Failing tests** — masskill False → spells kill nothing; masskill True (forced) + 25 seeded trials → ~75% of eligible monsters dead, level has no effect (level 1 vs 20 same distribution).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: GBC mass-kill first-strike`.

### Task 19: moons are move-driven; stop-time freezes moons and food; rename Trammel/Felucca

**Files:**
- Modify: `py_exodus/screens/overworld.py:2027-2036` (`update`), `py_exodus/screens/overworld.py:374-380` (phase properties)
- Test: overworld test file

**Interfaces:** `moon_phase` advances ONLY in `postmove`-equivalent: every 4th consumed turn on the world surface, every 16th consumed turn otherwise (`funcs5.c:1272-1279`); `AuraType.QUICKNESS` freezes moons AND food consumption (gate in the turn hook, `funcs5.c:1276-1279`). Renaming per canon/GBC (show-by-slow, route-by-fast unchanged): the slow moon (`min(7, moon_phase//3)`) is **Felucca**, the fast (`moon_phase % 8`) is **Trammel** — swap the two property names and every label/save key that shows them (grep `trammel|felucca` across `py_exodus/`); keep saved `moon_phase` value semantics (old saves continue: the phase integer means the same thing, only display names change).

- [ ] **Step 1: Failing tests** — 4 consumed turns on surface advance fast-moon phase by exactly 1 with a fixed party; no wall-clock dependence (`update(dt)` no longer touches phases — pass dt=large and assert unchanged); QUICKNESS freezes both; a save/load round-trip preserves integer phase; property names swapped.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: move-driven moon clock, stop-time gates, moon naming`.

### Task 20: wind becalmed + forced re-roll

**Files:**
- Modify: `py_exodus/screens/overworld.py:1250-1254` (headwind check), `py_exodus/screens/overworld.py:2027-2034` (timer → move-driven)
- Test: overworld test file

**Interfaces:** `party.wind_direction` type stays but gains a becalmed state — decision: `Optional[Direction]` (`None` = becalmed; grep all readers, defaulting them to "no wind message"). Sailing is BLOCKED (message "The ship is becalmed!") while becalmed and while sailing into the reverse direction ("Headwinds block thy ship!" — supersedes the slow-down message). Wind re-rolls every 20th consumed turn to a value DIFFERENT from the current one, choosing among the 4 directions + calm (5 outcomes; GBC `dowinds` re-rolls per ~20 moves and avoids repeating, `menucmd3.c:1449-1467`). Supersedes the 4-second timer.

- [ ] **Step 1: Failing tests** — becalmed blocks move; headwind blocks move; 20-turn cadence; no immediate repeat.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: GBC wind becalmed/blocked rules`.

### Task 21: force field 99 damage; fire/lava flat 50

**Files:**
- Modify: `py_exodus/ui/renderer.py:65-77` (force-field gate), `py_exodus/world/tile_effects.py:104-107` (fire/lava)
- Test: tile effects test file

**Interfaces:** force-field entry now: if NOT all members carry Mark of Force → message "FORCE FIELD!", every member LACKING the mark takes 99 via `apply_damage`, move refused; all-marked → passage allowed (GBC `postexo1.c:1861-1880`). Fire/lava stepping: flat 50 unless Mark of Fire on that member (`funcs5.c:1287-1310`), replacing `16+rand(32)`.

- [ ] **Step 1: Failing tests** — unmarked party: damage 99 to each unmarked member, position unchanged; all-marked: passage succeeds; fire/lava flat 50 with Mark-of-Fire immunity preserved.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: GBC field lethality and fire damage`.

### Task 22: starvation 5 HP per meal crossing; HP regen tied to meals

**Files:**
- Modify: `py_exodus/entities/party.py:640-665` (`tick_regen`) — **supersedes the 2026-11-10 controller interpretation for these two rules only** (poison/mana stay per-turn/Book-of-Play)
- Test: party test file

**Interfaces:** no change. GBC: at each meal crossing (the `submorsels < 0` block in `end_turn`), a member with `food == 0` takes 5 damage; a member with `food > 0` heals +1 HP (`funcs5.c:741-778`) — both routed through the death chokepoint. Remove the starvation and HP-regen lines from `tick_regen` (keep mana + poison there); if food>0 regen must NOT also fire for poisoned members (GBC regen gates on the member not being poisoned? py had that gate — keep the "not poisoned" gate on the meal regen).

- [ ] **Step 1: Failing tests** — moving through two meal crossings with food 0 → exactly two 5-damage events; food>0 → +1 HP per crossing; mana still +1/turn; poison still 1/turn.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: GBC meal-bound starvation and regen (supersedes 2026-11-10 interpretation for these two rules)`.

### Task 23: ladders consume a turn

**Files:**
- Modify: `py_exodus/world/dungeon.py` `klimb_up`/`klinb_down` (grep `def k?limb` — ~1669-1750)
- Test: dungeon test file

**Interfaces:** no change. GBC: climbing/descending consumes the move (`mademove` stays 1 → the encounter roll can fire while standing on the ladder, `ult3.c:1388-1429`). Change both methods to run the turn tick like a normal move.

- [ ] **Step 1: Failing test** — climbing with forced encounter rolls triggers the battle return path / decrements torch as a normal turn. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** Commit `feat: ladders consume a turn (GBC ult3.c:1388-1429)`.

### Task 24: torchtime durations

**Files:**
- Modify: `py_exodus/world/dungeon.py` (torch model + per-move decrement, `dungeon.py:1087-1094`), `py_exodus/screens/dungeon_screen.py:464-482`, `py_exodus/combat/magic.py` (LORUM/LUMINAE/SOMINAE branches ~700)
- Test: dungeon + magic test files

**Interfaces:**
- Produces: `DungeonWorld.torchtime: int` (0–255) replaces `is_torch_on` boolean internals; `lighting_active -> bool` returns `torchtime > 0` (kept name-compatible with the screen's existing read sites). Ignite (`I` handler grep `doignite|ignite`) consumes one `torches` item and sets 255; SOMINAE sets 235; LORUM/LUMINAE top up to ≥10 (`max(10, torchtime)`); wind trap sets 0; decremented once per consumed dungeon turn (in the same place moves tick).
- GBC: ignite consume+255 (`dungfun2.c:1168-1191`), 235/10 (`dungfun2.c:962, 852-853`), wind→0 (`dungfunc.c:722-734`), decrement per move.

- [ ] **Step 1: Failing tests** — ignite with 0 torches fails; ignite → torches−1 and torchtime 255; SOMINAE → 235; LORUM → ≥10; wind → 0 and view dark; torchtime 1 → next turn → dark.
- [ ] **Step 2:** FAIL. **Step 3:** implement (keep `is_torch_on` as a thin property delegating to `torchtime > 0` if screen code reads it — avoid breaking save dicts; check `grep -n "is_torch_on" py_exodus/ saves/` and keep the saved field name, storing the counter under a NEW field so old saves load). **Step 4:** PASS. **Step 5:** Commit `feat: GBC torch durations`.

---

## Part D — Adoptions (D1/D2/D4 now; D3 in Task 26)

### Task 25 (D4): FAL_DIVI re-dispatch, VIEDA peer view

**Files:**
- Modify: `py_exodus/combat/magic.py:707-721`
- Test: magic test file

**Interfaces:**
- VIEDA: GBC renders the peer-gem view (55 MP outside, `menucmd.c:1379-1390`). py: the spell's `SpellResult` gains an optional rendered callback — check how the overworld `P`eer path invokes `ui/gem_view.py` (`grep -n "gem_view\|peer" py_exodus/screens/overworld.py | head`); wire VIEDA (when cast outside combat) to the SAME function the Peer command uses, returning the normal message otherwise.
- FAL_DIVI: GBC re-enters the cleric spell menu after saving/restoring the caster class context (`menucmd.c:1519-1530`) — in py, casting FAL_DIVI opens the cleric cast prompt again (reuse the existing `C`-command cleric member+spell prompt of the calling screen via a `followup="cleric_menu"` field on `SpellResult`, handled by the call sites in town/overworld/combat screens).

- [ ] **Step 1: Failing tests** — VIEDA cast routes to the gem-view function (monkeypatched spy); FAL_DIVI result carries `followup="cleric_menu"` and the overworld screen handler dispatches the cleric menu once. **Steps 2-4** as usual. **Step 5:** Commit `feat: VIEDA peer view and FAL_DIVI re-dispatch (D4)`.

### Task 26 (D3): real Other commands — bribe, steal, dig, pray, search, score

**Files:**
- Create: `py_exodus/special_commands.py` (pure-logic module — screen-agnostic functions taking explicit args so both `town.py` and `overworld.py` share one implementation)
- Modify: `py_exodus/screens/town.py:877-903`, `py_exodus/screens/overworld.py:963-987` (delegate to the new module), dungeon screen `O` handler (grep `prompt_other` in `dungeon_screen.py`)
- Test: `tests/test_special_commands.py`

**Interfaces (all in `py_exodus/special_commands.py`):**
- `do_bribe(party, member, direction, game_map, creatures) -> str` — needs 100 gold from `member` (deduct), tile in `direction` must be the guard-class creature (py: creature with tile `"guard"`); removes it and restores the underlying tile (mirror `overworld.py` pirate-removal conventions); messages match GBC (insufficient gold, no effect).
- `do_steal(party, member, direction, game_map) -> str` — GBC shoplifting (`menucmd2.c:1440-1540`): the 3-tile chain in `direction` must be [person/vendor tile] → [door or locked_door tile] → [chest tile] (py rules `person`/`merchant`, `door`/`locked_door`, `chest` — semantic mapping of GBC 0x3C..0x56 / 0x0B|0x16 / 0x0C, documented). Skill = member dex (+80 if member `skill == 9` i.e. thief profession, +40 for professions index set {0,1,5,8} — map to py `Profession` names: fighter? implementer reads `py_exodus/constants.py` Profession order and picks the 4 GBC skill indices 0/1/5/8 with a comment). Roll `random.randrange(256) < skill` → success: gold `randrange(100) | 0x30` then `>100 → -=100`, cap 9999, message with amount; plus 25% chance a bonus message line (weapon or armor found — GBC continues past `make_rnd(0)<0x40`, `menucmd2.c:1541+` — read those 30 lines during implementation; if unclear, cap at the gold+message). Failure: 25% → "Watch out!" (all guard creatures on the map flagged hostile — py towns guard NPC `ctrl`; if the py town model has no hostile flag, make the nearest guard NPCs attack-compatible equivalent documented in code, or defer aggro and only play the warning — implementer decision, logged in the docstring).
- `do_dig(party, member, x, y, game_map) -> str` — outside only; (33,3) grants +1 Exotic weapon (stack cap 9 — py weapon enum index for EXOTIC, `grep -n "EXOTIC" py_exodus/constants.py`), (19,44) grants +1 Exotic armor (cap 9); message "EXOTICS!" then "Nothing happened." elsewhere (`menucmd3.c:1120-1133`).
- `do_pray(x, y, map_id) -> str` — GBC hint site: EXODUS map (48,48) → the EVOCARE vision message (keep the existing Java Yew hint in the same function — union of references, comment says so) (`menucmd3.c:1199-1206`; note `party_specials` bit has no py equivalent — the vision hint is the adopted part).
- `do_search(member, x, y, map_id, map_name) -> str` — on AMBROSIA at (4,36)→Card of Love, (45,52)→Card of Sol, (6,6)→Card of Moons, (55,27)→Card of Death — `char.cards[idx] += 1` (`menucmd3.c:1151-1197`); message "A Card with Strange Marks." 
- `do_score(party) -> str` — prints the party move counter (`menucmd3.c` SCORE entry — py `party.moves`; verify the GBC score content near `menucmd2.c:1050` region; message "Thou hast achieved a score of N!").

Both screens keep their `O` prompt; commands route through these functions; KISS stays the existing stub with a comment (GBC has no KISS; original-rule port deferred to pending-items).

- [ ] **Step 1: Failing tests** — pure-logic: bribe gold/guard/no-effect; steal success/fail/gold band (48..99)/3-tile-chain requirements incl. wrong-tile orders; dig coordinates/caps + "outside only"; pray sites; five search sites grant the right cards; score formatting. Screen-wiring tests: one per screen asserting the prompt routes to the module.
- [ ] **Step 2:** FAIL. **Step 3:** implement module + screen delegation. **Step 4:** PASS. **Step 5:** Commit `feat: functional Other commands (bribe/steal/dig/pray/search/score)`.

### Task 27 (D2): save integrity envelope

**Files:**
- Modify: `py_exodus/save_system.py:39-71` (save_game/load_game/load_game_data/save_roster/load_roster)
- Test: save system test file

**Interfaces:**
- Game saves become `{"magic": "U3PY", "checksum": int, "payload": {...}}` where checksum = `zlib.crc32(json.dumps(payload, sort_keys=True, indent=None).encode())`.
- Roster saves become `{"magic": "U3PY", "checksum": int, "payload": [...]}`.
- Loads accept BOTH formats: envelope form verifies checksum and raises `SaveChecksumError` (new exception class in the module) on mismatch; non-envelope (legacy) loads exactly as before. Checksum verification failure lists the file path in the message.
- Commit-rule parity with GBC (`menucmd2.c:1137-1139`): the checksum is computed at save time only (py JSON writes are atomic-enough at the fs level for this purpose; a mutation-time recompute hook is NOT required — document why in the module docstring).

- [ ] **Step 1: Failing tests** — round-trip save/load; tampered payload raises `SaveChecksumError`; legacy file loads; roster round-trip + legacy roster loads.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + full suite (save-format tests elsewhere may need updating — fix them in this task). **Step 5:** Commit `feat: save integrity envelope (GBC SRAM checksum pattern)`.

### Task 28 (D1): debug/cheat harness

**Files:**
- Create: `py_exodus/debug.py` (`DEBUG_MODE` module flag, `CheatState` frozen dataclass with the 7 toggles + `max_all()` helper, `get_cheat_menu(surface)` pygame menu)
- Modify: `py_exodus/__main__.py` (argparse `--debug`), `py_exodus/screens/overworld.py`, `py_exodus/screens/town.py`, `py_exodus/screens/dungeon_screen.py`, `py_exodus/screens/combat_screen.py` (F10 opens the menu when `debug.DEBUG_MODE`; effect sites below)
- Test: `tests/test_debug_menu.py`

**Interfaces (all in `py_exodus/debug.py`):**
- `CheatState`: `xray, nofight, nohurt, noblock, full_mp, no_class: bool`; module-level singleton `CHEATS`. Effect wiring mirrors GBC (`cheat.c:768-825` + cited sites):
  - `xray` → `py_exodus/world/field_of_view.py` caller (`grep -rn "field_of_view\|compute_fov" py_exodus/`): skip occlusion, all tiles visible.
  - `nofight` → overworld creature-contact dispatch: skip combat entry.
  - `nohurt` → `PartyMember.apply_damage` early-return (all HP loss).
  - `noblock` → `ui/renderer.py` walkability check early-return True (movement validator).
  - `full_mp` → at cast-prompt open (the three cast prompt sites), set caster `mp = max_mp` before selection.
  - `no_class` → profession gates in the spell lists (`magic.py` discipline filter) return both lists.
  - `max_all()` (one-shot from the menu, not a toggle): every member gold 9999, keys/gems/torches/powders 99, hp/max_hp 9999, all stats 99, food/exp 9999, level 99, all weapons + all armors stacks at 9, all marks+cards (`cheat.c:441-479`).
  - MUSIC jukebox: SKIP (no track-picker widget in py; note in the menu item's disabled state or omit — implementer decision, record in module docstring).
- The menu lists each toggle with the GBC description strings decoded (`cheat.c:77-102`): "SEE THROUGH ANY TILE", "NO RANDOM BATTLES", "HP NEVER DECREASES", "WALK THROUGH ANY TILE", "MP NEVER DECREASES", "ANY CHAR CAN CAST ANY SPELL", "MAX ALL STATS/GOLD/ITEMS" — cursor-move highlight.
- Cheat state is runtime-only: NOT in any `to_dict()`/save path — assert this in tests.

- [ ] **Step 1: Failing tests** — `--debug` sets `DEBUG_MODE` (call `main(["--debug"])` with pygame in dummy mode, or factor the flag parse into a testable function); each toggle flips through the menu (simulate two F10 opens); one effect test per flag (xray reveals a walled tile; nohurt survives a lethal hit; noblock walks a mountain; nofight skips combat entry; full_mp/mp=noclass/both-lists; max_all asserts the full stat set); save dict contains no cheat keys; non-debug F10 does nothing.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + full suite. **Step 5:** Commit `feat: GBC-style debug/cheat harness (D1)`.

---

## Deferred (not in this plan; ledger in pending-items after execution)

- D5 per-map music routing/jukebox, D6 post-Exodus New Game+, D7 presentation QoL (hover menus, digit-entry widget, hand-consumables, look-table, Dawn-as-tile, inventory caps, Mark-of-Kings partial advancement, dungeon-chest loot bands) — **exception: dungeon-chest item drops ARE adopted as Task 30 per the 2026-11-14 LW+NES ruling.**
- Chest Bomb trap (cannonfire reuse) — recorded in Task 8's comment.
- GBC hard-mode rules (extragame) — moot without D6.
- Post-Exodus spells (TERRAFORM/ARMAGEDDON/FLOTELLUM), auto-cast/auto-heal conveniences, Alchemist bonuses — **per user ruling 2026-11-14: never port (LW-only remake additions, not original U3).**
- Ship hull system, ranged-bolt 34% mechanics, chest trap-type ladder, chest gold bands — standing (no LW/NES pair agreement; user re-rule 2026-11-14 keeps current behavior where the refs do not agree).

---

## Amendments (user ruling #2, 2026-11-14 — LW+NES agreement rule)

Binding rule: *"Where LairWare + NES agree and differ from current choices, implement the LairWare+NES agreed."* Full ruling recorded in `.superpowers/sdd/2026-11-14-gbc-parity-and-fixes/progress.md`.

- **Task 17 amendment:** ALTAIR spell stop-time = **20 rounds** (LW `UltimaSpellCombat.c:238` `gTimeNegate=20`; NES `Bank0F.asm:3329` TimeStopTimer=$14), powder N stays **10**. Keep GBC freeze of moons+food during stop-time (LW contradicts, NES silent).
- **Task 19 amendment:** DROP the Trammel/Felucca rename (LW labels slow=Trammel/fast=Felucca — matching py's current naming; NES unfound). Keep everything else in Task 19 as written (move-driven 4/16, freeze, integer save semantics).
- **Task 26 amendment:** no Alchemist STEAL bonus (user ruling — GBC's 4-profession set stands); REMOVE the KISS branch from both `_prompt_other` handlers (user: KISS is not in U3; K = Klimb; LW lacks it too — replace its stub branch with the generic "Nothing happened." fallthrough and drop the plan's KISS-deferred note).
- **New Task 29** (below): undo Java's level-up stat gains.
- **New Task 30**: chest item drops. **New Task 31**: moongate model. **New Task 32**: reagent scrub.

### Task 29: undo level-up stat gains — stats only from Ambrosia shrines

**Files:** Modify: `py_exodus/entities/character.py:350-363` (`meet_lord_british`). Test: character test file.

**Interfaces:** no change. User ruling (2026-11-14): random 1–8 per-stat gains on level-up are NOT original behavior — remove them entirely; both independent refs agree (NES Bank0B:5301 region — exp→level only; LW `AddExp` `UltimaMisc.c:442-456` — no stat mutation). Level-up keeps: level advance, `max_hp = level*100+50`, `hp = max_hp`, status GOOD, and the Mark-of-Kings gate as-is. Stats increase only at shrines — verify `py_exodus/screens/shrine.py` already implements the buy (100g/point to race cap); if it is missing any of that, note it as a concern, do not expand scope.

- [ ] Step 1: failing test — `meet_lord_british` leaves str/dex/int/wis untouched across multiple level gains. Step 2: FAIL. Step 3: delete the gain loop + `USER-DIRECTED` comment citing the ruling and both references. Step 4: PASS. Step 5: commit `fix: no random stat gains on level-up; stats only via Ambrosia shrines`.

### Task 30: chest item drops (weapons 1–8 / armor 1–4 at 25% each)

**Files:** Modify: `py_exodus/world/chests.py:66-77` (`open_chest`). Test: chest test file.

**Interfaces:** `ChestOpenResult` gains `item_lines: list[str]` (message lines the screen appends). After gold credit: 25% chance a weapon stack +1 (LW `GetChestBooty` `UltimaMain.c:1736-1745`: weapon index `randrange(8) + 1` → weapons 1–8, stack cap 9); else another independent 25% chance armor +1 (`randrange(4) + 1` → armor 1–4, cap 9). Message lines name the item (reuse the vendor's item naming from the weapons/armors tables — `grep -n "WEAPONS\|names" py_exodus/entities/defs.py | head`). Gold band unchanged (Java truth; refs diverge; per ruling keep standing).

- [ ] Step 1: failing test — seeded trials produce item lines ~25%/25% with the right names and stack caps; gold band regression unchanged. Step 2: FAIL. Step 3: implement + deviation comment `(GBC menucmd.c:1148-1170; LW GetChestBooty UltimaMain.c:1736-1760)`. Step 4: PASS. Step 5: commit `feat: chest weapon/armor drops (LW+NES-agreed extension)`.

### Task 31: moongate model — 8 fixed sites, one gate, slow-site entry, fast-site destination

**Files:** Modify: `py_exodus/screens/overworld.py:1489-1525` (+ gate defs in `py_exodus/entities/defs.py` if needed). Test: overworld moongate tests.

**Interfaces:** py's `d1/d2/d3` per-gate destination tables (Java invention) are replaced by the model all three refs share: 8 fixed sites; the gate VISIBLE at site[slow_phase]; stepping on it teleports to site[fast_phase]. Build the site table from py's existing 8 moongate coordinates (`grep -n "Moongate\|moongates" py_exodus/entities/defs.py py_exodus/world/map_build.py | head`), keep Dawn-at-double-appearance logic untouched, keep save semantics (integer `moon_phase`).

- [ ] Step 1: failing test — gate renders at site[slow] and teleports to site[fast] for a sample phase pair; old d-table behavior test rewritten with deviation comment. Step 2: FAIL. Step 3: implement + comment `(GBC funcs5.c:1134-1152; LW UltimaMisc.c:1511-1560; NES Bank0F MoonGateTbl:734-771)`. Step 4: PASS. Step 5: commit `feat: moongate model per refs (single gate, slow-site/fast-site)`.

### Task 32: remove reagent references

**Files:** any file matched by `grep -rn -i "reagent" py_exodus/ assets/ tests/ README.md` (inventory first). Test: extend the touched tests.

**Interfaces:** removal only. If the grep finds no reagent logic (README prose only), delete the README mention and note in the report that no code referenced reagents — commit still made.

- [ ] Steps: inventory grep → failing tests if code exists (or, if prose-only, direct edit) → implement → full suite → commit `fix: remove reagent references (U3 has no reagents)`.
