"""Tests for the per-class vendor dialog framework (Task 7).

Java truth: vendor/BaseVendor.java, FoodVendor.java, TavernService.java,
OracleService.java, HorseService.java.  Each vendor class is a state machine
keyed on the vendor's InventoryType; the member's own purse (member.gold,
adjust_gold 9999 cap) is charged, not a party pool.
"""
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.defs import VendorDef, VendorItemDef
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.town import TownScreen
from py_exodus.screens.vendor_dialog import create_vendor_dialog


@pytest.fixture(scope="module")
def pygame_setup():
    import pygame

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


def logtext(town: TownScreen) -> str:
    """Wrapped log lines re-joined into one normalized string."""
    return " ".join(" ".join(town.text_log.history).split())


def make_party(gold_by_member=(1000,)):
    members = [
        PartyMember(Character(f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
        for i in range(len(gold_by_member))
    ]
    party = Party(members, x=10, y=10, transport=Transport.FOOT)
    for member, gold in zip(party.members, gold_by_member):
        member.gold = gold
    return party


def make_food_vendor(price=20, quant=25):
    """FOOD vendor item from vendor.xml has no `choice` attribute:
    <item type="FOOD" price="20" quant="25" />"""
    return VendorDef(
        id="DAWN",
        name="The Sage Deli",
        owner="Shaman",
        vendor_type="FOOD",
        items=[VendorItemDef(choice="", item_type="FOOD", price=price, quantity=quant)],
    )


def make_tavern_vendor(ale_price=2):
    return VendorDef(
        id="FAWN",
        name="Sam's Canteen",
        owner="Sam",
        vendor_type="TAVERNINFO",
        generic_field1="Lamb Chops",
        items=[
            VendorItemDef(item_type="FOOD", name="Lamb Chops", price=1),
            VendorItemDef(item_type="FOOD", name="ale", price=ale_price),
            VendorItemDef(
                item_type="TAVERNINFO",
                price=20,
                description="%s says: Dawn is a city of myths and magic",
            ),
        ],
    )


def make_oracle_vendor():
    return VendorDef(
        id="BRITISH",
        name="",
        owner="Radrion",
        vendor_type="ORACLEINFO",
        items=[
            VendorItemDef(
                item_type="ORACLEINFO",
                price=100,
                description="%s says: You'll learn of marks and cards.",
            ),
            VendorItemDef(
                item_type="ORACLEINFO",
                price=200,
                description="%s says: Of marks there are but four.",
            ),
        ],
    )


def make_horse_vendor(price=100):
    """vendor.xml: <item type="HORSE" name="horse" choice="y" price="100" />"""
    return VendorDef(
        id="DAWN",
        name="the Stables",
        owner="Fitz",
        vendor_type="HORSE",
        items=[VendorItemDef(choice="y", item_type="HORSE", name="horse", price=price)],
    )


# --- Framework -----------------------------------------------------------


def test_dispatch_keyed_on_vendor_type_and_fallback():
    """Like Java VendorClassSet.getVendorImpl: keyed on InventoryType;
    not-yet-ported classes fall back (return None)."""
    assert create_vendor_dialog(make_food_vendor(), None, None) is not None
    assert create_vendor_dialog(make_tavern_vendor(), None, None) is not None
    assert create_vendor_dialog(make_oracle_vendor(), None, None) is not None
    assert create_vendor_dialog(make_horse_vendor(), None, None) is not None

    weapon = VendorDef(id="x", vendor_type="WEAPON")
    armor = VendorDef(id="x", vendor_type="ARMOR")
    guild = VendorDef(id="x", vendor_type="GUILD")
    healer = VendorDef(id="x", vendor_type="HEALER")
    for not_ported in (weapon, armor, guild, healer):
        assert create_vendor_dialog(not_ported, None, None) is None


# --- Food (FoodVendor.java) ----------------------------------------------


def test_food_item_purchasable_by_type_not_choice(asset_mgr):
    """CRITICAL audit bug: vendor.xml FOOD items carry no `choice`, so the
    generic choice-keyed menu always refused them ("We have no such ware.").
    Java FoodVendor.java:13-17 finds the item by InventoryType.FOOD."""
    vendor = asset_mgr.vendors.get("the sage deli")
    assert vendor is not None
    assert vendor.vendor_type == "FOOD"
    food_item = next(i for i in vendor.items if i.item_type.upper() == "FOOD")
    assert food_item.price == 25
    assert food_item.quantity == 25

    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=2, asset_mgr=asset_mgr, start_x=28, start_y=42)
    food_before = member.food

    town._start_vendor_shopping(vendor, buyer=member)
    assert town.text_log.is_waiting_for_input
    assert "May I interest you in some rations?" in logtext(town)

    town.text_log.submit_input("y")
    assert town.text_log.is_waiting_for_input
    # "We have the best adventure rations, 25 for only 25gp."
    assert "best adventure rations" in logtext(town)
    assert "How many packs of 25 would you like?" in logtext(town)

    town.text_log.submit_input("2")
    assert member.food == food_before + 2 * 25
    assert member.gold == 100 - 50
    assert "Thank you." in logtext(town)
    assert "Anything else?" in logtext(town)


def test_food_multipack_packs_of_25():
    vendor = make_food_vendor(price=20, quant=25)
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    before = member.food

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("3")

    assert member.food == before + 75
    assert member.gold == 100 - 60


def test_food_only_afford_n_packs():
    """FoodVendor.java:101-112 — count exceeding funds prints
    "You can only afford N packs." (gold // price) and sells nothing."""
    vendor = make_food_vendor(price=20, quant=25)
    party = make_party((50,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    before = member.food

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("3")

    # 50 // 20 == 2
    assert any("You can only afford 2 packs." in m for m in town.text_log.history)
    assert member.food == before
    assert member.gold == 50
    # then farewell
    assert any("Goodbye. Come again!" in m for m in town.text_log.history)
    assert not town.text_log.is_waiting_for_input


def test_food_loop_until_bye_then_decline():
    vendor = make_food_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    before = member.food

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("1")
    # "Anything else?" -> y loops back to the packs prompt
    town.text_log.submit_input("y")
    assert town.text_log.is_waiting_for_input
    assert "How many packs" in logtext(town)
    # decline: 0 packs sends the player off (FoodVendor.java:89 FAREWELL)
    town.text_log.submit_input("0")
    assert not town.text_log.is_waiting_for_input
    assert member.food == before + 25
    assert "Goodbye. Come again!" in logtext(town)


def test_food_unaffordable_single_pack_bids_farewell():
    """gold < price at the packs prompt: 'You can only afford 0 packs.'"""
    vendor = make_food_vendor(price=20, quant=25)
    party = make_party((10,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("1")
    assert "You can only afford 0 packs." in logtext(town)
    assert not town.text_log.is_waiting_for_input


# --- Tavern (TavernService.java) -----------------------------------------


def test_tavern_food_credits_member_consumed_food():
    """TavernService.java:51-58 — plates credit the buying member's food
    (one per plate) and debit the member's purse; Java 132-138 has no
    affordability check on tavern food (dead code) — purchases always go through."""
    vendor = make_tavern_vendor()
    party = make_party((2,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    before = member.food

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("f")
    town.text_log.submit_input("5")

    assert member.food == before + 5
    # 5 plates * 1gp = 5gp > 2gp gold: adjust_gold clamps at 0, no refusal
    assert member.gold == 0
    assert any("Here ye arr." in m for m in town.text_log.history)


def test_tavern_ale_exact_price_no_tip():
    vendor = make_tavern_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("a")
    town.text_log.submit_input("2")

    assert member.gold == 98
    assert any("Here ye arr." in m for m in town.text_log.history)


def test_tavern_ale_no_gold_string():
    """TavernService.java:199-210: paying more than the member's purse prints
    "It seems that you have not the gold. Good Day!" and buys nothing."""
    vendor = make_tavern_vendor()
    party = make_party((10,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("a")
    town.text_log.submit_input("20")

    assert member.gold == 10
    assert "It seems that you have not the gold. Good Day!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_tavern_rumor_delivery_and_member_purse():
    vendor = make_tavern_vendor()
    party = make_party((100, 900))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("a")
    town.text_log.submit_input("22")  # ale 2gp + 20gp tip -> the 20gp Dawn clue

    assert member.gold == 78
    assert party.members[1].gold == 900
    assert "Dawn is a city" in logtext(town)


def test_tavern_lowball_refusal():
    """TavernService.java:155-158 branch order: youPay < ale price takes the
    DECLINE_BUY scum line before the youPay == 1 silent-farewell edge can,
    then the farewell closes the visit."""
    vendor = make_tavern_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("a")
    town.text_log.submit_input("1")

    assert "Won't pay, eh. Ya scum, be gone fore ey call the guards!" in logtext(town)
    assert "See ya mate!" in logtext(town)
    assert not town.text_log.is_waiting_for_input
    assert member.gold == 100


# --- Oracle (OracleService.java) -----------------------------------------


def test_oracle_offering_zero_prints_rhyme():
    """OracleService.java:99-104 — offering 0 -> the sage rhyme, then
    "More offering?" keeps the conversation open."""
    vendor = make_oracle_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    assert "Prophet of Life!" in logtext(town)
    town.text_log.submit_input("0")

    assert (
        "And so the sage said unto thee, if thou can solve my rhyme.." in logtext(town)
    )
    assert "More offering?" in logtext(town)
    assert member.gold == 100
    # loop stays open until the player declines
    assert town.text_log.is_waiting_for_input


def test_oracle_purchase_charges_and_ends_conversation():
    """OracleService.java:40-48 — one purchase; nextDialog itself returns
    False after buying (Java line 48), so the dialog closes."""
    vendor = make_oracle_vendor()
    party = make_party((500,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("2")

    assert member.gold == 300
    assert "marks there are but four" in logtext(town)
    assert "More offering?" in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_oracle_insufficient_offering():
    vendor = make_oracle_vendor()
    party = make_party((50,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("1")

    assert member.gold == 50
    assert "It seems thou hast not gold enough to pay!" in logtext(town)
    assert "More offering?" in logtext(town)


# --- Horse (HorseService.java) -------------------------------------------


def test_horse_purchase_spawns_and_boards_creature():
    """HorseService.java:33-44 — 100gp (per vendor.xml), gold debited, an
    actual horse creature is spawned at the party's position and boarded
    via board(); the transport flag is set through boarding, not directly."""
    vendor = make_horse_vendor(price=100)
    party = make_party((300,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1, start_x=11, start_y=13)

    town._start_vendor_shopping(vendor, buyer=member)
    assert "Can I interest thee in horses?" in logtext(town)
    town.text_log.submit_input("y")
    assert "For only 200g.p thou can have the best. Wilt thou buy?" in logtext(town)
    town.text_log.submit_input("y")

    assert member.gold == 200
    assert party.transport == Transport.HORSE
    # the spawned mount was boarded: creature removed from the town, not parked
    assert not any(c.get("tile") == "horse" for c in town.creatures)
    assert "Here, a better breed thou shalt not find ever!" in logtext(town)
    assert "Mount Horse!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_horse_spawn_keeps_creature_when_boarding_refused():
    """No permanent flag: the horse is a real creature. With transport
    occupied, board() refuses ("Board: Can't!") and the creature stays."""
    vendor = make_horse_vendor(price=100)
    party = make_party((300,))
    party.transport = Transport.SHIP
    member = party.members[0]
    town = TownScreen(party=party, map_id=1, start_x=11, start_y=13)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("y")

    assert any("Board: Can't!" in m for m in town.text_log.history)
    assert party.transport == Transport.SHIP
    assert list(town.creatures) == [{"tile": "horse", "x": 11, "y": 13}]


def test_horse_cannot_afford():
    vendor = make_horse_vendor(price=100)
    party = make_party((50,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("y")

    assert member.gold == 50
    assert party.transport == Transport.FOOT
    assert "It seems thou hast not gold enough to pay!" in logtext(town)
    assert "Fare thee well!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_horse_decline_string():
    vendor = make_horse_vendor(price=100)
    party = make_party((300,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("n")

    assert "A shame, thou looks like thou could use a good horse!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


# --- Per-member purse -----------------------------------------------------


def test_buying_member_purse_is_charged_not_party_pool():
    """Task 4 model: vendors charge the BUYING member's gold (adjust_gold
    9999 cap). The other member's purse and the party's derived total
    reflect only the buyer's spending."""
    vendor = make_food_vendor(price=20, quant=25)
    party = make_party((60, 100))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    before = party.members[1].food

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("2")

    assert member.gold == 20
    assert party.members[1].gold == 100
    assert party.members[1].food == before
    assert party.gold == 120
    assert member.food == party.members[0].food