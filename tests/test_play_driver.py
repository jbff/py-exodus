"""Smoke tests for the headless play driver (tests/play_driver.py).

The driver is infra: these tests pin that it boots the real screens headless
and that ``transcript`` mirrors the same ``text_log`` lines the harness tests
read (history + prompt state), keyed on the plan's two smoke rows:
- overworld boot via the Journey Onward save shortcut, then ``Z`` -> the
  zstats heading (OverworldScreen._toggle_zstats, overworld.py:683).
- a real CombatScreen (context_map_id, per test_combat_parity.py), then
  ``C`` -> the combat cast prompt (CombatScreen._prompt_cast).
"""
import pygame
import pytest
import random

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Sex
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.overworld import OverworldScreen

import play_driver
from play_driver import PlaySession, resolve_key


@pytest.fixture(autouse=True)
def hermetic_rng():
    """Zero RNG footprint for the suite.

    The driver exercises live CombatScreen/arena rolls (monster placement,
    attacks), which consume the global `random` stream. Restore the stream
    after each test so everything downstream of this module keeps the exact
    stream it had before the driver existed (several unseeded tests, e.g.
    the chest-trap loot rolls, are stream-sensitive).
    """
    state = random.getstate()
    yield
    random.setstate(state)


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


class TestKeyTokens:
    def test_compass_arrows_map_to_arrow_keys(self):
        """Documented token map: N/S/E/W are the arrow keys, matching the
        game's "Direction? (N,S,E,W)" prompts."""
        assert resolve_key("N") == pygame.K_UP
        assert resolve_key("S") == pygame.K_DOWN
        assert resolve_key("E") == pygame.K_RIGHT
        assert resolve_key("W") == pygame.K_LEFT

    def test_arrow_tokens_and_specials(self):
        assert resolve_key("UP") == pygame.K_UP
        assert resolve_key("DOWN") == pygame.K_DOWN
        assert resolve_key("LEFT") == pygame.K_LEFT
        assert resolve_key("RIGHT") == pygame.K_RIGHT
        assert resolve_key("SPACE") == pygame.K_SPACE
        assert resolve_key("ESC") == resolve_key("ESCAPE") == pygame.K_ESCAPE
        assert resolve_key("ENTER") == resolve_key("RETURN") == pygame.K_RETURN

    def test_letters_digits_and_passthrough(self):
        assert resolve_key("Z") == pygame.K_z
        assert resolve_key("a") == pygame.K_a
        assert resolve_key("5") == pygame.K_5
        assert resolve_key(pygame.K_F1) == pygame.K_F1

    def test_unknown_token_raises_with_map_hint(self):
        with pytest.raises(ValueError, match="N/S/E/W"):
            resolve_key("Q2")


class TestOverworldSmoke:
    def test_journey_onward_then_zstats_heading(self, asset_mgr):
        """Plan row 1: boot the roster->overworld flow (Journey Onward via
        the repo save), press Z, and read the zstats heading off the
        transcript; then cycle Z back to the normal view."""
        session = PlaySession(asset_mgr).start()
        assert isinstance(session.screen, OverworldScreen)
        assert session.active_member is None  # not a combat screen

        session.press_seq("Z")
        assert any(
            line.startswith("[msg] Zstats:") for line in session.transcript
        ), session.transcript
        # The heading names the first party member and their profession
        assert any(
            session.party.members[0].name in line for line in session.transcript
        )

        # Close the view the way the flow requires: Z cycles each member,
        # then back to the normal view.
        for _ in range(len(session.party.members) + 2):
            session.press("Z")
            if any("Zstats: Normal view" in line for line in session.transcript):
                break
        assert any("Zstats: Normal view" in line for line in session.transcript)
        assert session.screen.stats_panel.inspect_index is None


class TestCombatSmoke:
    def test_combat_c_press_shows_cast_prompt(self, asset_mgr):
        """Plan row 2: a real CombatScreen (CNFLCT_A.ULT, context_map_id=2 —
        the test_combat_parity.py fixture pattern), then C opens the combat
        cast prompt in the transcript; the driver reports the active member."""
        party = Party()
        wizard = Character(
            "Marvin", Sex.MALE, profession=Profession.WIZARD, hp=100, max_hp=100
        )
        party.add_member(wizard)

        session = PlaySession(asset_mgr).start(party=party)
        assert isinstance(session.screen, OverworldScreen)
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        assert isinstance(session.screen, CombatScreen)
        assert len(session.screen.arena.monsters) == 1
        assert session.active_member == "Marvin"

        session.press("C")
        assert any(
            line.startswith("[prompt] Wizard Spell? (A-P):") for line in session.transcript
        ), session.transcript
        assert session.is_waiting_for_input

        # A second, control smoke: a non-caster presses C and gets Java's
        # canonical no-castables line instead of a prompt.
        fighters = Party()
        fighters.add_member(Character("Bruiser", Sex.MALE, profession=Profession.FIGHTER))
        alt = PlaySession(asset_mgr).start(party=fighters)
        alt.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        alt.press("C")
        assert any("No spells to cast!" in line for line in alt.transcript)
        assert not alt.is_waiting_for_input
