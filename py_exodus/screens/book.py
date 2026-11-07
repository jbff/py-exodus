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
        elif event.key == pygame.K_TAB:
            self.switch_book()
        elif event.key == pygame.K_w:
            self.switch_book("wizard")
        elif event.key == pygame.K_c:
            self.switch_book("cleric")
        elif event.key in (pygame.K_DOWN, pygame.K_PAGEDOWN, pygame.K_RIGHT):
            self.scroll_index = 8
        elif event.key in (pygame.K_UP, pygame.K_PAGEUP, pygame.K_LEFT):
            self.scroll_index = 0
        elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
            # Toggle between page 1 (A-H) and page 2 (I-P)
            self.scroll_index = 8 if self.scroll_index < 8 else 0

    def update(self, dt: float) -> None:
        """Advance time-based animations if needed."""

    def render(self, surface: pygame.Surface) -> None:
        """Draw paginated spellbook, title banner, spell entries, and navigation footer."""
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
        surface.blit(title_surf, (outer_rect.centerx - title_surf.get_width() // 2, 10))

        prompt_surf = small_font.render(tab_prompt, True, EGA_LIGHT_GRAY)
        surface.blit(prompt_surf, (outer_rect.centerx - prompt_surf.get_width() // 2, 26))

        # Paginated spells (items_per_page = 8: Page 1 for A-H, Page 2 for I-P)
        spells = self.get_spells()
        page = 0 if self.scroll_index < 8 else 1
        start_idx = page * self.items_per_page
        page_spells = spells[start_idx : start_idx + self.items_per_page]

        page_info = f"PAGE {page + 1} OF 2  (Spells {page_spells[0].code} - {page_spells[-1].code})"
        page_surf = small_font.render(page_info, True, EGA_YELLOW)
        surface.blit(page_surf, (outer_rect.centerx - page_surf.get_width() // 2, 38))

        pygame.draw.line(surface, EGA_DARK_GRAY, (16, 50), (width - 16, 50))

        # Render 8 spells for current page with comfortable vertical spacing
        y_start = 54
        spacing = max(15, (height - 84) // self.items_per_page)

        for i, s in enumerate(page_spells):
            y = y_start + i * spacing
            code_text = f"{s.code}: {s.name:<11} ({s.mp_cost:>2} MP)"
            s_surf = small_font.render(code_text, True, EGA_WHITE)
            surface.blit(s_surf, (20, y))

            desc_text = f"- {s.desc}"
            desc_surf = small_font.render(desc_text, True, EGA_LIGHT_GRAY)
            surface.blit(desc_surf, (140, y))

        # Footer
        footer_y = height - 20
        pygame.draw.line(surface, EGA_DARK_GRAY, (16, footer_y - 4), (width - 16, footer_y - 4))
        footer_text = "[UP/DOWN/SPACE] Turn Page   [TAB] Switch Book   [ESC] Close"
        foot_surf = small_font.render(footer_text, True, EGA_BRIGHT_GREEN)
        surface.blit(foot_surf, (outer_rect.centerx - foot_surf.get_width() // 2, footer_y))
