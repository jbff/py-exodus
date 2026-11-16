# PyExodus — Comprehensive Work-in-Progress Brief + Fresh-Agent Prompt

Written 2026-11-16 for session handoff. This file is the complete context a fresh agent needs; the short prompt at the end (§5) is what the owner pastes into a new session, pointing here.

## 1. The project and why

**py-exodus** (`/sto/prj/py-exodus`, Python 3.10+/Pygame-CE, master @ `fdfc4fb` pushed) is a faithful re-implementation of *Ultima III: Exodus* (1983), ported from the LibGDX Java reference implementation `gdx-exodus`. The owner's goal: a **workable, mechanically faithful game** — not pixel-perfect, but every basic mechanic behaving as the references say. The owner plays it personally and reports issues; we are in a **verification-driven phase** whose purpose is to stop dependence on the owner's individual bug reports by playing the game ourselves with transcripts, fixing what misbehaves, and banking every fix as a transcript regression.

**Three verification references exist, in a decided precedence chain** (rulings recorded in in-code comments; do NOT "fix" any of them back):
1. **Java** (`/sto/src/gdx-exodus/src/main/java/`) — day-to-day parity truth (including its bugs, unless a ruling says otherwise).
2. **GBC port** (`refs/ult3src/`, 2026-11-14 ruling) — wins over Java where they disagree (GBC was ruled closer to the original for combat/lethality rules).
3. **NES disassembly** (`refs/nes_ultima_3_disassembly/`) + **LairWare C** (`refs/ultima3/`, Apple II-derived with memory-location comments) — where **LW+NES agree** and differ from the port, they win (2026-11-14 re-ruling). Never port LW-only conveniences (auto-cast, TERRAFORM/ARMAGEDDON/FLOTELLUM, Alchemist bonuses); never copy reference bugs (NES 5MP Star; LW inverted pit polarity); LW's *deliberate* quirks ARE parity (e.g. shrine lump-sum over-debit).
4. **Latest user ruling wins everything** (see §3).

## 2. Architecture and working discipline (non-negotiable)

- **Process:** every fix = a git worktree branch, TDD (failing test first), full suite green **twice** before each commit, implementer subagent → reviewer subagent (SDD), merge to master + push after clean review. One commit per task, `fix:`/`feat:` prefixes, `Co-Authored-By: Claude Code <noreply@anthropic.com>` footer. Plans live in `docs/superpowers/plans/`.
- **Key modules** (all under `py_exodus/`): `combat/{arena,resolver,magic}.py` (the GBC-ruled combat engine), `screens/*` (per-context screens; `overworld.py` is ~2000 lines), `world/{dungeon,map_build,...}.py`, `spell_menu.py` (fixed-letter cast menus), `special_commands.py` (Other commands), `debug.py` (cheat harness, `--debug` flag), `save_system.py` (JSON envelope: magic `U3PY` + crc32), `entities/{party,character,defs}.py`.
- **The verification instrument:** `tests/play_driver.py` — a headless harness that boots the real StateMachine, feeds the same `pygame.KEYDOWN` events a player types, and records transcripts (prompt lines, messages, active member). Driver DX traps are documented in `docs/analysis/journal.md` (compass-token shadowing in `press_seq`; prompts read `event.unicode`).
- **Evidence:** GBC text arrays are tile-encoded; decode with `python3 -I /tmp/u3decode.py <file.c> [array]` (recreate the script from `py-exodus parity workflow` section below if lost — it maps `'X'+0x1D` → X, 0x5D→space, etc.). Java source verified present at `/sto/src/gdx-exodus`; the runnable jar is at `~/.m2/repository/gdx-exodus/gdx-exodus/1.0.1/gdx-exodus-1.0.1-jar-with-dependencies.jar`.

## 3. User rulings (latest-wins; each carries an in-code `USER-DIRECTED ... DEVIATION (date)` comment — never revert any)

