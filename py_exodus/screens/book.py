"""Book of Lore browser for py-exodus.

Java truth: ``exodus/BookScreen.java:53`` loads ``/assets/data/ultima3.txt``
and ``exodus/BaseScreen.java:86-97`` mounts a Book button on every screen, so
this book is reachable from the title screen and from each game screen (F1
here, plus the title-screen menu entry).

The book is laid out as an open book: a contents page, then chapters split at
the lore's heading lines, each chapter starting on a new spread (left page).
Two more chapters close the book: the Python-only spell reference (letter,
name, MP, where castable, description) for each discipline, followed by the
rune and liturgy lore for those spells from the same text file. The text's
``*break`` markers no longer force pages; chapters do.

At 960x600 each view is a two-page spread. At 320x200 two pages would leave
about 28 characters per line in a 6-7px font, so each view is a single page
there (same chapters, same keys).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pygame

from py_exodus.assets import AssetManager
from py_exodus.constants import Spell
from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BRIGHT_CYAN,
    EGA_BRIGHT_GREEN,
    EGA_BROWN,
    EGA_WHITE,
    EGA_YELLOW,
    get_hud_font,
)

LORE_TITLE = "THE BOOK OF LORE"
CONTENTS_TITLE = "CONTENTS"

#: Lore heading lines (stripped) and the chapter each one opens. The heading
#: line itself is not shown: its chapter name heads the right-hand page.
CHAPTER_HEADINGS: dict[str, str] = {
    "EXODUS ULTIMA III COMMANDS": "Commands",
    "PY-EXODUS NAVIGATION & HOTKEYS": "Keys",
    "THE ADVENTURE": "The Adventure",
    "PREPARING FOR THY JOURNEY": "Preparing for thy Journey",
    "THROUGH THE GATEWAY": "Through the Gateway",
    "MAGIC": "Magic",
    "MOVEMENT": "Movement",
    "COMBAT": "Combat",
    "CHESTS": "Chests",
    "DUNGEONS": "Dungeons",
    "TRANSPORTATION": "Transportation",
    "LAST MINUTE COUNSEL": "Last Minute Counsel",
    "THE REALM OF SOSARIA": "The Realm of Sosaria",
    "CITIZENS": "Citizens",
    "MONSTERS - LAND": "Monsters of the Land",
    "MONSTERS - SEA": "Monsters of the Sea",
}
#: Title lines that open a chapter and stay in its text: the adventure's
#: title page, and the two spell books (whose chapters lead with the spell
#: reference table, see :func:`load_chapters`).
CHAPTER_OPENERS: dict[str, str] = {
    "Ultima III Exodus": "The Adventure",
    "The Book of": "Wizard Sorceries",
    "The Ancient Liturgy of Truth": "Clerical Prayers",
}
WIZARD_CHAPTER = "Wizard Sorceries"
CLERIC_CHAPTER = "Clerical Prayers"
#: Chapter keys, in contents order (1-9 then A-I).
CHAPTER_KEYS = "123456789ABCDEFGHI"
_CHAPTER_KEYCODES: dict[int, int] = {
    getattr(pygame, f"K_{ch.lower()}"): i for i, ch in enumerate(CHAPTER_KEYS)
}
# keypad digits work like the top-row digits
_CHAPTER_KEYCODES.update({getattr(pygame, f"K_KP{n}"): n - 1 for n in range(1, 10)})
#: Keys that return to the contents page.
_CONTENTS_KEYS = (pygame.K_0, pygame.K_KP0, pygame.K_HOME)

SPREAD_HINT = "Left/Right turn   Up/Down chapter   0 contents   Esc close"
CONTENTS_HINT = "1-9 / A-I or Up/Down choose   Enter open   Esc close"

#: Book colours (the approved mockup's palette).
PAGE_BG = (24, 20, 16)
RULE = (90, 80, 70)
BODY = (190, 190, 190)
DIM = (110, 110, 110)
HIGHLIGHT_BG = (60, 45, 20)
SPINE = EGA_BROWN

# USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
# always); availability refused at attempt - supersedes the Java
# getCastables letter compaction (Constants.java:751-762). The
# per-discipline ``s.code`` letters are FIXED (original-game alphabetical
# A-P per discipline), so the reference lists name + letter + MP + where.

#: Human-readable place words for the location bits (constants.MapType.mask;
#: the player-facing mirror of spell_menu._CONTEXT_MAPTYPES). A location
#: mask of 0xFF means every place.
_LOCATION_LABELS: tuple[tuple[int, str], ...] = (
    (0x01, "world"),
    (0x02, "combat"),
    (0x04, "town"),
    (0x08, "dungeon"),
    (0x10, "shrine"),
)
_LOCATION_ANYWHERE = "anywhere"

#: A list item's key: "A)", "Spacebar)", "Tab / F2)", "[ / ])" or a spell
#: reference row's "A -". Shown in cyan; such lines get no paragraph gap.
_KEY_RE = re.compile(r"^(?:[^(),]{1,24}\)|[A-P] -)(?= )")
#: Other list items that sit tight under each other.
_LIST_RE = re.compile(r"^(?:-- |\d+\. )")
#: A table row: cells separated by runs of two or more spaces.
_CELL_SPLIT = re.compile(r"\s{2,}")


def _location_phrase(spell: Spell) -> str:
    """Where a spell may be cast, from its location mask (Constants.java)."""
    if spell.location_mask == 0xFF:
        return _LOCATION_ANYWHERE
    if spell.location_mask == 0xFF & ~0x02:
        return "not in combat"
    places = [label for bit, label in _LOCATION_LABELS if spell.location_mask & bit]
    return "/".join(places)


# ---------------------------------------------------------------- text ---


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


def spell_reference_lines(discipline: str) -> list[str]:
    """The spell reference rows for one discipline ("wizard" or "cleric").

    All 16 spells with the FIXED letter (``s.code``), MP cost, where it may
    be cast and what it does, in enum order (each discipline's original-game
    alphabetical A-P; USER-DIRECTED RULING 2026-11-15: the letters never move
    with mana or context, and a spell the current place refuses prints
    "Not Here!" when attempted, per py_exodus/spell_menu.py).
    """
    return [
        f"{s.code} - {s.name} ({s.mp_cost} MP, {_location_phrase(s)}): {s.desc}"
        for s in Spell
        if s.spell_type == discipline
    ]


@dataclass
class Chapter:
    """One chapter of the book: its display name and raw source lines."""

    title: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def load_chapters(asset_mgr: AssetManager | None = None) -> list[Chapter]:
    """Split the lore into chapters at its heading lines.

    The 16 lore headings (:data:`CHAPTER_HEADINGS`) open the lore chapters;
    the spell books' title lines (:data:`CHAPTER_OPENERS`) open the two
    closing chapters, which lead with the spell reference rows. ``*break``
    lines read as blank lines.
    """
    chapters: list[Chapter] = []
    current: Chapter | None = None
    for raw in load_lore_text(asset_mgr).splitlines():
        line = raw.rstrip()
        key = line.strip()
        if key.startswith("*break"):
            line = key = ""  # a section break reads as a paragraph break
        if key in CHAPTER_HEADINGS:
            title = CHAPTER_HEADINGS[key]
            if current is None or current.title != title:
                current = Chapter(title)
                chapters.append(current)
            continue
        if key in CHAPTER_OPENERS:
            current = Chapter(CHAPTER_OPENERS[key])
            chapters.append(current)
        if current is None:
            current = Chapter(CHAPTER_HEADINGS["EXODUS ULTIMA III COMMANDS"])
            chapters.append(current)
        current.lines.append(line)

    by_title = {c.title: c for c in chapters}
    for title, discipline in ((WIZARD_CHAPTER, "wizard"), (CLERIC_CHAPTER, "cleric")):
        chapter = by_title.get(title)
        if chapter is None:
            chapter = Chapter(title)
            chapters.append(chapter)
        chapter.lines[:0] = spell_reference_lines(discipline) + [""]
    for chapter in chapters:
        while chapter.lines and not chapter.lines[0].strip():
            chapter.lines.pop(0)
        while chapter.lines and not chapter.lines[-1].strip():
            chapter.lines.pop()
    return [c for c in chapters if c.lines]


# -------------------------------------------------------------- layout ---


@dataclass(frozen=True)
class Row:
    """One laid-out row of a page.

    ``kind`` is "text" (``key`` drawn in cyan, then ``text``), "gap" (a
    half-line paragraph gap) or "cols" (``cells`` at ``col_x`` offsets).
    """

    kind: str
    text: str = ""
    key: str = ""
    style: str = "body"
    cells: tuple[str, ...] = ()
    col_x: tuple[int, ...] = ()

    @property
    def plain(self) -> str:
        if self.kind == "cols":
            return "  ".join(self.cells)
        return self.key + self.text


Page = list[Row]


def _line_style(line: str) -> str:
    """'title' for all-capitals lines (rune names, incantations, tables)."""
    letters = [c for c in line if c.isalpha()]
    if line.startswith("TABLE ") or (letters and not any(c.islower() for c in letters)):
        return "title"
    return "body"


def _break_word(word: str, font: pygame.font.Font, width: int) -> list[str]:
    """Hard-break a single word wider than the page (never expected)."""
    parts: list[str] = []
    piece = ""
    for ch in word:
        if piece and font.size(piece + ch)[0] > width:
            parts.append(piece)
            piece = ch
        else:
            piece += ch
    parts.append(piece)
    return parts


def wrap_text(text: str, font: pygame.font.Font, width: int) -> list[str]:
    """Greedy word wrap by measured pixel width with the real font."""
    out: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if font.size(candidate)[0] <= width:
            line = candidate
            continue
        if line:
            out.append(line)
        if font.size(word)[0] > width:
            *head, word = _break_word(word, font, width)
            out.extend(head)
        line = word
    if line:
        out.append(line)
    return out


def _table_block(lines: list[str], font: pygame.font.Font, width: int) -> list[Row] | None:
    """Lay out consecutive table rows as columns, or None if they don't fit."""
    rows = [tuple(_CELL_SPLIT.split(ln.strip())) for ln in lines]
    ncols = max(len(r) for r in rows)
    gap = font.size("    ")[0]
    widths = [
        max((font.size(r[i])[0] for r in rows if i < len(r)), default=0)
        for i in range(ncols)
    ]
    if sum(widths) + gap * (ncols - 1) > width:
        return None
    xs: list[int] = []
    x = 0
    for w in widths:
        xs.append(x)
        x += w + gap
    return [Row("cols", cells=r, col_x=tuple(xs[: len(r)])) for r in rows]


