# PyExodus — Pending Items & Decisions (context-reset handoff)

Written 2026-11-13, after master `718aec1` (774 tests green, pushed). Updated 2026-11-14 after the GBC-parity branch + pending-items batch (1048 tests green), and updated 2026-11-16 after Playtest-2 + the Playtest-2 fix batch (`1156` tests green). Read this first when resuming work in this repo.

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
12. Fixed spell letters (2026-11-15 user ruling): every spell menu lists the discipline's full original-game A–P set — letters NEVER move with mana or context — and availability refuses at the attempt ("Not Here!" for context-refused spells; "Not a spell!" for out-of-list keys; the canonical MP line right after the letter, before any target/direction prompt — F2 amendment). Supersedes the getCastables letter compaction (Java Constants.java:751-762) that the 2026-11-14 combat-interaction-parity plan ported; the whole batch (headless play driver +Tasks 1-7, `b61ee17..98d8768`) and this amendment (`676bb51`+) ride `worktree-fixed-spell-letters`, awaiting merge.

## Decisions awaiting the user

1. **Dungeon map overlay default**: turn it OFF by default (P toggles) once the user verdicts the 3D view "navigable". User said "much better" — awaiting the go.
2. **Which backlog item next** (list below) — user is playing again; new findings take priority.

## Deferred minors / backlog — 2026-11-14 status

### Closed 2026-11-14 (GBC-parity branch + pending-items batch) — dispositions

Original numbers kept for history against the 2026-11-13 list above.

1. Whirlpool engulf — CLOSED (user-directed GBC/LW same-tile-only ship
   contact, `ef59cb7`; supersedes Java's movementDistance≤1 ring). The
   separate `_check_whirlpool_engulf` scan stays (no inline
   list-break to mirror); the Chebyshev/movementDistance and doubled-
   deferred comment nits (item 19) also fixed 2026-11-14 — Java's ring is
   `movementDistance` ≤ 1, cited correctly now (overworld.py `_finish_turn`).
2. Ship-combat round effects — CLOSED (`6416d30`; Java
   `CombatScreen.java:470-514` rounds tick turns and hull repair).
3. Message-parity strings — CLOSED (`f3a6858`; canonical combat strings from
   Java GameScreen/CombatScreen).
4. Creature specials — CLOSED (`776ca35`; negate aura + camouflage
   hide/show per Java).
6. Enemy cannon wrap — CLOSED (`dee5ffa`; Java fireCannon edge-stops, no `%`).
7. Sunk unmanned frigate removal — CLOSED (same `dee5ffa`).
8. `fireAt`/boarding name superset — CLOSED (`e670479`; exact Java name match).
9. `dynamic_objects` save cap — CLOSED (`1f43eef`; Java Context.java cap).
11. Failed spell cast consumes turn — CLOSED (`a63730b`; Java leaves caster
    active on "Spell is negated!" / "Can't!").
14. EXODUS-map attack-refusal SFX — CLOSED (`e77286e`; Sound.NEGATIVE_EFFECT).
16. Peer/Book nits — CLOSED 2026-11-14: (a) lore empty-section filter
    **documented-and-kept**: Java's empty pages arise from its unconditional
    `labels.add()` in `BookScreen.addPages`, not from a removable filter line;
    matching is more than a one-line diff, and the real (only) `ultima3.txt`
    has no consecutive/trailing `*break` markers, so the divergence is
    unreachable. (b) F1 during a finished-screen transition — defensive
    guard added in `state_machine.handle_event` (Java has none; its
    setScreen is synchronous) with a regression test.
19. Whirlpool/deferred comment nits — CLOSED 2026-11-14: "agree at ≤1"
    phrasing gone; Java distance now cited as `movementDistance` ≤ 1 plus the
    same-tile deviation note; the doubled `# # deferred:` marker fused at
    overworld.py ("documented deferral:", pirate broadsides block).
20. Combat spell-cast letter mapping — CLOSED (combat-interaction-parity
    branch 2026-11-14): the discipline-first mapping was replaced by the Java
    re-running dynamic A-P per context and remaining mana
    (py_exodus/spell_menu.py after Java Constants.java:751-762 getCastables),
    with the lettered lists printed and the Book appendix relabelled to drop
    its dead letter column (`2656b2b`); executed-but-failed casts consume the
    turn (`5e86107`).
21. Chest Bomb trap — CLOSED (`ead9131` LW BombTrap; booty early-return
    follow-up `56ce2f3` per LW).
22. Thief-steal feedback — CLOSED (`144fd25`; GBC "PILFERED!" + "POISONED!"
    battle3.c:288/298/257).
23. Dungeon meal cadence — CLOSED (`ef5e9da`; GBC/LW underground feed/regen).
24. Shrine near-cap over-debit — CLOSED (`fd67773`; LW **deliberate
    LUMP-SUM over-debit** kept: full ``amount*100`` debit before the grant,
    race-cap clamp applied only after — so a near-cap buy is charged for
    points the clamp does not grant, verified ``UltimaMisc.c:1071-1093``);
    do NOT "fix" this to a pro-rated debit.

### Standing items (open, original numbers)

- 5. Creature 3D draw edge cases: side wall at shallower depth doesn't
  occlude; off-axis creature at depth 1 clips the screen edge — open.
- 10. Java's E-edge wrap quirk in `getValidMovesMask` (second-to-last column
  redirects to 0) — deliberate non-reproduction; port uses correct `% width`.
