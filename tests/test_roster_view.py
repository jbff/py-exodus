"""The roster screen's new look (L&F item 8): THE PARTY and A NEW ADVENTURER.

The keys and rules are the old ones; these tests pin the new list scrolling,
the arrow-key creation steps, the stats rules and that nothing drawn spills
out of its card at either size."""
import pygame
import pytest

from py_exodus.constants import ArmorType, Profession, Race, Sex, Status, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.roster_screen import RosterScreen
from py_exodus.ui import roster_view


def _char(name, race=Race.HUMAN, prof=Profession.FIGHTER, status=Status.GOOD):
    c = Character(name, Sex.MALE, race, prof, strength=15, dexterity=15, intelligence=10, wisdom=10,
                  hp=150, max_hp=150, food=150, gold=150, weapon=WeaponType.DAGGER, armor=ArmorType.CLOTH)
    c.status = status
    return c


def _key(scr, key, uni=""):
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=uni, mod=0))


def _type(scr, text):
    for ch in text:
        k = pygame.K_RETURN if ch == "\r" else getattr(pygame, "K_" + ch.lower(), pygame.K_UNKNOWN)
        _key(scr, k, ch)


def _screen(n, **kw):
    return RosterScreen(party=Party(members=[]), roster=[_char(f"Hero{i + 1}") for i in range(n)], **kw)


def _no_overflow(cv, surface):
    bounds = surface.get_rect()
    for text, r, box in cv.log:
        assert bounds.contains(r), f"{text!r} {r} leaves the screen"
        # Each text sits on its own line; what may spill is its width.
        assert box.left <= r.left and r.right <= box.right, f"{text!r} {r} leaves its box {box}"


# -- the list of 20 ---------------------------------------------------------


def test_scroll_offset_keeps_the_selection_in_view():
    assert roster_view.scroll_offset(0, 0) == 0
    assert roster_view.scroll_offset(9, 0) == 0
    assert roster_view.scroll_offset(10, 0) == 1
    assert roster_view.scroll_offset(19, 0) == 10
    assert roster_view.scroll_offset(12, 10) == 10  # still in view: no move
    assert roster_view.scroll_offset(3, 10) == 3


def test_scroll_hints_name_the_rows_out_of_view():
    assert roster_view.scroll_hints(0, 7) == (None, None)
    assert roster_view.scroll_hints(0, 11) == (None, "Row 11 below (Down)")
    assert roster_view.scroll_hints(0, 20) == (None, "Rows 11-20 below (Down)")
    assert roster_view.scroll_hints(3, 14) == ("Rows 1-3 above (Up)", "Row 14 below (Down)")
    assert roster_view.scroll_hints(4, 14) == ("Rows 1-4 above (Up)", None)
    assert roster_view.scroll_hints(1, 20) == ("Row 1 above (Up)", "Rows 12-20 below (Down)")


def test_down_past_row_ten_scrolls_the_list(pygame_setup):
    scr = _screen(14)
    for _ in range(12):
        _key(scr, pygame.K_DOWN)
    assert scr.selected_roster_idx == 12
    assert scr.roster_scroll_offset == 3
    # Up from the top wraps to the last character, which comes into view.
    for _ in range(13):
        _key(scr, pygame.K_UP)
    assert scr.selected_roster_idx == 13
    assert scr.roster_scroll_offset == 4
    # Adding the scrolled-to character works on the row selected.
    _key(scr, pygame.K_a)
    assert scr.party.members[0].character is scr.roster[13]


def test_scrolled_list_draws_rows_eleven_on(pygame_setup):
    scr = _screen(14)
    for _ in range(12):
        _key(scr, pygame.K_DOWN)
    surf = pygame.Surface((960, 600))
    cv = roster_view.render_roster(surf, scr)
    drawn = [t for t, _, _ in cv.log]
    assert "HERO11" in drawn and "HERO13" in drawn
    assert "HERO1" not in drawn and "HERO14" not in drawn  # rows 1-3 and 14 out of view
    assert "Rows 1-3 above (Up)" in drawn and "Row 14 below (Down)" in drawn
    _no_overflow(cv, surf)


# -- the keys keep their outcomes ---------------------------------------------


def test_tab_and_r_remove_the_chosen_party_member(pygame_setup):
    scr = _screen(3)
    _key(scr, pygame.K_a)
    _key(scr, pygame.K_DOWN)
    _key(scr, pygame.K_a)
    _key(scr, pygame.K_TAB)
    assert scr.focus_panel == "party"
    _key(scr, pygame.K_UP)  # wraps to place 4, then up to place 1
    _key(scr, pygame.K_UP)
    _key(scr, pygame.K_UP)
    _key(scr, pygame.K_UP)
    assert scr.selected_party_idx == 0
    _key(scr, pygame.K_r)
    assert [m.name for m in scr.party.members] == ["Hero2"]
    _key(scr, pygame.K_RIGHT)
    assert scr.focus_panel == "roster"


