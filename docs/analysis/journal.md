# py-exodus playtest #2 journal (fresh run from roster SHADOW/GRUMM/SERENA/ZIRCON)

Repo: /sto/prj/py-exodus @ 94c2b75. Driver loop: /tmp/play2/loop.py (FIFO /tmp/play2/in, out.log, full.log). party.json deleted pre-run; roster.json kept.

## Boot & start
- Fresh party formed from roster order; spawn (44,20) grass (user-directed deviated spawn) verified: one south + one west of castle gate (45,18).
- Stats at L1: hp 150/150 all; mp SHADOW 0, GRUMM 0, SERENA 25, ZIRCON 25 (thief/fighter no mp; cleric/wizard 25) — matches U3.
- Overworld boot message wraps: "Entering the realm of / SOSARIA..." + "Wind blows NORTH."
- 3 wandering creatures spawned on boot (post-fix spawn tables to verify below).

## Castle of Lord British (map 1)
- Enter via portal (45,18) with E: "Entering Castle of Lord British!" — fixed map label works (a07dc2e).
- Castle interior: outer corridor at x=31..33 south of inner MOAT rows 33-34 (water tiles) crossed by bridge at x=30; go-BFS found it; first straight-N walk blocked at (32,34) water - correct terrain block.
- Talk T -> member 1 -> N from (32,15): Lord British says: 'Welcome my child.. / Experience more!' at 0 exp. Parity with Java dialogue.

## Britain (map 3, "lcb" = Britain town)
- Portal (46,19) -> arrive (2,32). "Entering Britain!" — fixed town label works (a07dc2e).
- VOs: Osbert's Weaponry merchant NPC at (39,17), WEAPONS sign row y18, talk N from (39,19) across sign engages vendor (test parity). British Armour Otter at (50,18), sign y19, talk N from (50,20). The Market Max at (48,51), sign GROCERY y50, talk S from (48,49) (south column x48 at y52/53 is 'space' non-walkable — north approach only).
- WEAPON vendor flow: choice letter -> description -> "How many would you like?" -> digits then ENTER confirm -> "A fine choice!" + "anything else?" (y/n).
- ARMOR vendor flow: choice letter -> "Take it? (y or n)" -> "A fine choice!" + "anything else?" (distinct vendor questions = d411751 fix verified).
- FOOD vendor flow: rations offer "Reply? (y or n)" -> "25 for only 25gp. How many packs?" digits+ENTER -> "Thank you." + "Anything else?". Unaffordable: "You can only afford 0 packs." (SHADOW 15gp) — proper gold gating.
- Bought: Sling 60gp SHADOW; Mace 30gp GRUMM; Mace 30gp SERENA; Dagger 5gp ZIRCON; Cloth 75gp all four; 1 rations pack x3 (GRUMM/SERENA/ZIRCON). Gold now 15/20/20/45.
- Equip via R (ready weapon, A-P letters) and W (wear armor, A-H letters). All "Success!" lines seen.

## HARNESS/DX notes (not game bugs)
- Driver key token trap: single letters n/s/e/w resolve to compass arrows (documented in driver). All vendor y/n answers MUST go via raw pygame.K_e*n with unicode= or prompts silently ignore keyless events (prompts read event.unicode).
- "Thank you. Anything else?" requires explicit n; otherwise next T leaks into the y/n prompt and later keys hit town commands (Cast/Board/Yell) - my chunking error, but reproduces the real risk of mistyped keys cascading into commands.
- YELL text prompt: empty ENTER does not submit and ESC does not cancel ("Yell what?" stays open) - softlock-ish but a player can type any word + ENTER to exit. FILED as finding.
- go BFS in loop walks town streets ignoring NPCs (guards block, loop re-BFSes around, mimicking a human re-path).

## State snapshot
- All four: Cloth armor worn; weapons: Sling/Mace/Mace/Dagger. Food submorsels 90, display food 146/171.
- Position: Britain market (48,49). Next: exit town, fight overworld spawn fights, verify monster types + monster-hit lines + killer-only exp.
