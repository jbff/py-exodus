"""2D overworld/town and 3D dungeon BFS pathfinders for Full Autoplay."""
from __future__ import annotations

from collections import deque
import heapq
from typing import TYPE_CHECKING

import pygame

from py_exodus.constants import Direction, Transport
from py_exodus.entities.party import objects_on
from py_exodus.screens.overworld import can_move_to
from py_exodus.world import tile_effects
from py_exodus.world.dungeon import turn_left_dir, turn_right_dir
from py_exodus.world.map import DungeonTile

if TYPE_CHECKING:
    from py_exodus.entities.party import Party
    from py_exodus.world.map import DungeonMap, GameMap

_CARDINALS = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)
_BLOCKED_DUNGEON_TILES = frozenset({DungeonTile.WALL, DungeonTile.FIELD_ENERGY})
_LADDER_DOWN_TILES = frozenset({DungeonTile.LADDER_DOWN, DungeonTile.LADDER_UP_DOWN})
_LADDER_UP_TILES = frozenset({DungeonTile.LADDER_UP, DungeonTile.LADDER_UP_DOWN})


def locked_door_passable(game_map, x: int, y: int, transport: Transport, party=None) -> bool:
    """Can ``transport`` pass the locked door at (x, y) once it is unlocked?

    On the surface (Sosaria 0, Ambrosia 13) LairWare turns an unlocked door
    into the tile WEST of it (UltimaMain.c:2428-2433; the overworld U command
    mirrors it), so the door is as passable as that tile: Ambrosia's door in
    the water channel (39, 61) opens for a ship, not for walkers. Towns do
    the same, and their doors open onto floor or grass: walkable.
    """
    if getattr(game_map, "id", None) in (0, 13):
        wx = (x - 1) % game_map.width
        west = game_map.get_tile(wx, y)
        if west is None or str(getattr(west, "name", "")).lower() == "locked_door":
            return False
        if getattr(west, "index", 99) > 8:
            return transport == Transport.FOOT  # opens to grass
        return can_move_to(game_map, wx, y, transport=transport, party=party)
    return transport == Transport.FOOT


