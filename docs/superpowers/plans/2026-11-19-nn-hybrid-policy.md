# NN Hybrid Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a phased, gated hybrid EV + compact PyTorch neural policy (`<= 5M` params, `< 500 MB` VRAM on RTX 3050 6 GB) that improves unassisted (`nohurt=False`) A-to-Z win rates above the symbolic controller while keeping engine files untouched.

**Architecture:** Phase 0 replaces brittle `if/elif` goal priority in `py_exodus/autoplay/planner.py` with an expected-value (EV) utility scorer whose feature vector doubles as the Phase 3 macro-critic input. Phases 1–2 train a compact `1–3M`-param CNN+MLP tactical combat policy (`CombatScreen` 11×11 grid, 5–30 turn episodes) via outcome-filtered BC followed by PPO. Phase 3 trains a `1–5M`-param macro critic warm-started from winning trajectories (`seed=437` et al.) and gates any full-game PPO on beating the symbolic baseline on held-out seeds `900–999`.

**Tech Stack:** Python 3.14, `pygame-ce` (headless `dummy` driver), PyTorch (CUDA on RTX 3050 6 GB), `pytest` (`1,263` existing tests).

---

## Global Constraints

1. **Hardware & Model Ceiling:** Target GPU is `NVIDIA GeForce RTX 3050, 6144 MiB`. All models must stay `<= 5M` parameters and `< 500 MB` VRAM (including optimizer states & rollout batch).
2. **No LLM-in-the-Loop:** Zero per-step LLM calls at any stage (`112,074+` steps per full game makes any per-call latency unbudgetable for PPO).
3. **Reward Shaping (Anti-Rat-Farm):** Reward is milestone-shaped (marks, cards, exotics, Exodus panel/victory events) plus step penalties and episode timeouts — **never** raw XP or gold payout alone.
4. **Seed Hygiene:** Training seed block = `0–899` (existing dev sweeps `400–524` remain strictly in training). Held-out evaluation block = `900–999`. Holdout seeds `900–999` are **never** trained on, not even once.
5. **Engine Integrity:** Engine files (`py_exodus/screens/*`, `py_exodus/entities/*`, `py_exodus/world/*`, `py_exodus/combat/*`) stay **untouched**. All NN code lives in a new sibling package `py_exodus/nn/`. The `1,263`-test suite stays green throughout.
6. **Engine as Arbiter:** NN proposes an action; the engine/interface masks illegal actions before execution (`nav.py` stays symbolic).
7. **Disagreement Mining:** Log every NN-vs-symbolic clash; episodes where the NN wins after disagreeing with the symbolic rule become labeled review data for fixing weak symbolic rules.
8. **Eval Protocol:** Every phase evaluation runs `N` games on holdout seeds `900–999`, reporting win count, survival count, and all deaths itemized by cause and `(map_id, x, y)` tile.
9. **Commit Provenance:** Every trained checkpoint records the exact `git rev-parse HEAD` SHA it trained against; never train across untagged engine/controller changes.

---

## 1. Mandatory First Measurement: Headless Environment Throughput

Measured on this machine (`2026-11-19`, commit `cdf218d`, `SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`, full `StateMachine` + `OverworldScreen` + `AutoPlayController.step` + `sm.update(0.05)`):

| Mode | Measured Work | Wall Time | Throughput |
| :--- | :--- | :--- | :--- |
| **1x Single-Process** (`seed=437`) | `10,000` steps | `8.28 s` | **`1,208.2 steps/s`** |
| **10-Parallel (`fork` Pool)** (`seeds 437–446`) | `86,473` steps | `14.70 s` | **`5,880.5 aggregate steps/s`** (`588.1 steps/s` per worker) |
| **GPU** | `nvidia-smi` | — | **`NVIDIA GeForce RTX 3050, 6144 MiB`** |

### Throughput Gate & Budget Arithmetic
- **Gate (`>= ~300 steps/s` at 1x):** **PASSED** (`1,208.2 steps/s` is `4.0x` the `300 steps/s` threshold). No dedicated sim-speed optimization workstream is required before Phase 2 PPO.
- **Full-Game Episode Length:** Observed unassisted win `seed=437 WON@112,074` steps (`112k` steps/episode; `522 WON@112,667`; `472 WON@134,745`; `471 WON@149,406`).
- **Corrected Step & Wall-Time Budgets:**
  - **Phase 2 (Combat PPO, 5–30 turn episodes):**
    - `2M` steps @ `5,880.5 steps/s` (10-parallel) = `~5.7 min` (`~27.6 min` at 1x `1,208.2 steps/s`).
    - `10M` steps @ `5,880.5 steps/s` (10-parallel) = `~28.3 min` (`~2.3 h` at 1x).
  - **Phase 3 (Macro Critic Light PPO Fine-Tune, ~`112,074` steps/full game):**
    - `10M` steps (`~89` full games) @ `5,880.5 steps/s` = `~28.3 min` (`~2.3 h` at 1x).
    - `50M` steps (`~446` full games) @ `5,880.5 steps/s` = `~2.4 h`.
