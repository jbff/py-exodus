"""The attack orb combat draws: a coloured disc with a white core.

Combat shows each attack as this orb travelling to its target, over the
hit tile; the View's attack tiles use it too (user 2026-11-23: the EGA
sheet's own 'fire' tile is a bare white dot).
"""
from __future__ import annotations

import pygame

#: Orb colour per hit tile: ordinary weapons 'fire', magic weapons 'magic'.
HIT_ORB_COLOURS: dict[str, tuple[int, int, int]] = {
    "fire": (255, 85, 85),
    "magic": (85, 255, 255),
}


def draw_hit_orb(
    surface: pygame.Surface,
    centre: tuple[int, int],
    colour: tuple[int, int, int],
    scale: float = 1.0,
) -> None:
    """Radius 4 in colour with a radius-2 white core, in 16-px tile pixels
    (``scale`` screen pixels each)."""
    pygame.draw.circle(surface, colour, centre, max(1, round(4 * scale)))
    pygame.draw.circle(surface, (255, 255, 255), centre, max(1, round(2 * scale)))
