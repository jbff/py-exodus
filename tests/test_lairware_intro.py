"""LairWare's opening (UltimaMain.c Intro/Demo): the intro, then the View,
then the main menu; "Return to the View" from the menu; skipped in headless
and autoplay runs."""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.screens import intro as intro_mod
from py_exodus.screens.intro import IntroScreen, fight_frames, load_intro_data, signature_points
from py_exodus.screens.start import StartScreen
from py_exodus.state_machine import StateMachine


@pytest.fixture
def am():
    pygame.init()
    a = AssetManager(assets_dir="assets")
    a.load_tiles()
    a.load_xml_definitions()
    return a


def _key(scr, key=pygame.K_SPACE):
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=" "))


def test_the_demo_and_signature_data_came_out_of_the_rsrc(am):
    data = load_intro_data(am)
    assert len(data["DEMO"]) == 1280 and len(data["SGNT"]) == 385
    assert data["SGNT"][-1] == 0xFF or 0xFF in data["SGNT"]


def test_signature_ends_at_ff_and_stays_on_screen(am):
    passes = signature_points(load_intro_data(am)["SGNT"])
    assert len(passes) > 100
    xs = [x for p in passes for x, _ in p]
    ys = [y for p in passes for _, y in p]
    # PlotSig adds (244, 253): the strokes land right of "by" (UltimaGraphics.c:1209)
    assert -244 < min(xs) and max(xs) < 640 - 244 and -253 < min(ys) and max(ys) < 384 - 253


def test_fight_scene_frame_order():
    frames = fight_frames()
    assert frames[0] == (1, -25) and frames[1] == (2, -23) and frames[2] == (3, -21)
    assert len(frames) == 25 + 25 + 18 + 4 and frames[-1][1] == 10


def test_a_key_skips_the_intro_to_the_view_and_another_leaves(am):
    sm = StateMachine(asset_mgr=am, audio=None)
    start = sm.current_screen
    scr = IntroScreen(asset_mgr=am)
    sm.push_screen(scr)
    surf = pygame.Surface((960, 600))
    scr.render(surf)
    scr.update(0.5)
    _key(scr)
    assert scr.in_view and sm.current_screen is scr
    scr.render(surf)
    for _ in range(120):
        scr.update(1 / 60)
    assert scr.demo_ptr > 0  # the script is playing
    _key(scr)
    assert sm.current_screen is start


def test_the_view_plays_the_demo_script(am):
    scr = IntroScreen(asset_mgr=am, view_only=True)
    scr.render(pygame.Surface((960, 600)))
    before = list(scr.tiles)
    for _ in range(60 * 20):
        scr.update(1 / 60)
    assert scr.tiles != before and scr.anim > 0


def test_autoplay_never_waits_on_the_intro(am):
    sm = StateMachine(asset_mgr=am, audio=None)
    start = sm.current_screen
    sm.push_screen(IntroScreen(asset_mgr=am))
    sm.autoplay_enabled = True
    sm.current_screen.update(0.1)
    assert sm.current_screen is start


def test_main_menu_returns_to_the_view(am):
    sm = StateMachine(asset_mgr=am, audio=None)
    start = sm.current_screen
    assert isinstance(start, StartScreen)
    assert [label for label, _ in start.options][-1] == "Return to the View"
    _key(start, pygame.K_r)
    assert isinstance(sm.current_screen, IntroScreen) and sm.current_screen.in_view


def test_headless_runs_skip_the_intro():
    from py_exodus.__main__ import GameApp

    app = GameApp(assets_dir="assets", headless=True, sound_enabled=False)
    assert not isinstance(app.state_machine.current_screen, IntroScreen)
    assert intro_mod.VIEW_SONGS


# --- Sound and pace of the opening (user 2026-11-23) --------------------------


class FakeAudio:
    """Records what plays; a track 'plays' until stop_music or until the
    test says it ended."""

    enabled = True

    def __init__(self):
        self.log: list[tuple[str, str]] = []
        self.current: str | None = None

    def play_music(self, name, loops=-1, volume=None):
        self.log.append(("music", name))
        self.current = name
        return True

    def stop_music(self):
        self.log.append(("stop", ""))
        self.current = None

    def music_busy(self) -> bool:
        return self.current is not None

    def play_sfx(self, name, volume=None):
        self.log.append(("sfx", name))
        return True


def _run(scr, seconds):
    for _ in range(round(seconds * 60)):
        scr.update(1 / 60)


def test_main_menu_plays_no_crackle(am):
    """The crackle looped forever on the main menu (play_music's default
    loops=-1) and, still playing, kept the View's songs from starting."""
    audio = FakeAudio()
    sm = StateMachine(asset_mgr=am, audio=audio)
    assert isinstance(sm.current_screen, StartScreen)
    assert ("music", "title_fade") not in audio.log
    assert not audio.music_busy()


def test_the_crackle_plays_only_while_each_logo_dissolves_in(am):
    """LW FadeOnExodusUltima: the noise runs for each dissolve (pyExodus,
    then Ultima III) and stops when the picture is complete."""
    audio = FakeAudio()
    scr = IntroScreen(asset_mgr=am, audio=audio)
    scr.on_enter()
    assert audio.log == []  # nothing before the first dissolve
    scr.render(pygame.Surface((960, 600)))
    _run(scr, 2.0)  # 80-tick wait, then into the pyExodus dissolve
    assert audio.current == "title_fade"
    _run(scr, 3.0)  # pyExodus complete (43 passes x 5 ticks), 60-tick wait
    assert audio.current is None
    _run(scr, 1.5)  # into the Ultima III dissolve
    assert audio.current == "title_fade"
    _run(scr, 3.0)
    assert audio.current is None
    assert [e for e in audio.log if e[0] == "music"] == [("music", "title_fade")] * 2


def test_the_view_is_a_jukebox(am):
    """DemoUpdate: one song after another, in LW's order, each played once
    (loops=0) and the next started when it ends."""
    audio = FakeAudio()
    scr = IntroScreen(asset_mgr=am, audio=audio, view_only=True)
    scr.render(pygame.Surface((960, 600)))
    _run(scr, 1.0)
    assert audio.current == intro_mod.VIEW_SONGS[0]
    _run(scr, 1.0)
    assert [e for e in audio.log if e[0] == "music"] == [("music", intro_mod.VIEW_SONGS[0])]
    audio.current = None  # the song ends
    _run(scr, 0.5)
    assert audio.current == intro_mod.VIEW_SONGS[1]


def test_the_view_animates_tiles_at_the_game_pace(am):
    """Tiles changed frame every DrawDemo (4 ticks, 15 per second): the
    daemons flapped like they were about to fly off. The View now steps
    tile frames every 0.2 s, as the town and overworld do."""
    scr = IntroScreen(asset_mgr=am, view_only=True)
    scr.render(pygame.Surface((960, 600)))
    _run(scr, 0.25)
    start = scr.anim
    _run(scr, 2.0)
    assert 9 <= scr.anim - start <= 11  # 5 frames per second


def test_main_menu_credits_name_py_exodus():
    assert any("py-exodus © 2026" in line for line in StartScreen.CREDITS)
