# PyExodus — Session Handoff (2026-11-15, written at machine shutdown)

Read this first when resuming. It records what landed, what was learned, and what is left. The standing backlog remains in `2026-11-13-pending-items.md` (items 21-34 current numbering); this doc carries the newer session-specific thread.

## Project state at shutdown

- master `c62dfe4`, pushed; suite 1119 green (playtest-2 was killed mid-run; no uncommitted work).
- Latest user rulings (all in code comments, grep `user ruling|USER-DIRECTED|2026-11-15`): fixed spell letters (B=APPAR_UNEM always; full 16-row menus; "Not Here!" at attempt; MP refusal at letter-selection BEFORE On who?/Direction?); new-party spawn (44,20) — from_dict x/y-less fallback deliberately stays (45,19) (legacy save-format truth, pinned by test); ZXKuqyb de-bugged (fair 75%-per-monster kill per LW BigDeath); monster-hit affordance lines (hits+deaths only, user-approved deviation from Java silence); creature spawns ported to Java's `getRandomCreatureForTile` party-average-max-HP tier tables (exclusive high bound preserved — a level-1 party avg ≤300 CANNOT roll Pincher/17+; Giants gone at low levels — confirmed real divergence fix).
- Evidence refs: `refs/ult3src/` (GBC), `refs/ultima3/` (LairWare C), `refs/nes_ultima_3_disassembly/` (NES). Java source still at `/sto/src/gdx-exodus` (verified present).
- User's roster in `saves/roster.json`: SHADOW (elf thief D25 S15), GRUMM (dwarf fighter S25 D15), SERENA (bobbit cleric W25 S15), ZIRCON (fuzzy wizard I25 S15), L1, no party.json. User plays this party; wants Thief→Fighter→Cleric→Wizard order. Backups: `saves/*.bak-2026-11-15.json`.
- Analysis page committed? NO — `docs/analysis/exodus-party-blueprint.html` (party optimization) and `docs/analysis/journal.md` were added at shutdown — COMMIT THEM FIRST THING (they were staged for the shutdown session; this doc says so; git add + commit `docs: party analysis page + playtest journal salvage`).

## What landed this session (reverse order)

