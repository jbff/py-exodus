"""Tests for Special Screens: Shrines, Spellbook, and Final Epilogue."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.book import BookScreen
from py_exodus.screens.final import FinalScreen
from py_exodus.screens.shrine import ShrineScreen


@pytest.fixture(autouse=True)
def init_pygame():
    """Ensure pygame and display/font are initialized in headless mode."""
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


def test_shrine_stat_boost():
    """Verbatim test from task brief: Ambrosia Shrine stat donation."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.strength = 20
    p.add_member(c)
    p.gold = 200
    scr = ShrineScreen(party=p, stat_name="strength", return_screen=None)
    scr.donate(member_idx=0)
    assert c.strength == 21
    assert p.gold == 100


def test_shrine_stat_cap():
    """Ensure donation does not exceed the racial maximum cap."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.strength = Race.HUMAN.max_str  # 75
    p.add_member(c)
    p.gold = 200
    scr = ShrineScreen(party=p, stat_name="strength", return_screen=None)
    success = scr.donate(member_idx=0)
    assert success is True
    # Either capped at 75 or prevented from exceeding
    assert c.strength == Race.HUMAN.max_str
    # Gold might be deducted or refused, but stat must never exceed cap
    assert c.strength <= Race.HUMAN.max_str


def test_shrine_insufficient_gold():
    """Ensure party cannot donate if they have less than 100 gold."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.dexterity = 25
    p.add_member(c)
    p.gold = 50
    scr = ShrineScreen(party=p, stat_name="dexterity", return_screen=None)
    success = scr.donate(member_idx=0)
    assert success is False
    assert c.dexterity == 25
    assert p.gold == 50


def test_shrine_all_ambrosia_shrines():
    """Verify wisdom, dexterity, intelligence, and strength shrines."""
    p = Party()
    c = Character("Mage", "M", Race.ELF, Profession.WIZARD)
    c.strength = 15
    c.dexterity = 20
    c.intelligence = 25
    c.wisdom = 30
    p.add_member(c)
    p.gold = 1000

    for stat, initial in [
        ("strength", 15),
        ("dexterity", 20),
        ("intelligence", 25),
        ("wisdom", 30),
    ]:
        scr = ShrineScreen(party=p, stat_name=stat, return_screen=None)
        scr.donate(member_idx=0)
        assert getattr(c, stat) == initial + 1


def test_shrine_event_handling_and_rendering():
    """Verify ShrineScreen handles key events and renders to surface."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.strength = 20
    p.add_member(c)
    p.gold = 200

    dummy_return = BaseScreen()
    scr = ShrineScreen(party=p, stat_name="strength", return_screen=dummy_return)

    surface = pygame.Surface((320, 200))
    scr.render(surface)

    # Pressing '1' selects member 0
    event_1 = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1")
    scr.handle_event(event_1)
    assert scr.selected_member_idx == 0

    # Pressing '1' (or 'Y' or Enter) offers 100 gold
    event_y = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1")
    scr.handle_event(event_y)
    assert c.strength == 21

    # Update logic
    scr.update(0.1)

    # ESC key returns to return_screen
    event_esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    scr.handle_event(event_esc)
    assert scr.next_screen == dummy_return or scr.is_finished


def test_book_screen_pages_and_spells():
    """Verify BookScreen displays spells A-P with costs and descriptions."""
    scr = BookScreen(return_screen=None)
    assert scr.current_book in ("wizard", "cleric")

    # Check wizard spells
    scr.switch_book("wizard")
    wizard_spells = scr.get_spells()
    assert len(wizard_spells) == 16
    assert wizard_spells[0].code == "A"
    assert wizard_spells[0].name == "REPOND"
    assert wizard_spells[0].mp_cost == 0
    assert "Destroy" in wizard_spells[0].desc

    # Check clerical prayers
    scr.switch_book("cleric")
    cleric_spells = scr.get_spells()
    assert len(cleric_spells) == 16
    assert cleric_spells[0].code == "A"
    assert cleric_spells[0].name == "PONTORI"
    assert cleric_spells[0].mp_cost == 0
    assert "undead" in cleric_spells[0].desc.lower()


def test_book_screen_navigation_and_rendering():
    """Verify BookScreen tab switching, page scrolling, and rendering."""
    dummy_return = BaseScreen()
    scr = BookScreen(return_screen=dummy_return)

    initial_book = scr.current_book
    # TAB switches book
    tab_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
    scr.handle_event(tab_event)
    assert scr.current_book != initial_book

    # Scrolling or paging
    down_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN)
    scr.handle_event(down_event)
    scr.update(0.016)

    # Render surface
    surface = pygame.Surface((320, 200))
    scr.render(surface)

    # ESC exits to return_screen
    esc_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    scr.handle_event(esc_event)
    assert scr.next_screen == dummy_return or scr.is_finished


def test_final_screen_card_insertion_sequence():
    """Verify all four cards reach victory when placed on their own panel (order-free)."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    # Give all 4 cards to Hero: [Love, Sol, Moon, Death]
    c.cards = [1, 1, 1, 1]
    p.add_member(c)

    scr = FinalScreen(party=p, return_screen=None)
    assert not scr.victory

    # Each panel is independent: Love at x30, Sol x31, Moons x32, Death x33
    for card, px in (("love", 30), ("sol", 31), ("moons", 32), ("death", 33)):
        p.x = px
        p.y = 12
        res = scr.insert_card(card, member_idx=0, pos=(px, 12))
        assert res is True
    assert p.exodus_cards_status == 0x1 | 0x2 | 0x4 | 0x8
    assert c.cards == [0, 0, 0, 0]
    assert scr.victory is True


