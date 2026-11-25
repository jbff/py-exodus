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
from py_exodus.constants import Profession, Sex, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.save_system import SaveSystem
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.start import StartScreen

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
    @pytest.fixture(autouse=True)
    def _no_wanderers(self, monkeypatch):
        """These smoke tests read Z-stats; a wanderer stepping in to fight
        (LairWare diagonal attacks, 2026-11-22) would swap the screen
        depending on the random state earlier tests left behind."""
        monkeypatch.setattr(OverworldScreen, "_update_creatures", lambda self: None)
        monkeypatch.setattr(OverworldScreen, "_spawn_wandering_creature", lambda self: None)

    def test_journey_onward_then_zstats_heading(self, asset_mgr, monkeypatch, tmp_path):
        """Plan row 1: boot the roster->overworld flow (Journey Onward via
        an on-disk save in tmp_path), press Z, and read the zstats heading off the
        transcript; then cycle Z back to the normal view."""
        monkeypatch.chdir(tmp_path)
        party = Party()
        party.add_member(
            Character("Ariel", Sex.MALE, profession=Profession.FIGHTER, hp=100, max_hp=100)
        )
        SaveSystem.save_game(party, tmp_path / "saves" / "party.json")

        session = PlaySession(asset_mgr).start()
        assert isinstance(session.screen, OverworldScreen)
        assert session.active_member is None  # not a combat screen

        session.press_seq("Z")
        session.press("1")  # Ztats for #- (LairWare Stats, UltimaMain.c:2595)
        assert any(
            line.startswith("[msg] Zstats:") for line in session.transcript
        ), session.transcript
        # The heading names the first party member and their profession
        assert any(
            session.party.members[0].name in line for line in session.transcript
        )

        # Any key closes the view (DoStats, UltimaMacIF.c:1390-1394).
        session.press("Z")
        assert session.screen.stats_panel.inspect_index is None

    def test_drain_captures_messages_before_screen_transition(self, asset_mgr):
        party = Party()
        dead_char = Character(
            "Ghost", Sex.MALE, profession=Profession.FIGHTER, hp=0, max_hp=100, status=Status.DEAD
        )
        party.add_member(dead_char)
        session = PlaySession(asset_mgr).start(party=party)
        assert isinstance(session.screen, OverworldScreen)

        # Z asks whose Ztats (LairWare Stats, UltimaMain.c:2595); the turn
        # (Routine6E35) comes after the answer, and on it the wiped party
        # leaves for the start screen. The Ztats lines are drained before
        # the transition.
        session.press("Z")
        assert isinstance(session.screen, OverworldScreen)
        assert "[prompt] Ztats for #-" in session.transcript, session.transcript
        session.press("1")
        assert any(
            line.startswith("[msg] Zstats:") for line in session.transcript
        ), session.transcript
        assert isinstance(session.screen, StartScreen)
        assert session.screen.game_over is True


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


