"""Book of Lore browser for py-exodus.

Java truth: ``exodus/BookScreen.java:53`` loads ``/assets/data/ultima3.txt``
and ``BookScreen.java:150-174`` splits it into pages on ``*break`` lines and
on per-column text overflow. ``exodus/BaseScreen.java:86-97`` mounts a Book
button on every screen, so this book is reachable from the title screen and
from each game screen (F1 here, plus the title-screen menu entry).

The spell reference (Clerical Prayers / Wizard Sorceries) is a Python-only
invention kept as an appendix, rendered after the lore text as pages of the
same book.
"""
from __future__ import annotations

import textwrap
from typing import Any

import pygame

from py_exodus.assets import AssetManager
from py_exodus.constants import Spell
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_GREEN,
    EGA_BROWN,
    EGA_DARK_GRAY,
    EGA_LIGHT_GRAY,
    EGA_YELLOW,
    get_hud_font,
)

#: Wrapped text columns per page. Java wraps each column Label at ~450px of
#: 460 with an 18px font (BookScreen.java:150-174); this port wraps to a
#: similar column count for the HUD font so wide lore lines stay intact.
PAGE_COLS = 60
#: Text rows per page, derived from the real measured font metrics of the
#: repo gnuolane.ttf (linesize ~= 1.2x the point size: 12px at size 10 on a
#: 320x200 surface, 36px at size 30 at the 3x game resolution):
#:   page text starts at y = TEXT_TOP * scale,
#:   footer rule top is at height - (FOOTER_INSET + FOOTER_RULE_GAP) * scale,
#:   rows that fit = floor(page_height / linesize):
#:     320x200: floor((176 - 44) / 12) = 11  ->  10 with a one-row safety
#:     960x600: floor((528 - 132) / 36) = 11 ->  10 with a one-row safety
#: so 10 lines fill the viewport between the header rule and the footer at
#: BOTH resolutions (at 3x each row is ~36px of HUD-scale text).
PAGE_ROWS = 10
#: Body font logical size (30px at the 3x game resolution, 10px on a raw
#: 320x200 surface). Measured linesize: 12 at 1x, 36 at 3x (gnuolane.ttf).
BOOK_FONT_SIZE = 10
#: Logical y of the first page text row (header rule 38 + 6 gap).
TEXT_TOP = 44
#: Logical footer inset (footer text y = height - FOOTER_INSET * scale).
FOOTER_INSET = 20
#: Logical gap between the footer rule and the footer text.
FOOTER_RULE_GAP = 4

LORE_TITLE = "THE BOOK OF LORE"
APPENDIX_HEADER = "APPENDIX: SPELL REFERENCE"


def _wrap_lines(text: str) -> list[str]:
    """Wrap every raw line of a section to PAGE_COLS, preserving blanks."""
    lines: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            lines.append("")
        else:
            lines.extend(textwrap.wrap(raw, PAGE_COLS) or [""])
    return lines


def _split_into_pages(lines: list[str]) -> list[str]:
    """Chunk wrapped lines into fixed-height page texts (Java overflow rule)."""
    return [
        "\n".join(lines[i : i + PAGE_ROWS]).rstrip("\n")
        for i in range(0, len(lines), PAGE_ROWS)
    ]


def _resolve_lore_path(asset_mgr: AssetManager | None) -> Any:
    """Locate data/ultima3.txt, Java BookScreen.java:53 classpath resource."""
    mgr = asset_mgr if asset_mgr is not None else AssetManager()
    return mgr.resolve_path("data", "ultima3.txt")


def load_lore_text(asset_mgr: AssetManager | None = None) -> str:
    """Return the raw Book of Lore text, or an empty string when missing."""
    try:
        return _resolve_lore_path(asset_mgr).read_text(encoding="utf-8")
    except OSError:
        # BookScreen.java prints the stack trace and shows an empty book
        return ""


def load_lore_sections(asset_mgr: AssetManager | None = None) -> list[str]:
    """Split the lore text into section texts on '*break' lines.

    Java BookScreen.java:158-162: a line starting with ``*break`` ends the
    current page/section; text otherwise accumulates until it overflows the
    column. Pages are wrapped and height-clamped by :func:`load_lore_pages`.
    """
    text = load_lore_text(asset_mgr)
    sections: list[str] = []
    chunk: list[str] = []
    for line in text.splitlines():
        if line.startswith("*break"):
            sections.append("\n".join(chunk))
            chunk = []
            continue
        chunk.append(line)
    if chunk:
        sections.append("\n".join(chunk))
    return [s for s in sections if s.strip()]


def load_lore_pages(asset_mgr: AssetManager | None = None) -> list[str]:
    """Split lore sections into fixed-height page texts."""
    pages: list[str] = []
    for section in load_lore_sections(asset_mgr):
        pages.extend(_split_into_pages(_wrap_lines(section)))
    return pages


