# CASE ANALYSIS: autoplay failure on master and the neural-net branch (2026-11-21)

This is analysis only. Writing this file changed no code.
Line numbers refer to `master` (`14665e5`) unless they're labelled `nn:` (`neural-net` HEAD).
For a summary of the same material, see `docs/analysis/2026-11-21-autoplay-rebuild-analysis.md`.

---

## 1. Verified state

| Fact | Receipt |
|---|---|
| `master` is `pre-nn` plus one README edit | `git diff --stat pre-nn master` → `README.md | 8 ++++----` |
| `neural-net` forked at `0c58c9f` and carries 66 more commits | `git merge-base master neural-net` |
| Master claims 6 unassisted wins in about 70 seeds (~9%) | `README.md`, "Status" and "Known Open Items #5" |
| Master's win runs used uncommitted ad-hoc scripts | no harness in `git grep WON@ master`; the only hits are in plan docs |
| Handoff "3 wins" baseline = neural-net build `2c5114b`, not master | `HANDOFF_AUTOPLAY_2026-11-21.md` §1, §3 |

---

## 2. Named suspects on master, ranked

### S1: Transport has no single owner. Ship boarding and leaving (B/X) are decided in 17 places. (ROOT CAUSE of B/X loops)
B/X is emitted by `controller.py` lines **1132, 1245, 1285, 1296, 1311, 1336, 1363, 1566, 1877, 1892, 1912, 1922, 1938, 1988, 2022, 2040, 2084**. They sit across `_step_overworld` (1056), `_step_ambrosia` (1734) and `_enter_portal_or_wait_dawn` (1998).
- Each site checks its own local conditions: whether the party is on the mainland, the hull level, which goal is active, and whether a shore is next to it.
- Nothing remembers that the party "boarded in order to go somewhere". The next tick can re-decide the opposite.
- Example: the generic "on ship, not one of these goals → X if land adjacent reaches Britain" at **1554–1566**, against "not on mainland → board any frigate" at **1106–1138**.

### S2: The planner re-evaluates the goal every step, with no commitment
`planner.py:129` `evaluate_goal` is a priority if-ladder over the live party state. It is called on every step from `controller.py:460`, `:541` and `:2126`.
- Goals flip as soon as a threshold is crossed mid-trip. For example, food dips below 300 (`planner.py:61`) while the party is sailing for exotics, and BUY_FOOD preempts the trip.
- The only memory is `_food_shop_target` (`controller.py:869–903`).

### S3: Starvation in BUY_FOOD (open user-reported failure class)
Contributing code:
- `planner.py:150–173`: BUY_FOOD outranks CURE_POISON and RESURRECT, and is **suppressed while on a ship** except on map 0 with food < 250. A sailing party can drift low before it fires.
- `planner.py:173` requires gold ≥ 30. Below that it falls to GRIND (`:205`), and starving parties then hunt prey via `_hunt_starving_prey_or_patrol` (`controller.py:974`).
- `controller.py:572–581`: the heal detour is **disabled during BUY_FOOD**. Poisoned members keep bleeding all the way to the shop.
- `controller.py:1494–1507`: picks the nearest *reachable* food portal by path cost, but `_nearest_reachable_portal` (2224) falls back to `ordered[0]` (the nearest as the crow flies) when nothing is reachable. Unreachable target → transport fallback → S1.
- `controller.py:2124–2155`: starving parties drop creature avoidance only after an avoid-route costs more than 40 steps.

### S4: The poison pipeline is too expensive before the party has ALCORT
- `controller.py:564–570`: ALCORT needs 35 MP. Cleric MP comes from Wisdom (starting cap 25), so this is unreachable until Ambrosia shrines are used.
- `planner.py:182/191/201`: CURE_POISON needs gold ≥ 100 and is **not scored on a ship** (`party.transport != SHIP`, :196).
- `controller.py:918–925`: the healer cures **one member per visit**.
- `controller.py:1219–1233`: CURE_POISON on foot avoids all land creatures with radius 2. That routes the party around fights but makes walks longer while poison ticks.

