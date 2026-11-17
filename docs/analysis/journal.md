# py-exodus playtest #2 journal (fresh run from roster SHADOW/GRUMM/SERENA/ZIRCON)

Repo: /sto/prj/py-exodus @ 94c2b75. Driver loop: /tmp/play2/loop.py (FIFO /tmp/play2/in, out.log, full.log). party.json deleted pre-run; roster.json kept.

## Boot & start
- Fresh party formed from roster order; spawn (44,20) grass (user-directed deviated spawn) verified: one south + one west of castle gate (45,18).
- Stats at L1: hp 150/150 all; mp SHADOW 0, GRUMM 0, SERENA 25, ZIRCON 25 (thief/fighter no mp; cleric/wizard 25) — matches U3.
- Overworld boot message wraps: "Entering the realm of / SOSARIA..." + "Wind blows NORTH."
- 3 wandering creatures spawned on boot (post-fix spawn tables to verify below).

## Castle of Lord British (map 1)
- Enter via portal (45,18) with E: "Entering Castle of Lord British!" — fixed map label works (a07dc2e).
- Castle interior: outer corridor at x=31..33 south of inner MOAT rows 33-34 (water tiles) crossed by bridge at x=30; go-BFS found it; first straight-N walk blocked at (32,34) water - correct terrain block.
- Talk T -> member 1 -> N from (32,15): Lord British says: 'Welcome my child.. / Experience more!' at 0 exp. Parity with Java dialogue.

## Britain (map 3, "lcb" = Britain town)
- Portal (46,19) -> arrive (2,32). "Entering Britain!" — fixed town label works (a07dc2e).
- VOs: Osbert's Weaponry merchant NPC at (39,17), WEAPONS sign row y18, talk N from (39,19) across sign engages vendor (test parity). British Armour Otter at (50,18), sign y19, talk N from (50,20). The Market Max at (48,51), sign GROCERY y50, talk S from (48,49) (south column x48 at y52/53 is 'space' non-walkable — north approach only).
- WEAPON vendor flow: choice letter -> description -> "How many would you like?" -> digits then ENTER confirm -> "A fine choice!" + "anything else?" (y/n).
- ARMOR vendor flow: choice letter -> "Take it? (y or n)" -> "A fine choice!" + "anything else?" (distinct vendor questions = d411751 fix verified).
- FOOD vendor flow: rations offer "Reply? (y or n)" -> "25 for only 25gp. How many packs?" digits+ENTER -> "Thank you." + "Anything else?". Unaffordable: "You can only afford 0 packs." (SHADOW 15gp) — proper gold gating.
- Bought: Sling 60gp SHADOW; Mace 30gp GRUMM; Mace 30gp SERENA; Dagger 5gp ZIRCON; Cloth 75gp all four; 1 rations pack x3 (GRUMM/SERENA/ZIRCON). Gold now 15/20/20/45.
- Equip via R (ready weapon, A-P letters) and W (wear armor, A-H letters). All "Success!" lines seen.

## HARNESS/DX notes (not game bugs)
- Driver key token trap: single letters n/s/e/w resolve to compass arrows (documented in driver). All vendor y/n answers MUST go via raw pygame.K_e*n with unicode= or prompts silently ignore keyless events (prompts read event.unicode).
- "Thank you. Anything else?" requires explicit n; otherwise next T leaks into the y/n prompt and later keys hit town commands (Cast/Board/Yell) - my chunking error, but reproduces the real risk of mistyped keys cascading into commands.
- YELL text prompt: empty ENTER does not submit and ESC does not cancel ("Yell what?" stays open) - softlock-ish but a player can type any word + ENTER to exit. FILED as finding.
- go BFS in loop walks town streets ignoring NPCs (guards block, loop re-BFSes around, mimicking a human re-path).

## State snapshot
- All four: Cloth armor worn; weapons: Sling/Mace/Mace/Dagger. Food submorsels 90, display food 146/171.
- Position: Britain market (48,49). Next: exit town, fight overworld spawn fights, verify monster types + monster-hit lines + killer-only exp.

---

# py-exodus playtest #2 continuation (2026-11-16, @ 370cbaa)

Resumed via headless driver (`tests/play_driver.py` + `PlaySession(am).start()`) from Sosaria `(52, 27)`, `moves=276`, all 4 L1 at `150/150` HP (`SHADOW`, `GRUMM`, `SERENA`, `ZIRCON`). Key sequences used `N`/`S`/`E`/`W` arrows for movement/direction and `K_e`/`K_y`/`K_n`/spell letters with explicit `unicode` for single-char prompts.

