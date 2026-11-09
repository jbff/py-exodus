"""Peer Gem (P) view state and renderer.

Java truth: ``exodus/GameScreen.java:1076-1087`` — ``peerGem()`` uses the
FIRST party member holding gems, logs ``"Peer at a Gem!"`` and swaps input
to ``PeerGemInputAdapter``; with no gems it logs
``"Thou dost have no gems!"`` (GameScreen.java:1086). The adapter
(GameScreen.java:1114-1152) shows the map picture with
``gameTimer.active = False``; any key removes the image and restores the
timer, so no turn passes while the view is up. P itself has no early return
(GameScreen.java:604-605) and falls through the keyUp tail finishTurn
(GameScreen.java:628) — the press consumes a turn either way, before the
view opens. Dungeons never use it: DungeonScreen.java:1012-1015 makes P a
plain minimap toggle instead.

The picture is drawn by ``Util/Utils.peerGem`` (Utils.java:865-1042): for
the world map it blits a region of real tiles around the avatar (wrapping
the map edges), painting creatures/objects WHITE and the center (party)
tile WHITE as well; for a city it blits the WHOLE map and paints the
party's own tile YELLOW (Utils.java:938-944). Dungeon maps draw nothing
(the HUD minimap already covers them).

Presentation adaptation from the Java/libGDX renderer to this port's
colored-cell HUD precedent (dungeon_screen._render_minimap):
- Tiles are drawn as fixed 8px colored cells (Java scales 16px sprites into
  a 512x512 canvas on a 1024x768 screen); 8px fills the 320x200 base
  surface with a 40x25-grid window, as the task presentation guidance
  prescribes ("enough tiles to fill the screen at a reasonable cell size").
- Terrain colors come from a fixed name->EGA table with a deterministic
  CRC32 fallback for rare names, so repeated renders are byte-identical.
- The region is centered on the party and WRAPPED for wrap-border maps
  (matching Java's world peerGem modulo math) but CLIPPED at bounds
  elsewhere (Java's city view blits the whole map centered on the screen —
  the task presentation guidance instead asks for a region centered on the
  party, so towns reuse the world path).
- People/creatures/objects are WHITE cells (Utils.java:899-931) and the
  party cell is YELLOW (the city coloring — unifies Java's white center
  tile on the world map with the yellow city party marker).
"""
from __future__ import annotations

import zlib

import pygame

from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BLUE,
    EGA_BRIGHT_BLUE,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_MAGENTA,
    EGA_BRIGHT_RED,
    EGA_BROWN,
    EGA_CYAN,
    EGA_DARK_GRAY,
    EGA_GREEN,
    EGA_LIGHT_GRAY,
    EGA_MAGENTA,
    EGA_RED,
    EGA_WHITE,
    EGA_YELLOW,
)

# GameScreen.java:1081 (peer log) and GameScreen.java:1086 (no-gems log).
PEER_MESSAGE = "Peer at a Gem!"
NO_GEMS_MESSAGE = "Thou dost have no gems!"

CELL = 8

_TILE_COLORS = {
    "water": EGA_BLUE,
    "grass": EGA_BRIGHT_GREEN,
    "brush": EGA_GREEN,
    "forest": EGA_GREEN,
    "mountains": EGA_DARK_GRAY,
    "hills": EGA_BROWN,
    "dungeon": EGA_LIGHT_GRAY,
    "towne": EGA_BRIGHT_RED,
    "castle": EGA_BRIGHT_CYAN,
    "floor": EGA_LIGHT_GRAY,
    "chest": EGA_BROWN,
    "horse": EGA_BROWN,
    "frigate": EGA_BROWN,
    "whirlpool": EGA_BRIGHT_BLUE,
    "serpent": EGA_BRIGHT_MAGENTA,
    "squid": EGA_BRIGHT_MAGENTA,
    "pirate": EGA_MAGENTA,
    "merchant": EGA_BRIGHT_MAGENTA,
    "jester": EGA_BRIGHT_MAGENTA,
    "guard": EGA_BRIGHT_MAGENTA,
    "lord_british": EGA_BRIGHT_MAGENTA,
    "fighter": EGA_BRIGHT_MAGENTA,
    "cleric": EGA_BRIGHT_MAGENTA,
    "wizard": EGA_BRIGHT_MAGENTA,
    "thief": EGA_BRIGHT_MAGENTA,
    "orc": EGA_GREEN,
    "skeleton": EGA_WHITE,
    "giant": EGA_WHITE,
    "daemon": EGA_WHITE,
    "pincher": EGA_WHITE,
    "dragon": EGA_WHITE,
    "balron": EGA_WHITE,
    "exodus": EGA_WHITE,
    "energy_field": EGA_BRIGHT_RED,
    "lava": EGA_BRIGHT_RED,
    "moongate": EGA_BRIGHT_MAGENTA,
    "wall": EGA_WHITE,
    "blank": EGA_BLACK,
    "space": EGA_BLACK,
    "A": EGA_CYAN,
    "B": EGA_YELLOW,
    "C": EGA_CYAN,
    "D": EGA_CYAN,
    "E": EGA_CYAN,
    "F": EGA_CYAN,
    "G": EGA_CYAN,
    "H": EGA_CYAN,
    "I": EGA_CYAN,
    "V": EGA_CYAN,
    "Y": EGA_YELLOW,
    "L": EGA_CYAN,
    "M": EGA_CYAN,
    "N": EGA_CYAN,
    "O": EGA_CYAN,
    "P": EGA_CYAN,
    "W": EGA_CYAN,
    "R": EGA_CYAN,
    "S": EGA_CYAN,
    "T": EGA_CYAN,
}

