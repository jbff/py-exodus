"""Unit tests for HUD Text Log, prompt stream, and party stats sidebar."""
from __future__ import annotations

import pygame

from py_exodus.constants import ArmorType, Profession, Race, Sex, Status, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.ui.stats_panel import StatsPanel, inspect_row_color, inspect_rows
from py_exodus.ui.text_log import (
    EGA_BRIGHT_GREEN,
    EGA_LIGHT_GRAY,
    EGA_WHITE,
    EGA_YELLOW,
    TextLog,
)


def test_text_log_prompt():
    """Verify basic text log message addition and interactive prompt flow."""
    log = TextLog(max_lines=5)
    log.add_message("Welcome to Sosaria!")
    assert len(log.lines) == 1

    received: list[str] = []
    log.prompt("Direction?", lambda ans: received.append(ans))
    assert log.is_waiting_for_input
    log.handle_char("N")
    log.handle_enter()
    assert received == ["N"]
    assert not log.is_waiting_for_input


def test_text_log_scrolling_and_history():
    """Verify scrolling caps visible lines to max_lines while preserving history."""
    log = TextLog(max_lines=3)
    for i in range(5):
        log.add_message(f"Message {i}")

    assert len(log.lines) == 3
    assert log.lines == ["Message 2", "Message 3", "Message 4"]
    assert len(log.history) == 5
    assert log.history[0] == "Message 0"


def test_text_log_word_wrapping():
    """Verify long messages wrap neatly to wrap_width."""
    log = TextLog(max_lines=10, wrap_width=20)
    long_msg = "The quick brown fox jumps over the lazy dog."
    log.add_message(long_msg)
    assert len(log.lines) > 1
    for line in log.lines:
        assert len(line) <= 20


def test_text_log_editing_and_cancel():
    """Verify backspace editing and escape cancellation."""
    log = TextLog(max_lines=5)
    received: list[str] = []
    log.prompt("Command:", lambda ans: received.append(ans))

    log.handle_char("T")
    log.handle_char("A")
    log.handle_char("L")
    log.handle_char("K")
    assert log.input_buffer == "TALK"

    log.handle_backspace()
    assert log.input_buffer == "TAL"

    log.handle_escape()
    assert not log.is_waiting_for_input
    assert log.input_buffer == ""
    assert received == []


def test_text_log_chained_prompts():
    """Verify cascading/chained prompts for NPC dialogues or vendor streams without needing enter."""
    log = TextLog(max_lines=5)
    stream_results: list[str] = []

    def on_buy_item(item: str) -> None:
        stream_results.append(item)

    def on_direction(direction: str) -> None:
        stream_results.append(direction)
        # Chain next prompt in dialogue stream
        log.prompt("Buy what? (A-D):", on_buy_item)

    log.prompt("Direction?", on_direction)
    assert log.is_waiting_for_input
    assert log.current_prompt == "Direction?"

    # Instant single-character input immediately advances prompt
    log.handle_char("E")

    # Callback executed and seamlessly installed second prompt
    assert stream_results == ["E"]
    assert log.is_waiting_for_input
    assert log.current_prompt == "Buy what? (A-D):"

    # Second prompt also commits instantly on single character
    log.handle_char("B")
    assert stream_results == ["E", "B"]
    assert not log.is_waiting_for_input


def test_text_log_single_char_and_arrow_keys():
    """Verify single-character auto-commit and arrow key direction auto-submission."""
    log = TextLog(max_lines=5)

    # Multi-char prompt waits for enter
    multi_received: list[str] = []
    log.prompt("Other Command? ", lambda val: multi_received.append(val))
    assert log.single_char is False
    log.handle_char("X")
    assert log.is_waiting_for_input
    assert multi_received == []
    log.handle_enter()
    assert multi_received == ["X"]

    # Direction prompt auto-commits arrow keys
    dir_received: list[str] = []
    log.prompt("Direction? (N,S,E,W):", lambda val: dir_received.append(val))
    assert log.single_char is True

    # Arrow UP key event
    up_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode="")
    consumed = log.handle_event(up_event)
    assert consumed is True
    assert dir_received == ["NORTH"]
    assert not log.is_waiting_for_input

    # Arrow RIGHT key event
    log.prompt("Attack Direction? (N,S,E,W):", lambda val: dir_received.append(val))
    right_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, unicode="")
    assert log.handle_event(right_event) is True
    assert dir_received == ["NORTH", "EAST"]
    assert not log.is_waiting_for_input



