"""2D overworld/town and 3D dungeon BFS pathfinders for Full Autoplay."""
from __future__ import annotations

from collections import deque
import heapq
from typing import TYPE_CHECKING

import pygame

from py_exodus.constants import Direction, Transport
from py_exodus.screens.overworld import can_move_to
from py_exodus.world.dungeon import turn_left_dir, turn_right_dir
from py_exodus.world.map import DungeonTile

if TYPE_CHECKING:
    from py_exodus.entities.party import Party
    from py_exodus.world.map import DungeonMap, GameMap

_CARDINALS = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)
_BLOCKED_DUNGEON_TILES = frozenset({DungeonTile.WALL, DungeonTile.FIELD_ENERGY})
_LADDER_DOWN_TILES = frozenset({DungeonTile.LADDER_DOWN, DungeonTile.LADDER_UP_DOWN})
_LADDER_UP_TILES = frozenset({DungeonTile.LADDER_UP, DungeonTile.LADDER_UP_DOWN})


def find_2d_step(
    game_map: GameMap,
    start: tuple[int, int],
    goals: set[tuple[int, int]] | tuple[int, int],
    transport: Transport = Transport.FOOT,
    party: Party | None = None,
    avoid_tiles: set[tuple[int, int]] | None = None,
    wind_direction: Direction | None = None,
    prefer_paths: bool = False,
) -> Direction | None:
    """Return the first cardinal Direction toward the nearest reachable goal on a 2D map."""
    goal_set: set[tuple[int, int]] = (
        {goals} if isinstance(goals, tuple) and len(goals) == 2 and isinstance(goals[0], int) else set(goals)
    )
    if not goal_set or start in goal_set:
        return None

    if transport == Transport.SHIP and wind_direction is None:
        return None

    blocked_dir = (
        wind_direction.reverse()
        if transport == Transport.SHIP and wind_direction is not None
        else None
    )

    wraps = getattr(game_map, "border_behavior", "exit") == "wrap"
    width = game_map.width
    height = game_map.height
    avoid = avoid_tiles or set()

    portal_coords = {(p.x, p.y) for p in getattr(game_map, "portals", [])}
    frigate_coords = (
        {
            (obj.get("x"), obj.get("y"))
            for obj in getattr(party, "dynamic_objects", [])
            if str(obj.get("tile", "")).lower() == "frigate"
        }
        if party is not None
        else set()
    )

    def _tile_cost(tx: int, ty: int) -> int:
        if not prefer_paths:
            return 1
        t = game_map.get_tile(tx, ty)
        tname = str(getattr(t, "name", "")).lower() if t else ""
        return 1 if tname in ("floor", "bridge", "path") else 4

    if prefer_paths:
        pq: list[tuple[int, int, tuple[int, int], Direction | None]] = [(0, 0, start, None)]
        best_cost: dict[tuple[int, int], int] = {start: 0}
        tie = 0
        while pq:
            cost, _, (cx, cy), first_dir = heapq.heappop(pq)
            if cost > best_cost.get((cx, cy), float("inf")):
                continue
            if (cx, cy) in goal_set and first_dir is not None:
                return first_dir
            for d in _CARDINALS:
                if blocked_dir is not None and d == blocked_dir:
                    continue
                nx, ny = cx + d.dx, cy + d.dy
                if wraps:
                    nx %= width
                    ny %= height
                elif not (0 <= nx < width and 0 <= ny < height):
                    continue
                nxt = (nx, ny)
                step_dir = first_dir if first_dir is not None else d
                if nxt in goal_set:
                    if nxt in avoid and nxt not in portal_coords and nxt not in frigate_coords:
                        continue
                    tile = game_map.get_tile(nx, ny)
                    tile_name = str(getattr(tile, "name", "")).lower() if tile else ""
                    is_special = nxt in portal_coords or nxt in frigate_coords or tile_name == "whirlpool"
                    if not (is_special or can_move_to(game_map, nx, ny, transport=transport, party=party)):
                        continue
                    ncost = cost + _tile_cost(nx, ny)
                else:
                    if nxt in avoid or not can_move_to(game_map, nx, ny, transport=transport, party=party):
                        continue
                    ncost = cost + _tile_cost(nx, ny)
                if ncost < best_cost.get(nxt, 10**9):
                    best_cost[nxt] = ncost
                    tie += 1
                    heapq.heappush(pq, (ncost, tie, nxt, step_dir))
        return None

    queue: deque[tuple[tuple[int, int], Direction | None]] = deque([(start, None)])
    visited: set[tuple[int, int]] = {start}

    while queue:
        (cx, cy), first_dir = queue.popleft()
        for d in _CARDINALS:
            if blocked_dir is not None and d == blocked_dir:
                continue
            nx, ny = cx + d.dx, cy + d.dy
            if wraps:
                nx %= width
                ny %= height
            elif not (0 <= nx < width and 0 <= ny < height):
                continue

            nxt = (nx, ny)
            if nxt in visited:
                continue

            step_dir = first_dir if first_dir is not None else d

            if nxt in goal_set:
                if nxt in avoid and nxt not in portal_coords and nxt not in frigate_coords:
                    continue
                tile = game_map.get_tile(nx, ny)
                tile_name = str(getattr(tile, "name", "")).lower() if tile else ""
                is_special_goal = (
                    nxt in portal_coords
                    or nxt in frigate_coords
                    or tile_name == "whirlpool"
                )
                if is_special_goal or can_move_to(game_map, nx, ny, transport=transport, party=party):
                    return step_dir
                continue

            if nxt in avoid:
                continue
            if not can_move_to(game_map, nx, ny, transport=transport, party=party):
                continue

            visited.add(nxt)
            queue.append((nxt, step_dir))

    return None


