"""Unit tests for RosterScreen (party assembly and character creation)."""
import pygame
import pytest

from py_exodus.constants import ArmorType, Profession, Race, Sex, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.roster_screen import RosterScreen, get_starter_roster
from py_exodus.state_machine import StateMachine


def test_roster_screen_initialization(pygame_setup, asset_mgr):
    """Verify RosterScreen initializes with default roster recruits."""
    scr = RosterScreen(asset_mgr=asset_mgr)
    assert len(scr.roster) >= 4
    assert len(scr.party.members) == 0


def test_roster_screen_add_and_remove_member(pygame_setup, asset_mgr):
    """Verify [A]dd and [R]emove keyboard commands manage party slots."""
    party = Party()
    scr = RosterScreen(party=party, asset_mgr=asset_mgr)

    # Press 'A' to add highlighted member (Fighter)
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


def test_roster_screen_quick_party(pygame_setup, asset_mgr):
    """Verify pressing 'Q' loads a full 4-member classic party."""
    party = Party()
    scr = RosterScreen(party=party, asset_mgr=asset_mgr)

    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert len(scr.party.members) == 4
    names = [m.name for m in scr.party.members]
    assert "Fighter" in names
    assert "Cleric" in names
    assert "Wizard" in names
    assert "Thief" in names


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

    # Step 5: Portrait index (number + Enter)
    assert scr.text_log.is_waiting_for_input
    assert "Portrait" in scr.text_log.current_prompt
    for ch in "5\r":
        scr.text_log.handle_char(ch)

    # Step 6-9: stat allocation, each 5-25, total <= 50
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
    assert created.portrait_index == 5


def test_roster_screen_embark_validation(pygame_setup, asset_mgr):
    """Verify cannot embark with empty party, but transitions when party is formed."""
    sm = StateMachine(asset_mgr)
    scr = RosterScreen(asset_mgr=asset_mgr, manager=sm)
    sm.push_screen(scr)

    # Empty party embark fails
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))
    assert any("Cannot embark" in msg for msg in scr.text_log.history)

    # Add quick party and embark
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert len(scr.party.members) == 4
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))

    from py_exodus.screens.overworld import OverworldScreen
    assert isinstance(sm.current_screen, OverworldScreen)


def test_roster_screen_rendering(pygame_setup, asset_mgr):
    """Verify RosterScreen renders to 320x200 surface without errors."""
    scr = RosterScreen(asset_mgr=asset_mgr)
    surf = pygame.Surface((320, 200))
    scr.render(surf)