## Phase 1: Unmodified `master` blocker (`monster_damage_bonus(SOSARIA) == 30`)

- YELL probe (`Y -> 1 -> ENTER`, then `Y -> 1 -> ESC`): confirmed `"Yell what? "` accepts empty `ENTER` or `ESC` cleanly (`is_waiting_for_input=False`), silently returning nothing (Java `SecondaryInputProcessor.java:535-538` keeps empty buffer open and has no `ESC`).
- Overworld `APPAR_UNEM` (`C -> 3 -> b` on `SERENA`): disarmed and opened chest cleanly (`"The Chest Holds: 49 Gold"`, `"You found a Cloth!"`).
- Run 2 (near Castle British bay `x=47..50, y=19`): wiped in Battle 8 vs `serpent` at `(48, 20)` (`Serpent hits SERENA (-22)`, `Magic Blast!`, `Serpent hits SERENA (-31)`, `SERENA falls!`).
- Run 3 (inland grass `(42..46, 24)`, excluding sea creatures): wiped in **3 battles** against L1 Thieves (`thief x 1`, `thief x 6`, `thief x 7`): `Thief hits GRUMM (-34)`, `(-31)`, `(-30)`, `SERENA (-41)`, `ZIRCON (-31)`, `(-32)`. `Killer-only EXP mismatches: 0`.
- Root cause (`py_exodus/combat/resolver.py:126-141` vs `refs/ult3src/.../battle3.c:354-368`, `ult3.c:1150,1654,1677`, `UltimaSpellCombat.c:1226`, Java `Creature.java:465-472`): `monster_damage_bonus(SOSARIA)` adds **`+30`** instead of **`+0`** (the 2026-11-14 GBC agent misread `inside == 0x20`/`peermap == 0`; in GBC `inside == 0x20` only adds `+30` when `peermap == 12` (Ambrosia) and `+0` on Sosaria where `peermap == 99`, while `inside == 0x21` adds `+30` for `peermap == 0 || 4` (British/Exodus) and `+20` for other towns).
- Secondary crashes / bugs surfaced while testing Phase 1 & early Phase 2:
  - Game-over -> `RosterScreen` dead-party leak (`base.py:60-66`, `start.py:187-221`, `roster_screen.py:70`): `check_party_death()` passes the dead `party` to `StartScreen` -> `_new_game()` forwards it to `RosterScreen`; `saves/party.json` with all dead members is also resumable directly into `OverworldScreen`.
  - `CombatArena` / `PartyMember` `hp == 0` wipe softlock (observed in Phase 2 pre-fix Run 0, Battle 9 vs `skeleton`): when all 4 reach `hp == 0` and the last hit lands at `new_hp == 0` (`Skeleton hits SHADOW (-5)` on `5` HP -> `status` stays `GOOD` per `party.py:102-106`), `CombatArena._evaluate_party_status()` (`arena.py:1368-1378`) checks `hp > 0` and sets `is_finished=True, is_defeat=True` (`"Press Enter to continue."`), whereas `CombatScreen._handle_defeat_exit()` -> `check_party_death()` (`base.py:55`) checks `party.is_party_dead()` (`status == DEAD` only -> `False`) and does nothing, permanently trapping the player on `CombatScreen`.

## Phase 2: End-to-End Walkthrough to Level 6/7 (in-memory `monster_damage_bonus` GBC override)

Using an in-memory-only monkeypatch inside the scratch runner (`SOSARIA=0`, `DUNGEON=10`, `BRITISH/EXODUS/AMBROSIA=30`, towns `=20`) with unmodified production code:

