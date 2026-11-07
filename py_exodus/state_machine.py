"""Game state machine and screen transition manager for py-exodus."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.screens.base import BaseScreen

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager
    from py_exodus.entities.party import Party


class StateMachine:
    """Manages active screen, screen stack transitions, event routing, updates, and rendering."""

    def __init__(
        self,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        initial_screen: BaseScreen | None = None,
        party: Party | None = None,
        **kwargs: Any,
    ) -> None:
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.party = party
        self.screen_stack: list[BaseScreen] = []

        if initial_screen is not None:
            self.set_screen(initial_screen)
        else:
            # Default to StartScreen
            from py_exodus.screens.start import StartScreen

            start_screen = StartScreen(
                asset_mgr=self.asset_mgr,
                audio=self.audio,
                party=self.party,
                manager=self,
            )
            self.set_screen(start_screen)

    @property
    def current_screen(self) -> BaseScreen | None:
        """Return currently active screen on top of the stack."""
        if self.screen_stack:
            return self.screen_stack[-1]
        return None

    def set_screen(self, screen: BaseScreen) -> None:
        """Set active screen, replacing the current screen stack."""
        if self.current_screen is not None:
            self.current_screen.on_exit()

        screen.manager = self
        self.screen_stack = [screen]
        screen.on_enter()

    def push_screen(self, screen: BaseScreen) -> None:
        """Push a screen onto the stack (e.g. CombatScreen or ShrineScreen)."""
        if self.current_screen is not None:
            self.current_screen.on_exit()
            if screen.return_screen is None:
                screen.return_screen = self.current_screen

        screen.manager = self
        self.screen_stack.append(screen)
        screen.on_enter()

    def pop_screen(self) -> BaseScreen | None:
        """Pop the current screen and restore the previous screen on stack."""
        if len(self.screen_stack) > 1:
            popped = self.screen_stack.pop()
            popped.on_exit()

            top = self.screen_stack[-1]
            top.on_enter()
            return popped
        return None

    def handle_event(self, event: pygame.event.Event) -> None:
        """Route input event to active screen and process any triggered transitions."""
        cur = self.current_screen
        if cur is None:
            return

        cur.handle_event(event)
        self._check_screen_transition(cur)

    def update(self, dt: float) -> None:
        """Advance time-dependent logic on active screen and check transitions."""
        cur = self.current_screen
        if cur is None:
            return

        cur.update(dt)
        self._check_screen_transition(cur)

    def render(self, surface: pygame.Surface) -> None:
        """Render active screen contents onto target surface."""
        cur = self.current_screen
        if cur is not None:
            cur.render(surface)

    def _check_screen_transition(self, cur: BaseScreen) -> None:
        """Process screen completion or requested transition."""
        if not cur.is_finished:
            return

        if cur.next_screen is not None:
            next_scr = cur.next_screen
            cur.next_screen = None
            self.set_screen(next_scr)
        elif len(self.screen_stack) > 1:
            self.pop_screen()
        elif cur.return_screen is not None:
            ret_scr = cur.return_screen
            self.set_screen(ret_scr)
