"""HUD Scrolling Text Log and Interactive Command/Dialogue Stream."""
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
        self.scroll_offset: int = 0

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

    def cancel_prompt(self) -> None:
        """Alias for handle_escape."""
        self.handle_escape()

    def submit_input(self, text: str) -> None:
        """Programmatically submit input text for the active prompt."""
        self.input_buffer = text
        self.handle_enter()

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Process a Pygame KEYDOWN event if waiting for prompt input."""
        if not self.is_waiting_for_input:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.handle_escape()
                return True

            # Direction prompt shortcut: arrow keys and keypad auto-commit direction
            if "dir" in self.current_prompt.lower():
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
            font_size = 18 if target_rect.height >= 60 else (14 if target_rect.height >= 36 else 13)
            f = get_hud_font(size=font_size)

        line_height = max(8, f.get_linesize())
        max_renderable = max(1, (target_rect.height - 4) // line_height)

        lines_to_draw: list[tuple[str, tuple[int, int, int]]] = []
        if self.is_waiting_for_input:
            cursor = "_" if cursor_visible else ""
            prompt_line = f"{self.current_prompt} {self.input_buffer}{cursor}"
            hist_count = max_renderable - 1
            visible_history = self.lines[-hist_count:] if hist_count > 0 else []
            lines_to_draw = [(line, text_color) for line in visible_history] + [
                (prompt_line, prompt_color)
            ]
        else:
            visible_history = self.lines[-max_renderable:]
            lines_to_draw = [(line, text_color) for line in visible_history]

        draw_x = target_rect.x + 4
        draw_y = target_rect.y + 2
        for idx, (text, col) in enumerate(lines_to_draw):
            line_surf = f.render(text, False, col)
            surface.blit(line_surf, (draw_x, draw_y + idx * line_height))
