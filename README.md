# py-exodus

A faithful Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, ported from the LibGDX Java reference implementation [gdx-exodus](https://github.com/pantinor/gdx-exodus).

---

## Provenance & Attribution

- **Original Game**: *Ultima III: Exodus* (1983) by Richard Garriott / Origin Systems.
- **Java LibGDX Reference**: Created by [Paul Antinori](https://github.com/pantinor) ([pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus)).
- **Python Port**: A complete, self-contained Python reimplementation built on top of [Pygame-CE](https://pyga.me/) (Python 3.10+).

This project uses the original asset definitions, tile atlases, sound effects, binary `.ult` world maps, and XML data (`maps.xml`, `vendor.xml`, `creatures.xml`) from the Java LibGDX implementation, translating all game logic, formulas, tactical combat, and dungeon mechanics into modern Python.

---

## Features & Mechanics

- **World Exploration**:
  - Full Sosaria overland, Ambrosia, towns, and castles.
  - Dual celestial moon phases (**Trammel** and **Felucca**) driving:
    - The mythical City of **Dawn**, appearing only during the double new moon conjunction (`trammel == 0, felucca == 0`).
    - Dynamic **moongates**, routing players across Sosaria based on Felucca's phase (`d1`, `d2`, `d3`).
  - Naval navigation with wind direction and headwinds.
  - Frigate broadside cannons (`'F'`), firing strictly perpendicular to heading and damaging sea monsters.
  - Defeating pirate ships leaves behind a boardable frigate instead of a chest.
  - Ambrosia whirlpool warp back to the Sosaria coast.
  - Map label searches (`'S'`) awarding **Exotic Armour**, **Exotic Weapons**, and the four mystical **Cards** (Death, Sol, Moons, Love) along with 100 XP.

- **Tactical 11×11 Combat Arena**:
  - Turn-based tactical combat matching original combat maps.
  - Ranged attacks, spells, creature AI pathfinding, obstacle evasion, and flee mechanics.
  - Visual projectile animations (arrows, Mittar blue magic missile, enemy blasts) and hit effects before unit removal.
  - Spells can pass through friendly party members to hit enemies.
  - 0-MP free prayers (`REPOND`, `PONTORI`) limited to 1 cast per combat encounter.

- **3D First-Person Wireframe Dungeons**:
  - Full 8-level dungeon corridors rendered with wireframe perspective projection.
  - Tile hazards: pit traps, wind traps (torch extinguishment), food-stealing gremlins, and poison/fire fields.
  - Interactive dungeon search (`'S'`):
    - Fountains: Healing (full heal), Acid (25 damage), Cure (cures poison), Poison, and Plain.
    - Marks branding: Mark of Kings, Mark of Fire, Mark of Force, Mark of the Snake (inflicts 50 damage, sets mark flag).
    - Magical Orbs (+5 to all stats, 50 damage).
    - Treasure chests with trap disarming.

- **Spells & Magic System**:
  - 16 Cleric spells and 16 Wizard spells faithfully implemented across overland, town, combat, and dungeons.
  - Single-key casting flow (`'C'`) with multi-discipline handling (Druids, Rangers).
  - `APPAR_UNEM` auto-collects chest gold, disarms traps, and clears the chest tile in a single action across overland, towns, and dungeons.

- **Specialty Town Vendors & Dialogues**:
  - **Taverns (`TAVERNINFO`)**: Food plates and ale service; tipping the bartender reveals rumors and clues from `vendor.xml`.
  - **Oracle (`ORACLEINFO`)**: Offering gold in hundreds (100–900 GP) reveals prophecies.
  - **Healers, Guilds, Armorers, Weaponsmiths, and Stables**: Full transactional inventories.
  - **Lord British**: Level advancement and resurrection.

- **Roster & Save State**:
  - Create and manage party members from 5 races and 11 professions.
  - Binary `PARTY.SAV` compatibility and JSON state serialization.

---

## Installation & Requirements

### Prerequisites
- Python 3.10+ (tested through Python 3.14)
- [Pygame-CE](https://pyga.me/) >= 2.5.0

### Setup
```bash
# Clone the repository
git clone https://github.com/jbff/py-exodus.git
cd py-exodus

# Install dependencies
pip install -r requirements.txt  # or: pip install pygame-ce pytest
```

---

## How to Play

Launch the game directly:
```bash
python3 -m py_exodus
```

### Controls

| Key | Command | Description |
|---|---|---|
| **Arrow Keys / Keypad** | Move | Move party or cursor (movement is strictly keys, letters reserved for commands) |
| **A** | Attack | Attack in direction (towns or combat) |
| **B** | Board | Board adjacent or co-located frigate or mount horse |
| **C** | Cast | Cast cleric or wizard spells |
| **D** | Descend | Descend ladder (dungeons or overworld) |
| **E** | Enter | Enter city, dungeon, shrine, or whirlpool portal |
| **F** | Fire | Fire frigate broadside cannons (East/West or North/South based on heading) |
| **G** | Get | Get/open treasure chest |
| **H** | Hand | Hand items, weapons, armors, or gold between members |
| **I** | Ignite | Light a torch from party pack |
| **J** | Join | Pool party gold |
| **K** | Klimb | Climb ladder upward |
| **L** | Look | Inspect terrain tile in direction |
| **M** | Modify | Reorder party members |
| **N** | Negate | Use strange powder to stop time |
| **O** | Other | Execute special or shrine commands (e.g., PRAY, BRIBE) |
| **P** | Peer | Use a gem to gaze across the realm |
| **Q** | Quick Save | Save current game state to `PARTY.SAV` |
| **R** | Ready | Ready a weapon from inventory (A–P single-key selection) |
| **S** | Search | Search tile for marks, fountains, exotic items, cards, or hidden portals |
| **T** | Transact | Talk/shop with NPCs and vendors across counters |
| **U** | Unlock | Unlock doors with skeleton keys |
| **V** | Volume | Toggle audio and music on/off |
| **W** | Wear | Wear armor from inventory (A–H single-key selection) |
| **X** | eXit | Dismount horse or disembark ship onto shore/water |
| **Y** | Yell | Shout word of power (e.g. EVOCARE) |
| **Z** | Ztats | Inspect character attributes, inventory counts, and status |
| **Space** | Pass | Pass turn |

---

## Running the Test Suite

The project includes an extensive test suite covering asset loading, combat arena, game loop, dungeon exploration, magic formulas, vehicle mechanics, and XML definitions:

```bash
pytest
```
Expected output:
```text
============================= 240 passed in 10.67s =============================
```

---

## Known Open Items & Differences from Original LibGDX

1. **Wireframe Dungeon Rendering**:
   - The Java implementation uses LibGDX's 3D OpenGL pipeline (`ModelBatch`, textured 3D meshes for walls/doors/floors).
   - `py-exodus` uses a high-performance software wireframe vector projection renderer, matching the authentic Apple II / classic PC aesthetic of Ultima III.
2. **Audio Playback**:
   - Sound effects and music use Pygame-CE's audio mixer (`.ogg` / `.wav` assets). Synthesizer / live MIDI playback from LibGDX is not used.
3. **Controller / Gamepad Support**:
   - Keyboard and keypad input are currently implemented; gamepad axis-to-direction mapping is planned for a future update.

---

## License

This reimplementation is intended for educational, preservation, and non-commercial archival purposes. Original game content, design, and assets remain copyright © their respective owners and Richard Garriott / Origin Systems.
