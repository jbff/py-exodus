"""Project-wide enums and constants for py-exodus (Ultima III)."""
from __future__ import annotations

from enum import Enum, IntFlag

# --- Screen & Grid Dimensions ---
SCREEN_WIDTH = 960
SCREEN_HEIGHT = 600
BASE_WIDTH = 320
BASE_HEIGHT = 200
SCALE = 3
TILE_SIZE = 16
VIEWPORT_TILES = 11
VIEWPORT_PIXELS = VIEWPORT_TILES * TILE_SIZE  # 176x176

WORLD_WIDTH = 64
WORLD_HEIGHT = 64
COMBAT_WIDTH = 11
COMBAT_HEIGHT = 11
DUNGEON_WIDTH = 16
DUNGEON_HEIGHT = 16
DUNGEON_LEVELS = 8

MAX_PARTY_MEMBERS = 4
MAX_ROSTER_SIZE = 20
MOON_PHASES = 24
MOON_SECONDS_PER_PHASE = 4


class Direction(Enum):
    """Direction enumeration with grid offsets and bitmask values."""

    WEST = (1, -1, 0, 0x1)
    NORTH = (2, 0, -1, 0x2)
    EAST = (3, 1, 0, 0x4)
    SOUTH = (4, 0, 1, 0x8)

    def __new__(cls, val: int, dx: int, dy: int, mask: int):
        obj = object.__new__(cls)
        obj._value_ = val
        obj.dx = dx
        obj.dy = dy
        obj.mask = mask
        return obj

    def reverse(self) -> Direction:
        """Return the opposite direction."""
        opposites = {
            Direction.NORTH: Direction.SOUTH,
            Direction.SOUTH: Direction.NORTH,
            Direction.WEST: Direction.EAST,
            Direction.EAST: Direction.WEST,
        }
        return opposites[self]

    @classmethod
    def from_name_or_key(cls, key: str) -> Direction | None:
        """Parse direction from key or character (e.g. 'N', 'UP', 'NORTH')."""
        k = key.strip().upper()
        if k in ("N", "NORTH", "UP"):
            return cls.NORTH
        if k in ("S", "SOUTH", "DOWN"):
            return cls.SOUTH
        if k in ("W", "WEST", "LEFT"):
            return cls.WEST
        if k in ("E", "EAST", "RIGHT"):
            return cls.EAST
        return None


class MapType(str, Enum):
    """Map type classification."""

    WORLD = "world"
    COMBAT = "combat"
    CITY = "city"
    DUNGEON = "dungeon"
    SHRINE = "shrine"

    @property
    def mask(self) -> int:
        masks = {
            MapType.WORLD: 0x01,
            MapType.COMBAT: 0x02,
            MapType.CITY: 0x04,
            MapType.DUNGEON: 0x08,
            MapType.SHRINE: 0x10,
        }
        return masks.get(self, 0)


class TileAttrib(IntFlag):
    """Tile behavioral attributes matching classic Ultima III flags."""

    NONE = 0
    UNWALKABLE = 0x000001
    CREATUREUNWALKABLE = 0x000002
    SWIMMABLE = 0x000004
    SAILABLE = 0x000008
    UNFLYABLE = 0x000010
    RANGEATTACKOVER = 0x000020
    CHEST = 0x000080
    DISPELABLE = 0x000100
    DOOR = 0x000200
    HORSE = 0x000400
    SHIP = 0x000800
    REPLACEMENT = 0x002000
    SNAKE = 0x004000
    LIVINGTHING = 0x008000
    LOCKEDDOOR = 0x010000
    SECRETDOOR = 0x040000


