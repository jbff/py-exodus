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
from py_exodus.constants import Profession, Sex
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.save_system import SaveSystem
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.book import (
    BOOK_FONT_SIZE,
    FOOTER_INSET,
    FOOTER_RULE_GAP,
    PAGE_ROWS,
    TEXT_TOP,
    BookScreen,
    load_lore_pages,
    load_lore_sections,
    spell_reference_pages,
)
from py_exodus.state_machine import StateMachine
from py_exodus.ui.text_log import get_hud_font


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

    def test_pages_use_the_full_page_height(self, asset_mgr):
        """Pages carry PAGE_ROWS lines, filling the area between the header
        rule and the footer at both 320x200 and 960x600 (see book.py for the
        measured linesize math)."""
        for page in load_lore_pages() + spell_reference_pages():
            assert len(page.splitlines()) <= PAGE_ROWS
        # Most lore sections break into full pages rather than thin slivers
        lore = load_lore_pages()
        full = sum(1 for page in lore if len(page.splitlines()) == PAGE_ROWS)
        assert full > len(lore) / 2

    def test_page_count_is_plausible_for_the_dense_layout(self, asset_mgr):
        """Task-density fix: old layout was 193 turns (46x8 pages at a fixed
        tiny font); the 60-column layout turns the whole book in about
        two-thirds of that at HUD-scale font size."""
        scr = BookScreen(asset_mgr=asset_mgr)
        assert scr.page_count < 170
        assert 100 < scr.page_count  # still a real book


