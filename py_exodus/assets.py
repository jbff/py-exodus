"""Asset management, texture atlas parsing, EGA tile slicing, and resource resolution."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pygame

from py_exodus.constants import TileAttrib
from py_exodus.entities.defs import (
    ArmorDef,
    CaseInsensitiveDict,
    ConstraintDef,
    CreatureDef,
    LabelDef,
    MapDef,
    MoongateDef,
    PortalDef,
    VendorClassDef,
    VendorDef,
    VendorItemDef,
    WeaponDef,
)

# Combat Map ID and Filename mappings (matching classic Ultima III conflict arenas)
COMBAT_MAPS: dict[int, str] = {
    33: "CNFLCT_A.ULT",  # CONFLICT_SHIP_TOP
    34: "CNFLCT_B.ULT",  # CONFLICT_GRASS_BRUSH
    35: "CNFLCT_C.ULT",  # CONFLICT_BRICK_FLOOR
    36: "CNFLCT_F.ULT",  # CONFLICT_GRASS_FOREST
    37: "CNFLCT_G.ULT",  # CONFLICT_GRASS
    38: "CNFLCT_M.ULT",  # CONFLICT_SHORE
    39: "CNFLCT_Q.ULT",  # CONFLICT_SHIP
    40: "CNFLCT_R.ULT",  # CONFLICT_SHIP_BOTTOM
    41: "CNFLCT_S.ULT",  # CONFLICT_BOTH_SHIPS
}

# Maps enum name to integer map ID (matching classic Ultima III and maps.xml)
MAP_NAME_TO_ID: dict[str, int] = {
    "SOSARIA": 0,
    "BRITISH": 1,
    "EXODUS": 2,
    "LCB": 3,
    "YEW": 4,
    "MOON": 5,
    "GREY": 6,
    "DEVIL": 7,
    "MONTOR_E": 8,
    "MONTOR_W": 9,
    "DEATH": 10,
    "DAWN": 11,
    "FAWN": 12,
    "AMBROSIA": 13,
    "PERINIAN": 14,
    "DARDIN": 15,
    "MINE": 16,
    "FIRE": 17,
    "DOOM": 18,
    "SNAKE": 19,
    "TIME": 20,
    "CONFLICT_SHIP_TOP": 33,
    "CONFLICT_GRASS_BRUSH": 34,
    "CONFLICT_BRICK_FLOOR": 35,
    "CONFLICT_GRASS_FOREST": 36,
    "CONFLICT_GRASS": 37,
    "CONFLICT_SHORE": 38,
    "CONFLICT_SHIP": 39,
    "CONFLICT_SHIP_BOTTOM": 40,
    "CONFLICT_BOTH_SHIPS": 41,
    "SHRINE_WISDOM": 55,
    "SHRINE_DEXTERITY": 56,
    "SHRINE_INTELLIGENCE": 57,
    "SHRINE_STRENGTH": 58,
}
MAP_ID_TO_NAME: dict[int, str] = {v: k for k, v in MAP_NAME_TO_ID.items()}

# Rule attributes mapping from XML rule string to TileAttrib IntFlag
RULE_ATTRIBS: dict[str, TileAttrib] = {
    "none": TileAttrib.NONE,
    "water": (
        TileAttrib.UNWALKABLE
        | TileAttrib.SWIMMABLE
        | TileAttrib.SAILABLE
        | TileAttrib.RANGEATTACKOVER
    ),
    "shallows": (
        TileAttrib.UNWALKABLE
        | TileAttrib.SWIMMABLE
        | TileAttrib.RANGEATTACKOVER
    ),
    "swamp": TileAttrib.NONE,
    "grass": TileAttrib.REPLACEMENT,
    "brush": TileAttrib.NONE,
    "hills": TileAttrib.NONE,
    "mountains": (
        TileAttrib.UNWALKABLE
        | TileAttrib.UNFLYABLE
        | TileAttrib.CREATUREUNWALKABLE
    ),
    "lcb": TileAttrib.UNWALKABLE | TileAttrib.CREATUREUNWALKABLE,
    "lcb_entrance": TileAttrib.CREATUREUNWALKABLE,
    "ship": TileAttrib.SHIP | TileAttrib.CREATUREUNWALKABLE,
    "horse": TileAttrib.HORSE | TileAttrib.CREATUREUNWALKABLE,
    "floors": TileAttrib.REPLACEMENT,
    "person": TileAttrib.LIVINGTHING | TileAttrib.UNWALKABLE,
    "merchant": TileAttrib.LIVINGTHING | TileAttrib.UNWALKABLE,
    "solid": TileAttrib.UNWALKABLE | TileAttrib.RANGEATTACKOVER,
    "walls": TileAttrib.UNWALKABLE | TileAttrib.UNFLYABLE,
    "locked_door": (
        TileAttrib.UNWALKABLE
        | TileAttrib.LOCKEDDOOR
        | TileAttrib.CREATUREUNWALKABLE
        | TileAttrib.UNFLYABLE
    ),
    "door": (
        TileAttrib.UNWALKABLE
        | TileAttrib.DOOR
        | TileAttrib.CREATUREUNWALKABLE
        | TileAttrib.UNFLYABLE
    ),
    "secret_door": (
        TileAttrib.SECRETDOOR
        | TileAttrib.CREATUREUNWALKABLE
        | TileAttrib.UNFLYABLE
    ),
    "chest": TileAttrib.CHEST,
    "poison": TileAttrib.DISPELABLE,
    "energy": (
        TileAttrib.DISPELABLE
        | TileAttrib.UNFLYABLE
        | TileAttrib.UNWALKABLE
        | TileAttrib.CREATUREUNWALKABLE
    ),
    "fire": TileAttrib.DISPELABLE,
    "lava": TileAttrib.REPLACEMENT,
    "signs": (
        TileAttrib.UNWALKABLE
        | TileAttrib.UNFLYABLE
        | TileAttrib.RANGEATTACKOVER
    ),
    "spacers": TileAttrib.UNWALKABLE | TileAttrib.RANGEATTACKOVER,
    "snake": (
        TileAttrib.SNAKE
        | TileAttrib.UNWALKABLE
        | TileAttrib.SWIMMABLE
        | TileAttrib.SAILABLE
    ),
    "monster": TileAttrib.LIVINGTHING | TileAttrib.UNWALKABLE,
}

# Tile name to combat map ID mapping (matching Java TileSet rules)
TILE_COMBAT_MAP_IDS: dict[str, int] = {
    "water": 41,       # CONFLICT_BOTH_SHIPS
    "sea": 41,         # CONFLICT_BOTH_SHIPS
    "horse": 37,       # CONFLICT_GRASS
    "grass": 37,       # CONFLICT_GRASS
    "moongate": 37,    # CONFLICT_GRASS
    "brush": 34,       # CONFLICT_GRASS_BRUSH
    "shrine": 34,      # CONFLICT_GRASS_BRUSH
    "forest": 36,      # CONFLICT_GRASS_FOREST
    "dungeon": 35,     # CONFLICT_BRICK_FLOOR
    "city": 35,        # CONFLICT_BRICK_FLOOR
    "castle": 35,      # CONFLICT_BRICK_FLOOR
    "towne": 35,       # CONFLICT_BRICK_FLOOR
    "lcb_entrance": 35,# CONFLICT_BRICK_FLOOR
    "chest": 35,       # CONFLICT_BRICK_FLOOR
    "floor": 35,       # CONFLICT_BRICK_FLOOR
    "door": 35,        # CONFLICT_BRICK_FLOOR
    "secret_door": 35, # CONFLICT_BRICK_FLOOR
    "locked_door": 35, # CONFLICT_BRICK_FLOOR
    "energy_field": 35,# CONFLICT_BRICK_FLOOR
    "lava": 35,        # CONFLICT_BRICK_FLOOR
}


@dataclass
class TileDef:
    """Definition and attributes for a map tile."""

    index: int
    name: str
    rule: str = "none"
    opaque: bool = False
    attribs: TileAttrib = TileAttrib.NONE
    combat_map_id: int = 37
    combat_map_fname: str = "CNFLCT_G.ULT"

    @property
    def combat_map(self) -> int:
        """Alias for combat_map_id."""
        return self.combat_map_id

    @property
    def walkable(self) -> bool:
        """Check if party can walk on this tile."""
        return not bool(self.attribs & TileAttrib.UNWALKABLE)

    @property
    def living(self) -> bool:
        """Check if tile represents a living creature or person."""
        return bool(self.attribs & TileAttrib.LIVINGTHING)

    @property
    def swimmable(self) -> bool:
        """Check if tile is water/swimmable."""
        return bool(self.attribs & TileAttrib.SWIMMABLE)

    @property
    def sailable(self) -> bool:
        """Check if tile can be sailed on with a ship."""
        return bool(self.attribs & TileAttrib.SAILABLE)


ENTITY_TILES: set[str] = {
    "fighter", "cleric", "wizard", "thief", "ranger", "guard", "jester", "merchant", "lord_british",
    "orc", "skeleton", "giant", "daemon", "pincher", "dragon", "balron", "pirate", "serpent", "squid",
    "horse", "frigate", "chest", "whirlpool", "moongate", "corpse", "magic", "fire",
}


def load_image_surface(path: Path | str) -> pygame.Surface:
    """Load an image into a Pygame Surface with PNG and BMP fallback support."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    # If SDL_image has extended format support, attempt standard load
    if pygame.image.get_extended():
        try:
            return pygame.image.load(str(path))
        except Exception:
            pass

    # Fallback using Pillow (PIL) for systems without SDL_image PNG support
    try:
        from PIL import Image

        with Image.open(str(path)) as pil_img:
            rgba = pil_img.convert("RGBA")
            data = rgba.tobytes()
            size = rgba.size
            if hasattr(pygame.image, "frombytes"):
                return pygame.image.frombytes(data, size, "RGBA")
            return pygame.image.fromstring(data, size, "RGBA")
    except Exception:
        # Final attempt with standard pygame load
        return pygame.image.load(str(path))