# --- Text log scroll-back (user bug 2026-11-09; Java LogScrollPane affordance) ---
# Controller ruling: the mouse wheel always scrolls; PageUp/PageDown always
# work; arrow keys scroll only while the waiting prompt cannot consume them
# (a direction prompt auto-commits them as answers); any key consumed by an
# active prompt returns the view to the bottom first; new lines while scrolled
# up do not yank the view; and there are no pagination pauses inside vendor
# prompts — scroll-back covers review instead.


def _flooded_log(n: int = 12, max_lines: int = 5) -> TextLog:
    """A log whose menu-style history overflows the visible line buffer."""
    log = TextLog(max_lines=max_lines, wrap_width=28)
    for i in range(n):
        log.add_message(f"A - Item {i}: {i}gp")
    return log


def test_scroll_back_reaches_history_beyond_visible_lines():
    """Wheel/offset reveals menu history older than the max_lines buffer."""
    log = _flooded_log()
    assert len(log.lines) == 5  # visible buffer still capped as before
    assert log.scroll_offset == 0

    log.visible_rows = 4
    assert log.scroll_up(2) is True
    assert log.scroll_offset == 2
    assert log.visible_line_texts(4) == [
        "A - Item 6: 6gp",
        "A - Item 7: 7gp",
        "A - Item 8: 8gp",
        "A - Item 9: 9gp",
    ]

    # Clamped at the top of history
    assert log.scroll_up(50) is True
    assert log.scroll_offset == 8  # len(history) - 4 rows
    assert log.visible_line_texts(4)[0] == "A - Item 0: 0gp"
    assert log.scroll_up(1) is False  # already at the top


def test_mouse_wheel_scrolls_history_and_back():
    log = _flooded_log()
    log.visible_rows = 3
    assert log.handle_wheel(pygame.event.Event(pygame.MOUSEWHEEL, y=2)) is True
    assert log.scroll_offset == 2
    assert log.handle_wheel(pygame.event.Event(pygame.MOUSEWHEEL, y=-5)) is True
    assert log.scroll_offset == 0


def test_new_lines_do_not_yank_scrolled_view():
    """While scrolled up, arriving lines keep the view pinned in place."""
    log = _flooded_log(10)
    log.visible_rows = 3
    log.scroll_up(2)
    before = log.visible_line_texts(3)

    log.add_message("New line")
    assert log.scroll_offset == 3  # pinned to the same history content
    assert log.visible_line_texts(3) == before

    # At the bottom the view stays stuck to the newest line
    fresh = _flooded_log(10)
    fresh.visible_rows = 3
    fresh.add_message("Newest")
    assert fresh.scroll_offset == 0
    assert fresh.visible_line_texts(3)[-1] == "Newest"


def test_prompt_answer_snaps_view_to_bottom():
    """Answering a scrolled-away prompt consumes the letter and snaps back."""
    log = _flooded_log(10)
    log.visible_rows = 3
    log.scroll_up(2)
    received: list[str] = []
    log.prompt("Buy what? (A-D):", received.append, single_char=True)
    log.handle_char("A")
    assert received == ["A"]
    assert log.scroll_offset == 0


def test_any_consumed_prompt_key_snaps_view_to_bottom():
    log = _flooded_log(10)
    log.visible_rows = 3
    log.prompt("Other Command? ")
    log.scroll_up(3)

    log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x"))
    assert log.scroll_offset == 0

    # Backspace editing is a consumed key too
    log.scroll_up(3)
    log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, unicode="\b"))
    assert log.scroll_offset == 0


