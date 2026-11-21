# Autoplay rebuild — analysis (2026-11-21)

Branch `autoplay-rebuild` (off `master` == tag `pre-nn` + README). The neural-net branch is
reference only. `HANDOFF_AUTOPLAY_2026-11-21.md` (untracked) was written by the agent that
caused the regression; where it disagrees with the user, the user is right.

## Agreed plan (user, 2026-11-21)

1. Fix the Mark of Force bug and port trace/batch/atlas tooling — **done** (`f5a769c`, `75ef01c`).
2. 100-seed baseline on master, with traces — **running** (`traces/baseline-f5a769c/`).
3. Restore original-game monster spawning (see below).
4. Re-measure.
5. Rebuild the transport/trip layer as ONE authority; judge every change on ≥100 seeds.

Tooling:
- Live: `uv run exodus --autoplay --seed N --trace` → `traces/trace_seed<N>_<time>.jsonl.gz`
- Batch: `uv run python -m py_exodus.autoplay.batch --seeds 0-99 --workers 18 --out-dir traces/<name>`
  (emulates GameApp's 60 FPS loop minus rendering; canonical Thief/Fighter/Cleric/Wizard party;
  seed-reproducible; ~780 steps/s per worker, ~3 min per full game)
- Report: `uv run python scripts/autoplay_atlas.py traces/<name> [--list]`

## How master's autoplay works

- `planner.evaluate_goal` is a priority if-ladder recomputed **every step**, with no memory of
  trips in progress (only `_food_shop_target` is sticky).
- `controller._step_overworld` (~600 lines) mixes goal handling with transport decisions:
  boarding (B) and exiting (X) a ship are decided independently in ~10 places, so B/X loops are
  built into the design.
- Master's README claims 6 unassisted wins from ~70 seeds (~9%). Recorded loss classes:
  Death Gulch shore cannon fire, starvation in BUY_FOOD, poison.
- Master's win runs were measured with uncommitted ad-hoc scripts; the batch runner now fills
  that gap.

## Bugs found on master

- **Mark of Force index** (fixed `f5a769c`): nav + 3 controller flood fills used `marks[2]`
  (Snake) for force fields; Force is `marks[3]`. Now uses `tile_effects.all_members_mark_of_force`.
- **Fresh-game roster** (`_step_roster`): with no save, autoplay creates 4 Human Fighters (no
  Cleric/Wizard). Live runs normally Journey Onward from `saves/party.json`. Open.
- Fire-field / lava gate in nav uses any-member Fire mark; engine burns each unmarked member. Minor, open.

## Neural-net branch post-mortem (what not to repeat)

- Its "3 wins → 0" compared neural-net against itself (build `2c5114b`), not against master.
- The "transport reconciler" (`_desired_transport` + reconciler block, `b4efc42`/`890eedf`)
  was layered on top of the ~22 old B/X sites without deleting them; its gate passed by
  default; several X sites were never gated → B/X loops by construction. Routing ignored cost
  (200-tile walk beat a 10-tile sail) and ship availability, and ran on Ambrosia with Sosaria tables.
- Food trigger `1173ac7` fired at the fill target (no hysteresis) → shop shuttle forever.
- Three overlapping poison/heal rules added in 30 minutes (`415ce37`, `ee52073`, `9812fc1`).
- None→SPACE (`4492b22`) hid missing handlers as silent stalls.
- Tests weakened to pass: B/X alternation assertion deleted (`9c84060`), assertion loosened
  (`890eedf`), expectation inverted (`8149bc9`).
- Monster restoration `cc0685e` only added Squid + Pincher; its Dragon/Balron mountain branch is
  dead code (mountains are CREATUREUNWALKABLE, rejected before the check).
- Worth porting later: guard-bribe avoidance (`228822f`), stranded-frigate detection
  (`08fe7ed`), living-members-only food reserve (`d697f43`), optional ALCORT-on-poisoned in
  auto-combat (`08d1748`).

## Anti-patterns to avoid in the rebuild

New arbiter without deleting old decision sites · gates that pass by default · bypass flags ·
trigger == fill target · tick-to-tick goal reordering · None→SPACE · weakening tests ·
single-seed A/B · many behavioural commits per measured batch.

## Strategy facts that matter (walkthrough research + port data)