def find_dungeon_step(
    dmap: DungeonMap,
    x: int,
    y: int,
    z: int,
    facing: Direction,
    goals: set[tuple[int, int, int]],
) -> int | None:
    """Return the pygame.K_* key for the next step toward the nearest 3D dungeon goal."""
    if not goals or (x, y, z) in goals:
        return None

    start_state = (x, y, z, facing)
    queue: deque[tuple[int, int, int, Direction, int | None]] = deque(
        [(x, y, z, facing, None)]
    )
    visited: set[tuple[int, int, int, Direction]] = {start_state}

    while queue:
        cx, cy, cz, cfacing, first_key = queue.popleft()
        cur_tile = dmap.get_tile(cx, cy, cz)

        candidates: list[tuple[int, int, int, Direction, int]] = []

        # 1. Forward step
        fx = (cx + cfacing.dx) % dmap.width
        fy = (cy + cfacing.dy) % dmap.height
        if dmap.get_tile(fx, fy, cz) not in _BLOCKED_DUNGEON_TILES:
            candidates.append((fx, fy, cz, cfacing, pygame.K_UP))

        # 2. Ladder down
        if cur_tile in _LADDER_DOWN_TILES and cz + 1 < dmap.levels:
            candidates.append((cx, cy, cz + 1, cfacing, pygame.K_d))

        # 3. Ladder up
        if cur_tile in _LADDER_UP_TILES and cz - 1 >= 0:
            candidates.append((cx, cy, cz - 1, cfacing, pygame.K_k))

        # 4. Turn left / right
        candidates.append((cx, cy, cz, turn_left_dir(cfacing), pygame.K_LEFT))
        candidates.append((cx, cy, cz, turn_right_dir(cfacing), pygame.K_RIGHT))

        for nx, ny, nz, nfacing, key in candidates:
            step_key = first_key if first_key is not None else key
            if (nx, ny, nz) in goals:
                return step_key
            state = (nx, ny, nz, nfacing)
            if state not in visited:
                visited.add(state)
                queue.append((nx, ny, nz, nfacing, step_key))

    return None
