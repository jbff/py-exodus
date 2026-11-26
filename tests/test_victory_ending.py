"""The victory ending (look & feel item 6): LairWare's flashes, the victory
page, and the WinText epilogue.

LairWare truth: UltimaMisc.c:2357-2424 (the win) and UltimaText.c:728-746
(WinText); the congratulations are Messages 255 and 242.
"""
from __future__ import annotations

import random
from pathlib import Path

import pygame
import pytest
from conftest import play_out_ending

from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens import final
from py_exodus.screens.final import FinalScreen
from py_exodus.screens.start import StartScreen
from py_exodus.state_machine import StateMachine
from py_exodus.ui.pixel_font import BLOCK, LOGO, SERIF, TINY, render_banner

SIZES = [(960, 600), (320, 200)]
FRAME = 1 / 60
CARDS = (("love", 30), ("sol", 31), ("moons", 32), ("death", 33))


class _Audio:
    def __init__(self) -> None:
        self.sfx: list[str] = []
        self.music: list[str] = []

    def play_sfx(self, name, volume=None):
        self.sfx.append(name)
        return True

    def play_music(self, name, loops=-1, volume=None):
        self.music.append(name)
        return True

    def stop_music(self):
        pass


def _party(moves: int = 23417) -> Party:
    p = Party()
    for name, job, level in (
        ("Shadow", Profession.THIEF, 25),
        ("Grumm", Profession.FIGHTER, 25),
        ("Wwwwwwwwwwww", Profession.ILLUSIONIST, 21),  # the widest name and class
        ("Zircon", Profession.WIZARD, 23),
    ):
        c = Character(name, "M", Race.HUMAN, job)
        c.level = level
        c.cards = [1, 1, 1, 1]
        p.add_member(c)
    p.moves = moves
    return p


def _flicker_out(scr: FinalScreen) -> None:
    for _ in range(200):
        if scr.phase != "card":
            break
        scr.update(FRAME)
    assert scr.phase != "card"


def _won(party=None, seed: int = 7, flicker: bool = True, **kw) -> FinalScreen:
    """A FinalScreen after the fourth card: with its flicker played out, at
    the first flash; with ``flicker=False``, straight after the insert."""
    party = party or _party()
    scr = FinalScreen(party=party, rng=random.Random(seed), **kw)
    for card, px in CARDS:
        assert scr.insert_card(card, member_idx=0, pos=(px, 12))
    assert scr.victory and scr.phase == "card"
    if flicker:
        _flicker_out(scr)
        assert scr.phase == "flash"
        audio = kw.get("audio")
        if audio is not None:
            audio.sfx.clear()
    return scr


def _to_page(scr: FinalScreen) -> None:
    for _ in range(600):
        if scr.phase not in ("card", "flash"):
            break
        scr.update(FRAME)
    assert scr.phase == "page"


def _castle(asset_mgr, party, audio=None, x=33, status=0x7):
    """A state machine on Castle Exodus with the party at panel ``x``."""
    from py_exodus.screens.town import TownScreen

    sm = StateMachine(asset_mgr=asset_mgr)
    town = TownScreen(party=party, map_id=2, asset_mgr=asset_mgr, start_x=x, start_y=12, audio=audio)
    town.avatar_x, town.avatar_y = x, 12
    town.game_map.npcs = []
    sm.set_screen(town)
    party.exodus_cards_status = status
    return sm, town


def _insert(town, x, letter) -> None:
    final.prompt_insert_card(town, x, 12)
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
    town.handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=getattr(pygame, f"K_{letter}"), unicode=letter)
    )


def _key(scr, key=pygame.K_SPACE) -> None:
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))


