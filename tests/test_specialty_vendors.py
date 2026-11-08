"""Tests for specialty vendors: Tavern (Food/Ale tipping clues) and Oracle (offerings/prophecies)."""
import pytest
from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.town import TownScreen


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def party():
    members = [
        PartyMember(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100)),
    ]
    return Party(members, x=10, y=10, gold=1000, transport=Transport.FOOT)


def test_tavern_food_purchase(asset_mgr, party):
    """Buying food in tavern deducts gold and adds food to member/party."""
    # Fawn tavern vendor: Sam's Canteen
    vendor = asset_mgr.vendors.get("sam's canteen") or asset_mgr.get_vendor(3, 43, 26)
    assert vendor is not None
    assert vendor.vendor_type == "TAVERNINFO"

    town = TownScreen(party=party, map_id=3, asset_mgr=asset_mgr, start_x=43, start_y=26)
    initial_gold = party.gold
    initial_food = party.members[0].food

    # Start shopping dialog
    town._start_vendor_shopping(vendor, buyer=party.members[0])
    assert town.text_log.is_waiting_for_input

    # Choose 'F' for food
    town.text_log.handle_char("F")

    # Enter quantity '5'
    assert town.text_log.is_waiting_for_input
    town.text_log.submit_input("5")

    assert party.members[0].food == initial_food + 5
    assert party.gold < initial_gold
    assert any("Here ye arr" in msg for msg in town.text_log.history)


def test_tavern_ale_tipping_reveals_rumor(asset_mgr, party):
    """Buying ale with a tip prints the corresponding rumor clue from vendor.xml."""
    vendor = asset_mgr.vendors.get("sam's canteen") or asset_mgr.get_vendor(3, 43, 26)
    assert vendor is not None

    town = TownScreen(party=party, map_id=3, asset_mgr=asset_mgr, start_x=43, start_y=26)
    initial_gold = party.gold

    town._start_vendor_shopping(vendor, buyer=party.members[0])
    # Choose 'A' for ale
    town.text_log.handle_char("A")

    # Ale costs 2gp; tip 20gp -> pay 22gp
    assert town.text_log.is_waiting_for_input
    town.text_log.submit_input("22")

    assert party.gold == initial_gold - 22
    # 20gp tip corresponds to Dawn conjunction clue: "Dawn is a city of myths and magic"
    assert any("Dawn is a city" in msg for msg in town.text_log.history)


def test_oracle_prophecy_offering(asset_mgr, party):
    """Offering 300 gp to the Oracle reveals the corresponding 300 gp prophecy."""
    # British Castle Oracle: Radrion
    vendor = asset_mgr.vendors.get("radrion") or asset_mgr.get_vendor(1, 20, 44)
    assert vendor is not None
    assert vendor.vendor_type == "ORACLEINFO"

    town = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr, start_x=20, start_y=44)
    initial_gold = party.gold

    town._start_vendor_shopping(vendor, buyer=party.members[0])
    assert town.text_log.is_waiting_for_input

    # Offer '3' (300 gp)
    town.text_log.handle_char("3")
    town.text_log.handle_enter()

    assert party.gold == initial_gold - 300
    # 300 gp prophecy: "Devil Guard"
    assert any("Devil Guard" in msg for msg in town.text_log.history)
