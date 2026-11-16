# PyExodus — Pending Items & Decisions (context-reset handoff)

Written 2026-11-13, after master `718aec1` (774 tests green, pushed). Updated 2026-11-14 after the GBC-parity branch + pending-items batch (1048 tests green). Read this first when resuming work in this repo.

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
- 33. Publicize `py_exodus.combat.magic._PROJECTILE_SPELLS` — combat_screen
  imports it under its private name (combat_screen.py:6); rename for import
  (or re-home) — cosmetic hygiene, no behavior change.
- 34. Identify + seed the suite's latent stream-sensitive unseeded test(s) —
  at least one test is sensitive to the RNG stream yet runs unseeded; the
  `hermetic_rng` fixture (tests/test_play_driver.py) masks the symptom, it
  does not fix the leak. Find the test(s) and seed them (or the system RNG
  source) explicitly.

### New follow-ups found during the 2026-11-14 batch

25. `dynamic_monsters` save cap 8 (Java `Context.java:176-185`) — the
    creature-side counterpart of closed item 9; verify the port caps the
    dynamic creature list the same way at save time.
26. Player-cannon shoreline halt + creature-hit damage formula
    (`Utils.java:471` edge stop; `Utils.java:549-568` per-creature damage)
    — enemy cannons were fixed (`dee5ffa`); the port's own player cannon
    trace/damage should be re-verified against the same lines.
27. `fireAt` stacked-tile last-match nuance — Java's match loop resolves to
    the LAST matching tile/creature on a stacked tile; confirm the port's
    first-match order or adopt Java's.
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

### Deferred follow-ups ported from 2026-11-15 session handoff

35. Overworld boot + dungeon entry strings still ad-hoc ("Entering the realm
    of Sosaria...") vs Java Maps labels everywhere (reviewer note on
    `a07dc2e`).
36. Vendor prompt comment citations drifted ~18 lines (strings correct);
    touch-up in any next vendor commit.
37. ESC at a vendor prompt dangles the dialog (`text_log` `handle_escape`
    drops callback; vendor state not closed — user-visible? needs a check;
    implementer flagged out-of-scope).
38. Dungeon entry uses the enum key in some path (`dungeon_screen.py:83,107`
    name source) — observed live in Playtest-2 (`"Entering DARDIN..."`
    instead of `"Dardin's Pit"`); normalize to Java labels.
39. Suite-wide: one stream-sensitive unseeded test remains latent somewhere
    (`hermetic_rng` in `play_driver` masks the driver's own footprint;
    identify + seed once reproduced — overlap with item 34). Also
    `test_party_save.py:716` comment ambiguity (`(45,19)` is file-format
    truth now that Party default is `(44,20)`) — cosmetic.
40. YELL softlock-ish prompt (`playtest 2`, `docs/analysis/journal.md:28`):
    empty `ENTER` / `ESC` behavior at `"Yell what? "` vs Java
    `SecondaryInputProcessor.java:535-538` (`ENTER` on empty buffer keeps
    prompt open, no `ESC` cancel; `py_exodus` silently closes without
    emitting anything).
41. Playtest 1 unexercisable-then: `ZXKuqyb` masskill (70MP), 9999 gold cap,
    Healer Resurrect — Healer Resurrect exercised in Playtest-2 (`500gp`,
    revived `SERENA` to 1 HP); `ZXKuqyb` and 9999 gold cap still to
    exercise in a future session.

### New findings from Playtest-2 (2026-11-16)

42. **CRITICAL — `monster_damage_bonus(SOSARIA)` adds `+30` instead of `+0`**
    (`py_exodus/combat/resolver.py:126-141`): the 2026-11-14 GBC agent
    misread `refs/ult3src/sdk/gbz80-gb/2-1-5/examples/u3/battle3.c:354-368`
    (`ult3.c:1150,1654,1677`, `funcs5.c:1575-1610`). In GBC, `inside = 0`
    (`0x20` in combat) on Sosaria with `peermap = 99` (`0x20` only adds
    `+30` if `peermap == 12` Ambrosia, **`+0` on Sosaria**); `inside = 1`
    (`0x21` in combat) adds `+30` for `peermap == 0 || 4` (British/Exodus)
    and `+20` for other towns; `inside = 2` (`0x22` in combat) adds `+10`
    in dungeons. Corroborated by LairWare `UltimaSpellCombat.c:1226` (`0`
    on Sosaria) and Java `Creature.java:465-472` (`+0`). Causing L1
    Thieves/Orcs on Sosaria to hit for 30–43 dmg instead of 0–13, wiping L1
    parties in 1–3 battles (`tests/test_combat_resolver.py:349` and
    `docs/superpowers/plans/2026-11-14-gbc-parity-and-fixes.md:75` also
    pin the wrong `+30` value).
