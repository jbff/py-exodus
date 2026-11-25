"""BaseScreen abstract interface for py-exodus screens."""
from __future__ import annotations

from abc import ABC
from typing import Any

import pygame


class BaseScreen(ABC):
    """Abstract base class for all game screens in py-exodus."""

    def __init__(
        self,
        return_screen: BaseScreen | None = None,
        manager: Any | None = None,
        **kwargs: Any,
    ) -> None:
        self.return_screen: BaseScreen | None = return_screen
        self.next_screen: BaseScreen | None = None
        self.manager: Any | None = manager
        self.is_finished: bool = False
        self.is_active: bool = True

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle an incoming pygame input event."""

    def update(self, dt: float) -> None:
        """Advance time-dependent animations, timers, and game logic."""

    def render(self, surface: pygame.Surface) -> None:
        """Draw the screen contents onto the target display surface."""

    def exit_screen(self) -> None:
        """Mark screen as finished and schedule return to previous screen."""
        self.is_finished = True
        self.is_active = False
        self.next_screen = self.return_screen

    def check_party_death(self) -> bool:
        """Route a fully-dead party to the StartScreen game over.

        Java truth: ``exodus/GameScreen.java:433-446`` — when combat ends (or
        a ``PartyDeathException`` from ``Party.java:556-577`` surfaces),
        ``partyDeath()`` sets the start screen without reviving anyone.

        This is the single screening entry point for the Task 2 death flow:
        call it immediately after any damage application (tile effects,
        starvation, chest traps, monster attacks, spells — including damage
        applied through the ``chests`` pipeline, which never raises itself)
        and return early when it returns True. Returns True when the party
        is dead and the game-over transition was scheduled.
        """
        party = getattr(self, "party", None)
        if party is None or not party.is_party_dead():
            return False

        # LairWare CheckAllDead (UltimaMain.c:2798-2810): "ALL PLAYERS
        # OUT!", then classic AutoSave writes the dead party before the
        # game-over alert (user ruling 2026-11-25).
        run_hook = getattr(party, "run_autosave_hook", None)
        if callable(run_hook):
            run_hook()

        if getattr(self.manager, "autoplay_enabled", False):
            self.manager.autoplay_enabled = False
            text_log = getattr(self, "text_log", None)
            if text_log is not None:
                text_log.add_message(
                    f"PARTY DEAD on turn {party.moves}! Autoplay stopped."
                )
            return True

        self.return_to_title(game_over=True)
        return True

    def return_to_title(self, game_over: bool = False, won: bool = False) -> BaseScreen:
        """End the game: the title screen replaces every screen.

        Shared by the dead party's game over (``check_party_death``) and the
        victory ending (user ruling 2026-11-25: the game ends when Exodus
        falls, as the 8-bit originals did). ``game_over`` shows the
        perished line; the ending passes ``won``. The title keeps the party
        only so autoplay and the trace can tell how the game ended: after
        either end it never hands it on (``StartScreen._new_game``).
        """
        from py_exodus.screens.start import StartScreen

        start_screen = StartScreen(
            asset_mgr=getattr(self, "asset_mgr", None),
            audio=getattr(self, "audio", None),
            party=getattr(self, "party", None),
            manager=self.manager,
            game_over=game_over,
            won=won,
        )
        if self.manager is not None:
            self.manager.set_screen(start_screen)
        else:
            self.is_finished = True
            self.is_active = False
            self.next_screen = start_screen
        return start_screen

    def on_enter(self) -> None:
        """Hook called when screen becomes the active screen."""
        self.is_active = True
        self.is_finished = False

    def _render_stats_panel(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
    ) -> None:
        """Render the sidebar StatsPanel with autoplay, auto-combat, location, and turn count."""
        from py_exodus.assets import MAP_ID_TO_LABEL

        autoplay_on = bool(getattr(self.manager, "autoplay_enabled", False))
        autocombat_on = (
            autoplay_on
            or bool(getattr(self, "auto_combat", False))
            or bool(getattr(self.manager, "auto_combat_enabled", False))
        )
        step_interval = (
            getattr(self.manager, "autoplay_step_interval", None)
            if autoplay_on
            else None
        )
        map_id = getattr(self, "map_id", getattr(self.party, "map_id", 0))
        label = MAP_ID_TO_LABEL.get(map_id) or f"Map {map_id}"
        if hasattr(self, "state") and hasattr(self.state, "z"):
            location_text = f"{label} L{self.state.z + 1} ({self.state.x},{self.state.y})"
        elif hasattr(self, "avatar_x"):
            location_text = f"{label} ({self.avatar_x},{self.avatar_y})"
        else:
            location_text = f"{label} ({self.party.x},{self.party.y})"
        self.stats_panel.render(
            surface,
            self.party,
            rect=rect,
            autoplay=autoplay_on,
            auto_combat=autocombat_on,
            step_interval=step_interval,
            location_text=location_text,
        )

    def on_exit(self) -> None:
        """Hook called when screen transitions away."""
        self.is_active = False

    def open_book(self) -> Any:
        """Open the Book of Lore over this screen.

        Java truth: ``exodus/BaseScreen.java:86-97`` — ``addButtons()`` mounts
        a Book button on every screen; ``exodus/StartScreen.java:74`` does the
        same on the title screen. The port reuses the shared spell-button
        screen-mounting pattern (F1 anywhere plus the title menu entry).
        """
        from py_exodus.screens.book import BookScreen

        book = BookScreen(
            return_screen=self,
            manager=self.manager,
            asset_mgr=getattr(self, "asset_mgr", None),
        )
        if self.manager is not None:
            self.manager.push_screen(book)
        else:
            self.next_screen = book
            self.is_finished = True
        return book