def find_2d_step_and_cost(
    game_map: GameMap,
    start: tuple[int, int],
    goals: set[tuple[int, int]] | tuple[int, int],
    transport: Transport = Transport.FOOT,
    party: Party | None = None,
    avoid_tiles: set[tuple[int, int]] | None = None,
    wind_direction: Direction | None = None,
    prefer_paths: bool = False,
    allow_locked_doors: bool = False,
    ignore_wind: bool = False,
) -> tuple[Direction | None, int | None]:
    """Return ``(first_direction, path_cost)`` toward the nearest reachable goal."""
    goal_set: set[tuple[int, int]] = (
        {goals} if isinstance(goals, tuple) and len(goals) == 2 and isinstance(goals[0], int) else set(goals)
    )
    if not goal_set or start in goal_set:
        return (None, None)

    if transport == Transport.SHIP and wind_direction is None and not ignore_wind:
        return (None, None)

    blocked_dir = (
        wind_direction.reverse()
        if transport == Transport.SHIP and wind_direction is not None and not ignore_wind
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
            for obj in objects_on(party, game_map)
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

    has_fire = party is not None and any(not m.is_dead() and m.marks[1] > 0 for m in party.members)
    # Mark of Force is marks[3]; energy fields pass only when EVERY living
    # member carries it (GBC rule, world/tile_effects.py).
    has_force = tile_effects.all_members_mark_of_force(party)

    def _passable(nx: int, ny: int) -> bool:
        t = game_map.get_tile(nx, ny)
        tname = str(getattr(t, "name", "")).lower() if t else ""
        if tname in ("lava", "fire") and not has_fire:
            return False
        if tname in ("energy_field", "force_field") and not has_force:
            return False
        if can_move_to(game_map, nx, ny, transport=transport, party=party):
            return True
        if allow_locked_doors and t is not None and tname == "locked_door":
            return locked_door_passable(game_map, nx, ny, transport, party)
        return False

    if prefer_paths:
        pq: list[tuple[int, int, tuple[int, int], Direction | None]] = [(0, 0, start, None)]
        best_cost: dict[tuple[int, int], int] = {start: 0}
        tie = 0
        while pq:
            cost, _, (cx, cy), first_dir = heapq.heappop(pq)
            if cost > best_cost.get((cx, cy), float("inf")):
                continue
            if (cx, cy) in goal_set and first_dir is not None:
                return (first_dir, cost)
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
                    if not (is_special or _passable(nx, ny)):
                        continue
                    ncost = cost + _tile_cost(nx, ny)
                else:
                    if nxt in avoid or not _passable(nx, ny):
                        continue
                    ncost = cost + _tile_cost(nx, ny)
                if ncost < best_cost.get(nxt, 10**9):
                    best_cost[nxt] = ncost
                    tie += 1
                    heapq.heappush(pq, (ncost, tie, nxt, step_dir))
        return (None, None)

    queue: deque[tuple[tuple[int, int], Direction | None, int]] = deque([(start, None, 0)])
    visited: set[tuple[int, int]] = {start}

    while queue:
        (cx, cy), first_dir, dist = queue.popleft()
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
                if is_special_goal or _passable(nx, ny):
                    return (step_dir, dist + 1)
                continue

            if nxt in avoid:
                continue
            if not _passable(nx, ny):
                continue

            visited.add(nxt)
            queue.append((nxt, step_dir, dist + 1))

    return (None, None)


def reachable_2d(
    game_map: GameMap,
    start: tuple[int, int],
    transport: Transport = Transport.FOOT,
    party: Party | None = None,
    avoid_tiles: set[tuple[int, int]] | None = None,
    allow_locked_doors: bool = False,
) -> set[tuple[int, int]]:
    """Every tile reachable from ``start`` under find_2d_step's rules.

    Tiles that are not passable themselves but may be a step's goal (a
    chest under a counter, say) are not included; callers test goals
    against the neighbours of this set when they need that."""
    has_fire = party is not None and any(not m.is_dead() and m.marks[1] > 0 for m in party.members)
    has_force = tile_effects.all_members_mark_of_force(party)
    wraps = getattr(game_map, "border_behavior", "exit") == "wrap"
    w, h = game_map.width, game_map.height
    avoid = avoid_tiles or set()

    def _passable(nx: int, ny: int) -> bool:
        t = game_map.get_tile(nx, ny)
        tname = str(getattr(t, "name", "")).lower() if t else ""
        if tname in ("lava", "fire") and not has_fire:
            return False
        if tname in ("energy_field", "force_field") and not has_force:
            return False
        if can_move_to(game_map, nx, ny, transport=transport, party=party):
            return True
        if allow_locked_doors and t is not None and tname == "locked_door":
            return locked_door_passable(game_map, nx, ny, transport, party)
        return False

    seen = {start}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for d in _CARDINALS:
            nx, ny = cx + d.dx, cy + d.dy
            if wraps:
                nx %= w
                ny %= h
            elif not (0 <= nx < w and 0 <= ny < h):
                continue
            n = (nx, ny)
            if n in seen or n in avoid or not _passable(nx, ny):
                continue
            seen.add(n)
            queue.append(n)
    return seen


def find_2d_step(
    game_map: GameMap,
    start: tuple[int, int],
    goals: set[tuple[int, int]] | tuple[int, int],
    transport: Transport = Transport.FOOT,
    party: Party | None = None,
    avoid_tiles: set[tuple[int, int]] | None = None,
    wind_direction: Direction | None = None,
    prefer_paths: bool = False,
    allow_locked_doors: bool = False,
    ignore_wind: bool = False,
) -> Direction | None:
    """Return the first cardinal Direction toward the nearest reachable goal on a 2D map."""
    return find_2d_step_and_cost(
        game_map=game_map,
        start=start,
        goals=goals,
        transport=transport,
        party=party,
        avoid_tiles=avoid_tiles,
        wind_direction=wind_direction,
        prefer_paths=prefer_paths,
        allow_locked_doors=allow_locked_doors,
        ignore_wind=ignore_wind,
    )[0]


def find_dungeon_step(
    dmap: DungeonMap,
    x: int,
    y: int,
    z: int,
    facing: Direction,
    goals: set[tuple[int, int, int]],
    penalty_tiles: set[tuple[int, int, int]] | None = None,
) -> int | None:
    """Return the pygame.K_* key for the next step toward the nearest 3D dungeon goal.

    With ``penalty_tiles`` (gremlins, say), the route crosses as few of
    them as it can, then is the shortest; without, plain BFS."""
    if not goals or (x, y, z) in goals:
        return None
    if penalty_tiles:
        return _find_dungeon_step_weighted(dmap, x, y, z, facing, goals, penalty_tiles)

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


def _find_dungeon_step_weighted(
    dmap: DungeonMap,
    x: int,
    y: int,
    z: int,
    facing: Direction,
    goals: set[tuple[int, int, int]],
    penalty_tiles: set[tuple[int, int, int]],
) -> int | None:
    """Dijkstra twin of ``find_dungeon_step``: entering a penalty tile costs
    far more than any number of plain moves."""

    big = 10_000
    start = (x, y, z, facing)
    best: dict[tuple[int, int, int, Direction], int] = {start: 0}
    order = 0
    heap: list[tuple[int, int, int, int, int, Direction, int | None]] = [(0, order, x, y, z, facing, None)]
    while heap:
        cost, _o, cx, cy, cz, cfacing, first_key = heapq.heappop(heap)
        if (cx, cy, cz) in goals:
            return first_key
        if cost > best.get((cx, cy, cz, cfacing), cost):
            continue
        cur_tile = dmap.get_tile(cx, cy, cz)
        candidates: list[tuple[int, int, int, Direction, int]] = []
        fx = (cx + cfacing.dx) % dmap.width
        fy = (cy + cfacing.dy) % dmap.height
        if dmap.get_tile(fx, fy, cz) not in _BLOCKED_DUNGEON_TILES:
            candidates.append((fx, fy, cz, cfacing, pygame.K_UP))
        if cur_tile in _LADDER_DOWN_TILES and cz + 1 < dmap.levels:
            candidates.append((cx, cy, cz + 1, cfacing, pygame.K_d))
        if cur_tile in _LADDER_UP_TILES and cz - 1 >= 0:
            candidates.append((cx, cy, cz - 1, cfacing, pygame.K_k))
        candidates.append((cx, cy, cz, turn_left_dir(cfacing), pygame.K_LEFT))
        candidates.append((cx, cy, cz, turn_right_dir(cfacing), pygame.K_RIGHT))
        for nx, ny, nz, nfacing, key in candidates:
            moved = (nx, ny, nz) != (cx, cy, cz)
            ncost = cost + 1 + (big if moved and (nx, ny, nz) in penalty_tiles else 0)
            state = (nx, ny, nz, nfacing)
            if ncost < best.get(state, ncost + 1):
                best[state] = ncost
                order += 1
                heapq.heappush(heap, (ncost, order, nx, ny, nz, nfacing, first_key if first_key is not None else key))
    return None
