"""The release version and how the title screen shows it."""
from pathlib import Path

import pygame
import pytest

import py_exodus
from py_exodus import display_version


def test_display_version_forms():
    assert display_version("1.0.0b2") == "1.0 beta 2"
    assert display_version("1.0.0") == "1.0"
    assert display_version("1.2.3rc1") == "1.2.3 rc 1"
    assert display_version("2.1.0a4") == "2.1 alpha 4"
    assert display_version("weird") == "weird"


def test_pyproject_takes_the_package_version():
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "py_exodus.__version__"


def test_every_subpackage_is_listed():
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    data = tomllib.loads(Path("pyproject.toml").read_text())
    listed = set(data["tool"]["setuptools"]["packages"])
    found = {
        ".".join(p.parent.parts) for p in Path("py_exodus").rglob("__init__.py")
    }
    assert found <= listed


def test_title_screen_shows_the_version(monkeypatch):
    from py_exodus.screens import start as start_mod

    seen = []
    real = start_mod.get_hud_font

    def spy(*a, **k):
        font = real(*a, **k)

        class F:
            def __getattr__(self, n):
                return getattr(font, n)

            def render(self, text, *rest):
                seen.append(text)
                return font.render(text, *rest)

        return F()

    monkeypatch.setattr(start_mod, "get_hud_font", spy)
    pygame.init()
    screen = start_mod.StartScreen(asset_mgr=None, audio=None, party=None, manager=None)
    screen.render(pygame.Surface((960, 600)))
    assert display_version(py_exodus.__version__) in seen
