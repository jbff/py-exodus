# Gameplay Verification Strategy — decision memo (2026-11-14)

**Question:** how do we find and fix ALL broken basic mechanics without the owner reporting bugs one at a time — and is it worth continuing?

## Root cause of the recurring failures (not opinions — observed over 57 reviewed tasks)

1. **No executable oracle.** Every verification so far compared *texts* (py vs Java vs GBC vs LW) or pinned *postconditions* of single functions. A game loop is a state machine over key sequences; nothing ever executed a sequence and diffed the transcript. Rules audited this way landed well (the dice/hazard/spawn engine is now triple-corroborated). Interaction audited this way produced "B = wrong spell," a fabricated bolt, invisible turn state — because those defects live between functions, in the loop, where no unit test looks.
2. **Coverage was sampled, not enumerated.** Six recon agents covered rule domains. Nobody enumerated the interaction surface — the finite grid of (command × context × failure-path) — so "done" meant "the things we thought of," not "the whole surface."
3. **"Presentation-only" was a classification error.** A remapped spell letter is not presentation; it is the game. Presentation-only must mean colors and spacing, never key→effect mapping, prompt shapes, or turn ownership.
4. **No acceptance gate that "plays" the flow before merge.** Reviews read diffs; none ran the player's sequence.

## The strategy — five pillars

**P1. One oracle principle.** Every behavior gets a *transcript test*: the headless play driver (already being built in the combat plan, Task 1) boots the real game, feeds the same key events a player types, and records prompt text, messages, active member, and state deltas. A behavior is "fixed" only when its sequence passes. Unit tests remain for math; transcripts are the contract for loops.

**P2. The Java implementation is executable — differential testing is the gold standard.** The repo's reviews already extracted classes from `gdx-exodus-1.0.1-jar-with-dependencies.jar`; the code runs. If its screens can be constructed headless (LibGDX headless backend / direct InputProcessor driving; the UI can be skipped if we drive `Screen.keyUp` + intercept its `log`/state calls), we can run the **same scenario + same key sequence through Java and py and diff normalized transcripts automatically**. That turns "three implementations to copy from" from advice into an actual regression corpus. A 1-task spike decides feasibility; if the headless route fails, fall back to P3.
   - Failure mode honestly stated: LibGDX UI init may demand GL context. Escape hatches: drive the logic classes directly with a harness shim (their input handlers are plain keyUp(int) methods), or extract the screen logic. Unknown until tried; spike cost ≈ one task.

**P3. Enumerated interaction matrix (the option if the spike fails — still required either way).** Enumerate the surface: ~26 commands × contexts {overland, town, castle, dungeon, ship, combat} × failure paths (cancel/invalid/no-resource/dead-state) ≈ a few hundred cells; plus menu flows (cast lists, vendor ladders, roster). Ledger every cell with three statuses: **verified-by-transcript / verified-by-reading / unverified**. Burn down in priority order: combat loop → overland/ship movement → towns+vendors → dungeon specials → save/roster/meta. Expectations written from the Java interaction layer (InputProcessors + screens' keyUp handlers) with GBC cross-checks already banked from the interaction recon. This is mechanical work with a fixed shape — ideal for batched SDD cycles.

**P4. Acceptance runs.** No merge without the driver playing the touched flow end-to-end. Cheap once the driver exists; each batch adds its sequences as permanent regression.

**P5. Bug classes, not bug instances.** Every reported bug gets classified (mapping / turn-consumption / state-affordance / prompt-shape / rule). The class is fixed everywhere at once and its entire scenario family lands as tests. (The spell-letter bug's class was "fixed-code mapping" — the same class existed in three prompt flows; the batch fixes all three.)

## Cost / return estimate (honest ranges)

- Combat-interaction plan (in flight): 8 tasks, includes the driver.
- Interaction-matrix burn-down: ~4-6 batches × 5-8 tasks. Largest blocks: combat matrix (partially done by this plan), town/vendor flows (the vendor dialog ladders), dungeon specials, save/roster.
- Differential-harness spike (optional but recommended): 1 task to know, +2-3 tasks to build if feasible, then the scenario corpus runs Java-side automatically.
- **Return:** the bug classes you've reported (wrong key→effect, fake feedback, invisible state, broken refusal) are exactly the classes transcripts catch mechanically. After matrix coverage, "report bugs one at a time" becomes "the failing transcript tells us." That's the difference between this lasting two more months and lasting forever.

## The "workable game" gate (proposed definition)

A milestone checklist, each line proven by a passing transcript scenario: party creation → enter combat → all 4 classes attack/cast/ready/other incl. refusals → win/lose → loot → level-up → shop buy/sell → walk/ship/horse → dungeon climb/descend, marks, fountains, traps → save/load round-trip → Exodus machine → win/lose endings. ~20 scenarios. When those pass, the game is workable; breadth beyond that is polish.

## Recommendation

Approve: (a) finish the combat-interaction plan (in flight); (b) run the differential-harness spike; (c) matrix burn-down batches in the priority order above with transcript-level acceptance. Stop-report-one-at-a-time is achievable in roughly the next 4-6 batches; the game becomes verifiable workable before it becomes perfect.
