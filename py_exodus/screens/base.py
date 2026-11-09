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

        from py_exodus.screens.start import StartScreen

        start_screen = StartScreen(
            asset_mgr=getattr(self, "asset_mgr", None),
            audio=getattr(self, "audio", None),
            party=party,
            manager=self.manager,
            game_over=True,
        )
        if self.manager is not None:
            self.manager.set_screen(start_screen)
        else:
            self.is_finished = True
            self.is_active = False
            self.next_screen = start_screen
        return True

    def on_enter(self) -> None:
        """Hook called when screen becomes the active screen."""
        self.is_active = True
        self.is_finished = False

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