def _to_epilogue(scr: FinalScreen) -> None:
    _to_page(scr)
    _key(scr)
    for _ in range(200):
        if scr.phase != "fade_in":
            break
        scr.update(FRAME)
    assert scr.phase == "epilogue"


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------
def test_the_words_are_lairwares():
    # Messages.plist 255 and 242 (UltimaMisc.c:2367, 2379)
    assert final.LW_CONGRATULATIONS == "CONGRATULATIONS! Thou hast compleated EXODUS: ULTIMA III in"
    assert final.LW_MOVES == " MOVES"
    assert final.LW_REPORT == "REPORT THY FEAT!"
    assert " ".join(final.PAGE_LINES) == final.LW_CONGRATULATIONS.upper()
    # WinText, UltimaText.c:736-745
    assert final.EPILOGUE_LINES == (
        "   And so it came to",
        "pass  that  on  this",
        "day EXODUS,hell-born",
        "incarnate  of  evil,",
        "was vanquished  from",
        "SOSARIA.   What  now",
        "lies  ahead  in  the",
        "ULTIMA saga can only",
        "be pure speculation!",
        "Onward to ULTIMA IV!",
    )
    assert {len(line) for line in final.EPILOGUE_LINES} == {20}


def test_the_words_match_the_lairware_sources_when_present():
    root = Path(__file__).resolve().parents[1] / "refs/ultima3"
    if not root.exists():
        pytest.skip("LairWare reference checkout not present")
    import plistlib

    with open(root / "Resources/English.lproj/Strings/Messages.plist", "rb") as fh:
        messages = plistlib.load(fh)
    assert messages[254].rstrip() == final.LW_CONGRATULATIONS
    assert messages[241] == final.LW_MOVES + "\n" + final.LW_REPORT
    source = (root / "Sources/UltimaText.c").read_text(errors="replace")
    for line in final.EPILOGUE_LINES:
        assert f'UPrint2("\\p{line}"' in source


def test_every_glyph_the_ending_uses_exists():
    party = _party()
    assert not SERIF.missing("".join(final.EPILOGUE_LINES))
    assert not BLOCK.missing("".join(final.PAGE_LINES) + final.LW_MOVES + final.LW_REPORT)
    assert not LOGO.missing("EXODUS VANQUISHED 0123456789,")
    for job in Profession:
        assert not TINY.missing(f"{job.name.replace('_', ' ')} LV 0123456789")
    for m in party.members:
        assert not BLOCK.missing(m.name)


def test_the_alphabets_cover_what_the_brief_asks():
    import string

    assert not SERIF.missing(string.ascii_letters + string.digits + ",.!-")
    assert not BLOCK.missing(string.ascii_uppercase + string.digits + "!:,.")
    assert not TINY.missing(string.ascii_uppercase + string.digits)
    # the serif is fixed width, so LW's twenty columns line up
    assert {len(rows[0]) for rows in SERIF.glyphs.values()} == {7}
    assert SERIF.width("ab") == 15 and SERIF.width("  ") == 15


def test_pixel_text_scales_by_whole_pixels(pygame_setup):
    small = BLOCK.render("EXODUS", (255, 255, 255), 1)
    big = BLOCK.render("EXODUS", (255, 255, 255), 3)
    assert big.get_size() == (small.get_width() * 3, small.get_height() * 3)
    assert small.get_size() == (BLOCK.width("EXODUS"), 7)
    # a lower-case name draws in the capitals; an unknown sign draws as "?"
    assert BLOCK.ink("exodus") == BLOCK.ink("EXODUS")
    assert BLOCK.missing("A~A") == {"~"}
    assert BLOCK.ink("A~A") == BLOCK.ink("A?A") != BLOCK.ink("A A")
    assert BLOCK.ink("A A") == BLOCK.ink("A") | {(x + 12, y) for x, y in BLOCK.ink("A")}
    banner = render_banner(LOGO, "EXODUS", 1, 2)
    assert banner.get_size() == (LOGO.width("EXODUS") * 2 + 2, 22)


