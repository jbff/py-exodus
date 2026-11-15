# Combat Interaction Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the combat cast/turn flow behave like the references: dynamic A–P letter maps with a printed spell list, context filtering that never offers chest spells in battle, turn consumed on executed-but-failed casts, no fabricated spell FX, and a visible active-member marker — with a headless play driver making key sequences executable tests.

**Architecture:** A new pure module `py_exodus/spell_menu.py` owns the castable-letter mapping (Java `Constants.getCastables` port); the three prompt flows (combat screen, overworld/town/dungeon shared prompt) consume it instead of fixed `Spell.code`. Turn consumption moves to an executed-vs-refusal rule (GBC battle loop + Java effects branches agree on the shape). The play driver is a test helper that pushes real key events through the state machine and records a transcript.

**Tech Stack:** Python 3.10+/Pygame-CE, pytest, no new deps.

**Spec:** the 2026-11-14 interaction-layer recon (GBC battle machine: `refs/ult3src/.../ult3.c:922-1025`, `battle.c:978-1393`; Java: `Constants.java:751-762` getCastables, `SpellInputProcessor.java:34-61` letter lookup + printed list; defect traces of 2026-11-14 on the three play bugs) — summarized in this plan; the recon outputs are quoted where load-bearing.

## Global Constraints

- Java is binding for the LETTER mapping and prompt text; GBC is binding for context availability (battle = no chest spells, no OTHER) and the executed-vs-refusal turn shape; divergences carry `USER-DIRECTED`/reference comments as usual.
- Existing deviations preserved: the 2026-11-11 APPAR_UNEM no-direction ruling (overworld flow), the debug `no_class`/`full_mp` cheat hooks, PILFERED!/POISONED! lines, the "ship-once" round ruling.
- Deterministic tests only (RNG-pin conventions; no bare global seeds).
- TDD; suite green twice before every commit; one commit per task with `Co-Authored-By: Claude Code <noreply@anthropic.com>`; never modify `refs/`, `ult3src/`, `/sto/src/`.

## Review Focus

1. **Letters move with state**: the map must compact as MP drops, profession, and context change (a wounded caster's `D` is not yesterday's `D`) — pinned by a test that re-maps the same cleric at two MP levels.
2. **`debug.CHEATS.no_class` and `full_mp` must flow through the new mapping** (no_class widens the list; full_mp bypasses the `cost <= mana` filter) — test on the combat prompt.
3. **Prompt text is the contract**: sequence tests assert prompt lines ("X's turn", list rows) like the player sees them, not internal state only.
4. **No fabricated FX regression**: any directional action whose spell is not a real projectile produces no tracer — test with APPAR_UNEM-class refusal + MITTAR-class real bolt both ways.
5. **Old behavior kept where ruled**: MP-too-low/B-cancel/target-cancel still leave the caster active (Java + GBC agree); overworld APPAR_UNEM still prompts nothing (2026-11-11 ruling) — tests pin both.

---

### Task 1: Headless play driver (test helper)

**Files:**
- Create: `tests/play_driver.py` (plain helper module imported by tests, not a pytest plugin)
- Test: `tests/test_play_driver.py`