def test_final_screen_wrong_sequence():
    """Java: a card at a wrong panel costs health + 1 (lethal), no status bit."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.hp = 100
    c.cards = [1, 1, 1, 1]
    p.add_member(c)

    scr = FinalScreen(party=p, return_screen=None)

    # Inserting Love at x31 (Sol's panel) consumes the card and kills Hero;
    # a wipe raises PartyDeathException (Party.java:572-574)
    with pytest.raises(PartyDeathException):
        scr.insert_card("love", member_idx=0, pos=(31, 12))
    assert p.exodus_cards_status == 0
    assert not scr.victory
    assert c.status == Status.DEAD
    assert c.hp == 0
    assert scr.last_message != ""


def test_final_screen_epilogue_and_effects():
    """Verify victory fanfare, screen shake/crumbling effects, and epilogue text scroll."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.cards = [1, 1, 1, 1]
    p.add_member(c)

    scr = FinalScreen(party=p, return_screen=None)
    # Insert each card onto its own panel (order-free)
    for card, px in (("love", 30), ("moons", 32), ("death", 33), ("sol", 31)):
        assert scr.insert_card(card, member_idx=0, pos=(px, 12)) is True

    assert scr.victory is True
    assert scr.screen_shake is True
    assert scr.fanfare_played is True
    assert "EXODUS" in scr.epilogue_text
    assert "ULTIMA IV" in scr.epilogue_text

    # Updating simulates shake timer and epilogue text scrolling
    initial_scroll = scr.scroll_y
    scr.update(1.0)
    assert scr.scroll_y != initial_scroll or scr.shake_timer > 0

    # Rendering during victory
    surface = pygame.Surface((320, 200))
    scr.render(surface)


def test_base_screen_interface():
    """Verify BaseScreen interface methods."""
    class CustomScreen(BaseScreen):
        pass

    scr = CustomScreen()
    assert hasattr(scr, "handle_event")
    assert hasattr(scr, "update")
    assert hasattr(scr, "render")

    # Calling base methods shouldn't raise unhandled errors
    scr.update(0.1)
    surf = pygame.Surface((10, 10))
    scr.render(surf)
    scr.handle_event(pygame.event.Event(pygame.NOEVENT))


def test_shrine_render_with_asset_manager():
    """Verify ShrineScreen.render() uses render_viewport() and does not crash with real AssetManager."""
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()

    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    p.add_member(c)
    p.gold = 500

    scr = ShrineScreen(party=p, stat_name="strength", return_screen=None, asset_mgr=am)
    assert scr.game_map is not None

    surface = pygame.Surface((320, 200))
    scr.render(surface)


def test_book_screen_pagination():
    """Verify BookScreen paginates 8 spells per page without overlap."""
    scr = BookScreen(return_screen=None)
    surface = pygame.Surface((320, 200))

    # Page 1 (spells A-H)
    assert scr.scroll_index == 0
    scr.render(surface)

    # Turn to page 2 (spells I-P)
    event_down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN)
    scr.handle_event(event_down)
    assert scr.scroll_index == 8
    scr.render(surface)

    # Space toggles back to page 1
    event_space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    scr.handle_event(event_space)
    assert scr.scroll_index == 0


def test_final_screen_card_from_any_party_member():
    """Verify any party member carrying a card can insert it via key event."""
    p = Party()
    c1 = Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER)
    c2 = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC)
    # c1 has no cards, c2 has the Love card (cards[3], Party.java:711)
    c1.cards = [0, 0, 0, 0]
    c2.cards = [0, 0, 0, 1]
    p.add_member(c1)
    p.add_member(c2)
    p.x = 30
    p.y = 12  # Love's machine panel

    scr = FinalScreen(party=p, return_screen=None)
    # Press 'L' to insert the Love card without selecting a member
    event_l = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_l)
    scr.handle_event(event_l)

    assert p.exodus_cards_status == 0x1
    assert c2.cards[3] == 0  # Consumed from c2