43. **HIGH — Game-Over -> `RosterScreen` dead-party leak & dead `party.json`
    resume** (`py_exodus/screens/base.py:60-66`,
    `py_exodus/screens/start.py:187-221`,
    `py_exodus/screens/roster_screen.py:70`): `check_party_death()` passes
    the wiped `party` into `StartScreen(party=party, game_over=True)`,
    `_new_game()` forwards `self.party` into `RosterScreen` (exposing a
    wiped party in party formation and risking overwriting
    `saves/roster.json`/`saves/party.json` with dead members), and Journey
    Onward allows loading an all-dead `saves/party.json` directly into
    `OverworldScreen`.
44. **HIGH — `HealerVendorDialog` `'n'` infinite loop, `ASK_BUY_SELL` bug,
    and Enter-required member prompt**
    (`py_exodus/screens/vendor_dialog.py:1030-1037, 1071, 1087`): pressing
    `'n'` at `WAIT_NEED_HELP` / `"Anything else?"` when `hp < 400` sets
    `state = ConvState.WAIT_NEED_HELP`, looping back to Pendragon's greeting
    forever (at `hp >= 400` it unconditionally transitions to
    `WAIT_GIVE_BLOOD` and loops if declining); `check_can_pay` assigns
    nonexistent `ConvState.ASK_BUY_SELL` on `item is None`; and
    `WAIT_WHO_SERVICE` (`"Who is in need? (member number)"`) sets
    `single_char=False` requiring `ENTER`, inconsistent with single-key
    `1-4` member prompts elsewhere.
45. **MEDIUM — `DungeonState.touch_mark` & `chests._apply_fire_lava` bypass
    `apply_damage`** (`py_exodus/world/dungeon.py:2036-2039`,
    `py_exodus/world/chests.py:199-201`): both mutate `member.hp = max(0,
    ...)` directly and set `Status.DEAD` at `hp == 0`, violating the
    `apply_damage` chokepoint, the `< 0` death convention (Java
    `Party.java:556-577`), and `PartyDeathException`.
46. **CRITICAL/HIGH — `CombatArena` / `PartyMember` `hp == 0` defeat
    softlock** (`py_exodus/combat/arena.py:1368-1378` vs
    `py_exodus/screens/base.py:55`, `py_exodus/entities/party.py:102-106,
    826-832`): when all 4 party members hit `hp == 0` with at least one
    landing at `new_hp == 0` exactly (`status` stays `GOOD`/`POISONED`
    per item 12), `CombatArena._evaluate_party_status` checks `not
    m.is_dead() and m.hp > 0` and marks `is_finished = True, is_defeat =
    True` (`"Press Enter to continue."`), whereas
    `CombatScreen._handle_defeat_exit()` -> `check_party_death()` checks
    `party.is_party_dead()` (`status == DEAD` only -> `False`) and does
    nothing, trapping the player in `CombatScreen` forever.
47. **MEDIUM — `Q`-save/reload `moves` off-by-1 & `+3` wandering-creature
    respawn** (`py_exodus/screens/overworld.py:367, 387-389, 2260-2270`):
    `_save_game()` calls `SaveSystem.save_game` BEFORE
    `self._consume_pass_turn()`, persisting `moves - 1` (`3590` vs
    `3591`), and `OverworldScreen.__init__` restores `world_state`
    monsters AND unconditionally spawns 3 extra wandering creatures on top
    (`creatures_count: 5 -> 8`).
48. **MEDIUM — `DungeonScreen._process_event` double-logs `EXIT_DUNGEON`
    message** (`py_exodus/screens/dungeon_screen.py:317-318, 345`):
    `"You climb out of the dungeon to the surface!"` is added to
    `text_log` at line 318 and again at line 345 before `exit_screen()`.

## How to resume

1. Work the list top-down or from fresh playtest findings; each fix: branch off master, read the cited Java first, TDD, implementer + reviewer subagents (superpowers SDD flow), one commit per task (`fix:`/`parity:` prefix, Co-Authored-By footer), full suite green twice before every commit, merge + push after review.
2. Java citation hot-spots for the pending items: `BaseMap.java:421-610` (moveObjects/engulf/break), `CombatScreen.java:470-514` (round finishTurn, negate/quickness), `Utils.java:496-589` (fireCannon), `GameScreen.java:407-446` (endCombat strings), `SpellUtil.java` (spell turn gating), `Sound.java` (track/loop truth).
3. User-ruling code comments are searchable: grep `user ruling|user-directed|2026-11` in `py_exodus/`.
