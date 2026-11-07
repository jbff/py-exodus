"""Data models and entity definitions for Ultima III rules, creatures, weapons, and maps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from py_exodus.constants import Profession


class CaseInsensitiveDict(dict):
    """Dictionary supporting case-insensitive string key lookup."""

    def __init__(self, *args, **kwargs) -> None:
        self._lower_map: dict[str, Any] = {}
        super().__init__()
        self.update(*args, **kwargs)

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        if isinstance(key, str):
            self._lower_map[key.lower()] = key

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            mapped = self._lower_map.get(key.lower())
            if mapped is not None:
                return super().__getitem__(mapped)
        return super().__getitem__(key)

    def __contains__(self, key: Any) -> bool:
        if isinstance(key, str) and key.lower() in self._lower_map:
            return True
        return super().__contains__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if isinstance(key, str):
            mapped = self._lower_map.get(key.lower())
            if mapped is not None:
                return super().get(mapped, default)
        return super().get(key, default)

    def __delitem__(self, key: Any) -> None:
        if isinstance(key, str):
            mapped = self._lower_map.pop(key.lower(), None)
            if mapped is not None:
                super().__delitem__(mapped)
                return
        super().__delitem__(key)

    def update(self, *args, **kwargs) -> None:
        for k, v in dict(*args, **kwargs).items():
            self[k] = v

    def copy(self) -> CaseInsensitiveDict:
        new_dict = CaseInsensitiveDict()
        for k, v in self.items():
            new_dict[k] = v
        return new_dict


@dataclass
class CreatureDef:
    """Creature and enemy rules definition loaded from creatures.xml."""

    id: int
    name: str
    tile: str
    basehp: int = 48
    hp: int = 0
    exp: int = 0
    encounter_size: int = 1
    level: int = 1
    nes_exp: int = 0
    good: bool = False
    wont_attack: bool = False
    is_walkable_over: bool = False
    no_chest: bool = False
    invincible: bool = False
    undead: bool = False
    steals: str | None = None
    weak_against: str | None = None
    ranged: bool = False
    ranged_hit_tile: str | None = None
    ranged_miss_tile: str | None = None
    poisons: bool = False
    sails: bool = False
    swims: bool = False
    camouflage: bool = False
    camouflage_tile: str | None = None
    can_move_onto_avatar: bool = False
    casts: str | None = None
    divides: bool = False
    flies: bool = False
    force_of_nature: bool = False
    incorporeal: bool = False
    leaves_tile: bool = False
    resists: str | None = None
    spawns_on_death: bool = False
    teleports: bool = False

    def __post_init__(self) -> None:
        if self.hp == 0 and self.basehp > 0:
            self.hp = self.basehp

    @property
    def wontattack(self) -> bool:
        return self.wont_attack

    @property
    def isWalkableOver(self) -> bool:
        return self.is_walkable_over

    @property
    def nochest(self) -> bool:
        return self.no_chest

    @property
    def weakAgainst(self) -> str | None:
        return self.weak_against

    @property
    def encounterSize(self) -> int:
        return self.encounter_size

    @property
    def rangedhittile(self) -> str | None:
        return self.ranged_hit_tile

    @property
    def rangedmisstile(self) -> str | None:
        return self.ranged_miss_tile


@dataclass
class ConstraintDef:
    """Usage permission rule for weapons and armors based on profession."""

    can_use: bool = True
    char_class: str = "all"


@dataclass
class WeaponDef:
    """Weapon rules definition loaded from weapons.xml."""

    type: str
    name: str
    abbr: str = ""
    range: int = 1
    absolute_range: int = 0
    dmin: int = 0
    dmax: int = 0
    attack_through_objects: bool = False
    hit_tile: str = "none"
    leave_tile: str | None = None
    lose: bool = False
    lose_when_ranged: bool = False
    magic: bool = False
    miss_tile: str | None = None
    returns: bool = False
    constraints: list[ConstraintDef] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.absolute_range == 0:
            self.absolute_range = self.range

    def can_use(self, profession: Profession | str) -> bool:
        """Evaluate if the specified profession is permitted to equip this weapon."""
        if not self.constraints:
            return True
        prof_str = (
            profession.value.lower()
            if isinstance(profession, Profession)
            else str(profession).lower()
        )
        canuse = True
        for c in self.constraints:
            c_class = c.char_class.lower()
            if not c.can_use and (c_class == prof_str or c_class == "all"):
                canuse = False
            if c.can_use and c_class == prof_str:
                canuse = True
        return canuse

    @property
    def losewhenranged(self) -> bool:
        return self.lose_when_ranged


@dataclass
class ArmorDef:
    """Armor rules definition loaded from armors.xml."""

    type: str
    name: str
    defense: int = 128
    constraints: list[ConstraintDef] = field(default_factory=list)

    def can_use(self, profession: Profession | str) -> bool:
        """Evaluate if the specified profession is permitted to equip this armor."""
        if not self.constraints:
            return True
        prof_str = (
            profession.value.lower()
            if isinstance(profession, Profession)
            else str(profession).lower()
        )
        canuse = True
        for c in self.constraints:
            c_class = c.char_class.lower()
            if not c.can_use and (c_class == prof_str or c_class == "all"):
                canuse = False
            if c.can_use and c_class == prof_str:
                canuse = True
        return canuse


@dataclass
class VendorItemDef:
    """Single item or service sold by a vendor loaded from vendor.xml."""

    choice: str = ""
    item_type: str = ""
    name: str = ""
    price: int = 0
    quantity: int = 0
    weapon_type: str | None = None
    armor_type: str | None = None
    heal_type: str | None = None
    guild_item_type: str | None = None
    description: str | None = None
    room_x: int = 0
    room_y: int = 0
    hidden: bool = False


@dataclass
class VendorDef:
    """Vendor definition loaded from vendor.xml."""

    id: str
    name: str = ""
    owner: str = ""
    vendor_type: str = ""
    start_x: int = 0
    start_y: int = 0
    generic_field1: str | None = None
    items: list[VendorItemDef] = field(default_factory=list)

    @property
    def startX(self) -> int:
        return self.start_x

    @property
    def startY(self) -> int:
        return self.start_y

    @property
    def map_id(self) -> str:
        return self.id

    @property
    def genericField1(self) -> str | None:
        return self.generic_field1

    def get_item(self, choice: str) -> VendorItemDef | None:
        """Find an inventory item by key choice letter."""
        choice_lower = choice.strip().lower()
        for it in self.items:
            if it.choice.strip().lower() == choice_lower:
                return it
        return None


@dataclass
class VendorClassDef:
    """Vendor class category (e.g. WEAPON, ARMOR, FOOD, HEALER, etc.)."""

    type: str
    music: str = "SHOPPING"
    item_catalog: list[VendorItemDef] = field(default_factory=list)
    vendors: list[VendorDef] = field(default_factory=list)

    def get_item(self, choice: str) -> VendorItemDef | None:
        """Find a catalog item by key choice letter."""
        choice_lower = choice.strip().lower()
        for it in self.item_catalog:
            if it.choice.strip().lower() == choice_lower:
                return it
        return None


@dataclass
class PortalDef:
    """Map teleport portal definition loaded from maps.xml."""

    x: int
    y: int
    dest_map_id: int
    z: int = 0
    start_x: int = 0
    start_y: int = 0
    start_level: int = 0
    name: str | None = None
    exit_direction: str | None = None
    condition: str | None = None
    save_location: bool = False
    message: str | None = None
    transport: str | None = None

    @property
    def destmapid(self) -> int:
        return self.dest_map_id

    @property
    def startx(self) -> int:
        return self.start_x

    @property
    def starty(self) -> int:
        return self.start_y

    @property
    def startlevel(self) -> int:
        return self.start_level


@dataclass
class MoongateDef:
    """Moongate destination definition loaded from maps.xml."""

    name: str
    phase: int
    x: int
    y: int
    d1: int = 0
    d2: int = 0
    d3: int = 0


@dataclass
class LabelDef:
    """Special map label or fixture loaded from maps.xml."""

    name: str
    x: int
    y: int
    z: int = 0


@dataclass
class MapDef:
    """Map configuration loaded from maps.xml."""

    id: int
    map_type: str = "world"
    fname: str = ""
    width: int = 64
    height: int = 64
    levels: int = 1
    border_behavior: str = "exit"
    music: str = ""
    no_line_of_sight: bool = False
    tileset: str = "base"
    tilemap: str = "base"
    portals: list[PortalDef] = field(default_factory=list)
    moongates: list[MoongateDef] = field(default_factory=list)
    labels: list[LabelDef] = field(default_factory=list)

    @property
    def type(self) -> str:
        return self.map_type

    @property
    def borderbehavior(self) -> str:
        return self.border_behavior

    @property
    def nolineofsight(self) -> bool:
        return self.no_line_of_sight

    def get_portal(self, x: int, y: int, z: int = 0) -> PortalDef | None:
        """Find a portal at the given coordinate."""
        for p in self.portals:
            if p.x == x and p.y == y and p.z == z:
                return p
        return None

    def get_portals_to(self, dest_map_id: int) -> list[PortalDef]:
        """Find all portals that lead to a destination map."""
        return [p for p in self.portals if p.dest_map_id == dest_map_id]

    def get_moongate(self, phase: int) -> MoongateDef | None:
        """Find moongate for a specific moon phase (0-7)."""
        for m in self.moongates:
            if m.phase == phase:
                return m
        return None

    def get_labels(
        self, name: str | None = None, z: int | None = None
    ) -> list[LabelDef]:
        """Filter labels by name and/or z-floor level."""
        results = self.labels
        if name is not None:
            name_upper = name.strip().upper()
            results = [lbl for lbl in results if lbl.name.upper() == name_upper]
        if z is not None:
            results = [lbl for lbl in results if lbl.z == z]
        return results
