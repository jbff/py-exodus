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

#: C64-style title art (assets/graphics/title, user 2026-11-23), 236x67 and
#: 204x45 pixels, in LairWare's EXODUS and Ultima-logo slots (same aspect).
TITLE_ART = "title/pyexodus.png"
ULTIMA_ART = "title/ultima3.png"
#: The cave ceiling over the duel, 304x17 pixels (3x in its slot at 960 wide).
STALACTITES_ART = "title/stalactites.png"

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


#: The duel's cast, left to right (LairWare's order), in strip units.
DUEL_PARTY = ("cleric", "wizard", "fighter", "thief")
DUEL_PARTY_X = (40, 72, 104, 136)
DUEL_DRAGON_X = 178
DUEL_TILE = 32  # a 16-px tile at 2x fills the 32-unit strip; 1 tile pixel = 2 units


def duel_sprites(shape: int) -> list[tuple[str, int, int, int]]:
    """(tile name, frame, x, y) for FightScene shapes 1-5 in the strip's
    255x32 units. Shapes 1-3 are the walk/swing cycle (animorder 0,1,2,3,2),
    4 the breath, 5 the dragon alone over the ashes."""
    out: list[tuple[str, int, int, int]] = []
    if shape in (1, 2, 3):
        step = (shape - 1) % 2
        out += [(name, step, x, 0) for name, x in zip(DUEL_PARTY, DUEL_PARTY_X)]
        out.append(("dragon", step, DUEL_DRAGON_X, 0))
    elif shape in (4, 5):
        out.append(("dragon", shape - 4, DUEL_DRAGON_X, 0))
    return out


