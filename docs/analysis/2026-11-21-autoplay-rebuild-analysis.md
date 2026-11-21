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
