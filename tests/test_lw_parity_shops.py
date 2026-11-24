"""LairWare parity, batch S (shops and services).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "S - Shops".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import ArmorType, Profession, Race, Status, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.town import TownScreen

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def assets():
    am = AssetManager()
    am.load_tiles()
    am.load_xml_definitions()
    return am


def _party(*golds: int) -> Party:
    members = [
        PartyMember(Character(f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER, hp=300))
        for i in range(len(golds) or 1)
    ]
    party = Party(members, x=10, y=10, transport=Transport.FOOT)
    for m, g in zip(party.members, golds or (1000,)):
        m.gold = g
    return party


def _vendor(assets, town: str, vtype: str):
    for v in assets.vendor_classes[vtype].vendors:
        if v.id.upper() == town.upper():
            return v
    raise LookupError((town, vtype))


def _log(town: TownScreen) -> str:
    lines = list(town.text_log.history)
    if town.text_log.is_waiting_for_input:
        lines.append(town.text_log.current_prompt)
    return " ".join(" ".join(lines).split())


def _shop(vendor, party: Party, member: int = 0) -> TownScreen:
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(vendor, buyer=party.members[member])
    return town


# --- Grocer --------------------------------------------------------------------


def test_grocer_one_gold_per_ration(assets):
    """UltimaMisc.c:1660-1690 (message 192 "RATIONS: 1 g.p. EACH, How many
    would you like?"): every grocer sells single rations at 1 gold each; the
    count is the food bought."""
    for v in assets.vendor_classes["FOOD"].vendors:
        (item,) = v.items
        assert (item.price, item.quantity) == (1, 1), v.id
    party = _party(500)
    m = party.members[0]
    m.food = 100
    town = _shop(_vendor(assets, "YEW", "FOOD"), party)
    town.text_log.submit_input("y")
    town.text_log.submit_input("137")
    assert m.food == 237 and m.gold == 363


def test_grocer_not_enough_room_past_9999(assets):
    """UltimaMisc.c:1668-1673: ``if (input > (9999 - existingFood)) {
    UPrintMessageRewrapped(260); ... goto shop1; }`` -- refused and asked
    again; exactly the room left is sold."""
    party = _party(500)
    m = party.members[0]
    m.food = 9900
    town = _shop(_vendor(assets, "YEW", "FOOD"), party)
    town.text_log.submit_input("y")
    town.text_log.submit_input("100")
    assert "Not enough room!" in _log(town)
    assert m.food == 9900 and m.gold == 500
    assert "how many" in town.text_log.current_prompt.lower()
    town.text_log.submit_input("99")
    assert m.food == 9999 and m.gold == 401
