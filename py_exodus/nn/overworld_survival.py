"""Overworld tactical survival override for vulnerable parties (Option 2)."""
from __future__ import annotations

import pygame

from py_exodus.constants import Direction, Transport
from py_exodus.screens.overworld import can_move_to

_DIR_TO_KEY: dict[Direction, int] = {
    Direction.NORTH: pygame.K_UP,
    Direction.SOUTH: pygame.K_DOWN,
    Direction.WEST: pygame.K_LEFT,
    Direction.EAST: pygame.K_RIGHT,
}


def choose_survival_override_key(gmap, party, screen) -> int | None:
    """Return an evasive movement key when a vulnerable FOOT party faces a <=2-tile creature."""
    if gmap is None or getattr(gmap, "id", 0) != 0 or party.transport != Transport.FOOT:
        return None
    living = [m for m in party.members if not m.is_dead()]
    if not living:
        return None
    # Do not override if starving with 0 food and <30g (needs to fight for gold)
    if party.gold < 30 and any(m.food <= 0 for m in living):
        return None

    min_hp_ratio = min(m.hp / max(1, m.max_hp) for m in living)
    vulnerable = len(living) <= 2 or min_hp_ratio < 0.35
    if not vulnerable:
        return None

    px, py = party.x, party.y
    threats = [
        (c["x"], c["y"])
        for c in getattr(screen, "creatures", ())
        if "x" in c
        and "y" in c
        and str(c.get("tile_name") or c.get("tile") or "").lower() != "whirlpool"
        and (
            min((c["x"] - px) % gmap.width, (px - c["x"]) % gmap.width)
            + min((c["y"] - py) % gmap.height, (py - c["y"]) % gmap.height)
            <= 2
        )
    ]
    if not threats:
        return None

    cur_dist = min(
        min((cx - px) % gmap.width, (px - cx) % gmap.width)
        + min((cy - py) % gmap.height, (py - cy) % gmap.height)
        for cx, cy in threats
    )
    best_key = None
    best_dist = cur_dist
    for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
        nx, ny = (px + d.dx) % gmap.width, (py + d.dy) % gmap.height
        if not can_move_to(gmap, nx, ny, transport=Transport.FOOT, party=party):
            continue
        nd = min(
            min((cx - nx) % gmap.width, (nx - cx) % gmap.width)
            + min((cy - ny) % gmap.height, (ny - cy) % gmap.height)
            for cx, cy in threats
        )
        if nd > best_dist:
            best_dist = nd
            best_key = _DIR_TO_KEY[d]
    return best_key