class TestSpellReferenceAppendix:
    """USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
    always); availability refused at attempt — supersedes the Java
    getCastables letter compaction (Constants.java:751-762) adopted
    2026-11-14, and undoes the 2026-11-14 relabel that removed this column
    ("letters are assigned dynamically"). The per-discipline ``s.code``
    letters are FIXED again — each discipline's original-game alphabetical
    A-P — so the appendix restores the name + letter + MP + where-castable
    row and carries no letter-assignment note."""

    def _appendix_text(self) -> str:
        return "\n".join(spell_reference_pages())

    def test_every_row_carries_the_fixed_letter_column(self):
        import re

        from py_exodus.constants import Spell

        text = self._appendix_text()
        for spell in Spell:
            # "X - NAME (... MP, ...):" with the spell's own fixed code —
            # B=APPAR_UNEM ALWAYS, C=SANCTU always, per discipline.
            assert re.search(
                rf"^{spell.code} - {spell.name} \(\d+ MP, .+\): ", text, re.MULTILINE
            ), spell.name
        # the headline pin: the fixed cleric letters
        assert "B - APPAR_UNEM (5 MP," in text
        assert re.search(r"^C - SANCTU \(10 MP,", text, re.MULTILINE)

    def test_every_spell_listed_with_mp_cost(self):
        from py_exodus.constants import Spell

        text = self._appendix_text()
        for spell in Spell:
            assert spell.name in text
            assert f"({spell.mp_cost} MP, " in text

    def test_rows_name_the_place_context(self):
        """Each row carries the location-context availability next to the
        fixed letter (the mask feeds ATTEMPT refusals now, not the menu)."""
        text = self._appendix_text()
        # Combat-only bolts name combat; the anywhere spells say anywhere
        assert "B - MITTAR (5 MP, combat)" in text
        assert "C - SANCTU (10 MP, anywhere)" in text
        # APPAR_UNEM is world/city/dungeon (mask 0x0D) at its FIXED B
        assert "B - APPAR_UNEM (5 MP, world/town/dungeon)" in text
        # VIEDA is world+city only (mask 0x05) at its fixed L — the letter
        # never moves even though combat refuses the spell at attempt.
        assert "L - VIEDA (55 MP, world/town)" in text

    def test_no_dynamic_letter_note_remains(self):
        """RULING 2026-11-15: the "letters are assigned dynamically" note is
        gone — the appendix makes no letter-assignment claim at all."""
        text = self._appendix_text()
        assert "the letters that summon" not in text
        assert "deal the letters anew" not in text
        assert "assigned dynamically" not in text

    def test_appendix_order_matches_the_fixed_codes(self):
        """Declarations in Spell-enum order per discipline — each
        discipline's alphabetical A-P (the fixed codes ascend A..P in that
        same order)."""
        from py_exodus.constants import Spell

        text = self._appendix_text()
        wizard_names = [
            s.name for s in Spell if s.spell_type == "wizard"
        ]
        clerical_names = [s.name for s in Spell if s.spell_type == "cleric"]
        cursor = text.index("WIZARD SORCERIES")
        for name in wizard_names:
            cursor = text.index(name, cursor) + len(name)
        cursor = text.index("CLERICAL PRAYERS", cursor)
        for name in clerical_names:
            cursor = text.index(name, cursor) + len(name)


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

    def test_render_scaled_resolution_fits_between_header_and_footer(self, asset_mgr):
        """Geometry, not just "no errors": with the real font metrics, all
        PAGE_ROWS page rows must be visible between the header rule and the
        footer rule at both 320x200 and 960x600 (3x)."""
        full_page = next(
            p
            for p in load_lore_pages()
            if len(p.splitlines()) == PAGE_ROWS and all(p.splitlines())
        )
        scr = BookScreen(asset_mgr=asset_mgr)
        scr.pages = [full_page]  # pin one full page; page_count == 1

        for w, h, s in ((320, 200, 1), (960, 600, 3)):
            surface = pygame.Surface((w, h))
            scr.render(surface)

            linesize = get_hud_font(BOOK_FONT_SIZE * s).get_linesize()
            text_top = TEXT_TOP * s
            footer_rule_top = h - (FOOTER_INSET + FOOTER_RULE_GAP) * s
            # Metric assertion: the last row's bottom stays above the footer rule
            assert text_top + PAGE_ROWS * linesize <= footer_rule_top
            # Pixel assertion: every page row actually has ink on screen
            # within its band (gnuo glyphs start a few px below the blit y).
            bg = (24, 20, 16)  # the parchment fill, not ink
            for i in range(PAGE_ROWS):
                band_top = text_top + i * linesize
                row_has_ink = any(
                    surface.get_at((x, y))[:3] not in ((0, 0, 0), bg)
                    for y in range(band_top, band_top + linesize)
                    for x in range(20 * s, min(w - 20 * s, 200 * s))
                )
                assert row_has_ink, f"page row {i} not visible at {w}x{h}"


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

    def test_f1_noop_while_screen_finished(self, asset_mgr):
        """Pending item 16: F1 during a finished-screen window must not open
        the book (defensive guard — Java's synchronous setScreen has no such
        window, so Java needs no button guard)."""
        from py_exodus.screens.book import BookScreen as Book

        class Finishing(BaseScreen):
            def handle_event(self, event):
                if event.key == pygame.K_f:
                    # No next_screen and no return_screen at stack bottom:
                    # the transition check falls through and the flag sticks.
                    self.is_finished = True

        sm = StateMachine(asset_mgr=asset_mgr, initial_screen=Finishing())
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
        assert sm.current_screen.is_finished
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        assert isinstance(sm.current_screen, Finishing)
        assert not isinstance(sm.current_screen, Book)

    def test_f1_reaches_a_real_game_screen(self, asset_mgr, monkeypatch, tmp_path):
        """Journey onward into the overworld, then open the book with F1."""
        monkeypatch.chdir(tmp_path)
        party = Party()
        hero = Character("Hero", Sex.MALE, profession=Profession.FIGHTER, hp=100, max_hp=100)
        party.add_member(hero)
        SaveSystem.save_game(party, tmp_path / "saves" / "party.json")

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

    def test_in_game_docs_include_hotkeys_navigation_and_f1_closes(self, asset_mgr, pygame_setup):
        """Book of Lore includes navigation, F1/TAB/F9/[/] hotkeys, races, professions, and F1 closes it."""
        scr = BookScreen(asset_mgr=asset_mgr)
        full = _full_text(scr)
        for token in ("Arrow Keys", "F1)", "Tab / F2)", "F9)", "[ / ])", "TABLE 1", "TABLE 2", "WIZARD SORCERIES", "CLERICAL PRAYERS"):
            assert token in full

        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        assert scr.is_finished is True
