"""Book of Lore: BookScreen shows ultima3.txt as an open book.

Java truth:
- ``exodus/BookScreen.java:53`` — ``addPages(fontLarger, "/assets/data/ultima3.txt", labs)``
- ``exodus/BaseScreen.java:86-97`` — ``addButtons()`` mounts a Book button on
  every screen, so the lore book is reachable from the title screen and each
  game screen.

Look & feel (approved option B): a contents page, then chapters split at the
lore's headings, each starting on a new two-page spread. The spell reference
(a Python-only invention) is kept as the two closing chapters.
"""
import re

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Sex, Spell
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.save_system import SaveSystem
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.book import (
    CHAPTER_KEYS,
    BookLayout,
    BookScreen,
    load_chapters,
    spell_reference_lines,
)
from py_exodus.state_machine import StateMachine
from py_exodus.ui.text_log import get_hud_font

EXPECTED_CHAPTERS = [
    "Commands",
    "Keys",
    "The Adventure",
    "Preparing for thy Journey",
    "Through the Gateway",
    "Magic",
    "Movement",
    "Combat",
    "Chests",
    "Dungeons",
    "Transportation",
    "Last Minute Counsel",
    "The Realm of Sosaria",
    "Citizens",
    "Monsters of the Land",
    "Monsters of the Sea",
    "Wizard Sorceries",
    "Clerical Prayers",
]


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


def _key(scr: BookScreen, key: int) -> None:
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))


def _chapter_text(title: str) -> str:
    return next(c.text for c in load_chapters() if c.title == title)


def _full_text(scr: BookScreen) -> str:
    return "\n".join(c.text for c in scr.chapters)


def _laid_out_text(scr: BookScreen) -> str:
    """Every row on every page, as plain text."""
    return "\n".join(
        row.plain
        for view in scr.layout.views
        for page in view.pages
        if page
        for row in page
    )


class TestChapters:
    def test_loads_lore_from_ultima3_txt(self):
        """Java BookScreen.java:53 — lore text comes from data/ultima3.txt;
        the raw text opens with the command list."""
        commands = load_chapters()[0]
        assert commands.title == "Commands"
        assert commands.lines[0].startswith("A) Attack")

    def test_chapter_list_and_order(self):
        assert [c.title for c in load_chapters()] == EXPECTED_CHAPTERS
        assert len(CHAPTER_KEYS) == len(EXPECTED_CHAPTERS)

    def test_headings_and_break_markers_do_not_leak(self):
        for chapter in load_chapters():
            for line in chapter.lines:
                assert not line.startswith("*break")
                assert line.strip() not in ("THE ADVENTURE", "MONSTERS - SEA", "EXODUS ULTIMA III COMMANDS")

    def test_chapters_hold_their_lore(self):
        assert "Ultima III Exodus" in _chapter_text("The Adventure")
        assert "Mondain and Minax" in _chapter_text("The Adventure")
        assert "TABLE 1" in _chapter_text("Through the Gateway")
        assert "Man-O-Wars" in _chapter_text("Monsters of the Sea")
        # the spell books' lore belongs to the spell chapters, not the sea
        assert "Amber Runes" not in _chapter_text("Monsters of the Sea")
        assert "Amber Runes" in _chapter_text("Wizard Sorceries")
        assert "A. REPOND" in _chapter_text("Wizard Sorceries")
        assert "Ancient Liturgy of Truth" in _chapter_text("Clerical Prayers")
        assert "A. PONTORI" in _chapter_text("Clerical Prayers")

    def test_spell_chapters_lead_with_the_reference(self):
        by_title = {c.title: c for c in load_chapters()}
        wizard = by_title["Wizard Sorceries"]
        cleric = by_title["Clerical Prayers"]
        assert wizard.lines[:16] == spell_reference_lines("wizard")
        assert cleric.lines[:16] == spell_reference_lines("cleric")

    def test_book_is_deterministic(self, asset_mgr):
        first = BookScreen(asset_mgr=asset_mgr)
        second = BookScreen(asset_mgr=asset_mgr)
        assert first.page_count == second.page_count
        assert _laid_out_text(first) == _laid_out_text(second)


