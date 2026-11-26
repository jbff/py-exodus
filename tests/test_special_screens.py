"""Tests for Special Screens: Shrines, Book of Lore, and Final Epilogue."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException
from py_exodus.screens.base import BaseScreen
from py_exodus.screens.book import BookScreen
from py_exodus.screens.final import FinalScreen


@pytest.fixture(autouse=True)
def init_pygame():
    """Ensure pygame and display/font are initialized in headless mode."""
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


def test_book_screen_loads_lore_and_spell_appendix():
    """Book of Lore: ultima3.txt chapters plus the Python-only spell reference."""
    scr = BookScreen(return_screen=None)
    assert scr.page_count > 1
    full_text = "\n".join(c.text for c in scr.chapters)
    # Lore from Java BookScreen.java:53 (/assets/data/ultima3.txt)
    assert scr.chapters[0].title == "Commands"
    assert "A) Attack" in full_text
    # Spell reference kept as the closing chapters (Python-only invention)
    assert "REPOND" in full_text
    assert "PONTORI" in full_text


def test_book_screen_navigation_and_rendering():
    """Verify BookScreen paging, rendering, and exit."""
    dummy_return = BaseScreen()
    scr = BookScreen(return_screen=dummy_return)

    # Right turns from the contents page to the first spread
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
    scr.update(0.016)
    assert scr.view_index == 1

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

    # Love at x30, Sol x31, Moons x32, Death x33, in that order (LW lastCard)
    for card, px in (("love", 30), ("sol", 31), ("moons", 32), ("death", 33)):
        p.x = px
        p.y = 12
        res = scr.insert_card(card, member_idx=0, pos=(px, 12))
        assert res is True
    assert p.exodus_cards_status == 0x1 | 0x2 | 0x4 | 0x8
    assert c.cards == [1, 1, 1, 1]  # LairWare keeps the cards
    assert scr.victory is True


def test_final_screen_wrong_sequence():
    """Java: a card at a wrong panel costs health + 1 (lethal), no status bit."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.hp = 100
    c.cards = [1, 1, 1, 1]
    p.add_member(c)

    scr = FinalScreen(party=p, return_screen=None)

    # Inserting Love at x31 (Sol's panel) kills Hero but the card survives:
    # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): card survives a
    # wrong-panel insert (GBC menucmd3.c:959; LW UltimaMisc.c:2305-2350 card
    # never consumed on wrong panel). A wipe raises PartyDeathException
    # (Party.java:572-574)
    with pytest.raises(PartyDeathException):
        scr.insert_card("love", member_idx=0, pos=(31, 12))
    assert p.exodus_cards_status == 0
    assert not scr.victory
    assert c.status == Status.DEAD
    assert c.hp == 0
    assert c.cards[0] == 1  # card survives the wrong insert
    assert scr.last_message != ""


def test_final_screen_ending_starts_with_the_flashes():
    """The fourth card starts LairWare's ending: the flashes first, and the
    old shake, debris and scrolling text are gone."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.cards = [1, 1, 1, 1]
    p.add_member(c)

    scr = FinalScreen(party=p, return_screen=None)
    # Insert each card onto its own panel, in LW order (UltimaMisc.c:2333)
    for card, px in (("love", 30), ("sol", 31), ("moons", 32), ("death", 33)):
        assert scr.insert_card(card, member_idx=0, pos=(px, 12)) is True

    assert scr.victory is True
    assert scr.phase == "flash"
    for gone in ("screen_shake", "shake_timer", "particles", "scroll_y", "epilogue_text"):
        assert not hasattr(scr, gone)

    # Updating and rendering during the ending, with no screen underneath
    surface = pygame.Surface((320, 200))
    scr.update(1.0)
    scr.render(surface)
    assert scr.flash_colours


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


def test_book_screen_pagination():
    """Verify BookScreen turns forward and back through the spreads."""
    scr = BookScreen(return_screen=None)
    surface = pygame.Surface((320, 200))

    assert scr.view_index == 0  # the contents page
    scr.render(surface)

    event_right = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT)
    scr.handle_event(event_right)
    assert scr.view_index == 1
    scr.render(surface)
    scr.handle_event(event_right)
    assert scr.view_index == 2

    # Space steps forward; LEFT steps back
    event_space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    scr.handle_event(event_space)
    assert scr.view_index == 3
    event_left = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT)
    scr.handle_event(event_left)
    assert scr.view_index == 2


def test_party_exodus_defeated_roundtrip():
    """The beat-Exodus flag (LW Party[16]) is written with the party but
    loads as 0: a won save predates the game ending at the fall (user ruling
    2026-11-25), so it plays on as not won."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    p.add_member(c)
    p.exodus_defeated = 1
    data = p.to_dict()
    assert data["exodus_defeated"] == 1
    restored = Party.from_dict(data)
    assert restored.exodus_defeated == 0
    # Legacy save without the key loads the pre-win default.
    legacy = Party.from_dict({k: v for k, v in data.items() if k != "exodus_defeated"})
    assert legacy.exodus_defeated == 0


def test_final_victory_sets_exodus_defeated():
    """Inserting all four cards (LW UltimaMisc.c:2359 — Party[16] = 1) flips
    the beat-Exodus flag on the party record."""
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.cards = [1, 1, 1, 1]
    p.add_member(c)
    scr = FinalScreen(party=p, return_screen=None)
    assert p.exodus_defeated == 0
    for card, px in (("love", 30), ("sol", 31), ("moons", 32), ("death", 33)):
        p.x = px
        p.y = 12
        assert scr.insert_card(card, member_idx=0, pos=(px, 12)) is True
    assert scr.victory is True
    assert p.exodus_defeated == 1


def test_final_screen_card_from_any_party_member():
    """Verify any party member carrying a card can insert it via key event."""
    p = Party()
    c1 = Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER)
    c2 = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC)
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
    assert c2.cards[3] == 1  # inserted by c2, who keeps it (LairWare)