def _is_table_row(line: str) -> bool:
    return len(_CELL_SPLIT.split(line.strip())) >= 3


def layout_chapter(lines: list[str], font: pygame.font.Font, width: int) -> list[Row]:
    """Wrap a chapter's source lines into rows no wider than ``width``.

    Blank source lines become half-line gaps. Consecutive prose lines (the
    lore keeps one paragraph per line) also get a gap, except list items
    (``A) ...``, ``-- ...``, ``1. ...``) and runs of short lines (titles,
    signatures, tables), which sit tight.
    """
    rows: list[Row] = []
    prev_short = False
    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        if not raw:
            if rows and rows[-1].kind != "gap":
                rows.append(Row("gap"))
            prev_short = False
            i += 1
            continue

        if _is_table_row(raw):
            j = i
            while j < len(lines) and lines[j].strip() and _is_table_row(lines[j]):
                j += 1
            block = _table_block(lines[i:j], font, width)
            if block is not None:
                if rows and rows[-1].kind != "gap" and not prev_short:
                    rows.append(Row("gap"))
                rows.extend(block)
                prev_short = True
                i = j
                continue

        match = _KEY_RE.match(raw)
        key = match.group(0) if match else ""
        is_item = bool(key) or bool(_LIST_RE.match(raw))
        wrapped = wrap_text(raw, font, width)
        short = len(wrapped) == 1
        if rows and rows[-1].kind != "gap" and not is_item and not (short and prev_short):
            rows.append(Row("gap"))
        style = _line_style(raw)
        for n, text in enumerate(wrapped):
            if n == 0 and key and text.startswith(key):
                rows.append(Row("text", text=text[len(key):], key=key, style=style))
            else:
                rows.append(Row("text", text=text, style=style))
        prev_short = short
        i += 1
    while rows and rows[-1].kind == "gap":
        rows.pop()
    return rows