class TestSpellReference:
    """USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
    always); availability refused at attempt — supersedes the Java
    getCastables letter compaction (Constants.java:751-762). The
    per-discipline ``s.code`` letters are FIXED — each discipline's
    original-game alphabetical A-P — so each row carries name + letter + MP
    + where castable, and there is no letter-assignment note."""

    def _text(self) -> str:
        return "\n".join(spell_reference_lines("wizard") + spell_reference_lines("cleric"))

    def test_every_row_carries_the_fixed_letter_column(self):
        text = self._text()
        for spell in Spell:
            assert re.search(
                rf"^{spell.code} - {spell.name} \(\d+ MP, .+\): ", text, re.MULTILINE
            ), spell.name
        assert "B - APPAR_UNEM (5 MP," in text
        assert re.search(r"^C - SANCTU \(10 MP,", text, re.MULTILINE)

    def test_every_spell_listed_with_mp_cost_and_description(self):
        text = self._text()
        for spell in Spell:
            assert f"{spell.name} ({spell.mp_cost} MP, " in text
            assert spell.desc in text

    def test_rows_name_the_place_context(self):
        text = self._text()
        assert "B - MITTAR (5 MP, combat)" in text
        assert "C - SANCTU (10 MP, anywhere)" in text
        assert "B - APPAR_UNEM (5 MP, world/town/dungeon)" in text
        assert "L - VIEDA (55 MP, world/town)" in text

    def test_no_dynamic_letter_note_remains(self):
        text = _chapter_text("Wizard Sorceries") + _chapter_text("Clerical Prayers")
        assert "assigned dynamically" not in text
        assert "deal the letters anew" not in text

    def test_reference_order_matches_the_fixed_codes(self):
        for discipline in ("wizard", "cleric"):
            codes = [ln[0] for ln in spell_reference_lines(discipline)]
            assert codes == list("ABCDEFGHIJKLMNOP")

    def test_spell_rows_survive_the_layout(self, asset_mgr):
        """Wrapping keeps each row's cyan key and its text."""
        scr = BookScreen(asset_mgr=asset_mgr)
        text = _laid_out_text(scr)
        assert "B - APPAR_UNEM (5 MP, world/town/dungeon)" in text
        assert "REPOND" in text and "PONTORI" in text