- **VRAM Budget (`RTX 3050 6144 MiB`):**
  - Phase 2 Combat CNN+MLP (`1–3M` params, fp32 + AdamW + `2048`-step rollout buffer): `~40–120 MB` VRAM (`< 2%` of 6 GB).
  - Phase 3 Macro Critic MLP (`1–5M` params, fp32 + AdamW): `~60–180 MB` VRAM (`< 3%` of 6 GB).
  - Concurrent Phase 2 + Phase 3 inference footprint: `< 250 MB` VRAM, well below the `500 MB` cap.

---

## Review Focus (Key Failure Modes to Pin)

1. **Food-runway / gold-target mismatch:** Buying food drops gold below `4500g`, flipping `SAIL_WHIRLPOOL` back to `GRIND_AND_LEVEL` instead of completing the Ambrosia prep loop.
2. **Poisoned / low-HP combat oscillation:** Entering `CombatScreen` with 1 surviving member at `< 30%` HP or poisoned without `ALCORT` triggers repeated wipes instead of tactical retreat/healing.
3. **BC pollution from losing episodes:** Recording `wait` (`K_SPACE`), marooned island loops, or ship-hull-0 deaths into BC datasets teaches the policy to stall.
4. **Illegal action proposals:** NN proposes `K_e` on non-portal tiles, `K_c` with insufficient MP, or blocked combat moves — must be masked at the interface before `StateMachine.handle_event`.
5. **Seed memorization:** Overfitting to `400–524` monster spawns or wind sequences without generalizing to unseen holdout seeds `900–999`.

---

## Phase 0 — EV/Utility Planner (`py_exodus/autoplay/planner.py`)

**Scope:** Replace brittle `if/elif` goal priority in `py_exodus/autoplay/planner.py` with an explicit feature extractor + expected-value (EV) utility scorer over candidate `Goal`s. Keep `py_exodus/autoplay/nav.py` symbolic. Reuse the exact same `extract_macro_features(party, map_id, screen)` dictionary/vector for Phase 3's macro critic.

### Task 0.1: Shared Macro Feature Extractor
**Files:**
- Create: `py_exodus/autoplay/features.py`
- Test: `tests/test_autoplay_features.py`

- [ ] Define `MACRO_FEATURE_NAMES: tuple[str, ...]` covering:
  - Party vitals: `min_hp_ratio`, `mean_hp_ratio`, `dead_count`, `ash_count`, `poisoned_count`, `min_mp`, `can_alcort`, `can_sequi`
  - Sustenance & economy: `total_food`, `min_member_food`, `zero_food_count`, `food_runway_turns`, `party_gold`, `total_keys`, `total_gems`, `total_torches`
  - Progression: `min_level`, `marks_mask`, `cards_mask`, `exotics_weapons_ratio`, `exotics_armor_ratio`, `any_below_shrine_cap`
  - Navigation & hazard context: `cur_map_id`, `on_ship`, `ship_hull`, `wind_dir_idx`, `trammel_phase` (`0..23`), `felucca_phase` (`0..7`), `dawn_open`, `nearest_pirate_dist`, `at_exotic_island`
- [ ] Write unit tests verifying deterministic feature names, shapes, and values from stubbed `Party`/`Screen` inputs (1 assert per test).

### Task 0.2: EV/Utility Goal Scorer
**Files:**
- Modify: `py_exodus/autoplay/planner.py`
- Test: `tests/test_planner_ev.py`

- [ ] Implement `score_goals(features) -> dict[Goal, float]` combining:
  - Immediate survival penalties (starvation runway `food_runway_turns < 25`, poison tick risk vs `party_gold >= 100` / `can_alcort`, dead-member penalty)
  - Expected XP/gold/milestone progress per turn (Britain leveling vs Death Gulch raid vs Dungeon Marks vs Exotic digging vs Ambrosia shrines/cards vs Exodus)
  - Moon-phase window bonus (`dawn_open` for `BUY_KEYS`/`OUTFIT_BRITAIN`) and ship-hull risk penalty (`ship_hull <= 30`)
