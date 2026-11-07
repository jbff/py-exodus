"""Overworld exploration screen for Sosaria and Ambrosia."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    TILE_SIZE,
    Direction,
    MapType,
    TileAttrib,
    Transport,
)
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap


class OverworldScreen(BaseScreen):
    """Exploration screen for the Sosaria world map and Ambrosia continent."""

    def __init__(
        self,
        party: Party,
        map_id: int | str = 0,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        random_encounters: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.map_id = map_id
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.random_encounters_enabled = random_encounters

        self.game_map: GameMap | None = None
        self._load_world_map()

        self.anim_frame = 0
        self.anim_timer = 0.0
        self.moon_timer = 0.0
        self.moon_phase = 0

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        map_name = getattr(self.game_map, "name", "Sosaria")
        self.text_log.add_message(f"Entering the realm of {map_name}...")
        self.text_log.add_message(f"Wind blows {self.party.wind_direction.name}.")

    def _load_world_map(self) -> None:
        if self.asset_mgr is None:
            return
        try:
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            loaded = loader.load_map(self.map_id)
            if hasattr(loaded, "width"):
                self.game_map = loaded
        except Exception:
            pass

    def on_enter(self) -> None:
        super().on_enter()
        self._play_overworld_music()

    def _play_overworld_music(self) -> None:
        if self.audio is None:
            return
        if str(self.map_id) in ("13", "ambrosia"):
            self.audio.play_music("dungeon")
        else:
            self.audio.play_music("wander")

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # Movement
        if event.key in (pygame.K_UP, pygame.K_w):
            self._move_avatar(Direction.NORTH)
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self._move_avatar(Direction.SOUTH)
        elif event.key in (pygame.K_LEFT, pygame.K_a):
            self._move_avatar(Direction.WEST)
        elif event.key in (pygame.K_RIGHT, pygame.K_d):
            self._move_avatar(Direction.EAST)
        elif event.key == pygame.K_e:
            self._enter_portal()
        elif event.key == pygame.K_f and self.party.transport == Transport.SHIP:
            self._prompt_fire_cannons()
        elif event.key == pygame.K_b:
            self._toggle_board_transport()
        elif event.key == pygame.K_s:
            self._save_game()

    def _move_avatar(self, direction: Direction) -> None:
        if self.game_map is None:
            return

        # Frigate sailing rules
        if self.party.transport == Transport.SHIP:
            # Check headwind
            if direction == self.party.wind_direction.reverse():
                self.text_log.add_message("Sailing against headwinds slows thee!")

        nx = (self.party.x + direction.dx) % self.game_map.width
        ny = (self.party.y + direction.dy) % self.game_map.height

        if can_move_to(self.game_map, nx, ny, transport=self.party.transport, party=self.party):
            self.party.x = nx
            self.party.y = ny
            self.party.moves += 1

            if self.audio is not None:
                self.audio.play_sfx("walk_normal")

            # Check food consumption
            if self.party.moves % 40 == 0:
                if self.party.food > 0:
                    self.party.food -= 1
                else:
                    self.text_log.add_message("Starving! Party loses health.")
                    for m in self.party.members:
                        m.character.hp = max(0, m.character.hp - 2)

            # Check moongate teleports
            self._check_moongates()

            # Check random encounters
            if self.random_encounters_enabled:
                self._check_random_encounter()
        else:
            if self.audio is not None:
                self.audio.play_sfx("blocked")

    def _prompt_fire_cannons(self) -> None:
        """Fire frigate broadside cannons in a given direction."""
        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid firing direction!")
                return
            self._fire_cannons(d)

        self.text_log.prompt("Fire cannon direction? (N,S,E,W):", callback=_on_dir)

    def _fire_cannons(self, direction: Direction) -> None:
        if self.audio is not None:
            self.audio.play_sfx("cannon") or self.audio.play_sfx("enemy_magic_proj")

        self.text_log.add_message(f"BOOM! Broadside fired {direction.name}!")

        # Trace cannonball up to 3 tiles
        if self.game_map is None:
            return
        cx, cy = self.party.x, self.party.y
        for step in range(1, 4):
            tx = (cx + direction.dx * step) % self.game_map.width
            ty = (cy + direction.dy * step) % self.game_map.height
            tile = self.game_map.get_tile(tx, ty)
            if tile is not None and not tile.walkable and not tile.sailable:
                self.text_log.add_message("Cannonball crashed into the shoreline!")
                break

    def _enter_portal(self) -> None:
        """Enter city, dungeon, shrine, or whirlpool portal at party location."""
        if self.game_map is None:
            return

        portal = None
        for p in self.game_map.portals:
            if p.x == self.party.x and p.y == self.party.y:
                portal = p
                break

        if portal is None:
            self.text_log.add_message("Nothing to enter here!")
            return

        dest_id = portal.dest_map_id
        start_x = portal.start_x
        start_y = portal.start_y

        # Determine if destination is town, dungeon, or shrine
        if dest_id in (55, 56, 57, 58):  # Shrine
            from py_exodus.screens.shrine import ShrineScreen

            stat_names = {
                55: "wisdom",
                56: "dexterity",
                57: "intelligence",
                58: "strength",
            }
            shrine = ShrineScreen(
                party=self.party,
                stat_name=stat_names.get(dest_id, "strength"),
                asset_mgr=self.asset_mgr,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(shrine)
            else:
                self.next_screen = shrine
                self.is_finished = True

        elif dest_id in (14, 15, 16, 17, 18, 19, 20):  # Dungeons
            from py_exodus.screens.dungeon_screen import DungeonScreen

            dungeon = DungeonScreen(
                party=self.party,
                map_id=dest_id,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(dungeon)
            else:
                self.next_screen = dungeon
                self.is_finished = True

        else:  # Cities / Towns / Castles
            from py_exodus.screens.town import TownScreen

            town = TownScreen(
                party=self.party,
                map_id=dest_id,
                start_x=start_x,
                start_y=start_y,
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                return_screen=self,
                manager=self.manager,
            )
            if self.manager is not None:
                self.manager.push_screen(town)
            else:
                self.next_screen = town
                self.is_finished = True

    def _toggle_board_transport(self) -> None:
        """Board or dismount horse/frigate."""
        if self.party.transport == Transport.FOOT:
            # Check adjacent tiles or party location for transport
            self.party.transport = Transport.HORSE
            self.text_log.add_message("Mounted horse! Movement speed increased.")
        elif self.party.transport == Transport.HORSE:
            self.party.transport = Transport.FOOT
            self.text_log.add_message("Dismounted to foot.")
        elif self.party.transport == Transport.SHIP:
            self.party.transport = Transport.FOOT
            self.text_log.add_message("Disembarked ship to foot.")

    def _check_moongates(self) -> None:
        """Check if party stepped onto an active moongate."""
        if self.game_map is None:
            return
        for gate in self.game_map.moongates:
            if gate.phase == (self.moon_phase % 8):
                if gate.x == self.party.x and gate.y == self.party.y:
                    # Teleport to destination gate
                    dest_gate = self.game_map.moongates[(gate.d1) % len(self.game_map.moongates)]
                    self.party.x = dest_gate.x
                    self.party.y = dest_gate.y
                    self.text_log.add_message("Stepped through mystical moongate!")
                    if self.audio is not None:
                        self.audio.play_sfx("moongate_flash")
                    break

    def _check_random_encounter(self) -> None:
        """Check for random monster ambush on hostile terrain."""
        if self.game_map is None or self.asset_mgr is None:
            return

        tile = self.game_map.get_tile(self.party.x, self.party.y)
        if tile is None:
            return

        # 8% encounter chance
        if random.random() < 0.08:
            tile_name = getattr(tile, "name", "grass").lower()
            creature_name = "orc"
            conflict_map_id = 37

            if "brush" in tile_name or "forest" in tile_name:
                creature_name = "troll"
                conflict_map_id = 34
            elif "water" in tile_name or "sea" in tile_name:
                creature_name = "pirate"
                conflict_map_id = 41

            try:
                from py_exodus.screens.combat_screen import CombatScreen
                from py_exodus.world.loader import MapLoader

                loader = MapLoader(self.asset_mgr)
                c_map = loader.load_conflict_map(conflict_map_id)
                combat_scr = CombatScreen(
                    party=self.party,
                    combat_map=c_map,
                    creature_tile=creature_name,
                    asset_mgr=self.asset_mgr,
                    audio=self.audio,
                    return_screen=self,
                    manager=self.manager,
                )
                if self.manager is not None:
                    self.manager.push_screen(combat_scr)
                else:
                    self.next_screen = combat_scr
                    self.is_finished = True
            except Exception:
                pass

    def _save_game(self) -> None:
        """Save party progress to JSON file."""
        try:
            from py_exodus.save_system import SaveSystem

            SaveSystem.save_game(self.party, "saves/party.json")
            self.text_log.add_message("Game saved successfully.")
        except Exception as e:
            self.text_log.add_message("Save failed!")

    def update(self, dt: float) -> None:
        self.anim_timer += dt
        if self.anim_timer >= 0.2:
            self.anim_timer = 0.0
            self.anim_frame = (self.anim_frame + 1) % 4

        self.moon_timer += dt
        if self.moon_timer >= 4.0:
            self.moon_timer = 0.0
            self.moon_phase = (self.moon_phase + 1) % 24
            # Random wind shift
            if random.random() < 0.15:
                dirs = list(Direction)
                self.party.wind_direction = random.choice(dirs)

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)

        # 1. 11x11 Overworld Viewport (176x176 at 0, 0)
        if self.world_renderer is not None and self.game_map is not None:
            self.world_renderer.render_viewport(
                surface,
                self.game_map,
                center_x=self.party.x,
                center_y=self.party.y,
                anim_frame=self.anim_frame,
                party=self.party,
                dest_pos=(0, 0),
            )

        # 2. Right Sidebar (Party Stats)
        self.stats_panel.render(
            surface,
            self.party,
            rect=pygame.Rect(176, 0, surface.get_width() - 176, surface.get_height()),
        )

        # 3. Bottom HUD Text Log
        log_h = max(24, surface.get_height() - 176)
        self.text_log.render(
            surface,
            rect=pygame.Rect(0, 176, 176, log_h),
            draw_border=True,
        )
