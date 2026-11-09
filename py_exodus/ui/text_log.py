"""HUD Scrolling Text Log and Interactive Command/Dialogue Stream.

Scroll-back ruling (user bug 2026-11-09, reviewed against Java
``util/LogScrollPane`` — the original renders its log inside a vertical
ScrollPane). The port implements the equivalent affordance in the shared
``TextLog`` used by the overworld, town, dungeon and combat screens:

- PRIMARY: a viewport offset (``scroll_offset``) lets the player scroll UP
  through the full message history. The mouse wheel scrolls at any time;
  PageUp/PageDown always work; arrow keys scroll ONLY while the log is
  waiting on a prompt that cannot consume them (e.g. the single-letter
  vendor "Buy what?" prompt) — during a direction prompt the arrows are
  answers, not scroll keys, and while no prompt is waiting they remain
  avatar-command keys.
- While scrolled up (offset > 0), new arriving lines never yank the view
  back to the bottom (the offset pins the view in place); at offset 0 the
  view sticks to the bottom as messages arrive.
- Any key OTHER than a scroll key that gets consumed by an active prompt
  returns the view to the bottom FIRST, so an answer is never given
  against a scrolled-away view.
- No pagination pauses inside vendor prompts or dialogue streams: they
  would conflict with the letter-input prompt state. Scroll-back covers
  review instead.
- A small "▲ N" indicator is drawn in the log corner while the view is
  scrolled away from the bottom.

SECONDARY: when no font is supplied, the log picks its font size by
measured font metrics — the largest size that does not reduce the row
budget of the readable floor (size 10 / linesize 12). At the real scale-3
log strip (528x72 native) this is 5 readable rows where the old ladder
showed 3.
"""
from __future__ import annotations

import re
import textwrap
from collections.abc import Callable
from pathlib import Path

import pygame

# --- Classic EGA 16 Color Palette (RGB tuples) ---
EGA_BLACK = (0, 0, 0)
EGA_BLUE = (0, 0, 170)
EGA_GREEN = (0, 170, 0)
EGA_CYAN = (0, 170, 170)
EGA_RED = (170, 0, 0)
EGA_MAGENTA = (170, 0, 170)
EGA_BROWN = (170, 85, 0)
EGA_LIGHT_GRAY = (170, 170, 170)
EGA_DARK_GRAY = (85, 85, 85)
EGA_BRIGHT_BLUE = (85, 85, 255)
EGA_BRIGHT_GREEN = (85, 255, 85)
EGA_BRIGHT_CYAN = (85, 255, 255)
EGA_BRIGHT_RED = (255, 85, 85)
EGA_BRIGHT_MAGENTA = (255, 85, 255)
EGA_YELLOW = (255, 255, 85)
EGA_WHITE = (255, 255, 255)

_FONT_CACHE: dict[tuple[str | None, int], pygame.font.Font] = {}

_CANDIDATE_FONT_PATHS = [
    Path("src/main/resources/assets/fonts/gnuolane.ttf"),
    Path("assets/fonts/gnuolane.ttf"),
    Path("src/main/resources/assets/fonts/ultima.ttf"),
    Path("assets/fonts/ultima.ttf"),
    Path(__file__).parent.parent.parent / "src/main/resources/assets/fonts/gnuolane.ttf",
    Path(__file__).parent.parent.parent / "src/main/resources/assets/fonts/ultima.ttf",
]


def get_hud_font(size: int = 16, font_name: str | None = None) -> pygame.font.Font:
    """Retrieve or load cached TrueType/bitmap font with graceful fallback."""
    key = (font_name, size)
    if key in _FONT_CACHE:
        font_obj = _FONT_CACHE[key]
        try:
            # Check if font is still valid in case pygame.font.quit() was called
            font_obj.get_linesize()
            return font_obj
        except (pygame.error, Exception):
            _FONT_CACHE.pop(key, None)

    if not pygame.font.get_init():
        pygame.font.init()

    font_obj: pygame.font.Font | None = None

    # Preferred font search: default to gnuolane.ttf (the official LibGDX Exodus UI font)
    search_name = font_name if font_name not in (None, "default", "hud") else "gnuolane.ttf"

    for base in _CANDIDATE_FONT_PATHS:
        candidate = base.parent / search_name
        if candidate.exists():
            try:
                font_obj = pygame.font.Font(str(candidate), size)
                break
            except (pygame.error, OSError, RuntimeError):
                continue

    # Fallback to default font or system font
    if font_obj is None:
        try:
            font_obj = pygame.font.Font(None, size)
        except (pygame.error, OSError, RuntimeError):
            try:
                font_obj = pygame.font.SysFont("Courier, monospace", size)
            except (pygame.error, OSError, RuntimeError):
                font_obj = pygame.font.Font(None, size)

    _FONT_CACHE[key] = font_obj
    return font_obj


