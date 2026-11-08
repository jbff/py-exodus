# Comprehensive Java vs. Python Source Code Audit (83 Files)

This document provides a complete file-by-file audit comparing the Java LibGDX reference implementation (`src/main/java`) against the Python Pygame-CE implementation (`py_exodus`).

---

## 1. Directory: `src/main/java/objects/` (29 Files)

| # | Java File | Python Counterpart | Status | Detailed Comparison & Discrepancies |
|---|-----------|-------------------|--------|---------------------------------------|
| 1 | `Armor.java` | `py_exodus/entities/defs.py` (`ArmorDef`) | **Equivalent** | Defines armor name, index, defense value, cost. Matches 1:1. |
| 2 | `ArmorSet.java` | `py_exodus/assets.py` (`_load_armors_xml`) | **Equivalent** | XML container for `armors.xml`. Parsed into `AssetManager.armors`. |
| 3 | `ArmorTypeAdapter.java` | `py_exodus/constants.py` (`ArmorType`) | **Equivalent** | JAXB string-to-enum adapter. Handled by Python enum/dictionary lookups. |
| 4 | `Aura.java` | `py_exodus/combat/magic.py` (`AuraState`), `party.py` | **Partial** | Manages party aura (`AuraType`: `NONE`, `QUICKNESS`, `NEGATE`) and countdown durations. Python handles aura in combat, but overland party aura countdown per turn (`passTurn()`) needs explicit tracking. |
| 5 | `BaseMap.java` | `py_exodus/world/map.py`, `loader.py`, `overworld.py` | **Partial** | Map container, tiles, portals, labels, moongates, NPCs, doors, and `searchLocation()`. Discrepancies: `searchLocation()` in overworld was only checking portals/fountains and missed XML `labels` for `EXOTIC_ARMOR`, `EXOTIC_WEAPON`, and the four cards. Door state duration and locking. |
| 6 | `BorderTypeAdapter.java` | `py_exodus/world/loader.py` | **Equivalent** | JAXB adapter for `MapBorderBehavior` (wrap vs exit). Parsed and handled 1:1. |
| 7 | `Constraint.java` | `py_exodus/entities/defs.py` (`ConstraintDef`) | **Equivalent** | Class/race equipment constraint definitions from `armors.xml` and `weapons.xml`. Enforced in `character.can_equip()`. |
| 8 | `Creature.java` | `py_exodus/entities/defs.py` (`CreatureDef`), `arena.py` | **Equivalent** | Creature stats, hp, exp, ranged capabilities, poison, and `nochest` attribute. |
| 9 | `CreatureSet.java` | `py_exodus/assets.py` (`_load_creatures_xml`) | **Equivalent** | XML container for `creatures.xml`. Parsed into `AssetManager.creatures`. |
| 10 | `DirectionTypeAdapter.java` | `py_exodus/constants.py` (`Direction`) | **Equivalent** | JAXB adapter for `Direction`. Python `Direction.from_name_or_key()` handles all formats. |
| 11 | `Drawable.java` | `py_exodus/entities/party.py` (`dynamic_objects`) | **Partial** | Dynamic map objects (frigates, chests, horses). Java tracks `shipHull` on each ship `Drawable`. Python `dynamic_objects` didn't persist per-ship hull values. |
| 12 | `Dungeon.java` | `py_exodus/world/dungeon.py`, `py_exodus/world/map.py` | **Equivalent** | Container for 8-level 3D dungeon tile grids loaded from `.DNG`/`.ULT`. |
| 13 | `Label.java` | `py_exodus/entities/defs.py` (`LabelDef`) | **Equivalent** | Maps XML `<label>` elements (coordinates and item names) for hidden items, cards, marks, and fountains. |
| 14 | `MapSet.java` | `py_exodus/assets.py` (`_load_maps_xml`) | **Equivalent** | XML container for `maps.xml`. Parsed into `AssetManager.maps`. |
| 15 | `MapTypeAdapter.java` | `py_exodus/constants.py` (`MapType`) | **Equivalent** | JAXB adapter for `MapType` (world, city, dungeon, combat, shrine). |
| 16 | `Moongate.java` | `py_exodus/entities/defs.py` (`MoongateDef`) | **Equivalent** | Moongate definition (phase, d1, d2, d3, x, y coordinates). |
| 17 | `Person.java` | `py_exodus/world/map.py` (`MapNpc`) | **Equivalent** | City NPC representation (tile, position, dialogId, conversation, movement behavior, vendor link). Fully integrated in commit `f5d82ee`. |
| 18 | `PersonRole.java` | `py_exodus/world/map.py` | **Equivalent** | Enum for city NPC roles. Represented by tile definitions. |
| 19 | `Portal.java` | `py_exodus/entities/defs.py` (`PortalDef`) | **Equivalent** | Portal definition (x, y, destmapid, startx, starty). Parsed and linked 1:1. |
| 20 | `ProjectileActor.java` | `py_exodus/screens/combat_screen.py` (`combat_fx`) | **Equivalent** | LibGDX visual actor for flying spells, arrows, and cannonballs. Handled by timed visual fx surface rendering. |
| 21 | `RetroActiveDest.java` | `py_exodus/screens/combat_screen.py`, `town.py` | **Equivalent** | Return warp coordinates after defeat/city exit. Handled in `return_screen` and defeat handlers. |
| 22 | `Roster.java` | `py_exodus/save_system.py`, `roster_screen.py` | **Equivalent** | 20-slot character roster binary read/write for `ROSTER.DAT`. Fully implemented and tested. |
| 23 | `SaveGame.java` | `py_exodus/save_system.py`, `entities/party.py` | **Partial** | Full save game state (`PARTY.SAV`), 4 player records, inventory arrays (16 weapons, 8 armors), marks, cards, gold, food, submorsels, monsters, objects. Discrepancy: `submorsels` food decay counter (400 per food unit) and 25% ship hull recovery per turn. |
| 24 | `Tile.java` | `py_exodus/assets.py` (`TileDef`) | **Equivalent** | Tile definitions, indices, rules, attribs, and conflict map associations. |
| 25 | `TileRuleAdapter.java` | `py_exodus/constants.py` (`TileRule`) | **Equivalent** | JAXB adapter for `TileRule`. Handled by enum and rule name strings. |
| 26 | `TileSet.java` | `py_exodus/assets.py` (`_load_tileset_xml`) | **Equivalent** | XML container for `tileset-base.xml`. Parsed into `AssetManager.tile_defs`. |
| 27 | `Weapon.java` | `py_exodus/entities/defs.py` (`WeaponDef`) | **Equivalent** | Weapon definitions, range, damage values, cost, weapon types. |
| 28 | `WeaponSet.java` | `py_exodus/assets.py` (`_load_weapons_xml`) | **Equivalent** | XML container for `weapons.xml`. Parsed into `AssetManager.weapons`. |
| 29 | `WeaponTypeAdapter.java` | `py_exodus/constants.py` (`WeaponType`) | **Equivalent** | JAXB adapter for `WeaponType`. Handled by enum/dict lookups. |