- **2026-11-15 — FIXED SPELL LETTERS:** A–P lists are the original-game alphabetical per-discipline lists (enum `code` fields; cleric B=APPAR_UNEM *always*). Menus print the full 16 fixed rows; availability is refused **at attempt** ("Not Here!" for location mismatches incl. combat; canonical MP refusal at letter-selection, before target/direction prompts; both not-executed, caster stays active, menu disarms). Supersedes the Java getCastables compaction adopted 2026-11-14.
- **2026-11-14 — GBC wins** for the ~27 audited divergence items (combat dice/hazards/spawn rules); **LW+NES-agree wins** where both newer refs state the same thing.
- Monster-hit affordance lines approved (hits + deaths only, misses silent) — deliberate deviation from Java's silence; same class as the "X's turn." markers.
- ZXKuqyb de-bugged: fair 75%-per-monster kill roll (LW BigDeath; Java's `hp*3/4==0` quirk removed).
- New-party spawn (44,20) (one south + one west of Java's (45,19)); legacy x/y-less save fallback stays (45,19).
- Q-save only on Sosaria; no default party; Sex=M/F/O; casters start with computed max mana; mass-kill spells use a per-battle 50% latch; executed-but-failed casts consume the combat turn, pre-execution refusals don't.
- Magical Orbs removed; no starter party; portraits removed; victory fanfare once; dungeon-meal cadence adopted; whirlpool ships-only same-tile.

## 4. State at handoff (master `fdfc4fb`, pushed; suite 1119-with-1-environmental)

- **Roster:** `saves/roster.json` = the owner's four optimized characters (SHADOW elf thief DEX25/STR15, GRUMM dwarf fighter STR25/DEX15, SERENA bobbit cleric WIS25/STR15, ZIRCON fuzzy wizard INT25/STR15; L1, 150 gold/food). `saves/party.json` = a RESUMABLE playtest-2 save (the four at Sosaria (52,27), 276 moves) — keep it. `party.bak-2026-11-15.json` = the old pre-session party. **Back up saves with timestamps before any pre-run wipe** (a prior instruction destroyed the owner's own morning save without one — never repeat).
- **Known failure:** `tests/test_play_driver.py::test_journey_onward_then_zstats_heading` fails with the mid-session save present — transcript shows only map-entry lines, no Zstats heading after F1. Diagnose FIRST on resume: test assumption (Journey state differs) vs a real "F1 after a loaded Journey doesn't open the Book" bug. Either way: scope the test or fix the bug; the suite must return to full-green.
- **Phase:** simulated-human playtests with the transcript driver (the owner explicitly deferred the exhaustive interaction-matrix burn-down and the Java differential harness for token cost — do not start those without a fresh instruction; the strategy is in `2026-11-14-gameplay-verification-strategy.md` and the differential spike verdict ("FULL headless proven") is in the same file's sibling handoff).
- **Immediate queue at handoff:** (a) the F1/Journey diagnosis above; (b) restart playtest-2 from its salvaged journal `docs/analysis/journal.md` (it had verified shop flows/equipment and was positioned for overland fights; goal per owner: follow the Codex walkthrough `https://wiki.ultimacodex.com/wiki/Ultima_III_walkthrough` with strategy — buy, wander, fight, chests, spells, dungeon marks, level-ups through **level 6**, Q-save/reload — judging "does it behave properly?"); (c) port deferred follow-ups 35–41 (listed in `2026-11-15-session-handoff.md` §Deferred) into `2026-11-13-pending-items.md` (items 21–34);
 (d) report findings to the owner, propose fix batches, execute with the SDD loop.
- **Known softlock-ish finding already filed:** YELL "Yell what?" — empty ENTER doesn't submit, ESC doesn't cancel.

## 5. THE PROMPT (paste into the fresh agent session)

```
You are resuming py-exodus at /sto/prj/py-exodus (Pygame-CE port of Ultima III; master fdfc4fb pushed). READ FIRST, in order:
1. docs/superpowers/plans/2026-11-15-session-handoff.md  (authoritative state + resume list)
2. docs/superpowers/plans/2026-11-13-pending-items.md    (backlog, items 21-34)
3. docs/superpowers/plans/2026-11-14-gameplay-verification-strategy.md  (the verification strategy; matrix burn-down is DEFERRED — do not start it without instruction)

Rules that outrank your defaults:
- Parity precedence: Java (/sto/src/gdx-exodus) is truth unless a newer in-code comment (grep "USER-DIRECTED|user ruling|2026-11-15") says otherwise; GBC (refs/ult3src) and LairWare (refs/ultima3) corroborate; where LW+NES agree they win (2026-11-14); spell letters are FIXED per the 2026-11-15 ruling (B=APPAR_UNEM always — "Not Here!" refusals at attempt, letters never move). NEVER revert any recorded ruling.
- Work strictly via worktree+SDD: failing test first, full suite green TWICE per commit, implementer→reviewer subagents, one commit per task, merge+push after clean review. Never modify refs/, ult3src symlink, or /sto/src. Back up saves/party.json with a timestamp before anything that could wipe it (this destroyed a user save once already — never repeat).
- Current phase: simulated-human playtests (headless driver tests/play_driver.py; PlaySession.press_seq/transcript). Play like a human with strategy and judge "does what happen make sense?" — findings go to the owner with evidence and root causes, then fix batches. The matrix burn-down and Java differential harness are deferred.

Your first three tasks, in order:
1. Diagnose the failing test test_play_driver.py::test_journey_onward_then_zstats_heading (runs with the resumable save in saves/party.json — party at Sosaria (52,27)): test assumption vs real "F1 after a loaded Journey opens no Book" bug; fix accordingly; suite must return to full green.
2. Restart playtest-2 from its journal (docs/analysis/journal.md): continue the session from the resume save — overland fights (verify low-tier spawns, monster-hit lines, killer-only EXP), level the party via Lord British toward level 6 following https://wiki.ultimacodex.com/wiki/Ultima_III_walkthrough (adapt to killer-only EXP), Dardin descend/climb, Q-save/reload round-trip. Report anomalies by severity with key sequences + transcript excerpts; give me interim status notes every few milestones.
3. Port follow-ups 35-41 (listed in the handoff doc) into the repo backlog, then propose the next fix batch for my approval before implementing.

The owner values progress visibility: brief periodic updates on where you are and what didn't work. Report surprises; do not silently produce work you're unsure of.
```
