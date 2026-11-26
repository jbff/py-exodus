"""Shared pytest fixtures for py-exodus test suite."""
import pytest
import pygame
from py_exodus.assets import AssetManager


@pytest.fixture(autouse=True)
def _saves_stay_in_the_test_dir(monkeypatch):
    """Saves go to ``saves/`` under the current directory (tests chdir to
    tmp_path), never the player's per-user save folder."""
    monkeypatch.setenv("PY_EXODUS_SAVE_DIR", "saves")


@pytest.fixture(scope="module")
def pygame_setup():
    """Ensure pygame is initialized once for test session."""
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture
def asset_mgr():
    """Load AssetManager with standard assets."""
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


def play_out_ending(sm, key=pygame.K_SPACE):
    """Play the victory ending through to the title: the fourth card's
    flicker and the flashes run their time, ``key`` closes the victory page,
    the epilogue fades in, ``key`` again, and the fade out ends at the title."""
    scr = sm.current_screen
    for _ in range(1200):
        if sm.current_screen is not scr:
            return
        if scr.phase in ("page", "epilogue"):
            scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
        sm.update(1 / 60)
    raise AssertionError(f"the ending never finished (phase {scr.phase})")