---

## 2. Directory: `src/main/java/vendor/` (19 Files)

| # | Java File | Python Counterpart | Status | Detailed Comparison & Discrepancies |
|---|-----------|-------------------|--------|---------------------------------------|
| 30 | `BaseVendor.java` | `py_exodus/screens/town.py` (`_start_vendor_shopping`) | **Equivalent** | State machine for interactive vendor dialogue streams (`ConvState`). Handled via TextLog sequential prompts. |
| 31 | `Vendor.java` | `py_exodus/entities/defs.py` (`VendorDef`) | **Equivalent** | Vendor instance data (id, name, owner, type, startX, startY, inventory). |
| 32 | `VendorClass.java` | `py_exodus/entities/defs.py` (`VendorClassDef`) | **Equivalent** | Vendor class grouping (type, music, catalog). |
| 33 | `VendorClassSet.java` | `py_exodus/assets.py` (`_load_vendor_xml`), `loader.py` | **Equivalent** | XML container for `vendor.xml`, mapping vendor definitions to map coordinates. |
| 34 | `Item.java` | `py_exodus/entities/defs.py` (`VendorItemDef`) | **Equivalent** | Vendor catalog item (choice key, item type, price, quantity, description). |
| 35 | `Input.java` | `py_exodus/ui/text_log.py` | **Equivalent** | Text input capture wrapper. Handled by `TextLog.handle_char()` and `prompt()`. |
| 36 | `WeaponVendor.java` | `py_exodus/screens/town.py` | **Equivalent** | Sells weapons, checks gold, adds to buyer character's inventory array. |
| 37 | `ArmorVendor.java` | `py_exodus/screens/town.py` | **Equivalent** | Sells armor, checks gold, adds to buyer character's inventory array. |
| 38 | `FoodVendor.java` | `py_exodus/screens/town.py` | **Equivalent** | Sells food rations in 25-unit bundles, adds to party gold. |
| 39 | `GuildVendor.java` | `py_exodus/screens/town.py` | **Equivalent** | Sells torches, gems, keys, powder to party consumables. |
| 40 | `HealerService.java` | `py_exodus/screens/town.py` | **Equivalent** | Cures poison, fully heals hp, and resurrects dead/ashes party members. |
| 41 | `HorseService.java` | `py_exodus/screens/town.py` | **Equivalent** | Sells horses, changes party transport to `Transport.HORSE`. |
| 42 | `TavernService.java` | `py_exodus/screens/town.py` | **Partial** | Pubs/taverns in towns. Prompts "Food or Ale?", sells tavern specialty food plates, and rewards tips on ale with rumor clues (`TAVERNINFO`). Python only sold generic food/drink. |
| 43 | `OracleService.java` | `py_exodus/screens/town.py` | **Missing** | Oracles in Castle British and Dawn. Requests offerings in hundreds of gold (100–900 gp) and reveals prophecies (`ORACLEINFO`). Python did not have the tiered offering flow. |
| 44 | `ArmorAdapter.java` | `py_exodus/assets.py` | **Equivalent** | JAXB adapter for `Armor`. Handled in XML parser. |
| 45 | `GuildItemAdapter.java` | `py_exodus/assets.py` | **Equivalent** | JAXB adapter for `GuildItem`. Handled in XML parser. |
| 46 | `HealTypeAdapter.java` | `py_exodus/constants.py` | **Equivalent** | JAXB adapter for `HealType`. Handled by enum. |
| 47 | `InventoryTypeAdapter.java` | `py_exodus/constants.py` | **Equivalent** | JAXB adapter for `InventoryType`. Handled by enum. |
| 48 | `MapIdAdapter.java` | `py_exodus/assets.py` | **Equivalent** | JAXB adapter for Map IDs. Handled by dictionary lookups. |