- [ ] Keep `evaluate_goal(party, map_id=0)` returning `argmax(score_goals(...))` so `controller.py` remains interface-compatible.
- [ ] Write one regression test per scored decision using stubbed inputs:
  - `zero_food_count > 0` with `gold >= 25` scores `BUY_FOOD` highest
  - `poisoned_count > 0` with `gold >= 100` scores `CURE_POISON` above `GRIND_AND_LEVEL`
  - `dead_count > 0` with `gold >= 500` scores `RESURRECT_DEAD` above `GRIND_AND_LEVEL`
  - `marks_mask == 0xF`, `cards_mask == 0xF`, `min_level >= 25` scores `CONQUER_EXODUS` highest
  - `gold >= 4500`, `food >= 500`, `on_ship`, all marks, missing cards scores `SAIL_WHIRLPOOL` highest
- [ ] **Phase 0 Acceptance Gate:** `pytest` passes cleanly (`1,263+` existing + new EV tests), and a `10-seed` (`900–909`) holdout baseline sweep is logged (win count, survival count, deaths itemized by cause + tile).

---

## Phase 1 — Combat Data Pipeline & Behavioral Cloning (`py_exodus/nn/`)

**Scope:** Record `(state, action)` pairs from `auto_combat` rollouts on `CombatScreen` (`11x11` grid, 5–30 turn episodes), filter strictly by **episode outcome** (winning episodes only, or advantage-weighted), and train a compact BC baseline.

### Task 1.1: Combat State Encoder & Action Mask
**Files:**
- Create: `py_exodus/nn/__init__.py`
- Create: `py_exodus/nn/combat_env.py`
- Test: `tests/test_nn_combat_env.py`

- [ ] Encode `CombatScreen` state into:
  - Spatial grid tensor `(C, 11, 11)`: terrain walkability, party member positions/HP ratios, enemy positions/HP ratios/ranged capability, hazard/poison tiles.
  - Global context vector: `trammel_phase` (24), `felucca_phase` (8), `wind_direction`, `ship_hull`, active member stats (`HP`, `MP`, `status`, `food`, `gold`, weapon range, armor).
- [ ] Define discrete combat action space (move N/S/E/W, attack N/S/E/W, cast heal/offensive spell, pass) with an explicit `legal_action_mask(screen, actor)` so illegal moves are always masked at the interface.
- [ ] Write 1-assert-per-behavior unit tests for grid encoding shapes and action masking.

### Task 1.2: Outcome-Filtered Rollout Collector & BC Trainer
**Files:**
- Create: `py_exodus/nn/combat_dataset.py`
- Create: `py_exodus/nn/combat_bc.py`
- Test: `tests/test_nn_combat_bc.py`

- [ ] Collect `CombatScreen` rollouts across training seeds `0–899` (never `900–999`).
- [ ] **Outcome Filter:** Keep **winning combat episodes only** (zero party deaths or net positive advantage; discard wipes and stalled waits) to avoid cloning losing behavior.
- [ ] Train a `~1.5M`-param CNN+MLP (`<= 3M` params) with cross-entropy loss on masked logits; save checkpoint metadata `{git_sha, train_seeds, val_acc, param_count}`.
- [ ] **Phase 1 Acceptance Gate:** Masked BC policy achieves `>= 85%` action agreement on held-out winning combat transitions and matches or beats `auto_combat` win rate on `200` sampled `CombatScreen` encounters from holdout seeds `900–999`.

---

## Phase 2 — Combat PPO Fine-Tuning (`py_exodus/nn/combat_ppo.py`)

**Scope:** Fine-tune the Phase 1 BC combat CNN+MLP (`1–3M` params) via PPO on `CombatScreen` episodes only (5–30 turns).

### Task 2.1: Combat PPO Loop & Provenance Gate
**Files:**
- Create: `py_exodus/nn/combat_ppo.py`
- Test: `tests/test_nn_combat_ppo.py`

- [ ] Milestone/tactical reward for `CombatScreen`:
  - `+1.0` victory bonus, `-1.0` party wipe penalty, `-0.25` per ally death, `+0.1` per enemy defeated, `-0.005` per-turn step penalty, episode timeout at `60` combat turns (never raw XP/gold payout).