# ---------------------------------------------------------------------------
# Beat 1: the flashes
# ---------------------------------------------------------------------------
def test_lw_song_table_is_shared():
    """One table of LairWare's song numbers (audio.LW_SONGS), read by the
    intro's jukebox (UltimaGraphics.c:918) and the ending (song 10)."""
    from py_exodus.audio import LW_SONGS, MUSIC_TRACKS
    from py_exodus.screens import intro

    assert sorted(LW_SONGS) == [1, 2, 3, 4, 5, 6, 7, 8, 10, 11]  # no Song_9
    assert len(set(LW_SONGS.values())) == 10
    assert all(name in MUSIC_TRACKS for name in LW_SONGS.values())
    assert intro.VIEW_SONGS == tuple(LW_SONGS[n] for n in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11))
    assert LW_SONGS[10] == "alive" and LW_SONGS[11] == "fanfare"
    assert LW_SONGS[7] == "exodus" and LW_SONGS[8] == "rule britannia"


def test_each_card_flickers_its_panel_with_ten_hits(pygame_setup, asset_mgr):
    """UltimaMisc.c:2344-2355: five times the ball goes on the panel and
    comes off, a Hit and 15 ticks each half; then play goes on."""
    p = _party()
    audio = _Audio()
    sm, town = _castle(asset_mgr, p, audio, x=30, status=0)
    _insert(town, 30, "l")
    scr = sm.current_screen
    assert isinstance(scr, FinalScreen) and scr.phase == "card" and not scr.victory
    assert p.exodus_cards_status == 0x1  # the card counts at once
    assert "DivineMed" not in audio.sfx
    hits, frames = [], 0
    surface = pygame.Surface((960, 600))
    plain = pygame.Surface((960, 600))
    town.render(plain)
    panel = pygame.Rect(5 * 48, 4 * 48, 48, 48)  # the tile north of the party
    looks = set()
    while sm.current_screen is scr and frames < 400:
        _key(scr)  # keys do nothing while it flickers
        sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        sm.update(FRAME)
        frames += 1
        hits.append(audio.sfx.count("Hit"))
        if sm.current_screen is scr:
            scr.render(surface)
            looks.add(pygame.image.tobytes(surface.subsurface(panel), "RGB"))
            outside = pygame.Rect(0, 5 * 48, 528, 6 * 48)
            assert pygame.image.tobytes(surface.subsurface(outside), "RGB") == pygame.image.tobytes(
                plain.subsurface(outside), "RGB"
            )
    assert final.CARD_FLICKERS == 5 and final.CARD_FLICKER_TICKS == 15
    assert hits[0] == 1 and hits[13] == 1 and hits[16] == 2
    assert hits[-1] == 10
    assert abs(frames - 150) <= 2  # ten halves of 15 ticks
    assert len(looks) == 2  # the panel with the ball on it, and without
    # back in the castle, which takes keys again; the Book was never opened
    assert sm.current_screen is town and sm.screen_stack == [town]
    assert not audio.music or audio.music[-1] != "alive"
    assert "CONGRATULATIONS" not in " ".join(town.text_log.history)


def test_the_fourth_card_flickers_then_song_ten_and_the_congratulations(pygame_setup, asset_mgr):
    p = _party(moves=1234)
    audio = _Audio()
    sm, town = _castle(asset_mgr, p, audio)
    _insert(town, 33, "d")
    scr = sm.current_screen
    assert isinstance(scr, FinalScreen) and scr.phase == "card" and scr.victory
    assert p.exodus_defeated == 1
    # LairWare's order: the flicker, then the song and the words
    assert "alive" not in audio.music
    assert "CONGRATULATIONS" not in " ".join(town.text_log.history)
    for _ in range(200):
        if scr.phase != "card":
            break
        sm.update(FRAME)
    assert scr.phase == "flash" and audio.sfx.count("Hit") == 10
    assert audio.music[-1] == "alive"  # song 10, UltimaMisc.c:2362
    log = " ".join(town.text_log.history)
    assert (
        log.index("CONGRATULATIONS! Thou hast compleated EXODUS: ULTIMA III in")
        < log.index("1234 MOVES")
        < log.index("REPORT THY FEAT!")
    )

    # The flashes go over the castle screen: its map pane changes colour,
    # the party panel beside it does not.
    scr.rng = random.Random(3)
    sm.update(0.0)
    assert scr.flash_colours and min(scr.flash_colours[-1]) > 0
    for size in SIZES:
        scale = size[0] // 320
        plain = pygame.Surface(size)
        town.render(plain)
        flashed = pygame.Surface(size)
        scr.render(flashed)
        pane = pygame.Rect(0, 0, 176 * scale, 176 * scale)
        assert pygame.image.tobytes(flashed.subsurface(pane), "RGB") != pygame.image.tobytes(
            plain.subsurface(pane), "RGB"
        )
        side = pygame.Rect(pane.right, 0, size[0] - pane.right, size[1])
        assert pygame.image.tobytes(flashed.subsurface(side), "RGB") == pygame.image.tobytes(
            plain.subsurface(side), "RGB"
        )


