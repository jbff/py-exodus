"""Start and title screen for Ultima III: Exodus."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_GREEN,
    EGA_BRIGHT_RED,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
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
            ("Return to the View", self._open_view),
        ]
        self.selected_idx = 0
        self.anim_time: float = 0.0

        # Title art (C64-style, assets/graphics/title)
        self.logo_image: pygame.Surface | None = None
        self.exodus_image: pygame.Surface | None = None
        self._load_visual_assets()

    def _load_visual_assets(self) -> None:
        """The C64-style title art: "Ultima III" and "pyExodus"."""
        if self.asset_mgr is None:
            return
        try:
            from py_exodus.assets import load_image_surface

            self.logo_image = load_image_surface(
                self.asset_mgr.resolve_path("graphics", "title", "ultima3.png"))
            self.exodus_image = load_image_surface(
                self.asset_mgr.resolve_path("graphics", "title", "pyexodus.png"))
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
        elif event.key in (pygame.K_4, pygame.K_r):  # LairWare MainMenu 'R'
            self.selected_idx = 3
            self._open_view()

    def update(self, dt: float) -> None:
        self.anim_time += dt

    CREDITS = (
        "Ultima III: Exodus \u00a9 1983 Richard Garriott / Origin Systems",
        "Java port gdx-exodus by Paul Antinori  \u00b7  Mac port by LairWare (Leon McNeill)",
    )

    def render(self, surface: pygame.Surface) -> None:
        w, h = surface.get_width(), surface.get_height()
        surface.fill(EGA_BLACK)
        k = w / 960.0
        px = lambda v: max(1, int(round(v * k)))  # noqa: E731

        def blit_pixel_art(img, times, y):
            """Whole-number nearest-neighbour scale: the art stays blocky."""
            n = max(1, round(times * k))
            sw, sh = img.get_width() * n, img.get_height() * n
            surface.blit(pygame.transform.scale(img, (sw, sh)), ((w - sw) // 2, y))
            return y + sh

        y = px(6)
        if self.logo_image is not None:
            y = blit_pixel_art(self.logo_image, 2, y) + px(4)
        if self.exodus_image is not None:
            y = blit_pixel_art(self.exodus_image, 3, y) + px(4)
        else:
            t = get_hud_font(size=px(48), font_name="ultima.ttf").render(
                "ULTIMA III: EXODUS", True, EGA_YELLOW)
            surface.blit(t, ((w - t.get_width()) // 2, y))
            y += t.get_height() + px(10)

        tag_font = get_hud_font(size=px(24), font_name="BarlowSemiCondensed-SemiBold.ttf")
        for line in ("From the depths of hell...", "...he comes for vengeance!"):
            t = tag_font.render(line, True, EGA_BRIGHT_RED)
            surface.blit(t, ((w - t.get_width()) // 2, y))
            y += t.get_height()
        y += px(10)

        menu_font = get_hud_font(size=px(24))
        # Game-over messaging when the whole party perished (Task 2 death flow).
        # Documented deviation: Java's start screen shows no game-over text.
        if self.game_over:
            turns = getattr(self.party, "moves", None)
            msg = (
                f"Thy party has perished! (Turn {turns})"
                if turns is not None
                else "Thy party has perished!"
            )
            t = menu_font.render(msg, True, EGA_BRIGHT_RED)
            surface.blit(t, ((w - t.get_width()) // 2, y))
            y += t.get_height() + px(6)

        for i, (label, _) in enumerate(self.options):
            sel = i == self.selected_idx
            t = menu_font.render(label, True, EGA_BRIGHT_GREEN if sel else EGA_LIGHT_GRAY)
            x = (w - t.get_width()) // 2
            surface.blit(t, (x, y))
            if sel:
                arrow = menu_font.render(">", True, EGA_BRIGHT_GREEN)
                surface.blit(arrow, (x - arrow.get_width() - px(10), y))
            y += t.get_height() + px(2)

        small = get_hud_font(size=px(14))
        lines = ["Arrows and Enter, or 1-4"] + list(self.CREDITS)
        yb = h - px(8) - len(lines) * small.get_linesize()
        for i, line in enumerate(lines):
            t = small.render(line, True, EGA_DARK_GRAY if i == 0 else EGA_LIGHT_GRAY)
            surface.blit(t, ((w - t.get_width()) // 2, yb + i * small.get_linesize()))

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
        world_state: dict[str, Any] | None = None
        try:
            from py_exodus.save_system import SaveSystem

            json_p = Path("saves/party.json")
            if json_p.exists():
                # Java reads the whole SaveGame record (party + per-map
                # objects/monsters, Context.java:138-193); the screen extras
                # (overworld/dungeon blocks) ride along in the same document.
                data = SaveSystem.load_game_data(json_p)
                party = Party.from_dict(data)
                world_state = data.get("overworld")
        except Exception:
            party = None

        # Java StartScreen.java:108-113: the record must exist and
        # players[0].name must be non-empty, else the party-management
        # (roster) screen opens. Also fall back when every member is dead so
        # Journey Onward never resumes a wiped save.
        if (
            party is None
            or not party.members
            or not party.members[0].name.strip()
            or party.is_party_dead()
        ):
            self._new_game()
            return

        self.party = party

        from py_exodus.screens.overworld import OverworldScreen

        # Java GameScreen.java:280-330 rebuilds the saved Sosaria objects and
        # monsters onto the map on load (GameScreen constructor, sg.* arrays).
        overworld = OverworldScreen(
            party=self.party,
            asset_mgr=self.asset_mgr,
            audio=self.audio,
            return_screen=self,
            manager=self.manager,
            world_state=world_state,
        )
        if self.manager is not None:
            self.manager.set_screen(overworld)
        else:
            self.next_screen = overworld
            self.is_finished = True

    def _new_game(self) -> None:
        """Open Roster and Party formation screen to select and assemble party."""
        from py_exodus.screens.roster_screen import RosterScreen

        active_party = (
            None
            if (
                self.game_over
                or (
                    self.party is not None
                    and self.party.members
                    and self.party.is_party_dead()
                )
            )
            else self.party
        )
        roster_scr = RosterScreen(
            party=active_party,
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

    def _open_view(self) -> None:
        """LairWare's 'R': the View (Demo()) until a key."""
        from py_exodus.screens.intro import IntroScreen

        view = IntroScreen(asset_mgr=self.asset_mgr, audio=self.audio, view_only=True)
        if self.manager is not None:
            self.manager.push_screen(view)
        else:
            self.next_screen = view
            self.is_finished = True

    def _open_book(self) -> None:
        """Open the Book of Lore (Java StartScreen.java:74)."""
        self.open_book()