def test_pageup_pagedown_work_without_any_prompt():
    log = _flooded_log()
    log.visible_rows = 4
    assert log.handle_scroll_key(pygame.K_PAGEUP) is True
    assert log.scroll_offset == 4
    assert log.handle_scroll_key(pygame.K_PAGEUP) is True
    assert log.scroll_offset == 8
    assert log.handle_scroll_key(pygame.K_PAGEDOWN) is True
    assert log.scroll_offset == 4
    assert log.handle_scroll_key(pygame.K_PAGEDOWN) is True
    assert log.scroll_offset == 0


def test_pageup_pagedown_work_during_direction_prompt():
    log = _flooded_log()
    log.visible_rows = 4
    received: list[str] = []
    log.prompt("Direction? (N,S,E,W):", received.append)

    log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEUP, unicode=""))
    assert log.scroll_offset == 4
    assert log.is_waiting_for_input

    # In a direction prompt arrows answer (and snap the view back),
    # they never scroll the viewport.
    log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode=""))
    assert received == ["NORTH"]
    assert log.scroll_offset == 0


def test_arrow_keys_scroll_when_prompt_cannot_use_them():
    """Vendor letter prompts leave arrows free for scroll-back."""
    log = _flooded_log()
    log.visible_rows = 4
    received: list[str] = []
    log.prompt("Buy what? (A-D):", received.append, single_char=True)

    log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode=""))
    assert log.scroll_offset == 1
    log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, unicode=""))
    assert log.scroll_offset == 0

    # The arrows never answered the prompt
    assert received == []
    assert log.is_waiting_for_input


def test_oldest_line_reachable_while_prompt_open():
    """The scroll cap counts the prompt row: no line is lost while waiting.

    Fix round: with a prompt open the window shows visible_rows - 1 history
    rows, so the cap must clamp against that count — otherwise the oldest
    line is unreachable exactly in the vendor-menu scenario.
    """
    log = _flooded_log(12)
    log.visible_rows = 5
    received: list[str] = []
    log.prompt("Buy what? (A-D):", received.append, single_char=True)

    assert log.scroll_up(100) is True
    assert log.scroll_offset == 8  # 12 history - (5 rows - 1 prompt row)
    assert log.visible_line_texts(4) == [
        "A - Item 0: 0gp",
        "A - Item 1: 1gp",
        "A - Item 2: 2gp",
        "A - Item 3: 3gp",
    ]
    assert log.scroll_up(1) is False  # oldest line reached

    # Without an open prompt the old cap (visible_rows) still applies
    fresh = _flooded_log(12)
    fresh.visible_rows = 5
    fresh.scroll_up(100)
    assert fresh.scroll_offset == 7  # 12 - 5


def test_opened_prompt_snaps_view_to_bottom():
    """A prompt opening always starts from the bottom-most view."""
    log = _flooded_log(10)
    log.visible_rows = 3
    log.scroll_up(2)
    assert log.scroll_offset == 2

    received: list[str] = []
    log.prompt("Buy what? (A-D):", received.append, single_char=True)
    assert log.scroll_offset == 0
    assert log.visible_line_texts(2)[-1] == "A - Item 9: 9gp"


def test_scroll_indicator_text_shows_offset_while_scrolled():
    log = _flooded_log(10)
    assert log.scroll_indicator_text() == ""
    log.visible_rows = 3
    log.scroll_up(2)
    assert log.scroll_indicator_text() == "▲ 2"
    log.scroll_down(2)
    assert log.scroll_indicator_text() == ""


def test_scrolled_render_draws_indicator():
    pygame.font.init()
    surf = pygame.Surface((320, 200))
    surf.fill((0, 0, 0))
    log = _flooded_log(10)
    log.visible_rows = 2
    log.scroll_up(3)
    log.render(surf, rect=(0, 160, 320, 40))
    yellow = tuple(EGA_YELLOW)
    has_indicator = any(
        surf.get_at((x, y))[:3] == yellow
        for x in range(0, 320)
        for y in range(160, 178)
    )
    assert has_indicator


def test_clear_resets_scroll_offset():
    log = _flooded_log()
    log.visible_rows = 3
    log.scroll_up(2)
    log.clear()
    assert log.scroll_offset == 0
    assert not log.history


