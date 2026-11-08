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
    unknown types (Java has no GUILD entry) still fall back (return None)."""
    assert create_vendor_dialog(make_food_vendor(), None, None) is not None
    assert create_vendor_dialog(make_tavern_vendor(), None, None) is not None
    assert create_vendor_dialog(make_oracle_vendor(), None, None) is not None
    assert create_vendor_dialog(make_horse_vendor(), None, None) is not None

    guild = VendorDef(id="x", vendor_type="GUILD")
    assert create_vendor_dialog(guild, None, None) is None


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

# ==========================================================================
# Task 8: Weapon/Armor sell flow + full catalogs, Guild, Healer
# ==========================================================================

from py_exodus.constants import Status, WeaponType, ArmorType
from py_exodus.entities.defs import VendorClassDef


def make_weapon_vendor():
    """Windsor Weaponry (Dawn) sells 14 weapons (choices b..o) per vendor.xml."""
    from py_exodus.assets import AssetManager

    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()
    return am.vendors.get("windsor weaponry")


def make_armor_vendor():
    from py_exodus.assets import AssetManager

    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()
    return am.vendors.get("dawn armour")


def make_guild_vendor():
    """vendor.xml GUILDITEM items: torches (5 for 30gp), gems, keys, powder."""
    return VendorDef(
        id="BRITISH",
        name="The Guild",
        owner="Freddy",
        vendor_type="GUILDITEM",
        items=[
            VendorItemDef(
                choice="a", item_type="GUILDITEM", name="Torches", price=30,
                quantity=5, guild_item_type="torch",
                description="I can give ya 5 long lasting Torches for a mere 30gp.",
            ),
            VendorItemDef(
                choice="b", item_type="GUILDITEM", name="Magic Gems", price=75,
                quantity=1, guild_item_type="gem",
                description="I've got magical mapping Gems, for only 75gp.",
            ),
            VendorItemDef(
                choice="c", item_type="GUILDITEM", name="Magic Keys", price=50,
                quantity=1, guild_item_type="key",
                description="Magical Keys, 1 use each, a fair price at 50gp.",
            ),
            VendorItemDef(
                choice="d", item_type="GUILDITEM", name="Powder", price=90,
                quantity=1, guild_item_type="powder",
                description="Negate time for opponents using a powder, for 90gp each.",
            ),
        ],
    )


def make_healer_vendor():
    """vendor.xml HEALER catalog: CURE 100, FULLHEAL 200, RESURRECT 500, RECALL 900."""
    return VendorDef(
        id="BRITISH",
        name="The Royal Healer",
        owner="Pendragon",
        vendor_type="HEALER",
        items=[
            VendorItemDef(choice="a", item_type="HEALER", name="Curing",
                          description="A curing", price=100, heal_type="CURE"),
            VendorItemDef(choice="b", item_type="HEALER", name="Healing",
                          description="A healing", price=200, heal_type="FULLHEAL"),
            VendorItemDef(choice="c", item_type="HEALER", name="Resurrection",
                          description="Resurrection from death", price=500, heal_type="RESURRECT"),
            VendorItemDef(choice="d", item_type="HEALER", name="Recalling",
                          description="Recall from ashes", price=900, heal_type="RECALL"),
        ],
    )


def test_dispatch_weapon_armor_guilditem_healer_now_ported():
    """Task 8: WEAPON, ARMOR, GUILDITEM and HEALER get per-class state
    machines (Java VendorClassSet.java:58-94 has all 8 InventoryTypes)."""
    assert create_vendor_dialog(make_weapon_vendor(), None, None) is not None
    assert create_vendor_dialog(make_armor_vendor(), None, None) is not None
    assert create_vendor_dialog(make_guild_vendor(), None, None) is not None
    assert create_vendor_dialog(make_healer_vendor(), None, None) is not None
    # Java InventoryType has no GUILD entry; unknown types still fall back.
    assert create_vendor_dialog(VendorDef(id="x", vendor_type="GUILD"), None, None) is None


# --- Weapon (WeaponVendor.java) -------------------------------------------


def test_weapon_welcome_and_full_catalog_no_truncation():
    """WeaponVendor.java:34-45: welcome + every stock item listed; Windsor
    Weaponry has 14 items (b..o) — the old items[:6] truncation is gone."""
    vendor = make_weapon_vendor()
    assert len(vendor.items) == 14
    party = make_party((10000,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    log = logtext(town)
    assert "Art thou here to Buy or Sell?" in log
    town.text_log.submit_input("b")
    log = logtext(town)
    assert "Very Good! We Have:" in log
    assert "B - Dagger for 5gp." in log
    assert "O - Sword +4 for 4550gp." in log  # 14th item, was truncated before
    assert "Your Interest?" in log


def test_weapon_buy_multiple_via_member_purse():
    """WeaponVendor.java:62-68: count purchase credits member's weapon list
    and debits the member's purse; loop with "anything else?\"."""
    vendor = make_weapon_vendor()
    party = make_party((1000,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")  # Dagger, 5gp
    assert "How many would I like? 5" not in logtext(town)
    assert "a bargain at only 5gp" in logtext(town)  # description %d filled
    assert "How many would you like?" in logtext(town)
    town.text_log.submit_input("3")

    assert member.weapons[WeaponType.DAGGER] == 3
    assert member.gold == 1000 - 15
    assert "Winston says: A fine choice! anything else?" in logtext(town)


def test_weapon_buy_one_take_it_prompt():
    """gold <= 2*price splits to WAIT_BUY_ONE: "Take it?" (WeaponVendor also
    prints the price description first, WeaponVendor.java:52-55)."""
    vendor = make_weapon_vendor()
    party = make_party((8,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    assert "a bargain at only 5gp" in logtext(town)
    assert "Take it?" in logtext(town)
    town.text_log.submit_input("y")
    assert member.weapons[WeaponType.DAGGER] == 1
    assert member.gold == 3


def test_weapon_cannot_pay_single():
    """BaseVendor.checkCanPay: gold < price -> description + "You have not
    the funds for even one!" and back to the buy/sell question."""
    vendor = make_weapon_vendor()
    party = make_party((4,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    assert "You have not the funds for even one!" in logtext(town)
    assert member.gold == 4
    assert member.weapons[WeaponType.DAGGER] == 0
    # back at the welcome/buy-or-sell prompt
    assert town.text_log.is_waiting_for_input


def test_weapon_sell_half_price_and_purse_credit():
    """WeaponVendor.java: WAIT_SELL_INPUT lists the FULL class catalog with
    owned counts and half price; sell credits member.gold directly
    (gold = gold + price/2 * count, no adjustGold clamp)."""
    vendor = make_weapon_vendor()
    party = make_party((50,))
    member = party.members[0]
    member.weapons[WeaponType.SWORD_P2] = 2
    member.weapons[WeaponType.BOW_P4] = 1
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    log = logtext(town)
    assert "Excellent!" in log
    # full class catalog filtered to owned items only
    assert "K - Sword +2 for 400gp. (2)" in log
    assert "N - Bow +4 for 3275gp. (1)" in log
    assert "Which wouldst you sell?" in log

    town.text_log.submit_input("k")
    assert "I will give you 400gp each." in logtext(town)
    assert "How many would thee like to sell?" in logtext(town)
    town.text_log.submit_input("2")

    assert member.weapons[WeaponType.SWORD_P2] == 0
    assert member.weapons[WeaponType.BOW_P4] == 1
    assert member.gold == 50 + 800
    assert "Fine! Anything else?" in logtext(town)


def test_weapon_sell_single_deal_string():
    """Count == 1 skips the how-many prompt: "I will give you %dgp for that
    %s. Deal?" (WeaponVendor.java WAIT_SELL_ONE)."""
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    member.weapons[WeaponType.DAGGER] = 1
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("b")
    assert "I will give you 2gp for that Dagger. Deal?" in logtext(town)
    assert "I will give you 2gp each." not in logtext(town)
    town.text_log.submit_input("y")
    assert member.weapons[WeaponType.DAGGER] == 0
    assert member.gold == 2


def test_weapon_sell_too_many_swine():
    """WAIT_SELL_DONT_HAVE_THAT_MANY: selling more than owned (or a choice
    not on the catalog) prints the swine line and returns to buy-or-sell."""
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    member.weapons[WeaponType.DAGGER] = 2
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("b")  # 2 owned -> the how-many prompt
    town.text_log.submit_input("5")
    assert "You don't have that many swine! Anything else?" in logtext(town)
    assert member.weapons[WeaponType.DAGGER] == 2
    assert "Art thou here to Buy or Sell?" in logtext(town)  # re-welcomed


def test_weapon_sell_unknown_choice_swine():
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("z")
    assert "You don't have that many swine!" in logtext(town)


def test_weapon_multi_count_cannot_pay():
    """checkCanPay(item, count) failure: "I fear you have not the funds,
    perhaps something else." — nothing bought."""
    vendor = make_weapon_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    # Dagger at 5gp with gold 100: gold > 2*price -> the how-many path.
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    town.text_log.submit_input("21")  # 21 * 5 = 105gp > 100
    assert "I fear you have not the funds, perhaps something else." in logtext(town)
    assert member.weapons[WeaponType.DAGGER] == 0
    assert member.gold == 100


# --- Armor (ArmorVendor.java) ---------------------------------------------


def test_armor_buy_one_no_description_line():
    """ArmorVendor.java:57 WAIT_BUY_ONE prints ONLY "Take it?" — no item
    description (unlike WeaponVendor.java:52-55 which prints both)."""
    vendor = make_armor_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")  # Cloth, 75gp, 100 <= 2*75
    assert "Take it?" in logtext(town)
    assert "Fairly priced at" not in logtext(town)
    town.text_log.submit_input("y")
    assert member.armors[ArmorType.CLOTH] == 1
    assert member.gold == 25


def test_armor_sell_flow():
    """ArmorVendor.java sell flow: half price (75//2 == 37), gold credited
    with the direct write (no adjustGold), catalog filtered to owned."""
    vendor = make_armor_vendor()
    party = make_party((0,))
    member = party.members[0]
    member.armors[ArmorType.LEATHER] = 3
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    # only owned armor appears (5th+ items unowned -> skipped)
    assert "C - Leather for 97gp. (3)" in logtext(town)
    assert "D - Chain Mail" not in logtext(town)
    town.text_log.submit_input("c")
    assert "I will give you 97gp each." in logtext(town)
    town.text_log.submit_input("2")
    assert member.armors[ArmorType.LEATHER] == 1
    assert member.gold == 194
    assert "Fine! Anything else?" in logtext(town)


# --- Guild (GuildVendor.java) ----------------------------------------------


def test_guild_buy_torch_credits_member_not_party_pool():
    """GuildVendor.java BUY_ITEM: quantity credited to the member's own
    gems/keys/torches/powder fields, purse debited via adjustGold."""
    vendor = make_guild_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    log = logtext(town)
    assert "Avast ye mate!" in log
    assert "Shure ye wishes to buy from ol' Freddy?" in log
    assert "Welcome to The Guild.\nLike to see my goods?" in log or \
        ("Welcome to The Guild." in log and "Like to see my goods?" in log)

    town.text_log.submit_input("y")
    assert "Freddy says: Good Mate! Ya see I gots:" in logtext(town)
    assert "A - Torches (5) for 30gp" in logtext(town)
    assert "Wat'l it be?" in logtext(town)

    town.text_log.submit_input("a")
    assert "Will ya buy?" in logtext(town)
    town.text_log.submit_input("y")

    assert member.torches == 5
    assert member.gold == 70
    assert party.torches == 5  # derived from the member — no separate pool
    assert "Freddy says: See more?" in logtext(town)
    assert town.text_log.is_waiting_for_input

    town.text_log.submit_input("n")
    assert "See ya matie!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_guild_gems_keys_powder_credit_member():
    vendor = make_guild_vendor()
    party = make_party((1000,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("c")
    town.text_log.submit_input("y")
    assert member.keys == 1
    assert member.gold == 950


def test_guild_cant_pay_buzz_off():
    """GuildVendor.checkCanPay override: price > gold -> "What? Can't pay!
    Buzz off swine!" and the visit ends (setResponse -> FAREWELL)."""
    vendor = make_guild_vendor()
    party = make_party((20,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("a")
    assert "What? Can't pay! Buzz off swine!" in logtext(town)
    assert "See ya matie!" in logtext(town)
    assert not town.text_log.is_waiting_for_input
    assert member.torches == 0
    assert member.gold == 20


def test_guild_unknown_item_farewell():
    vendor = make_guild_vendor()
    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("z")
    # Java short-circuits (item != null && checkCanPay): no "cannot help"
    # line on an unknown choice — straight to the farewell.
    assert "I cannot help thee with that." not in logtext(town)
    assert "See ya matie!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


# --- Healer (HealerService.java + Party.java pm.heal) ----------------------


def test_pm_heal_unit_semantics():
    """Direct port of Party.java:381-433 pm.heal: need-checks return False;
    RESURRECT (like RECALL) sets hp to 1 — not full; no wisdom adjustment
    exists in Party.java:416-422 RECALL (nothing to port)."""
    m = PartyMember(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
    max_hp = m.max_hp

    assert m.heal("NONE") is True
    # CURE only when POISONED
    m.status = Status.POISONED
    assert m.heal("CURE") is True and m.status == Status.GOOD
    assert m.heal("CURE") is False
    # FULLHEAL rejected when DEAD or already full
    assert m.heal("FULLHEAL") is False
    m.hp = 40
    assert m.heal("FULLHEAL") is True and m.hp == max_hp
    m.status = Status.DEAD
    m.hp = 0
    assert m.heal("FULLHEAL") is False
    # RESURRECT only when DEAD; hp 1 (not full), GOOD
    assert m.heal("RESURRECT") is True and m.hp == 1 and m.status == Status.GOOD
    assert m.heal("RESURRECT") is False  # no longer DEAD
    # RECALL only when ASH; hp 1, GOOD
    m.status = Status.ASH
    m.hp = 0
    assert m.heal("RECALL") is True and m.hp == 1 and m.status == Status.GOOD
    m.status = Status.GOOD
    assert m.heal("RECALL") is False
    # HEAL rejected when DEAD/full; mangles with 75 + rand%25
    m.hp = 10
    healed = m.heal("HEAL")
    assert healed and 85 <= m.hp <= 85 + 24 or m.hp == m.max_hp
    # unknown type -> False
    assert m.heal("WHIMSY") is False


def test_healer_welcome_and_service_catalog():
    vendor = make_healer_vendor()
    party = make_party((10000, 10000))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    log = logtext(town)
    assert "Welcome unto The Royal Healer" in log
    assert "Pendragon says: Peace and Joy be with you friend." in log
    assert "Are you in need of help?" in log
    town.text_log.submit_input("y")
    log = logtext(town)
    assert "We can perform:" in log
    assert "A - Curing for 100gp." in log
    assert "D - Recalling for 900gp." in log
    assert "Your Need?" in log


def test_healer_cure_poisoned_member():
    vendor = make_healer_vendor()
    party = make_party((300, 500))
    member = party.members[0]
    member.status = Status.POISONED
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("a")
    assert "Who is in need?" in logtext(town)
    town.text_log.submit_input("1")
    assert "A curing will cost thee 100 gp." in logtext(town)
    assert "Wilt thou pay?" in logtext(town)
    town.text_log.submit_input("y")

    assert member.status == Status.GOOD
    assert member.gold == 200
    assert "There you are. Please be more careful next time." in logtext(town)
    assert "Anything else?" in logtext(town)


def test_healer_service_on_second_member():
    vendor = make_healer_vendor()
    party = make_party((300, 500))
    second = party.members[1]
    second.status = Status.POISONED
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=party.members[0])
    town.text_log.submit_input("y")
    town.text_log.submit_input("a")
    town.text_log.submit_input("2")
    town.text_log.submit_input("y")
    assert second.status == Status.GOOD
    # the BUYING member (HealerService member field) is charged
    assert party.members[0].gold == 200
    assert party.members[1].gold == 500


def test_healer_resurrect_sets_hp_one_not_full():
    """Party.java RESURRECT: hp = 1 (NOT max) and GOOD; charged 500."""
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    member.status = Status.DEAD
    member.hp = 0
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("c")
    town.text_log.submit_input("1")
    town.text_log.submit_input("y")

    assert member.status == Status.GOOD
    assert member.hp == 1
    assert member.hp != member.max_hp
    assert member.gold == 500


def test_healer_recall_only_when_ash():
    vendor = make_healer_vendor()
    party = make_party((1000, 1000))
    member = party.members[0]
    member.status = Status.ASH
    member.hp = 0
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("d")
    town.text_log.submit_input("1")
    town.text_log.submit_input("y")
    assert member.status == Status.GOOD
    assert member.hp == 1
    assert member.gold == 100
    # no wisdom loss — Java RECALL (Party.java:416-422) has no wis adjustment
    assert member.wisdom == 10


def test_healer_no_charge_when_not_in_need():
    """HealerService.java:58-64: pm.heal returning False charges NOTHING
    ("pm, thou art not in need of such service.")."""
    vendor = make_healer_vendor()
    party = make_party((1000,))

    # HEALTHY member picking CURE (only works when POISONED)
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("a")
    town.text_log.submit_input("1")
    town.text_log.submit_input("y")
    assert "Hero0, thou art not in need of such service." in logtext(town)
    assert member.gold == 1000
    assert member.status == Status.GOOD
    town.text_log.submit_input("n")

    # FULL-HP member picking FULLHEAL
    town2 = TownScreen(party=party, map_id=1)
    town2._start_vendor_shopping(vendor, buyer=member)
    town2.text_log.submit_input("y")
    town2.text_log.submit_input("b")
    town2.text_log.submit_input("1")
    town2.text_log.submit_input("y")
    assert "Hero0, thou art not in need of such service." in logtext(town2)
    assert member.gold == 1000
    assert "Anything else?" in logtext(town2)


def test_healer_fullheal_and_recall_rejected_on_wrong_status():
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    # RECALL rejected for a GOOD (not ASH) member
    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("d")
    town.text_log.submit_input("1")
    town.text_log.submit_input("y")
    assert "not in need of such service." in logtext(town)
    assert member.gold == 1000


def test_healer_resurrect_rejected_when_not_dead():
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("c")
    town.text_log.submit_input("1")
    town.text_log.submit_input("y")
    assert "not in need of such service." in logtext(town)
    assert member.gold == 1000
    assert member.status == Status.GOOD


def test_healer_insufficient_funds_string():
    """HealerService.checkCanPay override: "I see by thy purse that thou
    hast not enough gold. I cannot aid thee." then back to the need prompt."""
    vendor = make_healer_vendor()
    party = make_party((50,))
    member = party.members[0]
    member.status = Status.POISONED
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("b")  # Healing, 200gp > 50
    assert "I see by thy purse that thou hast not enough gold." \
        " I cannot aid thee." in logtext(town)
    assert member.status == Status.POISONED
    assert member.gold == 50
    # back at "Are you in need of help?" — the visit loop stays open
    assert town.text_log.is_waiting_for_input
    assert "Are you in need of help?" in logtext(town)


def test_healer_blood_donation():
    """HealerService.java: declined help with health >= 400 offers the
    100pt blood donation; "Thou art a great help. We are in dire need!"."""
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    member.hp = 500
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("n")
    assert "Art thou willing to give 100 pts of thy blood to aid others?" \
        in logtext(town)
    town.text_log.submit_input("y")
    assert member.hp == 400
    assert "Thou art a great help. We are in dire need!" in logtext(town)
    town.text_log.submit_input("n")
    assert "Pendragon says: May thy life be guarded by the powers of good." \
        in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_healer_low_health_decline_loops_back():
    """health < 400 and declining help returns to the need prompt (no blood
    offer), HealerService.java:74-80."""
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    member.hp = 100
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("n")
    assert "Art thou willing to give 100 pts of thy blood" not in logtext(town)
    assert town.text_log.is_waiting_for_input
    assert "Are you in need of help?" in logtext(town)


def test_healer_no_blood_offer_after_donating_low():
    """After GIVE_BLOOD, "y" re-loops the need prompt; health 399 declines."""
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    member.hp = 400
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("n")
    town.text_log.submit_input("y")   # donate -> hp 300
    town.text_log.submit_input("y")   # loop back to the need prompt
    assert member.hp == 300
    town.text_log.submit_input("n")
    # health below 400 -> the need prompt re-displays, visit stays open
    assert town.text_log.is_waiting_for_input
    assert "Are you in need of help?" in logtext(town)


# --- Generic menu catalog truncation removed -------------------------------


def test_generic_menu_lists_full_catalog():
    """Task 8: town.py's generic fallback menu must not truncate the catalog
    to 6 (the [:6] slice is removed)."""
    pm = PartyMember(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
    party = Party([pm], x=10, y=10)
    town = TownScreen(party=party, map_id=1)
    items = [VendorItemDef(choice=chr(ord("a") + i), item_type="WEAPON", name=f"W{i}", price=1 + i)
             for i in range(9)]
    vendor = VendorDef(id="X", name="Odd Shop", owner="Zed", vendor_type="MYSTERY", items=items)
    town._start_vendor_shopping(vendor, buyer=pm)
    log = logtext(town)
    assert "a) W0 - 1gp" in log
    assert "h) W7 - 8gp" in log
    assert "i) W8 - 9gp" in log