class TestActiveTurnMarker:
    """Task 6 (2026-11-14 combat-interaction-parity): the active-member turn
    marker in the combat text log.

    PLAYABILITY AFFORDANCE, not parity: GBC shows whose turn it is with the
    blink cursor + member stat window (battle2.c:297, battle.c:262) and logs
    nothing textually; this port's channel is the text log, so each member
    activation and each return-to-actor (a non-consuming action or a
    disarmed prompt) marks the member once."""

    def test_combat_start_marks_the_active_member_once(self, asset_mgr):
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        assert session.active_member == "Cora"
        # Exactly one marker per activation: never per-frame spam.
        assert session.transcript.count("[msg] Cora's turn.") == 1, (
            session.transcript
        )

    def test_not_a_spell_returns_the_turn_and_marks_it_again(self, asset_mgr):
        session = PlaySession(asset_mgr).start(party=_cleric_party(mp=3))
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        session.press("C")
        before = session.transcript
        before_round = session.screen.arena.round_count

        # USER-DIRECTED RULING (2026-11-15): fixed spell letters — a key
        # outside the fixed A-P codes (a digit is never a spell letter)
        # still takes Java's "Not a spell!" branch.
        session.press("1")
        added = session.transcript[len(before):]
        assert any("Not a spell!" in line for line in added), added
        # The refusal returned the turn to the SAME member: one more marker,
        # no member advance, no monster phase.
        assert sum("Cora's turn." in line for line in added) == 1, added
        assert session.active_member == "Cora"
        assert session.screen.arena.round_count == before_round
        assert not session.is_waiting_for_input

    def test_attempt_location_refusal_returns_the_turn_and_marks_it_again(
        self, asset_mgr
    ):
        """USER-DIRECTED RULING (2026-11-15): pressing a VALID fixed letter
        whose spell fails canCastLocation -> "Not Here!", NOT executed (no
        cast, no mana) — the menu disarms and the turn returns to the SAME
        member (marker repeat, no member advance, no monster phase). B is
        APPAR_UNEM ALWAYS; the combat context refuses it (mask lacks the
        combat bit, Constants.java:710)."""
        session = PlaySession(asset_mgr).start(party=_cleric_party(mp=99))
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        session.press("C")
        before = session.transcript
        before_round = session.screen.arena.round_count

        session.press("B")  # APPAR_UNEM, the fixed B — refused in combat
        added = session.transcript[len(before):]
        assert any("Not Here!" in line for line in added), added
        assert not any("Not a spell!" in line for line in added), added
        assert not any("FAILED" in line for line in added), added
        assert sum("Cora's turn." in line for line in added) == 1, added
        assert session.active_member == "Cora"
        assert session.screen.arena.round_count == before_round
        assert not session.is_waiting_for_input

    def test_invalid_attack_direction_cancel_marks_the_turn_again(self, asset_mgr):
        fighters = Party()
        fighters.add_member(
            Character("Bruiser", Sex.MALE, profession=Profession.FIGHTER)
        )
        session = PlaySession(asset_mgr).start(party=fighters)
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        session.press("A")
        assert any(
            line.startswith("[prompt] Direction? (N,S,E,W):")
            for line in session.transcript
        ), session.transcript
        before = session.transcript
        before_round = session.screen.arena.round_count

        session.press("X")  # not a compass answer -> "Invalid direction!"
        added = session.transcript[len(before):]
        assert any("Invalid direction!" in line for line in added), added
        # The cancel returned the turn to the SAME member: one more marker,
        # no member advance, no monster phase.
        assert sum("Bruiser's turn." in line for line in added) == 1, added
        assert session.active_member == "Bruiser"
        assert session.screen.arena.round_count == before_round

    def test_successful_cast_advances_the_marker_to_the_next_member(self, asset_mgr):
        party = _cleric_party()
        # Wounded second member: SANCTU is targeted-member healing, and a
        # full-health target is a pre-execution refusal (turn retained) —
        # NOT the consuming success this test pins.
        bruised = Character(
            "Bruiser", Sex.MALE, profession=Profession.FIGHTER, hp=50, max_hp=100
        )
        party.add_member(bruised)
        session = PlaySession(asset_mgr).start(party=party)
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        assert session.active_member == "Cora"
        before = session.transcript

        session.press_seq("C C 2")  # SANCTU (10 MP, fixed C) on Bruiser: consuming success
        added = session.transcript[len(before):]
        assert not any("Cora's turn." in line for line in added), added
        # The consumed turn advanced to the NEXT member, whose turn begins
        # with its own marker.
        assert sum("Bruiser's turn." in line for line in added) == 1, added
        assert session.screen.arena.active_party_member_idx == 1
        assert session.active_member == "Bruiser"


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
    """Task 3 (2026-11-14 combat-interaction-parity), rewritten for the
    USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
    always) — the combat C command prints the FULL FIXED A-P rows and reads
    the letter from the SAME list; the context mask refuses at attempt.

    Java truth: CombatScreen.java:322-330 builds the combat menu for the
    ACTIVE member (no member prompt) — "No spells to cast!" when the
    profession gate upstream opens no menu; SpellInputProcessor.java:36-39
    prints the rows before the first key is read. The getCastables letter
    compaction (Constants.java:751-762) is superseded."""

    def test_cleric_combat_prints_rows_without_member_prompt(self, asset_mgr):
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        assert session.active_member == "Cora"

        session.press("C")
        # The FIXED cleric list (combat context, letters never move):
        # APPAR_UNEM sits at its permanent B even though combat will refuse
        # the attempt (USER-DIRECTED RULING 2026-11-15).
        for row in (
            "A - PONTORI (0)",
            "B - APPAR_UNEM (5)",
            "C - SANCTU (10)",
            "H - ALCORT (35)",
            "K - SANCTU_MANI (50)",
            "P - ANJU_SERMANI (75)",
        ):
            assert f"[msg] {row}" in session.transcript, session.transcript
        # The list is the FULL fixed set: all 16 rows print.
        rows = [
            line
            for line in session.transcript
            if re.match(r"\[msg\] [A-P] - [A-Z_]+ \(\d+\)$", line)
        ]
        assert len(rows) == 16, session.transcript
        # Combat never asks which member (Java casts with the active one).
        assert not any("Which member?" in line for line in session.transcript)
        assert session.is_waiting_for_input

    def test_per_battle_latch_failed_cast_consumes_the_turn(self, asset_mgr):
        """``C A`` (PONTORI) with the per-battle latch clear: FAILED is an
        EXECUTED failure (LairWare UltimaSpellCombat.c:248-265 — the wrong
        monster type is Failed() in the effect, so the monster phase follows), the
        turn is consumed, and the round rolls over: with a one-member party
        the caster still holds the prompt at the head of the NEXT round.

        Rewritten 2026-11-14 (Task 4, plan's binding executed-vs-refusal
        rule): the Task 3 reading flipped — this cast reached its effect
        branch (mana spent, roll made), so it consumes; only pre-execution
        refusals (the SpellUtil gates, executed=False) keep the caster
        active."""
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        arena = session.screen.arena
        # Pontori at orcs: LW's type test fails it (UltimaSpellCombat.c:253).
        before_round = arena.round_count

        session.press_seq("C A")
        assert any("[msg] FAILED" in line for line in session.transcript), (
            session.transcript
        )

        # The consumed turn finished the single member's round: the monster
        # phase ran (round_count advanced) and the fresh round re-armed Cora.
        assert arena.round_count == before_round + 1
        assert arena.is_party_round_done is False
        assert session.active_member == "Cora"

        # The prompt re-opens for the caster's next-round turn (no member
        # prompt anywhere — combat casts with the active member).
        session.press("C")
        assert not any("Which member?" in line for line in session.transcript)
        assert session.active_member == "Cora"
        assert session.is_waiting_for_input
        assert any("[msg] A - PONTORI (0)" in line for line in session.transcript)

    def test_low_mp_cleric_full_list_and_attempt_refusals(self, asset_mgr):
        """USER-DIRECTED RULING (2026-11-15): MP 3 no longer compacts the
        list — the FULL fixed set prints (B - APPAR_UNEM (5) included).
        Refusals happen AT ATTEMPT: an out-of-list key (a digit) logs
        Java's canonical "Not a spell!"; the LISTED-but-context-refused
        APPAR_UNEM (mask lacks the combat bit) logs "Not Here!"; an
        unaffordable letter gets the canonical MP string AT LETTER
        SELECTION (F2 amendment 2026-11-15 — before any "On who?"/
        "Direction?" prompt, the prompt layer refuses). Every refusal is
        pre-execution (no "FAILED", no round advance) and DISARMS the menu
        — the turn stays with the active member (marker persists)."""
        session = PlaySession(asset_mgr).start(party=_cleric_party(mp=3))
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)

        session.press("C")
        rows = [
            line
            for line in session.transcript
            if re.match(r"\[msg\] [A-P] - [A-Z_]+ \(\d+\)$", line)
        ]
        assert len(rows) == 16, session.transcript
        assert "[msg] B - APPAR_UNEM (5)" in rows  # listed though refused
        assert "[msg] C - SANCTU (10)" in rows  # listed though unaffordable

        # (1) a non-code key: "Not a spell!" + disarm, turn retained.
        before = session.transcript
        before_round = session.screen.arena.round_count
        session.press("1")
        added = session.transcript[len(before):]
        assert any("Not a spell!" in line for line in added), added
        assert not session.is_waiting_for_input
        assert session.screen.arena.round_count == before_round

        # (2) a fixed letter the combat context refuses: "Not Here!" —
        # no cast, no mana, disarm, turn retained.
        session.press("C")
        before = session.transcript
        session.press("B")  # APPAR_UNEM ALWAYS at B
        added = session.transcript[len(before):]
        assert any("Not Here!" in line for line in added), added
        assert not any("FAILED" in line for line in added), added
        assert not session.is_waiting_for_input
        assert session.screen.arena.round_count == before_round

        # (3) an unaffordable listed letter: the canonical MP refusal fires
        # AT LETTER SELECTION (F2 amendment 2026-11-15 — the prompt layer
        # checks mp_cost <= mana right after letter_resolution). ZXKUQYB
        # (O, 70 MP) is non-targeted so nothing else happens on the press.
        session.press("C")
        before = session.transcript
        session.press("O")  # ZXKUQYB (70) at MP 3
        added = session.transcript[len(before):]
        # the string wraps in the narrow log: assert its two halves land.
        assert any(
            "Thou dost not have enough" in line for line in added
        ), added
        assert any("magic points" in line for line in added), added
        assert not any("FAILED" in line for line in added), added
        assert not session.is_waiting_for_input
        assert session.screen.arena.round_count == before_round
        assert session.active_member == "Cora"  # kept the turn throughout

        # (4) F2 amendment pinned on a TARGETED spell: an unaffordable
        # SANCTU (C, 10 at MP 3) refuses on the letter press itself — NO
        # "On who?" prompt ever opens (pre-amendment the target prompt
        # preceded the MP refusal). Disarm, turn retained.
        session.press("C")
        before = session.transcript
        session.press("C")  # SANCTU (10) at MP 3
        added = session.transcript[len(before):]
        assert any(
            "Thou dost not have enough" in line for line in added
        ), added
        assert any("magic points" in line for line in added), added
        assert not any("On who?" in line for line in added), added
        assert not any("FAILED" in line for line in added), added
        assert not session.is_waiting_for_input
        assert session.screen.arena.round_count == before_round
        assert session.active_member == "Cora"

    def test_combat_directional_mp_refusal_precedes_direction_prompt(self, asset_mgr):
        """F2 AMENDMENT (2026-11-15, binding): for a DIRECTIONAL spell the
        MP refusal fires AT LETTER SELECTION — before "Direction?" opens.
        A combat wizard menu press of MITTAR (B, 5) at MP 3 masks-in
        (0x02) but cannot be afforded, so the canonical refusal lands on
        the letter press itself; pre-amendment the "Direction?" prompt ran
        first and cast_spell prevalidation refused only after the
        direction was chosen. Disarm, turn retained, no round advance."""
        # MP 1 + 2 from combatstart's AgeChars (a Druid, LairWare
        # UltimaSpellCombat.c:920; Book of Lore +2) = 3 at the menu.
        session = PlaySession(asset_mgr).start(party=_druid_party(mp=1))
        session.enter_combat(creature_tile="orc", context_map_id=2, monster_count=1)
        before_round = session.screen.arena.round_count

        session.press("C")
        session.press("W")  # the druid's wizard menu
        session.press("B")  # MITTAR (5), directional, combat mask ok
        added = session.transcript[len(session.transcript) - 20:]
        assert any(
            "Thou dost not have enough" in line for line in added
        ), added
        assert not any("Direction?" in line for line in added), added
        assert not session.is_waiting_for_input
        assert session.screen.arena.round_count == before_round
        assert session.active_member == "Rowan"

    def test_druid_combat_wizard_cleric_choice_then_wizard_rows(self, asset_mgr):
        """The druid/ranger dual gate: combat prompts [W]izard or [C]leric
        first (py's discipline split — each choice shows its own FIXED
        list, USER-DIRECTED RULING 2026-11-15; two calls = two menus), then
        the chosen list prints."""
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
        """The world flow still prompts the member first; the FIXED list
        prints after the selection — APPAR_UNEM sits at its permanent B in
        EVERY list (USER-DIRECTED RULING 2026-11-15); world attempt-refuses
        the combat-only PONTORI at A instead of hiding it."""
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        assert isinstance(session.screen, OverworldScreen)

        session.press("C")
        assert any(
            "[prompt] Cast: Which member? (1-4):" in line for line in session.transcript
        ), session.transcript

        session.press("1")
        assert any("[msg] B - APPAR_UNEM (5)" in line for line in session.transcript)
        assert any("[msg] A - PONTORI (0)" in line for line in session.transcript)
        assert any(
            line.startswith("[prompt] Cleric Spell? (A-P):") for line in session.transcript
        )
        assert session.is_waiting_for_input