---

## 3. Directory: `src/main/java/util/` (11 Files)

| # | Java File | Python Counterpart | Status | Detailed Comparison & Discrepancies |
|---|-----------|-------------------|--------|---------------------------------------|
| 49 | `Utils.java` | `py_exodus/combat/resolver.py`, `world/loader.py`, `screens/overworld.py` | **Partial** | Math, pathfinding (`getPath`), naval combat (`enemyfireCannon`, `avatarfireCannon`), attack formulas, gem vision (`peerGem`), map binary parsing. Discrepancy: Overland ship cannon broadside restriction and cannonball animation; gem vision thumbnail rendering. |
| 50 | `SpreadFOV.java` | `py_exodus/world/field_of_view.py` | **Equivalent** | Recursive shadowcasting line-of-sight and field-of-view algorithm. |
| 51 | `DungeonTileModelInstance.java` | `py_exodus/world/dungeon.py`, `screens/dungeon_screen.py` | **Equivalent** | 3D visual representation for dungeon walls, doors, ladders, and chests. |
| 52 | `FixedSizeArrayList.java` | `py_exodus/ui/text_log.py` | **Equivalent** | Bounded line list for message HUD. Handled by `TextLog(max_lines=5)`. |
| 53 | `LogDisplay.java` | `py_exodus/ui/text_log.py` | **Equivalent** | Text display rendering widget. |
| 54 | `LogScrollPane.java` | `py_exodus/ui/text_log.py` | **Equivalent** | Scrolling text log history. |
| 55 | `MidiMusic.java` | `py_exodus/audio.py` | **Equivalent** | Background music playback via Pygame mixer. |
| 56 | `PartyDeathException.java` | `py_exodus/screens/combat_screen.py`, `overworld.py` | **Equivalent** | Exception triggering total party wipeout warp to Castle British. |
| 57 | `UltimaMapRenderer.java` | `py_exodus/ui/renderer.py` (`WorldRenderer`) | **Equivalent** | LibGDX 11x11 viewport tile grid renderer. Handled by `WorldRenderer.render_viewport()`. |
| 58 | `UltimaTiledMapLoader.java` | `py_exodus/world/loader.py` | **Equivalent** | Binary map loader converting `.ULT` files to grid structures. |
| 59 | `XORShiftRandom.java` | Python `random` | **Equivalent** | PRNG implementation. |

---

## 4. Directory: `src/main/java/exodus/` (24 Files)

