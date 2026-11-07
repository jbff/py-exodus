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

    def on_enter(self) -> None:
        """Hook called when screen becomes the active screen."""
        self.is_active = True
        self.is_finished = False

    def on_exit(self) -> None:
        """Hook called when screen transitions away."""
        self.is_active = False