- **Milestone 2a (Overland spawns, combat, EXP, chests)**:
  - **114 battles fought**, `Killer-only EXP mismatches: 0`.
  - **462 monster-hit lines** recorded at realistic low-tier damage (`Orc hits GRUMM (-6)`, `Skeleton hits GRUMM (-7)`, `(-1)`, `ZIRCON (-5)`, `SERENA (-7)`). Notice `Monster death lines` matched `" falls!"` = `0` (crit/kill feedback printed `"Skeleton Critical!"` rather than `"falls!"`).
  - **Health-tier spawn progression** verified across `avg_max_hp` buckets:
    - `150`: `{skeleton: 9, orc: 9, thief: 7}` (low-tier only — no giants/daemons/dragons)
    - `250`: `{thief: 11, orc: 8, skeleton: 6}`
    - `350`: `{thief: 2, giant: 4, skeleton: 3}` (Giants unlock above `<=300`!)
    - `400`: `{skeleton: 2, giant: 4, orc: 2, thief: 1}`
    - `425`: `{skeleton: 2, thief: 2, daemon: 1, orc: 3}` (Daemons unlock!)
    - `475`: `{daemon: 5, giant: 4, skeleton: 2, thief: 1, orc: 1}`
    - `550`: `{skeleton: 7, giant: 2, thief: 6, orc: 8, daemon: 2}`
  - Chest interactions: tested `C -> 3 -> b` (`APPAR_UNEM`, both `"FAILED"` and `"The Chest Holds: 43 Gold"` / `"You found a Cloth!"`) and `G -> 1` at L2 (`"The Chest Holds: 35 Gold"`). Also saw Bomb/Gas chest traps in pre-fix runs (`Gas Trap!` -> 4 poisoned -> HP drained by `-1 HP/turn` poison tick on Overworld).