def duel_flames(shape: int) -> list[tuple[int, int, int, int, int, bool]]:
    """(seed, x, y, width, height, embers) flame patches, x/y in strip units,
    width/height in tile pixels (2 units each)."""
    # No puff while the dragon walks (shape 1): it sat at his feet and read
    # as a stray flicker (user 2026-11-23); the tile has its own breath.
    if shape == 4:  # the breath over the whole party
        x0 = DUEL_PARTY_X[0] - 6
        return [(4, x0, 0, (DUEL_DRAGON_X - x0) // 2, 16, False)]
    if shape == 5:  # embers where each member stood
        return [(10 + i, x + 6, 26, 10, 3, True) for i, x in enumerate(DUEL_PARTY_X)]
    return []


#: EGA fire colours, hottest last.
_EMBER = ((85, 0, 0), (170, 0, 0), (255, 85, 85))
_FLAME = ((170, 0, 0), (255, 85, 85), (255, 255, 85), (255, 255, 255))


def flame_pixels(seed: int, width: int, height: int, embers: bool) -> pygame.Surface:
    """A blocky fire patch, one surface pixel per tile pixel: each column
    rises to a random height, hot at the core and red at the edges."""
    import random

    rng = random.Random(seed)
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    colours = _EMBER if embers else _FLAME
    for x in range(width):
        edge = min(x, width - 1 - x)
        top = rng.randint(0, max(0, height // 2 - min(edge, 3)))
        if not embers and edge == 0:
            top = max(top, height // 2)
        if embers and rng.random() < 0.35:
            continue
        for y in range(top, height):
            depth = (y - top) / max(1, height - top)
            heat = depth + rng.uniform(-0.25, 0.25) + (0.15 if edge > 2 else -0.2)
            level = max(0, min(len(colours) - 1, int(heat * len(colours))))
            surf.set_at((x, y), colours[level])
    return surf


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
        self._draws = 0

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
            if parts[0] != "title":  # our own title art; the rest is LairWare's
                parts.insert(0, "lairware")
            img = load_image_surface(self.asset_mgr.resolve_path("graphics", *parts))
            rgba = pygame.Surface(img.get_size(), pygame.SRCALPHA)
            rgba.blit(img, (0, 0))
            self._images[name] = rgba
        return self._images[name]

    #: The intro's copyright line: the game's left, the port's right (user
    #: 2026-11-23; was LairWare's baked "Origin Systems / Macintosh version"
    #: credits image). Ancestry and licences stay on the main menu.
    CREDITS = ("Ultima III \u00a9 1983 Lord British / Richard Garriott", "py-exodus \u00a9 2026")

    def _credits(self, rect: pygame.Rect) -> None:
        left, right = self.CREDITS
        size = max(8, round(rect.height * 0.7))
        while True:
            bold = get_hud_font(size=size, font_name="BarlowSemiCondensed-SemiBold.ttf")
            plain = get_hud_font(size=size, font_name="BarlowSemiCondensed-Medium.ttf")
            a = bold.render(left, True, (255, 255, 255))
            b = plain.render(right, True, (255, 255, 255))
            if a.get_width() + b.get_width() + rect.height <= rect.width or size <= 8:
                break
            size -= 1
        self.canvas.blit(a, (rect.x, rect.centery - a.get_height() // 2))
        self.canvas.blit(b, (rect.right - b.get_width(), rect.centery - b.get_height() // 2))

    def _scaled(self, name: str, size: tuple[int, int]) -> pygame.Surface:
        """The title art is C64-style pixel art: nearest-neighbour keeps it
        blocky (at 960 wide its slots are exactly 3x the art)."""
        scale = pygame.transform.scale if name.startswith("title/") else pygame.transform.smoothscale
        return scale(self._image(name), size)

    def _draw(self, name: str, rect: pygame.Rect) -> None:
        self.canvas.blit(self._scaled(name, rect.size), rect)

    # -- lifecycle --------------------------------------------------------

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
        self._crackle(False)  # a key during a dissolve cuts its noise
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
        """DrawIntro: a 255x32 strip at (192 + offset, 335) in 16-px units.

        LairWare blits one of five baked pictures. Here the strip is built
        from the active tile set (user 2026-11-23): the party and the dragon
        are 2x tiles (one tile fills the strip's height), shapes 1-3 swap
        their two frames, 4 is the dragon's breath, 5 the
        dragon over the embers. The fire is drawn as blocky EGA-coloured
        flames (flame_pixels), since no tile set has a usable fire wall."""
        if not 1 <= shape <= 5:
            return
        s = self._blk() / 16.0
        r = pygame.Rect(round((192 + offset) * s), 0, round(255 * s), round(32 * s))
        r.y = self._rect(0, 0, 1, 1).y + round(335 * s)
        # Clear the band the strip moves in. Its top overlaps the stalactites'
        # rect by a few pixels, so clear from the strip's own top and redraw
        # the stalactites under the sprites; clearing only below them left
        # the heads' top rows behind as a trail (user 2026-11-23).
        self.canvas.fill((0, 0, 0), (0, r.y, self.size[0], r.height))
        self._draw(STALACTITES_ART, self._rect(1, 19, 39, 21.125))
        px = round(DUEL_TILE * s)
        for name, frame, x, y in duel_sprites(shape):
            tile = self._duel_tile(name, frame)
            if tile is not None:
                img = pygame.transform.scale(tile, (px, px))
                self.canvas.blit(img, (r.x + round(x * s), r.y + round(y * s)))
        unit = 2 * s  # one tile pixel
        for seed, x, y, w, h, embers in duel_flames(shape):
            fire = flame_pixels(seed, w, h, embers)
            img = pygame.transform.scale(fire, (round(w * unit), round(h * unit)))
            self.canvas.blit(img, (r.x + round(x * s), r.y + round(y * s)))

    def _duel_tile(self, name: str, frame: int) -> pygame.Surface | None:
        if self.asset_mgr is None:
            return None
        try:
            return self.asset_mgr.get_tile_surface(name, frame)
        except KeyError:
            return None

    def _dissolve(self, name: str, rect: pygame.Rect, ticks: int, chunk: int) -> Iterator[float]:
        """FadeOnExodusUltima: each pass copies each chunk of the picture
        with chance (pass + 32767) / 65535, pass rising by 1536."""
        import numpy as np

        img = pygame.surfarray.array3d(self._scaled(name, rect.size))
        self._crackle(True)
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
        self._crackle(False)

    def _crackle(self, on: bool) -> None:
        """FadeOnExodusUltima's noise runs only while a picture dissolves in."""
        if self.audio is None:
            return
        self.audio.stop_music()
        if on:
            self.audio.play_music("title_fade", loops=0)

    def _intro(self) -> Iterator[float]:
        self.canvas.fill((0, 0, 0))
        self._draw(STALACTITES_ART, self._rect(1, 19, 39, 21.125))
        self._fighters(2, -25)
        yield 80
        yield from self._dissolve(TITLE_ART, self._rect(5.25, 1.25, 34.75, 9.625), 5, 8)
        yield 60
        yield from self._dissolve(ULTIMA_ART, self._rect(7.25, 9.9375, 32.75, 15.5625), 4, 4)
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
        self._credits(self._rect(1, 17.5625, 39, 19))
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
        self._draw(TITLE_ART, self._rect(5.25, 1.25, 34.75, 9.625))
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
                # Tile frames step every 3rd DrawDemo (12 ticks, 0.2 s), the
                # town/overworld pace; stepping every 4 ticks made the
                # daemons flap like they were about to fly away.
                self._draws += 1
                if self._draws % 3 == 0:
                    self.anim += 1
                self._draw_demo()
                yield 4  # DrawDemo idles until gTime + 4

    def _next_song(self) -> None:
        """DemoUpdate's jukebox: the next song once the last one has ended."""
        if self.audio is None or not getattr(self.audio, "enabled", False):
            return
        if not self.audio.music_busy():
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
