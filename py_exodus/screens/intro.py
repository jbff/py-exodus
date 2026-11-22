"""LairWare's opening: Intro() and the View (Demo()).

Intro (UltimaMain.c:266): the stalactites, EXODUS and the "Ultima III" logo
dissolving in (FadeOnExodusUltima), "by Lord British" written stroke by
stroke from the SGNT data (WriteLordBritish), the credits, the duel
(FightScene) and "PRESS <SPACE>". Any key skips the rest of the intro.

The View (UltimaMain.c:282, UltimaGraphics.c:711-946): EXODUS and
"ULTIMA III" over a 19x6 strip of Sosaria played by the 512-step DEMO
script, cycling the songs, until a key. Then the main menu.

LairWare draws on a 40x24 grid of blocks; here a block is 1/40 of the
screen width, with the grid centred vertically. Timings are in LairWare
ticks (1/60 s).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Iterator

import pygame

from py_exodus.screens.base import BaseScreen
from py_exodus.ui.text_log import get_hud_font

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.audio import AudioManager

TICK = 1 / 60.0
DEMO_COLS, DEMO_ROWS = 19, 6
# The View's songs (DemoUpdate songnum, as our soundtrack names them).
VIEW_SONGS = ("wander", "towns", "castles", "dungeon", "combat", "shopping",
              "alive", "exodus", "rule britannia", "fanfare")
# FightScene's frame order (animorder) and its three passes.
_ANIM_ORDER = (0, 1, 2, 3, 2)


def fight_frames() -> list[tuple[int, int]]:
    """FightScene (UltimaGraphics.c:1220): (shape, x offset) per 8-tick frame."""
    out: list[tuple[int, int]] = []
    anim = 1
    for x in range(-25, 25, 2):
        out.append((_ANIM_ORDER[anim], x))
        anim = anim + 1 if anim < 4 else 1
    for x in range(25, -25, -2):
        out.append((_ANIM_ORDER[anim], x))
        anim = anim - 1 if anim > 1 else 4
    for x in range(-25, 10, 2):
        out.append((_ANIM_ORDER[anim], x))
        anim = anim + 1 if anim < 4 else 1
    out += [(_ANIM_ORDER[anim], 10)] * 4
    return out


def signature_points(sig: list[int]) -> list[list[tuple[int, int]]]:
    """WriteLordBritish (UltimaGraphics.c:1124): the dots PlotSig paints,
    grouped per loop pass (each pass plots its point, then one step)."""
    steps = {0: (-1, -1), 1: (0, -1), 2: (1, -1), 3: (-1, 0),
             4: (1, 0), 5: (-1, 1), 6: (0, 1), 7: (1, 1)}
    passes: list[list[tuple[int, int]]] = []
    cx = cy = 0
    i = 0
    while i < len(sig):
        dots = [(cx * 2, cy * 2)]
        v = sig[i]
        i += 1
        if v in steps:
            dx, dy = steps[v]
            dots.append((cx * 2 + dx, cy * 2 + dy))
            cx, cy = cx + dx, cy + dy
        elif v == 8:
            cx = sig[i] - 256 if sig[i] > 127 else sig[i]
            cy = sig[i + 1] - 256 if sig[i + 1] > 127 else sig[i + 1]
            i += 2
        passes.append(dots)
        if v == 0xFF:
            break
    return passes


def load_intro_data(asset_mgr) -> dict[str, list[int]]:
    path = asset_mgr.resolve_path("data", "lairware_intro.json")
    return json.loads(path.read_text())


class IntroScreen(BaseScreen):
    """The intro then the View (``view_only`` starts at the View: the main
    menu's "Return to the View")."""

    def __init__(
        self,
        asset_mgr: AssetManager | None = None,
        audio: AudioManager | None = None,
        view_only: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.asset_mgr = asset_mgr
        self.audio = audio
        self.data = load_intro_data(asset_mgr)
        self.canvas: pygame.Surface | None = None
        self.size = (0, 0)
        self.wait = 0.0
        self.in_view = view_only
        self.done = False
        self._script: Iterator[float] | None = None
        self._images: dict[str, pygame.Surface] = {}
        # The View's state (GetDemoRsrc, DrawDemo).
        demo = self.data["DEMO"]
        self.tiles = list(demo[1024:1024 + DEMO_COLS * DEMO_ROWS])
        self.background = list(self.tiles)
        self.background[62] = 0  # "ship should be water"
        self.demo_ptr = 0
        self.frames_due = 0
        self.anim = 0
        self.song = 0

    # -- geometry ---------------------------------------------------------

    def _blk(self) -> float:
        return self.size[0] / 40.0

    def _rect(self, x0: float, y0: float, x1: float, y1: float) -> pygame.Rect:
        b = self._blk()
        oy = (self.size[1] - 24 * b) / 2
        return pygame.Rect(round(x0 * b), round(oy + y0 * b), round((x1 - x0) * b), round((y1 - y0) * b))

    def _image(self, name: str) -> pygame.Surface:
        if name not in self._images:
            from py_exodus.assets import load_image_surface

            parts = name.split("/")
            img = load_image_surface(self.asset_mgr.resolve_path("graphics", "lairware", *parts))
            rgba = pygame.Surface(img.get_size(), pygame.SRCALPHA)
            rgba.blit(img, (0, 0))
            self._images[name] = rgba
        return self._images[name]

    def _draw(self, name: str, rect: pygame.Rect) -> None:
        self.canvas.blit(pygame.transform.smoothscale(self._image(name), rect.size), rect)

    # -- lifecycle --------------------------------------------------------

    def on_enter(self) -> None:
        super().on_enter()
        if self.audio is not None and not self.in_view:
            self.audio.play_music("title_fade", loops=0)

    def _finish(self) -> None:
        self.done = True
        if self.audio is not None:
            self.audio.stop_music() if hasattr(self.audio, "stop_music") else None
        if self.manager is not None:
            self.manager.pop_screen()
        else:
            self.is_finished = True

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type not in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            return
        if self.in_view:
            self._finish()
        else:  # gInterrupt: the rest of the intro is skipped
            self._start_view()

    def _start_view(self) -> None:
        self.in_view = True
        self._script = None
        self.canvas = None
        self.wait = 0.0

    def update(self, dt: float) -> None:
        if self.done:
            return
        if self.manager is not None and getattr(self.manager, "autoplay_enabled", False):
            self._finish()
            return
        if self.canvas is None:
            return  # sized on the first render
        self.wait -= dt
        guard = 0
        while self.wait <= 0 and not self.done and guard < 2000:
            guard += 1
            step = self._next_step()
            if step is None:
                break
            self.wait += step * TICK

    def _next_step(self) -> float | None:
        if self._script is None:
            self._script = self._view() if self.in_view else self._intro()
        try:
            return next(self._script)
        except StopIteration:
            self._script = None
            if not self.in_view:
                self._start_view()
                return 0.0
            return None

    def render(self, surface: pygame.Surface) -> None:
        if self.canvas is None or self.canvas.get_size() != surface.get_size():
            self.size = surface.get_size()
            self.canvas = pygame.Surface(self.size)
            self.canvas.fill((0, 0, 0))
            self._script = None
        surface.blit(self.canvas, (0, 0))

    # -- the intro ----------------------------------------------------------

    def _fighters(self, shape: int, offset: int) -> None:
        """DrawIntro: a 255x32 strip at (192 + offset, 335) in 16-px units."""
        s = self._blk() / 16.0
        r = pygame.Rect(round((192 + offset) * s), 0, round(255 * s), round(32 * s))
        r.y = self._rect(0, 0, 1, 1).y + round(335 * s)
        if 1 <= shape <= 5:
            self.canvas.blit(pygame.transform.smoothscale(
                self._image(f"intro/opening_anim_{shape}.png"), r.size), r)

    def _dissolve(self, name: str, rect: pygame.Rect, ticks: int, chunk: int) -> Iterator[float]:
        """FadeOnExodusUltima: each pass copies each chunk of the picture
        with chance (pass + 32767) / 65535, pass rising by 1536."""
        import numpy as np

        img = pygame.surfarray.array3d(pygame.transform.smoothscale(self._image(name), rect.size))
        rng = np.random.default_rng()
        w, h = rect.size
        cw = (w + chunk - 1) // chunk
        p = -32767
        while p < 32768:
            keep = rng.integers(-32767, 32768, size=(cw, h)) < p
            mask = np.repeat(keep, chunk, axis=0)[:w]
            frame = np.where(mask[..., None], img, 0).astype(np.uint8)
            self.canvas.blit(pygame.surfarray.make_surface(frame), rect)
            yield ticks
            p += 1536
        self._draw(name, rect)

    def _intro(self) -> Iterator[float]:
        self.canvas.fill((0, 0, 0))
        self._draw("intro/stalagtites.png", self._rect(1, 19, 39, 21.125))
        self._fighters(2, -25)
        yield 80
        yield from self._dissolve("exodus.png", self._rect(5.25, 1.25, 34.75, 9.625), 5, 8)
        yield 60
        yield from self._dissolve("ultima_logo.png", self._rect(7.25, 9.9375, 32.75, 15.5625), 4, 4)
        yield 120
        self._draw("intro/by.png", self._rect(11.25, 15.75, 12.875, 17.1875))
        yield 10
        s = self._blk() / 16.0
        top = self._rect(0, 0, 1, 1).y
        dot = (max(1, round(self._blk() / 4)), max(1, round(self._blk() / 8)))
        for n, dots in enumerate(signature_points(self.data["SGNT"])):
            for x, y in dots:
                self.canvas.fill((255, 255, 255), (int((x + 244) * s), top + int((y + 253) * s), *dot))
            if n % 2:
                yield 1
        self._draw("intro/credits.png", self._rect(1, 17.5625, 39, 19))
        for shape, x in fight_frames():
            self._fighters(shape, x)
            yield 8
        if self.audio is not None:
            self.audio.play_sfx("Immolate.wav")
        self._fighters(4, 4)
        yield 30
        self._fighters(5, 22)
        font = get_hud_font(size=max(10, round(self._blk() * 0.9)), font_name="BarlowSemiCondensed-SemiBold.ttf")
        img = font.render("PRESS  <SPACE>", True, (255, 255, 255))
        r = self._rect(0, 23, 40, 24)
        self.canvas.blit(img, ((self.size[0] - img.get_width()) // 2, r.y))
        while True:  # WaitKeyMouse
            yield 60

    # -- the View -----------------------------------------------------------

    def _view(self) -> Iterator[float]:
        self.canvas.fill((0, 0, 0))
        self._draw("exodus.png", self._rect(5.25, 1.25, 34.75, 9.625))
        font = get_hud_font(size=max(10, round(self._blk() * 0.9)), font_name="BarlowSemiCondensed-SemiBold.ttf")
        img = font.render("ULTIMA III", True, (255, 255, 255))
        self.canvas.blit(img, ((self.size[0] - img.get_width()) // 2, self._rect(0, 10, 1, 11).y))
        self._draw_demo()
        demo = self.data["DEMO"]
        while True:
            self._next_song()
            where, what = demo[self.demo_ptr], demo[self.demo_ptr + 512]
            self.demo_ptr = (self.demo_ptr + 1) % 512
            if where != 255:
                self.tiles[where] = what
                repeat = 0 if what < 16 else 1
            else:
                repeat = what
            for _ in range(repeat * 4):
                self.anim += 1
                self._draw_demo()
                yield 4  # DrawDemo idles until gTime + 4

    def _next_song(self) -> None:
        if self.audio is None or not getattr(self.audio, "enabled", False):
            return
        try:
            busy = pygame.mixer.get_init() and pygame.mixer.music.get_busy()
        except pygame.error:
            return
        if not busy:
            self.audio.play_music(VIEW_SONGS[self.song % len(VIEW_SONGS)], loops=0)
            self.song += 1

    def _tile(self, value: int) -> pygame.Surface | None:
        index = value // 2
        if 64 <= index <= 67:  # LairWare's party-member art: the class tiles
            index -= 44
        try:
            name = self.asset_mgr.get_tile_by_index(index).name
            return self.asset_mgr.get_tile_surface(name, self.anim)
        except KeyError:
            return None

    def _draw_demo(self) -> None:
        """DrawDemo: a 19x6 strip of 2-block tiles from (1, 11)."""
        for i, value in enumerate(self.tiles):
            col, row = i % DEMO_COLS, i // DEMO_COLS
            r = self._rect(1 + 2 * col, 11 + 2 * row, 3 + 2 * col, 13 + 2 * row)
            bg = self.background[i]
            for v in ((bg, value) if bg != value else (value,)):
                t = self._tile(v)
                if t is not None:
                    self.canvas.blit(pygame.transform.scale(t, r.size), r)