class Profession(str, Enum):
    """The 11 professions of Ultima III: Exodus."""

    BARBARIAN = "barbarian"
    DRUID = "druid"
    ALCHEMIST = "alchemist"
    RANGER = "ranger"
    FIGHTER = "fighter"
    WIZARD = "wizard"
    THIEF = "thief"
    LARK = "lark"
    ILLUSIONIST = "illusionist"
    CLERIC = "cleric"
    PALADIN = "paladin"

    @property
    def tile(self) -> str:
        tiles = {
            Profession.BARBARIAN: "fighter",
            Profession.DRUID: "cleric",
            Profession.ALCHEMIST: "wizard",
            Profession.RANGER: "ranger",
            Profession.FIGHTER: "fighter",
            Profession.WIZARD: "wizard",
            Profession.THIEF: "thief",
            Profession.LARK: "thief",
            Profession.ILLUSIONIST: "wizard",
            Profession.CLERIC: "cleric",
            Profession.PALADIN: "fighter",
        }
        return tiles[self]

    @property
    def mask(self) -> int:
        masks = {
            Profession.BARBARIAN: 0x001,
            Profession.DRUID: 0x002,
            Profession.ALCHEMIST: 0x004,
            Profession.RANGER: 0x008,
            Profession.FIGHTER: 0x010,
            Profession.WIZARD: 0x020,
            Profession.THIEF: 0x040,
            Profession.LARK: 0x080,
            Profession.ILLUSIONIST: 0x100,
            Profession.CLERIC: 0x200,
            Profession.PALADIN: 0x400,
        }
        return masks[self]


class Race(str, Enum):
    """The 5 player character races and their stat caps."""

    HUMAN = "human"
    ELF = "elf"
    DWARF = "dwarf"
    BOBIT = "bobit"
    FUZZY = "fuzzy"

    @property
    def code(self) -> str:
        codes = {
            Race.HUMAN: "H",
            Race.ELF: "E",
            Race.DWARF: "D",
            Race.BOBIT: "B",
            Race.FUZZY: "F",
        }
        return codes[self]

    @property
    def max_str(self) -> int:
        caps = {
            Race.HUMAN: 75,
            Race.ELF: 75,
            Race.DWARF: 99,
            Race.BOBIT: 75,
            Race.FUZZY: 25,
        }
        return caps[self]

    @property
    def max_dex(self) -> int:
        caps = {
            Race.HUMAN: 75,
            Race.ELF: 99,
            Race.DWARF: 75,
            Race.BOBIT: 50,
            Race.FUZZY: 99,
        }
        return caps[self]

    @property
    def max_int(self) -> int:
        caps = {
            Race.HUMAN: 75,
            Race.ELF: 75,
            Race.DWARF: 50,
            Race.BOBIT: 75,
            Race.FUZZY: 99,
        }
        return caps[self]

    @property
    def max_wis(self) -> int:
        caps = {
            Race.HUMAN: 75,
            Race.ELF: 50,
            Race.DWARF: 75,
            Race.BOBIT: 99,
            Race.FUZZY: 75,
        }
        return caps[self]

    @classmethod
    def from_code(cls, code: str) -> Race:
        lookup = {
            "H": cls.HUMAN,
            "E": cls.ELF,
            "D": cls.DWARF,
            "B": cls.BOBIT,
            "F": cls.FUZZY,
        }
        c = code.strip().upper()
        if c in lookup:
            return lookup[c]
        raise ValueError(f"Unknown race code: {code}")


