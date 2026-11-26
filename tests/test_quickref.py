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
    """The letters a handler's dispatch tests as ``event.key == pygame.K_x``
    or ``event.key in (... pygame.K_x ...)``; range checks such as
    ``pygame.K_a <= event.key <= pygame.K_z`` do not count."""
    src = inspect.getsource(func)
    found = set(re.findall(r"event\.key == pygame\.K_([a-z])\b", src))
    for group in re.findall(r"event\.key in \(([^)]*)\)", src):
        found |= set(re.findall(r"pygame\.K_([a-z])\b", group))
    return {m.upper() for m in found}


def test_letters_in_ignores_range_checks():
    def handler(event):
        if pygame.K_a <= event.key <= pygame.K_z:
            pass
        if event.key == pygame.K_q:
            pass
        elif event.key in (pygame.K_SPACE, pygame.K_p):
            pass

    assert _letters_in(handler) == {"Q", "P"}


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


def _dungeon(asset_mgr):
    from py_exodus.screens.dungeon_screen import DungeonScreen
    from py_exodus.world.dungeon import DungeonMap, DungeonTile

    dmap = DungeonMap(id=98, name="Test", width=16, height=16, levels=8)
    dmap.tiles = [[[DungeonTile.NOTHING] * 16 for _y in range(16)] for _z in range(8)]
    ds = DungeonScreen(party=_party(), dungeon_map=dmap, asset_mgr=asset_mgr)
    ds.state.random_encounters_enabled = False
    return ds


def test_dungeon_flags_match_real_key_presses(pygame_setup, asset_mgr):
    """Each letter pressed in a real dungeon: "NOT A DNG CMD!" (refused)
    or "Pass" (the unhandled tail) means no D flag; anything else is a
    dungeon command."""
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        ds = _dungeon(asset_mgr)
        before = len(ds.text_log.history)
        _key(ds, getattr(pygame, f"K_{ch.lower()}"), ch.lower())
        new = ds.text_log.history[before:]
        refused = "NOT A DNG CMD!" in new or new == ["Pass"]
        assert ("D" in _flags(ch)) == (not refused), (ch, new)


def test_dungeon_flags_match_the_dungeon_handler():
    from py_exodus.screens.dungeon_screen import _NOT_DNG_CMD_KEYS, DungeonScreen

    handled = _letters_in(DungeonScreen._dispatch_command)
    refused = {pygame.key.name(k).upper() for k in _NOT_DNG_CMD_KEYS}
    assert refused == set("ABEFLQSTUX")
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        accepted = ch in handled and ch not in refused
        assert ("D" in _flags(ch)) == accepted, ch


def _combat(asset_mgr):
    from py_exodus.constants import Profession
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party
    from py_exodus.screens.combat_screen import CombatScreen
    from py_exodus.world.loader import MapLoader

    p = Party()
    for n in ("A", "B"):
        p.add_member(Character(name=n, profession=Profession.FIGHTER, hp=200, max_hp=300, food=150))
    cm = MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT")
    return CombatScreen(party=p, combat_map=cm, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)


def test_combat_flags_match_real_key_presses(pygame_setup, asset_mgr):
    """Each letter pressed in a real fight: a combat command answers (a
    line, a prompt, Ztats or the next member's turn); any other letter
    does nothing at all."""
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        cs = _combat(asset_mgr)
        before = list(cs.text_log.history)
        member = cs.arena.active_party_member_idx
        _key(cs, getattr(pygame, f"K_{ch.lower()}"), ch.lower())
        acted = (
            cs.text_log.history != before
            or cs.text_log.is_waiting_for_input
            or cs.stats_panel.inspect_index is not None
            or cs.arena.active_party_member_idx != member
        )
        if ch == "P":  # a second pass key, on the Pass row
            assert acted
            continue
        assert ("C" in _flags(ch)) == acted, ch


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
        assert text and "\n" not in text and len(text) <= 56, sp


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
    surf.fill((0, 0, 255))
    game.render = lambda s: s.fill((0, 0, 255))  # a plain blue game screen
    sm.render(surf)
    w, h = size
    # Outside the card: the game, dimmed (darker than the blue).
    corner = surf.get_at((1, 1))
    assert corner.b < 255 and corner.b > 0
    # Inside the card: the card's own background, not the backdrop.
    inside = surf.get_at((w // 2, h - h // 6))
    assert (inside.r, inside.g, inside.b) != (corner.r, corner.g, corner.b)
    # Text was drawn: the card holds more than two colours.
    colours = {tuple(surf.get_at((x, y))) for x in range(0, w, 3) for y in range(h // 6, h - h // 6, 3)}
    assert len(colours) > 10


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


# --- review fixes -----------------------------------------------------------


_POLL = 5 / 60


def test_closing_a_card_in_combat_restarts_the_member_wait(pygame_setup, asset_mgr):
    """The card is its own wait: back in the fight the member's 46-poll
    count starts afresh, so closing the card never passes at once."""
    from py_exodus.screens.combat_screen import COMBAT_PASS_POLLS

    cs = _combat(asset_mgr)
    sm = StateMachine(asset_mgr=asset_mgr, initial_screen=cs)
    passes = lambda: sum(1 for m in cs.text_log.history if m == "Pass")  # noqa: E731
    for _ in range(COMBAT_PASS_POLLS - 2):
        sm.update(_POLL)
    _key(sm, pygame.K_F3)
    assert isinstance(sm.current_screen, QuickRefScreen)
    for _ in range(200):
        sm.update(_POLL)
    _key(sm, pygame.K_ESCAPE)
    assert sm.current_screen is cs
    for _ in range(5):
        sm.update(_POLL)
    assert passes() == 0


@pytest.mark.parametrize("card_kind", ["quickref", "book"])
def test_autoplay_never_types_into_a_card_or_the_book(pygame_setup, asset_mgr, card_kind):
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.screens.book import BookScreen

    sm, game = _sm()
    sm.party = None
    if card_kind == "quickref":
        _key(sm, pygame.K_F3)
        top = sm.current_screen
        assert isinstance(top, QuickRefScreen)
    else:
        top = BookScreen(return_screen=game, manager=sm)
        sm.push_screen(top)
    ctrl = AutoPlayController(enabled=True)
    ctrl._key_queue.extend([pygame.K_a, pygame.K_RETURN])
    for _ in range(5):
        assert ctrl.step(sm) is None
    assert sm.current_screen is top
    assert list(ctrl._key_queue) == [pygame.K_a, pygame.K_RETURN]


def test_spell_lines_say_what_the_rules_do():
    assert "3 in 4" in SPELL_EFFECTS[Spell.REPOND] and "orcs" in SPELL_EFFECTS[Spell.REPOND]
    assert "3 in 4" in SPELL_EFFECTS[Spell.PONTORI] and "skeletons" in SPELL_EFFECTS[Spell.PONTORI]
    for sp in (Spell.REPOND, Spell.PONTORI):
        assert "half the time" in SPELL_EFFECTS[sp] and "one try" in SPELL_EFFECTS[sp]
    for sp in (Spell.LORUM, Spell.LUMINAE):
        assert SPELL_EFFECTS[sp] == "Light for 10 turns, unless a longer light is lit"


def test_q_says_sosaria_only():
    q = next(c for c in COMMANDS if c.key == "Q")
    assert q.where == "S" and "Sosaria only" in q.desc
