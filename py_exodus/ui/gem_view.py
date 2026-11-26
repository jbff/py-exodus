"""Peer Gem (P) view state and renderer.

Who pays: LairWare PeerGem (UltimaMain.c:2143-2159) asks whose gem
(``member_prompts.prompt_whose_item``); "Peer at a Gem!" opens the view. The adapter
(GameScreen.java:1114-1152) shows the map picture with
``gameTimer.active = False``; any key removes the image and restores the
timer, so no turn passes while the view is up. P itself has no early return
(GameScreen.java:604-605) and falls through the keyUp tail finishTurn
(GameScreen.java:628) — the press consumes a turn either way, before the
view opens.

Dungeons peer too (user ruling 2026-11-26, LairWare dPeer UltimaDngn.c:440-454
and Vieda UltimaSpellCombat.c:322-327): ``render_dungeon_gem_view`` draws
LairWare DrawMiniDng(0), the whole 16x16 level, in the same frame.

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


def _draw_shadow(surface: pygame.Surface, rect: pygame.Rect, scale: int) -> None:
    """Drop shadow (UltimaGraphics.c:1462-1469): a block-wide band right of
    and below the map, offset one block down/right, then a half-block band
    blended again over its inner half."""
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


def _draw_frame(surface: pygame.Surface, rect: pygame.Rect, scale: int) -> None:
    """Frame: white, then black outside it (FrameRect twice)."""
    fw = frame_width(scale)
    pygame.draw.rect(surface, EGA_WHITE, rect.inflate(2 * fw, 2 * fw), fw)
    pygame.draw.rect(surface, EGA_BLACK, rect.inflate(4 * fw, 4 * fw), fw)


def _draw_marker(
    surface: pygame.Surface, rect: pygame.Rect, cell: int, px: int, py: int, scale: int
) -> None:
    """Party marker: a yellow box around the party's cell."""
    pad = max(1, scale - 1)
    box = pygame.Rect(rect.x + px * cell, rect.y + py * cell, cell, cell).inflate(2 * pad, 2 * pad)
    if scale > 1:
        pygame.draw.rect(surface, EGA_BLACK, box.inflate(4, 4), 2)
    pygame.draw.rect(surface, EGA_YELLOW, box, pad)


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

        _draw_shadow(surface, rect, scale)

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

        _draw_frame(surface, rect, scale)

        # Party marker: a blinking yellow box around the party's cell.
        if marker_on and on_map(px, py):
            _draw_marker(surface, rect, cell, px, py, scale)
    finally:
        surface.set_clip(old_clip)


# --- Dungeon level map (LairWare DrawMiniDng) --------------------------------

#: DrawMiniDng's pieces (UltimaGraphics.c:1540-1555), by the number LairWare
#: hands DngPiece.  Piece 8 is the party marker, drawn here as the yellow box.
PIECE_DOOR = 0
PIECE_SECRET_DOOR = 1
PIECE_WALL = 2
PIECE_LADDER_BOTH = 3
PIECE_LADDER_UP = 4
PIECE_LADDER_DOWN = 5
PIECE_EMPTY = 6
PIECE_OTHER = 7

# Stone's colours (world.dungeon.DungeonCamera), so the map and the view
# read as one place.
_STONE = (182, 160, 124)
_STONE_MORTAR = (100, 88, 68)
_FLOOR = (44, 36, 28)
_FLOOR_SEAM = (30, 24, 18)
_DOOR_WOOD = (120, 62, 28)
_DOOR_TRIM = (60, 30, 12)
_BRASS = (230, 190, 60)
_RAIL = (200, 150, 80)

_DNG_PIECES: dict[tuple[int, int], pygame.Surface] = {}


def dungeon_piece(tile: Any) -> int:
    """Which piece DrawMiniDng draws for a dungeon tile.

    LairWare (UltimaGraphics.c:1540-1555) starts from piece 7 and names
    seven byte values: 0xC0 door 0, 0xA0 secret door 1, 0x80 wall 2, 0x30
    ladder up and down 3, 0x20 ladder down 5, 0x10 ladder up 4, 0x00 empty 6.
    A secret door has its own piece, so the map tells it from a wall.  Every
    other value (fountains, Marks, chests, traps, the Time Lord...) is the
    one "something here" piece 7.  The port's floor is LairWare's 0x00, and
    its locked door (no LairWare byte) is shown as a door.
    """
    from py_exodus.world.map import DungeonTile as T

    return {
        T.DOOR: PIECE_DOOR,
        T.LOCKED_DOOR: PIECE_DOOR,
        T.SECRET_DOOR: PIECE_SECRET_DOOR,
        T.WALL: PIECE_WALL,
        T.LADDER_UP_DOWN: PIECE_LADDER_BOTH,
        T.LADDER_UP: PIECE_LADDER_UP,
        T.LADDER_DOWN: PIECE_LADDER_DOWN,
        T.NOTHING: PIECE_EMPTY,
        T.FLOOR: PIECE_EMPTY,
    }.get(tile, PIECE_OTHER)


