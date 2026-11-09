# py-exodus

A faithful Python 3 / Pygame-CE reimplementation of *Ultima III: Exodus*, ported from the LibGDX Java reference implementation [gdx-exodus](https://github.com/pantinor/gdx-exodus).

---

## Provenance & Attribution

- **Original Game**: *Ultima III: Exodus* (1983) by Richard Garriott / Origin Systems.
- **Java LibGDX Reference**: Created by [Paul Antinori](https://github.com/pantinor) ([pantinor/gdx-exodus](https://github.com/pantinor/gdx-exodus)).
- **Python Port**: A complete, self-contained Python reimplementation built on top of [Pygame-CE](https://pyga.me/) (Python 3.10+; developed and tested through 3.14).

This project uses the original asset definitions, tile atlases, sound effects, binary `.ult` world maps, and XML data (`maps.xml`, `vendor.xml`, `creatures.xml`) from the Java LibGDX implementation, translating all game logic, formulas, tactical combat, and dungeon mechanics into modern Python. Game behavior is maintained at parity with the Java implementation: formulas, dice, thresholds, message strings, and even a few of the Java version's own quirks are ported as-is.

---

## Game Overview

Explore Sosaria (and Ambrosia) on foot, horseback, or by frigate; visit towns and castles to trade with vendors, gather rumors, and receive Lord British's advancement; find marks and cards hidden on dungeon floors and in map labels; descend the dungeon and destroy Exodus, the manifestation of Mondain and Minax — by inserting the four Cards of Love, Sol, Moons, and Death into the Exodus machine.

### World Exploration
- Full Sosaria overland, Ambrosia, towns, and castles; moongates cycle with the dual moon phases (Trammel/Felucca), and the City of Dawn appears only during the double new moon conjunction.
- Whirlpools engulf ships carrying the party to Ambrosia; step-in and portal-entry routes match the reference implementation.
- Naval travel with facing and broadside cannons (`'F'`); frigates take cannonball damage and can sink; defeating pirates leaves a boardable frigate.
- Terrain matters: poison and fire fields, lava, and gremlin tiles apply their effects every turn; energy fields require the Mark of Force to pass.

### Tactical 11×11 Combat Arena
- Turn-based tactical combat on the original combat maps with Java-equivalent creature dice (26% teleport, 34% ranged, double-damage fire/energy breath).
- Creature AI with randomized movement and Java's occupancy rules (members — including fallen ones — block movement).
- Experience is awarded for every kill you cause (capped at 9999) and victory chests drop where the creature fell.

### Dungeons
- 8-level wireframe dungeons (first-person projection), full command surface (climb/descend, search, chests, ready/wear, save).
- Wandering monsters approach your party level by level; battles can start mid-move, and the vanquished leave a chest.
- Fountains, wind and pit traps, gremlins, and the four Marks of Kings, Fire, Snake, and Force.

### Vendors
- Per-town weapon, armor, food, guild, healer, tavern, oracle, and horse-stable services with the reference implementation's dialog flows — buy and sell, multi-pack purchases, tavern rumors and ale tipping, oracle prophecies, healer cures/resurrections/recalls (charged only when the service can actually help), and blood donation.

### Characters & Magic
- Create characters from 5 races × 11 professions with a personal 50-point stat allocation; per-member food, gold, keys, gems, and quest marks/cards are tracked individually.
- 16 cleric and 16 wizard spells with Java-faithful dice and requirements; casting runs in combat, towns, dungeons, and the overworld, with the aura system (quickness/negate) gating spells and monster actions.

---

## Installation & Requirements

### Prerequisites
- Python 3.10+ (developed through 3.14)
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

All 26 letter commands match the reference implementation, including per-context behavior (the same letter can mean different things in a dungeon, in a town, on a ship, or in combat).

| Key | Command | Description |
|---|---|---|
| **Arrow Keys / Keypad** | Move | Move party (ships must first face the heading; dungeon DOWN steps backward) |
| **A** | Attack | Attack in a direction (combat, towns, or any creature tile) |
| **B** | Board | Board the frigate or horse standing on your tile ("Board What?" otherwise) |
| **C** | Cast | Cast cleric or wizard spells (member selection, then spell letter) |
| **D** | Descend | Descend a ladder (dungeons) |
| **E** | Enter | Enter a city, dungeon, shrine, castle, or whirlpool portal |
| **F** | Fire | Fire frigate broadside cannons (broadside only; 4-trace line) |
| **G** | Get | Open the treasure chest beneath the party |
| **H** | Hand | Hand a weapon or armor piece to another member |
| **I** | Ignite | Toggle a torch (dungeons; lights or extinguishes) |
| **J** | Join | Pool all members' gold into a chosen member (1–4) |
| **K** | Klimb | Climb a ladder upward (dungeons) |
| **L** | Open | Open an unlocked door in a direction |
| **M** | Modify | Reorder party members |
| **N** | Negate | Burn silver powder for a quickness aura (stops creatures for 6 turns) |
| **O** | Other | Type a special command (PRAY, BRIBE, STEAL, DIG, KISS, INSERT) |
| **P** | Peer | Use a gem to view a map of your surroundings |
| **Q** | Save | Save the game (Sosaria surface or anywhere in a dungeon) |
| **R** | Ready | Ready a weapon (member, then A–P) |
| **S** | Search | Search the party's tile (labels, fountains, chests, portals) |
| **T** | Transact | Talk or trade with NPCs and vendors (across signs) |
| **U** | Unlock | Unlock a door in a direction (uses a key) |
| **V** | Volume | Toggle audio and music |
| **W** | Wear | Wear armor (member, then A–H) |
| **X** | eXit | Dismount the horse, disembark the ship (foot only) |
| **Y** | Yell | Shout a word (EVOCARE — with the Mark of Snake — banishes the serpent) |
| **Z** | Ztats | Inspect stats, inventory, marks, and cards |
| **Space** | Pass | Pass a turn |
| **F1** | Book | Open the Book of Lore (any screen) |

---

## Running the Test Suite

The project has an extensive test suite covering asset loading, celestial routing, combat arena and parity dice, command semantics, chests, death flow, dungeon mechanics and specials, the endgame, magic, party/save state, tile effects, the turn tick, vendors, ships, and rendering:

```bash
pytest
```
All tests should pass; the count is printed at the end of the run.

---

## Documentation

`docs/superpowers/plans/2026-11-08-java-parity-fixes.md` documents a full Java↔Python parity audit (findings in `docs/superpowers/plans/2026-11-08-audit-findings.md`) and the fix plan that brought the port to parity.

---

## Known Open Items & Differences from Original LibGDX

1. **Wireframe dungeon rendering**: the Java implementation uses LibGDX's 3D pipeline; `py-exodus` uses a software wireframe renderer in the classic Ultima III style. Presentation only — mechanics match.
2. **Audio parity**: SFX/music play via Pygame-CE's mixer; some reference sound cues (e.g., trap and field effects) are not wired to every trigger.
3. **Controller/gamepad support**: keyboard only today; gamepad mapping is planned.
4. **Deliberate divergences from the Java port** (kept for playability): prompt-engine conveniences (ESC cancels, arrow keys commit); text instead of artwork for a few reference visualizations. The starter/quick-start party was removed (2026-11-09 user ruling) — new players create characters in the party-formation screen, as in Java.
5. **Not yet at parity**: Java's binary `party.sav` interop (saves are JSON; legacy binary roster import is read-only), combat-round move counting/hull repair during ship combat, and a small set of message-priority strings where the reference is silent — tracked for a future pass.

---

## License

This reimplementation is intended for educational, preservation, and non-commercial archival purposes. Original game content, design, and assets remain copyright © their respective owners and Richard Garriott / Origin Systems.