def test_log_font_uses_measured_row_budget():
    """Secondary ruling: measured font metrics leave no readable row unused
    (floor: size 10 / linesize 12 — the port never goes below readable)."""
    pygame.font.init()
    log = TextLog(max_lines=5)
    for i in range(12):
        log.add_message(f"row {i}")
    # The real scale-3 log strip: 528x72 native
    big = pygame.Surface((960, 600))
    log.render(big, rect=(0, 528, 528, 72))
    assert log.visible_rows >= 4
    assert log.font_size >= 10
    assert log.visible_line_texts(log.visible_rows)[-1] == "row 11"

    # The 320x200 log strip keeps at least one readable row
    small = pygame.Surface((320, 200))
    log2 = TextLog(max_lines=5)
    for i in range(6):
        log2.add_message(f"row {i}")
    log2.render(small, rect=(0, 176, 176, 24))
    assert log2.visible_rows >= 1
    assert log2.font_size >= 10


def test_text_log_render():
    """Verify rendering text log to a pygame surface with and without prompt."""
    pygame.font.init()
    surf = pygame.Surface((320, 200))
    surf.fill((0, 0, 0))

    log = TextLog(max_lines=5)
    log.add_message("Welcome to Sosaria!")
    log.add_message("Thy path is perilous.")
    log.render(surf, rect=(0, 160, 320, 40))

    # Verify pixels were drawn
    has_non_black = False
    for x in range(320):
        for y in range(160, 200):
            if surf.get_at((x, y))[:3] != (0, 0, 0):
                has_non_black = True
                break
        if has_non_black:
            break
    assert has_non_black

    # Render while waiting for input (prompt with cursor)
    log.prompt("Thou sayest:", lambda _: None)
    log.handle_char("Y")
    log.render(surf, rect=(0, 160, 320, 40))


def test_stats_panel_render_party():
    """Verify rendering party sidebar with all members and transport."""
    pygame.font.init()
    surf = pygame.Surface((320, 200))

    party = Party()
    c1 = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=150, mp=0, food=120)
    c2 = Character("Gwen", "F", Race.ELF, Profession.CLERIC, hp=100, mp=50, food=90)
    party.add_member(c1)
    party.add_member(c2)
    party.transport = Transport.HORSE
    party.food = 350
    party.gold = 500

    panel = StatsPanel()
    panel.render(surf, party)

    # Check non-black pixels in sidebar region (x >= 176)
    drawn_pixels = sum(
        1
        for x in range(176, 320)
        for y in range(200)
        if surf.get_at((x, y))[:3] != (0, 0, 0)
    )
    assert drawn_pixels > 0


def test_stats_panel_active_marker_and_status():
    """Verify active member marker and status abbreviations (G, P, D, A)."""
    party = Party()
    c1 = Character("Pal", "M", Race.HUMAN, Profession.PALADIN, hp=120, mp=20, status=Status.GOOD)
    c2 = Character("Wiz", "M", Race.BOBIT, Profession.WIZARD, hp=80, mp=80, status=Status.POISONED)
    c3 = Character("Thf", "F", Race.FUZZY, Profession.THIEF, hp=0, mp=0, status=Status.DEAD)
    c4 = Character("Clr", "F", Race.DWARF, Profession.CLERIC, hp=0, mp=0, status=Status.ASH)
    party.add_member(c1)
    party.add_member(c2)
    party.add_member(c3)
    party.add_member(c4)
    party.active_member_index = 1

    panel = StatsPanel()
    surf = pygame.Surface((320, 200))
    panel.render(surf, party)

    # Change active player to first member
    party.active_player = 0
    panel.render(surf, party)


def test_stats_panel_inspect_mode():
    """Verify inspection rendering for pooled items, torches, gems, keys, powder."""
    party = Party()
    c = Character(
        "Hero",
        "M",
        Race.HUMAN,
        Profession.FIGHTER,
        hp=200,
        mp=30,
        keys=5,
        gems=8,
        torches=12,
        powder=3,
        food=250,
        gold=1000,
    )
    party.add_member(c)
    party.torch_duration = 45
    party.gold = 1000
    party.food = 500

    panel = StatsPanel()
    surf = pygame.Surface((960, 600))

    # Inspect specific member
    panel.render(surf, party, inspect_index=0)

    # Inspect pooled party resources
    panel.render(surf, party, inspect_index=-1)