### S5: Fresh-game party is 4 Human Fighters
`controller.py:269–302` `_step_roster`: every character gets `"F"` (Fighter) at **:284** and `"H"` (Human) at :282.
- No Cleric or Wizard means no heals, no ALCORT, no light spell, and no APPAR_UNEM.
- Only bites when there's no `saves/party.json` (`_step_start`, :263). The live run "Journey Onward"s an existing save.

### S6: Mark of Force read from the wrong index (**FIXED** in `f5a769c`, user-approved)
`nav.py:77` and `controller.py:366, 663, 2051` used `marks[2]` (Snake). The engine uses `marks[3]` (`world/tile_effects.py:88, 102`; `ui/renderer.py:103`).
- Effect: a party with Force but no Snake could not path through force fields (Death Gulch, Exodus).

### S7: Fire/lava gate uses "any member" (minor)
`nav.py:76` treats lava as passable if any living member has `marks[1]`. The engine burns each unmarked member (`world/tile_effects.py:167`).

### S8: Monster pool is Java-bug, not original game (user wants original)
`screens/overworld.py:1882` sea `randint(20,21)` and `:1888` land tiers up to id 16, selected by average max HP (`:1876–1892`).
- Pincher (17), Dragon (18), Balron (19) and Man-O-War (22) never spawn.
- Original game (LairWare `refs/ultima3/Sources/UltimaMisc.c:1141–1186` `SpawnMonster`):
  - 7/135 spawn chance per turn.
  - Type is `RandNum(0,12) & RandNum(0,12)`.
  - Parties whose members all have max HP ≤ 150 get only orc, skeleton or thief.
  - Start terrain comes from `MonBegin` (grass or water).
  - Tile table `MonTypes` is at `UltimaMisc.c:36–37`. Man-O-War = 0x1C (`UltimaAutocombat.c:242`).

---

## 3. Named suspects on the neural-net branch (post-mortem; do not port)

| Suspect | Receipt | Verdict |
|---|---|---|
| Transport reconciler layered on top of the old B/X sites | nn: `controller.py` `_desired_transport` ~437, reconciler ~1659–1712, gate `_transport_emit_allowed` returns True when unlocked ~618; commits `b4efc42`, `890eedf` | Created a third decision-maker; B/X loops by construction |
| Ungated X sites | nn: `controller.py` ~1756 (CURE_POISON), ~2011/2022 (DIG), ~2718/2733/2753/2763 (Ambrosia; 2763 unconditional) | Reconciler bypassed |
| Food trigger at fill target | `1173ac7`: trigger `min food < 150`, shop fills to 150 | Shop shuttle forever; reverted in `8efb7b9` |
| None→SPACE | `4492b22`, nn: `controller.py` ~655 | Hid missing handlers as silent stalls |
| Three overlapping poison/heal rules | `415ce37`, `ee52073`, `9812fc1` (30 min apart) | Contradictory precedence |
| Tests weakened to pass | `9c84060` (deleted B/X-alternation assertion), `890eedf` (loosened to `in (K_b, K_LEFT)`), `8149bc9` (inverted expectation) | Lost the regression net |
| Monster restore half-dead | `cc0685e`, nn: `screens/overworld.py` ~1878–1916; mountains are CREATUREUNWALKABLE (`assets.py:138–142`), rejected before the Dragon/Balron branch | Only Squid and Pincher actually added |
| "3 wins → 0" claim | Handoff §3 compares `2c5114b` (neural-net) with later neural-net builds | Says nothing about master |
| Dead SHIP pathing | `2c5114b`, `9c84060`: `find_2d_step(SHIP)` without wind returns None (`nav.py:46–47`) | Dead code until `8e8b534` |

Worth porting later (self-contained): guard bribe/avoid `228822f`, stranded-frigate detection `08fe7ed`, living-only food reserve `d697f43`, ALCORT-on-poisoned in auto-combat `08d1748`.

---

## 4. Next steps (agreed with user)

1. ✅ Force fix and tooling (`f5a769c`, `75ef01c`).
2. ⏳ Baseline: 100 seeds on master code, in `traces/baseline-f5a769c/`.
3. Restore original-game spawning (S8). Annotate it as a USER-DIRECTED DEVIATION from Java.
4. Re-measure.
5. Single-owner trip/transport layer (fixes S1 and S2). Then attack S3 and S4 with measurements on 100+ seeds.