class TestLayout:
    @pytest.mark.parametrize("size", [(960, 600), (320, 200)])
    def test_every_chapter_starts_on_a_left_page(self, asset_mgr, size):
        scr = BookScreen(asset_mgr=asset_mgr)
        scr.render(pygame.Surface(size))
        lay = scr.layout
        assert len(lay.chapter_first_view) == len(EXPECTED_CHAPTERS)
        for ci, first in enumerate(lay.chapter_first_view):
            view = lay.views[first]
            assert view.chapter == ci
            assert view.pages[0], f"chapter {ci} opens on an empty left page"
            assert lay.views[first - 1].chapter != ci
            # page numbers: a chapter's first page is odd on the spread
            if lay.pages_per_view == 2:
                assert view.numbers[0] % 2 == 1

    def test_spread_count_is_sane(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        assert scr.layout.pages_per_view == 2
        assert 30 <= scr.spread_count <= 45
        assert scr.page_count == scr.spread_count + 1  # plus the contents

    @pytest.mark.parametrize("size", [(960, 600), (320, 200)])
    def test_no_row_wider_than_its_page(self, size):
        lay = BookLayout.for_size(*size)
        lay.build(load_chapters())
        font = get_hud_font(lay.body_size)
        for view in lay.views:
            for page in view.pages:
                for row in page or []:
                    if row.kind == "cols":
                        width = row.col_x[-1] + font.size(row.cells[-1])[0]
                    else:
                        width = font.size(row.key + row.text)[0]
                    assert width <= lay.page_width, row.plain

    @pytest.mark.parametrize("size", [(960, 600), (320, 200)])
    def test_pages_fit_between_header_and_footer(self, size):
        lay = BookLayout.for_size(*size)
        lay.build(load_chapters())
        for view in lay.views:
            for page in view.pages:
                rows = page or []
                height = sum(
                    lay.line_height // 2 if r.kind == "gap" else lay.line_height for r in rows
                )
                assert height <= lay.body_bottom - lay.body_top
                assert not rows or (rows[0].kind != "gap" and rows[-1].kind != "gap")
        # a real gap between the last body row and the footer rule
        assert lay.body_bottom <= lay.footer_rule_y - (6 if size[0] >= 640 else 2)
        assert lay.footer_rule_y < lay.footer_y

    @pytest.mark.parametrize("size", [(960, 600), (320, 200)])
    def test_every_word_of_the_lore_is_laid_out(self, size):
        """Word multisets: ultima3.txt minus headings and *break markers,
        against the laid-out pages minus the spell reference rows."""
        from collections import Counter
        from pathlib import Path

        from py_exodus.screens.book import CHAPTER_HEADINGS

        source: Counter[str] = Counter()
        for line in Path("assets/data/ultima3.txt").read_text(encoding="utf-8").splitlines():
            key = line.strip()
            if key in CHAPTER_HEADINGS or key.startswith("*break"):
                continue
            source.update(line.split())

        lay = BookLayout.for_size(*size)
        lay.build(load_chapters())
        laid: Counter[str] = Counter()
        for view in lay.views:
            for page in view.pages:
                for row in page or []:
                    laid.update(row.plain.split())
        for line in spell_reference_lines("wizard") + spell_reference_lines("cleric"):
            laid.subtract(line.split())
        assert +laid == source and not -laid

    @pytest.mark.parametrize("content", [None, ""])
    def test_missing_or_empty_lore_still_opens(self, tmp_path, content):
        class FakeAssets:
            def resolve_path(self, *parts):
                return tmp_path / "ultima3.txt"

        if content is not None:
            (tmp_path / "ultima3.txt").write_text(content, encoding="utf-8")
        scr = BookScreen(asset_mgr=FakeAssets())
        assert [c.title for c in scr.chapters] == ["Wizard Sorceries", "Clerical Prayers"]
        for size in ((960, 600), (320, 200)):
            surface = pygame.Surface(size)
            scr.render(surface)
            _key(scr, pygame.K_2)
            assert scr.current_chapter == 1
            scr.render(surface)
            _key(scr, pygame.K_9)  # no ninth chapter: ignored
            assert scr.current_chapter == 1
            _key(scr, pygame.K_0)
            assert scr.on_contents

    def test_layout_is_built_lazily_for_the_first_surface(self, asset_mgr, monkeypatch):
        built = []
        real = BookLayout.for_size.__func__

        def spy(cls, width, height):
            built.append((width, height))
            return real(cls, width, height)

        monkeypatch.setattr(BookLayout, "for_size", classmethod(spy))
        scr = BookScreen(asset_mgr=asset_mgr)
        assert built == []
        scr.render(pygame.Surface((320, 200)))
        assert built == [(320, 200)]

    def test_spreads_at_960_and_single_pages_at_320(self, asset_mgr):
        assert BookLayout.for_size(960, 600).pages_per_view == 2
        assert BookLayout.for_size(320, 200).pages_per_view == 1
        assert BookLayout.for_size(960, 600).body_size == 18

    def test_command_lines_carry_a_cyan_key(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        first = scr.layout.views[1].pages[0]
        assert first[0].key == "A)"
        assert first[0].text.startswith(" Attack")

    def test_resize_keeps_the_chapter(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        scr.open_chapter(7)
        scr.turn_forward()
        scr.render(pygame.Surface((320, 200)))
        assert scr.current_chapter == 7
        scr.render(pygame.Surface((960, 600)))
        assert scr.current_chapter == 7

    @pytest.mark.parametrize("size", [(960, 600), (320, 200)])
    def test_render_every_view(self, asset_mgr, size):
        scr = BookScreen(asset_mgr=asset_mgr)
        surface = pygame.Surface(size)
        for _ in range(scr.page_count + 1):
            scr.render(surface)
            scr.turn_forward()

    def test_spread_draws_text_on_both_pages(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        scr.open_chapter(0)
        surface = pygame.Surface((960, 600))
        scr.render(surface)
        lay = scr.layout
        for x0 in lay.page_x:
            ink = any(
                surface.get_at((x, y))[:3] not in ((0, 0, 0), (24, 20, 16))
                for y in range(lay.body_top, lay.body_top + 3 * lay.line_height)
                for x in range(x0, x0 + 150)
            )
            assert ink


class TestNavigation:
    def test_opens_on_the_contents(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        assert scr.on_contents and scr.view_index == 0
        assert scr.current_chapter == -1

    def test_contents_up_down_and_enter(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_UP)
        assert scr.highlight == 0
        _key(scr, pygame.K_DOWN)
        _key(scr, pygame.K_DOWN)
        assert scr.highlight == 2 and scr.on_contents
        _key(scr, pygame.K_RETURN)
        assert scr.current_chapter == 2
        assert scr.view_index == scr.layout.chapter_first_view[2]

    def test_contents_highlight_clamps_at_the_last_chapter(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        for _ in range(40):
            _key(scr, pygame.K_DOWN)
        assert scr.highlight == len(EXPECTED_CHAPTERS) - 1

    def test_chapter_keys_on_the_contents(self, asset_mgr):
        for i, ch in enumerate(CHAPTER_KEYS):
            scr = BookScreen(asset_mgr=asset_mgr)
            _key(scr, getattr(pygame, f"K_{ch.lower()}"))
            assert scr.current_chapter == i, ch
            assert scr.view_index == scr.layout.chapter_first_view[i]

    def test_chapter_keys_from_inside_the_book(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_5)
        assert scr.current_chapter == 4
        _key(scr, pygame.K_h)
        assert scr.current_chapter == 16
        _key(scr, pygame.K_1)
        assert scr.current_chapter == 0
        _key(scr, pygame.K_a)
        assert scr.current_chapter == 9

    @pytest.mark.parametrize("key", [pygame.K_0, pygame.K_KP0, pygame.K_HOME])
    def test_zero_returns_to_contents_with_the_chapter_highlighted(self, asset_mgr, key):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_8)
        _key(scr, pygame.K_RIGHT)
        _key(scr, key)
        assert scr.on_contents
        assert scr.highlight == 7

    def test_c_is_only_chapter_c(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_8)
        _key(scr, pygame.K_c)
        assert scr.current_chapter == 11  # Last Minute Counsel
        _key(scr, pygame.K_0)
        _key(scr, pygame.K_c)
        assert scr.current_chapter == 11

    def test_keypad_digits_open_chapters(self, asset_mgr):
        for i in range(9):
            scr = BookScreen(asset_mgr=asset_mgr)
            _key(scr, getattr(pygame, f"K_KP{i + 1}"))
            assert scr.current_chapter == i
            _key(scr, pygame.K_KP1)
            assert scr.current_chapter == 0

    def test_footer_hint_names_the_zero_key(self):
        from py_exodus.screens.book import SPREAD_HINT

        assert "0 contents" in SPREAD_HINT and "C contents" not in SPREAD_HINT

    def test_left_right_turn_spreads(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_RIGHT)
        assert scr.view_index == 1 and scr.current_chapter == 0
        _key(scr, pygame.K_RIGHT)
        assert scr.view_index == 2
        _key(scr, pygame.K_SPACE)
        assert scr.view_index == 3
        _key(scr, pygame.K_RETURN)
        assert scr.view_index == 4
        _key(scr, pygame.K_LEFT)
        assert scr.view_index == 3

    def test_turning_clamps_at_both_ends(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        for _ in range(scr.page_count + 5):
            _key(scr, pygame.K_RIGHT)
        assert scr.view_index == scr.page_count - 1
        assert scr.current_chapter == len(EXPECTED_CHAPTERS) - 1
        for _ in range(scr.page_count + 5):
            _key(scr, pygame.K_LEFT)
        assert scr.on_contents

    def test_up_down_jump_chapters(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_3)
        _key(scr, pygame.K_RIGHT)  # mid-chapter
        _key(scr, pygame.K_DOWN)
        assert scr.current_chapter == 3
        assert scr.view_index == scr.layout.chapter_first_view[3]
        _key(scr, pygame.K_UP)
        _key(scr, pygame.K_UP)
        assert scr.current_chapter == 1
        assert scr.view_index == scr.layout.chapter_first_view[1]
        _key(scr, pygame.K_UP)
        assert scr.current_chapter == 0

    def test_down_in_the_last_chapter_does_nothing(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_i)
        _key(scr, pygame.K_RIGHT)
        where = scr.view_index
        assert where > scr.layout.chapter_first_view[-1]
        _key(scr, pygame.K_DOWN)
        assert scr.view_index == where
        assert scr.current_chapter == len(EXPECTED_CHAPTERS) - 1

    def test_up_in_the_first_chapter_does_nothing(self, asset_mgr):
        scr = BookScreen(asset_mgr=asset_mgr)
        _key(scr, pygame.K_1)
        _key(scr, pygame.K_RIGHT)
        where = scr.view_index
        _key(scr, pygame.K_UP)
        assert scr.view_index == where
        assert scr.current_chapter == 0

    @pytest.mark.parametrize("key", [pygame.K_ESCAPE, pygame.K_q, pygame.K_F1])
    def test_close_keys_return_to_caller(self, asset_mgr, key):
        for chapter_key in (None, pygame.K_4):
            dummy = BaseScreen()
            scr = BookScreen(asset_mgr=asset_mgr, return_screen=dummy)
            if chapter_key:
                _key(scr, chapter_key)
            _key(scr, key)
            assert scr.is_finished
            assert scr.next_screen is dummy


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
        # Turn from the contents to the first spread, then leave
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        assert sm.current_screen.view_index == 1
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert isinstance(sm.current_screen, OverworldScreen)

    def test_in_game_docs_include_hotkeys_navigation_and_f1_closes(self, asset_mgr, pygame_setup):
        """Book of Lore includes navigation, F1/TAB/F9/[/] hotkeys, races, professions, and F1 closes it."""
        scr = BookScreen(asset_mgr=asset_mgr)
        full = _full_text(scr)
        for token in ("Arrow Keys", "F1)", "Tab / F2)", "F9)", "[ / ])", "TABLE 1", "TABLE 2"):
            assert token in full
        titles = [c.title for c in scr.chapters]
        assert "Wizard Sorceries" in titles and "Clerical Prayers" in titles

        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        assert scr.is_finished is True


def test_command_list_follows_lairware_letters():
    """LairWare LetterCommand (UltimaMain.c:1160-1195): ``case 'L': Look();``
    and ``case 'S': Steal();``; there is no Search or Open letter (user
    ruling 2026-11-25: the Java-sourced list was wrong on S and L)."""
    from pathlib import Path

    lines = Path("assets/data/ultima3.txt").read_text(encoding="utf-8").splitlines()
    commands = {ln[0]: ln for ln in lines[:30] if len(ln) > 2 and ln[1] == ")" and ln[0].isalpha()}
    assert commands["L"].startswith("L) Look")
    assert commands["S"].startswith("S) Steal")
    assert not any("Search:" in ln or "Open a door" in ln for ln in commands.values())
    assert "Unlock" in commands["U"]