# --- Zstats inspect rows (exodus/Party.java:669-715 getZstats column set) ---
# One test per row newly ported from Java getZstats.


def _inspect_member() -> Character:
    """A fully loaded member to exercise every zstats row."""
    c = Character(
        "Hero",
        "M",
        Race.ELF,
        Profession.WIZARD,
        hp=150,
        mp=25,
        exp=450,
        keys=5,
        gems=8,
        torches=12,
        powder=3,
        food=150,
        gold=150,
    )
    c.weapons[WeaponType.MACE] = 2
    c.weapons[WeaponType.SWORD] = 1
    c.weapons[WeaponType.EXOTIC] = 4
    c.armors[ArmorType.LEATHER] = 2
    c.armors[ArmorType.CHAIN] = 1
    c.armors[ArmorType.EXOTIC] = 3
    return c


def test_inspect_row_identity_name_race_sex_class_status():
    """Java line 1: name  Race|Profession|Sex STATUS: G — the name rides the
    identity row (no separate title row)."""
    rows = inspect_rows(_inspect_member())
    assert "HERO ELF M WIZARD ST:G" in rows


def test_inspect_row_identity_sex_other():
    """Sex = Other (original-rules deviation): the compact identity row keeps
    its initial-letter style, so Other shows as "O" (Java's full zstats prints
    "Male"/"Female" proper-case; the compact-label ruling applies, and the
    third initial is "O")."""
    m = _inspect_member()
    m.sex = Sex.OTHER
    rows = inspect_rows(m)
    assert "HERO ELF O WIZARD ST:G" in rows


def test_inspect_row_health_and_maxhealth():
    """Java rows: HEALTH and MAXHEALTH."""
    rows = inspect_rows(_inspect_member())
    assert "HP:150/150" in rows


def test_inspect_row_mana_and_level():
    """Java rows: MANA and LV."""
    rows = inspect_rows(_inspect_member())
    assert "MANA:25 LV:1" in rows


def test_inspect_row_gold_and_food_are_per_member():
    """Java shows GOLD and FOOD from the member record, not party pools."""
    m = _inspect_member()
    m.gold = 777
    rows = inspect_rows(m)
    assert "GOLD:777 FOOD:150" in rows


def test_inspect_row_armor_inventory_uses_xml_names_and_java_rule():
    """Java lists every standard armor type (even 0-count) with its count,
    two per line, EXOTIC appended only when > 0 (exodus/Party.java:673-697);
    names come from armors.xml, e.g. "Exotic Armour"."""
    rows = inspect_rows(_inspect_member())
    assert " Cloth: 0  Leather: 2" in rows
    assert " Chain: 1  Plate: 0" in rows
    assert " Chain +2: 0  Plate +2: 0" in rows
    assert " Exotic Armour: 3" in rows


def test_inspect_row_weapon_inventory_uses_xml_names_and_java_rule():
    """Weapon listing: every standard type in weapons.xml order (even 0),
    then "Exotic Weapon" only when owned."""
    rows = inspect_rows(_inspect_member())
    assert " Dagger: 0  Mace: 2" in rows
    assert " Sword: 1  Sling: 0" not in rows  # pairs follow enum order
    assert " Bow: 0  Sword: 1" in rows
    assert " 2-Handed Sword: 0  Axe +2: 0" in rows
    assert " Exotic Weapon: 4" in rows


def test_inspect_row_exotic_listed_only_when_owned():
    """EXOTIC entries are conditional: absent at 0, present when > 0."""
    m = _inspect_member()
    m.armors[ArmorType.EXOTIC] = 0
    m.weapons[WeaponType.EXOTIC] = 0
    text = "\n".join(inspect_rows(m))
    assert "Exotic Armour" not in text
    assert "Exotic Weapon" not in text


def test_inspect_row_lists_zero_count_standard_types():
    """A bare member still lists every standard type with 0 (Java rule)."""
    m = Character("Bare", "M", Race.HUMAN, Profession.FIGHTER, hp=100, mp=0)
    text = "\n".join(inspect_rows(m))
    assert "Dagger: 0" in text
    assert "Cloth: 0" in text


