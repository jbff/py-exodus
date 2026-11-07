"""Asset management, texture atlas parsing, EGA tile slicing, and resource resolution."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

import pygame

from py_exodus.constants import TileAttrib

# Combat Map ID and Filename mappings (matching classic Ultima III conflict arenas)
COMBAT_MAPS: dict[int, str] = {
    33: "CNFLCT_A.ULT",  # CONFLICT_SHIP_TOP
    34: "CNFLCT_B.ULT",  # CONFLICT_GRASS_BRUSH
    35: "CNFLCT_C.ULT",  # CONFLICT_BRICK_FLOOR
    36: "CNFLCT_F.ULT",  # CONFLICT_GRASS_FOREST
    37: "CNFLCT_G.ULT",  # CONFLICT_GRASS
    38: "CNFLCT_M.ULT",  # CONFLICT_SHORE
    39: "CNFLCT_Q.ULT",  # CONFLICT_SHIP
    40: "CNFLCT_S.ULT",  # CONFLICT_SHIP_BOTTOM
    41: "CNFLCT_W.ULT",  # CONFLICT_BOTH_SHIPS
}

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


class AssetManager:
    """Central asset manager for Ultima III assets, tilesets, and definitions."""

    def __init__(self, assets_dir: Optional[str | Path] = None) -> None:
        self.assets_dir: Path = self._resolve_assets_dir(assets_dir)
        self.tiles: Dict[str, List[pygame.Surface]] = {}
        self.tile_defs: Dict[int, TileDef] = {}
        self.tile_defs_by_name: Dict[str, TileDef] = {}

    @classmethod
    def _resolve_assets_dir(cls, custom_path: Optional[str | Path] = None) -> Path:
        """Find the root assets directory across repo and runtime layouts."""
        candidates: List[Path] = []
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
        temp_frames: Dict[str, List[tuple[int, pygame.Surface]]] = {}

        current_surface: Optional[pygame.Surface] = None
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
                props: Dict[str, str] = {}
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

    def get_tile_by_name(self, name: str) -> Optional[TileDef]:
        """Get TileDef by tile name."""
        if not self.tile_defs:
            self.load_tiles()

        return self.tile_defs_by_name.get(name)
