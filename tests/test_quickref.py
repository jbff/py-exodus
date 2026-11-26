"""Quick-reference cards: F3 commands, F4 spells (look & feel item 3).

The card's command table must match what each screen's key handler
actually does: S Sosaria (and Ambrosia), T town/castle, D dungeon, C combat.
"""
from __future__ import annotations

import inspect
import re

import pygame
import pytest

from py_exodus.constants import Spell
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.quickref import (
    COMMANDS,
    SPELL_EFFECTS,
    QuickRefScreen,
    spell_where,
)
from py_exodus.state_machine import StateMachine


def _key(sm_or_screen, k: int, unicode: str = "") -> None:
    sm_or_screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode))


def _flags(letter: str) -> str:
    for cmd in COMMANDS:
        if cmd.key == letter:
            return cmd.where
    raise KeyError(letter)


def _letters_in(func) -> set[str]:
    """The single letters a handler tests with ``pygame.K_<x>``."""
    src = inspect.getsource(func)
    return {m.upper() for m in re.findall(r"pygame\.K_([a-z])\b", src)}


# --- the command table ------------------------------------------------------


def test_every_letter_and_space_is_on_the_card():
    keys = [c.key for c in COMMANDS]
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        assert ch in keys
    assert "Spc" in keys
    assert len(keys) == len(set(keys))
    for c in COMMANDS:
        assert c.where and set(c.where) <= set("STDC"), c


def test_sosaria_flags_match_the_overworld_handler():
    from py_exodus.screens.overworld import OverworldScreen

    handled = _letters_in(OverworldScreen.handle_event)
    # D, I and K have no branch: they fall through to the pass tail.
    assert not {"D", "I", "K"} & handled
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if "S" in _flags(ch):
            assert ch in handled, ch
        else:
            # Steal / Transact / Unlock have a branch on Sosaria but nothing
            # there to steal from, talk to or unlock (counters, people and
            # doors are town tiles); everything else unflagged has no branch.
            assert ch not in handled or ch in "STU", ch


def test_town_flags_match_the_town_handler():
    from py_exodus.screens.town import TownScreen

    handled = _letters_in(TownScreen.handle_event)
    refused = {"Q"}  # "Cannot save here!"
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if "T" in _flags(ch):
            assert ch in handled and ch not in refused, ch
        else:
            # E has a branch, but no town or castle holds a portal.
            assert ch not in handled or ch in refused or ch == "E", ch


def test_town_q_refuses(pygame_setup, asset_mgr):
    from py_exodus.screens.town import TownScreen

    t = TownScreen(party=_party(), map_id=3, asset_mgr=asset_mgr)
    _key(t, pygame.K_q)
    assert any("Cannot save here!" in m for m in _log(t))


def test_dungeon_flags_match_the_dungeon_handler():
    from py_exodus.screens.dungeon_screen import _NOT_DNG_CMD_KEYS, DungeonScreen

    handled = _letters_in(DungeonScreen._dispatch_command)
    refused = {pygame.key.name(k).upper() for k in _NOT_DNG_CMD_KEYS}
    assert refused == set("ABEFLQSTUX")
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        accepted = ch in handled and ch not in refused
        assert ("D" in _flags(ch)) == accepted, ch


def test_combat_flags_match_the_combat_handler():
    from py_exodus.screens.combat_screen import CombatScreen

    handled = _letters_in(CombatScreen._on_combat_key) | {"Z"}
    assert "Z" in _letters_in(CombatScreen.handle_event)
    # P in combat is a second pass key (listed on the Pass row), not Peer.
    handled.discard("P")
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        assert ("C" in _flags(ch)) == (ch in handled), ch
    assert "C" in _flags("Spc") and "C" in _flags("Tab")


# --- spell cards ------------------------------------------------------------


def test_every_spell_has_a_one_line_effect():
    assert set(SPELL_EFFECTS) == set(Spell)
    for sp, text in SPELL_EFFECTS.items():
        assert text and "\n" not in text and len(text) <= 52, sp


def test_spell_where_follows_the_location_mask():
    assert spell_where(Spell.MITTAR) == "combat"
    assert spell_where(Spell.LORUM) == "dungeon"
    assert spell_where(Spell.DAG_ACRON) == "Sosaria"
    assert spell_where(Spell.FAL_DIVI) == "anywhere"
    assert spell_where(Spell.SURMANDUM) == "not in combat"
    assert spell_where(Spell.APPAR_UNEM) == "not in combat"
    assert spell_where(Spell.VIEDA) == "Sosaria, town"


# --- opening, switching, closing --------------------------------------------


class _Game(BaseScreen):
    allows_quick_reference = True

    def __init__(self):
        super().__init__()
        self.keys: list[int] = []
        self.updates = 0

    def handle_event(self, event):
        self.keys.append(event.key)

    def update(self, dt):
        self.updates += 1


def _sm():
    game = _Game()
    return StateMachine(initial_screen=game), game


