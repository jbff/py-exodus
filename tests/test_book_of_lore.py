"""Task 15: Book of Lore — BookScreen loads ultima3.txt as a paged text view.

Java truth:
- ``exodus/BookScreen.java:53`` — ``addPages(fontLarger, "/assets/data/ultima3.txt", labs)``
- ``exodus/BookScreen.java:150-174`` — pages split on ``*break`` lines and on
  per-column text overflow.
- ``exodus/BaseScreen.java:86-97`` — ``addButtons()`` mounts a Book button on
  every screen, so the lore book is reachable from the title screen and each
  game screen.

The spell reference (a Python-only invention) is kept, appended after the
lore text.
"""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.book import (
    BookScreen,
    load_lore_pages,
    load_lore_sections,
    spell_reference_pages,
)
from py_exodus.state_machine import StateMachine


@pytest.fixture(autouse=True)
def init_pygame():
    """Ensure pygame and fonts are initialized in headless mode."""
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture
def asset_mgr():
    return AssetManager()


def _page_text(scr: BookScreen) -> str:
    return scr.pages[scr.page_index]


def _full_text(scr: BookScreen) -> str:
    return "\n".join(scr.pages)


class TestLoreLoading:
    def test_loads_lore_from_ultima3_txt(self):
        """Java BookScreen.java:53 — lore text comes from data/ultima3.txt."""
        pages = load_lore_pages()
        assert pages, "Book of Lore must load content from ultima3.txt"
        # Java BookScreen.java:159 — raw text file starts with the commands list
        assert "EXODUS ULTIMA III COMMANDS" in pages[0]
        assert "A) Attack" in pages[0]

    def test_sections_split_on_break_markers(self):
        """Java BookScreen.java:158-162 — '*break' lines end a lore section."""
        sections = load_lore_sections()
        # ultima3.txt contains 12 '*break' markers -> 13 sections
        assert len(sections) == 13

    def test_no_break_markers_leak_into_pages(self):
        pages = load_lore_pages()
        for page in pages:
            assert "*break" not in page

    def test_book_screen_builds_paged_text_view(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        assert scr.page_count > 1
        assert scr.page_index == 0
        # First lore page follows the Java truth: the command list opens the book
        assert "EXODUS ULTIMA III COMMANDS" in _page_text(scr)

    def test_page_count_stable(self, asset_mgr):
        """Rebuilding the book yields an identical, deterministic page count."""
        first = BookScreen(asset_mgr=asset_mgr)
        second = BookScreen(asset_mgr=asset_mgr)
        assert first.page_count == second.page_count
        assert first.pages == second.pages
        # The appended spell reference is stable too
        assert "REPOND" in _full_text(first)
        assert "PONTORI" in _full_text(first)

    def test_spell_reference_appended_last(self, asset_mgr):
        """Plan decision: spell reference stays as a Python-only appendix."""
        scr = BookScreen(asset_mgr=asset_mgr)
        lore = load_lore_pages()
        ref_pages = spell_reference_pages()
        ref_text = "\n".join(ref_pages)
        assert "REPOND" in ref_text
        assert "PONTORI" in ref_text
        # Lore pages come first, verbatim; the spell reference is appended last
        assert scr.pages == lore + ref_pages


class TestPaging:
    def test_turn_forward_and_back(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        assert scr.page_index == 0
        scr.turn_forward()
        assert scr.page_index == 1
        scr.turn_back()
        assert scr.page_index == 0

    def test_forward_clamps_at_last_page(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        for _ in range(scr.page_count + 5):
            scr.turn_forward()
        assert scr.page_index == scr.page_count - 1

    def test_back_clamps_at_first_page(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        scr.turn_forward()
        for _ in range(5):
            scr.turn_back()
        assert scr.page_index == 0

    def test_key_navigation(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr, return_screen=BaseScreen())
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        assert scr.page_index == 1
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
        assert scr.page_index == 2
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
        assert scr.page_index == 1
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
        assert scr.page_index == 0

    def test_escape_returns_to_caller(self, asset_mgr):
        dummy = BaseScreen()
        scr = BookScreen(asset_mgr=asset_mgr, return_screen=dummy)
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert scr.is_finished
        assert scr.next_screen is dummy

    def test_render_all_pages(self, asset_mgr):
        """Render every page onto a 320x200 surface without errors."""
        scr = BookScreen(asset_mgr=asset_mgr)
        surface = pygame.Surface((320, 200))
        for _ in range(scr.page_count):
            scr.render(surface)
            scr.turn_forward()


class TestReachability:
    def test_open_book_from_start_screen(self, asset_mgr):
        """Java StartScreen.java:74 — the title screen mounts the Book button."""
        sm = StateMachine(asset_mgr=asset_mgr)
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
        from py_exodus.screens.book import BookScreen as Book
        from py_exodus.screens.start import StartScreen

        start = sm.current_screen
        assert isinstance(start, Book)
        assert start.page_count > 1
        # ESC pops the book and reveals the title screen again
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert isinstance(sm.current_screen, StartScreen)

    def test_f1_opens_book_over_any_screen(self, asset_mgr):
        """Java BaseScreen.java:86-97 — every screen carries the Book button."""
        sm = StateMachine(asset_mgr=asset_mgr, initial_screen=BaseScreen())
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        from py_exodus.screens.book import BookScreen

        assert isinstance(sm.current_screen, BookScreen)
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert isinstance(sm.current_screen, BaseScreen)
        assert not isinstance(sm.current_screen, BookScreen)

    def test_f1_reaches_a_real_game_screen(self, asset_mgr):
        """Journey onward into the overworld, then open the book with F1."""
        sm = StateMachine(asset_mgr=asset_mgr)
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1))
        from py_exodus.screens.overworld import OverworldScreen

        assert isinstance(sm.current_screen, OverworldScreen)
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        from py_exodus.screens.book import BookScreen

        assert isinstance(sm.current_screen, BookScreen)
        # Page through, then leave
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        assert sm.current_screen.page_index == 1
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert isinstance(sm.current_screen, OverworldScreen)