- [ ] Log `git rev-parse HEAD` in every checkpoint; refuse to resume/mix rollouts if `HEAD` differs from checkpoint SHA.
- [ ] Train `2M–10M` combat steps (`~6–28 min` wall time at `5,880.5 steps/s` 10-parallel; `< 120 MB` VRAM).
- [ ] **Phase 2 Acceptance Gate:** Beats Phase 1 BC and symbolic `auto_combat` on `200` holdout (`900–999`) combat encounters (higher win rate, lower ally-death rate), with zero engine edits and full `pytest` green.

---

## Phase 3 — Macro Critic & Optional Light Full-Game PPO (`py_exodus/nn/macro_critic.py`)

**Scope:** Train a `1–5M`-param macro policy/critic over `Goal` choices using the Phase 0 feature vector (`extract_macro_features`), warm-started via BC from verified winning full-game trajectories (`seed=437`, `471`, `472`, `522`, etc.).

### Task 3.1: Full-Game Trajectory Recorder & Macro BC Warm-Start
**Files:**
- Create: `py_exodus/nn/macro_dataset.py`
- Create: `py_exodus/nn/macro_critic.py`
- Test: `tests/test_nn_macro_critic.py`

- [ ] Record `(extract_macro_features, goal, milestone_return)` from verified winning training-block runs (`0–899`), strictly excluding `900–999`.
- [ ] Train `1–5M`-param MLP policy+value head (`< 180 MB` VRAM) with action masking over legal `Goal`s.
- [ ] **Disagreement Mining:** Whenever the macro NN proposes a different `Goal` than `planner.py`, log `(step, map_id, pos, nn_goal, sym_goal, outcome)`; episodes where the NN wins after a clash are exported for symbolic-rule review.
- [ ] **Mandatory Holdout Gate:** Run `N = 20` full `160k`-step non-`nohurt` games on holdout seeds `900–999` (budget: `~5.4 min` total at `5,880.5 steps/s` 10-parallel).
  - **Gate:** The BC macro policy **must strictly beat** the Phase 0 symbolic controller's non-`nohurt` win rate on `900–999` **before** any full-game PPO is budgeted.

### Task 3.2: Light Full-Game PPO Fine-Tune (Gated on Task 3.1)
**Files:**
- Create: `py_exodus/nn/macro_ppo.py`
- Test: `tests/test_nn_macro_ppo.py`

- [ ] Milestone-shaped full-game reward:
  - `+0.5` Mark of Kings, `+0.5` each remaining Mark, `+0.5` full Exotic set, `+0.5` each Ambrosia Card, `+1.0` each Exodus panel inserted, `+5.0` Exodus Victory (`DONE`), `-5.0` wipe, `-0.0001` step penalty, timeout at `160,000` steps. **Never** raw XP/gold payout.
- [ ] Budget: `10M` steps (`~89` full games, `~28.3 min` wall time at `5,880.5 steps/s` 10-parallel; `< 250 MB` VRAM).
- [ ] **Phase 3 Acceptance Gate:** Holdout eval on `900–999` (`N = 20`, `160k` steps, `nohurt=False`) improves win count and reduces itemized deaths without regressing the `1,263+`-test suite.

---

## Risks & Mitigations

| Risk | Failure Mode | Mitigation |
| :--- | :--- | :--- |
| **Reward Hacking** | Policy farms low-risk Sosaria rats/pirates indefinitely for XP/gold instead of entering dungeons/Ambrosia. | Strictly milestone-shaped rewards (marks, cards, exotics, Exodus events) + per-step penalty + `160k` timeout; zero raw XP/gold reward terms. |
| **BC Pollution** | Cloning mixed-outcome rollouts teaches `K_SPACE` stalls, shore-cannon camping, or ship-hull-0 sinkings. | Hard outcome filter in Phase 1 (winning combat episodes only) and Phase 3 (verified `WON@` full-game trajectories only). |
| **Seed Memorization** | Model memorizes `0–899` spawn timings, wind patterns, or chest trap rolls and collapses on unseen games. | Strict train (`0–899`) / holdout (`900–999`) split; holdout seeds never enter training datasets or hyperparameter tuning; every round reports itemized holdout deaths by cause and tile. |
| **Controller Drift** | Training rollouts across changing `AutoPlayController` heuristics corrupts policy/critic targets. | Every dataset and checkpoint records `git rev-parse HEAD`; training scripts assert clean/matching SHA provenance. |