- 12. Members at exactly 0 hp treated as alive-but-wiped in some combat paths
  (0-hp-GOOD convention) — pre-existing convention, keep.
- 13. JINX aura AI dice in a different RNG order — stream divergence only.
- 15. Zstats compact labels — ruled adaptation; some styling deviates.
- 17. Java binary `party.sav`/roster interop — deferred own project.
- 18. Gamepad support — keyboard only today.

### New follow-ups found during the 2026-11-14 batch

28. LW trap-typing distribution 56/19/19/6 — chest trap weights (per LW);
    note alongside the Bomb-trap wiring from closed item 21 for future
    verification.
29. Camouflage tele/ranged gate-placement nuance — where Java's camouflaged
    creatures gate tele/ranged actions relative to gate placement.
30. Spell-cast narration + overworld move-narration purge (P12 flagged) —
    audit invented narration lines vs Java/GBC during spell casts and
    overworld moves.
31. Group-damage kill lines — narration when one hit kills a whole group.
32. Item-3 GBC-mechanic-string carve-out (ledger note; comments-only
    today): "Magic Blast!" (resolver.py:207-209; GBC prints no text on that
    branch — battle3.c:856-866, magiceffect2(3) + damageplayer, no
    writegamemessage) and "Cannonball barrage!" (resolver.py:698; GBC
    cannonfire prints no text — battle3.c:501-560, no writegamemessage;
    Java's rangedAttackAt logs only Electrified!/Fiery Hit!/Poisoned!) are
    kept as player feedback per the item-3 ruling to keep GBC-adopted
    mechanic strings and note them; note landed in comments, logged here
    so the disposition is documentable.

### Closed 2026-11-16 (Playtest-2 fix batch)

36. Vendor prompt Java line citations — CLOSED (`fae85bd`; re-synced
    line-number comments in `py_exodus/screens/vendor_dialog.py` and
    `tests/test_vendor_flows.py` against `vendor/*.java`).
37. ESC at a vendor prompt — CLOSED (`fae85bd`; added `on_cancel`
    cleanup hook to `TextLog.prompt` / `handle_escape` / `clear`, wired
    to `BaseVendorDialog._finish` and `TownScreen` generic vendor prompt
    to restore town music cleanly with no dangling state).
38. Dungeon entry display label — CLOSED (`e83f4d7`; `DungeonScreen` now
    resolves player-facing labels from `MAP_ID_TO_LABEL` when `id != 0`,
    so `map_id=15` logs `"Entering Dardin's Pit!"` instead of `"Entering
    DARDIN..."` while injected/custom maps keep their own names; note
    related `DungeonState.spell_exit` at `dungeon.py:1254` still uses
    `dmap.name`).
42. `monster_damage_bonus(SOSARIA)` `+30` -> `+0` — CLOSED (`fc1bd34`;
    corrected GBC `battle3.c:354-368` tier mapping: `+0` Sosaria, `+10`
    dungeons, `+30` Ambrosia / Castle British / Castle of Death, `+20`
    other towns/interiors/`None`, updating `test_combat_resolver.py`,
    `test_combat_parity.py`, and plan docs).
43. Game-Over -> `RosterScreen` dead-party leak & dead `party.json`
    resume — CLOSED (`f69fa30`; `StartScreen._start_journey` falls back
    to `_new_game` on all-dead saves, `StartScreen._new_game` clears
    `party` when `game_over` or all-dead, and `RosterScreen.__init__`
    drops non-empty all-dead party arguments).
44. `HealerVendorDialog` `'n'` exit loop, `ASK_BUY_SELL` bug, &
    `single_char` member prompt — CLOSED (`fae85bd`; declining below
    400 HP or declining Give Blood exits via `FAREWELL`, removed
    `ASK_BUY_SELL` write in `check_can_pay(None)`, split `ANYTHING_ELSE`
    to `"Anything else? (y or n)"`, and made `Who is in need? (member
    number)` `single_char=True`).
45. `DungeonState.touch_mark` & `chests._apply_fire_lava` bypass
    `apply_damage` — CLOSED (`e83f4d7`; both now route through
    `member.apply_damage`, preserving the `0-hp-GOOD` convention and
    `PartyDeathException` wipe routing).
46. `CombatArena` / `PartyMember` `hp == 0` defeat softlock — CLOSED
    (`3fe317b`; aligned `_is_member_eligible_for_turn`,
    `_find_nearest_player`, and `_evaluate_party_status` with
    `0-hp-GOOD` (`is_dead()`/`fled` only, matching Java
    `CombatScreen.java:291, 568, 816`)).
47. `Q`-save/reload `moves` off-by-1 & `+3` wandering-creature respawn —
    CLOSED (`e83f4d7`; `OverworldScreen.__init__` skips initial `+3`
    wanderer spawns when `map_id=0` restores non-empty `world_state.monsters`,
    and `_restore_world_state` preserves free-seeded whirlpools on empty
    `"monsters": []`; `_save_game()` calling `SaveSystem.save_game`
    before `_consume_pass_turn()` (`moves` -1) is deliberately preserved as
    exact Java `GameScreen.java:557-563, 628` parity).
48. `DungeonScreen._process_event` double-logs `EXIT_DUNGEON` message —
    CLOSED (`e83f4d7`; fallback `"Leaving dungeon..."` now only logs
    when `not evt.message`).

### Closed 2026-11-16 (Backlog fix batch)

25. `dynamic_monsters` save cap 8 — CLOSED (`a336cea`; added
    `Party.DYNAMIC_MONSTERS_SAVE_CAP = 8` and write-time slicing in
    `Party.to_dict()` per Java `Context.java:176-185`).
26. Player-cannon shoreline halt + creature-hit damage formula — CLOSED
    (`cc057db`; updated `OverworldScreen._fire_cannons` per
    `Utils.java:423-444, 471, 551-569`: removed shoreline halt, skips
    `"whirlpool"`, uses `1-in-3` (`random.randint(0, 2) == 0`) for creature
    hits, and stops trace on `HIT` or `MISS`).
27. `fireAt` stacked-tile last-match nuance — CLOSED (`cc057db`; extracted
    `OverworldScreen._damage_unmanned_frigate_at` using last-match lookup
    on stacked tiles per `Utils.java:536-547` for both `_fire_cannons` and
    `_enemy_fire_cannons`).
33. Publicize `py_exodus.combat.magic._PROJECTILE_SPELLS` — CLOSED
    (`087958c`; renamed `_PROJECTILE_SPELLS` -> `PROJECTILE_SPELLS` and
    updated `py_exodus/screens/combat_screen.py` import).
34. Identify + seed the suite's latent stream-sensitive unseeded test(s) —
    CLOSED (`73cf324`; `TestGetChest::test_overworld_g_chest_on_party_tile`
    and `test_town_g_chest_tile_under_party` in `tests/test_command_parity.py`
    now seed `py_exodus.world.chests.random` via `monkeypatch` so BombTrap
    rolls cannot flake `The Chest Holds:` assertions).
35. Overworld boot string & `DungeonState.spell_exit` map label — CLOSED
    (`087958c`; `OverworldScreen.__init__` now logs `"Entering {label}!"`
    via `MAP_ID_TO_LABEL` (`"Sosaria"`, `"Ambrosia"`), and
    `DungeonState.spell_exit` logs `"Leaving {label}!"`).
39. `test_party_save.py:716` comment ambiguity & latent unseeded test —
    CLOSED (`a336cea` clarified `(45, 19)` vs `(44, 20)` in
    `tests/test_party_save.py`; latent unseeded test resolved in `73cf324`).
40. YELL empty `ENTER` prompt behavior — CLOSED (`fd766ed`; added
    `allow_empty` to `TextLog.prompt` and set `allow_empty=False` in
    `_prompt_yell` (`overworld.py`, `town.py`) per
    `SecondaryInputProcessor.java:535-538`, keeping `ESC` cancelable).

### Remaining deferred follow-ups (2026-11-15 / 2026-11-16)

41. Playtest 1 unexercisable-then: `ZXKuqyb` masskill (70MP), 9999 gold cap,
    Healer Resurrect — Healer Resurrect exercised in Playtest-2 (`500gp`,
    revived `SERENA` to 1 HP); `ZXKuqyb` and 9999 gold cap to exercise in
    Playtest-3.

## How to resume

1. Work the list top-down or from fresh playtest findings; each fix: branch off master, read the cited Java first, TDD, implementer + reviewer subagents (superpowers SDD flow), one commit per task (`fix:`/`parity:`/`docs:` prefix), full suite green twice before every commit, merge + push after review.
2. Java citation hot-spots for the pending items: `BaseMap.java:421-610` (moveObjects/engulf/break), `CombatScreen.java:470-514` (round finishTurn, negate/quickness), `Utils.java:496-589` (fireCannon), `GameScreen.java:407-446` (endCombat strings), `SpellUtil.java` (spell turn gating), `Sound.java` (track/loop truth).
3. User-ruling code comments are searchable: grep `user ruling|user-directed|2026-11` in `py_exodus/`.