class TestClericCombatCastLoopRegression:
    """Task 8: the user's 2026-11-14 play report, re-pinned under the
    USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
    always); availability refused at attempt.

    The reported session: combat vs the undead family (skeletons), the
    per-battle Pontori latch clear, a lone cleric holding the turn:
    (1) ``C`` prints the FULL FIXED cleric list — PONTORI at its permanent
    ``A``, APPAR_UNEM at its permanent ``B`` (listed even though combat
    refuses the attempt); (2) pressing ``B`` in combat logs "Not Here!" —
    NOT executed, no cast, no mana, the menu disarms and the SAME member's
    turn marker repeats; a non-code key still takes "Not a spell!";
    (3) ``C`` re-arms the prompt, and casting PONTORI (always letter ``A``)
    under the OFF latch prints FAILED and CONSUMES the turn (monster phase,
    round advance, same member re-armed next round); (4) combat never asks
    "Which member?"; (5) the non-projectile Pontori cast drew no fabricated
    tracer FX (mirrors Task 5's spell_fx_count hook)."""

    def test_list_rows_attempt_refusals_then_rearm(self, asset_mgr):
        """Play report (1)+(2)+(4): the FULL FIXED list rows, the B-in-combat
        "Not Here!" attempt refusal with the marker repeat, the non-code
        "Not a spell!" disarm, and the re-armed re-open."""
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(
            creature_tile="skeleton", context_map_id=2, monster_count=1
        )
        assert session.active_member == "Cora"

        # (1) ``C``: the FULL FIXED cleric rows print for the active member —
        # PONTORI (the per-battle latch spell) at its permanent ``A``,
        # APPAR_UNEM listed at its permanent ``B`` even though combat will
        # refuse the attempt (USER-DIRECTED RULING 2026-11-15).
        session.press("C")
        rows = [
            line
            for line in session.transcript
            if re.match(r"\[msg\] [A-P] - [A-Z_]+ \(\d+\)$", line)
        ]
        assert len(rows) == 16, session.transcript
        assert "[msg] A - PONTORI (0)" in rows
        assert "[msg] B - APPAR_UNEM (5)" in rows

        # (2a) B in combat: a VALID fixed letter whose spell the context
        # refuses -> "Not Here!" — NOT executed (no cast, no mana, no
        # "FAILED"), the menu DISARMS, and the turn is untouched: the SAME
        # member keeps it (the marker repeats once), no member advance, no
        # monster phase.
        before = session.transcript
        before_round = session.screen.arena.round_count
        session.press("B")
        added = session.transcript[len(before):]
        assert any("Not Here!" in line for line in added), added
        assert not any("FAILED" in line or "Not a spell!" in line for line in added)
        assert not session.is_waiting_for_input
        assert sum("Cora's turn." in line for line in added) == 1, added
        assert session.active_member == "Cora"
        assert session.screen.arena.round_count == before_round

        # (2b) a non-code key still takes Java's "Not a spell!" branch
        # (retained for unknown letters).
        session.press("C")
        before = session.transcript
        session.press("1")
        added = session.transcript[len(before):]
        assert any("Not a spell!" in line for line in added), added
        assert not session.is_waiting_for_input
        assert session.screen.arena.round_count == before_round

        # (4) Combat never asks which member casts: the active member IS
        # the caster (the world flow's "[prompt] Cast: Which member?" has
        # no combat twin).
        assert not any("Which member?" in line for line in session.transcript)

        # (3) closing beat: ``C`` again re-arms the prompt with its rows —
        # the same fixed list, not a member prompt.
        session.press("C")
        assert session.is_waiting_for_input
        assert any("[msg] A - PONTORI (0)" in line for line in session.transcript)

    def test_per_battle_latch_failed_consumes_turn_no_member_prompt_no_tracer(
        self, asset_mgr, monkeypatch
    ):
        """Play report (3)+(4)+(5): casting PONTORI (per-battle latch) with
        the latch clear and a missed 50% roll prints FAILED and CONSUMES the
        turn (an executed failure, LairWare UltimaSpellCombat.c:262-265): the monster phase follows, the
        round advances, and the next round re-arms the same member at its
        position; no member prompt ever appears, and the non-projectile
        cast draws no fabricated tracer."""
        session = PlaySession(asset_mgr).start(party=_cleric_party())
        session.enter_combat(
            creature_tile="skeleton", context_map_id=2, monster_count=1
        )
        arena = session.screen.arena
        # The 50% roll misses (LW UltimaSpellCombat.c:262-266 RandNum < 128).
        import py_exodus.combat.magic as magic

        real = magic.random.randrange
        monkeypatch.setattr(
            magic.random, "randrange", lambda n, *a: 0 if n == 256 else real(n, *a)
        )
        before_round = arena.round_count

        # Mirror Task 5's FX hook: a tracer is a spell fx carrying a path.
        def spell_tracers() -> list:
            return [
                fx
                for fx in session.screen.combat_fx
                if fx["type"] == "spell" and fx["path"]
            ]

        session.press_seq("C A")  # PONTORI (0), the per-battle latch spell
        assert any("[msg] FAILED" in line for line in session.transcript), (
            session.transcript
        )

        # The cast EXECUTED and failed: the turn is consumed — the single
        # member's round finishes, the monster phase runs (round_count
        # advances), and the fresh round re-arms Cora at her position.
        assert arena.round_count == before_round + 1
        assert arena.is_party_round_done is False
        assert session.active_member == "Cora"

        # (5) No fabricated tracer: PONTORI is not a projectile spell, so
        # no spell fx with a path may exist — even on the FAILED cast.
        assert spell_tracers() == [], session.screen.combat_fx

        # (4) No "Cast: Which member?" string ever appears in combat —
        # including across the round rollover this cast just drove.
        assert not any("Which member?" in line for line in session.transcript)