def _parse_bool(val: str | None, default: bool = False) -> bool:
    """Parse boolean from XML attribute string."""
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes")


def _parse_int(val: str | None, default: int = 0) -> int:
    """Parse integer from XML attribute string safely."""
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


class AssetManager:
    """Central asset manager for Ultima III assets, tilesets, and definitions."""

    def __init__(self, assets_dir: str | Path | None = None) -> None:
        self.assets_dir: Path = self._resolve_assets_dir(assets_dir)
        self.tiles: dict[str, list[pygame.Surface]] = {}
        self.tile_defs: dict[int, TileDef] = {}
        self.tile_defs_by_name: dict[str, TileDef] = {}

        # XML entity, equipment, vendor, and map definitions
        self.creatures: dict[str, CreatureDef] = CaseInsensitiveDict()
        self.weapons: dict[str, WeaponDef] = CaseInsensitiveDict()
        self.armors: dict[str, ArmorDef] = CaseInsensitiveDict()
        self.vendors: dict[str, VendorDef] = CaseInsensitiveDict()
        self.vendor_classes: dict[str, VendorClassDef] = {}
        self.map_defs: dict[int, MapDef] = {}

    @classmethod
    def _resolve_assets_dir(cls, custom_path: str | Path | None = None) -> Path:
        """Find the root assets directory across repo and runtime layouts."""
        candidates: list[Path] = []
        if custom_path:
            candidates.append(Path(custom_path))

        repo_root = Path(__file__).resolve().parent.parent
        cwd = Path.cwd()

        candidates.extend([
            cwd / "src/main/resources/assets",
            cwd / "assets",
            repo_root / "src/main/resources/assets",
            repo_root / "assets",
        ])

        for candidate in candidates:
            if candidate.is_dir():
                return candidate.resolve()

        # Fallback to custom_path or default
        return Path(custom_path or "src/main/resources/assets").resolve()

    def resolve_path(self, *parts: str | Path) -> Path:
        """Resolve a path relative to assets_dir case-insensitively and normalized."""
        curr = self.assets_dir

        for part in parts:
            part_str = str(part).replace("\\", "/")
            segments = [s for s in part_str.split("/") if s and s != "."]

            for seg in segments:
                if seg == "..":
                    curr = curr.parent
                    continue

                direct = curr / seg
                if direct.exists():
                    curr = direct
                    continue

                # Case-insensitive search inside current directory
                matched = None
                seg_lower = seg.lower()
                if curr.is_dir():
                    try:
                        for entry in curr.iterdir():
                            if entry.name.lower() == seg_lower:
                                matched = entry
                                break
                    except (OSError, PermissionError):
                        pass

                if matched is not None:
                    curr = matched
                else:
                    curr = curr / seg

        return curr

    def load_tiles(self) -> None:
        """Parse latest-atlas.txt, slice ultima-ega.png, and parse tileset-base.xml."""
        atlas_path = self.resolve_path("graphics", "latest-atlas.txt")
        if not atlas_path.exists():
            raise FileNotFoundError(f"Texture atlas not found: {atlas_path}")

        xml_path = self.resolve_path("xml", "tileset-base.xml")
        if not xml_path.exists():
            raise FileNotFoundError(f"Tileset XML not found: {xml_path}")

        # 1. Parse LibGDX texture atlas
        self._load_atlas(atlas_path)

        # 2. Parse tileset XML
        self._load_tileset_xml(xml_path)

    def _load_atlas(self, atlas_path: Path) -> None:
        """Parse LibGDX atlas and slice subsurfaces from the atlas page image."""
        with open(atlas_path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\r\n") for line in f]

        self.tiles.clear()
        # Temporary frame accumulator: name -> list of (frame_index, surface)
        temp_frames: dict[str, list[tuple[int, pygame.Surface]]] = {}

        current_surface: pygame.Surface | None = None
        i = 0
        total_lines = len(lines)

        while i < total_lines:
            line = lines[i]
            if not line:
                i += 1
                continue

            # Check if this line is an image file page header
            if not line.startswith(" ") and (
                i + 1 < total_lines and lines[i + 1].strip().startswith("format:")
            ):
                image_name = line.strip()
                image_path = self.resolve_path("graphics", image_name)
                current_surface = load_image_surface(image_path)
                i += 1
                # Skip page property lines (format, filter, repeat)
                while i < total_lines and lines[i].startswith(" "):
                    i += 1
                continue

            # Otherwise, line is a region entry name
            if not line.startswith(" "):
                region_name = line.strip()
                i += 1
                props: dict[str, str] = {}
                while i < total_lines and lines[i].startswith(" "):
                    prop_line = lines[i].strip()
                    if ":" in prop_line:
                        k, v = prop_line.split(":", 1)
                        props[k.strip()] = v.strip()
                    i += 1

                if current_surface is None:
                    continue

                # Parse xy: x, y
                xy_str = props.get("xy", "0, 0")
                xy_parts = [int(p.strip()) for p in xy_str.split(",")]
                x, y = xy_parts[0], xy_parts[1]

                # Parse size: w, h
                size_str = props.get("size", "16, 16")
                size_parts = [int(p.strip()) for p in size_str.split(",")]
                w, h = size_parts[0], size_parts[1]

                # Parse frame index
                idx_str = props.get("index", "-1")
                try:
                    frame_idx = int(idx_str)
                except ValueError:
                    frame_idx = -1

                rect = pygame.Rect(x, y, w, h)
                sub = current_surface.subsurface(rect).copy()
                if region_name.lower() in ENTITY_TILES:
                    sub.set_colorkey((0, 0, 0))

                if region_name not in temp_frames:
                    temp_frames[region_name] = []
                temp_frames[region_name].append((frame_idx, sub))
                continue

            i += 1

        # Populate self.tiles ensuring ordered frames
        for name, frame_list in temp_frames.items():
            # If all frames have index >= 0 and are distinct, sort by index
            indices = [idx for idx, _ in frame_list]
            if all(idx >= 0 for idx in indices) and len(set(indices)) == len(indices):
                frame_list.sort(key=lambda t: t[0])
            self.tiles[name] = [surf for _, surf in frame_list]

    def _load_tileset_xml(self, xml_path: Path) -> None:
        """Parse tileset-base.xml and build TileDef mapping."""
        tree = ET.parse(xml_path)
        root = tree.getroot()

        self.tile_defs.clear()
        self.tile_defs_by_name.clear()

        for tile_elem in root.findall("tile"):
            idx_str = tile_elem.get("index")
            if idx_str is None:
                continue
            index = int(idx_str)
            name = tile_elem.get("name", "")
            rule = tile_elem.get("rule", "none")
            opaque = tile_elem.get("opaque", "false").lower() == "true"

            # Derive attributes from rule
            attribs = RULE_ATTRIBS.get(rule.lower(), TileAttrib.NONE)

            # Derive combat map association
            combat_map_id = TILE_COMBAT_MAP_IDS.get(name.lower(), 37)
            combat_map_fname = COMBAT_MAPS.get(combat_map_id, "CNFLCT_G.ULT")

            tile_def = TileDef(
                index=index,
                name=name,
                rule=rule,
                opaque=opaque,
                attribs=attribs,
                combat_map_id=combat_map_id,
                combat_map_fname=combat_map_fname,
            )

            self.tile_defs[index] = tile_def
            self.tile_defs_by_name[name] = tile_def

    def get_tile_surface(self, name: str, frame: int = 0) -> pygame.Surface:
        """Get the pygame Surface for a tile name and animation frame."""
        if not self.tiles:
            self.load_tiles()

        if name not in self.tiles:
            aliases = {
                "troll": "giant",
                "avatar": "ranger",
                "player": "ranger",
            }
            if name.lower() in aliases and aliases[name.lower()] in self.tiles:
                name = aliases[name.lower()]
            else:
                raise KeyError(f"Tile name '{name}' not found in loaded texture atlas.")

        frames = self.tiles[name]
        if not frames:
            raise KeyError(f"No frames found for tile '{name}'.")

        # Modulo wrap-around so animations can simply pass incrementing tick counts
        return frames[frame % len(frames)]

    def get_tile_by_index(self, index: int) -> TileDef:
        """Get TileDef by numeric index."""
        if not self.tile_defs:
            self.load_tiles()

        if index not in self.tile_defs:
            raise KeyError(f"Tile index {index} not found in tileset.")

        return self.tile_defs[index]

    def get_tile_by_name(self, name: str) -> TileDef | None:
        """Get TileDef by tile name."""
        if not self.tile_defs:
            self.load_tiles()

        return self.tile_defs_by_name.get(name)

    def load_all(self) -> None:
        """Load tileset atlas and all XML entity and map definitions."""
        self.load_tiles()
        self.load_xml_definitions()

    def load_xml_definitions(self) -> None:
        """Parse creatures.xml, weapons.xml, armors.xml, maps.xml, and vendor.xml."""
        self._load_creatures_xml()
        self._load_weapons_xml()
        self._load_armors_xml()
        self._load_maps_xml()
        self._load_vendor_xml()

    def _load_creatures_xml(self, xml_path: Path | None = None) -> None:
        """Parse creatures.xml and populate self.creatures."""
        path = xml_path or self.resolve_path("xml", "creatures.xml")
        if not path.exists():
            raise FileNotFoundError(f"Creatures XML not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()

        self.creatures.clear()
        for elem in root.findall("creature"):
            basehp = _parse_int(elem.get("basehp"), 48)
            hp_val = _parse_int(elem.get("hp", elem.get("basehp")), basehp)
            c = CreatureDef(
                id=_parse_int(elem.get("id")),
                name=elem.get("name", ""),
                tile=elem.get("tile", ""),
                basehp=basehp,
                hp=hp_val,
                exp=_parse_int(elem.get("exp"), 0),
                encounter_size=_parse_int(elem.get("encounterSize"), 1),
                level=_parse_int(elem.get("level"), 1),
                nes_exp=_parse_int(elem.get("nesExp"), 0),
                good=_parse_bool(elem.get("good")),
                wont_attack=_parse_bool(elem.get("wontattack")),
                is_walkable_over=_parse_bool(elem.get("isWalkableOver")),
                no_chest=_parse_bool(elem.get("nochest")),
                invincible=_parse_bool(elem.get("invincible")),
                undead=_parse_bool(elem.get("undead")),
                steals=elem.get("steals"),
                weak_against=elem.get("weakAgainst"),
                ranged=_parse_bool(elem.get("ranged")),
                ranged_hit_tile=elem.get("rangedhittile"),
                ranged_miss_tile=elem.get("rangedmisstile"),
                poisons=_parse_bool(elem.get("poisons")),
                sails=_parse_bool(elem.get("sails")),
                swims=_parse_bool(elem.get("swims")),
                camouflage=_parse_bool(elem.get("camouflage")),
                camouflage_tile=elem.get("camouflageTile"),
                can_move_onto_avatar=_parse_bool(elem.get("canMoveOntoAvatar")),
                casts=elem.get("casts"),
                divides=_parse_bool(elem.get("divides")),
                flies=_parse_bool(elem.get("flies")),
                force_of_nature=_parse_bool(elem.get("forceOfNature")),
                incorporeal=_parse_bool(elem.get("incorporeal")),
                leaves_tile=_parse_bool(elem.get("leavestile")),
                resists=elem.get("resists"),
                spawns_on_death=_parse_bool(elem.get("spawnsOnDeath")),
                teleports=_parse_bool(elem.get("teleports")),
            )
            if c.tile:
                self.creatures[c.tile.lower()] = c
            if c.name:
                self.creatures[c.name.lower()] = c

    def _load_weapons_xml(self, xml_path: Path | None = None) -> None:
        """Parse weapons.xml and populate self.weapons."""
        path = xml_path or self.resolve_path("xml", "weapons.xml")
        if not path.exists():
            raise FileNotFoundError(f"Weapons XML not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()

        self.weapons.clear()
        for elem in root.findall("weapon"):
            range_val = _parse_int(elem.get("range"), 1)
            abs_range = _parse_int(
                elem.get("absolute_range", elem.get("range")), range_val
            )

            constraints: list[ConstraintDef] = []
            for c_elem in elem.findall("constraint"):
                constraints.append(
                    ConstraintDef(
                        can_use=_parse_bool(c_elem.get("canuse"), True),
                        char_class=c_elem.get("class", "all"),
                    )
                )

            w = WeaponDef(
                type=elem.get("type", ""),
                name=elem.get("name", ""),
                abbr=elem.get("abbr", ""),
                range=range_val,
                absolute_range=abs_range,
                dmin=_parse_int(elem.get("dmin"), 0),
                dmax=_parse_int(elem.get("dmax"), 0),
                attack_through_objects=_parse_bool(elem.get("attackthroughobjects")),
                hit_tile=elem.get("hittile", "none"),
                leave_tile=elem.get("leavetile"),
                lose=_parse_bool(elem.get("lose")),
                lose_when_ranged=_parse_bool(elem.get("losewhenranged")),
                magic=_parse_bool(elem.get("magic")),
                miss_tile=elem.get("misstile"),
                returns=_parse_bool(elem.get("returns")),
                constraints=constraints,
            )
            if w.type:
                self.weapons[w.type.lower()] = w
            if w.name:
                self.weapons[w.name.lower()] = w

    def _load_armors_xml(self, xml_path: Path | None = None) -> None:
        """Parse armors.xml and populate self.armors."""
        path = xml_path or self.resolve_path("xml", "armors.xml")
        if not path.exists():
            raise FileNotFoundError(f"Armors XML not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()

        self.armors.clear()
        for elem in root.findall("armor"):
            constraints: list[ConstraintDef] = []
            for c_elem in elem.findall("constraint"):
                constraints.append(
                    ConstraintDef(
                        can_use=_parse_bool(c_elem.get("canuse"), True),
                        char_class=c_elem.get("class", "all"),
                    )
                )

            a = ArmorDef(
                type=elem.get("type", ""),
                name=elem.get("name", ""),
                defense=_parse_int(elem.get("defense"), 128),
                constraints=constraints,
            )
            if a.type:
                self.armors[a.type.lower()] = a
            if a.name:
                self.armors[a.name.lower()] = a

    def _load_maps_xml(self, xml_path: Path | None = None) -> None:
        """Parse maps.xml and populate self.map_defs."""
        path = xml_path or self.resolve_path("xml", "maps.xml")
        if not path.exists():
            raise FileNotFoundError(f"Maps XML not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()

        self.map_defs.clear()
        for elem in root.findall("map"):
            map_id = _parse_int(elem.get("id"))

            portals: list[PortalDef] = []
            for p_elem in elem.findall("portal"):
                portals.append(
                    PortalDef(
                        x=_parse_int(p_elem.get("x")),
                        y=_parse_int(p_elem.get("y")),
                        dest_map_id=_parse_int(p_elem.get("destmapid")),
                        z=_parse_int(p_elem.get("z"), 0),
                        start_x=_parse_int(p_elem.get("startx"), 0),
                        start_y=_parse_int(p_elem.get("starty"), 0),
                        start_level=_parse_int(p_elem.get("startlevel"), 0),
                        name=p_elem.get("name"),
                        exit_direction=p_elem.get("exitDirection"),
                        condition=p_elem.get("condition"),
                        save_location=_parse_bool(p_elem.get("savelocation")),
                        message=p_elem.get("message"),
                        transport=p_elem.get("transport"),
                    )
                )

            moongates: list[MoongateDef] = []
            for m_elem in elem.findall("moongate"):
                moongates.append(
                    MoongateDef(
                        name=m_elem.get("name", ""),
                        phase=_parse_int(m_elem.get("phase")),
                        x=_parse_int(m_elem.get("x")),
                        y=_parse_int(m_elem.get("y")),
                        d1=_parse_int(m_elem.get("d1")),
                        d2=_parse_int(m_elem.get("d2")),
                        d3=_parse_int(m_elem.get("d3")),
                    )
                )

            labels: list[LabelDef] = []
            for l_elem in elem.findall("label"):
                labels.append(
                    LabelDef(
                        name=l_elem.get("name", ""),
                        x=_parse_int(l_elem.get("x")),
                        y=_parse_int(l_elem.get("y")),
                        z=_parse_int(l_elem.get("z"), 0),
                    )
                )

            m_def = MapDef(
                id=map_id,
                map_type=elem.get("type", "world"),
                fname=elem.get("fname", ""),
                width=_parse_int(elem.get("width"), 64),
                height=_parse_int(elem.get("height"), 64),
                levels=_parse_int(elem.get("levels"), 1),
                border_behavior=elem.get("borderbehavior", "exit"),
                music=elem.get("music", ""),
                no_line_of_sight=_parse_bool(elem.get("nolineofsight")),
                tileset=elem.get("tileset", "base"),
                tilemap=elem.get("tilemap", "base"),
                portals=portals,
                moongates=moongates,
                labels=labels,
            )
            self.map_defs[map_id] = m_def

    @staticmethod
    def _parse_vendor_item(elem: ET.Element, fallback_type: str = "") -> VendorItemDef:
        """Parse a VendorItemDef from an item XML element."""
        return VendorItemDef(
            choice=elem.get("choice", ""),
            item_type=elem.get("type", fallback_type),
            name=elem.get("name", ""),
            price=_parse_int(elem.get("price")),
            quantity=_parse_int(elem.get("quant")),
            weapon_type=elem.get("weaponType"),
            armor_type=elem.get("armorType"),
            heal_type=elem.get("healType"),
            guild_item_type=elem.get("guildItemType"),
            description=elem.get("description"),
            room_x=_parse_int(elem.get("x")),
            room_y=_parse_int(elem.get("y")),
            hidden=_parse_bool(elem.get("hidden")),
        )

    def _load_vendor_xml(self, xml_path: Path | None = None) -> None:
        """Parse vendor.xml and populate self.vendors and self.vendor_classes."""
        path = xml_path or self.resolve_path("xml", "vendor.xml")
        if not path.exists():
            raise FileNotFoundError(f"Vendor XML not found: {path}")

        tree = ET.parse(path)
        root = tree.getroot()

        self.vendors.clear()
        self.vendor_classes.clear()

        for class_elem in root.findall("vendorClass"):
            class_type = class_elem.get("type", "")
            music = class_elem.get("music", "SHOPPING")

            item_catalog: list[VendorItemDef] = [
                self._parse_vendor_item(i_elem, class_type)
                for i_elem in class_elem.findall("item")
            ]

            vendor_list: list[VendorDef] = []
            for v_elem in class_elem.findall("vendor"):
                v_items: list[VendorItemDef] = [
                    self._parse_vendor_item(i_elem, class_type)
                    for i_elem in v_elem.findall("item")
                ]

                if not v_items and item_catalog:
                    v_items = list(item_catalog)

                v = VendorDef(
                    id=v_elem.get("id", ""),
                    name=v_elem.get("name", ""),
                    owner=v_elem.get("owner", ""),
                    vendor_type=v_elem.get("type", class_type),
                    start_x=_parse_int(v_elem.get("startX")),
                    start_y=_parse_int(v_elem.get("startY")),
                    generic_field1=v_elem.get("genericField1"),
                    items=v_items,
                )
                vendor_list.append(v)

                if v.owner:
                    self.vendors[v.owner.lower()] = v
                if v.name:
                    self.vendors[v.name.lower()] = v
                if v.id and v.vendor_type:
                    self.vendors[f"{v.id.lower()}_{v.vendor_type.lower()}"] = v
                if v.id and v.owner:
                    self.vendors[f"{v.id.lower()}_{v.owner.lower()}"] = v
                if v.id:
                    self.vendors[f"{v.id.lower()}_{v.start_x}_{v.start_y}"] = v
                    if v.id.lower() not in self.vendors:
                        self.vendors[v.id.lower()] = v

            self.vendor_classes[class_type] = VendorClassDef(
                type=class_type,
                music=music,
                item_catalog=item_catalog,
                vendors=vendor_list,
            )

    def get_creature(self, name_or_tile: str) -> CreatureDef | None:
        """Look up CreatureDef by name or tile (case-insensitive)."""
        if not self.creatures:
            self.load_xml_definitions()
        return self.creatures.get(name_or_tile)

    def get_weapon(self, name_or_type: str) -> WeaponDef | None:
        """Look up WeaponDef by name or type (case-insensitive)."""
        if not self.weapons:
            self.load_xml_definitions()
        return self.weapons.get(name_or_type)

    def get_armor(self, name_or_type: str) -> ArmorDef | None:
        """Look up ArmorDef by name or type (case-insensitive)."""
        if not self.armors:
            self.load_xml_definitions()
        return self.armors.get(name_or_type)

    def get_map_def(self, id_or_name: int | str) -> MapDef | None:
        """Look up MapDef by map ID or filename/name."""
        if not self.map_defs:
            self.load_xml_definitions()
        if isinstance(id_or_name, int):
            return self.map_defs.get(id_or_name)
        if isinstance(id_or_name, str) and id_or_name.isdigit():
            return self.map_defs.get(int(id_or_name))
        query = str(id_or_name).strip().lower()
        if query.upper() in MAP_NAME_TO_ID:
            return self.map_defs.get(MAP_NAME_TO_ID[query.upper()])
        for m in self.map_defs.values():
            if m.fname.lower() == query or Path(m.fname).stem.lower() == query:
                return m
        return None

    def get_vendor(self, map_id: str | int, x: int, y: int) -> VendorDef | None:
        """Find vendor by map id/name and starting coordinates."""
        if not self.vendors:
            self.load_xml_definitions()
        mid = int(map_id) if isinstance(map_id, str) and map_id.isdigit() else map_id
        map_str = (
            MAP_ID_TO_NAME.get(mid, str(mid))
            if isinstance(mid, int)
            else str(mid)
        ).upper()
        key = f"{map_str.lower()}_{x}_{y}"
        if key in self.vendors:
            return self.vendors[key]
        for vc in self.vendor_classes.values():
            for v in vc.vendors:
                if v.id.upper() == map_str and v.start_x == x and v.start_y == y:
                    return v
        return None

    def get_vendors_for_map(self, map_id: str | int) -> list[VendorDef]:
        """Find all vendors located in a map."""
        if not self.vendors:
            self.load_xml_definitions()
        mid = int(map_id) if isinstance(map_id, str) and map_id.isdigit() else map_id
        map_str = (
            MAP_ID_TO_NAME.get(mid, str(mid))
            if isinstance(mid, int)
            else str(mid)
        ).upper()
        results: list[VendorDef] = []
        for vc in self.vendor_classes.values():
            for v in vc.vendors:
                if v.id.upper() == map_str:
                    results.append(v)
        return results
