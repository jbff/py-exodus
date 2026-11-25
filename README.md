# py-exodus

A Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, with **Auto-Combat** (`TAB`) and a **Full Autoplay / Watch Mode** (`F9`) that plays the whole game, from party creation to Exodus.

---

## Reference Implementations & Assets

- **Original game**: [*Ultima III: Exodus*](https://wiki.ultimacodex.com/wiki/Ultima_III:_Exodus) (1983) by Richard Garriott / Origin Systems.
- **Port base: [pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus)**. `py-exodus` started as a port of Paul Antinori's LibGDX Java implementation, which also supplied the sound effects, `.ogg` soundtrack (transcoded from MIDI), XML definitions (`maps.xml`, `vendor.xml`, `creatures.xml`, `weapons.xml`, `armors.xml`) and the world maps/rosters (now JSON).
- **Graphics: the LairWare Mac port's tile sheets** (its PC EGA set by default; LairWare's own, Apple II, C64, MCGA and Ultima V sets with `--tiles`), animated the way LairWare animates them: people and monsters swap frames, water and lava scroll, Exodus blinks. Text is set in [Barlow Semi Condensed](https://github.com/jpt/barlow) (SIL Open Font License, `assets/fonts/OFL-Barlow.txt`).
- **Rules authority: the LairWare Mac port** (`UltimaMain.c`, `UltimaMisc.c`, `UltimaSpellCombat.c`, ...). Where the Java port and the classic releases disagree, **LairWare is the correct implementation**. Recent LairWare ports include:
  - **People move in towns and castles** (`MoveMonsters`): wanderers wander, shopkeepers follow, attackers close in and start a fight; in Castle Exodus the defenders come to you.
  - **The dead leave the combat board** and no longer block the living.
  - **Wind** steers ships on Ambrosia as on Sosaria, and is shown there too. A wind is named for where it blows from, as sailors name them: a NORTH wind stops a ship sailing north; a calm stops every ship. The wind changes on its own clock, about every 2.75 seconds of play (33 polls of 5/60 s), even while you stand idle, and not with your moves; it keeps time on the surface, in towns and in combat, but not in a dungeon. A new wind is never the old one: calm comes up 1 time in 9, each direction 2 in 9.
  - **Monster attacks**: hit chance by armor (`RandNum(0, armor+16) < 8`), damage that grows with the target's max HP, and a location bonus (+16 dungeon, +32 town, +48 castles and Ambrosia). Castle Exodus is a real fight now. Dragon fire always hits.
  - **Monster HP** in battle: 15 up to a cap set by the monster's kind (orcs 63, skeletons 95, clerics 111, giants 127, thieves and pirate crews 143, daemons and wizards 175, fighters and pinchers 207, dragons and serpents 239, balrons, Man-O-Wars and guards 255; merchants and jesters 47).
  - **Party attacks**: half of all swings face a DEX check (a 0-99 roll above DEX misses), the rest land; a landed blow does 0 to STR (odd) + STR/2 + 3 per weapon rank (Dagger 1 .. Exotic 15) + 4.
  - **Missiles** (sling, bows, a thrown dagger) fly over walls and water to the edge of the board, stopping only at a monster.
  - **The battlefield** is chosen by the ground the party stands on (grass, brush, forest or floor; anything else is grass), in towns too, not by the monster's tile.
  - **Monsters move and attack diagonally** on Sosaria (the party still can't).
  - **Monsters in battle** attack a member next to them, diagonals included; otherwise they step toward the nearest member they can reach, diagonally first (brush and forest never slow them, and they do not path around walls). Only dragons breathe fire (half their turns, along the line to their target, hitting the first member on it, no armour roll); serpents, Man-O-Wars, wizards, daemons, dragons and balrons may instead cast at a random party slot, but only at a member in good health (a poisoned, dead or empty slot and they move instead). Every attack or spell by a pincher, balron or Man-O-War poisons a healthy member one time in four, and every thief (pirate crews too) tries to pilfer a whole stack of one weapon or armour kind (never the readied or worn one), hit or miss.
  - **Monster ground**: land monsters start on grass and walk only on grass, brush, forest and floor (never lava, nor a parked ship, a horse or a dropped chest); serpents, Man-O-Wars and pirates start and sail only on open water.
  - **Selling weapons and armour** pays the shop's full price, only for what that shop stocks (Dawn's magic gear sells only at Dawn), never past 9999 gold (the sale is cancelled), a failed sale ("You don't own one of those!") ends the visit, and the readied weapon or worn armour can go too (back to hands or skin).
  - **Buying weapons and armour** stops at 99 of a kind, the readied weapon or worn armour counted ("Not enough room!", nothing charged).
  - **Grocers** sell rations at 1 gold each, as many as you like, never past 9,999 food ("Not enough room!"). Death Gulch, Montor West and Moon have one too; the cook in Castle British has no counter and only talks.
  - **Pubs**: a drink costs 7 gold (less and you are thrown out); pay up to 99 and the barkeep's line depends on the whole amount, a tenth of it picking one of LairWare's ten (7-9 gold: "Thank you, kindly!", 90-99: the Lord of Time).
  - **The oracle** takes one key, an offering of 0-9 hundred gold, each with its line of the rhyme (a typed "15" no longer costs 1,500 gold for nothing).
  - **Healers**: curing 100, healing 200, resurrection 500, recalling 900 gold. A healing restores full HP to anyone, the dead and ashes too; resurrection and recalling only bring the member back, with the HP they had (0, unless healed first).
  - **The guild** sells torches (5 for 30 gold), keys (50), powders (90) and gems (75), never past 99 of a kind (95 torches can't take another five: "Not enough room!").
  - **Horses** are sold in Devil Guard (and Dawn), not Grey, at 200 gold for each member (800 for four).
  - **Experience** stops at 9,899 (it used to run to 9,999).
  - **Join Gold** tops the receiver up to 9999 and leaves the rest with the givers (it used to destroy anything past 9999).
  - **Chest traps** are dodged by DEX, with a big bonus for Thieves; nobody is trap-proof.
  - **Chest contents**: 30-100 gold, and one chest in four may also hold a weapon (Dagger to 2-Handed Sword, about one chest in fourteen) or armour (Cloth to Chain, about one in twenty-five); stacks cap at 99. An acid trap burns the opener for 0-55 HP, Mark of Fire or not, and only a living member can open a chest.
  - **Letters as in LairWare**: `S` is Steal and `L` is Look (a direction, then the name of the monster there, plural outside towns and castles, or of the ground). There is no Search command: the Ambrosia cards come from the Other word `SEARCH`, and map spots give no items or experience to a search.
  - **Other commands**: Steal (`S`) rolls on DEX, with a big bonus for Thieves and a smaller one for Barbarians, Illusionists, Rangers and Alchemists (the same as disarming), and needs a shop counter next to the thief and the chest three tiles out (it becomes floor; the take is a chest's), a failed steal brings the guards down on you one time in four; a bribe costs 100 gold whoever takes it, and only a guard leaves; Dig sets your Exotic count to one; Pray works only at (48, 48) in Yew; every Other word needs a living member. `STEAL` is not an Other word.
  - **A beaten pirate** leaves a frigate on its tile only when you fought it from land; beat one from your own ship and the water stays open (it used to seal the Ambrosia channel).
  - **Unlock** is the only way through a door: every door is locked, a member's key opens one east or west of you (the key is spent), and the door turns into the ground beside it (in towns too). There is no Open command, and walking into a door doesn't open it.
  - **X-it** leaves a ship anywhere at sea (no shoreline needed) and a horse only on grass.
  - **Entering**: every town starts you at its west gate (1, 32), every castle at its south gate (32, 62).
  - **Lord British** raises one level (100 max HP) per visit, with no healing or cure, up to 25; past level 5 he wants the Mark of Kings. Talking to anyone (him, shopkeepers, townsfolk) needs a living member.
  - **Attack in towns**: `A` fights whoever stands in that direction, guards, merchants or townsfolk alike; beat one and a chest is left where it stood (unless on water), until you leave. Guards take weapon and spell damage and can be killed like anyone else (eight come to a guard fight; anyone else in a town, a merchant or Lord British, comes alone); Lord British takes no damage at all.
  - **Fights in towns call the guards**: any fight in a town or castle, whoever starts it (your `A`, or a hostile townsperson such as Death Gulch's merchants reaching you), turns every guard and Lord British against you. They hunt the party for the rest of the visit and attack when they reach it; the town is back to normal on your next visit. A failed steal (one time in four) sets the guards on you the same way, though not Lord British.
  - **Yell**: `EVOCARE` (with the Mark of Snake) carries the party three rows past the Great Earth Serpent, which stays; any other word works as an Other command.
  - **INSERT**: the Cards go in Love, Sol, Moons, Death order, each at its own panel; a card out of order, at the wrong panel or a second time kills the member who inserts it. A card is never used up: the member keeps it. Castle Exodus resets like every town: cards inserted on one visit no longer count after the party leaves, and card progress is never saved, so the order starts over at Love on each visit.
  - **The game ends when Exodus falls**, as in the 8-bit originals: the last card plays the ending, and its closing key returns to the title screen, as a dead party's game over does. Nothing is saved after the ending, so the last save stays the one made before entering Castle Exodus. LairWare's play after the win (the castle emptied, harmless wanderers, Lord British past 25, shrines past the race cap, Dag Acron aboard ship) is gone.
  - **Hand** (`H`): from, to, then **F**ood or **G**old with an amount (the taker holds at most 9,999), **E**quipment (gems, keys, powder, torches; at most 99), or one **W**eapon or **A**rmour by letter; the readied weapon or worn armour stays unless the giver has another.
  - **Death**: a member brought down to 0 HP is dead (it used to take less than 0). Raising (Surmandum, Anju Sermani, or a healer's resurrection or recalling) keeps the HP the member had, so one raised with 0 HP is alive, but the next blow, however small, kills again.
  - **Turns**: every letter command takes one turn, whether it works, is refused or is cancelled (one that starts a fight or leads into a new map is not given an extra turn on top), and that turn lets the monsters move once and counts stopped time down, `G`et included.
  - **Attack spells**: Mittar hits for 16-31 or 48-56 (`RandNum(0, 40) | 16`), Fulgar for 75, Mentar for the caster's INT, Decorp and Excuun always kill. Noxum (75 each), Dag Mentar (twice the caster's INT), ZXKUQYB and UNSPEAKABLE (death) strike each monster three times in four. No spell hurts Lord British.
  - **Repond and Pontori** get one try each per fight for the whole party, not per caster: the first cast uses it up, works half the time, and a later cast of the same spell that fight is refused. They work only on their own foe (orcs, skeletons): cast at the wrong kind they fail without using up the try. Auto-combat casts each only while its try is unused. **Altair** spends the caster's turn and holds the monsters for 20 rounds; winning the fight ends it.
  - **Dag Acron** drops the party on a random grass tile anywhere on Sosaria (never a monster's or a parked ship's); aboard ship it never works.
  - **Dag Lorum** is wizard spell I (Java's food spell Pabulum is gone): a long light, 250 turns of it in a dungeon. It casts anywhere, and in a fight it spends the turn.
  - **Fal Divi** (wizard J) lets the same caster pick a cleric spell and cast it, paying for both (if the cleric spell costs more than is left, "M.P. too low!" and only Fal Divi is spent). It works anywhere, and in a fight it spends the turn.
  - **Necorp** (wizard O, in a fight only) drops every living monster to 5 HP, and that is all: it leaves no weakness behind.
  - **Light never gets shorter**: Lorum and Luminae give at least 10 turns of light, Sominae and Dag Lorum at least 250 (Sominae used to give 235), a torch 255; none of them cuts short a light that would last longer.
  - **Who casts what**: only MP limits a caster, so a Ranger (up to 49 MP) can cast wizard I-J and cleric J too. Surmandum and Anju Sermani don't work in combat, and Dor Acron / Rec Du are refused on a dungeon's lowest level.
  - **Ambrosia's creatures all hunt the party**, its two horses and the jester too, and each fights as itself (a horse brings horses to the fight).
  - **Shrines**: no shrine screen. Enter on an Ambrosia shrine, name who enters, offer 0-9 hundred gold, all in the message log with the map still in view (no shrine picture or chant). The stat goes up by the offering, capped by race, and never past 99.
  - **Opening**: LairWare's intro sequence, with py-exodus's own C64-style title art (pyExodus and Ultima III dissolving in, kept blocky by whole-pixel scaling), "by Lord British" written stroke by stroke, the copyright line (Ultima III © 1983 Lord British / Richard Garriott; py-exodus © 2026), the duel under pixel-art stalactites, with the party and dragon drawn from the current tile set and blocky EGA-coloured fire; the crackle plays only while each logo dissolves in), then the View, a scripted scene of Sosaria with its tiles animating at the in-game pace, attacks drawn as combat's hit orbs, and the songs playing one after another, until a key. The main menu is silent. Any key skips the intro; the main menu has "Return to the View". Never in headless or autoplay runs.
  - **The turn**: left waiting at the command prompt with no key for 5 seconds (6 in a dungeon), the turn passes by itself, as Space would; it never does in a prompt, a menu, a shop or talk, Ztats (`Z` asks whose stats and shows only that member; it pauses the game, as in the original: any key closes it, and the wind and whirlpool stand still; in combat `Z` shows the active member and ends that member's turn), or while autoplay runs (LairWare's automatic healing while idle is not ported). In combat a member left waiting with no key for about 3.8 seconds (46 polls) passes, unless a prompt or Ztats is open, auto-combat is on or autoplay runs. A refused step (a wall, a mountain, the wind) still takes the turn; lava burns on the step onto it, not while you stand there; a town is left the moment you step onto its edge row or column. On horseback or aboard ship the monsters act only every other turn, and the people of a town or castle you ride into move only every other turn too; while time is stopped no new ones appear and nobody in a town or castle moves.
  - **Time and the body** (LairWare `AgeChars`): one tick every turn on Sosaria and every 4th turn anywhere else (towns, castles, dungeons, Ambrosia) and every 4th round of a fight. Each tick eats a tenth of a ration, takes 1 HP from the poisoned ("POISON!") and 5 HP from anyone whose food has run out ("STARVING!", every tick until fed), and gives every caster 1 MP up to their maximum, the dead and ashes too (a Druid 2, as the Book of Lore has it). Every 10th tick every living member heals 1 HP, poisoned or starving. Fights count no moves, aboard ship too.
  - **Stopped time** (`N`, a powder) holds the monsters for 10 turns on foot (about 20 on horse or ship, as they move only every other turn), counting only turns they would have moved; meals, moons, poison and healing carry on. Dungeon steps don't count it down.
  - **The moons** turn only on Sosaria (Trammel every 12 turns, Felucca every 4); in towns, castles, dungeons and on Ambrosia they stand still.
  - **Force fields** stop the party unless every living member has the Mark of Force; the first unmarked living member takes 99 HP (the dead and ashes don't count either way).
  - **Castle Exodus throws fireballs**: each turn one chance in 144 that a ball lands on the party, every living member losing 8-127 HP; stopped time doesn't last there.
  - **Moongates**: a new game starts with both moons at phase 4 (so no Dawn yet), and the new-moon gate stands at (8, 8). A gate takes the party at the end of any turn it is under it, so one that rises where the party stands (a pass, a refused step, a command) sends it on too. Monsters never step or appear on the visible gate, nor on Dawn while it shows. The gate tiles inside Castle British and Castle Exodus can be walked onto, and each sends the party to a random grass tile of that castle.
  - **New characters** start with a readied Dagger and Cloth (on top of 150 food and 150 gold), and a name keeps at most 12 letters.
  - **Forming a party starts a new game**: on foot at the start square, no moves made, the world reset. While a party is in play (saved), the roster screen shows it and won't add, remove or embark anyone; `X` disperses it first, writing what each member gained back to their roster slot (Journey Onward then has nothing to resume).
  - **Saving** (LairWare's classic AutoSave): one save slot. Besides `Q` on Sosaria, the game saves itself on entering a town, castle or dungeon (Castle Exodus included, so the last save is the one just before the castle), on leaving one, on the whirlpool trip to Ambrosia and back, each time a member dies (in a fight too), and when the whole party is wiped, before the game over (Journey Onward then finds no living party and opens the empty roster). Never inside a fight otherwise, never after the ending, and never in headless runs, batches, tests or while autoplay is on.
  - **The roster** knows each character by its slot, not its name: two characters may share a name and join the same party, and deleting one removes the one you picked.
  - **Party panel**: a card per member (race, class, sex and level in words; HP and MP bars; food, gold, stats, experience, weapon and armor; a colored edge and tag when poisoned, dead or ashes), then party supplies, quest chips for marks, cards and exotics, and location, turn, autoplay (with its goal) and autocombat.
  - **Ship cannons** (`F`, aboard ship): any of the four directions, up to 3 tiles, wrapping round the map; the first monster in the path is destroyed half the time (a pirate a quarter). No heading, no broadsides-only rule.
  - **Pirates and dragons fire back**: each turn, half the time, one within 3 tiles along a row, column or diagonal hits the whole party for 8-127 HP each; mountains and walls stop the shot, and so does any square hidden from your view (behind forest, mountains or walls), so cover protects you. Ships have no hull and cannot sink (only the whirlpool destroys a parked one).
  - **The whirlpool**: Sosaria has one, starting at (47, 17). It drifts on its own clock, one step about every third of a second of play while the game waits for your command (not with your moves, and not while a prompt is open), along its heading (any of eight directions), taking a new heading one time in eight or when land or a monster is in the way; it runs over a parked ship ("A ship was destroyed!") and takes a ship with the party aboard, even if you are standing still. Horse, ship and stopped time don't slow it.
  - **A new game starts with no monsters** on Sosaria; they arrive one at a time, a 7-in-135 chance each turn (the map used to start nearly full).
  - **Sosaria keeps its monsters**: they and the whirlpool wait out a trip to Ambrosia where they were (the whirlpool that took you moves off to (2, 62)), and a save keeps every one of them, not just the first 8, and every parked ship, horse and chest, not just 24.
  - **Dungeon turns**: every dungeon command takes exactly one turn (food, the torch, the chance of a fight), whether it works, is refused (a wall, no ladder) or is cancelled, turning and `Z` included; the party can't turn while standing in a doorway (step on or back out); a dungeon is entered at (1, 1) facing east. Hand (`H`), Join Gold (`J`), Negate Time (`N`) and Yell (`Y`, a word that works as an Other command) work in dungeons too. `A`, `B`, `E`, `F`, `L`, `Q`, `S`, `T`, `U` and `X` are refused there ("NOT A DNG CMD!") and still take the turn.
  - **Dungeon traps and gremlins**: a trap is sprung or evaded for the whole party on the first member's DEX roll (Thieves best, then Barbarians, Illusionists, Rangers and Alchemists), dead or alive; sprung, it costs every living member 8-127 HP. Gremlins pick a random member and, unless that one is dead, take 100 of their food (someone with less than 100 loses nothing). Both are gone once found.
  - **Dungeon fixtures act after every command** while the party stands on them (there is no Search; `S` and `L` are not dungeon commands): a fountain asks who will drink, and asks again after each drink until you press a key other than 1-4 (the answers take no turn); the red-hot rod asks who will touch it, marking one member (and burning 50 HP) per command; the Time Lord and the misty writing speak each time; the strange wind puts the torch out each time.
  - **Dungeon fountains and chests** serve only the living: the dead and ashes can't drink ("Can't") or open a chest ("Incapacitated!").
  - **Dungeon fixtures come from the map's own bytes**: a mark's kind and a fountain's kind follow the tile's column (x & 3), so the Time dungeon's mark at (11, 15) on level 8 is the Mark of Kings, not Fire, and the Snake dungeon's writing on level 5 is a writing again, not a fountain.
  - **Ignite** (`I`, in a dungeon) asks whose torch; that member burns one ("None left!" when they have none) and the light is fresh (255 turns) whether a torch was burning or not. `I` never puts a torch out.
  - **Dungeon fights**: no monsters roam the dungeons. Every command that leaves the party on an empty tile has a (3 + level)-in-(131 + level) chance of a fight (about 2% on the first level, 7% on the eighth): orcs, skeletons and giants on the first level, then daemons, pinchers, dragons and balrons further down (balrons from the fifth). A chest is left on that tile before the fight, whatever its end.
  - **Monster variants**: half of Sosaria's wanderers come as a named variant: Brigands and Cutpurses, Goblins and Trolls, Ghouls and Zombies, Golems and Titans, Gargoyles and Manes, Snatches and Bradles, Griffons and Wyverns, Orcuses and Devils. Same stats, new name, their own art.
- **Other classic references**: the Game Boy Color port (`u3gbc`) for moongate routing and ship-battle cannon barrages; the NES `MoonGateTbl` for the 8-site moongate table.

---

## Auto-Combat (`TAB`)

Borrowed in concept from the LairWare port: **`TAB`** (or `F2`) during any battle toggles tactical Auto-Combat. Each living member picks healing and cures when needed, offensive magic, or ranged/melee attacks; you can take back control at any moment. As in LairWare, a Wizard, Lark, Alchemist, Druid or Ranger with 5+ MP and no Bow +2 or +4 never melees: it casts Mittar at the nearest monster on its row or column, at any range and next to it too, and otherwise moves to line one up.

## Full Autoplay / Watch Mode (`F9`)

**`F9`** (or `--autoplay`) hands the game to `AutoPlayController`, which presses real keys through the live UI, so everything it does goes through the same rules you play by. **`[`** / **`]`** slow it down or speed it up. What it does, in order:

- **Tested party only**: autoplay has been tested and tuned with one party alone, the one `scripts/reset_new_game.py` writes to the roster and the headless batches build: SHADOW, Elf Thief (STR 15, DEX 25, INT 5, WIS 5); GRUMM, Dwarf Fighter (25/15/5/5); SERENA, Bobbit Cleric (15/5/5/25); ZIRCON, Fuzzy Wizard (15/5/25/5), 50 points each as LairWare allows, each with the readied Dagger and Cloth every new character gets (batches before 2026-11-25 started without them, so their win rates are not comparable). Batches before 2026-11-22 (up to `775884a`) gave the same four 60 points each. Started on an empty roster, autoplay creates this same party. How it fares with any other party is untested.
- **Party & outfitting**: creates a Thief / Fighter / Cleric / Wizard party, buys starter gear and armor upgrades, keeps food and gold balanced across members. Shopkeepers wander behind their counters (Montor East's shops have two each), so before Transacting it walks along the counter to the spot facing one. On the way out of a town with weapon and armour shops (never as a trip of its own), it sells spare gear: anything no living member would ready or wear over what they have, which the shop stocks, keeping a dead member's things for the resurrection.
- **Marks & exotics**: levels for the Mark of Kings, captures a frigate, sails (wind- and pirate-aware) to dig the Exotic weapons and armor, and clears the dungeons for the Marks of Fire, Force and Snake. It doesn't buy gems or peer: it already knows the dungeon layouts (as it knows plenty a new player wouldn't), so the gem it used to peer on every level was only a conceit, and it's gone. In dungeons it steps around gremlins where it can (each can take 100 food from a member), opens chests it walks over only the safe way (APPAR UNEM, or the Thief when no caster lives), and heads for the exit the moment anyone's food reaches 0.
- **Gold**: raids Death Gulch (with 4 keys for its doors, bought first if short: once at the guild it stocks up for every raid still to come, a key per 850 gold short of the target, as far as the gold allows above the bribe money; levelling parties buy them too, and a raid for a return trip runs 500 gold past the trip's cost so the food eaten on the way can't send it back, and 400 gold for the guards' bribes, and only with the Cleric's MP full: it waits at the gate, where MP returns four times faster than inside), opening chests safely with APPAR UNEM (waiting in place for MP), routing patiently around the moving townspeople, and bribing guards only where they block the way. Because a town fight sets every guard hunting (eight guards come to that fight, and Lord British can't be hurt), it keeps out of reach of hostile townspeople (in Death Gulch it leaves the armour shop's chests next to the merchant's counter; a roaming one, like Grey's thief, is only avoided while some route around it reaches the errand, otherwise the party goes anyway), and if the guards ever do hunt, it bribes one that reaches it (if one member holds the 100 gold) and walks straight out of town, never stepping next to a hunter where another step will do. With the Cleric dead, the Thief opens chests (then the Fighter, the Wizard last) so the party can still earn the gold to resurrect.
- **Ambrosia**: sails into the whirlpool for the four Cards, then makes return trips for shrine stats in plan order (Cleric WIS to its race maximum first, for ALCORT and the biggest APPAR UNEM pool; DEX 40 for all; Wizard INT 50/75/99; Fighter and Thief STR). A return trip raids only for what the remaining stats cost (at most about 8,500), and buys only the entry food, so stocking up doesn't send it back to raid. Each trip, cards or stats, budgets the gold, the food and 8 keys (Ambrosia's doors relock between visits, and the Moons card alone is behind three), and leaves while it still has a key for the water door.
- **Levels**: grinds every member to 25, starting on a loop near Britain's healer and Lord British and widening to the whole continent when nothing shows up for 150 moves. A Cleric below level 5 steps away from melee at half HP. Below level 8 the grind doesn't go after dragons (a chased party still fights them); from level 8, at full strength, it walks up to a dragon instead of dodging its fire. The Mark of Kings (needed to pass level 5) waits for three of the four at level 5, not all four. Lagging casters open fights with their strongest area spell so they earn the kills. Chests dropped on the surface are picked up straight away, errands included, unless that would court disaster: a weak party with no safe opener, a chest inside a firing lane, a poisoned member near death on the way to the cure, or a badly hurt party with monsters closing in. Hurt, it takes only chests within four steps; healthy and grinding, it fetches any it can reach. A chest a fight drops ashore while the party is on its ship is fetched too (leave ship, open, board again) when no sea monster is near.
- **The red-hot rod**: touches a mark's rod (50 HP) only with a member left at half health or better. A member who falls short is healed first: Sanctu by a Cleric, Druid or Paladin, or Sanctu Mani by a Cleric or Druid for a big gap. With no MP for that, the party waits on the rod while a healer's MP or its own HP comes back in time (well fed, not poisoned); otherwise (no healer, and poisoned or short of food) it leaves the mark and does not step back on while that holds.
- **The dead first**: with a member dead, food waits (until someone is down to 40) so the gold goes to the resurrection.
- **Poison**: a Cleric or Druid who can reach ALCORT's 35 MP cures on the spot once the MP is back, as long as the poisoned can afford the wait; otherwise a healer (100 gold).
- **Endgame**: only once every planned stat is bought, yells `EVOCARE` to pass the Great Earth Serpent, heals everyone to full HP and waits for every caster's MP to fill at the castle gate, fights through Castle Exodus and inserts the four Cards.
- **After the win**: once the four Cards are in, autoplay has no goal left and switches itself off: it leaves the ending to the player and doesn't resume a save from the title screen. A headless batch counts the run as WON there.

### Status

- **Wins from a fresh game, no cheats.** The latest 100-seed batch (`775884a`, LairWare combat rules, the final castle fighting back) won **58**, wiped 37 and hit the step cap 5 times, matching the easier-rules batch before it (`bbceab3`: 58 won, 39 wiped, 3 step caps). 34 of the 37 wipes are parties at level 10 or below. Live runs on 2026-11-22 won with every member at level 25.
- **Open fronts**: early-game wipes (being measured by the next 100-seed batch).

---

## Controls & Hotkeys

- **Movement**: arrow keys or numpad (ships sail straight off in any direction the wind allows; in dungeons `DOWN` steps backward). **Enter** / **Space** confirm and advance; **Esc** cancels.
- **`F1`**: Book of Lore, spell books and command reference, from any screen.
- **`TAB`** (or **`F2`**): Auto-Combat on/off in battle.
- **`F9`**: Full Autoplay on/off (**`[`** slower, **`]`** faster).
- **`F10`** *(with `--debug`)*: debug cheat menu.

---

## Installation & Running

Managed with [uv](https://docs.astral.sh/uv/) and a committed `uv.lock` (Python 3.10+, tested through 3.14):

```bash
git clone https://github.com/jbff/py-exodus.git
cd py-exodus
uv sync
uv run exodus          # or: uv run py-exodus
```

Without `uv`:

```bash
pip install pygame-ce sounddevice soundfile
python3 -m py_exodus
```

### Command-line options

| Flag | Effect |
|---|---|
| `--autoplay` | Start in Full Autoplay (Watch Mode); `F9` still toggles it. |
| `--trace` | Record the run to `traces/trace_<time>.jsonl.gz` (written when the game exits). |
| `--tiles NAME` | Tile set, from LairWare's sheets: `ega` (default), `lairware`, `apple2`, `c64`, `mcga`, `ultima5` (`--tiles list` prints them, the default first, marked `[default]`). |
| `--debug` | Enable the debug cheat harness (`F10`). |

Live play runs on wall-clock time and the `[` / `]` speed keys change it, so a live run can't be replayed exactly. There is no `--seed` flag.

### Headless batches and traces

Reproducible autoplay runs, one trace per seed, no window:

```bash
uv run python -m py_exodus.autoplay.batch --seeds 0-99 --workers 2 --out-dir traces/batch
```

Each seed prints `WON@<steps>`, `WIPED@<steps>` or `STEP_CAP@<steps>`. A trace row records position, goal, party state, the key pressed and **`why`**: the autoplay functions and lines that chose it. In towns it also lists the people within 4 tiles. So a loop in a trace names the code that caused it.

### Tests

```bash
uv run python -m pytest
```

About **1,800 tests** covering mechanics, LairWare/Java/GBC parity, vendors, dungeons, combat, rendering and autoplay regressions (most autoplay fixes come with a test that fails on the old code).

---

## Deliberate Deviations

1. **Wireframe dungeons**: a classic first-person wireframe view instead of Java's 3D pipeline (mechanics match). The wireframe makes depth hard to judge accurately, so the dungeon map overlay stays on by default (`P` hides it), even though the original has no such map.
2. **Fixed spell letters (A–P)**: spell menus keep the original A–P slots; an invalid cast refuses with `"Not Here!"` or the MP message.
3. **Classic GBC/LairWare rulings**: slow/fast moongate table, party-wide ship cannon barrage. Druids regain 2 MP a tick to their maximum (the Book of Lore; LairWare gives 1 per half they are under).
4. **Quality of life**: no quick-start party; `Q` saves only on the Sosaria overworld (the automatic saves above follow LairWare); `APPAR UNEM` opens the chest underfoot without a direction prompt; saves and rosters are JSON only; a shopkeeper's question is asked once, as the input prompt, with the answer on the same line (Java printed it and then prompted it again).
5. **LairWare oddities not ported**: a dungeon trap is avoided by a good DEX roll (LairWare's code springs it on a good roll and spares the party on a bad one); a force field lets the party through only when every living member has the Mark of Force (LairWare lets everyone through once a marked member comes before the one it strikes); cancelling Fal Divi's cleric prompt, or picking a cleric spell that can't be cast here, charges nothing more (LairWare could charge for a cancelled choice).
6. **Wind display**: reads `Wind NORTH` etc. in words, without arrow glyphs (`Wind NORTH` blows from the north, as LairWare's NORTH WIND does).

## Known Open Items

1. **Audio**: the poison/fire field sound cues (`Sound.POISON_EFFECT`, `Sound.FIREFIELD`) aren't wired yet.
2. **Input**: keyboard only.
3. **Autoplay**: early-game wipes are the main loss; see Status above.

---

## Utilities

- `scripts/render_maps.py`: renders the JSON maps to top-down PNGs in `maps_rendered/`.
- `scripts/autoplay_atlas.py`: summarizes autoplay traces.

---

## License

py-exodus's own code is [MIT](LICENSE). Material from elsewhere keeps its own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): LairWare's port (MIT), the Barlow font (OFL), and assets still derived from gdx-exodus, which publishes no license and which are being replaced with LairWare-derived equivalents. *Ultima III: Exodus* itself remains copyright © Richard Garriott / Origin Systems; this is an unofficial, non-commercial fan port.
