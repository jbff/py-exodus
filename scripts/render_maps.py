#!/usr/bin/env python
"""Render every map in assets/maps/*.json to PNG images (not part of the test suite).

Grid, combat, and shrine maps render top-down from the tile atlas; city maps
overlay red dots on NPC positions and combat maps overlay monster (red) and
player (blue) start positions. Dungeon maps render one top-down PNG per level,
with the dungeon view's own tile textures where the atlas has them and
hash-colored patches otherwise.

Usage:
    python -I scripts/render_maps.py [--outdir DIR] [--scale N]

Defaults: .superpowers/maprenders/, scale 1 (16px tiles; 64x64 maps -> 1024px).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections import defaultdict

import pygame  # noqa: E402

from py_exodus.assets import AssetManager  # noqa: E402
from py_exodus.world.map import DungeonTile  # noqa: E402

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".superpowers", "maprenders",
)
TILE = 16


def tile_color(index: int) -> pygame.Color:
    """Fallback patch color: deterministic, EGA-flavored, from the tile index."""
    palette = [
        (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0),
        (170, 0, 170), (170, 85, 0), (170, 170, 170), (85, 85, 85),
        (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85),
        (255, 85, 255), (255, 255, 85), (255, 255, 255),
    ]
    return pygame.Color(*palette[index % len(palette)])


def dungeon_color(tile: DungeonTile) -> pygame.Color:
    """Fallback color for dungeon tiles the atlas has no 2D texture for."""
    h = sum(ord(c) * (i + 7) for i, c in enumerate(tile.display_name))
    return pygame.Color(80 + h % 120, 60 + (h * 3) % 120, 100 + (h * 7) % 155)


def brightest_frame(asset_mgr: AssetManager, name: str) -> int:
    """Static renders look best on a bright frame; animated tiles cycle dark/bright."""
    key = f"#{name}"
    if key in _frame_cache:
        return _frame_cache[key]
    best = 0
    try:
        frames = asset_mgr.tiles[name]
        if len(frames) > 1:
            best_score = -1.0
            for i in range(len(frames)):
                avg = pygame.transform.average_color(frames[i])
                score = sum(avg[:3])
                if score > best_score:
                    best_score, best = score, i
    except KeyError:
        pass
    _frame_cache[key] = best
    return best


_frame_cache: dict[str, int] = {}


def draw_tile(surf: pygame.Surface, x: int, y: int, asset_mgr: AssetManager,
              name: str, index: int, frame: int | None = None) -> None:
    rect = (x * TILE, y * TILE, TILE, TILE)
    try:
        if frame is None:
            frame = brightest_frame(asset_mgr, name)
        surf.blit(asset_mgr.get_tile_surface(name, frame), rect)
    except (KeyError, Exception):
        pygame.draw.rect(surf, tile_color(index), rect)


def render_surface_map(kind: str, asset_mgr: AssetManager, m, npcs=(),
                       combat=(), scale: int = 1) -> pygame.Surface:
    struct_w, struct_h = m.width, m.height
    surf = pygame.Surface((struct_w * TILE, struct_h * TILE))
    for yy in range(struct_h):
        for xx in range(struct_w):
            tile = m.tiles[yy * struct_w + xx]
            name = tile.name if tile else ""
            index = tile.index if tile else 0
            draw_tile(surf, xx, yy, asset_mgr, name, index)
    if kind == "city":
        for npc in npcs:
            cx, cy = npc.x * TILE + TILE // 2, npc.y * TILE + TILE // 2
            pygame.draw.circle(surf, (255, 0, 0), (cx, cy), TILE // 5)
    if kind == "combat":
        for mx, my in combat[:8]:
            pygame.draw.circle(surf, (255, 0, 0), (mx * TILE + TILE // 2, my * TILE + TILE // 2), TILE // 5)
        for px, py in combat[8:]:
            pygame.draw.circle(surf, (0, 100, 255), (px * TILE + TILE // 2, py * TILE + TILE // 2), TILE // 5)
    if scale != 1:
        surf = pygame.transform.scale(surf, (surf.get_width() * scale, surf.get_height() * scale))
    return surf


def render_dungeon_level(asset_mgr: AssetManager, level, scale: int = 1) -> pygame.Surface:
    surf = pygame.Surface((len(level[0]) * TILE, len(level) * TILE))
    for yy, row in enumerate(level):
        for xx, tile in enumerate(row):
            rect = (xx * TILE, yy * TILE, TILE, TILE)
            try:
                surf.blit(asset_mgr.get_tile_surface(
                    tile.tile_name, brightest_frame(asset_mgr, tile.tile_name)), rect)
            except (KeyError, Exception):
                pygame.draw.rect(surf, dungeon_color(tile), rect)
    if scale != 1:
        surf = pygame.transform.scale(surf, (surf.get_width() * scale, surf.get_height() * scale))
    return surf


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=DEFAULT_OUT)
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args()

    pygame.init()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    asset_mgr = AssetManager()
    asset_mgr.load_all()
    from py_exodus.world.loader import MapLoader
    loader = MapLoader(asset_mgr)

    rendered: dict[str, int] = {}
    for mdef in sorted(asset_mgr.map_defs.values(), key=lambda m: m.id):
        stem = Path(mdef.fname).stem.lower()
        m = loader.load_map(mdef.id)
        if hasattr(m, "level_texts"):  # DungeonMap: one PNG per level
            for z in range(m.levels):
                img = render_dungeon_level(asset_mgr, m.tiles[z], args.scale)
                path = out / f"{stem}_level{z + 1}.png"
                pygame.image.save(img, str(path))
                rendered[stem] = rendered.get(stem, 0) + 1
        else:
            kind = mdef.map_type.lower()
            combat = tuple(m.monster_starts) + tuple(m.player_starts) if kind == "combat" else ()
            img = render_surface_map(kind, asset_mgr, m,
                                     npcs=getattr(m, "npcs", ()),
                                     combat=combat, scale=args.scale)
            pygame.image.save(img, str(out / f"{stem}.png"))
            rendered[stem] = 1

    total = sum(rendered.values())
    print(f"rendered {total} PNG file(s) for {len(rendered)} map(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