def spell_reference_pages() -> list[str]:
    """Build the Python-only spell reference appendix page texts.

    Kept from the former spellbook browser: all 16 spells per discipline with
    letter codes, MP costs, and descriptions, appended after the lore text.
    """
    lines: list[str] = [APPENDIX_HEADER, ""]
    for discipline, label in (("wizard", "WIZARD SORCERIES"), ("cleric", "CLERICAL PRAYERS")):
        spells = sorted(
            (s for s in Spell if s.spell_type == discipline),
            key=lambda s: s.code,
        )
        lines.append(f"{label}")
        lines.append("")
        for s in spells:
            lines.append(f"{s.code}: {s.name} ({s.mp_cost:>2} MP)")
        lines.append("")
        for s in spells:
            lines.append(f"{s.code}: {s.desc}")
        lines.append("")
    return _split_into_pages(_wrap_lines("\n".join(lines)))


class BookScreen(BaseScreen):
    """Paged Book of Lore browser.

    Loads ``data/ultima3.txt`` (Java BookScreen.java:53), splits pages on
    ``*break`` markers and text overflow (Java BookScreen.java:150-174), and
    appends the Python-only spell reference as the last pages.
    """

    def __init__(
        self,
        return_screen: BaseScreen | None = None,
        asset_mgr: AssetManager | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.asset_mgr = asset_mgr
        self._appendix_pages: list[str] = spell_reference_pages()
        self.pages: list[str] = load_lore_pages(asset_mgr) + self._appendix_pages
        self.page_index: int = 0

    @property
    def page_count(self) -> int:
        """Total number of lore pages (deterministic given ultima3.txt)."""
        return len(self.pages)

    def turn_forward(self) -> None:
        """Advance one page, clamped at the last page."""
        if self.page_count:
            self.page_index = min(self.page_index + 1, self.page_count - 1)

    def turn_back(self) -> None:
        """Go back one page, clamped at the first page."""
        if self.page_count:
            self.page_index = max(self.page_index - 1, 0)

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle page navigation and exit."""
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_ESCAPE, pygame.K_q):
            self.exit_screen()
        elif event.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_RIGHT, pygame.K_DOWN, pygame.K_PAGEDOWN):
            self.turn_forward()
        elif event.key in (pygame.K_LEFT, pygame.K_UP, pygame.K_PAGEUP):
            self.turn_back()

    def update(self, dt: float) -> None:
        """Advance time-based animations if needed."""

    def render(self, surface: pygame.Surface) -> None:
        """Draw the paged lore text, title banner, and navigation footer.

        Layout is scale-proportional like the other screens: at 3x the page
        body font is physically as large as the rest of the HUD (BOOK_FONT_SIZE
        * 3 = 30px, linesize 36) and the PAGE_ROWS-page block fills the
        viewport between the header rule and the footer (see PAGE_ROWS for the
        measured fit math).
        """
        width = surface.get_width()
        height = surface.get_height()
        scale = 3 if width >= 640 else 1

        # Background parchment / dark frame
        surface.fill(EGA_BLACK)
        outer_rect = pygame.Rect(
            8 * scale, 8 * scale, width - 16 * scale, height - 16 * scale
        )
        pygame.draw.rect(surface, (24, 20, 16), outer_rect)
        pygame.draw.rect(surface, EGA_BROWN, outer_rect, 2 * scale)

        title_font = get_hud_font(14 * scale)
        body_font = get_hud_font(BOOK_FONT_SIZE * scale)
        info_font = get_hud_font(8 * scale)

        title_surf = title_font.render(LORE_TITLE, True, EGA_YELLOW)
        surface.blit(
            title_surf,
            (
                outer_rect.centerx - title_surf.get_width() // 2,
                10 * scale,
            ),
        )

        page = self.pages[self.page_index] if self.pages else "(The book is empty.)"
        page_info = f"PAGE {self.page_index + 1} OF {self.page_count}"
        page_surf = info_font.render(page_info, True, EGA_YELLOW)
        surface.blit(
            page_surf,
            (
                outer_rect.centerx - page_surf.get_width() // 2,
                28 * scale,
            ),
        )

        header_bottom = TEXT_TOP * scale - 6 * scale
        pygame.draw.line(
            surface,
            EGA_DARK_GRAY,
            (16 * scale, header_bottom),
            (width - 16 * scale, header_bottom),
        )

        footer_y = height - FOOTER_INSET * scale
        spacing = body_font.get_linesize()
        y = TEXT_TOP * scale
        for line in page.splitlines()[:PAGE_ROWS]:
            if line == APPENDIX_HEADER or line in ("WIZARD SORCERIES", "CLERICAL PRAYERS"):
                color = EGA_BRIGHT_GREEN
            else:
                color = EGA_LIGHT_GRAY
            line_surf = body_font.render(line, True, color)
            surface.blit(line_surf, (20 * scale, y))
            y += spacing

        pygame.draw.line(
            surface,
            EGA_DARK_GRAY,
            (16 * scale, footer_y - FOOTER_RULE_GAP * scale),
            (width - 16 * scale, footer_y - FOOTER_RULE_GAP * scale),
        )
        footer_text = "[SPACE/RETURN/UP/DOWN] Turn Page   [ESC] Close"
        foot_surf = info_font.render(footer_text, True, EGA_BRIGHT_GREEN)
        surface.blit(
            foot_surf,
            (
                outer_rect.centerx - foot_surf.get_width() // 2,
                footer_y,
            ),
        )