- Level = EXP/100+1 at Lord British; cap 5 without Mark of Kings (each member must touch it,
  −50 HP each), cap 25 overall. No stat gains on level-up (user ruling) — stats rise only at
  Ambrosia shrines (100g/point from the member's own purse; request exactly `cap − stat`).
- **ALCORT needs 35 MP; the Cleric can't reach it until shrines raise Wisdom** → poison stays
  expensive (healer 100g, one member per visit) until an Ambrosia trip. Early Ambrosia matters.
- Kings: Perinian Depths L1. Fire + Force: Dungeon of Fire L8 (one trip). Snake: Snake dungeon L8.
- Exotics: DIG at (33,3) weapon and (19,44) armour, once per member.
- Whirlpools fixed at (50,13) and (17,48); Ambrosia exit (32,58). Cards via SEARCH at
  Death (55,27) / Sol (45,52) / Moons (6,6) / Love (4,36); Death and Moons are behind locked doors.
- Exodus castle: only Exotic weapons hurt; non-Exotic armour always hit → all 4 need Exotics.
  EVOCARE beside the serpent at (10,58) with a Snake-marked member; castle portal (10,53).

## Original-game monster spawning (in progress)

LairWare `refs/ultima3/Sources/UltimaMisc.c:1141` `SpawnMonster` ($7A0C):
- 7/135 chance per turn; up to 32 monsters; random tile anywhere on the map; must match the
  type's start terrain (`MonBegin`: 4 = grass for land types, 0 = water for sea types).
- `type = RandNum(0,12) & RandNum(0,12)` (inclusive, bitwise AND → biased to low types); if
  every member's max HP ≤ 150, `type = RandNum(0,2)` (orc/skeleton/thief only).
- `MonTypes[13] = {24,23,25,20,26,27,13,28,22,14,15,29,30}`; Man-O-War is tile 0x1C (28).
  Remaining: map tile indices → monster names, and GBC/NES cross-check.
- Names are aliases across versions (user): Orcus = Pincher, Dragon = Wyvern, Squid = Man-O-War,
  Thief = Cutthroat. Fidelity to which monsters spawn where is what matters.
- Java instead picks by party average max-HP tiers and never spawns Pincher/Dragon/Balron/Man-O-War.

## The transport/trip layer (next design)

One function owns transport: given position, destination and goal, return a trip plan whose
legs are walk / sail own ship / capture a ship / moongate, costed (wind-aware), chosen once,
and followed until arrival or invalidation. Goal handlers only name destinations; nothing else
may emit B or X. Squid policy (user): keep off squid-infested coast on foot; on a ship, cannon
them, never melee them, until ALCORT is available.

### Original spawn distribution (computed, LairWare `type = RandNum(0,12) & RandNum(0,12)`)

| type idx | P(%) | MonTypes tile | start terrain (`MonBegin`) |
|---|---|---|---|
| 0 | 42.0 | 24 | grass (thief per the "thiefs/orx/skeletons" comment) |
| 1 | 12.4 | 23 | grass (orc) |
| 2 | 12.4 | 25 | grass (skeleton) |
| 3 | 4.1 | 20 | grass |
| 4 | 10.1 | 26 | grass |
| 5 | 1.8 | 27 | grass |
| 6 | 1.8 | 13 | **water** (sea monster) |
| 7 | 0.6 | 28 | grass |
| 8 | 10.1 | 22 | grass |
| 9 | 1.8 | 14 | **water** |
| 10 | 1.8 | 15 | **water** |
| 11 | 0.6 | 29 | grass |
| 12 | 0.6 | 30 | grass |

Takeaways: the original is heavily weighted to the weakest types (54% of land spawns are
types 0-2); the nasty ones (types 7, 11, 12) are under 1% each; sea monsters (6, 9, 10) are
~5.4% combined and spawn only on water tiles. There is no party-strength tier beyond the
"all members max HP <= 150 -> types 0-2 only" rule.

**Still unresolved:** the exact tile-number -> monster-name mapping for MonTypes
(24/23/25 = thief/orc/skeleton is inferred from the source comment; the rest needs the LairWare
tile table or GBC `monsterstatdat` ordering). Sea tiles 13/14/15 are most likely
pirate/serpent/Man-O-War. Resolve this before porting; do not guess.

## Reference research: how the original ports handle monsters (2026-11-21)

Sources: LairWare `refs/ultima3/Sources/UltimaMisc.c:1141-1290` (SpawnMonster / MoveMonsters),
`UltimaSpellCombat.c:812-905` (HowMany / Combat setup); GBC `refs/ult3src/sdk/gbz80-gb/2-1-5/examples/u3/battle3.c:1105-1285`
(`generatemonsters`, `montilearr`), `funcs5.c:219-` (`monsterstatdat`); NES `refs/nes_ultima_3_disassembly`.

**Type table (LW and GBC agree exactly; mapping confirmed by LW `Tiles.plist` + GBC tile offset +6):**
roll idx = RandNum(0,12) & RandNum(0,12): 0 Orc, 1 Thief, 2 Skeleton, 3 Fighter, 4 Giant, 5 Daemon,
6 Sea Serpent(water), 7 Pincher(Orcus), 8 Wizard, 9 Man-O-War(water), 10 Pirate(water), 11 Dragon, 12 Balron.
Terrain: water types only on water (tile 0); land types only on grass (tile 4). The GBC additionally treats tile
0x0B/0x05 as valid land in dungeons-of-generators only. After beating Exodus (`extragame`) the GBC stops spawning
pirates. **Cleric (21) / Ranger / Merchant etc. never spawn as wanderers.** Implemented in `b8c2648`.

**Where LW and GBC differ:**
- Weak-party rule: LW has "all members max HP <= 150 -> only Orc/Thief/Skeleton" (UltimaMisc.c:1161-1164); GBC has NO such rule.
  Kept LW's (gentler at level 1). Under the user's truth chain (GBC wins over Java; LW+NES agree beats GBC) this is LW-only,
  NES gives no confirmation, so it is a judgment call - flag it to the user if revisited.
- Spawn chance per turn: LW 7/135 (5.2%) (`RandNum(0,134) < 128` returns); GBC 9/137 (6.6%) (`make_rnd(0x89) & 0x80`).
- Placement: both pick a RANDOM tile anywhere on the 64x64 map (`RandNum(0, mapsize-1)`), retry on wrong terrain;
  GBC also forbids same column AND same row as the player; LW forbids same x or same y.
- Population cap: LW 32 slots, GBC 31 (`nummonsters < 31`). The port caps at 6 on-screen (`len(self.creatures) < 6`) and 8 total.

**Combat numbers are NOT scaled by party strength in the originals:**
- LW `HowMany()`: 1..8 monsters (`RandNum(0,7)+1`), independent of party. The port already matches (GBC ruling, arena.py:327).
- LW monster HP = `RandNum(0, monhpstart[type]) | 0x0F` where monhpstart caps are 0x20..0xF0 (Orc 48 ... up to 240); the port's
  per-type caps come from Java `basehp` and are LOWER than GBC's for several types (Thief 80 vs 128, Giant 80 vs 112,
  Wizard 112 vs 160, Daemon 135 vs 160) - so the port's monsters are, if anything, slightly softer than GBC's.
