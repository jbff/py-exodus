"""Start and title screen for Ultima III: Exodus."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager


class StartScreen(BaseScreen):
    """Title and main menu screen for py-exodus."""

    def __init__(
        self,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        party: Party | None = None,
        return_screen: BaseScreen | None = None,
        game_over: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.party = party
        # Task 2 death flow: True when routed here because the party perished
        self.game_over: bool = game_over

        self.options = [
            ("Journey Onward", self._start_journey),
            ("New Game / Roster", self._new_game),
            ("Book of Lore", self._open_book),
        ]
        self.selected_idx = 0
        self.anim_time: float = 0.0

        # Background surfaces
        self.bg_image: pygame.Surface | None = None
        self.border_image: pygame.Surface | None = None
        self._load_visual_assets()

    def _load_visual_assets(self) -> None:
        if self.asset_mgr is None:
            return
        try:
            from py_exodus.assets import load_image_surface

            demon_path = self.asset_mgr.resolve_path("graphics", "demon.png")
            if demon_path.exists():
                self.bg_image = load_image_surface(demon_path)
            border_path = self.asset_mgr.resolve_path("graphics", "splash_border.png")
            if border_path.exists():
                self.border_image = load_image_surface(border_path)
        except Exception:
            pass

    def on_enter(self) -> None:
        super().on_enter()
        if self.audio is not None:
            self.audio.play_music("title_fade")

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_UP, pygame.K_w):
            self.selected_idx = (self.selected_idx - 1) % len(self.options)
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
        elif event.key in (pygame.K_DOWN, pygame.K_s):
            self.selected_idx = (self.selected_idx + 1) % len(self.options)
            if self.audio is not None:
                self.audio.play_sfx("walk_normal")
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self.audio is not None:
                self.audio.play_sfx("trigger")
            self.options[self.selected_idx][1]()
        elif event.key in (pygame.K_1, pygame.K_j):
            self.selected_idx = 0
            self._start_journey()
        elif event.key in (pygame.K_2, pygame.K_m, pygame.K_n):
            self.selected_idx = 1
            self._new_game()
        elif event.key in (pygame.K_3, pygame.K_b):
            self.selected_idx = 2
            self._open_book()

    def update(self, dt: float) -> None:
        self.anim_time += dt

    def render(self, surface: pygame.Surface) -> None:
        w, h = surface.get_width(), surface.get_height()
        surface.fill(EGA_BLACK)

        # Draw decorative background if available
        if self.bg_image is not None:
            scaled_bg = pygame.transform.scale(self.bg_image, (w, h))
            surface.blit(scaled_bg, (0, 0))

        scale = 3 if w >= 640 else 1

        # Title banner
        title_font = get_hud_font(size=24 * scale, font_name="ultima.ttf")
        sub_font = get_hud_font(size=14 * scale)
        info_font = get_hud_font(size=11 * scale)

        title_surf = title_font.render("ULTIMA III: EXODUS", True, EGA_YELLOW)
        surface.blit(
            title_surf,
            ((w - title_surf.get_width()) // 2, 20 * scale),
        )

        sub_surf = sub_font.render("From the depths of hell... he comes!", True, EGA_BRIGHT_RED)
        surface.blit(
            sub_surf,
            ((w - sub_surf.get_width()) // 2, 50 * scale),
        )

        # Game-over messaging when the whole party perished (Task 2 death flow).
        # Documented deviation: Java's start screen shows no game-over text;
        # the label is kept for UI clarity (controller ruling, Task 2 fix round 1).
        if self.game_over:
            over_surf = sub_font.render("Thy party has perished!", True, EGA_BRIGHT_RED)
            surface.blit(over_surf, ((w - over_surf.get_width()) // 2, 70 * scale))

        # Menu options
        menu_y = 90 * scale
        for i, (label, _) in enumerate(self.options):
            is_sel = (i == self.selected_idx)
            color = EGA_BRIGHT_GREEN if is_sel else EGA_LIGHT_GRAY
            prefix = " > " if is_sel else "   "
            opt_surf = sub_font.render(f"{prefix}{label}", True, color)
            surface.blit(opt_surf, (80 * scale, menu_y + i * 26 * scale))

        # Footer
        footer = "Use Arrows/Enter or 1-3 to select"
        foot_surf = info_font.render(footer, True, EGA_DARK_GRAY)
        surface.blit(foot_surf, ((w - foot_surf.get_width()) // 2, h - 25 * scale))

    def _start_journey(self) -> None:
        """Begin or resume the adventure in the overworld.

        Java truth: ``exodus/StartScreen.java:100-117`` — Journey Onward
        ALWAYS reads the on-disk party save (Java party.sav; here
        saves/party.json), never screen-attached state (after ``partyDeath``
        that would be a dead party). party.sav missing, unreadable, or
        players[0] name empty → ManagePartyScreen (the roster screen). Java
        has no default party anywhere on this path.
        """
        party = None
        try:
            from py_exodus.save_system import SaveSystem

            json_p = Path("saves/party.json")
            if json_p.exists():
                party = SaveSystem.load_game(json_p)
        except Exception:
            party = None

        # Java StartScreen.java:108-113: the record must exist and
        # players[0].name must be non-empty, else the party-management
        # (roster) screen opens.
        if party is None or not party.members or not party.members[0].name.strip():
            self._new_game()
            return

        self.party = party

        from py_exodus.screens.overworld import OverworldScreen

        overworld = OverworldScreen(
            party=self.party,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=self,
            manager=self.manager,
        )
        if self.manager is not None:
            self.manager.set_screen(overworld)
        else:
            self.next_screen = overworld
            self.is_finished = True

    def _new_game(self) -> None:
        """Open Roster and Party formation screen to select and assemble party."""
        from py_exodus.screens.roster_screen import RosterScreen

        roster_scr = RosterScreen(
            party=self.party,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=self,
            manager=self.manager,
        )
        if self.manager is not None:
            self.manager.push_screen(roster_scr)
        else:
            self.next_screen = roster_scr
            self.is_finished = True

    def _open_book(self) -> None:
        """Open the Book of Lore (Java StartScreen.java:74)."""
        self.open_book()