def test_inspect_row_colors():
    """Inventory rows render gray; supply and mark/card rows render green."""
    assert inspect_row_color(" Cloth: 0  Leather: 2") == EGA_LIGHT_GRAY
    assert inspect_row_color(" Exotic Weapon: 4") == EGA_LIGHT_GRAY
    assert inspect_row_color("KEYS:5 POWD:3") == EGA_BRIGHT_GREEN
    assert inspect_row_color("MARK KINGS: 1") == EGA_BRIGHT_GREEN
    assert inspect_row_color("HP:150/150") == EGA_WHITE


def test_stats_panel_render_inspect_rows_smoke(pygame_setup):
    """StatsPanel draws the ported zstats rows in inspect mode."""
    panel = StatsPanel()
    party = Party()
    party.add_member(_inspect_member())
    for size in ((320, 200), (960, 600)):
        surf = pygame.Surface(size)
        panel.render(surf, party, inspect_index=0)


def test_stats_panel_scaled_resolution():
    """Verify StatsPanel renders seamlessly at 960x600 integer scaled resolution."""
    pygame.font.init()
    surf = pygame.Surface((960, 600))
    party = Party()
    party.add_member(Character("Ranger", "M", Race.ELF, Profession.RANGER))
    party.transport = Transport.SHIP
    party.ship_hull = 42

    panel = StatsPanel()
    panel.render(surf, party)

    # Check that pixels are rendered on right side of 960x600 screen (x >= 528)
    drawn_pixels = sum(
        1
        for x in range(540, 960, 4)
        for y in range(0, 600, 4)
        if surf.get_at((x, y))[:3] != (0, 0, 0)
    )
    assert drawn_pixels > 0


# --- Screen-level scroll-back routing (overworld/town share the same paths) ---


def _screen_party() -> Party:
    return Party(
        [
            PartyMember(
                Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100)
            )
        ],
        x=10,
        y=10,
    )


def _fill_screen_log(screen) -> None:
    for i in range(12):
        screen.text_log.add_message(f"L{i}")
    screen.text_log.visible_rows = 3


def test_town_screen_routes_wheel_and_page_keys_to_log():
    from py_exodus.screens.town import TownScreen

    town = TownScreen(party=_screen_party(), map_id=1)
    _fill_screen_log(town)

    town.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=2))
    assert town.text_log.scroll_offset == 2

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEUP))
    assert town.text_log.scroll_offset == 5

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEDOWN))
    assert town.text_log.scroll_offset == 2


def test_town_wheel_scrolls_during_vendor_letter_prompt():
    """The wheel works while a single-letter vendor prompt is waiting."""
    from py_exodus.screens.town import TownScreen

    town = TownScreen(party=_screen_party(), map_id=1)
    _fill_screen_log(town)
    received: list[str] = []
    town.text_log.prompt("Buy what? (A-D):", received.append, single_char=True)

    town.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1))
    assert town.text_log.scroll_offset == 1
    assert received == []

    # Answering the letter still works against the bottom-most view
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a"))
    assert received == ["a"]
    assert town.text_log.scroll_offset == 0


def test_town_arrows_do_not_scroll_log_when_free():
    """With no prompt the arrows stay avatar-command keys (never scroll)."""
    from py_exodus.screens.town import TownScreen

    town = TownScreen(party=_screen_party(), map_id=1)
    _fill_screen_log(town)
    offset_before = town.text_log.scroll_offset
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    assert town.text_log.scroll_offset == offset_before


def test_overworld_wheel_blocked_while_gem_view_active():
    """Peer-gem view owns all input: wheel neither scrolls nor closes it."""
    from py_exodus.screens.overworld import OverworldScreen

    ow = OverworldScreen(
        party=_screen_party(), map_id=0, asset_mgr=None, random_encounters=False
    )
    _fill_screen_log(ow)
    ow.gem_view_active = True

    ow.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=2))
    assert ow.text_log.scroll_offset == 0
    assert ow.gem_view_active is True

    # Any key still closes the gem view as before
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    assert ow.gem_view_active is False
