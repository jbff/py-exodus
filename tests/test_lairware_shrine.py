"""Ambrosia's shrines, the LairWare way (user 2026-11-22: "no shrine screen,
follow LairWare"): Enter on the shrine, "Who enters?-", "Offering*100-", all in
the message log with LairWare's Shrine.jpg over the map. UltimaMain.c:1461-1484,
UltimaMisc.c:1000-1097."""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.world import shrine

# The four shrines on Ambrosia (maps.xml portals); x & 3 names the stat.
SITES = {"wisdom": (55, 27), "dexterity": (45, 52), "intelligence": (6, 6), "strength": (4, 36)}


@pytest.fixture
def amb():
    pygame.init()
    am = AssetManager(assets_dir="assets")
    am.load_tiles()
    am.load_xml_definitions()
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20)
    hero.gold = 2000
    party.add_member(hero)
    party.add_member(Character("Two", "F", Race.ELF, Profession.CLERIC))
    ow = OverworldScreen(party=party, map_id=13, asset_mgr=am, random_encounters=False)
    return ow


def _key(ow, ch):
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=ord(ch), unicode=ch))


def _visit(ow, stat, who="1", amount="5"):
    ow.party.x, ow.party.y = SITES[stat]
    _key(ow, "e")
    assert ow.text_log.current_prompt == shrine.PROMPT_WHO
    _key(ow, who)
    if ow.text_log.is_waiting_for_input:
        _key(ow, amount)


@pytest.mark.parametrize("stat", ["strength", "dexterity", "intelligence", "wisdom"])
def test_each_shrine_raises_its_stat_by_the_offering(amb, stat):
    hero = amb.party.members[0]
    setattr(hero, stat, 20)
    _visit(amb, stat, amount="5")
    assert getattr(hero, stat) == 25 and hero.gold == 1500
    assert f"Welcome to the Shrine of {stat.capitalize()}" in amb.text_log.history
    assert "SHAZAM!" in amb.text_log.history
    assert amb.shrine_member is None  # picture gone


def test_shrine_stat_follows_x_and_3():
    assert [shrine.shrine_stat(x) for x, _ in SITES.values()] == [
        "wisdom", "dexterity", "intelligence", "strength"]


def test_zero_is_then_be_off(amb):
    _visit(amb, "strength", amount="0")
    assert "Then be off!" in amb.text_log.history
    assert amb.party.members[0].strength == 20


def test_too_poor_is_you_cant_cheat_the_gods(amb):
    amb.party.members[0].gold = 300
    _visit(amb, "strength", amount="4")
    assert "YOU CAN'T CHEAT THE GODS!" in amb.text_log.history
    assert amb.party.members[0].gold == 300


def test_the_member_pays_from_their_own_purse(amb):
    amb.party.members[1].gold = 900
    _visit(amb, "strength", who="1", amount="2")
    assert amb.party.members[0].gold == 1800 and amb.party.members[1].gold == 900


def test_dead_member_is_incapacitated(amb):
    amb.party.members[1].status = Status.DEAD
    _visit(amb, "strength", who="2")
    assert "Incapacitated!" in amb.text_log.history
    assert not amb.text_log.is_waiting_for_input


def test_race_cap_and_over_debit(amb):
    hero = amb.party.members[0]
    hero.strength = Race.HUMAN.max_str - 1
    _visit(amb, "strength", amount="9")
    assert hero.strength == Race.HUMAN.max_str
    assert hero.gold == 2000 - 900  # LairWare charges the whole offering


def test_after_exodus_the_race_cap_lifts_but_99_holds(amb):
    hero = amb.party.members[0]
    amb.party.exodus_defeated = 1
    hero.strength = Race.HUMAN.max_str - 1
    _visit(amb, "strength", amount="5")
    assert hero.strength == Race.HUMAN.max_str + 4
    hero.strength = 98
    _visit(amb, "strength", amount="5")
    assert hero.strength == 99


def test_the_shrine_picture_covers_the_map_while_offering(amb):
    surf = pygame.Surface((960, 600))
    amb.party.x, amb.party.y = SITES["wisdom"]
    amb.render(surf)
    before = surf.get_at((264, 264))
    _key(amb, "e")
    _key(amb, "1")
    assert amb.shrine_member == 0
    amb.render(surf)
    assert surf.get_at((264, 264)) != before


def test_autoplay_offers_up_to_the_plan_target(amb):
    """At the wisdom shrine a WIS-30 Cleric offers toward the plan target
    (race-cap WIS since the user's 2026-11-22 ruling; one offering is at
    most 9 points), paying 100 a point (the old ShrineScreen test, ported)."""
    from py_exodus.autoplay import batch
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.state_machine import StateMachine

    party = batch.build_party()
    cleric = party.members[2]
    cleric.wisdom, cleric.gold = 30, 2000
    amb.party = party
    party.x, party.y = SITES["wisdom"]
    sm = StateMachine(asset_mgr=amb.asset_mgr, audio=None)
    sm.set_screen(amb)
    amb.begin_shrine()
    ctrl = AutoPlayController(enabled=True)
    for _ in range(3):
        if not amb.text_log.is_waiting_for_input:
            break
        ctrl.step(sm)  # the controller presses the key itself
    assert cleric.wisdom > 35
    assert cleric.gold == 2000 - 100 * (cleric.wisdom - 30)
