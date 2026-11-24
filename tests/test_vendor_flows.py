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
    """What the player sees: wrapped log lines plus the open prompt row,
    re-joined into one normalized string. (A shop's question is asked once,
    as the prompt, so it reaches the history only when answered.)"""
    lines = list(town.text_log.history)
    if town.text_log.is_waiting_for_input:
        lines.append(town.text_log.current_prompt)
    return " ".join(" ".join(lines).split())


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
    # LairWare Shop case 1: a ration is 1 gold (was 25 for 25gp).
    assert food_item.price == 1
    assert food_item.quantity == 1

    party = make_party((100,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=2, asset_mgr=asset_mgr, start_x=28, start_y=42)
    food_before = member.food

    town._start_vendor_shopping(vendor, buyer=member)
    assert town.text_log.is_waiting_for_input
    assert "May I interest you in some rations?" in logtext(town)

    town.text_log.submit_input("y")
    assert town.text_log.is_waiting_for_input
    # "We have the best adventure rations, 1gp each."
    assert "best adventure rations" in logtext(town)
    assert "How many rations would you like?" in logtext(town)

    town.text_log.submit_input("50")
    assert member.food == food_before + 50
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
    assert any("You can only afford 2 rations." in m for m in town.text_log.history)
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
    assert "How many rations" in logtext(town)
    # decline: 0 packs sends the player off (FoodVendor.java:89 FAREWELL)
    town.text_log.submit_input("0")
    assert not town.text_log.is_waiting_for_input
    assert member.food == before + 25
    assert "Goodbye. Come again!" in logtext(town)


def test_food_unaffordable_single_pack_bids_farewell():
    """gold < price at the count prompt: 'You can only afford 0 rations.'"""
    vendor = make_food_vendor(price=20, quant=25)
    party = make_party((10,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("1")
    assert "You can only afford 0 rations." in logtext(town)
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
    """WeaponVendor.java:24-31: welcome + every stock item listed; Windsor
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
    """WeaponVendor.java:41-46: count purchase credits member's weapon list
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
    assert "Winston says: A fine choice!" in logtext(town)
    assert town.text_log.current_prompt == "Anything else? (y or n)"


def test_weapon_buy_one_take_it_prompt():
    """gold <= 2*price splits to WAIT_BUY_ONE: "Take it?" (WeaponVendor also
    prints the price description first, WeaponVendor.java:36-39)."""
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


def test_weapon_sell_full_price_and_purse_credit():
    """LairWare (UltimaMisc.c shop case 3): the sell branch pays the same
    WeaponsArmour price the buy branch charges. WAIT_SELL_INPUT lists the
    shop's stock filtered to what the member owns (Java: half price)."""
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
    assert "K - Sword +2 for 800gp. (2)" in log
    assert "N - Bow +4 for 6550gp. (1)" in log
    assert "Which wouldst you sell?" in log

    town.text_log.submit_input("k")
    assert "I will give you 800gp each." in logtext(town)
    assert "How many would thee like to sell?" in logtext(town)
    town.text_log.submit_input("2")

    assert member.weapons[WeaponType.SWORD_P2] == 0
    assert member.weapons[WeaponType.BOW_P4] == 1
    assert member.gold == 50 + 1600
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
    assert "I will give you 5gp for that Dagger. Deal?" in logtext(town)
    assert "I will give you 5gp each." not in logtext(town)
    town.text_log.submit_input("y")
    assert member.weapons[WeaponType.DAGGER] == 0
    assert member.gold == 5


def test_weapon_sell_too_many_swine():
    """WAIT_SELL_DONT_HAVE_THAT_MANY: selling more than owned prints the
    swine line and ends the visit, as LairWare ends it on a failed sale
    (Java said "Anything else?" but sat at Buy or Sell)."""
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    member.weapons[WeaponType.DAGGER] = 2
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("b")  # 2 owned -> the how-many prompt
    town.text_log.submit_input("5")
    assert "You don't have that many swine!" in logtext(town)
    assert "Anything else?" not in logtext(town)
    assert member.weapons[WeaponType.DAGGER] == 2
    assert not town.text_log.is_waiting_for_input  # visit over


# --- Buy-or-Sell key semantics (playtest-1 fix batch, item 2) --------------
#
# Java truth: WeaponVendor.setResponse ASK_BUY_SELL (WeaponVendor.java:98-105)
# maps b/s to the buy/sell menus and leaves ANY other input (including
# non-alphabetical junk) in ASK_BUY_SELL; nextDialog then re-prints the full
# welcome message (WeaponVendor.java:21-23) — so Java's "unrecognized key"
# handling at the buy-or-sell choice IS a re-welcome + re-ask, no error line
# anywhere. The port keeps the "(b or s)" prompt affordance (Java is a
# free-text modal field with no prompt strings) and re-asks the same way.
# Empty ENTER hides the ConversationDialog and ends the visit WITHOUT
# consulting the vendor (exodus/ConversationDialog.java:73-80 hides on
# length()==0; the vendor setResponse still runs but the dialog is already
# dismissed) — the port's empty-ENTER exit is Java-faithful, pinned as
# documented truth.
#
# The shared "Reply (y or n)" prompt text is a PORT affordance bug: Java's
# y/n questions at the three states are distinct ("Take it?" WAIT_BUY_ONE,
# "anything else?" BUY_ITEM, "Deal?" WAIT_SELL_ONE), and the playability
# ruling makes the port prompt mirror the DISTINCT question text.


def test_weapon_invalid_key_rewelcomes_and_reprompts():
    """Non-B/S key at the buy-or-sell choice: Java keeps ASK_BUY_SELL and
    nextDialog re-prints the whole welcome (WeaponVendor.java:98-105 +
    21-23). Driver: pressing x re-welcomes and re-prompts, never exits."""
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    assert logtext(town).count("Art thou here to Buy or Sell?") == 1

    town.text_log.handle_char("x")  # single-char prompt: flushes immediately

    assert town.text_log.is_waiting_for_input, "dialog must stay open"
    assert town.text_log.current_prompt == "Art thou here to Buy or Sell? (b or s)"
    assert logtext(town).count("Art thou here to Buy or Sell?") == 2, (
        "Java re-prints the welcome message on an unrecognized answer"
    )
    assert member.gold == 0  # nothing happened


def test_weapon_empty_enter_ends_visit_javanote():
    """Empty ENTER hides the ConversationDialog on the spot
    (ConversationDialog.java:74-80) — the port's silent exit is Java-truth,
    pinned here so the playtest finding is answered with the citation."""
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    assert town.text_log.is_waiting_for_input

    town.text_log.submit_input("")  # bare ENTER

    assert not town.text_log.is_waiting_for_input


def test_weapon_distinct_yn_prompts_per_state():
    """The three y/n questions have DISTINCT Java texts ("Take it?",
    "anything else?", "Deal?") — the port prompt must mirror them, not serve
    one shared "Reply (y or n)" string."""
    from py_exodus.constants import WeaponType

    party = make_party((8,))  # gold <= 2*5 forces the WAIT_BUY_ONE branch
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    # WAIT_BUY_ONE: "Take it?"
    town._start_vendor_shopping(make_weapon_vendor(), buyer=member)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")  # Dagger 5gp -> 8 <= 10 -> Take it?
    assert town.text_log.current_prompt == "Take it? (y or n)"
    town.text_log.submit_input("y")  # BUY_ITEM: "A fine choice! anything else?"
    assert town.text_log.current_prompt == "Anything else? (y or n)"

    town.text_log.submit_input("y")  # non-y would FAREWELL (Java BUY_ITEM:63-66)
    assert town.text_log.current_prompt == "Art thou here to Buy or Sell? (b or s)"
    town.text_log.submit_input("s")  # -> WAIT_SELL_INPUT
    assert town.text_log.current_prompt == "Which wouldst you sell?"
    town.text_log.submit_input("b")  # one dagger owned -> WAIT_SELL_ONE
    assert town.text_log.current_prompt == "Deal? (y or n)"
    town.text_log.submit_input("y")  # sell -> SELL_ITEM "Fine! Anything else?"
    assert town.text_log.current_prompt == "Anything else? (y or n)"
    town.text_log.submit_input("y")  # -> WAIT_SELL_INPUT again
    assert town.text_log.is_waiting_for_input


def test_weapon_wait_sell_one_deal_prompt():
    """WAIT_SELL_ONE (count == 1) asks "Deal?" — its own prompt."""
    from py_exodus.constants import WeaponType

    party = make_party((0,))
    member = party.members[0]
    member.weapons[WeaponType.DAGGER] = 1
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(make_weapon_vendor(), buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("b")  # one dagger -> WAIT_SELL_ONE
    assert "Deal?" in logtext(town)
    assert town.text_log.current_prompt == "Deal? (y or n)"
    town.text_log.submit_input("y")


def test_weapon_sell_unknown_choice_swine():
    vendor = make_weapon_vendor()
    party = make_party((0,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("z")
    assert "You don't own one of those!" in logtext(town)
    assert not town.text_log.is_waiting_for_input


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
    """ArmorVendor.java:35-37 WAIT_BUY_ONE prints ONLY "Take it?" — no item
    description (unlike WeaponVendor.java:36-39 which prints both)."""
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
    """Armour sell flow at LairWare's full price (Leather 195), the shop's
    stock filtered to what the member owns."""
    vendor = make_armor_vendor()
    party = make_party((0,))
    member = party.members[0]
    member.armors[ArmorType.LEATHER] = 3
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("s")
    # only owned armor appears (5th+ items unowned -> skipped)
    assert "C - Leather for 195gp. (3)" in logtext(town)
    assert "D - Chain Mail" not in logtext(town)
    town.text_log.submit_input("c")
    assert "I will give you 195gp each." in logtext(town)
    town.text_log.submit_input("2")
    assert member.armors[ArmorType.LEATHER] == 1
    assert member.gold == 390
    assert "Fine! Anything else?" in logtext(town)


def _grey_weaponry():
    from py_exodus.assets import AssetManager

    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()
    return am.vendors.get("kruppe's weaponry")


def test_sell_only_what_this_shop_stocks():
    """LairWare: the sell letter must be below the shop's opnum, so an
    ordinary weapon shop (Dagger..2-H-Sword) won't buy a +2 Axe; Dawn will."""
    party = make_party((0,))
    member = party.members[0]
    member.weapons[WeaponType.AXE_P2] = 1
    member.weapons[WeaponType.SWORD] = 1
    town = TownScreen(party=party, map_id=1)
    grey = _grey_weaponry()
    assert len(grey.items) == 7
    town._start_vendor_shopping(grey, buyer=member)
    town.text_log.submit_input("s")
    assert "Sword for 200gp. (1)" in logtext(town)
    assert "Axe +2" not in logtext(town)
    town.text_log.submit_input("i")  # the +2 Axe's letter at Dawn
    assert "You don't own one of those!" in logtext(town)
    assert member.weapons[WeaponType.AXE_P2] == 1 and member.gold == 0


def test_sell_nothing_owned_is_refused():
    """LairWare 212 "You don't own one of those!": an unowned item is not
    sold (Java went on to "Deal?" and paid for nothing)."""
    party = make_party((0,))
    member = party.members[0]
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(make_weapon_vendor(), buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("g")  # Sword, none owned
    assert "You don't own one of those!" in logtext(town)
    assert not town.text_log.is_waiting_for_input  # LW `return`: visit over
    assert member.gold == 0 and member.weapons[WeaponType.SWORD] == 0


def test_sell_past_9999_gold_is_cancelled():
    """LairWare AddGold(..., FALSE): a sale that would take the purse past
    9999 is cancelled and the item kept."""
    party = make_party((9800,))
    member = party.members[0]
    member.armors[ArmorType.PLATE] = 1
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(make_armor_vendor(), buyer=member)
    town.text_log.submit_input("s")
    town.text_log.submit_input("e")  # Plate, 2500
    town.text_log.submit_input("y")
    assert "More gold than thou can carry! Sale cancelled." in logtext(town)
    assert member.armors[ArmorType.PLATE] == 1 and member.gold == 9800
    assert not town.text_log.is_waiting_for_input  # LW `return`: visit over


def test_sell_the_readied_weapon_leaves_hands():
    """LairWare counts the readied weapon as owned; selling the last one
    leaves the member on hands (Player[48] = 0)."""
    party = make_party((0,))
    member = party.members[0]
    member.weapon = WeaponType.SWORD
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(make_weapon_vendor(), buyer=member)
    town.text_log.submit_input("s")
    assert "Sword for 200gp. (1)" in logtext(town)
    town.text_log.submit_input("g")
    town.text_log.submit_input("y")
    assert member.weapon == WeaponType.NONE
    assert member.gold == 200


def test_sell_spares_before_the_readied_one():
    """Selling fewer than owned takes the spares and keeps the readied."""
    party = make_party((0,))
    member = party.members[0]
    member.armor = ArmorType.CHAIN
    member.armors[ArmorType.CHAIN] = 1
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(make_armor_vendor(), buyer=member)
    town.text_log.submit_input("s")
    assert "Chain" in logtext(town) and "(2)" in logtext(town)
    town.text_log.submit_input("d")
    town.text_log.submit_input("1")
    assert member.armor == ArmorType.CHAIN
    assert member.armors[ArmorType.CHAIN] == 0
    assert member.gold == 575


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
    """Party.java:381-433 pm.heal with LairWare's Clerical effects
    (UltimaMisc.c:1747-1784): need-checks return False; FULLHEAL heals the
    dead too; RESURRECT and RECALL change only the status; no wisdom
    adjustment."""
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
    assert m.heal("FULLHEAL") is True and m.hp == max_hp and m.status == Status.DEAD
    m.hp = 0
    # RESURRECT only when DEAD; HP left as it is, GOOD
    assert m.heal("RESURRECT") is True and m.hp == 0 and m.status == Status.GOOD
    assert m.heal("RESURRECT") is False  # no longer DEAD
    # RECALL only when ASH; HP left as it is, GOOD
    m.status = Status.ASH
    m.hp = 0
    assert m.heal("RECALL") is True and m.hp == 0 and m.status == Status.GOOD
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


def test_healer_resurrect_leaves_hp():
    """LairWare UltimaMisc.c:1766-1767 RESURRECT: DEAD -> GOOD, HP left as
    it is (0 here; Java set 1); charged 500."""
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
    assert member.hp == 0
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
    assert member.hp == 0  # LairWare UltimaMisc.c:1783-1784: HP untouched
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


def test_healer_low_health_decline_exits_farewell():
    """Playability fix (item 44): Java HealerService.java:91-97 sets
    WAIT_NEED_HELP when health < 400 and the player says no, trapping the
    player in an infinite loop; PyExodus exits cleanly via FAREWELL."""
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    member.hp = 100
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("n")
    assert "Art thou willing to give 100 pts of thy blood" not in logtext(town)
    assert "Pendragon says: May thy life be guarded by the powers of good." \
        in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_healer_no_blood_offer_after_donating_low():
    """After GIVE_BLOOD, "y" re-loops the need prompt; declining at hp < 400
    exits via FAREWELL instead of offering blood again or looping forever."""
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
    assert logtext(town).count("Art thou willing to give 100 pts of thy blood") == 1
    assert "Pendragon says: May thy life be guarded by the powers of good." \
        in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_healer_decline_blood_offer_exits_farewell():
    """Declining 'Give blood?' at hp >= 400 exits cleanly via FAREWELL."""
    vendor = make_healer_vendor()
    party = make_party((1000,))
    member = party.members[0]
    member.hp = 500
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("n")
    assert "Art thou willing to give 100 pts of thy blood to aid others?" \
        in logtext(town)
    town.text_log.submit_input("n")
    assert member.hp == 500
    assert "Pendragon says: May thy life be guarded by the powers of good." \
        in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_healer_anything_else_prompt_and_low_hp_exit():
    """ANYTHING_ELSE uses 'Anything else? (y or n)' (single_char=True), and
    answering 'n' when hp < 400 exits cleanly via FAREWELL."""
    vendor = make_healer_vendor()
    party = make_party((300,))
    member = party.members[0]
    member.hp = 100
    member.status = Status.POISONED
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=member)
    town.text_log.submit_input("y")
    town.text_log.submit_input("a")
    town.text_log.submit_input("1")
    town.text_log.submit_input("y")

    assert town.text_log.is_waiting_for_input
    assert town.text_log.current_prompt == "Anything else? (y or n)"
    assert town.text_log.single_char is True

    town.text_log.handle_char("n")
    assert "Pendragon says: May thy life be guarded by the powers of good." \
        in logtext(town)
    assert not town.text_log.is_waiting_for_input


def test_healer_who_service_single_char_member_prompt(pygame_setup):
    """WAIT_WHO_SERVICE ('Who is in need? (member number)') commits on a single
    digit key without pressing ENTER."""
    import pygame

    vendor = make_healer_vendor()
    party = make_party((300, 500))
    party.members[0].status = Status.POISONED
    town = TownScreen(party=party, map_id=1)

    town._start_vendor_shopping(vendor, buyer=party.members[0])
    town.text_log.handle_char("y")
    town.text_log.handle_char("a")
    assert town.text_log.current_prompt == "Who is in need? (member number)"
    assert town.text_log.single_char is True

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
    assert "A curing will cost thee 100 gp." in logtext(town)
    assert "Wilt thou pay?" in logtext(town)
    assert town.text_log.current_prompt == "Wilt thou pay? (y or n)"


def test_healer_check_can_pay_none_keeps_state():
    """HealerVendorDialog.check_can_pay(None) must leave dialog.state untouched
    instead of assigning ConvState.ASK_BUY_SELL."""
    from py_exodus.screens.vendor_dialog import ConvState, HealerVendorDialog

    vendor = make_healer_vendor()
    party = make_party((300,))
    town = TownScreen(party=party, map_id=1)
    dialog = HealerVendorDialog(vendor, party.members[0], town.text_log)
    dialog.state = ConvState.WAIT_WHICH_SERVICE

    assert dialog.check_can_pay(None) is False
    assert dialog.state == ConvState.WAIT_WHICH_SERVICE
    assert "I cannot help thee with that." in logtext(town)


def test_ported_vendor_escape_clears_prompt_and_restores_music(pygame_setup):
    """Pressing ESC at an active ported vendor prompt clears text_log prompt
    and invokes on_end to restore town music."""
    import pygame

    played_music: list[str] = []

    class _StubAudio:
        def play_music(self, name: str, **kwargs) -> None:
            played_music.append(name)

        def play_sfx(self, name: str, **kwargs) -> None:
            pass

    party = make_party((500,))
    town = TownScreen(party=party, map_id=3, audio=_StubAudio())
    town._start_vendor_shopping(make_weapon_vendor(), buyer=party.members[0])
    assert played_music == ["shopping"]
    assert town.text_log.is_waiting_for_input

    town.text_log.handle_char("b")
    assert town.text_log.is_waiting_for_input

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="\x1b"))
    assert not town.text_log.is_waiting_for_input
    assert town.text_log._callback is None
    assert town.text_log._on_cancel is None
    assert played_music == ["shopping", "towns"]


def test_generic_vendor_escape_clears_prompt_and_restores_music(pygame_setup):
    """Pressing ESC at the generic vendor fallback prompt clears text_log
    and invokes on_cancel to restore town music."""
    import pygame

    played_music: list[str] = []

    class _StubAudio:
        def play_music(self, name: str, **kwargs) -> None:
            played_music.append(name)

        def play_sfx(self, name: str, **kwargs) -> None:
            pass

    party = make_party((500,))
    town = TownScreen(party=party, map_id=3, audio=_StubAudio())
    vendor = VendorDef(
        id="X",
        name="Odd Shop",
        owner="Zed",
        vendor_type="MYSTERY",
        items=[VendorItemDef(choice="a", item_type="WEAPON", name="W0", price=1)],
    )
    town._start_vendor_shopping(vendor, buyer=party.members[0])
    assert played_music == ["shopping"]
    assert town.text_log.is_waiting_for_input

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="\x1b"))
    assert not town.text_log.is_waiting_for_input
    assert town.text_log._callback is None
    assert town.text_log._on_cancel is None
    assert played_music == ["shopping", "towns"]


def test_text_log_clear_does_not_fire_on_cancel_and_enter_clears_on_cancel():
    """TextLog.clear() drops on_cancel without calling it, and handle_enter()
    clears the previous prompt's on_cancel before firing chained prompts."""
    from py_exodus.ui.text_log import TextLog

    log = TextLog(max_lines=5)
    cancelled: list[str] = []
    submitted: list[str] = []

    log.prompt(
        "First?",
        callback=submitted.append,
        on_cancel=lambda: cancelled.append("clear"),
    )
    log.clear()
    assert not log.is_waiting_for_input
    assert cancelled == []

    def _on_first(val: str) -> None:
        submitted.append(val)
        log.prompt("Second?", callback=submitted.append)

    log.prompt(
        "First?",
        callback=_on_first,
        on_cancel=lambda: cancelled.append("stale"),
    )
    log.submit_input("ok")
    assert submitted == ["ok"]
    assert log.is_waiting_for_input

    log.handle_escape()
    assert not log.is_waiting_for_input
    assert cancelled == []


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


# --- Each question asked once (user 2026-11-23) ------------------------------


def _drive(vendor, inputs, gold=1000, setup=None):
    party = make_party((gold,))
    member = party.members[0]
    if setup:
        setup(member)
    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(vendor, buyer=member)
    for value in inputs:
        assert town.text_log.is_waiting_for_input
        town.text_log.submit_input(value)
    return town


@pytest.mark.parametrize(
    "vendor_fn, inputs, gold, setup",
    [
        (make_weapon_vendor, ["b", "b", "2", "y", "b", "c", "n"], 1000, None),
        (make_weapon_vendor, ["b", "c", "y", "n"], 40, None),
        (make_weapon_vendor, ["s", "b", "2", "n"], 0,
         lambda m: m.weapons.__setitem__(WeaponType.DAGGER, 3)),
        (make_weapon_vendor, ["s", "b", "y", "n"], 0,
         lambda m: m.weapons.__setitem__(WeaponType.DAGGER, 1)),
        (make_armor_vendor, ["b", "b", "y", "n"], 100, None),
        (make_food_vendor, ["y", "1", "n"], 1000, None),
        (make_tavern_vendor, ["f", "1", "a", "2", "n"], 1000, None),
        (make_horse_vendor, ["y", "n"], 1000, None),
        (make_oracle_vendor, ["1"], 1000, None),
        (make_guild_vendor, ["y", "b", "y", "n"], 1000, None),
        (make_healer_vendor, ["y", "b", "1", "y", "n"], 1000, None),
    ],
)
def test_no_shop_question_is_asked_twice(vendor_fn, inputs, gold, setup):
    """Java printed each question in the log and again beside its input
    field, so the port asked every shop question twice ("How many would you
    like?" then "How many would you like? 2"). The question is now the
    prompt: no line in the log may end with a question that the next line
    (the answered prompt) repeats."""
    town = _drive(vendor_fn(), inputs, gold, setup)
    hist = [h.strip() for h in town.text_log.history if h.strip()]
    for before, after in zip(hist, hist[1:]):
        if before.endswith("?"):
            assert not after.startswith(before.split(": ")[-1]), (before, after)
