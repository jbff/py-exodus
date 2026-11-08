"""Dungeon exploration screen with 3D wireframe corridors, HUD, and combat triggers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    Direction,
    MapType,
    Spell,
)
from py_exodus.screens.base import BaseScreen
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
from py_exodus.world.dungeon import (
    DungeonCamera,
    DungeonEvent,
    DungeonEventType,
    DungeonState,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party
    from py_exodus.world.map import DungeonMap


class DungeonScreen(BaseScreen):
    """First-person 3D wireframe dungeon navigation screen."""

    def __init__(
        self,
        party: Party,
        dungeon_map: DungeonMap | None = None,
        map_id: int | str = 14,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        start_x: int = 1,
        start_y: int = 1,
        start_z: int = 0,
        start_dir: Direction = Direction.NORTH,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.map_id = map_id

        # Load map if not provided
        self.dungeon_map = dungeon_map
        if self.dungeon_map is None and self.asset_mgr is not None:
            self._load_map()

        # Fallback empty dungeon map if none could be loaded
        if self.dungeon_map is None:
            from py_exodus.world.map import DungeonMap

            self.dungeon_map = DungeonMap(
                width=16, height=16, levels=8, name="Dungeon", fname="perinian.ult"
            )

        self.state = DungeonState(
            dmap=self.dungeon_map,
            start_x=start_x,
            start_y=start_y,
            start_z=start_z,
            start_dir=start_dir,
            party=self.party,
            asset_manager=self.asset_mgr,
        )
        self.camera = DungeonCamera(viewport_size=176)
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        self.text_log.add_message(f"Entering {self.dungeon_map.name}...")
        self.text_log.add_message("Level 1. Darkness surrounds thee.")

    def _load_map(self) -> None:
        try:
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            loaded = loader.load_map(self.map_id)
            if hasattr(loaded, "levels"):
                self.dungeon_map = loaded
        except Exception:
            pass

    def on_enter(self) -> None:
        super().on_enter()
        if self.audio is not None:
            self.audio.play_music("dungeon")

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # Movement and navigation keys: Arrow keys and Keypad ONLY (no WASD)
        if event.key in (pygame.K_UP, pygame.K_KP8):
            evt = self.state.move_forward()
            self._process_event(evt)
        elif event.key in (pygame.K_DOWN, pygame.K_KP2):
            evt = self.state.turn_around()
            self._process_event(evt)
        elif event.key in (pygame.K_LEFT, pygame.K_KP4):
            evt = self.state.turn_left()
            self._process_event(evt)
        elif event.key in (pygame.K_RIGHT, pygame.K_KP6):
            evt = self.state.turn_right()
            self._process_event(evt)
        elif event.key in (pygame.K_k, pygame.K_u):
            evt = self.state.klimb_up()
            self._process_event(evt)
        elif event.key in (pygame.K_d, pygame.K_j):  # Down ladder
            evt = self.state.klimb_down()
            self._process_event(evt)
        elif event.key in (pygame.K_t, pygame.K_i):
            self._use_torch()
        elif event.key == pygame.K_c:
            self._cast_spell()
        elif event.key == pygame.K_z:
            self._toggle_zstats()
        elif event.key == pygame.K_s:
            self._search()
        elif event.key == pygame.K_g:
            self._get_chest()
        elif event.key == pygame.K_o:
            def _on_other(cmd: str) -> None:
                self.text_log.add_message(f"'{cmd.strip().upper()}': Nothing happened.")
            self.text_log.prompt("Other Command? ", callback=_on_other)
        elif event.key == pygame.K_SPACE:
            self.text_log.add_message("Pass.")

    def _toggle_zstats(self) -> None:
        """Cycle Ztats inspect mode through party members."""
        current = self.stats_panel.inspect_index
        member_count = len(self.party.members)
        if member_count == 0:
            return
        if current is None:
            self.stats_panel.inspect_index = 0
        elif current + 1 < member_count:
            self.stats_panel.inspect_index = current + 1
        else:
            self.stats_panel.inspect_index = None

    def _process_event(self, evt: DungeonEvent) -> None:
        if evt.message:
            self.text_log.add_message(evt.message)

        if self.audio is not None:
            if evt.type == DungeonEventType.BLOCKED:
                self.audio.play_sfx("blocked")
            elif evt.type in (DungeonEventType.MOVED, DungeonEventType.TURNED):
                self.audio.play_sfx("walk_normal")
            elif evt.type in (DungeonEventType.LADDER_UP, DungeonEventType.LADDER_DOWN):
                self.audio.play_sfx("trigger")
            elif evt.type == DungeonEventType.MARK:
                self.audio.play_sfx("lightning") or self.audio.play_sfx("magic")
            elif evt.type in (DungeonEventType.FOUNTAIN, DungeonEventType.HEAL):
                self.audio.play_sfx("magic")
            elif evt.type == DungeonEventType.CHEST:
                self.audio.play_sfx("trigger")

        if evt.type == DungeonEventType.EXIT_DUNGEON:
            self.text_log.add_message("Leaving dungeon...")
            self.exit_screen()
        elif evt.type == DungeonEventType.COMBAT:
            c_name = "skeleton"
            if evt.creature is not None:
                if hasattr(evt.creature, "tile"):
                    c_name = evt.creature.tile
                elif hasattr(evt.creature, "name"):
                    c_name = evt.creature.name.lower()
            self._trigger_combat(c_name)

    def _search(self) -> None:
        """Search dungeon tile for fountains, marks, orbs, or chests."""
        from py_exodus.world.map import DungeonTile

        tile = self.state.current_tile
        fountains = (
            DungeonTile.FOUNTAIN_PLAIN,
            DungeonTile.FOUNTAIN_HEAL,
            DungeonTile.FOUNTAIN_ACID,
            DungeonTile.FOUNTAIN_CURE,
            DungeonTile.FOUNTAIN_POISON,
        )
        marks = (
            DungeonTile.MARK,
            DungeonTile.MARK_KINGS,
            DungeonTile.MARK_FIRE,
            DungeonTile.MARK_SNAKE,
            DungeonTile.MARK_FORCE,
        )

        if tile in fountains:
            prompt_msg = "You find a Fountain. Who drinks? (1-4): "
            action = self.state.drink_fountain
        elif tile in marks:
            prompt_msg = "You find a mystical Mark. Who touches? (1-4): "
            action = self.state.touch_mark
        elif tile == DungeonTile.ORB:
            prompt_msg = "You find a Magical Orb...Who touches? (1-4): "
            action = self.state.touch_orb
        elif tile == DungeonTile.CHEST:
            prompt_msg = "Who gets the chest? (1-4): "
            action = lambda idx: self.state.open_chest(idx, disarm=False)
        else:
            prompt_msg = "Who searches? (1-4): "
            action = None

        def _on_who(who_str: str) -> None:
            try:
                idx = int(who_str.strip()) - 1
            except ValueError:
                idx = 0

            if not (0 <= idx < len(self.party.members)):
                self.text_log.add_message("Invalid member #!")
                return

            if action is not None:
                evt = action(idx)
                self._process_event(evt)
            else:
                self.text_log.add_message("Search: Thou searchest the damp corridor... Nothing here!")

        self.text_log.prompt(prompt_msg, callback=_on_who, single_char=True)

    def _get_chest(self) -> None:
        """Open a treasure chest by direction-targeting the adjacent tile."""
        from py_exodus.world.map import DungeonTile

        def _on_dir(dir_str: str) -> None:
            direction = Direction.from_name_or_key(dir_str)
            if direction is None:
                self.text_log.add_message("Invalid direction!")
                return

            tx = self.state.x + direction.dx
            ty = self.state.y + direction.dy

            from py_exodus.world.chests import open_chest

            if self.dungeon_map.get_tile(tx, ty, self.state.z) != DungeonTile.CHEST:
                self.state._tick_turn()  # Java routes G through finishTurn
                self.text_log.add_message("Not Here!")
                return

            self.state._tick_turn()  # Java routes G through finishTurn

            def _on_who(who_str: str) -> None:
                try:
                    idx = int(who_str.strip()) - 1
                except ValueError:
                    idx = -1
                member = self.party.get_member(idx)
                if member is None:
                    self.text_log.add_message("Invalid member #!")
                    return

                self.dungeon_map.set_tile(tx, ty, self.state.z, DungeonTile.NOTHING)
                for line in open_chest(self.party, member, dungeon=True):
                    self.text_log.add_message(line)

            self.text_log.prompt("Who gets the chest? (1-4): ", callback=_on_who, single_char=True)

        self.text_log.prompt("Get: Direction? (N,S,E,W):", callback=_on_dir, single_char=True)

    def _trigger_combat(self, creature_name: str) -> None:
        """Launch combat screen from dungeon encounter."""
        if self.asset_mgr is None:
            return

        try:
            from py_exodus.screens.combat_screen import CombatScreen
            from py_exodus.world.loader import MapLoader

            loader = MapLoader(self.asset_mgr)
            # Brick floor combat map (map ID 35)
            c_map = loader.load_conflict_map("CNFLCT_B.ULT")
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

    def _use_torch(self) -> None:
        """Light a torch from party inventory."""
        if self.state.light_torch():
            self.text_log.add_message("Torch ignited! Corridors illuminate.")
            if self.audio is not None:
                self.audio.play_sfx("fire_field_walking")
        else:
            self.text_log.add_message("No torches left in inventory!")

    def _cast_spell(self) -> None:
        from py_exodus.combat.magic import prompt_cast_party
        prompt_cast_party(self.text_log, self.party, world_map=self.state, audio=self.audio)

    def update(self, dt: float) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)
        w, h = surface.get_width(), surface.get_height()
        scale = 3 if w >= 640 else 1
        v_size = 176 * scale

        if scale > 1:
            temp_v = pygame.Surface((176, 176))
            self.camera.render_wireframe(
                temp_v,
                dmap=self.state.dmap,
                x=self.state.x,
                y=self.state.y,
                z=self.state.z,
                dir=self.state.dir,
                torch_rounds=self.state.torch_rounds,
                light_spell=self.state.light_spell,
            )

            font = get_hud_font(size=10)
            status_line = f"LVL: {self.state.z + 1}  DIR: {self.state.dir.name}"
            stat_surf = font.render(status_line, True, EGA_YELLOW)
            temp_v.blit(stat_surf, (4, 4))

            if self.state.torch_rounds > 0 or self.state.light_spell:
                torch_line = f"TORCH: {self.state.torch_rounds}"
                torch_surf = font.render(torch_line, True, EGA_BRIGHT_GREEN)
                temp_v.blit(torch_surf, (4, 16))

            scaled_v = pygame.transform.scale(temp_v, (v_size, v_size))
            surface.blit(scaled_v, (0, 0))

            # Right Sidebar (Party Stats) at native high resolution
            self.stats_panel.render(
                surface,
                self.party,
                rect=pygame.Rect(v_size, 0, w - v_size, h),
            )

            # Bottom HUD Text Log at native resolution
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, v_size, v_size, h - v_size),
                draw_border=True,
            )
        else:
            self.camera.render_wireframe(
                surface,
                dmap=self.state.dmap,
                x=self.state.x,
                y=self.state.y,
                z=self.state.z,
                dir=self.state.dir,
                torch_rounds=self.state.torch_rounds,
                light_spell=self.state.light_spell,
            )

            font = get_hud_font(size=10)
            status_line = f"LVL: {self.state.z + 1}  DIR: {self.state.dir.name}"
            stat_surf = font.render(status_line, True, EGA_YELLOW)
            surface.blit(stat_surf, (4, 4))

            if self.state.torch_rounds > 0 or self.state.light_spell:
                torch_line = f"TORCH: {self.state.torch_rounds}"
                torch_surf = font.render(torch_line, True, EGA_BRIGHT_GREEN)
                surface.blit(torch_surf, (4, 16))

            self.stats_panel.render(
                surface,
                self.party,
                rect=pygame.Rect(176, 0, w - 176, h),
            )

            log_h = max(24, h - 176)
            self.text_log.render(
                surface,
                rect=pygame.Rect(0, 176, 176, log_h),
                draw_border=True,
            )