def paginate(rows: list[Row], line_height: int, page_height: int) -> list[Page]:
    """Fill pages by pixel height (a gap is half a line); no gap tops a page."""
    gap_height = line_height // 2
    pages: list[Page] = []
    page: Page = []
    used = 0
    for row in rows:
        height = gap_height if row.kind == "gap" else line_height
        if row.kind == "gap" and not page:
            continue
        if used + height > page_height and page:
            while page and page[-1].kind == "gap":
                page.pop()
            pages.append(page)
            page, used = [], 0
            if row.kind == "gap":
                continue
        page.append(row)
        used += height
    while page and page[-1].kind == "gap":
        page.pop()
    if page or not pages:
        pages.append(page)
    return pages


@dataclass
class View:
    """One screenful: the contents page (chapter -1) or a chapter's pages."""

    chapter: int
    pages: list[Page | None] = field(default_factory=list)
    numbers: list[int | None] = field(default_factory=list)


@dataclass
class BookLayout:
    """Geometry for one surface size, plus the book laid out to it."""

    width: int
    height: int
    pages_per_view: int
    body_size: int
    header_size: int
    small_size: int
    frame: pygame.Rect
    header_y: int
    body_top: int
    body_bottom: int
    footer_rule_y: int
    footer_y: int
    page_x: tuple[int, ...]
    page_width: int
    line_height: int = 0
    views: list[View] = field(default_factory=list)
    chapter_first_view: list[int] = field(default_factory=list)

    @classmethod
    def for_size(cls, width: int, height: int) -> "BookLayout":
        """Two-page spread at 960x600; a single page at 320x200."""
        if width >= 640:
            return cls(
                width=width,
                height=height,
                pages_per_view=2,
                body_size=18,
                header_size=24,
                small_size=16,
                frame=pygame.Rect(20, 16, width - 40, height - 32),
                header_y=30,
                body_top=72,
                body_bottom=height - 70,
                footer_rule_y=height - 62,
                footer_y=height - 52,
                page_x=(44, width // 2 + 40),
                page_width=width // 2 - 84,
            )
        return cls(
            width=width,
            height=height,
            pages_per_view=1,
            body_size=9,
            header_size=10,
            small_size=8,
            frame=pygame.Rect(4, 3, width - 8, height - 6),
            header_y=7,
            body_top=24,
            body_bottom=height - 22,
            footer_rule_y=height - 19,
            footer_y=height - 16,
            page_x=(12,),
            page_width=width - 24,
        )

    def build(self, chapters: list[Chapter]) -> None:
        """Lay out every chapter; each chapter starts on a new view."""
        font = get_hud_font(self.body_size)
        self.line_height = font.get_linesize()
        self.views = [View(chapter=-1)]
        self.chapter_first_view = []
        number = 0
        for ci, chapter in enumerate(chapters):
            pages: list[Page | None] = list(
                paginate(
                    layout_chapter(chapter.lines, font, self.page_width),
                    self.line_height,
                    self.body_bottom - self.body_top,
                )
            )
            while len(pages) % self.pages_per_view:
                pages.append(None)  # a blank page; the next chapter opens left
            self.chapter_first_view.append(len(self.views))
            for start in range(0, len(pages), self.pages_per_view):
                group = pages[start : start + self.pages_per_view]
                numbers: list[int | None] = []
                for page in group:
                    number += 1
                    numbers.append(number if page else None)
                self.views.append(View(chapter=ci, pages=group, numbers=numbers))

    def chapter_views(self, chapter: int) -> range:
        first = self.chapter_first_view[chapter]
        if chapter + 1 < len(self.chapter_first_view):
            return range(first, self.chapter_first_view[chapter + 1])
        return range(first, len(self.views))


# -------------------------------------------------------------- screen ---


class BookScreen(BaseScreen):
    """The Book of Lore as an open book with a contents page.

    Loads ``data/ultima3.txt`` (Java BookScreen.java:53), splits it into
    chapters at its headings, and closes with the two spell chapters.
    """

    def __init__(
        self,
        return_screen: BaseScreen | None = None,
        asset_mgr: AssetManager | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(return_screen=return_screen, **kwargs)
        self.asset_mgr = asset_mgr
        self.chapters: list[Chapter] = load_chapters(asset_mgr)
        #: 0 is the contents page; 1.. are chapter spreads (or pages).
        self.view_index: int = 0
        #: Highlighted chapter on the contents page.
        self.highlight: int = 0
        #: Built on first use for the surface size actually drawn to.
        self._layout: BookLayout | None = None

    # -- layout -------------------------------------------------------

    def _build_layout(self, width: int, height: int) -> BookLayout:
        layout = BookLayout.for_size(width, height)
        layout.build(self.chapters)
        return layout

    @property
    def layout(self) -> BookLayout:
        """The current layout; 960x600 until a surface has been drawn to."""
        if self._layout is None:
            self._layout = self._build_layout(960, 600)
        return self._layout

    def _ensure_layout(self, width: int, height: int) -> None:
        """Lay the book out for this surface size, keeping the place."""
        if self._layout is None:
            self._layout = self._build_layout(width, height)
            return
        if (self._layout.width, self._layout.height) == (width, height):
            return
        old = self._layout
        new = self._build_layout(width, height)
        chapter = self.current_chapter
        if chapter >= 0:
            page_in_chapter = (self.view_index - old.chapter_first_view[chapter]) * old.pages_per_view
            views = new.chapter_views(chapter)
            self.view_index = min(views.start + page_in_chapter // new.pages_per_view, views.stop - 1)
        self._layout = new

    # -- state --------------------------------------------------------

    @property
    def page_count(self) -> int:
        """Number of views: the contents page plus every spread."""
        return len(self.layout.views)

    @property
    def spread_count(self) -> int:
        return len(self.layout.views) - 1

    @property
    def on_contents(self) -> bool:
        return self.view_index == 0

    @property
    def current_chapter(self) -> int:
        """Chapter shown now, or -1 on the contents page."""
        return self.layout.views[self.view_index].chapter

    def open_chapter(self, chapter: int) -> None:
        if 0 <= chapter < len(self.chapters):
            self.view_index = self.layout.chapter_first_view[chapter]
            self.highlight = chapter

    def show_contents(self) -> None:
        if not self.on_contents:
            self.highlight = self.current_chapter
        self.view_index = 0

    def turn_forward(self) -> None:
        """Turn one spread on, clamped at the last."""
        self.view_index = min(self.view_index + 1, self.page_count - 1)

    def turn_back(self) -> None:
        """Turn one spread back; from the first spread back to contents."""
        self.view_index = max(self.view_index - 1, 0)

    def next_chapter(self) -> None:
        """Jump to the next chapter's start; nothing in the last chapter."""
        if self.current_chapter + 1 < len(self.chapters):
            self.open_chapter(self.current_chapter + 1)

    def previous_chapter(self) -> None:
        """Jump to the previous chapter's start; nothing in the first."""
        if self.current_chapter > 0:
            self.open_chapter(self.current_chapter - 1)

    # -- input --------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        """Turn pages, jump between chapters, use the contents, or close."""
        if event.type != pygame.KEYDOWN:
            return
        key = event.key
        if key in (pygame.K_ESCAPE, pygame.K_q, pygame.K_F1):
            self.exit_screen()
            return

        if self.on_contents:
            if key in _CHAPTER_KEYCODES:
                self.open_chapter(_CHAPTER_KEYCODES[key])
            elif key == pygame.K_UP:
                self.highlight = max(self.highlight - 1, 0)
            elif key == pygame.K_DOWN:
                self.highlight = min(self.highlight + 1, len(self.chapters) - 1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.open_chapter(self.highlight)
            elif key in (pygame.K_RIGHT, pygame.K_PAGEDOWN):
                self.turn_forward()
            return

        if key in _CONTENTS_KEYS:
            self.show_contents()
        elif key in _CHAPTER_KEYCODES:
            self.open_chapter(_CHAPTER_KEYCODES[key])
        elif key in (pygame.K_RIGHT, pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_PAGEDOWN):
            self.turn_forward()
        elif key in (pygame.K_LEFT, pygame.K_PAGEUP):
            self.turn_back()
        elif key == pygame.K_DOWN:
            self.next_chapter()
        elif key == pygame.K_UP:
            self.previous_chapter()

    def update(self, dt: float) -> None:
        """No animation."""

    # -- drawing ------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        """Draw the contents page or the current spread."""
        width, height = surface.get_width(), surface.get_height()
        self._ensure_layout(width, height)
        lay = self.layout
        surface.fill(EGA_BLACK)
        pygame.draw.rect(surface, PAGE_BG, lay.frame)
        pygame.draw.rect(surface, SPINE, lay.frame, 4 if lay.pages_per_view == 2 else 2)
        if self.on_contents:
            self._render_contents(surface)
        else:
            self._render_view(surface)

    def _render_heading_bar(self, surface: pygame.Surface, right_title: str) -> None:
        """Single-width header: book title left, ``right_title`` right."""
        lay = self.layout
        header = get_hud_font(lay.header_size + (2 if lay.pages_per_view == 2 else 0))
        x0, x1 = lay.page_x[0], lay.width - lay.page_x[0]
        surface.blit(header.render(LORE_TITLE, True, SPINE), (x0, lay.header_y))
        title = header.render(right_title, True, EGA_YELLOW)
        surface.blit(title, (x1 - title.get_width(), lay.header_y))
        rule_y = lay.header_y + header.get_linesize() + (4 if lay.pages_per_view == 2 else 1)
        pygame.draw.line(surface, RULE, (x0, rule_y), (x1, rule_y))

    def _render_footer_rule(self, surface: pygame.Surface) -> None:
        lay = self.layout
        x0, x1 = lay.page_x[0], lay.width - lay.page_x[0]
        pygame.draw.line(surface, RULE, (x0, lay.footer_rule_y), (x1, lay.footer_rule_y))

    def _render_contents(self, surface: pygame.Surface) -> None:
        lay = self.layout
        big = lay.pages_per_view == 2
        self._render_heading_bar(surface, CONTENTS_TITLE)
        font = get_hud_font(22 if big else 9)
        half = (len(self.chapters) + 1) // 2
        col_w = (lay.width - 2 * lay.page_x[0]) // 2
        pitch = 44 if big else 15
        top = 96 if big else 28
        key_w = 40 if big else 14
        for i, chapter in enumerate(self.chapters):
            col, row = divmod(i, half)
            x = lay.page_x[0] + (26 if big else 8) + col * col_w
            y = top + row * pitch
            selected = i == self.highlight
            if selected:
                pad = 12 if big else 4
                bar = pygame.Rect(x - pad, y - (6 if big else 2), col_w - (30 if big else 8), pitch - (6 if big else 2))
                pygame.draw.rect(surface, HIGHLIGHT_BG, bar)
            surface.blit(font.render(CHAPTER_KEYS[i], True, EGA_BRIGHT_CYAN), (x, y))
            colour = EGA_WHITE if selected else BODY
            surface.blit(font.render(chapter.title, True, colour), (x + key_w, y))
        self._render_footer_rule(surface)
        self._render_hint(surface, CONTENTS_HINT)

    def _render_hint(self, surface: pygame.Surface, hint: str, right_edge: int | None = None) -> None:
        lay = self.layout
        font = get_hud_font(lay.small_size)
        surf = font.render(hint, True, EGA_BRIGHT_GREEN)
        edge = right_edge if right_edge is not None else lay.width - lay.page_x[0]
        surface.blit(surf, (edge - surf.get_width(), lay.footer_y))

    def _render_view(self, surface: pygame.Surface) -> None:
        lay = self.layout
        view = lay.views[self.view_index]
        chapter_title = self.chapters[view.chapter].title
        body = get_hud_font(lay.body_size)
        small = get_hud_font(lay.small_size)

        if lay.pages_per_view == 2:
            spine_x = lay.width // 2
            pygame.draw.line(surface, SPINE, (spine_x, lay.frame.top + 8), (spine_x, lay.frame.bottom - 8), 2)
            header = get_hud_font(lay.header_size)
            for side, x0 in enumerate(lay.page_x):
                text, colour = (LORE_TITLE, SPINE) if side == 0 else (chapter_title.upper(), EGA_YELLOW)
                surf = header.render(text, True, colour)
                surface.blit(surf, (x0 + (lay.page_width - surf.get_width()) // 2, lay.header_y))
        else:
            self._render_heading_bar(surface, chapter_title.upper())
            self._render_footer_rule(surface)

        for side, page in enumerate(view.pages):
            x0 = lay.page_x[side]
            if page:
                self._render_page(surface, page, x0, body)
            number = view.numbers[side]
            if number is None:
                continue
            num = small.render(str(number), True, DIM)
            if side == 0:
                surface.blit(num, (x0, lay.footer_y))
            else:
                surface.blit(num, (x0 + lay.page_width - num.get_width(), lay.footer_y))

        if lay.pages_per_view == 2:
            right_x0 = lay.page_x[1]
            right_num_w = small.size("000")[0]
            self._render_hint(surface, SPREAD_HINT, right_x0 + lay.page_width - right_num_w - 12)
        else:
            self._render_hint(surface, SPREAD_HINT)

    def _render_page(self, surface: pygame.Surface, page: Page, x0: int, font: pygame.font.Font) -> None:
        lay = self.layout
        y = lay.body_top
        for row in page:
            if row.kind == "gap":
                y += lay.line_height // 2
                continue
            colour = EGA_WHITE if row.style == "title" else BODY
            if row.kind == "cols":
                for cell, dx in zip(row.cells, row.col_x):
                    surface.blit(font.render(cell, True, colour), (x0 + dx, y))
            else:
                x = x0
                if row.key:
                    key_surf = font.render(row.key, True, EGA_BRIGHT_CYAN)
                    surface.blit(key_surf, (x, y))
                    x += font.size(row.key)[0]
                if row.text:
                    surface.blit(font.render(row.text, True, colour), (x, y))
            y += lay.line_height
