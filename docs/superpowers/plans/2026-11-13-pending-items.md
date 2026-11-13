# PyExodus — Pending Items & Decisions (context-reset handoff)

Written 2026-11-13, after master `718aec1` (774 tests green, pushed). Read this first when resuming work in this repo.

## Project state

- Java-parity port of gdx-exodus is complete (15-task SDD plan merged 2026-11-09), followed by ~15 user-directed fix batches (peer gem, MP/Ztats/lore, log scroll-back, party persistence, original-rules tick, Q-save restriction, music invariant, dungeon 3D render, dungeon specials/monsters/APPAR, BaseMap.moveObjects pirate/seas port). All merged to master and pushed.
- Suite: 774 passed (`pytest`), green.
- Process: Java source at `/sto/src/gdx-exodus/src/main/java/` is the binding truth; user-ruling deviations carry in-code comments citing the ruling; fixes run implementer subagent → reviewer subagent → merge → push. Plan + audit trail live in `docs/superpowers/plans/`.

## Decisions made (user rulings — do NOT "fix" these back to Java)

1. Magical Orbs removed entirely (dead code in Java; user says C64 had none).
2. No default/starter party; roster starts empty (Java behavior).
3. Character portraits removed from UI (field kept in saves).
4. `Sex = M/F/Other` reinstated (original-game rule Java's SexType lacks).
5. Casters start with `mp = compute_max_mp()` (original rules; Java's creator leaves mana 0).
6. Q-save only on Sosaria overland; dungeons REFUSE (Java allows dungeon saves — documented deviation); Ambrosia/towns already refuse.
7. Whirlpools save like any other creature (Java excludes them from the save block).
8. `APPAR_UNEM` asks no direction (Java prompts then ignores); opens the caster's-tile chest once.
9. Victory fanfare plays ONCE on combat victory (`loops=0`); loops only as British's castle map theme.
10. Original-rules exploration tick (Book of Play): MP +1/turn surface, +1 per 4 turns town/dungeon, Druids double; poison −1 HP per step; HP +1/turn surface, +1/4-turns underground (interpretation); starvation 2 dmg/turn; replaces Java's meal-tick regen.
11. Peer gem is a real whole-map view; dungeon map overlay is still ON by default (see pending decisions).

## Decisions awaiting the user

1. **Dungeon map overlay default**: turn it OFF by default (P toggles) once the user verdicts the 3D view "navigable". User said "much better" — awaiting the go.
2. **Which backlog item next** (list below) — user is playing again; new findings take priority.

## Deferred minors / backlog (all ledgered, none urgent)

1. Whirlpool engulf uses Chebyshev ≤ 1; Java uses movementDistance (diagonal = 2 → no diag engulf). Also engulf-loop-break semantics: Java's inline engulf branch breaks the creature list; Python's separate `_check_whirlpool_engulf` scan lets remaining creatures tick.
2. Ship-combat round effects: combat rounds don't count as moves and hull doesn't repair during cannon duels (Java runs a small endTurn at `CombatScreen.java:472`). Ruled ship-once, flagged.
3. Message-parity pass: invented player-visible combat strings ("DEFEAT!…", per-attack lines) vs Java's terse "Missed!"/"{name} Killed! Exp. {n}".
4. Creature specials unported: negating creatures (set NEGATE aura) and camouflage (hide/show at distance).
5. Creature 3D draw edge cases: side wall at shallower depth doesn't occlude; off-axis creature at depth 1 clips the screen edge.
6. Enemy cannon trace wraps across map seams (port takes `%` per tile; Java stops at map edge). Port's own player cannons share the pre-existing wrap.
7. Cannon-sunk unmanned frigate is not removed from the map (Java removes it; port leaves it boardable, hull resets to 50 on board).
8. `fireAt`/boarding match accepts `"frigate" | "ship"` (defensive superset of Java's exact name).
9. `dynamic_objects` list unbounded in saves (Java caps at 24 + an off-by-one).
10. Java's E-edge wrap quirk in `getValidMovesMask` (second-to-last column redirects to 0) not reproduced; port uses correct `% width`.
11. Failed spell casts consume the combat turn (Java leaves the caster active on "Spell is negated!" / "Can't!").
12. Members at exactly 0 hp treated as alive-but-wiped in some combat paths (0-hp-GOOD convention) vs Java's hp>0 aliveness rule — pre-existing convention.
13. JINX aura skips AI dice in a different RNG order (stream divergence only).
14. EXODUS-map attack refusal plays the wrong SFX (cosmetic audio).
15. Zstats compact labels (WPN:/ARM:/TORCH:) are a ruled adaptation; some identity-row styling deviates from Java's proper case.
16. Peer-gem/Book minor nits: empty-section filter in lore loader (Java would add empty pages), F1 during a finished-screen transition, duplicate test cleanup done, `PAGE_ROWS` depth fine at 10.
17. Java binary `party.sav`/roster (80-byte records) interoperability — deferred as its own project; Python saves JSON (legacy binary read-only already exists).
18. Gamepad support — keyboard only today.
19. Two comment nits: whirlpool deferred comment claims Chebyshev/movementDistance "agree at ≤1" (false on diagonals); doubled `# deferred` markers at overworld.py:1645/1663.
20. Combat spell-cast letter mapping is discipline-first (Java reassigns A–P over the filtered list) — presentation-only, unscheduled.

## How to resume

1. Work the list top-down or from fresh playtest findings; each fix: branch off master, read the cited Java first, TDD, implementer + reviewer subagents (superpowers SDD flow), one commit per task (`fix:`/`parity:` prefix, Co-Authored-By footer), full suite green twice before every commit, merge + push after review.
2. Java citation hot-spots for the pending items: `BaseMap.java:421-610` (moveObjects/engulf/break), `CombatScreen.java:470-514` (round finishTurn, negate/quickness), `Utils.java:496-589` (fireCannon), `GameScreen.java:407-446` (endCombat strings), `SpellUtil.java` (spell turn gating), `Sound.java` (track/loop truth).
3. User-ruling code comments are searchable: grep `user ruling|user-directed|2026-11` in `py_exodus/`.