def test_f1_does_not_open_the_book_over_the_ending(pygame_setup, asset_mgr):
    """Through the state machine: F1 opens the Book over the castle, never
    over the ending, where it is a key like any other."""
    from py_exodus.screens.book import BookScreen

    f1 = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1)
    sm, town = _castle(asset_mgr, _party())
    sm.handle_event(f1)
    assert isinstance(sm.current_screen, BookScreen)
    sm.pop_screen()
    assert sm.current_screen is town
    town.avatar_x, town.avatar_y = 33, 12
    town.party.exodus_cards_status = 0x7
    _insert(town, 33, "d")
    scr = sm.current_screen
    assert isinstance(scr, FinalScreen) and not scr.allows_book
    seen = set()
    for _ in range(1200):
        if sm.current_screen is not scr:
            break
        seen.add(scr.phase)
        sm.handle_event(f1)  # on the page and the epilogue, the closing key
        assert not isinstance(sm.current_screen, BookScreen)
        sm.update(FRAME)
    assert seen >= {"card", "flash", "page", "fade_in", "epilogue", "fade_out"}
    assert isinstance(sm.current_screen, StartScreen)
    assert FinalScreen(party=_party()).allows_book  # nothing has gone in yet


def test_an_odd_character_in_a_name_draws_as_a_question_mark(pygame_setup):
    p = _party()
    p.members[0].name = "Sh~dow"
    scr = _won(p)
    _to_page(scr)
    surface = pygame.Surface((320, 200))
    scr.render(surface)
    rect = dict(scr.layout)["name 0"]
    assert rect.size == BLOCK.render("SH?DOW", (255, 255, 255), 1).get_size()
    drawn = {(x, y) for x in range(rect.w) for y in range(rect.h)
             if surface.get_at((rect.x + x, rect.y + y))[:3] != (0, 0, 0)}
    assert drawn == BLOCK.ink("SH?DOW")


def test_twenty_one_flashes_ten_ticks_apart_with_a_hit_each(pygame_setup):
    audio = _Audio()
    scr = _won(audio=audio)  # the card's own ten hits are done and cleared
    assert audio.sfx.count("Hit") == 0 and scr.flash_colours == []
    seen = []
    for _ in range(400):
        if scr.phase != "flash":
            break
        scr.update(FRAME)
        seen.append(len(scr.flash_colours))
    # for (input = 0; input <= 20; input++) ... ThreadSleepTicks(10)
    assert final.FLASH_COUNT == 21 and final.FLASH_TICKS == 10
    assert len(scr.flash_colours) == 21
    assert audio.sfx.count("Hit") == 21
    assert seen[0] == 1  # the first flash is at once
    assert seen[7] == 1 and seen[11] == 2
    assert abs(len(seen) - 210) <= 1  # 21 flashes of 10 ticks, then the page
    assert scr.phase == "page"
    scr.update(5.0)
    assert len(scr.flash_colours) == 21 and audio.sfx.count("Hit") == 21