- **Milestone 2b (Lord British, Britain, Royal Healer)**:
  - Level-ups at Castle British `(45, 18)` (`e`, walk `(32, 15)`, `T -> 1..4 -> N`): all 4 advanced cleanly `L1 -> L2` (`max_hp 250`), `L2 -> L3` (`max_hp 350`), `L3 -> L4`/`L5`, and `L5` (`[616, 672, 504, 531]` EXP, `max_hp=550`).
  - With `min(exp) >= 500` (`[616, 672, 504, 531]`) and **no Mark of Kings**, Lord British **refused L5 -> L6** (`levels=[5, 5, 5, 5]`).
  - Food vendor at Castle British `(16, 22)` (`T -> m -> N -> y -> 1 -> ENTER -> n`) worked cleanly (`"How many packs? 1"`, `"Thank you."`, `"Goodbye. Come again!"`).
  - Royal Healer Pendragon at `(46, 26)` (`T -> 1 -> N -> y -> a/c -> slot -> ENTER -> y -> n`): curing (`a`) and resurrection (`c`, `500gp`, revived `SERENA` to 1 HP `GOOD`) both worked, **HOWEVER**:
    - Pressing `n` at `"Anything else?"` (`"In need of help? (y or n)"`) **refuses to exit**: when `hp < 400`, it loops straight back to `"Welcome unto The Royal Healer... Are you in need of help?"`; when `hp >= 400`, it prompts `"Give blood? (y or n)"` (`vendor_dialog.py:1030-1037`).
    - `"Who is in need? (member number)"` requires `ENTER` (`single_char=False` at `vendor_dialog.py:1087`), unlike `TALK`/`CAST` `1-4` prompts.
  - Note: automated detour to Britain `(46, 19)` after L2 stayed on `OverworldScreen` during runner step (`press_char("e")` didn't transition after `exit_town_south` / creature state; standalone `K_e` at `(46, 19)` verified to enter `TownScreen`).
- **Milestone 2c (Dardin's Pit `(46, 7)` & L6/7 Advance)**:
  - Entry (`e` at `(46, 7)`): logged `"Entering DARDIN..."` (enum key `"DARDIN"`, not `"Dardin's Pit"`, confirming item 38) + `"Level 1. Darkness surrounds thee."`.
  - Lighting: `I` -> `"No Torches!"`; `C -> 3 -> d` (`LORUM`) -> `"Luminae illuminates the darkness."` (`torch_on=True, torchtime=10`).
  - Descended `D` at `(11, 11)` to `z=1` (`"Climbed down to level 2."`).
  - Mark of Kings at `(11, 3, z=1)`: `s -> 1..4` -> `"You touch the Mark of Kings!"`; all 4 got `marks=[1, 0, 0, 0]`, HP dropped `[529, 527, 532, 540] -> [479, 477, 483, 490]` (`-50` HP per member; +1 regen on `SERENA`'s move/turn; `dungeon.py:2036-2039` mutates `hp` directly bypassing `apply_damage`).
  - Acid Fountain `(6, 4, z=1)`: `s -> 2` -> `"Bleck--Nasty!"`, `GRUMM` HP `478 -> 453`.
  - Descended `D` at `(13, 11)` to `z=2`; Healing Fountain `(13, 13, z=2)`: `s -> 2` -> `"Ahh-Refreshing!"`, `GRUMM` healed to `550/550`.
  - Climbed `K` at `(13, 11, z=2)` -> `z=1`, `K` at `(11, 11, z=1)` -> `z=0`, `K` at `(1, 1, z=0)` -> Overworld `(46, 7)`: **`"You climb out of the dungeon to the surface!"` logged TWICE** (`dungeon_screen.py:317-318` + `345`).
  - Returned to Lord British `(45, 18)`: all 4 advanced cleanly (`levels=[7, 7, 6, 6]`, `max_hp=[750, 750, 650, 650]`).
- **Milestone 2d (Q-save / Reload Round-Trip)**:
  - Pressed `Q` at `(45, 18)` -> `"Saved Game."` (`saves/party.bak-2026-11-16-level6-qsave.json`).
  - Reload via fresh `PlaySession(am).start()` matched position `(45, 18)`, `moon_phase=19`, and all 4 member stats/equipment/marks (`SHADOW L7 624exp 750HP`, `GRUMM L7 688exp 750HP`, `SERENA L6 512exp 650HP`, `ZIRCON L6 547exp 650HP 3221gp`, `marks=[1,0,0,0]`), **HOWEVER two state mismatches appeared**:
    1. **`moves` off-by-1 (`3591` -> `3590`)**: `OverworldScreen._save_game` (`overworld.py:2260-2270`) calls `SaveSystem.save_game` BEFORE `self._consume_pass_turn()`.
    2. **`creatures_count` jumped `5 -> 8`**: `OverworldScreen.__init__` (`overworld.py:367, 387-389`) restores saved monsters AND unconditionally spawns 3 extra wandering creatures on top.

## Playtest-2 Anomaly Summary (by severity)

1. **CRITICAL — `monster_damage_bonus(SOSARIA) == +30` (`py_exodus/combat/resolver.py:126-141`)**: Sosaria L1 thieves/orcs hit for 30–43 damage instead of 0–13, wiping L1 parties in 1–3 battles; true GBC `battle3.c:354-368` is `+0` Sosaria, `+10` dungeon, `+30` British/Exodus/Ambrosia, `+20` other towns.
2. **CRITICAL/HIGH — `CombatArena` / `PartyMember` `hp == 0` wipe softlock (`arena.py:1368-1378` vs `base.py:55`, `party.py:102-106, 826-832`)**: All-0-HP wipe with `status != DEAD` triggers `is_defeat=True` (`"Press Enter to continue."`), but `check_party_death()` returns `False`, trapping the player on `CombatScreen`.
3. **HIGH — `HealerVendorDialog` `'n'` exit loop & bugs (`vendor_dialog.py:1030-1037, 1071, 1087`)**: `'n'` at `"Anything else?"` loops back to `"Are you in need of help?"` when `hp < 400` or asks `"Give blood?"` at `hp >= 400`; `check_can_pay` assigns nonexistent `ConvState.ASK_BUY_SELL`; `Who is in need?` uses `single_char=False`.
4. **HIGH — Game-Over -> `RosterScreen` dead-party leak & dead `party.json` resume (`base.py:60-66`, `start.py:187-221`, `roster_screen.py:70`)**: Dead party leaks into `StartScreen`/`RosterScreen`, and Journey Onward loads an all-dead `party.json` into `OverworldScreen`.
5. **MEDIUM — `Q`-save `moves` off-by-1 & +3 creature respawn (`overworld.py:367, 387-389, 2260-2270`)**: `SaveSystem.save_game` runs before `_consume_pass_turn()` (`moves` -1), and `__init__` adds 3 extra creatures on top of restored creatures (`5 -> 8`).
6. **MEDIUM — `DungeonState.touch_mark` (`dungeon.py:2036-2039`) & `chests._apply_fire_lava` (`chests.py:199-201`) bypass `apply_damage`**: Mutate `hp` directly and kill at `hp == 0`, bypassing `< 0` death convention and `PartyDeathException`.
7. **MEDIUM — Dungeon entry enum label `"Entering DARDIN..."` (item 38, `dungeon_screen.py`)** & **duplicate `"You climb out of the dungeon to the surface!"` on exit (`dungeon_screen.py:317-318, 345`)**.
8. **MEDIUM — `YELL` prompt edge cases (item 40, `journal.md:28`)**: Empty `ENTER` / `ESC` closes `"Yell what? "` silently returning nothing vs Java's non-empty keep-open behavior.

---

# py-exodus playtest #3 (Endgame Walkthrough, 2026-11-16 @ 7cefcea)

Resumed via headless driver (`tests/play_driver.py` + `PlaySession`) from `saves/party.bak-2026-11-16-level6-qsave.json` (`(45, 18)` Sosaria, `moves=3590`, `SHADOW` L7, `GRUMM` L7, `SERENA` L6, `ZIRCON` L6, `marks=[1, 0, 0, 0]`, `3,221` gp). Boot logged `"Entering Sosaria!"` and `"Wind blows WEST."`, and restored both Sosaria whirlpools at `(50, 13)` and `(17, 48)`.

## Walkthrough Legs

- **Naval Frigate & Broadsides (`F`)**: Boarded unmanned frigate (`B` -> `Transport.SHIP`, `"Board Frigate!"`). Broadside `F` -> `N` while heading `NORTH` refused with `"Broadsides only!"`; `F` -> `E` fired `"BOOM! Broadside fired EAST!"` -> `"Direct hit! The Serpent sinks into the sea!"`.
- **Whirlpool -> Ambrosia (`map_id=13`)**: Sailed `SOUTH` onto the Sosaria whirlpool -> `"lungs you pass into / Darkness! / You awaken on the shores of / a forgotten Land. / Your ship and crew lost to / the sea!"`, landing at `(32, 54)` on `Transport.FOOT`.
- **9999 Gold Cap & Ambrosia Shrines/Cards**: `adjust_gold(99999)` capped cleanly at `9999`. Collected all 4 Cards via `O -> SEARCH` (`"You found a Card with / Strange Marks."`, `cards=[1, 1, 1, 1]`) at `(55, 27)` Death, `(45, 52)` Sol, `(6, 6)` Moons, `(4, 36)` Love. Entered all 4 Shrines (`ShrineScreen`): raised `SERENA` WIS `25 -> 79` (`max_mp=79`) and `ZIRCON` INT `25 -> 79` (`max_mp=79`).
- **Remaining Marks & `ZXKuqyb` (70 MP masskill, Item 41)**:
  - Entered `Dungeon of Fire` (`map_id=17` at `(49, 34)`): `show_minimap=True` verified; touched `MARK_FIRE` at `(5, 14, 7)` (`marks=[1, 1, 0, 0]`) and `MARK_FORCE` at `(4, 10, 7)` (`marks=[1, 1, 0, 1]`).
  - Entered `Dungeon of the Snake` (`map_id=19` at `(58, 44)`): touched `MARK_SNAKE` at `(6, 15, 7)` (`marks=[1, 1, 1, 1]`).
  - Entered combat (`4` orcs) with `SERENA` at `75 MP`, cast Cleric spell `O` (`ZXKUQYB`): spent `70 MP` (`75 -> 5`), logged `"Zxkuqyb destroys 2 monsters!"` (75% per-monster kill roll).
- **Exotic Gear (`O -> DIG`)**: Dug at `(33, 3)` (`EXOTIC` weapon) and `(19, 44)` (`EXOTIC` armor) on Sosaria (`weapons[EXOTIC]=1`, `armors[EXOTIC]=1`).
- **Castle of Death (`EXODUS`, `map_id=2` at `(10, 53)`), `PRAY`, `INSERT` Cards & Ending**:
  - `O -> PRAY` at `(48, 48)` logged `"A vision appears: Yell / 'EVOCARE'!"`.
  - Entered EXODUS combat (`context_map_id=2`, `daemon x 2`) with `EXOTIC` gear equipped.
  - At EXODUS machine panels `(30..33, 12)`, `O -> INSERT` inserted Love (`L`, `0x1`), Sol (`S`, `0x3`), Moons (`M`, `0x7`), Death (`D`, `0xf`), transitioning cleanly to `FinalScreen` with `exodus_defeated=1`.

## Playtest-3 Anomaly Summary (by severity)

1. **CRITICAL — Softlock exiting Ambrosia (`py_exodus/screens/overworld.py:1391` vs `:1408`, `py_exodus/world/portal_entry.py:28-50`)**: On Ambrosia (`map_id=13`), the exit `WHIRLPOOL` portal at `(32, 58)` is a `whirlpool` tile (`UNWALKABLE|LIVINGTHING`) adjacent to `water` at `(32, 57)` (`UNWALKABLE`). Because `step_in_whirlpool_portal(self, nx, ny)` runs *inside* `if can_move_to(...)`, a party arriving on Ambrosia on `Transport.FOOT` cannot step onto `(32, 58)` and is permanently softlocked on Ambrosia.
2. **MINOR — `ShrineScreen.handle_event` missing `.unicode` guard (`py_exodus/screens/shrine.py:155, 173`)**: Reads `event.unicode` directly without `getattr(event, "unicode", "") or ""`, raising `AttributeError` on `KEYDOWN` events lacking `.unicode` (e.g. modifier/programmatic events).
