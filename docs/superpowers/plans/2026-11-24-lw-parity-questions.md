# LairWare parity audit: open questions

The audit found 73 open questions (ledger class `ask`). One of them (S-18) you have already ruled, so 72 rows are left, plus three autoplay questions. They are grouped below into 56 questions.

LairWare is the rules authority, so the default answer is **Follow LairWare**. **Keep port** is suggested where you ruled the point earlier, where LairWare added something the classic game never had, where LairWare's code looks wrong, or where the change would break autoplay for little gain. **Defer** is suggested for auto-combat and autoplay strategy changes that need seed-checked autoplay runs first.

To answer, you can reply "accept all except 7 and 12" and give your ruling on those.

## All questions

1. How characters start: start at 100 HP, not 150. **Keep port**
2. How characters start: forming a party starts a new game. **Follow LairWare**
3. How characters start: the starting square. **Keep port**
4. How characters start: two characters with the same name. **Follow LairWare**
5. Earlier rulings (food, poison, time): starving and slow healing. **Keep port**
6. Earlier rulings (food, poison, time): poison and mana speed. **Keep port**
7. Earlier rulings (food, poison, time): ticks during fights and in dungeons. **Keep port**
8. Earlier rulings (food, poison, time): moons stop off Sosaria. **Keep port**
9. Earlier rulings (food, poison, time): what stopped time stops. **Keep port**
10. Earlier rulings (food, poison, time): the force field. **Keep port**
11. Earlier rulings (fights and traps): how many monsters attack. **Keep port**
12. Earlier rulings (fights and traps): monster hit points. **Keep port**
13. Earlier rulings (fights and traps): guards can't be hurt. **Keep port**
14. Earlier rulings (fights and traps): poison and theft in a fight. **Keep port**
15. Earlier rulings (fights and traps): whom monster spells target. **Keep port**
16. Earlier rulings (fights and traps): dungeon traps and gremlins. **Keep port**
17. Earlier rulings (fights and traps): the Alchemist's stealing bonus. **Keep port**
18. Death and coming back: dead at exactly 0 HP. **Follow LairWare**
19. Death and coming back: HP after Surmandum or Anju Sermani. **Follow LairWare**
20. Death and coming back: resurrection when the whole party falls. **Keep port**
21. Spell names: wizard spell I, Dag Lorum or Pabulum. **Follow LairWare**
22. Spell effects: how much light the light spells give. **Keep port**
23. Spell effects: Necorp also weakens monsters. **Keep port**
24. Spell effects: how Fal Divi works. **Keep port**
25. Wind and sea: what the wind's name means. **Follow LairWare**
26. Wind and sea: how often the wind changes, and wind after Exodus. **Keep port**
27. Wind and sea: how fast the whirlpool moves. **Keep port**
28. Monsters and guards: a new game starts with no monsters. **Follow LairWare**
29. Monsters and guards: Ambrosia's horses and jester attack. **Follow LairWare**
30. Monsters and guards: shots stop where you can't see. **Follow LairWare**
31. Town danger: after any town fight, guards and Lord British hunt you. **Defer**
32. Monsters and guards: monsters calm down after Exodus falls. **Keep port**
33. Commands and dungeon fixtures: S and L keys, Search. **Keep port**
34. Commands and dungeon fixtures: when fountains, rods and the like trigger. **Keep port**
35. LairWare-only extras: diagonal moves. **Keep port**
36. LairWare-only extras: the turn passes when you wait, and auto-heal. **Keep port**
37. LairWare-only extras: Look, and Kreate (a random new world). **Keep port**
38. LairWare-only extras: Terraform, Armageddon, Flotellum. **Keep port**
39. LairWare-only extras: joke words, and the port's SCORE. **Keep port**
40. LairWare-only extras: debug key and secret wall names. **Keep port**
41. Likely LairWare bugs: swapping with an empty position. **Keep port**
42. Likely LairWare bugs: the move count goes up by party size. **Keep port**
43. Likely LairWare bugs: food lost when it rolls over a hundred. **Keep port**
44. Likely LairWare bugs: monsters walk the long way round. **Keep port**
45. Likely LairWare bugs: a wanderer kills other monsters. **Keep port**
46. Likely LairWare bugs: a thrown last dagger hits as bare hands. **Keep port**
47. Likely LairWare bugs: chest bomb damage doesn't grow with depth. **Keep port**
48. Likely LairWare bugs: cards and moons forgotten on reload. **Keep port**
49. Auto-combat: when to flee, heal and hold back. **Defer**
50. Auto-combat: free Repond and Pontori once per battle. **Defer**
51. Auto-combat: aiming shots and Mittar. **Defer**
52. Auto-combat: moving into position. **Defer**
53. Auto-combat: the port's extra spell habits. **Keep port**
54. Autoplay: the stat goals at the shrines (DEX 40). **Defer**
55. Autoplay: test parties get the starting Dagger and Cloth. **Follow LairWare**
56. Autoplay: Druid healing casts fail (bug). **Follow LairWare** (fix it)

