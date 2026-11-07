"""Tactical grid CombatScreen wrapping CombatArena for 11x11 battles."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.combat.arena import Action, ActionType, CombatArena
from py_exodus.constants import (
    BASE_HEIGHT,
    BASE_WIDTH,
    COMBAT_HEIGHT,
    COMBAT_WIDTH,
    TILE_SIZE,
    Direction,
    Spell,
)
from py_exodus.entities.party import PartyMember
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.renderer import WorldRenderer
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
    from py_exodus.world.map import ConflictMap


class CombatScreen(BaseScreen):
    """Interactive screen for 11x11 tactical turn-based combat encounters."""

    def __init__(
        self,
        party: Party,
        combat_map: ConflictMap,
        creature_tile: str = "orc",
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        return_screen: BaseScreen | None = None,
        monster_count: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.party = party
        self.combat_map = combat_map
        self.creature_tile = creature_tile
        self.asset_mgr = asset_mgr
        self.audio = audio

        self.arena = CombatArena(
            party=party,
            combat_map=combat_map,
            creature_tile=creature_tile,
            asset_mgr=asset_mgr,
            monster_count=monster_count,
        )

        self.world_renderer = (
            WorldRenderer(asset_mgr) if asset_mgr is not None else None
        )
        self.stats_panel = StatsPanel()
        self.text_log = TextLog(max_lines=5, wrap_width=28)

        # Seed initial combat message
        c_name = self.arena.creature_def.name
        self.text_log.add_message(f"Ambushed by {c_name}s!")
        for msg in self.arena.log_messages:
            self.text_log.add_message(msg)
        self.arena.log_messages.clear()

        self._pending_action_type: ActionType | None = None
        self.awaiting_exit_ack = False

    @property
    def active_party_member(self) -> PartyMember | None:
        """Return currently active party member taking turn in combat."""
        return self.party.get_member(self.arena.active_party_member_idx)

    def on_enter(self) -> None:
        super().on_enter()
        if self.audio is not None:
            self.audio.play_music("combat")

    def on_exit(self) -> None:
        super().on_exit()
        if self.audio is not None:
            self.audio.stop_music()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        # If waiting for prompt input (e.g. Direction or Spell code)
        if self.text_log.is_waiting_for_input:
            self.text_log.handle_event(event)
            return

        # If combat is finished, any key acknowledges and exits
        if self.arena.is_finished:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE):
                self.exit_screen()
            return

        # Standard combat keys
        active_member = self.active_party_member
        if active_member is None:
            return

        # Movement keys
        if event.key in (pygame.K_UP, pygame.K_w):
            self._execute_action(Action.move(Direction.NORTH))
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self._execute_action(Action.move(Direction.SOUTH))
        elif event.key in (pygame.K_LEFT, pygame.K_a):
            self._execute_action(Action.move(Direction.WEST))
        elif event.key in (pygame.K_RIGHT, pygame.K_d):
            self._execute_action(Action.move(Direction.EAST))
        elif event.key in (pygame.K_SPACE, pygame.K_p):
            self._execute_action(Action.pass_turn())
        elif event.key == pygame.K_f:
            self._execute_action(Action(ActionType.FLEE, direction=Direction.SOUTH))
        elif event.key == pygame.K_k:  # Attack command
            self._prompt_attack()
        elif event.key == pygame.K_c:  # Cast command
            self._prompt_cast()

    def _prompt_attack(self) -> None:
        """Prompt active member for attack direction."""
        active = self.active_party_member
        if not active:
            return

        def _on_dir(d_str: str) -> None:
            d = Direction.from_name_or_key(d_str)
            if d is None:
                self.text_log.add_message("Invalid direction!")
                return
            self._execute_action(Action.attack(d))

        self.text_log.prompt("Direction? (N,S,E,W):", callback=_on_dir)

    def _prompt_cast(self) -> None:
        """Prompt active member for spell letter code."""
        active = self.active_party_member
        if not active:
            return

        def _on_spell(code: str) -> None:
            code_upper = code.strip().upper()
            found_spell = None
            for s in Spell:
                if s.code == code_upper:
                    found_spell = s
                    break

            if found_spell is None:
                self.text_log.add_message("Unknown spell!")
                return
            self._execute_action(Action.cast(found_spell))

        self.text_log.prompt("Spell? (A-P):", callback=_on_spell)

    def _execute_action(self, action: Action) -> None:
        """Execute action in CombatArena, update audio, and sync logs."""
        result = self.arena.execute_turn(action)

        # Sync arena log messages to HUD
        for msg in self.arena.log_messages:
            self.text_log.add_message(msg)
        self.arena.log_messages.clear()

        # Play audio effects
        if self.audio is not None:
            if action.type == ActionType.ATTACK:
                self.audio.play_sfx("pc_attack")
            elif action.type == ActionType.CAST:
                self.audio.play_sfx("magic")
            elif action.type == ActionType.MOVE:
                self.audio.play_sfx("walk_normal")

        # Check end states
        if self.arena.is_finished:
            if self.arena.is_victory:
                self.text_log.add_message("VICTORY! All foes slain.")
                self.text_log.add_message("Press Enter to continue.")
                if self.audio is not None:
                    self.audio.play_sfx("Fanfare")
            elif self.arena.is_defeat:
                self.text_log.add_message("DEFEAT! Thy party has fallen.")
                self.text_log.add_message("Press Enter to continue.")
            elif self.arena.is_fled:
                self.text_log.add_message("Escaped from combat!")
                self.exit_screen()

    def update(self, dt: float) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(EGA_BLACK)

        # 1. Render 11x11 combat grid (176x176 at top-left 0, 0)
        if self.world_renderer is not None:
            self.world_renderer.render_viewport(
                surface,
                self.arena.combat_map,
                center_x=5,
                center_y=5,
                dest_pos=(0, 0),
            )
        else:
            self._render_grid_fallback(surface)

        # 2. Render Monsters
        self._render_monsters(surface)

        # 3. Render Players
        self._render_players(surface)

        # 4. Render Right Sidebar (Party Stats)
        self.stats_panel.render(
            surface,
            self.party,
            inspect_index=self.arena.active_party_member_idx,
            rect=pygame.Rect(176, 0, surface.get_width() - 176, surface.get_height()),
        )

        # 5. Render Bottom HUD Text Log
        log_h = max(24, surface.get_height() - 176)
        self.text_log.render(
            surface,
            rect=pygame.Rect(0, 176, 176, log_h),
            draw_border=True,
        )

    def _render_monsters(self, surface: pygame.Surface) -> None:
        font = get_hud_font(size=12)
        for m in self.arena.monsters:
            if m.is_dead:
                continue
            px = m.x * TILE_SIZE
            py = m.y * TILE_SIZE
            # Attempt tile blit if asset_mgr available
            blitted = False
            if self.asset_mgr is not None:
                try:
                    t_img = self.asset_mgr.get_tile_surface(m.tile)
                    if t_img is not None:
                        surface.blit(t_img, (px, py))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                rect = pygame.Rect(px + 1, py + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, EGA_BRIGHT_RED, rect)
                txt = font.render(m.name[:1], True, EGA_WHITE)
                surface.blit(txt, (px + 3, py + 1))

    def _render_players(self, surface: pygame.Surface) -> None:
        font = get_hud_font(size=12)
        for p_idx, (px, py) in self.arena.player_positions.items():
            screen_x = px * TILE_SIZE
            screen_y = py * TILE_SIZE
            is_active = (p_idx == self.arena.active_party_member_idx)

            blitted = False
            member = self.party.get_member(p_idx)
            if self.asset_mgr is not None and member is not None:
                try:
                    t_name = getattr(member.profession, "tile", "fighter")
                    t_img = self.asset_mgr.get_tile_surface(t_name)
                    if t_img is not None:
                        surface.blit(t_img, (screen_x, screen_y))
                        blitted = True
                except Exception:
                    pass

            if not blitted:
                color = EGA_BRIGHT_GREEN if is_active else EGA_BRIGHT_CYAN
                rect = pygame.Rect(screen_x + 1, screen_y + 1, TILE_SIZE - 2, TILE_SIZE - 2)
                pygame.draw.rect(surface, color, rect)
                char_label = str(p_idx + 1)
                txt = font.render(char_label, True, EGA_BLACK)
                surface.blit(txt, (screen_x + 4, screen_y + 1))

            # Highlight active member with yellow border
            if is_active:
                pygame.draw.rect(
                    surface,
                    EGA_YELLOW,
                    pygame.Rect(screen_x, screen_y, TILE_SIZE, TILE_SIZE),
                    1,
                )

    def _render_grid_fallback(self, surface: pygame.Surface) -> None:
        for y in range(COMBAT_HEIGHT):
            for x in range(COMBAT_WIDTH):
                rect = pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surface, EGA_DARK_GRAY, rect, 1)