class TextLog:
    """Maintains scrolling HUD message history and interactive input prompt stream.

    Supports word-wrapping to viewport width, history buffering, backspace editing,
    cancellation, and sequential/nested prompts for vendor shopping and dialogues.
    """

    def __init__(
        self,
        max_lines: int = 5,
        wrap_width: int | None = None,
        font: pygame.font.Font | None = None,
    ) -> None:
        self.max_lines = max_lines
        self.wrap_width = wrap_width
        self._font = font

        self.lines: list[str] = []
        self.history: list[str] = []

        self.is_waiting_for_input: bool = False
        self.current_prompt: str = ""
        self.input_buffer: str = ""
        self.single_char: bool = False
        self._callback: Callable[[str], None] | None = None
        # Scroll-back viewport: 0 = stuck to the newest line; N = the window
        # ends N history lines above the newest (N grows as lines arrive so
        # a scrolled-up view stays pinned). See module docstring for the
        # scroll-back ruling.
        self.scroll_offset: int = 0
        # History row budget, refreshed by render(); scroll/page helpers use
        # it when no explicit row count is passed.
        self.visible_rows: int = 1
        # Font size chosen by the last render() (readable floor is 10).
        self.font_size: int = 13

    def add_message(self, msg: str) -> None:
        """Add a message to the scrolling log, wrapping text if wrap_width is set."""
        if not msg:
            self._append_line("")
            return

        # Split existing newlines first
        raw_lines = msg.split("\n")
        for raw in raw_lines:
            if self.wrap_width is not None and len(raw) > self.wrap_width:
                wrapped = textwrap.wrap(raw, width=self.wrap_width)
                if not wrapped:
                    wrapped = [""]
                for w in wrapped:
                    self._append_line(w)
            else:
                self._append_line(raw)

    def _append_line(self, line: str) -> None:
        """Internal helper to append line to history and visible scrolling lines."""
        self.history.append(line)
        self.lines.append(line)
        if len(self.lines) > self.max_lines:
            self.lines.pop(0)
        if self.scroll_offset:
            # A scrolled-up view stays pinned to the same history content;
            # only a bottom-stuck view (offset 0) rides along with arrivals.
            self.scroll_offset += 1

    # --- Scroll-back (Java LogScrollPane affordance; module docstring rules) ---

    def _snap_to_bottom(self) -> None:
        """Return the viewport to the newest line (offset 0)."""
        self.scroll_offset = 0

    def _window_offset(self, rows: int) -> int:
        """Effective offset for a window of `rows` history lines."""
        return min(self.scroll_offset, max(0, len(self.history) - rows))

    def visible_line_texts(self, rows: int | None = None) -> list[str]:
        """The history lines the current viewport shows for `rows` rows."""
        budget = self.visible_rows if rows is None else max(1, rows)
        end = len(self.history) - self._window_offset(budget)
        return list(self.history[max(0, end - budget):end])

    def scroll_up(self, lines: int = 1) -> bool:
        """Show older history lines. True when the viewport moved."""
        cap = max(0, len(self.history) - max(1, self.visible_rows))
        target = min(self.scroll_offset + max(1, lines), cap)
        if target == self.scroll_offset:
            return False
        self.scroll_offset = target
        return True

    def scroll_down(self, lines: int = 1) -> bool:
        """Move toward the newest lines. True when the viewport moved."""
        target = max(0, self.scroll_offset - max(1, lines))
        if target == self.scroll_offset:
            return False
        self.scroll_offset = target
        return True

    def page_up(self) -> bool:
        """Scroll back a full viewport of rows."""
        return self.scroll_up(max(1, self.visible_rows))

    def page_down(self) -> bool:
        """Scroll forward a full viewport of rows."""
        return self.scroll_down(max(1, self.visible_rows))

    def handle_wheel(self, event: pygame.event.Event) -> bool:
        """Process a MOUSEWHEEL event (mouse wheel scrolls at any time)."""
        if event.type != pygame.MOUSEWHEEL:
            return False
        delta = int(getattr(event, "y", 0))
        if delta > 0:
            return self.scroll_up(delta)
        if delta < 0:
            return self.scroll_down(-delta)
        return False

    def handle_scroll_key(self, key: int) -> bool:
        """PageUp/PageDown scroll-back in every state; True = key consumed."""
        if key == pygame.K_PAGEUP:
            self.page_up()
            return True
        if key == pygame.K_PAGEDOWN:
            self.page_down()
            return True
        return False

    def scroll_indicator_text(self) -> str:
        """Corner indicator while the viewport is scrolled off the bottom."""
        return f"▲ {self.scroll_offset}" if self.scroll_offset > 0 else ""

    def prompt(
        self,
        query: str,
        callback: Callable[[str], None] | None = None,
        single_char: bool | None = None,
    ) -> None:
        """Initiate an interactive prompt stream query (e.g. 'Direction?', 'Buy what?')."""
        self.is_waiting_for_input = True
        self.current_prompt = query
        self.input_buffer = ""
        self._callback = callback

        if single_char is not None:
            self.single_char = single_char
        else:
            q_lower = query.lower()
            if any(term in q_lower for term in ("name", "yell", "other command", "phrase")):
                self.single_char = False
            elif (
                re.search(r"\([a-z0-9]-[a-z0-9]\)", q_lower)
                or re.search(r"\[[a-z0-9]\]", q_lower)
                or any(
                    term in q_lower
                    for term in (
                        "direction",
                        "dir",
                        "n,s,e,w",
                        "which member",
                        "member #",
                        "choice",
                        "sex",
                        "race",
                        "class",
                        "w/c",
                        "y/n",
                    )
                )
            ):
                self.single_char = True
            else:
                self.single_char = False

    def handle_char(self, char: str) -> bool:
        """Process a single character input into the active prompt buffer."""
        if not self.is_waiting_for_input:
            return False

        if char == "\b":
            return self.handle_backspace()
        if char in ("\r", "\n"):
            self.handle_enter()
            return True

        if char.isprintable():
            # Consumed prompt keys always answer against the bottom-most view
            self._snap_to_bottom()
            self.input_buffer += char
            if self.single_char:
                self.handle_enter()
            return True

        return False

    def handle_backspace(self) -> bool:
        """Remove the trailing character from the active input buffer."""
        if not self.is_waiting_for_input:
            return False

        if self.input_buffer:
            self._snap_to_bottom()
            self.input_buffer = self.input_buffer[:-1]
            return True
        return False

    def handle_enter(self) -> None:
        """Commit the current input buffer, add to history, and fire callback."""
        if not self.is_waiting_for_input:
            return

        val = self.input_buffer
        prompt_str = self.current_prompt
        cb = self._callback

        # Reset prompt state first so subsequent prompts inside callback are preserved
        self.is_waiting_for_input = False
        self.current_prompt = ""
        self.input_buffer = ""
        self.single_char = False
        self._callback = None
        self._snap_to_bottom()

        # Add the completed prompt + input line to message log
        if prompt_str:
            if val:
                self.add_message(f"{prompt_str} {val}")
            else:
                self.add_message(prompt_str)

        # Trigger callback with captured input
        if cb is not None:
            cb(val)

    def handle_escape(self) -> None:
        """Cancel the active prompt without executing the callback."""
        if not self.is_waiting_for_input:
            return

        self.is_waiting_for_input = False
        self.current_prompt = ""
        self.input_buffer = ""
        self.single_char = False
        self._callback = None
        self._snap_to_bottom()

    def cancel_prompt(self) -> None:
        """Alias for handle_escape."""
        self.handle_escape()

    def submit_input(self, text: str) -> None:
        """Programmatically submit input text for the active prompt."""
        self.input_buffer = text
        self.handle_enter()

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Process a Pygame KEYDOWN/MOUSEWHEEL event for prompt input.

        Scroll keys (mouse wheel, PageUp/PageDown) work in every state; arrow
        keys scroll only while the waiting prompt cannot consume them. Any
        key consumed by the prompt returns the view to the bottom first.
        """
        # Mouse wheel scrolls history in any state (module docstring ruling)
        if self.handle_wheel(event):
            return True

        if event.type != pygame.KEYDOWN:
            return False

        # PageUp/PageDown always scroll-back, with or without an active prompt
        if event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            return self.handle_scroll_key(event.key)

        if not self.is_waiting_for_input:
            return False

        # Direction prompt shortcut: arrow keys and keypad auto-commit direction
        is_direction_prompt = any(
            k in self.current_prompt.lower() for k in ("dir", "n,s,e,w", "where")
        )
        if is_direction_prompt:
            if event.key in (pygame.K_UP, pygame.K_KP8):
                self.submit_input("NORTH")
                return True
            if event.key in (pygame.K_DOWN, pygame.K_KP2):
                self.submit_input("SOUTH")
                return True
            if event.key in (pygame.K_LEFT, pygame.K_KP4):
                self.submit_input("WEST")
                return True
            if event.key in (pygame.K_RIGHT, pygame.K_KP6):
                self.submit_input("EAST")
                return True
        elif event.key in (pygame.K_UP, pygame.K_DOWN):
            # The waiting prompt cannot consume the up/down arrows (it is a
            # single-letter/phrase vendor-style prompt), so they scroll.
            return self.scroll_up(1) if event.key == pygame.K_UP else self.scroll_down(1)

        # Consumed prompt keys (escape/enter/backspace/characters) each return
        # the viewport to the bottom inside their own handlers below, so an
        # answer is never given against a scrolled-away view.

        if event.key == pygame.K_ESCAPE:
            self.handle_escape()
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.handle_enter()
            return True
        if event.key == pygame.K_BACKSPACE:
            self.handle_backspace()
            return True

        u = getattr(event, "unicode", "")
        if u and u.isprintable():
            self.handle_char(u)
            return True

        return False

    def clear(self) -> None:
        """Clear visible lines and active prompt."""
        self.lines.clear()
        self.history.clear()
        self._snap_to_bottom()
        self.handle_escape()

    def render(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect | tuple[int, int, int, int] | None = None,
        font: pygame.font.Font | None = None,
        text_color: tuple[int, int, int] = EGA_WHITE,
        prompt_color: tuple[int, int, int] = EGA_YELLOW,
        bg_color: tuple[int, int, int] | None = EGA_BLACK,
        cursor_visible: bool = True,
        draw_border: bool = True,
    ) -> None:
        """Render scrolling message lines and active prompt to pygame surface."""
        w, h = surface.get_width(), surface.get_height()
        if rect is None:
            if w <= 320:
                target_rect = pygame.Rect(0, 150, 176, h - 150)
            else:
                scale = w / 320.0
                target_rect = pygame.Rect(
                    0,
                    int(150 * scale),
                    int(176 * scale),
                    h - int(150 * scale),
                )
        else:
            target_rect = pygame.Rect(rect)

        if bg_color is not None:
            surface.fill(bg_color, target_rect)

        if draw_border:
            pygame.draw.rect(surface, EGA_DARK_GRAY, target_rect, width=1)

        f = font or self._font
        if f is None:
            self.font_size = self._pick_font_size(target_rect.height)
            f = get_hud_font(size=self.font_size)

        line_height = max(8, f.get_linesize())
        max_renderable = max(1, (target_rect.height - 4) // line_height)
        self.visible_rows = max_renderable

        # Viewport window over the full history (scroll-back ruling: offset 0
        # shows the newest lines; offset N ends N lines above the newest;
        # while waiting the prompt keeps the last row pinned).
        rows_hist = max_renderable - 1 if self.is_waiting_for_input else max_renderable
        visible_history = self.visible_line_texts(rows_hist)

        lines_to_draw: list[tuple[str, tuple[int, int, int]]] = [
            (line, text_color) for line in visible_history
        ]
        if self.is_waiting_for_input:
            cursor = "_" if cursor_visible else ""
            prompt_line = f"{self.current_prompt} {self.input_buffer}{cursor}"
            lines_to_draw.append((prompt_line, prompt_color))

        draw_x = target_rect.x + 4
        draw_y = target_rect.y + 2
        for idx, (text, col) in enumerate(lines_to_draw):
            line_surf = f.render(text, False, col)
            surface.blit(line_surf, (draw_x, draw_y + idx * line_height))

        indicator = self.scroll_indicator_text()
        if indicator:
            ind_surf = f.render(indicator, False, EGA_YELLOW)
            surface.blit(
                ind_surf,
                (target_rect.right - ind_surf.get_width() - 3, target_rect.y + 2),
            )

    # Readable floor: size 10 / linesize 12 (the dungeon status font). Any
    # larger candidate font must not cost a single row of that budget.
    _MIN_FONT_SIZE = 10
    _FONT_SIZE_LADDER = (20, 18, 16, 14, 12, 10)

    @classmethod
    def _pick_font_size(cls, height: int) -> int:
        """Largest font size that leaves no readable row unused.

        Rows are measured with each candidate's real ``get_linesize()``
        against the usable height (rect minus the 2px frame padding on each
        edge). The size-10 floor fixes the row budget; a bigger font is only
        chosen when it still fits that same number of rows.
        """
        usable = max(1, height - 4)

        def rows_for(size: int) -> int:
            line_height = get_hud_font(size=size).get_linesize()
            return usable // max(1, line_height)

        budget = rows_for(cls._MIN_FONT_SIZE)
        for size in cls._FONT_SIZE_LADDER:
            if size < cls._MIN_FONT_SIZE:
                break
            if rows_for(size) >= budget:
                return size
        return cls._MIN_FONT_SIZE
