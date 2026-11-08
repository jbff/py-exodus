"""Task 3: Exodus endgame — INSERT wiring, card indices, FinalScreen reachable.

Java truth: ``exodus/SecondaryInputProcessor.java:613-731`` (INSERT +
``InsertCardInputAdapter``), ``exodus/Party.java:703-715`` (zstats marks/cards
rows), ``exodus/GameScreen.java:299-311`` (exodusCardsStatus persist/reload).

Card indices are ``[DEATH, SOL, MOONS, LOVE] = cards[0..3]``; panels are at
EXODUS x 30 (love), 31 (sol), 32 (moons), 33 (death), all y 12; wrong panel
costs health + 1 (lethal); all four bits set => FinalScreen (win epilogue).
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException
from py_exodus.save_system import SaveSystem
from py_exodus.screens.final import (
    CARD_NAME_TO_INDEX,
    FinalScreen,
    all_cards_inserted,
    apply_exodus_card_tiles,
    is_machine_region,
)
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.town import TownScreen
from py_exodus.state_machine import StateMachine
from py_exodus.ui.stats_panel import StatsPanel, mark_and_card_rows


@pytest.fixture(scope="module")
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


def card_party(x: int = 30, y: int = 12, cards=(1, 1, 1, 1), members: int = 1) -> Party:
    """Party standing at an EXODUS panel with a card-holding member."""
    party = Party(members=[], x=x, y=y, map_id=2, food=400, transport=Transport.FOOT)
    for i in range(members):
        char = Character(
            name=f"Hero{i}", sex="M", race=Race.HUMAN, profession=Profession.FIGHTER
        )
        char.hp = 100
        char.cards = list(cards)
        party.add_member(char)
    return party


def type_prompt(text_log, text: str) -> None:
    """Type a full prompt answer (no auto-commit) and press enter."""
    for ch in text:
        text_log.handle_char(ch)
    text_log.handle_enter()


def single_char(text_log, char: str) -> None:
    text_log.handle_char(char)  # single_char prompts commit immediately


# --- Card index order: [DEATH, SOL, MOONS, LOVE] = cards[0..3] ---


def test_card_index_order_matches_java():
    """Java: L->3(SPP.java:664), S->1, M->2, D->0; Party.java:708-711 row labels."""
    assert CARD_NAME_TO_INDEX["love"] == 3
    assert CARD_NAME_TO_INDEX["sol"] == 1
    assert CARD_NAME_TO_INDEX["moons"] == 2
    assert CARD_NAME_TO_INDEX["death"] == 0


def test_insert_love_consumes_cards3_and_sets_bit1():
    """Inserting Love sets cards[3] and status bit 0x1, not cards[0] (SPP.java:664,682-686)."""
    party = card_party()
    scr = FinalScreen(party=party)

    res = scr.insert_card("love", member_idx=0, pos=(30, 12))

    assert res is True
    assert party.exodus_cards_status == 0x1
    assert party.members[0].cards[3] == 0
    assert party.members[0].cards[0] == 1  # death untouched
    assert all_cards_inserted(party.exodus_cards_status) is False


def test_insert_sol_moons_death_bits():
    """Sol->0x2 at x31, Moons->0x4 at x32, Death->0x8 at x33 (SPP.java:665-667)."""
    party = card_party()
    scr = FinalScreen(party=party)
    assert scr.insert_card("sol", member_idx=0, pos=(31, 12)) is True
    assert scr.insert_card("moons", member_idx=0, pos=(32, 12)) is True
    assert scr.insert_card("death", member_idx=0, pos=(33, 12)) is True
    assert party.exodus_cards_status == 0x2 | 0x4 | 0x8
    assert party.members[0].cards[1] == 0
    assert party.members[0].cards[2] == 0
    assert party.members[0].cards[0] == 0


def test_insert_wildcard_no_forced_order():
    """Each panel is independent: any card order reaches victory (no Love->Sol->...)."""
    party = card_party()
    scr = FinalScreen(party=party)
    for card, px in (("death", 33), ("moons", 32), ("love", 30), ("sol", 31)):
        assert scr.insert_card(card, member_idx=0, pos=(px, 12)) is True
    assert all_cards_inserted(party.exodus_cards_status) is True
    assert scr.victory is True


# --- Wrong panel: health + 1 damage (lethal), no bit (SPP.java:687-690) ---


def test_wrong_panel_lethal_no_bit():
    """Inserting Love while standing on another panel eats the card and kills."""
    party = card_party(x=31, y=12)
    scr = FinalScreen(party=party)

    with pytest.raises(PartyDeathException):
        scr.insert_card("love", member_idx=0, pos=(31, 12))

    m = party.members[0]
    assert m.status == Status.DEAD
    assert m.hp == 0
    assert party.exodus_cards_status == 0  # no bit set
    assert m.cards[3] == 0  # card consumed even on a wrong panel (SPP.java:680-682)


def test_insert_non_panel_position_lethal_no_bit():
    """x=29 at y=12 is a wrong panel too: card eaten, lethal damage, no bit."""
    party = card_party(x=29, y=12)
    scr = FinalScreen(party=party)

    with pytest.raises(PartyDeathException):
        scr.insert_card("love", member_idx=0, pos=(29, 12))

    assert party.exodus_cards_status == 0
    assert party.members[0].status == Status.DEAD
    assert party.members[0].cards[3] == 0


def test_wrong_panel_damages_only_selected_member():
    """With party members alive, the selected member dies but no exception."""
    party = card_party(x=31, y=12, members=2)
    scr = FinalScreen(party=party)

    res = scr.insert_card("death", member_idx=0, pos=(31, 12))

    assert res is False
    assert party.members[0].hp == 0
    assert party.members[0].status == Status.DEAD
    assert party.members[1].status == Status.GOOD
    assert party.exodus_cards_status == 0


def test_insert_none_owned():
    """No card of that kind: 'None owned!', no bit, no damage (SPP.java:693-695)."""
    party = card_party(cards=(1, 0, 0, 0))
    scr = FinalScreen(party=party)

    res = scr.insert_card("love", member_idx=0, pos=(30, 12))

    assert res is False
    assert scr.last_message == "None owned!"
    assert party.exodus_cards_status == 0
    assert party.members[0].status == Status.GOOD


def test_unknown_card_asks_what():
    party = card_party()
    scr = FinalScreen(party=party)
    assert scr.insert_card("banana", member_idx=0, pos=(30, 12)) is False
    assert scr.last_message == "What?"


# --- Region gate (SPP.java:614-619) ---


def test_machine_region_gate():
    assert is_machine_region(29, 12) is False
    assert is_machine_region(34, 12) is False
    assert is_machine_region(30, 11) is False
    assert is_machine_region(30, 12) is True
    assert is_machine_region(33, 12) is True


# --- Overworld typed INSERT flow ---


def test_overworld_insert_rejects_off_machine(pygame_setup, asset_mgr):
    """INSERT typed outside the machine region on the EXODUS map: 'What?'."""
    party = card_party(x=29, y=12)
    ow = OverworldScreen(party=party, map_id=2, asset_mgr=asset_mgr)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(ow.text_log, "INSERT")

    assert ow.text_log.is_waiting_for_input is False
    assert any(m == "What?" for m in ow.text_log.history)
    assert party.exodus_cards_status == 0


def test_overworld_insert_rejects_other_map(pygame_setup, asset_mgr):
    """INSERT away from the EXODUS map always answers 'What?' (SPP.java:618)."""
    party = card_party(x=32, y=12)
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(ow.text_log, "INSERT")

    assert any(m == "What?" for m in ow.text_log.history)
    assert ow.text_log.is_waiting_for_input is False


def test_overworld_insert_flow_correct_panel(pygame_setup, asset_mgr):
    """Typing INSERT on a panel prompts member then card; Love at x30 sets 0x1."""
    party = card_party(x=30, y=12)
    ow = OverworldScreen(party=party, map_id=2, asset_mgr=asset_mgr)

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(ow.text_log, "INSERT")
    assert "Which party member?" in ow.text_log.current_prompt
    single_char(ow.text_log, "1")
    assert "D, S, L, M:" in ow.text_log.current_prompt
    single_char(ow.text_log, "L")

    assert party.exodus_cards_status == 0x1
    assert party.members[0].cards[3] == 0
    assert ow.game_map.get_tile(30, 11).name == "floor"
    assert any(
        "Card of Love" in m for m in ow.text_log.history
    )


def test_overworld_all_four_cards_reach_final_screen(pygame_setup, asset_mgr):
    """All four bits set => FinalScreen instantiated and shown (SPP.java:718-731)."""
    party = card_party(x=30, y=12)
    sm = StateMachine(asset_mgr=asset_mgr)
    ow = OverworldScreen(party=party, map_id=2, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    # First card from (30, 12)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(ow.text_log, "INSERT")
    single_char(ow.text_log, "1")
    single_char(ow.text_log, "L")
    assert party.exodus_cards_status == 0x1

    # Remaining cards: move onto each panel and repeat
    for px, letter in ((31, "S"), (32, "M"), (33, "D")):
        party.x = px
        ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
        type_prompt(ow.text_log, "INSERT")
        single_char(ow.text_log, "1")
        single_char(ow.text_log, letter)

    assert all_cards_inserted(party.exodus_cards_status) is True
    assert isinstance(sm.current_screen, FinalScreen)
    assert sm.current_screen.victory is True


def test_overworld_lethal_insert_routes_game_over(pygame_setup, asset_mgr):
    """Wrong-card insert killing the last member routes to the game over screen."""
    party = card_party(x=31, y=12, cards=(0, 0, 0, 1))
    sm = StateMachine(asset_mgr=asset_mgr)
    ow = OverworldScreen(party=party, map_id=2, asset_mgr=asset_mgr, manager=sm)
    sm.set_screen(ow)

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(ow.text_log, "INSERT")
    single_char(ow.text_log, "1")
    single_char(ow.text_log, "L")  # love panel is x30; standing on x31

    assert party.members[0].status == Status.DEAD
    from py_exodus.screens.start import StartScreen

    assert isinstance(sm.current_screen, StartScreen)
    assert sm.current_screen.game_over is True


# --- Town "Other command" INSERT path ---


def test_town_insert_flow(pygame_setup, asset_mgr):
    """TownScreen on the EXODUS map: INSERT at a panel inserts the card."""
    party = card_party()
    town = TownScreen(party=party, map_id=2, start_x=32, start_y=12, asset_mgr=asset_mgr)

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(town.text_log, "INSERT")
    single_char(town.text_log, "1")
    single_char(town.text_log, "M")

    assert party.exodus_cards_status == 0x4
    assert party.members[0].cards[2] == 0
    assert town.game_map.get_tile(32, 11).name == "floor"


def test_town_insert_rejects_other_town(pygame_setup, asset_mgr):
    """INSERT in a normal city answers 'What?' (SPP.java:617-619)."""
    party = card_party(x=32, y=12)
    party.map_id = 1
    town = TownScreen(party=party, map_id=1, start_x=32, start_y=12, asset_mgr=asset_mgr)

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o))
    type_prompt(town.text_log, "INSERT")

    assert any(m == "What?" for m in town.text_log.history)
    assert party.exodus_cards_status == 0


# --- Persist / reload (GameScreen.java:299-311) ---


def test_exodus_cards_status_persists(tmp_path):
    party = Party(members=[])
    party.exodus_cards_status = 0x5
    path = tmp_path / "party.json"
    SaveSystem.save_game(party, path)
    loaded = SaveSystem.load_game(path)
    assert loaded.exodus_cards_status == 0x5


def test_reload_sets_cleared_panel_tiles(pygame_setup, asset_mgr):
    """Bits set => machine tiles become floor at (x, 11); unset panels untouched."""
    from py_exodus.world.loader import MapLoader

    game_map = MapLoader(asset_mgr).load_map(2)
    apply_exodus_card_tiles(game_map, asset_mgr, 0x2)
    assert game_map.get_tile(31, 11).name == "floor"
    assert game_map.get_tile(30, 11).name == "exodus"


def test_screens_apply_card_tiles_on_enter(pygame_setup, asset_mgr):
    party = card_party()
    party.exodus_cards_status = 0x8
    ow = OverworldScreen(party=party, map_id=2, asset_mgr=asset_mgr)
    ow.on_enter()
    assert ow.game_map.get_tile(33, 11).name == "floor"

    party2 = card_party()
    party2.exodus_cards_status = 0x1
    town = TownScreen(party=party2, map_id=2, start_x=30, start_y=12, asset_mgr=asset_mgr)
    town.on_enter()
    assert town.game_map.get_tile(30, 11).name == "floor"


# --- Zstats marks / cards rows (Party.java:703-715) ---


def test_stats_panel_mark_and_card_rows():
    member = card_party(members=1).members[0]
    member.marks = [1, 0, 2, 3]
    member.cards = [0, 1, 1, 0]

    rows = mark_and_card_rows(member)
    text = "\n".join(rows)
    assert "MARK KINGS: 1" in text
    assert "MARK SNAKE: 2" in text
    assert "MARK FORCE: 3" in text
    assert "CARD DEATH: 1" not in text
    assert "CARD SOL: 1" in text
    assert "CARD MOONS: 1" in text
    assert "MARK FIRE" not in text
    assert "CARD LOVE" not in text


def test_stats_panel_renders_rows_without_marks():
    member = card_party(members=1).members[0]
    member.cards = [0, 0, 0, 0]
    assert mark_and_card_rows(member) == []


def test_stats_panel_render_smoke(pygame_setup):
    party = card_party()
    party.members[0].marks = [1, 0, 0, 0]
    party.members[0].cards = [0, 0, 0, 2]
    panel = StatsPanel()
    surface = pygame.Surface((140, 200))
    panel.set_inspect(0)
    panel.render(surface, party, inspect_index=0)
