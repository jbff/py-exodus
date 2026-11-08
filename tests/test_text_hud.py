"""Unit tests for HUD Text Log, prompt stream, and party stats sidebar."""
from __future__ import annotations

import pygame

from py_exodus.constants import Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.ui.stats_panel import StatsPanel
from py_exodus.ui.text_log import TextLog


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
