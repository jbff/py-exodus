"""Shared pytest fixtures for py-exodus test suite."""
import pytest
import pygame
from py_exodus.assets import AssetManager


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
