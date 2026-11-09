"""Unit tests for RosterScreen (party assembly and character creation)."""
import pygame
import pytest

from py_exodus.constants import ArmorType, Profession, Race, Sex, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.roster_screen import RosterScreen
from py_exodus.state_machine import StateMachine


def _roster_char(name: str) -> Character:
    """Build a roster recruit the way the creation wizard does.

    Java ManagePartyScreen.java:185-192: creation starts with health/food/gold
    = 150, NO weapon or armor, and MP from the getMaxMana formula.
    """
    c = Character(
        name=name,
        sex=Sex.MALE,
        race=Race.HUMAN,
        profession=Profession.FIGHTER,
        strength=10,
        dexterity=10,
        intelligence=10,
        wisdom=10,
        hp=150,
        max_hp=150,
        food=150,
        gold=150,
    )
    c.mp = c.compute_max_mp()
    return c


def test_roster_screen_initialization(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Verify RosterScreen starts empty — Java ships no default party or
    starter roster; new players create characters in the roster screen."""
    monkeypatch.chdir(tmp_path)
    scr = RosterScreen(asset_mgr=asset_mgr)
    assert scr.roster == []
    assert len(scr.party.members) == 0


def test_roster_screen_add_and_remove_member(pygame_setup, asset_mgr):
    """Verify [A]dd and [R]emove keyboard commands manage party slots."""
    party = Party()
    scr = RosterScreen(
        party=party, asset_mgr=asset_mgr, roster=[_roster_char("Ariel"), _roster_char("Bors")]
    )

    # Press 'A' to add highlighted member (Ariel)
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
    assert len(scr.party.members) == 1
    assert scr.party.members[0].name == scr.roster[0].name

    # Press 'Down' and 'A' to add second member
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
    assert len(scr.party.members) == 2

    # Press 'R' to remove member
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    assert len(scr.party.members) == 1


def test_roster_screen_no_quick_start_party(pygame_setup, asset_mgr):
    """The quick-start party was removed by user ruling: [Q] forms nothing."""
    party = Party()
    scr = RosterScreen(party=party, asset_mgr=asset_mgr, roster=[_roster_char("Ariel")])

    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert len(scr.party.members) == 0


def test_roster_screen_character_creation(pygame_setup, asset_mgr):
    """Verify interactive wizard creates new character and adds to roster."""
    scr = RosterScreen(asset_mgr=asset_mgr)
    roster_count_before = len(scr.roster)

    # Trigger Create Character
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
    assert scr.text_log.is_waiting_for_input
    assert "Name" in scr.text_log.current_prompt

    # Enter Name
    for ch in "Lancelot\r":
        scr.text_log.handle_char(ch)

    # Step 2: Sex (instant single-character input)
    assert scr.text_log.is_waiting_for_input
    assert "Sex" in scr.text_log.current_prompt
    scr.text_log.handle_char("M")

    # Step 3: Race (instant single-character input)
    assert scr.text_log.is_waiting_for_input
    assert "Race" in scr.text_log.current_prompt
    scr.text_log.handle_char("H")

    # Step 4: Class (instant single-character input)
    assert scr.text_log.is_waiting_for_input
    assert "Class" in scr.text_log.current_prompt
    scr.text_log.handle_char("P")

    # The portrait-number prompt step was removed by user ruling (user:
    # "dump the faces/images for characters"); the wizard goes straight
    # from Class to stat allocation. No "Portrait" prompt may ever appear.
    assert "Portrait" not in scr.text_log.current_prompt

    # Step 5-8: stat allocation, each 5-25, total <= 50
    for word, value in [("Strength", 10), ("Dexterity", 10), ("Intelligence", 10), ("Wisdom", 10)]:
        assert scr.text_log.is_waiting_for_input
        assert word in scr.text_log.current_prompt, scr.text_log.current_prompt
        for ch in f"{value}\r":
            scr.text_log.handle_char(ch)

    # Wizard finished
    assert not scr.text_log.is_waiting_for_input
    assert len(scr.roster) == roster_count_before + 1
    created = scr.roster[-1]
    assert created.name == "Lancelot"
    assert created.sex == Sex.MALE
    assert created.race == Race.HUMAN
    assert created.profession == Profession.PALADIN
    # Java ManagePartyScreen.java:185-192 — creation start values
    assert created.hp == 150 and created.max_hp == 150
    assert created.food == 150 and created.gold == 150
    assert created.weapon == WeaponType.NONE
    assert created.armor == ArmorType.NONE
    # Portrait field preserved for save compatibility but invisible: the
    # wizard no longer asks, the value stays at its default.
    assert created.portrait_index == 43


def test_roster_screen_embark_validation(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Verify cannot embark with empty party, but transitions and writes both
    save records when the party is formed."""
    monkeypatch.chdir(tmp_path)
    sm = StateMachine(asset_mgr)
    scr = RosterScreen(
        asset_mgr=asset_mgr, manager=sm, roster=[_roster_char("Ariel"), _roster_char("Bors")]
    )
    sm.push_screen(scr)

    # Empty party embark fails
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))
    assert any("Cannot embark" in msg for msg in scr.text_log.history)

    # Form a party from roster-created characters and embark
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
    assert len(scr.party.members) == 2
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))

    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.save_system import SaveSystem

    assert isinstance(sm.current_screen, OverworldScreen)

    loaded = SaveSystem.load_game(tmp_path / "saves" / "party.json")
    assert loaded.members[0].name == "Ariel"
    saved_roster = SaveSystem.load_roster(tmp_path / "saves" / "roster.json")
    assert [c.name for c in saved_roster] == ["Ariel", "Bors"]


def test_roster_screen_rendering(pygame_setup, asset_mgr):
    """Verify RosterScreen renders to 320x200 surface without errors."""
    scr = RosterScreen(asset_mgr=asset_mgr)
    surf = pygame.Surface((320, 200))
    scr.render(surf)