def _stone_block(s: pygame.Surface, c: int) -> None:
    """A block of wall seen from above: stone with running-bond mortar."""
    s.fill(_STONE)
    if c < 6:
        return
    rows = 4 if c >= 16 else 2
    for r in range(rows):
        y = r * c // rows
        pygame.draw.line(s, _STONE_MORTAR, (0, y), (c - 1, y))
        x = (c // 4 if r % 2 else 3 * c // 4)
        pygame.draw.line(s, _STONE_MORTAR, (x, y), (x, (r + 1) * c // rows))
    pygame.draw.line(s, _STONE_MORTAR, (0, 0), (0, c - 1))


def _door_rect(c: int) -> pygame.Rect:
    return pygame.Rect(c * 3 // 10, c // 5, max(2, c * 2 // 5), c - c // 5)


def _ladder(s: pygame.Surface, c: int) -> None:
    x0, x1 = c * 3 // 8, c - 1 - c * 3 // 8
    top, bot = c // 5, c - 1 - c // 5
    pygame.draw.line(s, _RAIL, (x0, top), (x0, bot))
    pygame.draw.line(s, _RAIL, (x1, top), (x1, bot))
    for i in range(1, 4):
        y = top + (bot - top) * i // 4
        pygame.draw.line(s, _RAIL, (x0, y), (x1, y))


def _arrow(s: pygame.Surface, c: int, up: bool, x: int) -> None:
    """A small arrowhead beside the ladder: which way it goes."""
    h = max(2, c // 5)
    mid = c // 2
    if up:
        pts = [(x, mid - h), (x - h, mid), (x + h, mid)]
    else:
        pts = [(x, mid + h), (x - h, mid), (x + h, mid)]
    pygame.draw.polygon(s, EGA_WHITE, pts)


def _dungeon_piece_surface(piece: int, cell: int) -> pygame.Surface:
    """One map piece, ``cell`` px square, drawn once per size."""
    hit = _DNG_PIECES.get((piece, cell))
    if hit is not None:
        return hit
    c = cell
    s = pygame.Surface((c, c))
    if piece in (PIECE_WALL, PIECE_DOOR, PIECE_SECRET_DOOR):
        _stone_block(s, c)
        door = _door_rect(c)
        if piece == PIECE_DOOR:
            s.fill(_DOOR_WOOD, door)
            pygame.draw.rect(s, _DOOR_TRIM, door, 1)
            if c >= 16:
                pygame.draw.circle(s, _BRASS, (door.right - c // 8, door.centery + c // 10), max(1, c // 16))
        elif piece == PIECE_SECRET_DOOR:
            # The outline of a door in the stone, and nothing more.
            pygame.draw.rect(s, _DOOR_TRIM, door, max(1, c // 16))
    else:
        s.fill(_FLOOR)
        if c >= 6:
            pygame.draw.rect(s, _FLOOR_SEAM, (0, 0, c, c), 1)
        if piece in (PIECE_LADDER_UP, PIECE_LADDER_DOWN, PIECE_LADDER_BOTH):
            _ladder(s, c)
            if piece in (PIECE_LADDER_UP, PIECE_LADDER_BOTH):
                _arrow(s, c, True, c // 6 + 1)
            if piece in (PIECE_LADDER_DOWN, PIECE_LADDER_BOTH):
                _arrow(s, c, False, c - 2 - c // 6)
        elif piece == PIECE_OTHER:
            r = max(1, c // 5)
            m = c // 2
            pygame.draw.polygon(s, _BRASS, [(m, m - r), (m + r, m), (m, m + r), (m - r, m)])
    _DNG_PIECES[(piece, cell)] = s
    return s


def render_dungeon_gem_view(
    surface: pygame.Surface,
    pane: pygame.Rect,
    dmap: Any,
    level: int,
    party_xy: tuple[int, int],
    *,
    marker_on: bool = True,
) -> None:
    """Draw one whole dungeon level into ``pane``: LairWare DrawMiniDng(0).

    Same frame, drop shadow and blinking yellow party box as the surface
    Peer picture.  Nothing outside the pane is touched.
    """
    scale = 3 if surface.get_width() >= 640 else 1
    map_w, map_h = dmap.width, dmap.height
    cell = peer_cell(min(pane.w, pane.h), map_w, map_h, scale)
    rect = peer_map_rect(pane, map_w, map_h, scale)

    old_clip = surface.get_clip()
    surface.set_clip(pane.clip(old_clip) if old_clip else pane)
    try:
        surface.fill(EGA_BLACK, pane)
        _draw_shadow(surface, rect, scale)
        for my in range(map_h):
            for mx in range(map_w):
                piece = dungeon_piece(dmap.get_tile(mx, my, level))
                surface.blit(
                    _dungeon_piece_surface(piece, cell),
                    (rect.x + mx * cell, rect.y + my * cell),
                )
        _draw_frame(surface, rect, scale)
        px, py = party_xy
        if marker_on and 0 <= px < map_w and 0 <= py < map_h:
            _draw_marker(surface, rect, cell, px, py, scale)
    finally:
        surface.set_clip(old_clip)