Count: 11 Follow LairWare, 39 Keep port, 6 Defer.

## Already decided (not asked again)

- **Healer order (S-18):** keep the port's healer, which asks who first and charges only when the service works. The ledger row becomes ruled-keep.
- **Shop moves (S-02):** the Castle British cook only talks, and the stable is Devil Guard's. Already ported.
- **Town exit:** stays as LairWare's.
- **Castle Exodus fireballs:** right as they are.

---

## How characters start

**1. Start at 100 HP, not 150** (R-05, B-17)
- LairWare: a new character has 100 HP, and each Lord British visit adds 100 max HP. LairWare changed this on purpose; the classic releases and LairWare's own older code gave 150.
- Port: 150 HP to start, as in the classic game.
- If we follow LairWare: every character is 50 HP weaker at every level. Fights don't change otherwise (B-17). Autoplay's early game gets harder.
- **Recommendation: Keep port.** It is a LairWare-only change from the classic game.

**2. Forming a party starts a new game** (R-11)
- LairWare: you can't form a party while one exists ("disperse first"). Forming one starts fresh: on foot on Sosaria, move count 0, world reset.
- Port: you can add or remove members of a saved party, so fresh recruits can join a game in progress.
- If we follow LairWare: no more swapping in new recruits mid-game. Needs a new roster-screen flow. Autoplay builds its party once from an empty roster, so it isn't affected.
- **Recommendation: Follow LairWare.**

**3. The starting square** (R-12)
- LairWare: a new party starts two squares further west than in the port.
- Port: you moved the start there yourself on 2026-11-15.
- If we follow LairWare: a two-square difference. The batch test party's start would move with it.
- **Recommendation: Keep port** (your earlier ruling).

**4. Two characters with the same name** (R-14)
- LairWare: tells characters apart by roster slot, so two with the same name can be in one party.
- Port: tells them apart by name. It refuses a second recruit with the same name, and Terminate can delete the wrong one of two same-named records.
- If we follow LairWare: same names allowed, and Terminate always removes the one you picked. Autoplay isn't affected.
- **Recommendation: Follow LairWare.**

## Rulings you made before the audit: food, poison, time (confirm keep?)

Your rulings from 2026-11-10 and 2026-11-14 aren't in the protected keep list, so the audit asks about them again.

**5. Starving and slow healing** (T-16, T-17)
- LairWare: a member with no food loses 5 HP on every tick (every turn on Sosaria, every 4th turn elsewhere). Every living member, even a poisoned or starving one, gets +1 HP on every 10th tick.
- Port: starving costs 5 HP only at each meal (every 10th or 40th turn). Only fed, unpoisoned members heal +1 at each meal.
- If we follow LairWare: starving kills much faster. Healing is about as fast but reaches the poisoned and starving too.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**6. Poison and mana speed** (T-18, T-20)
- LairWare: poison takes 1 HP every turn on Sosaria and every 4th turn in towns, castles and Ambrosia. Mana grows 1 per tick for every member, dead ones included. A Druid gains only +1 once it is past half of its INT or WIS.
- Port: poison takes 1 every turn everywhere. Mana grows 1 per turn on Sosaria and Ambrosia and every 4th turn in towns. A Druid gets +2. Living members only.
- If we follow LairWare: poison is milder indoors, and mana is slower on Ambrosia.
- **Recommendation: Keep port** (your 2026-11-10 ruling).

