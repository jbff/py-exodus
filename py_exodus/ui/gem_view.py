"""Peer Gem (P) view state and renderer.

Who pays: LairWare PeerGem (UltimaMain.c:2143-2159) asks whose gem
(``member_prompts.prompt_whose_item``); "Peer at a Gem!" opens the view. The adapter
(GameScreen.java:1114-1152) shows the map picture with
``gameTimer.active = False``; any key removes the image and restores the
timer, so no turn passes while the view is up. P itself has no early return
(GameScreen.java:604-605) and falls through the keyUp tail finishTurn
(GameScreen.java:628) — the press consumes a turn either way, before the
view opens. Dungeons never use it: DungeonScreen.java:1012-1015 makes P a
plain minimap toggle instead.

The picture follows LairWare DrawMiniMap (UltimaGraphics.c:1433-1495): the
WHOLE map, drawn from shrunken real tiles into the MAP PANE only (the party
panel and the message log stay up), each cell ``pane / mapsize`` px, the
map centred in the pane over a grey drop shadow and inside a white/black
frame. LairWare keeps townspeople and wandering monsters in the map grid,
so they show at their places; the port draws them (and the whirlpool and
parked ships/horses) as their own shrunken tiles over the terrain. The
party's cell carries its own tile and a YELLOW box that blinks (user
addition to the approved mockup), 0.4 s on and 0.4 s off on the screen's
0.2 s animation frame.
"""
from __future__ import annotations

import weakref
from collections.abc import Iterable
from typing import Any

import pygame

from py_exodus.ui.text_log import EGA_BLACK, EGA_WHITE, EGA_YELLOW

# GameScreen.java:1081 (peer log).
PEER_MESSAGE = "Peer at a Gem!"

# LairWare's blended drop shadow: OpColor 24576 (96/255 grey) blended
# over the pane, once for a full block band and again for a half band.
SHADOW_COLOR = (96, 96, 96, 160)
# Cell painted where a tile has no art in the loaded tile set.
MISSING_TILE_COLOR = (40, 40, 40)

# Shrunken tile cache: source frame -> {cell: shrunk}. Weak on the
# source, so a replaced AssetManager or tile set frees its shrunk tiles.
_SHRUNK: weakref.WeakKeyDictionary[pygame.Surface, dict[int, pygame.Surface]] = (
    weakref.WeakKeyDictionary()
)

# The composed terrain of the last map peered at: (key, surface). One
# entry only; the key holds the map's tile names, so a changed tile (a door
# opened, a field burnt) recomposes it.
_TERRAIN: list[Any] = [None, None]