def test_the_flash_colours_are_random(pygame_setup):
    scr = _won(seed=7)
    _to_page(scr)
    colours = scr.flash_colours
    assert len(set(colours)) > 15  # not a fixed palette
    assert all(0 <= c <= 255 for colour in colours for c in colour)
    other = _won(seed=8)
    _to_page(other)
    assert other.flash_colours != colours
    # with no generator handed in, the screen makes its own
    plain = FinalScreen(party=_party())
    assert isinstance(plain.rng, random.Random)


def test_the_flashes_leave_the_games_random_stream_alone(pygame_setup):
    random.seed(99)
    expect = random.random()
    random.seed(99)
    scr = FinalScreen(party=_party())
    for card, px in CARDS:
        scr.insert_card(card, member_idx=0, pos=(px, 12))
    _to_page(scr)
    assert random.random() == expect


def test_keys_cannot_skip_the_flashes_and_are_not_kept(pygame_setup):
    scr = _won()
    scr.update(FRAME)
    for k in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_a):
        _key(scr, k)
        assert scr.phase == "flash"
    _to_page(scr)
    assert len(scr.flash_colours) == 21
    # the keys pressed during the flashes did not carry over to the page
    scr.update(1.0)
    assert scr.phase == "page"


def test_the_flashes_save_nothing(pygame_setup, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _party()
    saved = []
    p.autosave_hook = lambda *a, **k: saved.append(1)
    scr = _won(p)
    _key(scr)
    _to_page(scr)
    assert saved == [] and list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Beat 2: the victory page
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size", SIZES)
def test_victory_page_text_and_move_count_fit(pygame_setup, asset_mgr, size):
    scr = _won(asset_mgr=asset_mgr)
    _to_page(scr)
    surface = pygame.Surface(size)
    scr.render(surface)
    names = [name for name, _ in scr.layout]
    for line in ("CONGRATULATIONS!", "THOU HAST COMPLEATED", "EXODUS: ULTIMA III", "IN"):
        assert line in names
    for word in ("stalactites", "EXODUS", "VANQUISHED", "moves", "MOVES", "REPORT THY FEAT!"):
        assert word in names
    assert names.index("IN") < names.index("moves") < names.index("MOVES")
    rects = dict(scr.layout)
    # the number is the party's move count, as drawn
    assert rects["moves"].size == render_banner(LOGO, "23,417", size[0] // 320).get_size()
    # four heroes: sprite, name, class and level
    for i in range(4):
        assert {f"sprite {i}", f"name {i}", f"class {i}"} <= set(names)
    # nothing leaves the screen and nothing is drawn over anything else
    for name, rect in scr.layout:
        assert surface.get_rect().contains(rect), (name, rect)
    for i, (a_name, a) in enumerate(scr.layout):
        for b_name, b in scr.layout[i + 1:]:
            assert not a.colliderect(b), (a_name, b_name)
    assert surface.get_bounding_rect().height > size[1] // 2  # it drew


def test_victory_page_uses_the_partys_own_move_count(pygame_setup):
    drawn = {}
    for moves in (7, 1234567):
        scr = _won(_party(moves=moves))
        _to_page(scr)
        surface = pygame.Surface((320, 200))
        scr.render(surface)
        drawn[moves] = dict(scr.layout)["moves"]
        assert surface.get_rect().contains(drawn[moves])
    assert drawn[7].size == render_banner(LOGO, "7", 1).get_size()
    assert drawn[1234567].size == render_banner(LOGO, "1,234,567", 1).get_size()


def test_victory_page_waits_for_a_key(pygame_setup):
    scr = _won()
    _to_page(scr)
    scr.update(600.0)
    assert scr.phase == "page"
    scr.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE))
    assert scr.phase == "page"
    _key(scr, pygame.K_x)
    assert scr.phase == "fade_in" and scr.grey == 0