def test_f3_opens_commands_and_f3_closes(pygame_setup):
    sm, game = _sm()
    _key(sm, pygame.K_F3)
    assert isinstance(sm.current_screen, QuickRefScreen)
    assert sm.current_screen.card == "commands"
    _key(sm, pygame.K_F3)
    assert sm.current_screen is game
    assert game.keys == []


def test_f4_opens_spells_tab_switches_and_is_remembered(pygame_setup):
    sm, game = _sm()
    _key(sm, pygame.K_F4)
    assert sm.current_screen.card == "wizard"
    _key(sm, pygame.K_TAB)
    assert sm.current_screen.card == "cleric"
    _key(sm, pygame.K_TAB)
    _key(sm, pygame.K_TAB)
    assert sm.current_screen.card == "cleric"
    _key(sm, pygame.K_x, "x")  # any other key closes
    assert sm.current_screen is game
    _key(sm, pygame.K_F4)
    assert sm.current_screen.card == "cleric"
    _key(sm, pygame.K_F4)
    assert sm.current_screen is game
    assert game.keys == []


def test_f3_and_f4_switch_cards(pygame_setup):
    sm, game = _sm()
    _key(sm, pygame.K_F4)
    _key(sm, pygame.K_F3)
    assert sm.current_screen.card == "commands"
    _key(sm, pygame.K_F4)
    assert sm.current_screen.card in ("wizard", "cleric")
    assert len(sm.screen_stack) == 2


def test_modifier_keys_do_not_close_and_tab_on_commands_closes(pygame_setup):
    sm, game = _sm()
    _key(sm, pygame.K_F3)
    _key(sm, pygame.K_LSHIFT)
    assert isinstance(sm.current_screen, QuickRefScreen)
    _key(sm, pygame.K_ESCAPE)
    assert sm.current_screen is game


def test_f1_on_the_card_closes_it(pygame_setup):
    sm, game = _sm()
    _key(sm, pygame.K_F3)
    _key(sm, pygame.K_F1)
    assert sm.current_screen is game


def test_game_is_paused_while_open(pygame_setup):
    sm, game = _sm()
    _key(sm, pygame.K_F3)
    for _ in range(100):
        sm.update(0.25)
    assert game.updates == 0
    _key(sm, pygame.K_SPACE)
    sm.update(0.25)
    assert game.updates == 1


def test_not_offered_on_title_or_plain_screens(pygame_setup):
    sm = StateMachine(initial_screen=BaseScreen())
    _key(sm, pygame.K_F3)
    _key(sm, pygame.K_F4)
    assert not isinstance(sm.current_screen, QuickRefScreen)


@pytest.mark.parametrize(
    "module,cls",
    [
        ("py_exodus.screens.overworld", "OverworldScreen"),
        ("py_exodus.screens.town", "TownScreen"),
        ("py_exodus.screens.dungeon_screen", "DungeonScreen"),
        ("py_exodus.screens.combat_screen", "CombatScreen"),
    ],
)
def test_game_screens_offer_the_cards(module, cls):
    import importlib

    assert getattr(importlib.import_module(module), cls).allows_quick_reference


def test_overworld_f3_pauses_the_idle_pass(pygame_setup, asset_mgr):
    from py_exodus.screens.overworld import OverworldScreen

    ow = OverworldScreen(party=_party(), map_id=0, asset_mgr=asset_mgr, start_x=40, start_y=40)
    ow.party.x, ow.party.y = 40, 40
    ow.creatures = []
    sm = StateMachine(initial_screen=ow)
    moves = ow.party.moves
    _key(sm, pygame.K_F3)
    for _ in range(600):
        sm.update(1 / 60)
    assert ow.party.moves == moves
    _key(sm, pygame.K_ESCAPE)
    assert sm.current_screen is ow


# --- drawing ----------------------------------------------------------------


@pytest.mark.parametrize("size", [(960, 600), (320, 200)])
@pytest.mark.parametrize("card", ["commands", "wizard", "cleric"])
def test_cards_render(pygame_setup, size, card):
    sm, game = _sm()
    sm.push_screen(QuickRefScreen(card=card))
    surf = pygame.Surface(size)
    sm.render(surf)
    assert surf.get_at((size[0] // 2, size[1] // 2)) is not None


def test_commands_rows_fit_their_column(pygame_setup):
    from py_exodus.screens.quickref import command_row_overflows

    assert command_row_overflows(3) == []


def test_spell_rows_fit_their_column(pygame_setup):
    from py_exodus.screens.quickref import spell_row_overflows

    assert spell_row_overflows(3) == []


# --- helpers ----------------------------------------------------------------


def _party():
    from py_exodus.constants import Profession
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party

    p = Party()
    p.add_member(Character(name="Hero", profession=Profession.FIGHTER, hp=200, max_hp=300))
    return p


def _log(screen) -> list[str]:
    tl = screen.text_log
    msgs = getattr(tl, "messages", None) or getattr(tl, "lines", None) or []
    return [str(m) for m in msgs]
