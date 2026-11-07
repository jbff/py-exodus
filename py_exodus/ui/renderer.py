"""2D World Viewport Renderer, Camera tracking, and Collision checking."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    TILE_SIZE,
    VIEWPORT_TILES,
    TileAttrib,
    Transport,
)
from py_exodus.world.field_of_view import compute_fov

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap


def can_move_to(
    game_map: GameMap,
    target_x: int,
    target_y: int,
    transport: Transport | str = Transport.FOOT,
    party: Party | None = None,
) -> bool:
    """Validate whether the party can traverse into (target_x, target_y).

    Respects map border behavior (wrap vs exit vs fixed), terrain tile attributes,
    transport modality (foot, horse, ship), and NPC presence.
    """
    if isinstance(transport, str):
        t_str = transport.strip().lower()
        if t_str == "ship":
            transport = Transport.SHIP
        elif t_str == "horse":
            transport = Transport.HORSE
        else:
            transport = Transport.FOOT

    # Map border behavior
    if game_map.border_behavior == "wrap":
        target_x = target_x % game_map.width
        target_y = target_y % game_map.height
    else:
        if not (0 <= target_x < game_map.width and 0 <= target_y < game_map.height):
            # Exit borders allow stepping off map; fixed borders block movement
            return game_map.border_behavior == "exit"

    # Check tile walkability / sailability
    tile = game_map.get_tile(target_x, target_y)
    if tile is None:
        return False

    if transport == Transport.SHIP:
        if not tile.sailable or bool(tile.attribs & TileAttrib.SNAKE):
            return False
    elif transport == Transport.HORSE:
        if not tile.walkable or bool(tile.attribs & TileAttrib.CREATUREUNWALKABLE):
            return False
    else:  # Transport.FOOT
        if not tile.walkable:
            return False

    # Check NPC collision
    for npc in game_map.npcs:
        if npc.x == target_x and npc.y == target_y:
            return False

    return True


def check_collision(
    game_map: GameMap,
    target_x: int,
    target_y: int,
    transport: Transport | str = Transport.FOOT,
    party: Party | None = None,
) -> bool:
    """Check if movement into (target_x, target_y) results in a collision (is blocked)."""
    return not can_move_to(
        game_map,
        target_x,
        target_y,
        transport=transport,
        party=party,
    )


class WorldRenderer:
    """Renders 11x11 tile viewport (176x176 pixels) for world, city, and combat maps."""

    def __init__(
        self,
        asset_manager: AssetManager,
        tile_size: int = TILE_SIZE,
        viewport_tiles: int = VIEWPORT_TILES,
    ) -> None:
        self.asset_manager = asset_manager
        self.tile_size = tile_size
        self.viewport_tiles = viewport_tiles
        self.viewport_pixels = viewport_tiles * tile_size

    def render_viewport(
        self,
        surface: pygame.Surface,
        game_map: GameMap,
        center_x: int,
        center_y: int,
        anim_frame: int = 0,
        party: Party | None = None,
        fov: set[tuple[int, int]] | None = None,
        dest_pos: tuple[int, int] = (0, 0),
        **kwargs: Any,
    ) -> None:
        """Render the 11x11 tile window centered at (center_x, center_y).

        - Handles map wrapping for Sosaria (64x64 wrap-around).
        - Handles fixed or exit borders (e.g. cities, combat arenas).
        - Renders base terrain tiles with animation frame cycling.
        - Applies line-of-sight shading if game_map.no_line_of_sight is False.
        - Renders dynamic map objects (frigate, horse, chest) and NPCs.
        - Renders active party avatar (foot, horse, or frigate).
        """
        ox, oy = dest_pos
        half = self.viewport_tiles // 2  # 5 for 11x11

        # Fill viewport bounds with black background
        surface.fill(
            (0, 0, 0),
            pygame.Rect(ox, oy, self.viewport_pixels, self.viewport_pixels),
        )

        is_wrap = (game_map.border_behavior == "wrap")
        width = game_map.width
        height = game_map.height

        # Calculate FOV if not provided and line of sight is enabled
        if fov is None and not game_map.no_line_of_sight:
            fov = compute_fov(game_map, center_x, center_y, radius=6)

        # 1. Render base terrain tiles
        for row in range(self.viewport_tiles):
            for col in range(self.viewport_tiles):
                map_x = center_x + (col - half)
                map_y = center_y + (row - half)

                # Check FOV visibility
                if fov is not None:
                    check_x = map_x % width if is_wrap else map_x
                    check_y = map_y % height if is_wrap else map_y
                    if (check_x, check_y) not in fov and (map_x, map_y) not in fov:
                        continue

                tile = game_map.get_tile(map_x, map_y)
                if tile is None:
                    continue

                tile_surf = self.asset_manager.get_tile_surface(tile.name, anim_frame)
                px = ox + col * self.tile_size
                py = oy + row * self.tile_size
                surface.blit(tile_surf, (px, py))

        # Helper to convert map coordinates to viewport grid position (col, row)
        def map_to_viewport(ex: int, ey: int) -> tuple[int, int] | None:
            if is_wrap:
                dx = (ex - center_x + width // 2) % width - width // 2
                dy = (ey - center_y + height // 2) % height - height // 2
            else:
                dx = ex - center_x
                dy = ey - center_y

            col = half + dx
            row = half + dy
            if 0 <= col < self.viewport_tiles and 0 <= row < self.viewport_tiles:
                return col, row
            return None

        # 2. Render dynamic map objects (ships, horses, chests)
        dynamic_objs: list[Any] = []
        if party is not None and hasattr(party, "dynamic_objects"):
            dynamic_objs.extend(party.dynamic_objects)
        if kwargs.get("dynamic_objects"):
            dynamic_objs.extend(kwargs["dynamic_objects"])
        if kwargs.get("objects"):
            dynamic_objs.extend(kwargs["objects"])

        for obj in dynamic_objs:
            if isinstance(obj, dict):
                ex = obj.get("x", 0)
                ey = obj.get("y", 0)
                tile_name = obj.get("tile_name") or obj.get("name")
                if not tile_name and "tile_id" in obj:
                    tile_name = self.asset_manager.get_tile_by_index(obj["tile_id"]).name
                elif not tile_name and "tile" in obj:
                    t = obj["tile"]
                    tile_name = t.name if hasattr(t, "name") else str(t)
            else:
                ex = getattr(obj, "x", getattr(obj, "cx", 0))
                ey = getattr(obj, "y", getattr(obj, "cy", 0))
                t = getattr(obj, "tile", None)
                if t is not None and hasattr(t, "name"):
                    tile_name = str(t.name)
                else:
                    tile_name = str(t or "")

            if not tile_name:
                continue

            grid_pos = map_to_viewport(ex, ey)
            if grid_pos is None:
                continue

            col, row = grid_pos
            # Check FOV visibility
            if fov is not None:
                check_x = ex % width if is_wrap else ex
                check_y = ey % height if is_wrap else ey
                if (check_x, check_y) not in fov and (ex, ey) not in fov:
                    continue

            obj_surf = self.asset_manager.get_tile_surface(tile_name, anim_frame)
            surface.blit(obj_surf, (ox + col * self.tile_size, oy + row * self.tile_size))

        # 3. Render dynamic monsters
        dynamic_monsters: list[Any] = []
        if party is not None and hasattr(party, "dynamic_monsters"):
            dynamic_monsters.extend(party.dynamic_monsters)
        if kwargs.get("dynamic_monsters"):
            dynamic_monsters.extend(kwargs["dynamic_monsters"])
        if kwargs.get("monsters"):
            dynamic_monsters.extend(kwargs["monsters"])

        for mon in dynamic_monsters:
            if isinstance(mon, dict):
                ex = mon.get("x", 0)
                ey = mon.get("y", 0)
                tile_name = mon.get("tile_name") or mon.get("name")
                if not tile_name and "tile_id" in mon:
                    tile_name = self.asset_manager.get_tile_by_index(mon["tile_id"]).name
            else:
                ex = getattr(mon, "x", getattr(mon, "currentX", 0))
                ey = getattr(mon, "y", getattr(mon, "currentY", 0))
                t = getattr(mon, "tile_name", getattr(mon, "tile", ""))
                tile_name = t.name if hasattr(t, "name") else str(t)

            if not tile_name:
                continue

            grid_pos = map_to_viewport(ex, ey)
            if grid_pos is None:
                continue

            col, row = grid_pos
            if fov is not None:
                check_x = ex % width if is_wrap else ex
                check_y = ey % height if is_wrap else ey
                if (check_x, check_y) not in fov and (ex, ey) not in fov:
                    continue

            mon_surf = self.asset_manager.get_tile_surface(tile_name, anim_frame)
            surface.blit(mon_surf, (ox + col * self.tile_size, oy + row * self.tile_size))

        # 4. Render map NPCs
        npcs: list[Any] = list(game_map.npcs)
        if kwargs.get("npcs"):
            npcs.extend(kwargs["npcs"])

        for npc in npcs:
            ex = getattr(npc, "x", 0)
            ey = getattr(npc, "y", 0)
            tile_name = getattr(npc, "tile_name", None)
            if not tile_name and hasattr(npc, "tile_def") and npc.tile_def:
                tile_name = npc.tile_def.name

            if not tile_name:
                continue

            grid_pos = map_to_viewport(ex, ey)
            if grid_pos is None:
                continue

            col, row = grid_pos
            if fov is not None:
                check_x = ex % width if is_wrap else ex
                check_y = ey % height if is_wrap else ey
                if (check_x, check_y) not in fov and (ex, ey) not in fov:
                    continue

            npc_surf = self.asset_manager.get_tile_surface(tile_name, anim_frame)
            surface.blit(npc_surf, (ox + col * self.tile_size, oy + row * self.tile_size))

        # 5. Render moongates if phase active
        moon_phase = kwargs.get("moon_phase")
        if moon_phase is not None and game_map.moongates:
            for gate in game_map.moongates:
                if gate.phase == moon_phase:
                    grid_pos = map_to_viewport(gate.x, gate.y)
                    if grid_pos is not None:
                        col, row = grid_pos
                        gate_surf = self.asset_manager.get_tile_surface("moongate", anim_frame)
                        surface.blit(gate_surf, (ox + col * self.tile_size, oy + row * self.tile_size))

        # 6. Render active party avatar
        if party is not None:
            grid_pos = map_to_viewport(party.x, party.y)
            if grid_pos is not None:
                col, row = grid_pos
                avatar_name = kwargs.get("avatar_override")
                if not avatar_name:
                    if party.transport == Transport.SHIP:
                        avatar_name = "frigate"
                    elif party.transport == Transport.HORSE:
                        avatar_name = "horse"
                    else:
                        avatar_name = "ranger"

                avatar_surf = self.asset_manager.get_tile_surface(avatar_name, anim_frame)
                surface.blit(avatar_surf, (ox + col * self.tile_size, oy + row * self.tile_size))
        elif kwargs.get("avatar_tile") or kwargs.get("avatar_name"):
            av_name = kwargs.get("avatar_tile") or kwargs.get("avatar_name")
            av_surf = self.asset_manager.get_tile_surface(str(av_name), anim_frame)
            surface.blit(av_surf, (ox + half * self.tile_size, oy + half * self.tile_size))

    def can_move(
        self,
        game_map: GameMap,
        target_x: int,
        target_y: int,
        transport: Transport | str = Transport.FOOT,
        party: Party | None = None,
    ) -> bool:
        """Helper to test move validity."""
        return can_move_to(game_map, target_x, target_y, transport=transport, party=party)

    def check_collision(
        self,
        game_map: GameMap,
        target_x: int,
        target_y: int,
        transport: Transport | str = Transport.FOOT,
        party: Party | None = None,
    ) -> bool:
        """Helper to test collision."""
        return check_collision(game_map, target_x, target_y, transport=transport, party=party)