def test_a_small_party_fits_the_page(pygame_setup, asset_mgr):
    p = Party()
    c = Character("Solo", "M", Race.HUMAN, Profession.RANGER)
    c.cards = [1, 1, 1, 1]
    p.add_member(c)
    scr = _won(p, asset_mgr=asset_mgr)
    _to_page(scr)
    surface = pygame.Surface((320, 200))
    scr.render(surface)
    assert abs(dict(scr.layout)["name 0"].centerx - 160) <= 1


# ---------------------------------------------------------------------------
# Beat 3: the epilogue
# ---------------------------------------------------------------------------
def test_epilogue_fades_in_as_lairware(pygame_setup):
    scr = _won()
    _to_page(scr)
    _key(scr)
    greys = []
    for _ in range(200):
        if scr.phase != "fade_in":
            break
        scr.update(FRAME)
        greys.append(scr.grey)
    # for (input = 0; input < 256; input += 16) WinText(input)
    assert greys[0] == 0
    assert sorted(set(greys)) == list(range(0, 256, 16))
    assert greys == sorted(greys)
    assert scr.phase == "epilogue" and scr.grey == 240
    assert 30 <= len(greys) <= 34  # 16 steps of two ticks
    # a key during the fade in does nothing
    scr2 = _won()
    _to_page(scr2)
    _key(scr2)
    scr2.update(FRAME * 4)
    _key(scr2)
    assert scr2.phase == "fade_in"


@pytest.mark.parametrize("size", SIZES)
def test_epilogue_shows_wintext_white_and_yellow(pygame_setup, size):
    scr = _won()
    _to_epilogue(scr)
    surface = pygame.Surface(size)
    scr.render(surface)
    assert [name for name, _ in scr.layout] == list(final.EPILOGUE_LINES)
    rects = [rect for _, rect in scr.layout]
    for rect in rects:
        assert surface.get_rect().contains(rect)
    assert len({r.left for r in rects}) == 1 and len({r.width for r in rects}) == 1
    assert all(a.bottom <= b.top for a, b in zip(rects, rects[1:]))
    assert abs(rects[0].centerx - size[0] // 2) <= size[0] // 320  # centred

    def colours(rect):
        sub = surface.subsurface(rect)
        return {tuple(sub.get_at((x, y)))[:3] for x in range(rect.w) for y in range(rect.h)}

    g = 240
    assert colours(rects[1]) == {(0, 0, 0), (g, g, g)}
    assert colours(rects[-1]) == {(0, 0, 0), (238 * g // 255, 238 * g // 255, 119 * g // 255)}


def test_epilogue_waits_for_a_key_then_fades_out_to_the_title(pygame_setup, asset_mgr):
    p = _party()
    sm = StateMachine(asset_mgr=asset_mgr)
    scr = _won(p, asset_mgr=asset_mgr)
    sm.set_screen(scr)
    _to_epilogue(scr)
    sm.update(600.0)
    assert sm.current_screen is scr and scr.phase == "epilogue"
    _key(scr, pygame.K_q)
    assert scr.phase == "fade_out" and scr.grey == 255
    greys = []
    for _ in range(100):
        if sm.current_screen is not scr:
            break
        sm.update(FRAME)
        greys.append(scr.grey)
        scr.render(pygame.Surface((320, 200)))
    # for (input = 255; input >= 0; input -= 16) WinText(input)
    assert greys[0] == 255  # the fade starts from full white
    assert sorted(set(greys) - {0}, reverse=True) == list(range(255, 0, -16))
    assert greys == sorted(greys, reverse=True)
    title = sm.current_screen
    assert isinstance(title, StartScreen) and title.won and not title.game_over
    assert title.party is p and p.exodus_defeated == 1
    assert sm.screen_stack == [title]


def test_a_click_works_the_key_waits(pygame_setup):
    scr = _won()
    _to_page(scr)
    scr.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5)))
    assert scr.phase == "fade_in"


