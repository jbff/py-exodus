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