1. Spawn nit c62dfe4: (44,20) at Party defaults + roster_screen inherit.
2. ZXKuqyb fix a04012d.
3. Playtest-1 fixes batch 94c2b75: creature spawn health-tiers (d411751), vendor prompts mirror Java strings (6d45fb4), town labels via Maps enum "Entering Britain!" (a07dc2e), monster-hit affordance lines (94c2b75).
4. Fixed-letters amendment 227bad9 (+ F1 676bb51: spell_menu.py fixed A-P, "Not Here!" at attempt; F2: MP refusal at letter selection before target/direction prompts).
5. Combat-interaction batch 81ec58c..98d8768: headless play driver tests/play_driver.py (transcript harness), spell_menu module, executed-vs-refused turn rule (executed-FAILED consumes; prevalidation refuses don't), tracer-FX gated to real projectiles, "X's turn." markers, availability audit (32 Java mask rows verified vs Constants.java:693-724), Book appendix relabel.
6. GBC-parity batch 81ec58c (44th master): A1-A12 bugs, B-rules per 2026-11-14 GBC ruling, D1 cheat harness (--debug, F10, runtime-only), D2 save integrity envelope (U3PY + crc32), D3 Other commands (bribe/steal/dig/pray/search/score py_exodus/special_commands.py), D4 VIEDA/FAL_DIVI unstubbed.

## Differential spike verdict (gameplay-verification strategy, docs/superpowers/plans/2026-11-14-gameplay-verification-strategy.md)

FULL headless proven: the gdx-exodus jar (at ~/.m2/repository/gdx-exodus/gdx-exodus/1.0.1/, 30MB) runs its logic layer with zero GL. Spike artifacts in /tmp/java-spike (WILL BE LOST on shutdown — the skeleton: HeadlessProbe.java ~180 lines, JDK 25, loads XML/ults via getResourceAsStream, `Exodus.hud` swap to a LogDisplay subclass capturing log lines, reflection healthBar shim, party getters, SaveGame.write for canonical snapshots). Harness shape documented in the spike report: init shim ~150 lines (+ HeadlessAtlas no-op), input→dispatch ~300 lines re-implementing Java keyUp/finishTurn faithfully, seeded XORShiftRandom alignment with the port. Est. 2-4 days agent-work. NOT yet built — decision deferred by user (token cost).
Jar path correction for resume: the earlier reviewer's path `/sto/src/gdx-exodus/src/main/resources/...` is the SOURCE tree; the jar in this machine's maven cache is confirmed buildable/running.

## Play-testing (the current phase; user-approved plan)

Phase: simulated-human playtests with the transcript driver (NOT the exhaustive matrix — deferred). Cadence: full sessions, consolidated reports, interim status pings.
- Playtest 1 (done, findings all fixed except notes below): found creature-roll uniformity (fixed), monster-attack invisibility (affordance lines added), vendor loop (fixed), town labels (fixed). Report /tmp/playtest-report.md (WILL BE LOST; substance captured in the commit messages + findings above).
- Playtest 2 (KILLED mid-run at user shutdown — restart instructions below): journal salvaged at `docs/analysis/journal.md`. Progress: boot→spawn verified→Castle visited (LB refuses advance at 0 exp, correct)→Britain shops exercised (all flows incl. distinct vendor prompts verified live; prices exact; food-gating "You can only afford 0 packs." verified)→bought Sling/Mace×2/Dagger/Cloth×4 + rations→equipped all (Success!)→positioned at Britain market awaiting overland fights. NEXT when resuming: (a) exit Britain, verify low-tier spawns (no Giants at L1), monster-hit lines in battle, killer-only exp; (b) grind to 100 exp for one LB advance; (c) Dardin descend/climb per walkthrough; (d) Q-save/reload; (e) judge against walkthrough https://wiki.ultimacodex.com/wiki/Ultima_III_walkthrough.
- Playtest-2 finding already filed: YELL "Yell what?" prompt — empty ENTER does not submit, ESC does not cancel (softlock-ish; a word+ENTER escapes). ADD to pending-items as a candidate fix (compare Java's YellInputAdapter).
- Strategy doc (committed): differential spike verdict "full headless" (above), matrix burn-down plan, workable-core gate (~20 scenarios). User approved spike + approved phase-1-in-principle but deferred the thorough execution for token cost; current phase = simulated-human playtests.

## Deferred follow-ups ledgered during the session (NOT yet in the repo backlog; ADD to pending-items on resume)

35. Overworld boot + dungeon entry strings still ad-hoc ("Entering the realm of Sosaria...") vs Java Maps labels everywhere (reviewer note on a07dc2e).
36. Vendor prompt comment citations drifted ~18 lines (strings correct); touch-up in any next vendor commit.
37. ESC at a vendor prompt dangles the dialog (text_log handle_escape drops callback; vendor state not closed — user-visible? needs a check; implementer flagged out-of-scope).
38. Dungeon entry uses the enum key in some path (dungeon_screen.py:83,107 name source) — normalize to Java labels.
39. Suite-wide: one stream-sensitive unseeded test remains latent somewhere (hermetic_rng in play_driver masks the driver's own footprint; identify + seed once reproduced). Also test_party_save.py:716 comment ambiguity ((45,19) is file-format truth now that Party default is (44,20)) — cosmetic.
40. YELL softlock-ish prompt (playtest 2, above).
41. Playtest 1 unexercisable-then: ZXKuqyb masskill (70MP), 9999 gold cap, healer Resurrect — exercise in a future session.

## Resume procedure

1. Commit the docs/analysis files (this doc's first task).
2. Read 2026-11-13-pending-items.md (21-34) + this doc's deferred list (35-41): port them in, keep numbering.
3. Restart playtest 2 from the journal (driver loop script /tmp/play2/loop.py is lost; rebuild a simple key-FIFO loop or drive via PlaySession directly in a pytest-style scratch — the F1-era session notes in docs/analysis/journal.md carry the harness/DX traps: compass-token shadowing in press_seq, prompts read event.unicode so y/n must be sent with unicode or raw K_ keys).
4. After playtests: propose the fix batches; the matrix burn-down + differential jar harness remain the deferred big-ticket items awaiting the user's token-cost call.
5. Suite baseline: 1119; ensure green ×2 per commit, worktree SDD flow, merge+push per fix.