def test_the_whole_ending_saves_nothing(pygame_setup, asset_mgr, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _party()
    saved = []
    p.autosave_hook = lambda *a, **k: saved.append(1)
    sm = StateMachine(asset_mgr=asset_mgr)
    scr = _won(p, asset_mgr=asset_mgr)
    sm.set_screen(scr)
    play_out_ending(sm)
    assert isinstance(sm.current_screen, StartScreen)
    assert saved == [] and list(tmp_path.iterdir()) == []


def test_ending_renders_every_beat_at_both_sizes(pygame_setup, asset_mgr):
    for size in SIZES:
        sm = StateMachine(asset_mgr=asset_mgr)
        scr = _won(asset_mgr=asset_mgr)
        sm.set_screen(scr)
        surface = pygame.Surface(size)
        seen = set()
        for _ in range(1200):
            if sm.current_screen is not scr:
                break
            seen.add(scr.phase)
            scr.render(surface)
            if scr.phase in ("page", "epilogue"):
                _key(scr)
            sm.update(FRAME)
        assert seen >= {"flash", "page", "fade_in", "epilogue", "fade_out"}
        assert isinstance(sm.current_screen, StartScreen)


def test_the_win_counts_before_any_of_the_ending_plays(pygame_setup):
    """Batches, autoplay and the trace read exodus_defeated (or the four
    card bits) straight after the insert: no key or frame of the ending is
    needed for a run to be recorded as WON."""
    p = _party()
    scr = _won(p, flicker=False)
    assert p.exodus_defeated == 1 and p.exodus_cards_status == 0xF
    assert scr.phase == "card" and scr.card_hits == 0 and scr.flash_colours == []


def test_autoplay_switches_off_when_the_game_is_won(pygame_setup, asset_mgr):
    """The won check comes before the FinalScreen wait: on the ending
    autoplay is off (as the README says), not merely silent."""
    from py_exodus.autoplay import AutoPlayController

    sm = StateMachine(asset_mgr=asset_mgr)
    scr = _won(asset_mgr=asset_mgr, flicker=False)
    sm.set_screen(scr)
    sm.autoplay_enabled = True
    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    ctrl._key_queue.append(pygame.K_SPACE)
    assert ctrl.step(sm) is None
    assert not ctrl.enabled and not sm.autoplay_enabled and not ctrl._key_queue
    assert scr.phase == "card"  # it pressed nothing


def test_autoplay_waits_out_a_cards_flicker_and_stays_on(pygame_setup, asset_mgr):
    from py_exodus.autoplay import AutoPlayController

    p = _party()
    sm, town = _castle(asset_mgr, p, x=30, status=0)
    sm.autoplay_enabled = True
    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    _insert(town, 30, "l")
    scr = sm.current_screen
    assert isinstance(scr, FinalScreen) and not scr.victory
    assert ctrl.step(sm) is None and ctrl.enabled and sm.autoplay_enabled
    for _ in range(200):
        if sm.current_screen is not scr:
            break
        ctrl.update(FRAME, sm)
        sm.update(FRAME)
    assert sm.current_screen is town and ctrl.enabled


def test_autoplay_leaves_every_beat_of_the_ending_alone(pygame_setup, asset_mgr):
    from py_exodus.autoplay import AutoPlayController

    sm = StateMachine(asset_mgr=asset_mgr)
    scr = _won(asset_mgr=asset_mgr, flicker=False)
    sm.set_screen(scr)
    sm.autoplay_enabled = True
    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    seen = set()
    for _ in range(1200):
        if sm.current_screen is not scr:
            break
        seen.add(scr.phase)
        assert ctrl.step(sm) is None  # it presses nothing
        if scr.phase in ("page", "epilogue"):
            _key(scr)  # the player's key
        ctrl.update(FRAME, sm)
        sm.update(FRAME)
    assert seen >= {"card", "flash", "page", "fade_in", "epilogue", "fade_out"}
    assert isinstance(sm.current_screen, StartScreen)
    assert ctrl.step(sm) is None
    assert not ctrl.enabled and not sm.autoplay_enabled