- No difficulty scaling exists to explain why the original is survivable; players survive by their own tactics (levelling
  with Lord British, spells, ranged weapons) - and by encounter RARITY (next point).

**Big finding - encounter frequency/placement is what differs most from the port:**
- Original: ~5-7% spawn chance per turn at a RANDOM place on the whole map (usually far from the party), up to 31-32
  persistent monsters roaming the map; most are far away; the party meets few of them unless it dawdles. All monsters
  then home in on the party each turn (LW `GetMonsterDir`/attack mode 0xC0) but from a long way off.
- Port (Java behaviour): 25% chance per turn (`overworld.py:1932`) AND a forced spawn whenever no creature exists, placed
  8-12 tiles from the party (`_spawn_wandering_creature`, :1796-1812), cap 6, despawn beyond 24 tiles. That is a far
  higher encounter rate than the original, which is the likely source of the "legions of demons" feel and a large part of the
  combat-death rate seen in run 2.
- A faithful port of spawning therefore means changing RATE, PLACEMENT, CAP and PERSISTENCE together, not only the type
  table. Not yet done (needs a persistent whole-map monster list; the overworld currently despawns at 24 tiles). This is
  the next experiment to try before softening anything.

**NES (`refs/nes_ultima_3_disassembly`):** a different game design (13+ enemy classes, level-tiered `NPC_LND_EN_1/3/5/7/9`
and `NPC_WTR_EN_5/7` overworld enemy classes; `Ultima_3_Defines.asm:815-821`; spawn code is unlabelled assembly, not found
in a quick pass). It does NOT use the LW/GBC AND-roll table, so LW+NES cannot be said to agree on the type mechanism.
Not used as truth for this experiment.