_FALLBACK_PALETTE = (
    EGA_RED,
    EGA_GREEN,
    EGA_BLUE,
    EGA_MAGENTA,
    EGA_LIGHT_GRAY,
    EGA_BROWN,
)


def _tile_color(tile_name: str):
    color = _TILE_COLORS.get(tile_name)
    if color is None:
        # Deterministic hash (str.__hash__ is salted per process; CRC32 is
        # not) so repeated renders of the same map are byte-identical.
        color = _FALLBACK_PALETTE[zlib.crc32(tile_name.encode()) % len(_FALLBACK_PALETTE)]
    return color


def find_first_gem_member(party):
    """Java ``peerGem`` scan (GameScreen.java:1077-1080): the FIRST member
    holding gems, in roster order; None when nobody holds any."""
    for member in party.members:
        if getattr(member, "gems", 0) > 0:
            return member
    return None


def consume_peer_gem(party):
    """Take one gem from the first member holding any (Java truth above).
    Returns the payer, or None with no gems taken."""
    member = find_first_gem_member(party)
    if member is not None:
        member.gems -= 1
    return member


def render_gem_view(
    surface: pygame.Surface,
    game_map,
    center_x: int,
    center_y: int,
    marks=(),
) -> None:
    """Draw the gem-vision picture: the map region around (center_x,
    center_y) as fixed colored cells, people/marks WHITE and the party cell
    YELLOW (see module docstring for the Java->port adaptation)."""

    surface.fill(EGA_BLACK)

    width = surface.get_width()
    height = surface.get_height()
    cols = max(1, width // CELL)
    rows = max(1, height // CELL)
    start_x = center_x - cols // 2
    start_y = center_y - rows // 2

    is_wrap = game_map.border_behavior == "wrap"
    map_w = game_map.width
    map_h = game_map.height

    for row in range(rows):
        for col in range(cols):
            mx = start_x + col
            my = start_y + row
            if is_wrap:
                mx %= map_w
                my %= map_h
            elif not (0 <= mx < map_w and 0 <= my < map_h):
                continue
            tile = game_map.get_tile(mx, my)
            if tile is None:
                continue
            rect = pygame.Rect(col * CELL, row * CELL, CELL - 1, CELL - 1)
            surface.fill(_tile_color(tile.name), rect)

    # People/creatures/objects on the viewed region as WHITE cells.
    for (ex, ey) in marks:
        if is_wrap:
            # Shortest signed delta (WorldRenderer.map_to_viewport wrap
            # math) so marks keep their true position across the seam.
            col = cols // 2 + ((ex - center_x + map_w // 2) % map_w) - (map_w // 2)
            row = rows // 2 + ((ey - center_y + map_h // 2) % map_h) - (map_h // 2)
        else:
            col = ex - start_x
            row = ey - start_y
        if 0 <= col < cols and 0 <= row < rows:
            surface.fill(
                EGA_WHITE,
                pygame.Rect(col * CELL, row * CELL, CELL - 1, CELL - 1),
            )

    # Party marker: a YELLOW cell at the region center.
    p_col = cols // 2
    p_row = rows // 2
    surface.fill(
        EGA_YELLOW,
        pygame.Rect(p_col * CELL, p_row * CELL, CELL - 1, CELL - 1),
    )