class Spell(Enum):
    """The 32 spells of Ultima III (16 Sorcery / Wizard, 16 Prayer / Cleric)."""

    # --- Sorcery (Wizard) Spells A-P ---
    REPOND = ("A", 0, "Destroy orcs, gremlins, trolls", "wizard", 0x0AE, 0x02)
    MITTAR = ("B", 5, "Magic missile", "wizard", 0x0AE, 0x02)
    LORUM = ("C", 10, "Minor light spell", "wizard", 0x0AE, 0x08)
    DOR_ACRON = ("D", 15, "Down one dungeon level", "wizard", 0x0AE, 0x08)
    SUR_ACRON = ("E", 20, "Up one dungeon level", "wizard", 0x0AE, 0x08)
    FULGAR = ("F", 25, "Fireball", "wizard", 0x0AE, 0x02)
    DAG_ACRON = ("G", 30, "Random teleport on surface or combat", "wizard", 0x0AE, 0x03)
    MENTAR = ("H", 35, "Magic missile", "wizard", 0x0AE, 0x02)
    PABULUM = ("I", 40, "Feeds the many", "wizard", 0x0A6, 0xFF)
    FAL_DIVI = ("J", 45, "Cast a cleric spell", "wizard", 0x0A6, 0xFF)
    NOXUM = ("K", 50, "Multi-fireball", "wizard", 0x020, 0x02)
    DECORP = ("L", 55, "Death bolt", "wizard", 0x020, 0x02)
    ALTAIR = ("M", 60, "Stop time", "wizard", 0x020, 0xFF)
    DAG_MENTAR = ("N", 65, "Major multi-fireball", "wizard", 0x020, 0x02)
    NECORP = ("O", 70, "Weakens enemies", "wizard", 0x020, 0x02)
    UNSPEAKABLE = ("P", 75, "Multi-death bolt", "wizard", 0x020, 0x02)

    # --- Prayer (Cleric) Spells A-P ---
    PONTORI = ("A", 0, "Turn the undead", "cleric", 0x70A, 0x02)
    APPAR_UNEM = ("B", 5, "Disarm chest safely", "cleric", 0x70A, 0x0D)
    SANCTU = ("C", 10, "Minor healing", "cleric", 0x70A, 0xFF)
    LUMINAE = ("D", 15, "Minor light spell", "cleric", 0x70A, 0x08)
    REC_SU = ("E", 20, "Up one dungeon level", "cleric", 0x70A, 0x08)
    REC_DU = ("F", 25, "Down one dungeon level", "cleric", 0x70A, 0x08)
    LIB_REC = ("G", 30, "Random teleport in dungeon", "cleric", 0x70A, 0x08)
    ALCORT = ("H", 35, "Cure poison", "cleric", 0x70A, 0xFF)
    SEQUITU = ("I", 40, "Exit from dungeon", "cleric", 0x70A, 0x08)
    SOMINAE = ("J", 45, "Major light spell", "cleric", 0x702, 0x08)
    SANCTU_MANI = ("K", 50, "Major healing", "cleric", 0x702, 0xFF)
    VIEDA = ("L", 55, "Overhead view of surroundings", "cleric", 0x200, 0x05)
    EXCUUN = ("M", 60, "Death bolt", "cleric", 0x200, 0x02)
    SURMANDUM = ("N", 65, "Resurrection", "cleric", 0x200, 0xFF)
    ZXKUQYB = ("O", 70, "Multi-death bolt", "cleric", 0x200, 0x02)
    ANJU_SERMANI = ("P", 75, "Recall from ashes", "cleric", 0x200, 0xFF)

    def __init__(
        self,
        code: str,
        cost: int,
        desc: str,
        spell_type: str,
        castable_mask: int,
        location_mask: int,
    ):
        self.code = code
        self.cost = cost
        self.desc = desc
        self.spell_type = spell_type
        self.castable_mask = castable_mask
        self.location_mask = location_mask

    @property
    def mp_cost(self) -> int:
        """Alias for cost in magic points."""
        return self.cost

    def can_cast(self, profession: Profession) -> bool:
        """Check if the profession can cast this spell."""
        return bool(profession.mask & self.castable_mask)

    def can_cast_location(self, map_type: MapType) -> bool:
        """Check if spell can be cast in the given map type."""
        return bool(map_type.mask & self.location_mask)


class WeaponType(str, Enum):
    """Weapon types matching weapons.xml and classic Ultima III."""

    NONE = "NONE"
    DAGGER = "DAGGER"
    MACE = "MACE"
    SLING = "SLING"
    AXE = "AXE"
    BOW = "BOW"
    SWORD = "SWORD"
    SWORD_2H = "SWORD_2H"
    AXE_P2 = "AXE_P2"
    BOW_P2 = "BOW_P2"
    SWORD_P2 = "SWORD_P2"
    GLOVES = "GLOVES"
    AXE_P4 = "AXE_P4"
    BOW_P4 = "BOW_P4"
    SWORD_P4 = "SWORD_P4"
    EXOTIC = "EXOTIC"


class ArmorType(str, Enum):
    """Armor types matching armors.xml and classic Ultima III."""

    NONE = "NONE"
    CLOTH = "CLOTH"
    LEATHER = "LEATHER"
    CHAIN = "CHAIN"
    PLATE = "PLATE"
    CHAIN_P2 = "CHAIN_P2"
    PLATE_P2 = "PLATE_P2"
    EXOTIC = "EXOTIC"


class Status(str, Enum):
    """Party member status condition."""

    GOOD = "G"
    POISONED = "P"
    POISON = "P"
    ASH = "A"
    ASHES = "A"
    DEAD = "D"


StatusType = Status


class Sex(str, Enum):
    """Character sex."""

    MALE = "M"
    FEMALE = "F"


SexType = Sex


class Transport(str, Enum):
    """Active player transport type."""

    FOOT = "foot"
    HORSE = "horse"
    SHIP = "ship"
