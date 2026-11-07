"""Spellbook reference manual browser for py-exodus."""
from __future__ import annotations

from typing import Any

import pygame

from py_exodus.constants import Spell
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BROWN,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)


class BookScreen(BaseScreen):
    """Spellbook reference browser displaying Clerical Prayers and Wizard Sorceries.

    Lists all 16 spells per discipline with letter codes (A-P), spell names,
    MP costs, and full descriptions. Allows switching books and scrolling.
    """

    def __init__(
        self,
        return_screen: BaseScreen | None = None,
        book_type: str = "wizard",
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.current_book: str = book_type.lower()
        self.scroll_index: int = 0
        self.items_per_page: int = 8  # Show 8 spells at a time or 16 split into two columns

        # Cache spells by discipline
        self._wizard_spells = sorted(
            [s for s in Spell if s.spell_type == "wizard"],
            key=lambda s: s.code,
        )
        self._cleric_spells = sorted(
            [s for s in Spell if s.spell_type == "cleric"],
            key=lambda s: s.code,
        )

    def switch_book(self, book_type: str | None = None) -> None:
        """Switch between Wizard Sorceries and Clerical Prayers."""
        if book_type is not None:
            self.current_book = book_type.lower()
        else:
            self.current_book = "cleric" if self.current_book == "wizard" else "wizard"
        self.scroll_index = 0

    def get_spells(self) -> list[Spell]:
        """Return the list of 16 spells for the currently active book."""
        if self.current_book == "cleric":
            return self._cleric_spells
        return self._wizard_spells

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle book switching, page navigation, and exit."""
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_ESCAPE, pygame.K_q):
            self.exit_screen()
        elif event.key in (pygame.K_TAB, pygame.K_LEFT, pygame.K_RIGHT):
            self.switch_book()
        elif event.key == pygame.K_w:
            self.switch_book("wizard")
        elif event.key == pygame.K_c:
            self.switch_book("cleric")
        elif event.key in (pygame.K_DOWN, pygame.K_PAGEUP):
            self.scroll_index = min(len(self.get_spells()) - 1, self.scroll_index + 1)
        elif event.key in (pygame.K_UP, pygame.K_PAGEDOWN):
            self.scroll_index = max(0, self.scroll_index - 1)
        elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
            # Toggle between first 8 (A-H) and second 8 (I-P)
            self.scroll_index = 8 if self.scroll_index == 0 else 0

    def update(self, dt: float) -> None:
        """Advance time-based animations if needed."""

    def render(self, surface: pygame.Surface) -> None:
        """Draw the spellbook pages, title banner, spell entries, and navigation footer."""
        width = surface.get_width()
        height = surface.get_height()

        # Background parchment / dark frame
        surface.fill(EGA_BLACK)

        outer_rect = pygame.Rect(8, 8, width - 16, height - 16)
        pygame.draw.rect(surface, (24, 20, 16), outer_rect)
        pygame.draw.rect(surface, EGA_BROWN, outer_rect, 2)

        font = get_hud_font(16)
        small_font = get_hud_font(12)

        # Title
        if self.current_book == "cleric":
            title = "THE BOOK OF CLERICAL PRAYERS"
            tab_prompt = "[TAB] Switch to Wizard Sorceries"
            title_color = EGA_BRIGHT_CYAN
        else:
            title = "THE BOOK OF WIZARD SORCERIES"
            tab_prompt = "[TAB] Switch to Clerical Prayers"
            title_color = EGA_YELLOW

        title_surf = font.render(title, True, title_color)
        surface.blit(title_surf, (outer_rect.centerx - title_surf.get_width() // 2, 14))

        prompt_surf = small_font.render(tab_prompt, True, EGA_LIGHT_GRAY)
        surface.blit(prompt_surf, (outer_rect.centerx - prompt_surf.get_width() // 2, 34))

        pygame.draw.line(surface, EGA_DARK_GRAY, (16, 50), (width - 16, 50))

        # Render 16 spells in 2 columns of 8 or scrolling view
        spells = self.get_spells()
        y_start = 58
        line_height = 16

        # Column 1: A to H (indices 0 to 7)
        for i in range(8):
            if i < len(spells):
                s = spells[i]
                y = y_start + i * line_height
                code_text = f"{s.code}: {s.name:<11} ({s.mp_cost:>2} MP)"
                s_surf = small_font.render(code_text, True, EGA_WHITE)
                surface.blit(s_surf, (20, y))

                desc_surf = small_font.render(f"- {s.desc[:26]}", True, EGA_LIGHT_GRAY)
                surface.blit(desc_surf, (20, y + 8))

        # Column 2: I to P (indices 8 to 15)
        for i in range(8, 16):
            if i < len(spells):
                s = spells[i]
                y = y_start + (i - 8) * line_height
                code_text = f"{s.code}: {s.name:<11} ({s.mp_cost:>2} MP)"
                s_surf = small_font.render(code_text, True, EGA_WHITE)
                surface.blit(s_surf, (outer_rect.centerx + 8, y))

                desc_surf = small_font.render(f"- {s.desc[:26]}", True, EGA_LIGHT_GRAY)
                surface.blit(desc_surf, (outer_rect.centerx + 8, y + 8))

        # Footer
        footer_y = height - 26
        pygame.draw.line(surface, EGA_DARK_GRAY, (16, footer_y - 4), (width - 16, footer_y - 4))
        footer_text = "[TAB] Switch Book    [ESC / Q] Close"
        foot_surf = small_font.render(footer_text, True, EGA_BRIGHT_GREEN)
        surface.blit(foot_surf, (outer_rect.centerx - foot_surf.get_width() // 2, footer_y))