class TestMonsterHitAffordance:
    """Playtest-1 fix batch, item 4 (user-approved deviation from Java's
    message silence): when a monster's melee/ranged/cannonfire hit lands on a
    member, the combat transcript gains an affordance line in the port's
    voice, mirroring the task-6 turn-marker precedent ("X's turn.", "Pass")
    — event-driven, never per-frame. Java logs NOTHING on ANY monster action
    (CombatScreen.java:720-745 melee is sounds-only; rangedAttackAt logs
    only "Electrified!"/"Fiery Hit!"/"Poisoned!"), so these lines are NOT
    message parity; the user-approved scope covers HITS and DEATHS only —
    misses stay silent to keep noise down."""

    def _giant_battle(self, asset_mgr, monkeypatch, *, hp=100, hit=True,
                      damage=34, roll_bonus=0):
        """One-member 'Serana' vs one adjacent giant; deterministic hit and
        damage rolls (resolver-level patches, exactly the functions the melee
        resolve consults); monster_damage_bonus is zeroed so the transcript
        number is the plain damage roll."""
        import py_exodus.combat.resolver as resolver

        party = Party()
        party.add_member(
            Character("Serana", Sex.FEMALE, profession=Profession.FIGHTER, hp=hp, max_hp=100)
        )
        session = PlaySession(asset_mgr).start(party=party)
        session.enter_combat(creature_tile="giant", monster_count=1)
        arena = session.screen.arena
        monster = arena.monsters[0]
        member_pos = arena.player_positions[arena.active_party_member_idx]
        mx = member_pos[0] + 1 if member_pos[0] < 10 else member_pos[0] - 1
        monster.x, monster.y = mx, member_pos[1]

        monkeypatch.setattr(resolver, "roll_hit", lambda *a, **k: hit)
        monkeypatch.setattr(resolver, "calculate_monster_damage", lambda basehp: damage)
        # Monster attacks use the LairWare roll/damage (2026-11-22).
        monkeypatch.setattr(resolver, "lw_monster_hits", lambda *a, **k: hit)
        monkeypatch.setattr(resolver, "lw_monster_damage_roll", lambda *a, **k: damage)
        monkeypatch.setattr(resolver, "monster_damage_bonus", lambda cmap: roll_bonus)
        return session

    def test_giant_melee_hit_line_with_the_number(self, asset_mgr, monkeypatch):
        session = self._giant_battle(asset_mgr, monkeypatch)
        before = session.transcript

        session.press("SPACE")  # pass: round ends, the giant attacks

        added = session.transcript[len(before):]
        assert any("[msg] Giant hits Serana (-34)." in line for line in added), added

    def test_member_death_line_after_a_killing_hit(self, asset_mgr, monkeypatch):
        session = self._giant_battle(asset_mgr, monkeypatch, hp=30)  # 34 > 30

        session.press("SPACE")

        text = "\n".join(session.transcript)
        assert "Giant hits Serana (-34)." in text
        assert "Serana falls!" in text

    def test_melee_miss_stays_silent(self, asset_mgr, monkeypatch):
        session = self._giant_battle(asset_mgr, monkeypatch, hit=False)
        before = session.transcript

        session.press("SPACE")

        added = session.transcript[len(before):]
        assert not any("Giant hits" in line for line in added), added
        assert not any("falls!" in line for line in added), added

    def test_ranged_bolt_hit_line(self, asset_mgr, monkeypatch):
        """A dragon's fire bolt that lands on a member gains the same hit
        line; the ranged "Fiery Hit!" mechanic string rides along (its own
        message slot) and the member's death still gets its line."""
        import py_exodus.combat.resolver as resolver

        party = Party()
        party.add_member(
            Character("Serana", Sex.FEMALE, profession=Profession.CLERIC, hp=200, max_hp=200)
        )
        session = PlaySession(asset_mgr).start(party=party)
        session.enter_combat(creature_tile="dragon", monster_count=1)
        arena = session.screen.arena
        monster = arena.monsters[0]
        member_pos = arena.player_positions[0]
        monster.x, monster.y = member_pos[0], member_pos[1] - 2  # straight bolt south

        # AI: the ranged-only choice (randrange(100) -> 0 <= 33); damage 27,
        # one roll per landed bolt (LairWare; Java's double roll is gone).
        monkeypatch.setattr(random, "randrange", lambda n: 0)
        # The dragon fires on RandNum(0, 255) < 128 (arena, UltimaSpellCombat.c:
        # 1119-1124); pin it, or the test passes only half the time.
        monkeypatch.setattr(random, "randint", lambda a, b: a)
        monkeypatch.setattr(resolver, "lw_monster_hits", lambda *a, **k: True)
        monkeypatch.setattr(resolver, "lw_monster_damage_roll", lambda *a, **k: 27)
        monkeypatch.setattr(resolver, "monster_damage_bonus", lambda cmap: 0)
        before = session.transcript

        session.press("SPACE")

        added = session.transcript[len(before):]
        assert any("[msg] Fiery Hit!" in line for line in added), added
        assert any("Dragon hits Serana (-27)." in line for line in added), added

    def test_ship_serpent_ranged_uses_projectile_not_cannonfire(self, asset_mgr, monkeypatch):
        """Ship battles use single-target LoS projectiles instead of party-wide cannonfire."""
        import py_exodus.combat.resolver as resolver
        from py_exodus.constants import Transport

        party = Party()
        party.add_member(
            Character("Serana", Sex.FEMALE, profession=Profession.FIGHTER, hp=100, max_hp=100)
        )
        party.transport = Transport.SHIP
        session = PlaySession(asset_mgr).start(party=party)
        session.enter_combat(creature_tile="serpent", monster_count=1)
        arena = session.screen.arena
        assert arena.ship_battle

        arena.monsters[0].x, arena.monsters[0].y = 5, 2
        px, py = arena.player_positions[0]
        arena.monsters[0].x = px
        monkeypatch.setattr(random, "randrange", lambda n: 0 if n == 100 else 12)
        monkeypatch.setattr(resolver, "roll_hit", lambda *a, **k: True)
        before = session.transcript

        session.press("SPACE")

        added = session.transcript[len(before):]
        assert not any("Cannonball barrage!" in line for line in added), added
