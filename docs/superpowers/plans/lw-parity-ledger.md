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

### M - Monsters

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### C - Commands

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### S - Shops

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### W - World

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### B - Battle

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### P - Spells

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### D - Dungeon

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

### A - Autocombat

| ID | LW function (File.c:lines) | Port (file:lines) | Difference | Class | Status | Commit |
|----|----------------------------|-------------------|------------|-------|--------|--------|

