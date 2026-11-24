# LairWare Logic Parity Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every game rule in py-exodus behaves as LairWare's Mac port (`refs/ultima3/Sources`) does, except where the user has ruled otherwise, with each difference found, recorded, tested and fixed.

**Architecture:** The audit runs in eleven batches, one per subsystem. Each batch reads a fixed list of LairWare functions next to their port counterparts and records every difference in one ledger. It then classifies each difference, and fixes each "port it" row test-first, one commit per row or per small group. The fixes themselves are not knowable before the reading, so this plan fixes the scope, the order, the per-row procedure and the definition of done, not the code.

**Tech Stack:** Python 3.14, pygame-ce, pytest (`.venv/bin/python -m pytest`). LairWare C sources are read-only evidence in `refs/ultima3/Sources/`.

**Spec:** the user's instruction of 2026-11-23 ("create a comprehensive plan to bring logic to LairWare parity ... just plan"), plus the standing rulings in the repo `CLAUDE.md`, README "Deliberate Deviations", and the future-work queue (item 1: "sweep refs/ultima3/Sources against py_exodus for logic mismatches and port them. Logic only; UI/look is deliberately NOT LairWare").

## Global Constraints

- LairWare is the correct implementation in any rules dispute (`CLAUDE.md`).
- Logic only. Look, sound, layout, art and UI flow are deliberately not LairWare (intro, title, shrines were de-LairWared 2026-11-23). Message wording changes only where the text carries a rule (a number, a condition).
- Work on `master`. Never force-push or rewrite it.
- Push only after the full suite passes with exit code 0, checked directly (`.venv/bin/python -m pytest -q; echo RC=$?`), not through a pipe.
- After every commit pushed to master, move the annotated `beta` tag to HEAD and push it: `git tag -f -a beta -m "beta: ..." HEAD && git push -f origin refs/tags/beta`.
- No `Co-Authored-By` lines in commits.
- Update `README.md` in the same commit as any change that makes it stale.
- No binary or proprietary files are loaded at runtime (maps and roster are JSON). Rule data stays in XML/JSON.
- Autoplay runs (live or batch) only on the user's explicit request. Autoplay fixes forced by a rule change are narrow (no step-cap or key-wait work).
- Keep these user rulings even where LairWare differs (record them as `keep`, never "fix" them back):
  - No starter party; roster starts empty. Sex=Other exists. Character portraits removed from UI.
  - Magical Orbs removed entirely.
  - Spell letters A–P are fixed per discipline; invalid casts refuse at attempt ("Not Here!" or the MP message).
  - Wireframe dungeons, with the map overlay on by default (`P` hides it).
  - Quality of life: `Q` saves only on the Sosaria overworld; `APPAR UNEM` opens the chest underfoot without a direction prompt; saves are JSON.
  - A shopkeeper's question is asked once, as the prompt.
  - Healer: hp < 400 declining help, or declining blood, ends the visit (2026-11-16 item 44).
  - Towns, castles and Death Gulch fully reset on every entry.
  - Tavern/guild/oracle Java conversation flow stays unless a rule (price, amount, condition) differs.

## Review Focus

1. **Byte arithmetic.** LairWare stores stats, HP, food and gold in `unsigned char` / 16-bit fields that wrap or clamp (`> 99`, `> 9999`, `/256` splits). Python ints don't. Expect saturating caps, not wraps, unless the C code really wraps; each cap gets a boundary test (98→99→99, 9998+5→9999 or refused).
2. **Random ranges.** `RandNum(a, b)` is inclusive at both ends, and `Random()` is a signed 16-bit value compared with thresholds. A port that uses `randint`/`random()` with off-by-one bounds shifts odds. Each ported roll gets a test that pins the bounds with a seeded or monkeypatched RNG.
3. **Turn timing.** `FinishAll` (spawn + move monsters) runs per command on Sosaria but every other tick on water; food, aging and moongate phases tick in `IncMoves`/`EatFood`/`AgeChars`. A rule ported into the wrong hook runs at the wrong rate. Tests count calls over N moves.
4. **Saves.** A rule change that alters stored fields (new counters, changed meanings) must still load old `saves/party.json` and roster files. Each such task adds a load-an-old-save test.
5. **Autoplay.** Rule changes that make the game harder or change prompts can break autoplay. The suite's autoplay tests must pass; a prompt-text change must keep autoplay's keyword matches (`py_exodus/autoplay/controller.py` `_handle_town_prompt`).

---

## File Structure

