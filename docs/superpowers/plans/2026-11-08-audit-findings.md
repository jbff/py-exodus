# PyExodus Java-Parity Audit — Findings & Resolution (2026-11-08)

Five parallel audit agents read the Java source (`/sto/src/gdx-exodus/src/main/java/`) and the Python port and compared logic statement by statement. This file records the findings and their resolution; the plan in `2026-11-08-java-parity-fixes.md` decomposed them into 15 tasks, all executed and reviewed (branch merged to master at `99a9a8d`).

Counts at audit time: ~110 raw findings → ~90 after dedupe: **6 game-blocking (CRITICAL)**, **~45 MAJOR**, rest minor.

## 1. Commands & input (GameScreen/SecondaryInputProcessor vs screens)

- **CRITICAL:** dungeon G crashed (`UnboundLocalError`); **MISSING:** endgame INSERT unreachable (FinalScreen never instantiated).
- **MAJOR:** B auto-mounted horses with none present; X exited towns; E missing in town + whirlpool triggered on E not step-in; J had no member prompt and pooled into the wrong member; U never checked/consumed keys; combat lacked the Exodus-map exotic-weapon gate; EVOCARE snake-removal missing (Mark of Snake gate); ship moved without requiring facing; dungeon had no R/W/M/V/P/Q; dungeon Q missing while overworld saved anywhere; dungeon DOWN turned 180° instead of back-stepping.
- **MINOR:** L was an invented "Look"; H handed no armor; I ignored torch toggle-off; town T/S stubs; unhandled keys didn't pass a turn; prompt-cancel differences.
- **Resolution:** all fixed across Tasks 1, 3, 6, 9, 10, 11, 12. Final G semantics settled by Java keycode verification: G → member digit → chest at the party's own tile.

## 2. Combat & magic (CombatScreen/SpellUtil vs combat/*)

- **MAJOR:** monster ranged attacks fired every round (Java: 26% teleport → 34% ranged → melee, fire/energy breath deals damage twice); no aura system at all (NEGATE blocking, quickness); PONTORI/REPOND deterministic kills (Java: level-scaled 50/65/80/100% chance, only `orc`/`undead`); SANCTU healed 10–25 vs Java 75–99; ZXKUQYB "fixed" Java's integer-division bug instead of porting it; spell kills awarded no XP; party wipe survivable; DAG_ACRON castable in combat (Java: world-only — 0x01 mask); Castle of Death special rules absent (non-exotic attacks refused, creature auto-hits without exotic armor); MENTAR-family damage floors.
- **MINOR:** damage rolls high-inclusive vs Java exclusive-high; weapon loss never triggered ("Last One!"); flee added despite Java disabling it; combat-round poison tick invented; arena map selection simplified; monster AI movement deterministic; XP uncapped.
- **Resolution:** Tasks 11/12. Java bugs ported deliberately (ZXKUQYB, loseWeapon timing, corpse bolts). Flee removed (user-confirmed parity). Tracked follow-ups (not fixed): combat-round move counting, hull repair during sail combat, negate()/camouflage creature behaviors.

## 3. Vendors & conversation (vendor/* vs town.py)

- **CRITICAL:** food unbuyable in every food shop (purchase keyed on a `choice` attribute FOOD items don't have); healer charged unconditionally, Recall/Resurrect semantics wrong (resurrect should set hp=1).
- **MAJOR:** no sell flow for weapons/armor (half-price catalog); vendor catalog truncated to 6 items (Dawn sells 14); no quantity/"Take it?" flow; purchases charged the party pool instead of the buyer; no multi-transaction loop; tavern food credited to a field never consumed (purchased food vanished); hunger model diverged; healer lacked need-checks/member selection/blood donation; horse purchase set a permanent flag instead of spawning a boardable horse; Lord British resurrected the dead (Java's resurrect loop is commented-out dead code — only level advancement).
- **Resolution:** Tasks 7/8 — per-class vendor dialog framework in `screens/vendor_dialog.py` mirroring Java's `VendorClassSet`, all strings verbatim incl. Java quirks (dead branches, typos, unclamped sell writes). Character creation and roster removal fixed in Task 14.

## 4. World data, tiles, maps, saves (objects/*, util/* vs world/*, entities/*, save_system)

- **CRITICAL:** binary save/roster format incompatible with Java's 80-byte records (interop-only; Python saves JSON — resolution: documented, interop deferred).
- **MAJOR:** food/meal engine divergent (no submorsels, no heal/poison tick, no mana regen; wrong interval per map; party-level vs per-member stores); tile speeds and standing terrain effects (fire/lava/poison/gremlins) missing entirely; energy fields passable only with Mark of Force; dungeon pit traps misimplemented (invented z-drop + flat damage vs Java's per-member LAVA roll + tile clear, no level change); dungeon doors impassable (passable in Java); dungeon wandering monsters replaced by a bare ambush roll (Java: persistent creatures that path to you); chests 3–6× richer and with whole-party uninvented traps; marks index corruption in the binary loader (Snake/Force swapped); whirlpool→Ambrosia engulf absent (and the return exit randomized instead of Java's fixed (1,1)); ship sinking absent.
- **MINOR:** FOV edge-wrap on city borders; orb behavior (Java's orb is dead code); dungeon ladder clamp; torch model; damage off-by-one; aura persistence.
- **Resolution:** Tasks 4/5/6/13 (+14 for marks/gate). Verified clean: moongates, FOV core, data tables (XMLs are byte-identical), dungeon loader, progression math.

## 5. Screens, flow, party, death (Context/Party/screens)

- **CRITICAL:** no party-death→game-over flow anywhere (nothing called the kill/revive helpers); FinalScreen unreachable (win path absent); card indices Love/Death swapped vs Java's `cards[0]=DEATH...cards[3]=LOVE`.
- **MAJOR:** no per-move endTurn tick (submorsels/poison/heal ticks/mana regen/ship repair); no overworld tile effects; food/gold pooled party-wide vs Java per-member; wrong card insertion mechanics (invented forced order, flat 50 damage vs Java's lethal whole-HP drain at wrong panels); character creation lacked stat allocation (fixed presets, gold 50 vs Java's 50-point budget with 150/150/150 start); removed members discarded instead of returned to the roster.
- **MINOR:** Mark-of-Kings level gate off by one (level 5 vs Java's level 6); max_mp frozen on load instead of recomputed; shrine gold source; start position (45,19); start screen quick-start party (removed 2026-11-09 by user ruling — see kept divergences).
- **Resolution:** Tasks 2/3/4/14/15. Book of Lore now loads `assets/data/ultima3.txt` with an appended spell reference.

## Kept divergences (documented, deliberate)

Orbs removed entirely (user decision — dead code in Java); peer gem (now a real map view); text-log prompt conventions; FOV edge-wrap; single-column Book of Lore paging; start-screen game-over label (Java shows nothing). The starter/quick-start party was REMOVED (2026-11-09 user ruling — "nobody wants a janky default party"): Java ships none, new players create characters in the roster screen, Journey Onward requires a saved party with a named first member.

## Verified at parity (no changes needed)

Moongate routing (Felucca phase, Dawn conjunction), FOV algorithm core, combat hit/defense formulas, damage bit-formula, spell dice tables and profession/location masks (29/32), max-MP per profession math, race caps, dungeon model & loader (16×16×8, 0x800 texts, labels, ladders, fountains), XML data (byte-identical), NPC conversation core flow.
