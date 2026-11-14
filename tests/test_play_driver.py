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
import re

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


def _cleric_party(mp: int = 99) -> Party:
    """A one-member cleric party with the given mana (combat cast flows)."""
    party = Party()
    party.add_member(
        Character(
            "Cora", Sex.FEMALE, profession=Profession.CLERIC, hp=100, max_hp=100, mp=mp
        )
    )
    return party


def _druid_party(mp: int = 99) -> Party:
    """A one-member druid party (the cleric+wizard dual-discipline gate)."""
    party = Party()
    party.add_member(
        Character(
            "Rowan", Sex.FEMALE, profession=Profession.DRUID, hp=100, max_hp=100, mp=mp
        )
    )
    return party


class TestCombatCastFlow:
    """Task 3 (2026-11-14 combat-interaction-parity): the combat C command
    prints the LIVE getCastables rows and reads the letter from the SAME map.

    Java truth: CombatScreen.java:322-330 builds
    ``Spell.getCastables(ap, MapType.combat)`` for the ACTIVE member (no
    member prompt), "No spells to cast!" when the map is empty; the ctor of
    SpellInputProcessor.java:36-39 prints the rows before the first key is
    read."""

    def test_cleric_combat_prints_rows_without_member_prompt(self, asset_mgr):
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        assert session.active_member == "Cora"

        session.press("C")
        # The printed list is the live mapping (cleric, combat, mp 99):
        # PONTORI 0-cost first at A, letters compact over the survivors.
        for row in (
            "A - PONTORI (0)",
            "B - SANCTU (10)",
            "C - ALCORT (35)",
            "D - SANCTU_MANI (50)",
            "E - EXCUUN (60)",
            "F - SURMANDUM (65)",
            "G - ZXKUQYB (70)",
            "H - ANJU_SERMANI (75)",
        ):
            assert f"[msg] {row}" in session.transcript, session.transcript
        # Combat never asks which member (Java casts with the active one).
        assert not any("Which member?" in line for line in session.transcript)
        # APPAR_UNEM is a chest spell: never in the combat list (mask
        # world|city|dungeon), matching the 2026-11-11 no-combat ruling.
        assert not any("APPAR_UNEM" in line for line in session.transcript)
        assert session.is_waiting_for_input

    def test_masskill_gate_failed_cast_reopens_for_same_member(self, asset_mgr):
        """``C A`` (PONTORI) with the per-battle masskill latch OFF: the
        FAILED refusal does not execute, the turn is not consumed, and a
        follow-up C re-opens the spell list for the SAME member with no
        member prompt anywhere (Task 4 will pin the executed-vs-refusal
        consumption rule)."""
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        session.screen.arena.masskill = False  # pin the 50% latch

        session.press_seq("C A")
        assert any("[msg] FAILED" in line for line in session.transcript), (
            session.transcript
        )
        marker = session.active_member
        assert marker == "Cora"

        # The prompt re-opens for the same caster.
        session.press("C")
        assert not any("Which member?" in line for line in session.transcript)
        assert session.active_member == marker
        assert session.is_waiting_for_input
        assert any("[msg] A - PONTORI (0)" in line for line in session.transcript)

    def test_low_mp_cleric_list_compacts_and_beyond_letter_is_silent(self, asset_mgr):
        """MP 3: only the 0-cost spell is listed (not offered = not
        promptable — no "Thou dost not have enough magic points!" from the
        prompt flow); a letter beyond the list length does nothing silently
        and the active-member marker persists."""
        session = PlaySession(asset_mgr).start(party=_cleric_party(mp=3))
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)

        session.press("C")
        # The mapped list for a cleric at MP 3 in combat: only the 0-cost
        # spell; every other cleric spell costs >= 5.
        spell_rows = [
            line
            for line in session.transcript
            if re.match(r"\[msg\] [A-Z] - \w+ \(\d+\)$", line)
        ]
        assert spell_rows == ["[msg] A - PONTORI (0)"], session.transcript
        assert not any("magic points" in line for line in session.transcript)

        before = session.transcript
        session.press("B")  # beyond the one-entry list
        added = session.transcript[len(before):]
        assert not any(
            "Unknown spell!" in line or "Not a spell!" in line for line in added
        ), added
        assert not any("FAILED" in line for line in added)
        assert session.active_member == "Cora"  # marker persists
        assert session.is_waiting_for_input

    def test_druid_combat_wizard_cleric_choice_then_wizard_rows(self, asset_mgr):
        """The druid/ranger dual gate: combat prompts [W]izard or [C]leric
        first (py's discipline split — get_castables takes the RESOLVED
        discipline; two calls = two menus), then the chosen list prints."""
        session = PlaySession(asset_mgr).start(party=_druid_party())
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)

        session.press("C")
        assert any(
            line == "[prompt] Spell Type? [W]izard or [C]leric:"
            for line in session.transcript
        ), session.transcript

        session.press("W")
        assert any("[msg] A - REPOND (0)" in line for line in session.transcript)
        assert any(
            line.startswith("[prompt] Wizard Spell? (A-P):")
            for line in session.transcript
        )
        assert session.is_waiting_for_input

        # Escape closes the menu without acting; the caster keeps the turn
        # (existing cancel semantics).
        session.press("ESC")
        assert not session.is_waiting_for_input
        assert session.active_member == "Rowan"

        # The other discipline prints ITS list (cleric spells, druid-castable).
        session.press("C")
        session.press("C")
        assert any("[msg] A - PONTORI (0)" in line for line in session.transcript)
        assert any(
            line.startswith("[prompt] Cleric Spell? (A-P):")
            for line in session.transcript
        )

    def test_world_flow_member_prompt_then_rows_and_appar_unem(self, asset_mgr):
        """The world flow still prompts the member first; the list prints
        after the selection and offers the context spells (APPAR_UNEM is
        IN the world list — the combat exclusion is the contrast)."""
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        assert isinstance(session.screen, OverworldScreen)

        session.press("C")
        assert any(
            "[prompt] Cast: Which member? (1-4):" in line for line in session.transcript
        ), session.transcript

        session.press("1")
        assert any("[msg] A - APPAR_UNEM (5)" in line for line in session.transcript)
        assert any(
            line.startswith("[prompt] Cleric Spell? (A-P):") for line in session.transcript
        )
        assert session.is_waiting_for_input