def frame_width(scale: int) -> int:
    """Width of each of the white and black frame lines."""
    return max(1, (2 * scale) // 3)


def shadow_width(scale: int) -> int:
    """The drop shadow's full band (LW one blkSiz; its half band is half)."""
    return 4 * scale


def peer_cell(pane: int, map_w: int, map_h: int, scale: int) -> int:
    """Cell size in px for the whole map in a ``pane``-px square map pane:
    LairWare ``minSize = (blkSiz * 22) / gCurMapSize`` (at least 1), less
    room for the frame (top/left) and the drop shadow (bottom/right). A
    64x64 map gets 8 px at 960x600 (pane 528) and 2 px at 320x200 (176)."""
    size = max(map_w, map_h, 1)
    avail = pane - 2 * frame_width(scale) - shadow_width(scale)
    return max(1, avail // size)


def marker_visible(anim_frame: int) -> bool:
    """The party box blinks: on for two 0.2 s animation frames, off for
    two (0.4 s each way)."""
    return (anim_frame // 2) % 2 == 0


def _shrunk(src: pygame.Surface, cell: int) -> pygame.Surface:
    sizes = _SHRUNK.setdefault(src, {})
    hit = sizes.get(cell)
    if hit is not None:
        return hit
    # Opaque, like LairWare's mini tiles. Smooth shrinking keeps the EGA
    # dither from aliasing; the tile sheets are 8-bit, which smoothscale
    # refuses, so go via 32-bit.
    out = pygame.Surface(src.get_size(), depth=32)
    out.blit(src, (0, 0))
    if out.get_size() != (cell, cell):
        out = pygame.transform.smoothscale(out, (cell, cell))
    sizes[cell] = out
    return out


def _tile(asset_mgr: Any, name: str | None, cell: int) -> pygame.Surface | None:
    if asset_mgr is None or not name:
        return None
    try:
        src = asset_mgr.get_tile_surface(str(name), 0)
    except (KeyError, AttributeError):
        return None
    return _shrunk(src, cell)


def _sprite_name(thing: Any, asset_mgr: Any) -> str | None:
    """Tile name of a map object, creature or NPC (as WorldRenderer draws
    them in the normal view)."""
    if isinstance(thing, dict):
        name = thing.get("tile_name") or thing.get("name")
        tile = thing.get("tile")
        if tile is not None and not thing.get("tile_name"):
            name = tile.name if hasattr(tile, "name") else str(tile)
        variant = str(thing.get("name", "")).lower()
        tiles = getattr(asset_mgr, "tiles", None) or {}
        if thing.get("variant") and variant in tiles:
            name = variant
        return str(name) if name else None
    name = getattr(thing, "tile_name", None)
    if not name and getattr(thing, "tile_def", None) is not None:
        name = thing.tile_def.name
    return str(name) if name else None


def peer_sprites(game_map: Any, party: Any, creatures: Iterable[Any], asset_mgr: Any) -> list[tuple[int, int, str]]:
    """Everything that stands on the map besides the party, as
    ``(x, y, tile_name)``: parked ships/horses and dropped chests on their
    own surface map, creatures (wandering monsters, the whirlpool, horses)
    and townspeople at their current positions."""
    from py_exodus.entities.party import objects_on

    out: list[tuple[int, int, str]] = []
    things: list[Any] = list(objects_on(party, game_map)) if getattr(game_map, "id", 0) in (0, 13) else []
    things.extend(creatures)
    things.extend(getattr(game_map, "npcs", ()))
    for thing in things:
        name = _sprite_name(thing, asset_mgr)
        if not name:
            continue
        if isinstance(thing, dict):
            x, y = thing.get("x", 0), thing.get("y", 0)
        else:
            x, y = getattr(thing, "x", 0), getattr(thing, "y", 0)
        out.append((int(x), int(y), name))
    return out


def peer_map_rect(pane: pygame.Rect, map_w: int, map_h: int, scale: int) -> pygame.Rect:
    """Where the whole map lands: centred in the pane (DrawMiniMap
    mapRect) with its frame and drop shadow inside the pane."""
    cell = peer_cell(min(pane.w, pane.h), map_w, map_h, scale)
    w, h = map_w * cell, map_h * cell
    lead = 2 * frame_width(scale)
    trail = shadow_width(scale)
    x = pane.x + lead + (pane.w - lead - trail - w) // 2
    y = pane.y + lead + (pane.h - lead - trail - h) // 2
    return pygame.Rect(x, y, w, h)


def _terrain(game_map: Any, asset_mgr: Any, cell: int) -> pygame.Surface:
    """The map's terrain from shrunken tiles, composed once and reused
    until the map, its tiles, the tile set or the cell size change."""
    map_w, map_h = game_map.width, game_map.height
    names = tuple(
        getattr(game_map.get_tile(mx, my), "name", None)
        for my in range(map_h)
        for mx in range(map_w)
    )
    key = (id(game_map), id(asset_mgr), id(getattr(asset_mgr, "tiles", None)), cell, map_w, names)
    if _TERRAIN[0] == key:
        return _TERRAIN[1]
    out = pygame.Surface((map_w * cell, map_h * cell))
    for i, name in enumerate(names):
        mx, my = i % map_w, i // map_w
        img = _tile(asset_mgr, name, cell)
        if img is None:
            out.fill(MISSING_TILE_COLOR, (mx * cell, my * cell, cell, cell))
        else:
            out.blit(img, (mx * cell, my * cell))
    _TERRAIN[0], _TERRAIN[1] = key, out
    return out


def render_gem_view(
    surface: pygame.Surface,
    pane: pygame.Rect,
    game_map: Any,
    asset_mgr: Any,
    party_xy: tuple[int, int],
    *,
    sprites: Iterable[tuple[int, int, str]] = (),
    party_tile: str | None = None,
    marker_on: bool = True,
) -> None:
    """Draw the Peer picture into ``pane`` (the map pane) of ``surface``:
    LairWare DrawMiniMap. Nothing outside the pane is touched."""
    scale = 3 if surface.get_width() >= 640 else 1
    map_w, map_h = game_map.width, game_map.height
    cell = peer_cell(min(pane.w, pane.h), map_w, map_h, scale)
    rect = peer_map_rect(pane, map_w, map_h, scale)

    old_clip = surface.get_clip()
    surface.set_clip(pane.clip(old_clip) if old_clip else pane)
    try:
        surface.fill(EGA_BLACK, pane)

        # Drop shadow (UltimaGraphics.c:1462-1469): a block-wide band right
        # of and below the map, offset one block down/right, then a
        # half-block band blended again over its inner half.
        for band in (shadow_width(scale), shadow_width(scale) // 2):
            if band <= 0:
                continue
            for r in (
                pygame.Rect(rect.right, rect.top + band, band, rect.h),
                pygame.Rect(rect.left + band, rect.bottom, rect.w - band, band),
            ):
                shade = pygame.Surface(r.size, pygame.SRCALPHA)
                shade.fill(SHADOW_COLOR)
                surface.blit(shade, r)

        # Terrain (composed once), then everyone standing on it.
        surface.blit(_terrain(game_map, asset_mgr, cell), rect)

        def on_map(x: int, y: int) -> bool:
            return 0 <= x < map_w and 0 <= y < map_h

        for x, y, name in sprites:
            img = _tile(asset_mgr, name, cell)
            if img is not None and on_map(x, y):
                surface.blit(img, (rect.x + x * cell, rect.y + y * cell))

        px, py = party_xy
        if on_map(px, py):
            img = _tile(asset_mgr, party_tile, cell)
            if img is not None:
                surface.blit(img, (rect.x + px * cell, rect.y + py * cell))

        # Frame: white, then black outside it (FrameRect twice).
        fw = frame_width(scale)
        pygame.draw.rect(surface, EGA_WHITE, rect.inflate(2 * fw, 2 * fw), fw)
        pygame.draw.rect(surface, EGA_BLACK, rect.inflate(4 * fw, 4 * fw), fw)

        # Party marker: a blinking yellow box around the party's cell.
        if marker_on and on_map(px, py):
            pad = max(1, scale - 1)
            box = pygame.Rect(rect.x + px * cell, rect.y + py * cell, cell, cell).inflate(2 * pad, 2 * pad)
            if scale > 1:
                pygame.draw.rect(surface, EGA_BLACK, box.inflate(4, 4), 2)
            pygame.draw.rect(surface, EGA_YELLOW, box, pad)
    finally:
        surface.set_clip(old_clip)
