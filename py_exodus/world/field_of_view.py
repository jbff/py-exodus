"""Field of View (FOV) and line-of-sight calculations using recursive shadowcasting."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_exodus.world.map import GameMap

DIAGONALS: list[tuple[int, int]] = [(-1, -1), (1, -1), (-1, 1), (1, 1)]


def compute_fov(
    game_map: GameMap,
    origin_x: int,
    origin_y: int,
    radius: int = 6,
) -> set[tuple[int, int]]:
    """Compute line-of-sight visible grid tiles from (origin_x, origin_y) within radius.

    When game_map.no_line_of_sight is True (e.g. tactical combat maps), all tiles
    within radius are visible.
    When game_map.no_line_of_sight is False, recursive octant shadowcasting is performed,
    with opaque tiles (walls, mountains, forest) casting shadows.

    For wrapping maps (border_behavior == "wrap"), coordinates wrap around map boundaries,
    and both normalized (x % W, y % H) and raw coordinates are included in the result.
    """
    visible: set[tuple[int, int]] = set()

    is_wrap = (game_map.border_behavior == "wrap")
    width = game_map.width
    height = game_map.height

    def add_tile(x: int, y: int) -> None:
        if is_wrap:
            visible.add((x % width, y % height))
            visible.add((x, y))
        else:
            if 0 <= x < width and 0 <= y < height:
                visible.add((x, y))

    def is_opaque(x: int, y: int) -> bool:
        tile = game_map.get_tile(x, y)
        if tile is None:
            return True
        return bool(tile.opaque)

    # Origin is always visible
    add_tile(origin_x, origin_y)

    if radius <= 0:
        return visible

    # If map has line-of-sight disabled, every in-range tile is visible
    if game_map.no_line_of_sight:
        r_sq = radius * radius
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= r_sq:
                    add_tile(origin_x + dx, origin_y + dy)
        return visible

    def cast_light(
        row: int,
        start_slope: float,
        end_slope: float,
        rad: int,
        xx: int,
        xy: int,
        yx: int,
        yy: int,
    ) -> None:
        if start_slope < end_slope:
            return

        rad_sq = rad * rad
        blocked = False
        new_start = 0.0

        for distance in range(row, rad + 1):
            if blocked:
                break
            delta_y = -distance
            for delta_x in range(-distance, 1):
                curr_x = origin_x + delta_x * xx + delta_y * xy
                curr_y = origin_y + delta_x * yx + delta_y * yy

                left_slope = (delta_x - 0.5) / (delta_y + 0.5)
                right_slope = (delta_x + 0.5) / (delta_y - 0.5)

                if start_slope < right_slope:
                    continue
                elif end_slope > left_slope:
                    break

                # Check if cell is within light radius
                if delta_x * delta_x + delta_y * delta_y <= rad_sq:
                    add_tile(curr_x, curr_y)

                tile_opaque = is_opaque(curr_x, curr_y)

                if blocked:
                    if tile_opaque:
                        new_start = right_slope
                        continue
                    else:
                        blocked = False
                        start_slope = new_start
                else:
                    if tile_opaque and distance < rad:
                        blocked = True
                        cast_light(
                            distance + 1,
                            start_slope,
                            left_slope,
                            rad,
                            xx,
                            xy,
                            yx,
                            yy,
                        )
                        new_start = right_slope

    # Cast light in all 8 octants
    for dx, dy in DIAGONALS:
        cast_light(1, 1.0, 0.0, radius, 0, dx, dy, 0)
        cast_light(1, 1.0, 0.0, radius, dx, 0, 0, dy)

    # Ensure 8 immediate neighbors around origin are also added
    for ndy in (-1, 0, 1):
        for ndx in (-1, 0, 1):
            add_tile(origin_x + ndx, origin_y + ndy)

    return visible
