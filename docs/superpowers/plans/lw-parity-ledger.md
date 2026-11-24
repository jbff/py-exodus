# LairWare Logic Parity Ledger

Single ledger for the LairWare logic parity audit (plan: `docs/superpowers/plans/2026-11-23-lairware-logic-parity.md`). LairWare (`refs/ultima3`) is the correct implementation in any rules dispute. Logic only: look, sound, layout, art and UI flow are deliberately not LairWare.

Baseline: HEAD `91aa579`, `.venv/bin/python -m pytest -q -p no:cacheprovider; echo RC=$?` gives `1424 passed`, `RC=0` (2026-11-24).

## Format

```markdown
| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| T-03 | EatFood (UltimaMisc.c:1210-1240) | entities/party.py:412-430 | LW eats every 8 moves; port every 10 | port | done | abc1234 |
```

- ID: batch letter + number (R roster, T turn, M monsters, C commands, S shops, W world, B battle, P spells, D dungeon, A autocombat).
- Class, exactly one of:
  - `port`: the port differs from LairWare and no ruling covers it. Fix it.
  - `keep`: a user ruling (section below) covers it. Note which one.
  - `ask`: a LairWare-only addition not in the classic game (e.g. TERRAFORM, ARMAGEDDON, FLOTELLUM, the Alchemist's steal bonus, DoAutoHeal, the new-map generator), or code that looks like a LairWare bug. Needs a user ruling before any change. Record with Status `open`; the controller asks the user once after Task 11.
  - `same`: checked and equal. One row per function group, so coverage is visible.
- Status: `open` / `done` / `ruled-keep` / `ruled-port` / `wontfix`.

Per `port` row: failing test in `tests/test_lw_parity_<area>.py` (docstring quotes the LW lines) -> smallest fix with a comment citing LW lines -> batch file and full suite (RC=0) -> README if a documented rule changed -> commit `fix(rules): <what> (LairWare)` with no Co-Authored-By -> fill the Commit cell. Do not push; do not touch the `beta` tag.

## User rulings (keep)

Class a row `keep` (and cite the number) where one of these covers it; never "fix" them back.

1. No starter party; roster starts empty. Sex=Other exists. Character portraits removed from UI.
2. Magical Orbs removed entirely.
3. Spell letters A-P are fixed per discipline; invalid casts refuse at attempt ("Not Here!" or the MP message).
4. Wireframe dungeons, with the map overlay on by default (`P` hides it).
5. Quality of life: `Q` saves only on the Sosaria overworld; `APPAR UNEM` opens the chest underfoot without a direction prompt; saves are JSON.
6. A shopkeeper's question is asked once, as the prompt.
7. Healer: hp < 400 declining help, or declining blood, ends the visit (2026-11-16 item 44).
8. Towns, castles and Death Gulch fully reset on every entry.
9. Tavern/guild/oracle Java conversation flow stays unless a rule (price, amount, condition) differs.
10. Wanderer spawning is faithful to the original U3 (not the Java bug); see `05caeae`, `b8c2648`.
11. Wind shown in words without arrows (README deviation 5).
12. Casters start with full MP (`compute_max_mp`), an original-rules ruling; LairWare starts at 0.

## Prior ports (already LairWare; re-verify, do not re-port)

| Rule | Commit(s) |
|------|-----------|
| Monster hit/damage and UNSPEAKABLE | `1a99024` |
| People move in towns (MoveMonsters) | `c3d6e9e` |
| Sosaria monsters move/attack diagonally | `2990bd3` |
| Dead members leave the combat board | `2dcf92e` |
| Ambrosia monsters, objects, water door | `fdedf78` |
| Whirlpool return | `4e2bdea` |
| Shrines (no shrine screen) | `c450fd6`, `76925c4` |
| Shrine buy pro-rated at cap, cap semantics (pending item 24, CLOSED) | `fd67773` |
| Chest traps: distribution 56/19/19/6 (item 28, CLOSED), Bomb trap (item 21, CLOSED) | `8f9b989`, `ead9131` |
| Bomb trap credits no booty (LW early return) | `56ce2f3` |
| Thief opens chests once Cleric dead; trap dodge | `a12c566` |
| BigDeath (ZXKUQYB 75% per monster) | `a04012d` |
| Pirates/dragons fire, ships have no hull | `ede5b50` |
| Ship cannons any direction, sail without turning | `fd704fa` |
| Selling weapons and armour | `a8ad544` |
| Join Gold keeps what won't fit under 9999 | `7450004` |
| Moongates (single gate, slow/fast site) | `c3128df` |
| Dungeon meal cadence (item 23, CLOSED) | `ef5e9da` |
| Whirlpool engulf same-tile only (item 1, CLOSED; GBC/LW) | see pending-items |
| Monster variant names | `c2ad61d` |
| Original-game wanderer rate, placement, cap | `05caeae`, `b8c2648` |
| No Castle Exodus until stat plan bought (autoplay) | `775884a` |

All SHAs verified present in `git log`.

## Open pending items naming LairWare / LW

None. Every item in `docs/superpowers/plans/2026-11-13-pending-items.md` that names LairWare or LW (items 1, 21, 23, 24, 28) is CLOSED and listed above.

## Findings

### R - Roster

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| R-01 | CharacterCreateDialog stat spinner (UltimaMacIF.c:2373, 2465-2483); Shrine `shMax` (UltimaMisc.c:1004); race/class pop-ups (UltimaMacIF.c:2505-2512) | entities/character.py:364-412; screens/roster_screen.py:337-390 | Checked equal: each stat 5..25, total at most 50 (points left never below 0). Racial maxima (lowest is 25, Fuzzy STR) never bind at creation, so the port's extra racial check is inert. Any race may take any class in both (LW has no pair check). | same | done | - |
| R-02 | CreateChar (UltimaMain.c:814-817) | screens/roster_screen.py:395-410 | LW gives every new character one Cloth and one Dagger, both readied; the port (Java ManagePartyScreen) gave none. | port | done | 13ff946 |
| R-03 | CharacterCreateDialog name field (UltimaMacIF.c:2430-2432, 2492-2496) | screens/roster_screen.py:480-490 | LW keeps at most 12 letters of a name; the port (Java) allowed 16. Old rosters with longer names still load unchanged. | port | done | 13ff946 |
| R-04 | CreateChar (UltimaMain.c:794-796, 808-813) | screens/roster_screen.py:395-410; entities/character.py:25-160 | Checked equal: food 150 (`[32]*100+[33]` = 1*100+50), gold 150, status Good, experience 0 (level 1), every other byte 0 (no torches, gems, keys, powder, marks or cards). | same | done | - |
| R-05 | CreateChar HP (UltimaMain.c:809-810); Lord British HP rule (UltimaMain.c:2352-2387) | screens/roster_screen.py:401-402; entities/character.py:334-356 | LW starts a character at 100/100 HP; the port at 150/150 (Java and the classic releases; LW's own old creation code, UltimaMain.c:936-938, also gave 150). LW changed it on purpose: its level is max HP / 100 (Lord British adds 100 and drops a legacy +50), so porting 100 also means porting the Lord British HP rule (batch C). LW-only change from the classic game, so ask. | ask | open | - |
| R-06 | CreateChar MP (UltimaMain.c:794-796 zeroes byte 25, never set) | screens/roster_screen.py:411-420 | LW starts every character at 0 MP; the port starts a caster full (`compute_max_mp`). The port code marks this as a user-directed original-rules (C64) deviation, kept by the user's original-rules ruling (casters start with `compute_max_mp`), controller ruling R4. | keep | ruled-keep | - |
| R-07 | MaxMana (UltimaMacIF.c:1856-1879) | entities/character.py:293-311 | Checked equal: Wizard INT, Cleric WIS, Lark/Alchemist INT/2, Paladin/Illusionist WIS/2, Druid the greater half, Ranger the lesser half, Fighter/Thief/Barbarian 0. | same | done | - |
| R-08 | CharacterCreateDialog sex (UltimaMacIF.c:2291, 2500-2504) | screens/roster_screen.py:459-478 | Checked equal: Female, Male and Other can all be chosen (keep ruling 1 needs Other). LW pre-selects a random F/M; the port asks (UI). | same | done | - |
| R-09 | CreateChar free slot (UltimaMain.c:768-776); RosterSelect (UltimaMacIF.c:2152-2245); Create button (UltimaMacIF.c:2417-2418) | screens/roster_screen.py:35, 392-394, 480-488 | Checked equal: 20 roster slots, creation refused when full. Differences are UI only: LW checks before the dialog and the port after the stats; LW numbers fixed slots and the port lists compactly; LW greys Create on an empty name but always pre-fills a random one, the port fills `HeroN`. | same | done | - |
| R-10 | KillChar, TerminateCharacterDialog (UltimaMain.c:960-967; UltimaNew.c:38-114) | screens/roster_screen.py:269-306 | Checked equal: a party member cannot be terminated (menu item disabled, UltimaNew.c:72-73); terminating drops the record with all its items and gold (`Player[0]=0`, UltimaNew.c:93-96). The port's Y/N confirm is UI (GBC deviation). | same | done | - |
| R-11 | FormPartyDialog (UltimaNew.c:126-133, 205-232); ResetSosaria (UltimaMisc.c:757-810) | screens/roster_screen.py:172-235, 492-525; screens/start.py:239-266 | LW refuses to form while a party exists ("disperse first"), and forming starts a new game: on foot on Sosaria, move count 0, the Sosaria map, monsters, moon phases and location table reset (ResetSosaria, GetMiscStuff(0)). The port lets members be added to or removed from a saved party, and embarking keeps that party's position, moves and state, so fresh recruits can be swapped into a game in progress. A fix needs a new roster-screen flow (UI flow is deliberately not LW), so ask. | ask | open | - |
| R-12 | FormPartyDialog start tile (UltimaNew.c:222-225) | entities/party.py:225-226 | LW starts a new party at (42,20); the port at (44,20), a user-directed nit of 2026-11-15 (Java's (45,19) moved one south and one west) that is not in the keep list, so ask. | ask | open | - |
| R-13 | FormPartyDialog members (UltimaNew.c:205-216, 250-266) | screens/roster_screen.py:172-191; entities/party.py:483-495 | Checked equal: one to four members, in the order chosen; the same record cannot be chosen twice. | same | done | - |
| R-14 | FormPartyDialog / TerminateCharacterDialog by roster slot (UltimaNew.c:60-79, 157-185) | screens/roster_screen.py:172-191, 193-235, 269-306 | LW identifies a record by its roster slot and allows two characters with the same name in one party. The port identifies records by name: it refuses a second same-named recruit, and Remove/Terminate match by name (with two same-named records, Terminate can drop the wrong one). Moving the port to slot identity is a data-model change, so ask. | ask | open | - |
| R-15 | DisperseParty (UltimaMain.c:724-745) | screens/roster_screen.py:193-235 | Checked equal for the characters: LW clears every in-party flag and the party record; each character keeps all items, gold, HP and experience (they are the roster records). The port's Remove writes the member back with everything it carries. The party-record reset is R-11. | same | done | - |
| R-16 | ModifyOrder (UltimaMain.c:2096-2119) | screens/member_prompts.py:148-190; entities/party.py:524-536 | Swap is equal. LW accepts any two positions 1-4 without checking the party size: with fewer than four members, swapping with an empty position writes 0 into an occupied one (looks like an LW bug). The port refuses a position beyond the party size ("What?"). Same position twice: LW prints message 71, the port does nothing (message only). | ask | open | - |
| R-17 | Examine, DrawCharacterList (UltimaMain.c:590-628) | - | Checked equal: obsolete in LW (commented out of Organize); the port has no Examine. | same | done | - |
| R-18 | GetRoster/PutRoster, GetParty/PutParty (UltimaMisc.c:709-755) | save_system.py:89-175 | LW keeps 20 64-byte records in resources; the port writes JSON (keep ruling 5). PutParty writes only on Sosaria (`Party[3]==0`), as the port's `Q` saves only on the overworld (keep ruling 5). | keep | ruled-keep | - |
| R-19 | AddGold, AddExp record caps (UltimaMisc.c:470-500) | entities/character.py:322-360; combat/resolver.py:543-551; combat/magic.py:595-1118 | Gold caps at 9999 in both. Experience: LW caps at 9899 (`experience > 9899`), the port at 9999. The award sites are combat code, so the fix is left to batch B (AddExp owner). | port | open | - |

### T - Turn

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| T-01 | Pass, North, South, East, West (UltimaMain.c:1199-1260); main loop (UltimaMain.c:1057-1091); MapConstrain, GetXYVal/PutXYVal (UltimaMisc.c:982-998, 2545-2553) | screens/overworld.py:646-718, 1438-1515; screens/town.py:226-245, 352-420; ui/renderer.py:32-135 | Checked equal: one tile per arrow key, Sosaria wraps (MapConstrain), a town map reads as grass beyond its edge, Pass and any non-command key pass the turn. | same | done | - |
| T-02 | NorthEast..NorthWest, U3PrefNoDiagonals (UltimaMain.c:1041, 1070-1085, 1261-1325; PrefsDialog.m:105-130) | screens/overworld.py:646-655; screens/town.py:226-235 | LW's default (modern) preferences let the party step diagonally with 1/3/7/9 (a ship needs both component winds to allow it); the classic preset turns it off. The port is orthogonal only (README: "the party still can't"), as classic. LW-only option, so ask; recommend keeping the classic rule. | ask | open | - |
| T-03 | NoGo and the main loop's Routine6E35 after every arrow key (UltimaMain.c:1057-1091, 1203-1215, 3278-3282) | screens/overworld.py:1438-1515; screens/town.py:352-420 | LW prints INVALID MOVE! and still runs Routine6E35 (IncMoves, AgeChars, FinishAll), so a step refused by terrain or the wind takes the turn; the port refused it for free (the GBC wind block said "without consuming a turn, like any other blocked step"). | port | done | 7a475f4 |
| T-04 | ValidDir, on foot and horseback (UltimaMain.c:3169-3220) | ui/renderer.py:32-135; assets.py RULE_ATTRIBS | Checked equal for every tile in the surface and town maps: grass, brush, forest, dungeon, towne, castle, floor, chest, horse, frigate, lava and shrine pass; water, mountains, people, monsters, Exodus, walls, letters and snakes block; horse moves as foot. Inert differences: the port's horse may not enter a horse/frigate TILE (those tiles exist only on maps walked on foot) and has no force-field branch (Sosaria has no fields); magic (60) and fire (61) tiles appear in no map. Moongate tiles (0x22) in Castle British and Castle Exodus are walkable in LW: see W-01. | same | done | - |
| T-05 | ValidDir force field (UltimaMain.c:3178-3192) | world/tile_effects.py:79-148; ui/renderer.py:83-102; screens/overworld.py:1517-1540 | LW loops over the four party slots: the first member without the Mark of Force (byte 14 bit 0x10) takes 99 and the loop stops; passage is granted once any member before it had the mark (GoodPlace is set in the else branch and never cleared), so a marked first member lets the whole party through while the next unmarked one is struck; dead members and empty slots count. The port (user-directed GBC ruling 2026-11-14, not in the keep list) passes only when every living member is marked and strikes each unmarked living member for 99. Looks like an LW bug, so ask. | ask | open | - |
| T-06 | ValidDir lava (UltimaMain.c:3194-3207) | screens/overworld.py:1476-1492, 1553-1600; screens/town.py:385-397; world/tile_effects.py:151-243 | LW burns each living member without the Mark of Fire for 50 on the step ONTO lava; standing or passing there does nothing. The port (Java finishTurn) applied the effect of the tile being left, so a pass on lava burned and the step onto it did not. The flat 50 and the Mark of Fire were already equal, but the port also burned ashes (it skipped only the dead), turning them into the dead; LW burns only 'G' and 'P' (UltimaMain.c:3197-3199), so the tile effects now skip ashes too. | port | done | 7a475f4, c9f9a02 |
| T-07 | ValidDir aboard ship (UltimaMain.c:3174-3176) | ui/renderer.py:73-85 | Water and the whirlpool only, as the port's sailable water (the whirlpool is a prior port, `4e2bdea`). A parked frigate is its own map tile in LW (0x2C), so a ship could not sail onto it; the port let a ship sail onto a parked frigate object. | port | done | 9148832 |
| T-08 | ValidTrans, DoWind, ShowWind (UltimaMain.c:3222-3237, 3284-3337; FullUpdate 3339-3346) | screens/overworld.py:1438-1460, 1541-1551, 1595-1607; autoplay/nav.py:66-72; autoplay/threats.py:204-211 | Equal: a becalmed ship cannot sail, sailing into a headwind is refused, and the wind steers ships on Ambrosia too. Differences: (a) naming: LW's NORTH WIND (WindDir 1) refuses sailing north; the port's "Wind NORTH" refuses sailing south (`direction == wind.reverse()`); (b) timing: LW changes the wind in the animation loop every 33 FullUpdate ticks of real time (WindCtr 32, "SUPPOSED TO BE 8!"), idle or not; the port every 20th move; (c) odds: LW folds RandNum(0, 8) (> 4 minus 4), so calm 1/9 and each direction 2/9 before excluding the current wind; the port picks uniformly among the other four outcomes; (d) LW's wind is a preference (classic on, modern default off). The port follows the user-directed GBC wind ruling of 2026-11-14, which is not in the keep list, so ask. | ask | open | - |
| T-09 | IncMoves (UltimaMisc.c:531-548) | entities/party.py:686 | LW adds Party[2], the number of members (UltimaNew.c:210), per turn, in four base-100 digits capped at 99,999,999; the port adds 1, uncapped. A move count that steps by party size looks like a misreading of the 6502 counter, so ask. A port fix must give the wind re-roll (`moves % 20`) its own counter. | ask | open | - |
| T-10 | Routine6E35 town exit (UltimaMisc.c:1365-1369) | screens/town.py:352-397, 582-588 | LW leaves a town or castle as soon as a step lands on column 0 or row 0 (a step off the far edge wraps to 0), and that step is a turn; the port left only on a step off the map, one step later on the west and north sides, without the turn. | port | done | 7a475f4 |
| T-11 | FinishAll mounted cadence (UltimaMisc.c:1112-1119) | screens/overworld.py:1962-1985 | On horseback (0x14) or aboard ship (0x16) LW flips zp[0xCD] and spawns and moves monsters only every other turn; on foot every turn. The port ran them every turn whatever the transport. | port | done | aafd008 |
| T-12 | FinishAll time stop (UltimaMisc.c:1120-1125) | screens/overworld.py:1962-1990 | While gTimeNegate runs LW skips SpawnMonster as well as MoveMonsters; the port (Java) skipped only the moves and kept spawning. | port | done | aafd008 |
| T-13 | Routine6E35 with gTimeNegate (UltimaMisc.c:1357-1401; UltimaMain.c:2129-2139) | entities/party.py:694-776; aura.py | LW's stopped time only gates FinishAll: IncMoves, MoonGateUpdate, AgeChars (food, poison, regen) all run on; it counts down only on turns FinishAll gets past the mounted flip (20 turns on horse or ship). The port's QUICKNESS (user-directed GBC ruling 2026-11-14, README deviation 3, not in the keep list) freezes meals and moons and lasts 10 turns. Ask. | ask | open | - |
| T-14 | AgeChars cadence, EatFood rate (UltimaMisc.c:1403-1414, 1449-1453, 1468-1476) | entities/party.py:694-748; screens/overworld.py:1574-1580; screens/town.py:457-475 | Checked equal: AgeChars ticks every turn on Sosaria and every 4th turn while Party[3] > 0 (towns, castles, Ambrosia; the dungeon is batch D); each tick eats 10/100 food, one food per ~10 Sosaria turns and ~40 elsewhere. The port's 40 (Sosaria) and 10 (towns, Ambrosia) of a 400 pool give the same rates. | same | done | - |
| T-15 | EatFood borrow (UltimaMisc.c:1468-1490) | entities/party.py:742-745 | LW's borrow is `-= 157` on an unsigned byte, adding 99 instead of 100 (a binary port of the 6502's BCD), so 150 food lasts 1,476 surface ticks instead of ~1,500 and each hundreds borrow loses one more unit. Looks like an LW bug, so ask; recommend wontfix. | ask | open | - |
| T-16 | EatFood starvation (UltimaMisc.c:1477-1487) | entities/party.py:738-748 (`3fd97c2`) | LW: once a member's food is gone, every AgeChars tick underflows again: STARVING! and 5 HP each tick (every Sosaria turn, every 4th elsewhere). The port (user-directed GBC ruling 2026-11-14, `3fd97c2`, README deviation 3, not in the keep list) takes 5 only at a meal crossing (every 10th or 40th turn), including the crossing that takes the last food (LW takes nothing there). `3fd97c2` cites UltimaMisc.c:1428-1493 as corroboration, but LW's rule is per tick. Ask. | ask | open | - |
| T-17 | AgeChars HP regen (UltimaMisc.c:1412-1414, 1461-1462) | entities/party.py:738-748 (`3fd97c2`) | LW: +1 HP on every 10th AgeChars tick (gTime[1], one counter for the party: every 10th Sosaria turn, 40th elsewhere) for every living member, poisoned or starving included. The port (same GBC ruling, `3fd97c2`): +1 at each member's own meal crossing (same cadence), fed and unpoisoned members only. Ask. | ask | open | - |
| T-18 | AgeChars poison (UltimaMisc.c:1454-1460) | entities/party.py:780-830 | LW: -1 HP (POISON!) per AgeChars tick: every Sosaria turn, every 4th turn in towns, castles and Ambrosia. The port (user-directed 2026-11-10 interpretation, "every step") takes 1 every turn everywhere. Ask. | ask | open | - |
| T-19 | AgeChars status gate (UltimaMisc.c:1449-1452) | entities/party.py:728-735 | LW skips 'D' and 'A' members for food, poison and regen; the port skipped only the dead, so ashes ate. | port | done | 451297c |
| T-20 | AgeChars mana (UltimaMisc.c:1418-1447) | entities/party.py:780-830 | LW: +1 MP per AgeChars tick for every member (dead and ashes too: the status check comes after), so every 4th turn on Ambrosia; a Druid gets +1 for each half (INT/2, WIS/2) it is still below, so +2 only while under both. The port (user-directed 2026-11-10): +1 per turn on Sosaria and Ambrosia, every 4th turn in towns, Druid +2 up to max, living members only. Ask. | ask | open | - |
| T-21 | HPAdd (UltimaMain.c:3239-3248) | entities/party.py:748 | Checked equal: adds and caps at max HP. | same | done | - |
| T-22 | CheckAlive, CheckAllDead alive test (UltimaMain.c:2786-2798, 2895-2903) | entities/party.py:831-842 | LW counts only 'G' and 'P' members alive; the port counted ashes alive, so a party of the dead and ashes played on. | port | done | 451297c |
| T-23 | HPSubtract (UltimaMain.c:3250-3276) | entities/party.py:74-116 | LW: a member brought below 1 HP (exactly 0 included) is dead. The port (Java) kills only below 0; pending item 12 records this "0-hp-GOOD convention" as pre-existing, keep, but it is not in the keep list. Ask. | ask | open | - |
| T-24 | CheckAllDead resurrection (UltimaMain.c:2799-2893) | screens/base.py:40-85 | LW offers a resurrection when all are out: every member back to Good with 100 HP, 150 gold, readied Dagger and Cloth, food at least 100, items (bytes 35-63) and torches cleared, the party on foot at (42,20) and the world reset. The port (Java) ends the game at the start screen. LW-only addition, so ask. | ask | open | - |
| T-25 | Main loop idle pass (UltimaMain.c:1040-1056) | screens/overworld.py:606-718; screens/town.py:191-312 | LW passes the turn by itself when no key arrives during the 60-poll wait (and DoAutoHeal runs at poll 40); the port waits for a key. Real-time behaviour and a LW-only DoAutoHeal, so ask. | ask | open | - |
| T-26 | StatWait (UltimaMain.c:3424-3436) | - | Checked equal: a key wait, UI only. | same | done | - |
| T-27 | Routine6E35 Castle Exodus ball (UltimaMisc.c:1379-1398); ExodusCastle (UltimaSpellCombat.c:672-684); BombTrap (UltimaMain.c:1728-1740) | screens/town.py:457-511 | Each turn in Castle Exodus until Exodus falls, LW cancels stopped time and drops a ball on a random view tile (RandNum(0, 11) twice); on the party's (5,5), one turn in 144, each living member loses (RandNum(0, 255) & 0x77) + 8. The port had no such ball. | port | done | 560c62d |

### M - Monsters

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| M-01 | WhirlPool (UltimaMain.c:2959-3013) | screens/overworld.py:1962-2080 | Noted by batch T: LW moves the whirlpool in the idle loop (every 4th poll, real time), not with the monsters; the port moves it in `_update_creatures`, which since `aafd008` (T-11) runs every other turn aboard ship. Batch M to confirm (class provisional). | ask | open | - |

### C - Commands

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| C-01 | LetterCommand then Routine6E35 (UltimaMain.c:1057-1059) | screens/overworld.py:640-718; screens/town.py:226-312 | Noted by batch T: in LW every letter key, valid or refused or cancelled, ends with Routine6E35 and so takes a turn; the port follows each command's Java flow (some take the turn, some not). Batch C to check each command (class provisional). | port | open | - |
| C-02 | Enter town/castle positions (UltimaMain.c:1440-1455) | assets/xml/maps.xml:4-23 | Noted by batch T: LW enters towns at (1,32) and castles at (32,62); the port uses Java's (2,32), (5,32), (32,61) and (32,62). With T-10, LW's town exit west is one step from the entry. Batch C to confirm (class provisional). | port | open | - |
| C-03 | Negate Time (UltimaMain.c:2118-2139) | screens/overworld.py:1102-1116 | Noted by batch T: LW asks which member uses the powder; the port takes the first member with one. Batch C to confirm (class provisional). | port | open | - |

### S - Shops

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### W - World

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| W-01 | ValidDir moongate value 136, HandleMoonStep, MoonGateUpdate (UltimaMain.c:3209-3210; UltimaMisc.c:1373-1378, 1492-1507, 1569-1597) | assets/xml/tileset-base.xml:35 (`moongate` rule solid); entities/party.py:750-778 | Noted by batch T: the 0x22 gate tiles in Castle British (19-22,43) and Castle Exodus (29-34,9) are walkable in LW and send the party to a random grass tile of the map; the port's tile is solid. LW's moons turn only on Sosaria (Trammel every 12 turns, Felucca every 4; frozen in towns and on Ambrosia); the port's moons follow the GBC 4/16-move ruling. Batch W to confirm (class provisional). | port | open | - |
| W-02 | Routine6E35 exit test on Ambrosia (UltimaMisc.c:1365-1369; GoWhirlPool UltimaMain.c:3079 sets Party[3] = 255) | screens/overworld.py | Noted by batch T: Party[3] is 255 on Ambrosia, so `Party[3] > 1` holds there and reaching row or column 0 sends the party to Sosaria at zp[0xE3/0xE4]. Looks like an LW bug; batch W to classify (likely ask). | ask | open | - |

### B - Battle

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| B-01 | IncMoves callers (UltimaMisc.c:1359); AgeChars in combat (UltimaSpellCombat.c:921) | combat/arena.py:866 | Noted by batch T: LW counts moves only in Routine6E35, so combat rounds add none; the port's `end_turn(combat=True)` counts each round. LW also runs AgeChars in combat (README known item 4 says the port's MP regen does not tick there). Batch B to confirm (class provisional). | port | open | - |

### P - Spells

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### D - Dungeon

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|
| D-01 | AgeChars from the dungeon (UltimaDngn.c:188) | world/dungeon.py:1620-1655 | Noted by batch T: the dungeon calls AgeChars itself, which ticks every 4th call while Party[3] > 0; the T rows on food, poison, regen and mana (T-14..T-20) apply there too. Batch D to verify the cadence; ask while T-16..T-20 are open. | ask | open | - |

### A - Autocombat

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