- Create: `docs/superpowers/plans/lw-parity-ledger.md` — the single ledger of findings (format below). Committed after each batch.
- Create: `tests/test_lw_parity_<area>.py`, one per batch (`roster`, `turn`, `monsters`, `commands`, `shops`, `world`, `combat`, `spells`, `dungeon`, `autocombat`). Each test's docstring cites the LairWare `File.c:line` it pins.
- Modify: the port modules named in each batch. No new modules unless a batch's ledger shows a missing mechanic.

### Ledger format (the interface between tasks)

```markdown
| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| T-03 | EatFood (UltimaMisc.c:1210-1240) | entities/party.py:412-430 | LW eats every 8 moves; port every 10 | port | done | abc1234 |
```

- ID: batch letter + number (R roster, T turn, M monsters, C commands, S shops, W world, B battle, P spells, D dungeon, A autocombat).
- Class, exactly one of:
  - `port`: the port differs from LairWare and no ruling covers it. Fix it.
  - `keep`: a user ruling in Global Constraints covers it. Note which one.
  - `ask`: a LairWare-only addition not in the classic game (e.g. TERRAFORM, ARMAGEDDON, FLOTELLUM, the Alchemist's steal bonus, DoAutoHeal, the new-map generator), or code that looks like a LairWare bug. Needs a user ruling before any change.
  - `same`: checked and equal. One row per function group, so coverage is visible.
- Status: `open` / `done` / `ruled-keep` / `ruled-port` / `wontfix`.

## Per-row procedure (every `port` row, every batch)

- [ ] Write the failing test in that batch's `tests/test_lw_parity_<area>.py`. Name it `test_<lw_function>_<behaviour>` and quote the LairWare lines in the docstring.
- [ ] Run it: `.venv/bin/python -m pytest tests/test_lw_parity_<area>.py::<name> -q`. Expect FAIL on the port's current behaviour.
- [ ] Make the smallest change that makes it pass, with a comment citing the LairWare lines.
- [ ] Run the batch file and the full suite; full suite exit code 0.
- [ ] Update README if a documented rule changed (README lists LairWare ports under "Rules authority").
- [ ] Commit (`fix(rules): <what> (LairWare)`), push, move and push `beta`, fill the ledger row's Commit.

`ask` rows are gathered and put to the user at the end of each batch (one AskUserQuestion, up to four rows per question). Nothing in an `ask` row changes until the user rules.

---

### Task 1: Ledger, baseline and prior ports

**Files:**
- Create: `docs/superpowers/plans/lw-parity-ledger.md`
- Read: `docs/superpowers/plans/2026-11-13-pending-items.md`, `README.md` ("Rules authority", "Deliberate Deviations"), `git log --grep=LairWare`

**Interfaces:**
- Produces: the ledger table (format above) with a "Prior ports" section listing already-ported LairWare rules and their commits, so later batches re-verify instead of re-porting: monster hit/damage and UNSPEAKABLE (`1a99024`), people move in towns (`c3d6e9e`), Sosaria diagonal monsters (`2990bd3`), dead members leave the board (`2dcf92e`), Ambrosia monsters/objects/water door (`fdedf78`), whirlpool return (`4e2bdea`), shrines (`c450fd6`, `76925c4`, `fd67773`), chest traps and Bomb trap (`8f9b989`, `ead9131`, `56ce2f3`, `a12c566`), BigDeath (`a04012d`), pirates/dragons fire and cannons (`ede5b50`, `fd704fa`), selling (`a8ad544`), Join Gold (`7450004`), moongates (`c3128df`).

- [ ] Create the ledger with the header, the class definitions, the Prior ports section, and one empty table per batch (R, T, M, C, S, W, B, P, D, A).
- [ ] Copy every still-open item from `2026-11-13-pending-items.md` that names LairWare or "LW" into the right batch table as `open` rows (most LW items there are already CLOSED; list closed ones under Prior ports).
- [ ] Record the baseline: `.venv/bin/python -m pytest -q; echo RC=$?` → expect `1424 passed`, `RC=0`; note the HEAD commit in the ledger.
- [ ] Commit `docs: LairWare parity ledger`, push, move `beta`.

### Task 2: Batch R — character creation and roster

**LairWare:** `UltimaMain.c` CreateChar, ShowPoints, KillChar, FormParty, DisperseParty, Organize, Examine, ModifyOrder; `UltimaMisc.c` GetRoster/PutRoster, GetParty/PutParty.
**Port:** `py_exodus/entities/character.py`, `py_exodus/screens/roster_screen.py`, `py_exodus/entities/party.py`, `py_exodus/save_system.py`.
**Check, at least:** the 50-point budget and per-stat minimum/maximum; race/class stat caps; starting HP, MP, food, gold and gear; which race/class pairs are allowed; what Kill Char and Disperse do to items and gold; party order changes.

- [ ] Read each function next to its port; add R rows (`same` rows included).
- [ ] Run the per-row procedure for each `port` row (`tests/test_lw_parity_roster.py`).
- [ ] Put the batch's `ask` rows to the user; apply rulings.
- [ ] Commit the ledger update, push, move `beta`.

### Task 3: Batch T — the turn: movement, food, aging, wind, healing

**LairWare:** `UltimaMain.c` North…NorthWest, Pass, ValidDir, ValidTrans, NoGo, DoWind, HPAdd, HPSubtract, CheckAllDead, CheckAlive, StatWait; `UltimaMisc.c` IncMoves, EatFood, AgeChars, FinishAll, Routine6E6B, Routine6E35, MapConstrain, GetXYVal/PutXYVal.
**Port:** `py_exodus/screens/overworld.py`, `py_exodus/screens/town.py`, `py_exodus/entities/party.py`, `py_exodus/world/tile_effects.py`, `py_exodus/aura.py`.
**Check, at least:** food per move and starvation damage; HP regeneration; what each terrain costs or blocks per transport; poison ticks; ship and horse movement rules; wind on water; the move counter; when the party is "all dead". The GBC-era meal-bound starvation/regen rule (`3fd97c2`) is a known candidate: compare it with EatFood and classify.

- [ ] Same four steps as Task 2, with `tests/test_lw_parity_turn.py`.

### Task 4: Batch M — monsters outside combat

**LairWare:** `UltimaMisc.c` SpawnMonster, SpawnUntilFull, MoveMonsters, GetMonsterDir, ValidMonsterDir, MonsterHere, ShowMonsterList, GetHeading, Absolute; `UltimaMain.c` WhirlPool, GoWhirlPool.
**Port:** `py_exodus/screens/overworld.py`, `py_exodus/screens/town.py`, `py_exodus/world/monster_variants.py`.
**Check, at least:** spawn odds (`RandNum(0,134) < 128` skip), the 32-slot table, the first-level-party restriction (types 0–2), terrain match, movement and attack adjacency, pirates' and dragons' fire, guards and town people, whirlpool and serpent behaviour. Most of this was ported 2026-11-21/22; re-verify against the Prior ports list.

- [ ] Same four steps, with `tests/test_lw_parity_monsters.py`.

### Task 5: Batch C — the A–Z commands

**LairWare:** `UltimaMain.c` Attack, AttackCode, Board, Descend, Enter, Fire, GetChest, BombTrap, HandEquip, Ignite, JoinGold, Klimb, Look, NegateTime, PeerGem, ReadyWeapon, Steal, Transact, Unlock, WearArmour, Exit, Yell, Stats, What, What2, NotHere; `UltimaMisc.c` OtherCommand, AddGold, AddItem, AddExp, StealDisarmFail, GetDirection.
**Port:** `py_exodus/special_commands.py`, `py_exodus/screens/overworld.py`, `py_exodus/screens/town.py`, `py_exodus/world/chests.py`, `py_exodus/world/doors.py`, `py_exodus/world/search.py`, `py_exodus/entities/party.py`.
**Check, at least:** who may ready which weapon and wear which armour; Steal success and guard response; Unlock and key use; Ignite torch length; Peer at gem; chest contents and gold; Negate Time length; experience per kill; Yell's effects; the Other commands (bribe, pray, dig, search).

- [ ] Same four steps, with `tests/test_lw_parity_commands.py`.

### Task 6: Batch S — shops and services

**LairWare:** `UltimaMisc.c` Shop (every case), Clerical, GuildPay, GuildGive, WeaponList, ArmourList, SpellNoize (heal effects only).
**Port:** `py_exodus/screens/vendor_dialog.py`, `assets/xml/vendor.xml` (prices and stock).
**Check, at least:** food price and pack size; tavern/pub tips and clues by amount; oracle prices and clues; healer prices (cure 100, heal 200, resurrect 500, recall 900 per LW) and who may be healed; guild items, quantities and prices; horse price; weapon/armour buying limits (the 99 cap, LW message 260); Dawn's stock. Selling was ported 2026-11-23; re-verify only.

- [ ] Same four steps, with `tests/test_lw_parity_shops.py`.

### Task 7: Batch W — moongates, shrines, Exodus and world state

**LairWare:** `UltimaMisc.c` MoonGateUpdate, HandleMoonStep, Shrine, ShrineRace, SafeExodus, BlockExodus, ResetSosaria, GetSosaria/PutSosaria, PushSosaria/PullSosaria, LoadUltimaMap, GetMiscStuff/PutMiscStuff.
**Port:** `py_exodus/screens/overworld.py`, `py_exodus/world/portal_entry.py`, `py_exodus/world/shrine.py`, `py_exodus/screens/final.py`, `py_exodus/save_system.py`.
**Check, at least:** moon phase timing and gate destinations; shrine caps (already ported; re-verify); what entering and leaving a town restores; what blocks Castle Exodus and what the four cards/marks require; the end sequence's conditions; what the save keeps. Town reset on entry is a `keep` ruling.

- [ ] Same four steps, with `tests/test_lw_parity_world.py`.

### Task 8: Batch B — combat

**LairWare:** `UltimaSpellCombat.c` Combat, CombatAttack, Missed, DamageMonster, Victory, FigureNewMonPosition, CombatValidMove, ValidMove, HandleMove, Shoot, Projectile, Poison, Pilfer, ShowHit, DetermineShape, GetScreen, ExodusCastle, CombatMonsterHere, CombatCharacterHere, BackGround, HowMany.
**Port:** `py_exodus/combat/arena.py`, `py_exodus/combat/resolver.py`, `py_exodus/screens/combat_screen.py`.
**Check, at least:** how many monsters appear and where; to-hit and damage for each weapon; ranged weapons' reach; monster AI moves and targets; poison and pilfer odds; experience and the chest on victory; fleeing; the Exodus castle fight. Monster hit/damage was ported (`1a99024`); re-verify only.

- [ ] Same four steps, with `tests/test_lw_parity_combat.py`.

### Task 9: Batch P — spells

**LairWare:** `UltimaSpellCombat.c` Cast, ProcessMagic, EitherChoose, ClericChoose, WizardChoose, Spell, Incap, BigDeath, Necorp, Heal, Failed, Flashriek, RelocateDungeon, DownLevel, UpLevel.
**Port:** `py_exodus/combat/magic.py`, `py_exodus/spell_menu.py`.
**Check, at least:** MP cost and the level/class requirement of each spell; where each may be cast; each spell's effect, damage range and odds; failure chances. Fixed spell letters and refuse-at-attempt are `keep`. TERRAFORM, ARMAGEDDON, FLOTELLUM and any LairWare-only spell are `ask`.

- [ ] Same four steps, with `tests/test_lw_parity_spells.py`.

### Task 10: Batch D — dungeons

**LairWare:** `UltimaDngn.c` dPass, Forward, Retreat, Right, Left, dDescend, dKlimb, dPeer, DngInfo, InvalCmd, NotDngCmd, ShowSecret; dungeon-side parts of `UltimaMain.c` (GetChest, Ignite) and `UltimaSpellCombat.c` (DownLevel, UpLevel, RelocateDungeon); `GetXYDng`/`PutXYDng`.
**Port:** `py_exodus/world/dungeon.py`, `py_exodus/screens/dungeon_screen.py`.
**Check, at least:** torch light and darkness; fountains (each kind's effect); traps, gremlins and wind; marks and the Time Lord; what's in dungeon chests; encounter odds per level; secret doors; ladder rules. The wireframe view and map overlay are `keep`.

- [ ] Same four steps, with `tests/test_lw_parity_dungeon.py`.

### Task 11: Batch A — auto-combat

**LairWare:** `UltimaAutocombat.c` (all 25 functions).
**Port:** `py_exodus/combat/auto_combat.py`.
**Check:** LairWare's per-class choices (who heals when, which spells, melee vs ranged, targeting). The port's TAB auto-combat is "borrowed in concept", so every difference here starts as `ask`: the user decides whether auto-combat should match LairWare's or keep its own (autoplay depends on it, so a change needs a seed check the user runs).

- [ ] Read and record A rows, all `ask` or `same`.
- [ ] Put them to the user; apply rulings with the per-row procedure (`tests/test_lw_parity_autocombat.py`).
- [ ] Commit the ledger, push, move `beta`.

### Task 12: Close-out

- [ ] Confirm every LairWare function named in Tasks 2–11 has at least one ledger row (`same` counts), and every row is `done`, `ruled-keep`, `ruled-port` (done) or `wontfix` with a reason.
- [ ] README: refresh the "Rules authority" list of LairWare ports and the test count.
- [ ] Full suite, exit code 0.
- [ ] Ask the user whether to run an autoplay batch (100 seeds as 10×10 on one commit) to compare with the last batch numbers (`775884a`: 58 won).
- [ ] Commit `docs: LairWare parity audit complete`, push, move `beta`.

## Out of scope

- `UltimaGraphics.c`, `UltimaMacIF.c`, `UltimaNew.c` (display, prefs, dialogs), `UltimaText.c` (wording), sound and art: the look is deliberately not LairWare.
- `UltimaNewMap.c` (LairWare's random new-map generator): a LairWare-only feature; listed once as an `ask` row in batch W.
- Autoplay strategy, except narrow fixes a rule change forces.