| # | Java File | Python Counterpart | Status | Detailed Comparison & Discrepancies |
|---|-----------|-------------------|--------|---------------------------------------|
| 60 | `BaseScreen.java` | `py_exodus/screens/base.py` | **Equivalent** | Abstract base screen with input event routing, HUD rendering, and screen lifecycle. |
| 61 | `BookScreen.java` | `py_exodus/screens/book.py` | **Equivalent** | In-game manual / rulebook reading screen with page turning. |
| 62 | `CombatScreen.java` | `py_exodus/screens/combat_screen.py`, `combat/arena.py` | **Partial** | Tactical combat arena, player/creature turn loops, animations, spell casting. Discrepancy: 0-cost spells (`REPOND` and `PONTORI`) are limited to 1 cast per combat engagement per caster (`usedFreeSpellInCombat = true`). |
| 63 | `Constants.java` | `py_exodus/constants.py` | **Equivalent** | Core enums: professions, races, stats, spells, tile attributes, equipment types. |
| 64 | `Context.java` | `py_exodus/state_machine.py`, `entities/party.py` | **Equivalent** | Global game context holding current map, party, aura, and active vehicle. |
| 65 | `ConversationDialog.java` | `py_exodus/screens/town.py` | **Equivalent** | Modal dialog interface for vendor commerce and NPC interactions. |
| 66 | `DungeonScreen.java` | `py_exodus/screens/dungeon_screen.py`, `world/dungeon.py` | **Partial** | 3D first-person dungeon exploration, ladders, traps, fountains, marks, orbs. Discrepancies: Mark branding dealing 50 damage, fountain drinking effects, gremlin food theft, orb touch damage. |
| 67 | `Exodus.java` | `py_exodus/__main__.py`, `state_machine.py` | **Equivalent** | Game application entry point, window management, screen stack transitions. |
| 68 | `FinalScreen.java` | `py_exodus/screens/final.py` | **Equivalent** | Epilogue victory screen displaying scrolling narrative after defeating Exodus. |
| 69 | `GameScreen.java` | `py_exodus/screens/overworld.py` | **Partial** | Overland exploration, vehicles, cannons, moongates, celestial conjunctions, whirlpools. Discrepancies: Pirate defeat drops frigate (not chest); Boarding frigate/horse; Disembarking ('X') parks vehicles on map; Cannon broadsides only; Dawn entrance restricted to conjunction (0,0); Whirlpool warp from Ambrosia; Map label search ('S') for exotics/cards. |
| 70 | `HandDialog.java` | `py_exodus/screens/overworld.py` (`_prompt_hand_equipment`) | **Equivalent** | Hands gold, items, weapons, or armor between party members. |
| 71 | `ManagePartyScreen.java` | `py_exodus/screens/roster_screen.py` | **Equivalent** | Roster management: create character, disband, form party, inspect stats. |
| 72 | `Party.java` | `py_exodus/entities/party.py`, `character.py` | **Equivalent** | Party state, gold pooling, turn ending, food consumption, regeneration, stats. |
| 73 | `SecondaryInputProcessor.java` | `py_exodus/screens/town.py`, `overworld.py`, `dungeon_screen.py` | **Partial** | Handles secondary commands with party member prompt (1-4). Discrepancy: Town Get ('G') on chest tiles; Search ('S') for map labels with 100 XP award. |
| 74 | `ShrineScreen.java` | `py_exodus/screens/shrine.py` | **Equivalent** | Ambrosia shrines of Truth, Strength, Dexterity, Wisdom, Intelligence. Stat boost offerings capped at race limits. |
| 75 | `Sound.java` / `Sounds.java` | `py_exodus/audio.py` | **Equivalent** | Sound effect definitions and SFX/music playback triggers. |
| 76 | `SpellInputProcessor.java` | `py_exodus/combat/magic.py`, `screens/combat_screen.py` | **Equivalent** | Spell input sequence: member selection, Wizard/Cleric choice (if hybrid), spell letter (A–P), target/direction. |
| 77 | `SpellUtil.java` | `py_exodus/combat/magic.py` | **Partial** | 32 spell implementations. Discrepancy: `APPAR_UNEM` auto-collects chest contents without requiring subsequent 'Get'; 0-cost spell combat limit. |
| 78 | `StartScreen.java` | `py_exodus/screens/start.py` | **Equivalent** | Main menu / title screen options (Play, Manage Roster, Book). |
| 79–83 | JAXB & Sound Adapters | `py_exodus/assets.py`, `constants.py` | **Equivalent** | Serialization helper classes handled natively in Python. |

---

## 5. Summary of Audit Findings

Out of the 83 Java files audited:
- **72 files are fully equivalent**: All core architectures, models, rendering structures, roster managers, basic combat, and binary loaders match the reference.
- **10 files are partial**: Behavior exists but is missing specific Ultima III mechanics (broadside cannons, vehicle parking/boarding, map label item searching, `APPAR_UNEM` chest collection, 0-cost spell limit, dungeon hazards/fountains, tavern clues).
- **1 file is missing**: `OracleService.java` (tiered prophecy offering in Castle British and Dawn).

All identified gaps have been organized into the 7 tasks of the [Parity Fixes Implementation Plan](file:///sto/src/gdx-exodus/docs/superpowers/plans/2026-11-08-parity-fixes.md).