def test_p_saves_and_esc_goes_back(pygame_setup, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scr = _screen(2)
    _key(scr, pygame.K_a)
    _key(scr, pygame.K_p)
    assert (tmp_path / "saves" / "roster.json").exists()
    assert (tmp_path / "saves" / "party.json").exists()
    assert scr.is_finished
    scr2 = _screen(1)
    _key(scr2, pygame.K_ESCAPE)
    assert scr2.is_finished


def test_the_key_chips_are_the_real_keys():
    keys = [k for k, _ in roster_view.ROSTER_KEYS]
    assert keys == ["A", "R", "C", "D", "X", "P", "Tab", "Enter", "Esc"]


# -- creation: five steps, arrows or letters -----------------------------------


def test_creation_by_arrows_and_enter(pygame_setup):
    scr = _screen(0)
    _key(scr, pygame.K_c)
    assert scr._create_step == 0
    _type(scr, "Arwen\r")
    assert scr._create_step == 1
    _key(scr, pygame.K_DOWN)  # Female
    _key(scr, pygame.K_RETURN, "\r")
    assert scr._create_step == 2
    _key(scr, pygame.K_DOWN)  # Elf
    _key(scr, pygame.K_RETURN, "\r")
    for _ in range(6):  # Fighter .. Ranger
        _key(scr, pygame.K_DOWN)
    _key(scr, pygame.K_RETURN, "\r")
    assert scr._create_step == 4
    assert scr.points_left() == 30
    for _ in range(10):
        _key(scr, pygame.K_RIGHT)
    _key(scr, pygame.K_DOWN)
    for _ in range(15):
        _key(scr, pygame.K_RIGHT)
    _key(scr, pygame.K_DOWN)
    for _ in range(5):
        _key(scr, pygame.K_RIGHT)
    assert scr.points_left() == 0
    _key(scr, pygame.K_RETURN, "\r")
    assert scr._create_step is None
    c = scr.roster[-1]
    assert (c.name, c.sex, c.race, c.profession) == ("Arwen", Sex.FEMALE, Race.ELF, Profession.RANGER)
    assert (c.strength, c.dexterity, c.intelligence, c.wisdom) == (15, 20, 10, 5)
    assert c.hp == 150 and c.food == 150 and c.gold == 150
    assert c.weapon == WeaponType.DAGGER and c.armor == ArmorType.CLOTH
    assert c.mp == c.compute_max_mp()
    assert not scr.text_log.is_waiting_for_input


def test_enter_on_untouched_race_and_class_gives_the_old_defaults(pygame_setup):
    """The first of each list is what an unknown letter always gave."""
    scr = _screen(0)
    _key(scr, pygame.K_c)
    _type(scr, "Bo\r")
    _key(scr, pygame.K_RETURN, "\r")
    _key(scr, pygame.K_RETURN, "\r")
    _key(scr, pygame.K_RETURN, "\r")
    assert scr._new_char_data["sex"] == Sex.MALE
    assert scr._new_char_data["race"] == Race.HUMAN
    assert scr._new_char_data["prof"] == Profession.FIGHTER


def test_letters_still_answer_each_step(pygame_setup):
    scr = _screen(0)
    _key(scr, pygame.K_c)
    _type(scr, "Gimli\r")
    _type(scr, "F")
    _type(scr, "D")
    _type(scr, "B")
    assert scr._new_char_data["prof"] == Profession.BARBARIAN
    for v in ("25\r", "15\r", "5\r", "5\r"):
        _type(scr, v)
    c = scr.roster[-1]
    assert (c.name, c.race, c.strength, c.dexterity) == ("Gimli", Race.DWARF, 25, 15)


def test_the_stats_need_every_point_shared_before_enter(pygame_setup):
    scr = _screen(0)
    _key(scr, pygame.K_c)
    _type(scr, "Al\r")
    _type(scr, "M")
    _type(scr, "F")  # Fuzzy
    _type(scr, "W")
    assert scr._create_step == 4
    _key(scr, pygame.K_LEFT)  # 5 is the floor
    assert scr._new_char_data["stats"][0] == 5
    for _ in range(30):
        _key(scr, pygame.K_RIGHT)
    assert scr._new_char_data["stats"][0] == 25  # 25 is the ceiling
    _key(scr, pygame.K_RETURN, "\r")
    assert scr._create_step == 4 and not scr.roster  # 10 left: refused
    assert "10 points left" in scr._create_note
    _key(scr, pygame.K_DOWN)
    for _ in range(20):
        _key(scr, pygame.K_RIGHT)
    assert scr._new_char_data["stats"][1] == 15  # no points left to add
    assert scr.points_left() == 0
    _key(scr, pygame.K_RETURN, "\r")
    assert len(scr.roster) == 1


def test_stat_limit_is_25_or_the_race_maximum(pygame_setup):
    scr = _screen(0)
    scr._new_char_data = {"race": Race.FUZZY}
    assert [scr.stat_limit(i) for i in range(4)] == [25, 25, 25, 25]
    assert all(min(25, cap) == 25 for r in Race for cap in (r.max_str, r.max_dex, r.max_int, r.max_wis))


def test_esc_goes_back_a_step_and_cancels_at_the_name(pygame_setup):
    scr = _screen(0)
    _key(scr, pygame.K_c)
    _type(scr, "Ann\r")
    _type(scr, "F")
    _type(scr, "E")
    assert scr._create_step == 3
    _key(scr, pygame.K_ESCAPE)
    assert scr._create_step == 2
    assert "Race" in scr.text_log.current_prompt
    assert scr._create_cursor == 1  # Elf, as chosen before
    _key(scr, pygame.K_ESCAPE)
    _key(scr, pygame.K_ESCAPE)
    assert scr._create_step == 0
    assert scr.text_log.input_buffer == "Ann"
    _key(scr, pygame.K_ESCAPE)
    assert scr._create_step is None
    assert not scr.text_log.is_waiting_for_input
    assert not scr.roster


def test_creation_preview_fills_in_as_you_go(pygame_setup):
    scr = _screen(0)
    _key(scr, pygame.K_c)
    _type(scr, "Mo")
    v = scr.creation_view()
    assert v["name"] == "Mo" and v["prof"] is None
    _type(scr, "\rM")
    _key(scr, pygame.K_DOWN)
    _key(scr, pygame.K_DOWN)  # hovering Dwarf
    v = scr.creation_view()
    assert v["race"] == Race.DWARF and v["race_done"] is None


# -- drawing ----------------------------------------------------------------------


def _states():
    """(name, screen) in every state the screen draws."""
    long = "W" * 12
    roster = [_char(long, Race.BOBBIT, Profession.ILLUSIONIST), _char("Tobias", status=Status.DEAD),
              _char("Ash", status=Status.ASH), _char("Pip", status=Status.POISONED)]
    roster += [_char(f"Hero{i}") for i in range(16)]
    party = Party(members=[])
    for c in roster[:4]:
        party.add_member(c)
    main = RosterScreen(party=party, roster=roster)
    main.party_formed = False
    yield "main", main
    scrolled = RosterScreen(party=Party(members=[]), roster=list(roster))
    for _ in range(15):
        _key(scrolled, pygame.K_DOWN)
    yield "scrolled", scrolled
    focus = RosterScreen(party=party, roster=roster)
    _key(focus, pygame.K_TAB)
    yield "party focus", focus
    yield "empty", RosterScreen(party=Party(members=[]), roster=[])
    c = RosterScreen(party=Party(members=[]), roster=[])
    _key(c, pygame.K_c)
    _type(c, "WWWWWWWWWWWWWWW")
    yield "create name", c
    _type(c, "\r")
    yield "create sex", c
    _type(c, "M")
    yield "create race", c
    _type(c, "B")
    for _ in range(8):
        _key(c, pygame.K_DOWN)
    yield "create class", c
    _type(c, "I")
    _key(c, pygame.K_RETURN, "\r")
    yield "create stats", c


@pytest.mark.parametrize("size", [(960, 600), (320, 200)])
def test_every_state_renders_with_no_text_out_of_its_box(pygame_setup, size):
    for name, scr in _states():
        surf = pygame.Surface(size)
        if scr._create_step is None:
            cv = roster_view.render_roster(surf, scr)
        else:
            cv = roster_view.render_creation(surf, scr)
        assert cv.log, name
        _no_overflow(cv, surf)
        scr.render(surf)  # the screen's own entry point draws the same


def test_a_dead_character_is_tagged(pygame_setup):
    dead = _char("Tobias", status=Status.DEAD)
    scr = RosterScreen(party=Party(members=[]), roster=[_char("Ann"), dead])
    _key(scr, pygame.K_DOWN)
    surf = pygame.Surface((960, 600))
    cv = roster_view.render_roster(surf, scr)
    tags = [r for t, r, _ in cv.log if t == "dead"]
    assert len(tags) == 2  # its row and its detail card
    assert roster_view.status_tag(dead)[0] == "dead"
    assert roster_view.status_tag(_char("Ash", status=Status.ASH))[0] == "ashes"
    assert roster_view.status_tag(_char("Ann")) is None


def test_the_titles(pygame_setup):
    scr = _screen(1)
    cv = roster_view.render_roster(pygame.Surface((960, 600)), scr)
    assert cv.log[0][0] == "THE PARTY"
    _key(scr, pygame.K_c)
    cv = roster_view.render_creation(pygame.Surface((960, 600)), scr)
    assert cv.log[0][0] == "A NEW ADVENTURER"