**Interfaces:**
- Produces: `PlaySession` with `start(map_id=None, party=None) -> PlaySession` (boots the StateMachine via the existing test fixtures' asset_mgr pattern — read `tests/conftest.py` + `tests/test_book_of_lore.py` for how screens are constructed headless), `press(key) -> None` (builds the same `pygame.event.Event(KEYDOWN, key=...)` the harness tests use), `press_seq("C B N")` (space-split), `transcript -> list[str]` (every `text_log` message/prompt line appended since start, tagged), `active_member -> str | None`, `screen -> BaseScreen`. Nothing here mutates production code.

- [ ] **Step 1: Write the driver + smoke test** — a session boots the roster flow into the overworld (per existing test conventions) and `press_seq("Z")` shows Ztats: assert the transcript contains the zstats heading.
- [ ] **Step 2: Run** `uv run python -m pytest tests/test_play_driver.py -v` — PASS (this is infra; the FAIL-first requirement applies from Task 3 onward).
- [ ] **Step 3: Commit** `test: headless play driver for key-sequence transcripts`.

### Task 2: dynamic castable list (`spell_menu.py`)

**Files:**
- Create: `py_exodus/spell_menu.py`
- Modify: `py_exodus/combat/magic.py` (`resolve_spell` letter lookups ~243-247; the three prompt builders: combat path in `combat_screen.py:227-300`, shared prompt `magic.py:1130-1310`)
- Test: `tests/test_spell_menu.py`

**Interfaces:**
- Produces: `get_castables(caster, context: str, *, cheats_ok: bool = True) -> list[tuple[str, Spell]]` — `context` ∈ {"combat","world","city","dungeon"}; walks the `Spell` enum in declaration order; filters `Spell.spell_type` discipline by the caster profession (cleric-type vs wizard-type, incl. the druid/ranger dual gate and the alchemist/lark gate per Java `Constants.java:751-762` — port that walk), `can_cast(profession)` (respecting `debug.CHEATS.no_class` widening), the `location_mask` (`constants.py:313-321`, now LIVE) vs the context, and `mp_cost <= mana` (skipped when `full_mp` cheat on). Letters assigned `"A","B",...` sequentially. `spell_menu_prompt_lines(castables) -> list[str]` formats the printed list per Java `SpellInputProcessor.java:36-39` (letter, name, cost — read the Java format and match it, cost omitted for 0).
- Consumes: `py_exodus/constants.py` Spell entries (code/enum order, `mp_cost`, `location_mask`), `debug.CHEATS`.

- [ ] **Step 1: failing tests** — full-MP cleric in "combat": castables == [A=PONTORI, B=SANCTU, C=ALCORT, D=SANCTU_MANI, E=EXCUM/EXCUUN per the enum's real name, F=SURMANDUM? NO — location masks govern: assert the exact list against the live enum per the Java algorithm; do NOT copy GBC's menu contents — the Java filter is the truth; APPAR_UNEM (mask city|world|dungeon) absent in "combat"]; wizard in "combat" == the 11-entry walk in enum order; the same cleric at MP 3 drops >3-cost entries (letters compact — PONTORI is 0-cost so stays A); APPAR_UNEM present in "world" list; a barbarian's list in combat is empty.
- [ ] **Step 2:** red. **Step 3:** implement. **Step 4:** green. **Step 5:** commit `feat: dynamic castable spell mapping per Java getCastables`.

### Task 3: the three prompt flows consume the mapping

**Files:**
- Modify: `py_exodus/screens/combat_screen.py:227-300`, `py_exodus/combat/magic.py:1130-1310`
- Test: `tests/test_play_driver.py` (extend), `tests/test_spell_menu.py`

**Interfaces:**
- Consumes: `get_castables`/`spell_menu_prompt_lines`.
- Produces: every cast prompt prints the list rows before reading the letter; the letter lookup resolves through `get_castables` (unknown letter → "Unknown spell!" replaced with the canonical no-op silence Java has for out-of-range letters — verify: SpellInputProcessor ignores non-A..P-mapped keys silently :84-116; implement silence). The 2026-11-11 overworld APPAR_UNEM no-direction ruling is implemented at the dispatch layer of the WORLD flow only (unchanged behavior); combat keeps the Java direction prompt shape.

- [ ] **Step 1: failing sequence tests via the driver** — combat, cleric with enough MP: `press_seq("C")` → transcript contains the list rows and NOT "Cast: Which member?"; `press_seq("C A")` on skeletons with masskill False → the FAILED result and a follow-up turn for the same member (Task 4's rule pins the consumption — here assert the prompt re-opens for the same caster after a NON-executed refusal). `press_seq("C D")` with 3 MP on a >3-cost spell at D → "Thou dost not have enough magic points!" is gone (not offered); pressing a letter beyond the list length does nothing silently.
- [ ] **Step 2:** red. **Step 3:** implement both flows (combat + shared). **Step 4:** green + full suite ×2. **Step 5:** commit `feat: cast prompts print the live A-P list and map letters dynamically`.

### Task 4: turn-consumption rule — executed vs refused

**Files:**
- Modify: `py_exodus/combat/arena.py` (`_handle_player_cast` ~748-790, the `consume_turn = ...` site), `py_exodus/combat/magic.py` (PONTORI/REPOND masskill-fail paths ~520-590: mark them as EXECUTED failures)
- Test: `tests/test_combat_arena.py`, `tests/test_play_driver.py`

**Interfaces:**
- Produces: `SpellResult` gains `executed: bool = True` (execution happened even when `success=False`); masskill-gate FAILED sets `executed=True, success=False`; pre-execution refusals (the gates) keep `executed=False`; `consume_turn = bool(res.executed and spell_res resolved not in NO_TURN_SPELLS)` — replacing the P6 `success`-based rule. The GBC table's non-consuming refusals stay non-consuming: MP too low (now unreachable post Task 2 for >mana, still reachable for 0-cost… keep the gate), B-cancel, target-cancel, wrong-class.
- [ ] **Step 1: failing tests** — masskill False → PONTORI "FAILED" CONSUMES the turn (monster phase follows); mana-refusal (direct API call bypassing the menu) still leaves caster active; menu B-cancel leaves caster active; ALTAIR stays NO_TURN.
- [ ] **Step 2:** red. **Step 3:** implement. **Step 4:** green + suite ×2. **Step 5:** commit `parity: executed-but-failed casts consume the turn (GBC battle.c:1052; refs P6 over-breadth)`.

### Task 5: no fabricated spell FX

**Files:**
- Modify: `py_exodus/screens/combat_screen.py:464-486` (the synthetic-path fallback) — gate to real projectile spells only (`Spell.MITTAR/FULGAR/MENTAR/DECORP/EXCUUN`); the action must carry the resolved spell (pass it through `Action.cast` if not already).
- Test: `tests/test_play_driver.py` + combat FX unit test.

- [ ] **Step 1: failing test** — combat, `press_seq("C <cleric-list letter for a non-projectile>")` … simpler: direct `Action.cast(APPAR_UNEM, direction=NORTH)` on the world flow and a combat refusal: assert `_render_combat_fx` receives NO path for the refusal; MITTAR cast still produces its real path.
- [ ] **Step 2:** red. **Step 3:** implement the gate. **Step 4:** green + suite ×2. **Step 5:** commit `fix: tracer FX only for real projectile spells`.

### Task 6: active-turn affordance

**Files:**
- Modify: `py_exodus/screens/combat_screen.py` — prefix the command prompt region with `"{name}'s turn"` when the active member's turn begins and after each non-consuming action returns to them; keep the zstats-side inspection as-is.
- Test: `tests/test_play_driver.py`.

- [ ] **Step 1: failing test** — combat: after the member activates, the transcript contains `Thou: <name> — Attack, Cast...`-style line exactly once per activation (pick the port's message style; GBC's equivalent is the blink cursor + stat window — the text log is this port's channel). After a FAILED cast (turn retained), the SAME marker appears again but no member-advance occurred (assert active member unchanged).
- [ ] **Step 2:** red. **Step 3:** implement. **Step 4:** green + suite ×2. **Step 5:** commit `feat: active-member turn marker in combat`.

### Task 7: context-availability audit vs GBC tables (matrix dry-run)

**Files:**
- Test: `tests/test_spell_menu.py` (audit-style), `py_exodus/constants.py` (only if a mask is provably wrong vs Java — mask cites Java `Constants.java:710`-region values)

**Interfaces:** Consumes `get_castables`.

- [ ] **Step 1: failing audit tests** — for each context ∈ {combat, world, city, dungeon} × cleric/wizard: the castable list must equal the Java-mask walk (recompute independently in the test from the enum attributes); then cross-check against the GBC battle lists (cleric battle 6: PONTORI SANCTU ALCORT SANCTU_MANI EXCUM ZXKUQYB; wizard battle 11: REPOND MITTAR FULGAR MENTAR FAL_DIVI NOXUM DECORP ALTAIR DAG_MENTAR NECORP UNSPEAKABLE) — where the Java-mask walk and the GBC menu disagree for "combat", the test asserts the JAVA list and a comment records the GBC delta (GBC omissions are its own curation; Java governs letters — this is a documented ruling: cite it). Note: FAL_DIVI re-entering the cleric menu mid-combat already works (D4); wizard battle list must contain NO DAG_ACRON in "combat".
- [ ] **Step 2:** red (any mask/enum mismatch surfaces here — fix the mask value with the Java cite, not the test). **Step 3-5:** implement/commit `parity: context spell availability audit (Java masks; GBC deltas documented)`.

### Task 8: the user's scenario as a regression test

**Files:**
- Test: `tests/test_play_driver.py`

- [ ] **Step 1: write the failing sequence test** — combat vs skeletons, cleric active: `C` prints the list with SANCTU at some letter and no APPAR_UNEM anywhere; pressing an unmapped letter does nothing and the marker persists; casting the masskill-gated spell with flag False consumes the turn (monster phase runs); the cleric is NOT re-prompted as caster on the next C (no "Which member?" in combat at all).
- [ ] **Step 2:** verify red against pre-Task-3 behavior only if run in isolation — with Tasks 2-6 landed this is green; its value is regression-pinning the exact play report. If green at write time, note it and commit as part of the batch.
- [ ] **Step 3:** full suite ×2. **Step 4:** commit `test: cleric combat cast loop regression (play report 2026-11-14)`.
