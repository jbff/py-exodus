"""Map data structures for py-exodus (World, City, Conflict, and Dungeon maps)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from py_exodus.constants import MapType

if TYPE_CHECKING:
    from py_exodus.assets import TileDef
    from py_exodus.entities.defs import LabelDef, MoongateDef, PortalDef


class DungeonTile(Enum):
    """Tiles and features appearing inside 3D dungeons."""

    display_name: str
    tile_name: str
    creature_walkable: bool

    NOTHING = (0x00, "Nothing", "floor", True)
    FLOOR = (0x01_00, "Floor", "floor", True)
    WATER = (0x02_00, "Water", "water", True)
    CEILING = (0x03_00, "Ceiling", "none", False)
    LADDER_UP = (0x10, "Ladder Up", "up_ladder", True)
    LADDER_DOWN = (0x20, "Ladder Down", "down_ladder", True)
    LADDER_UP_DOWN = (0x30, "Ladder Up & Down", "down_ladder", True)
    CEILING_HOLE = (0x04_00, "Ceiling Hole", "solid", False)
    FLOOR_HOLE = (0x05_00, "Floor Hole", "solid", False)
    ORB = (0x06_00, "Magic Orb", "magic", True)
    LIGHT = (0x07_00, "Light", "miss_flash", True)
    MOONGATE = (0x08_00, "Moongate", "moongate", True)
    ALTAR = (0x09_00, "Altar", "altar", True)
    CHEST = (0x40, "Treasure Chest", "chest", True)
    MARK = (0x05, "Mark", "whirlpool", True)
    MARK_SNAKE = (0x0A_00, "Mark of the Snake", "whirlpool", True)
    MARK_KINGS = (0x0B_00, "Mark of Kings", "whirlpool", True)
    MARK_FORCE = (0x0C_00, "Mark of Force", "whirlpool", True)
    MARK_FIRE = (0x0D_00, "Mark of Fire", "whirlpool", True)
    WIND_TRAP = (0x03, "Winds/Darkness Trap", "magic", True)
    GREMLINS = (0x06, "Gremlins", "jester", True)
    PIT_TRAP = (0x04, "Pit Trap", "fire", True)
    FOUNTAIN_PLAIN = (0x0E_00, "Plain Fountain", "Z", True)
    FOUNTAIN_HEAL = (0x02, "Healing Fountain", "H", True)
    FOUNTAIN_ACID = (0x0F_00, "Acid Fountain", "A", True)
    FOUNTAIN_CURE = (0x10_00, "Cure Fountain", "C", True)
    FOUNTAIN_POISON = (0x11_00, "Poison Fountain", "P", True)
    FIELD_POISON = (0x12_00, "Poison Field", "poison_field", False)
    FIELD_ENERGY = (0x13_00, "Energy Field", "energy_field", False)
    FIELD_FIRE = (0x14_00, "Fire Field", "fire_field", False)
    DOOR = (0xC0, "Door", "door", True)
    LOCKED_DOOR = (0x15_00, "Locked Door", "locked_door", False)
    SECRET_DOOR = (0xA0, "Secret Door", "secret_door", False)
    TIME_LORD = (0x01, "Time Lord", "lord_british", False)
    MISTY_WRITINGS = (0x08, "Misty Writings", "shrine", True)
    WALL = (0x80, "Wall", "brick_wall", False)

    def __new__(
        cls,
        val: int,
        display_name: str,
        tile_name: str,
        creature_walkable: bool,
    ):
        obj = object.__new__(cls)
        obj._value_ = val
        obj.display_name = display_name
        obj.tile_name = tile_name
        obj.creature_walkable = creature_walkable
        return obj

    @property
    def byte_value(self) -> int:
        return self._value_ & 0xFF

    @classmethod
    def get_tile_by_value(cls, byte_val: int) -> DungeonTile:
        """Map raw binary byte value from .ult file to DungeonTile."""
        mapping = {
            0x00: cls.NOTHING,
            0x01: cls.TIME_LORD,
            0x02: cls.FOUNTAIN_HEAL,
            0x03: cls.WIND_TRAP,
            0x04: cls.PIT_TRAP,
            0x05: cls.MARK,
            0x06: cls.GREMLINS,
            0x08: cls.MISTY_WRITINGS,
            0x10: cls.LADDER_UP,
            0x20: cls.LADDER_DOWN,
            0x30: cls.LADDER_UP_DOWN,
            0x40: cls.CHEST,
            0x80: cls.WALL,
            0xA0: cls.SECRET_DOOR,
            0xC0: cls.DOOR,
        }
        return mapping.get(byte_val & 0xFF, cls.FLOOR)

    @classmethod
    def from_name(cls, name: str) -> DungeonTile | None:
        """Find DungeonTile by exact or case-insensitive enum member name."""
        try:
            return cls[name.strip().upper()]
        except KeyError:
            return None


@dataclass
class MapNpc:
    """NPC entity in a town or city map loaded from city .ult files."""

    tile_index: int
    tile_name: str
    x: int
    y: int
    start_x: int
    start_y: int
    tile_def: TileDef | None = None


@dataclass
class GameMap:
    """2D tile grid map for Overworld, Cities, Castles, and Shrines."""

    id: int = 0
    name: str = ""
    fname: str = ""
    map_type: MapType = MapType.WORLD
    width: int = 64
    height: int = 64
    levels: int = 1
    border_behavior: str = "exit"
    music: str = ""
    no_line_of_sight: bool = False
    tiles: list[TileDef] = field(default_factory=list)
    npcs: list[MapNpc] = field(default_factory=list)
    portals: list[PortalDef] = field(default_factory=list)
    moongates: list[MoongateDef] = field(default_factory=list)
    labels: list[LabelDef] = field(default_factory=list)

    @property
    def people(self) -> list[MapNpc]:
        """Alias for npcs."""
        return self.npcs

    def get_tile(self, x: int, y: int) -> TileDef | None:
        """Get TileDef at (x, y), handling border wrapping when configured."""
        if self.border_behavior == "wrap":
            x = x % self.width
            y = y % self.height
        elif not (0 <= x < self.width and 0 <= y < self.height):
            return None
        idx = y * self.width + x
        if 0 <= idx < len(self.tiles):
            return self.tiles[idx]
        return None

    def set_tile(self, x: int, y: int, tile: TileDef) -> None:
        """Set TileDef at (x, y)."""
        if self.border_behavior == "wrap":
            x = x % self.width
            y = y % self.height
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = y * self.width + x
            if idx < len(self.tiles):
                self.tiles[idx] = tile

    def get_portal(self, x: int, y: int) -> PortalDef | None:
        """Find teleport portal at grid coordinate (x, y)."""
        for p in self.portals:
            if p.x == x and p.y == y:
                return p
        return None

    def get_moongate(self, phase_or_name: int | str) -> MoongateDef | None:
        """Find moongate by moon phase index or name."""
        for m in self.moongates:
            if isinstance(phase_or_name, int) and m.phase == phase_or_name:
                return m
            if (
                isinstance(phase_or_name, str)
                and m.name.lower() == phase_or_name.lower()
            ):
                return m
        return None

    def get_label(self, name: str) -> LabelDef | None:
        """Find label by name."""
        target = name.strip().lower()
        for lbl in self.labels:
            if lbl.name.strip().lower() == target:
                return lbl
        return None


@dataclass
class ConflictMap(GameMap):
    """11x11 tactical combat arena map with monster and player spawn coordinates."""

    map_type: MapType = MapType.COMBAT
    width: int = 11
    height: int = 11
    monster_starts: list[tuple[int, int]] = field(default_factory=list)
    player_starts: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class DungeonMap:
    """3D wireframe dungeon map (16x16x8 levels)."""

    id: int = 0
    name: str = ""
    fname: str = ""
    map_type: MapType = MapType.DUNGEON
    width: int = 16
    height: int = 16
    levels: int = 8
    border_behavior: str = "exit"
    music: str = "DUNGEON"
    level_texts: list[str] = field(default_factory=list)
    labels: list[LabelDef] = field(default_factory=list)
    tiles: list[list[list[DungeonTile]]] = field(default_factory=list)

    def get_tile(self, x: int, y: int, z: int) -> DungeonTile:
        """Get DungeonTile at coordinate (x, y, z) where z is level (0-7)."""
        if not (0 <= z < self.levels and 0 <= y < self.height and 0 <= x < self.width):
            return DungeonTile.WALL
        if self.tiles and len(self.tiles) > z:
            level_grid = self.tiles[z]
            if len(level_grid) > y and len(level_grid[y]) > x:
                return level_grid[y][x]
        return DungeonTile.WALL

    def set_tile(self, x: int, y: int, z: int, tile: DungeonTile) -> None:
        """Set DungeonTile at coordinate (x, y, z)."""
        if 0 <= z < self.levels and 0 <= y < self.height and 0 <= x < self.width:
            self.tiles[z][y][x] = tile