**7. Ticks during fights and in dungeons** (B-01, D-01)
- LairWare: in a fight, food, poison, mana and healing tick every 4th round. In dungeons they tick every 4th command, by the rules in questions 5 and 6.
- Port: nothing ticks in a land fight. A ship fight counts each round as a move (your 2026-11-13 "ship-once" ruling). Mana never grows in combat. Dungeons use the port's own tick rules, as on the surface.
- If we follow LairWare: long fights drain food and poison members, and casters regain a little MP.
- **Recommendation: Keep port.** It follows your earlier rulings and questions 5 and 6.

**8. The moons stop off Sosaria** (W-03)
- LairWare: the moons (and so the moongates) turn only on Sosaria. They stand still in towns, castles, dungeons and on Ambrosia, and stopped time doesn't freeze them.
- Port: the moons turn every 4th turn on Ambrosia and every 16th in towns, castles and dungeons, and stopped time freezes them.
- If we follow LairWare: waiting inside a town no longer changes the moongates.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**9. What stopped time stops** (T-13)
- LairWare: stopped time halts only the monsters. Meals, moons, poison and healing carry on, and it lasts longer, because its count runs only on turns when monsters would move.
- Port: it lasts 10 turns and also freezes meals and moons.
- If we follow LairWare: a longer freeze, but you keep eating while it lasts.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**10. The force field** (T-05)
- LairWare: checks members in order. The first one without the Mark of Force takes 99 damage, but the party gets through if anyone ahead of them had the mark. Dead members count. It looks like a bug.
- Port: you pass only if every living member has the mark, and each unmarked one takes 99.
- If we follow LairWare: one marked member in the lead gets everyone through.
- **Recommendation: Keep port** (your 2026-11-14 ruling, and LairWare's version looks like a bug).

## Rulings you made before the audit: fights, traps, thieves (confirm keep?)

**11. How many monsters attack** (B-09)
- LairWare: Lord British comes alone, and so does anyone else you fight in a town or castle. Guards and Castle Exodus come 8 strong. Sosaria, dungeons and Ambrosia send 1 to 8.
- Port: guards 8, Castle Exodus 8, everything else 1 to 8, so a merchant or Lord British can come 8 strong.
- If we follow LairWare: town fights other than guards are one-on-one.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**12. Monster hit points** (B-10)
- LairWare: higher HP caps, for example orc 48, skeleton 80, giant 112, balron 240.
- Port: orc 30, skeleton 50, giant 80, balron 180 (dragon 228 against LairWare's 224).
- If we follow LairWare: most fights last longer, and autoplay's early game gets harder.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**13. Guards can't be hurt** (B-11)
- LairWare: only Lord British can't be hurt. Guards take damage and die.
- Port: guards can't be hurt either.
- If we follow LairWare: you can kill guards. See question 31.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**14. Poison and theft in a fight** (B-12, B-13)
- LairWare: pinchers, balrons and Man-O-Wars can poison (1 in 4) on a hit or a miss, and when they cast. Thieves and pirate crews steal on a hit or a miss, and take the whole stack of a weapon or armour.
- Port: only a blow that lands (and that the member survives) can poison. Theft takes one item, at 1 in 16 for armour or 1 in 32 for a weapon.
- If we follow LairWare: much more poison, and gear can vanish fast.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**15. Whom monster spells target** (B-14)
- LairWare: a casting monster picks a random party position and casts only if that member is healthy. Otherwise it moves instead.
- Port: it picks any living member, poisoned ones included. The odds of casting are the same.
- If we follow LairWare: somewhat fewer monster spells land.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**16. Dungeon traps and gremlins** (D-13, D-14)
- LairWare: the first member's disarm skill decides a trap for the whole party, and a failure hits every living member for 8 to 127. A gremlin hits a random position (a dead one: nothing happens) and takes 100 food only from a member with at least 100.
- Port: each member dodges a trap by DEX, and the damage grows with level. A gremlin picks a living member and takes 100 food, down to 0.
- If we follow LairWare: traps hit everyone or no one. Gremlins can't empty a member's last food.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**17. The Alchemist's stealing bonus** (C-27)
- LairWare: Alchemists get a bonus for stealing and for disarming. LairWare added it; its own code notes that the Apple II version didn't have it.
- Port: Alchemists get the bonus for disarming but not for stealing.
- If we follow LairWare: Alchemists steal more easily.
- **Recommendation: Keep port** (your 2026-11-14 ruling; a LairWare-only rule).

## Death and coming back

**18. Dead at exactly 0 HP** (T-23)
- LairWare: a member brought down to 0 HP is dead.
- Port: a member dies only below 0, so one can stand at 0 HP.
- If we follow LairWare: slightly more deaths. Members raised by a healer still come back at 0 HP and alive, as in LairWare.
- **Recommendation: Follow LairWare.**

**19. HP after Surmandum or Anju Sermani** (P-21)
- LairWare: a raised member keeps the HP they had (0 after death), as the healer already does in the port. A caster with under 5 WIS who casts Anju Sermani wraps round to about 251 WIS, which looks like a bug.
- Port: a raised member gets 1 HP, and WIS stops at 0.
- If we follow LairWare: raised members come back at 0 HP and need healing. Keep the port's WIS floor.
- **Recommendation: Follow LairWare** on HP. Leave out the WIS bug.

**20. Resurrection when the whole party falls** (T-24)
- LairWare: offers a fresh start. Everyone is back to good health with 100 HP, 150 gold, a Dagger and Cloth and at least 100 food, but items and torches are lost and the world resets.
- Port: the game ends.
- If we follow LairWare: a party wipe is no longer final. Autoplay batches currently end at a wipe.
- **Recommendation: Keep port** (a LairWare-only addition).

## Spells

**21. Wizard spell I: Dag Lorum or Pabulum** (P-17)
- LairWare: spell I is Dag Lorum, a long-lasting light that works anywhere and is useful in dungeons.
- Port: spell I is Pabulum (5 to 9 food for every member, free in combat). The bundled manual names it.
- If we follow LairWare: the in-game book and manual change, and the letter stays I. Autoplay never casts it.
- **Recommendation: Follow LairWare.**

**22. How much light the light spells give** (P-18)
- LairWare: Lorum and Luminae set the light to exactly 10, cutting short a longer light. Sominae sets it to 250.
- Port: never shortens a light (at least 10). Sominae gives 235.
- If we follow LairWare: a small spell can cut short a torch.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**23. Necorp also weakens monsters** (P-19)
- LairWare: Necorp drops every monster to 5 HP, and that's all.
- Port: it also halves their melee damage.
- If we follow LairWare: Necorp is a little weaker. Auto-combat uses it (question 53).
- **Recommendation: Keep port** (your 2026-11-14 ruling).

**24. How Fal Divi works** (P-20)
- LairWare: after Fal Divi, the same caster picks a cleric spell, pays its MP and casts it, in or out of combat. In combat that uses the turn.
- Port: out of combat it reopens the whole cast prompt, so any member may cast. In combat it does nothing and the caster acts again.
- If we follow LairWare: Fal Divi becomes useful in combat.
- **Recommendation: Keep port** (your 2026-11-14 ruling).

## Wind and sea

**25. What the wind's name means** (T-08, naming part)
- LairWare: a NORTH wind blows from the north, so you can't sail north into it, as sailors name winds.
- Port: "Wind NORTH" stops you sailing south.
- If we follow LairWare: only the shown name flips. Which way you can sail is the same, so autoplay isn't affected.
- **Recommendation: Follow LairWare.**

**26. How often the wind changes, and wind after Exodus** (T-08, W-18)
- LairWare: the wind changes on a real-time clock, even while you wait. Before the current wind is ruled out, calm comes up 1 time in 9 and each direction 2 in 9. Once Exodus falls, the wind never stops a ship. Wind itself is an option in LairWare.
- Port: the wind changes every 20th move, chosen evenly among the other four outcomes. The wind still blocks after the fall.
- If we follow LairWare: real-time wind in a turn-based port.
- **Recommendation: Keep port** (your 2026-11-14 wind ruling).

**27. How fast the whirlpool moves** (M-01)
- LairWare: moves in real time, up to about 15 steps while you wait for a turn.
- Port: moves once per turn.
- If we follow LairWare: the whirlpool's speed depends on how fast you type.
- **Recommendation: Keep port** (LairWare's version is real time).

## Monsters and guards

**28. A new game starts with no monsters** (M-18)
- LairWare: a new standard game has no monsters on Sosaria. They arrive at 7 chances in 135 per turn.
- Port: fills the map with monsters at the start. The rule behind it cited LairWare's random-new-world code, not its new-game code.
- If we follow LairWare: a quieter start, which fits your "faithful to the original" spawning ruling. Autoplay's early game gets easier and batch baselines shift.
- **Recommendation: Follow LairWare.**

**29. Ambrosia's horses and jester attack** (M-12)
- LairWare: Ambrosia's data has every creature there, the two horses and the jester included, chase the party and start a fight.
- Port: horses and jester wander and never attack.
- If we follow LairWare: a few more easy fights on Ambrosia trips.
- **Recommendation: Follow LairWare.**

**30. Shots stop where you can't see** (M-17)
- LairWare: a pirate's or dragon's shot stops at the first square hidden from view (behind forest, mountains or walls).
- Port: shots ignore what you can see.
- If we follow LairWare: hiding behind mountains or forest protects you. This would use the port's own view, since LairWare's view drawing isn't ported. Autoplay's pirate dodging just becomes a little over-cautious.
- **Recommendation: Follow LairWare.**

**31. Town danger: after any town fight, guards and Lord British hunt you** (B-15)
- LairWare (original game code): any fight in a town or castle turns every guard and Lord British against the party for the rest of that visit. Lord British can't be hurt, so meeting him is near-certain death.
- Port: they stay as they were.
- If we follow LairWare: town fights become very dangerous, and more so with the port's unhurtable guards (question 13). Autoplay's Death Gulch raids depend on bribing guards, not running from them.
- **Recommendation: Defer** until it can be checked with seeded autoplay runs.

**32. Monsters calm down after Exodus falls** (W-13)
- LairWare: once Exodus falls, land monsters already on the map stop hunting after you come back from Ambrosia (and, with modern settings, from a town or dungeon).
- Port: those keep hunting. Only newly arriving ones wander.
- If we follow LairWare: a calmer world after the win.
- **Recommendation: Keep port** (a LairWare-only addition that depends on settings).

## Commands and dungeon fixtures

**33. S and L keys, and Search** (C-23)
- LairWare: S is Steal, L is Look, and Search is a typed word.
- Port: S is Search (with +100 XP and extras, from Java), L is Open, and Steal is typed.
- If we follow LairWare: the keys change and Search loses its bonuses. Autoplay presses S in dungeons.
- **Recommendation: Keep port.** It would break autoplay for little gain.

**34. When fountains, rods and the like trigger** (D-12)
- LairWare: a fixture fires after every command while you stand on it. A fountain keeps asking who drinks. The strange wind puts out the torch on every command. S does nothing in a dungeon.
- Port: wind, writing and the Time Lord fire when you step on. Fountains and marks work through S (one drink or touch).
- If we follow LairWare: the dungeon command flow changes, and autoplay's mark and fountain handling breaks.
- **Recommendation: Keep port.**

## LairWare-only extras

**35. Diagonal moves** (T-02, C-28, A-13)
- LairWare: by default you move, aim and fight diagonally (1/3/7/9), and auto-combat uses diagonals too. The "classic" setting turns this off.
- Port: up, down, left and right only, as classic.
- If we follow LairWare: a large change to movement, combat and autoplay.
- **Recommendation: Keep port** (classic rule).

**36. The turn passes when you wait, and auto-heal** (T-25, D-23)
- LairWare: if you don't press a key, the turn passes by itself (after 6 seconds in dungeons), and an auto-heal runs.
- Port: waits for your key.
- **Recommendation: Keep port** (real time, LairWare-only).

**37. Look, and Kreate (a random new world)** (C-24, C-25, W-21)
- LairWare: Look can bring a monster drawn into the map to life. After Exodus falls, K on Sosaria offers "Kreate": a random new world full of monsters.
- Port: has neither.
- **Recommendation: Keep port** (LairWare-only).

**38. Terraform, Armageddon, Flotellum** (P-16)
- LairWare: three extra wizard spells once Exodus falls: rewrite any square, turn every monster on the map into a chest, make a ship on the nearest water.
- Port: has none of them.
- **Recommendation: Keep port** (LairWare-only).

**39. Joke words, and the port's SCORE** (C-26)
- LairWare: has PAXUM (calms nearby chasers off Sosaria) and the joke words SCREAM and PISSOFF.
- Port: has none of these, but adds SCORE (shows the move count; you added it on 2026-11-14).
- **Recommendation: Keep port.**

**40. Debug key and secret wall names** (M-19, D-21)
- LairWare: has a debug key that shows or fills the monster table, and credits names drawn on walls on dungeon levels 7 and 8.
- Port: has neither.
- **Recommendation: Keep port** (LairWare-only).

## Likely LairWare bugs

**41. Swapping with an empty position** (R-16)
- LairWare: with fewer than four members, swapping into an empty position wipes out a member.
- Port: refuses ("What?").
- **Recommendation: Keep port.**

**42. The move count goes up by party size** (T-09)
- LairWare: each turn adds the number of members to the move count, which tops out at 99,999,999. It looks like a misread of the original counter.
- Port: adds 1 per turn, with no cap.
- **Recommendation: Keep port.**

**43. Food lost when it rolls over a hundred** (T-15)
- LairWare: each time a member's food drops through a hundred, one extra unit is lost (a leftover of the original's number format).
- Port: food goes down exactly.
- **Recommendation: Keep port.**

**44. Monsters walk the long way round** (M-06)
- LairWare: a monster 33 to 63 squares east of the party walks west, the long way round the world.
- Port: takes the short way, as the original did.
- **Recommendation: Keep port.**

**45. A wanderer kills other monsters** (M-09)
- LairWare: after Exodus falls, a wandering monster that steps onto a weaker one kills it. One of its step tries also uses another monster's direction.
- Port: neither.
- **Recommendation: Keep port.**

**46. A thrown last dagger hits as bare hands** (B-16)
- LairWare: throwing your last dagger unreadies it before the hit, so the throw does bare-hand damage.
- Port: the throw counts as a dagger.
- **Recommendation: Keep port.**

**47. Chest bomb damage doesn't grow with depth** (D-15)
- LairWare: the fixed part of a chest bomb's damage is 8 everywhere, because the value that should give the depth is never set.
- Port: 8 per dungeon level (8 on level 1, up to 64 on level 8), which is what the original most likely meant.
- **Recommendation: Keep port.**

**48. Cards and moons forgotten on reload** (C-29, W-08)
- LairWare: the order of inserted Exodus cards and the moon phases aren't saved, so they reset when you reload.
- Port: saves both.
- **Recommendation: Keep port.**

## Auto-combat

Auto-combat is the `TAB` helper, and autoplay relies on it in every fight. Its current settings were tuned on autoplay batches, so changes need seeded before-and-after runs.

**49. When to flee, heal and hold back** (A-01, A-06, A-11)
- LairWare: a member under 50 HP flees from an adjacent monster in a fixed order of directions, and if it can't, it waits rather than attacking. The last member standing flees too. A cleric heals with Sanctu only a member under 75 HP and never uses Sanctu Mani.
- Port: flee thresholds scale with max HP, and the last member never flees. It heals anyone under 75% of max HP, with Sanctu Mani first.
- If we follow LairWare: high-level parties heal only when nearly dead. This is autoplay's biggest survival lever.
- **Recommendation: Defer** (needs seeded autoplay runs).

**50. Free Repond and Pontori once per battle** (A-02)
- LairWare: one caster tries the free Repond (against orcs) or Pontori (against skeletons) once per battle.
- Port: every eligible caster tries. In a battle where it can't work, each one wastes its first turn.
- If we follow LairWare: fewer wasted turns early on.
- **Recommendation: Defer** (needs seeded autoplay runs).

**51. Aiming shots and Mittar** (A-07, A-09, A-12)
- LairWare: a wizard with 5+ MP and no good bow never melees. It casts Mittar at the nearest monster in line, at any range and over walls. Bows and slings shoot the same way, and daggers are never thrown.
- Port: hits an adjacent monster with its weapon first. It aims only up, down, left or right, within 5 squares for Mittar, and still treats walls as blocking, so it skips shots that would now land. It throws spare daggers.
- If we follow LairWare: casters burn more MP on Mittar.
- **Recommendation: Defer** (needs seeded autoplay runs).

**52. Moving into position** (A-10, A-11)
- LairWare: predicts where each monster will step and moves to line up a shot or close in, with no route-finding.
- Port: uses route-finding round walls, masts and allies, and attacks only up, down, left or right.
- If we follow LairWare: members can get stuck behind obstacles.
- **Recommendation: Defer** (needs seeded autoplay runs).

**53. The port's extra spell habits** (A-04, A-05, A-08)
- LairWare: has none of them.
- Port: a low-level caster opens with an area spell so it can catch up in levels. A wizard uses Noxum, Dag Mentar or Necorp against crowds, and Fulgar at sea.
- If we follow LairWare: autoplay's caster levelling and sea fights lose these.
- **Recommendation: Keep port.** Dropping them would break autoplay for little gain.

## Autoplay follow-ups

**54. The stat goals at the shrines (DEX 40)** (not a ledger row)
- Before: autoplay buys DEX 40 for everyone because the old rule made DEX 40 always hit.
- Now (B-04): half of all swings face a DEX roll. DEX 25 hits about 63% of the time, DEX 40 about 70%, DEX 50 about 75%, and DEX 99 always. Damage is about STR + 3 per weapon rank + 4, so each STR point adds about 1 damage per hit.
- Change: the plan could favour STR, or push DEX higher. Your last run won comfortably on the current plan.
- **Recommendation: Defer.** Keep the plan for now, and try a changed plan in a 100-seed batch later.

**55. Test parties get the starting Dagger and Cloth** (not a ledger row)
- Now: characters made on the roster screen start with a readied Dagger and Cloth (R-02). The party written by the new-game reset script and the headless batch parties don't get them.
- If we match: every autoplay party starts the same, but the batch win-rate baseline must be taken again once.
- **Recommendation: Follow LairWare.**

**56. Druid healing casts fail (bug)** (not a ledger row)
- Now: when a Druid casts Surmandum, Anju Sermani or Alcort on the map, autoplay doesn't answer the "Wizard or Cleric?" question, so the cast fails.
- Fix: answer Cleric. This only matters for parties with a Druid (the tested party has none).
- **Recommendation: Follow LairWare** (fix it).
