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


# --- Transact: which shop is where -------------------------------------------

_LW_SHOP = {0: "TAVERNINFO", 1: "FOOD", 2: "HEALER", 3: "WEAPON", 4: "ARMOR",
            5: "GUILDITEM", 6: "ORACLEINFO", 7: "HORSE"}


def _counter_stands(town: str, x: int, y: int) -> list[tuple[int, int]]:
    """Where a party can stand to Transact with the merchant at (x, y): a
    counter tile (0x94..0xE7, port tiles 37..57) between them, and floor or
    grass (not wall, water or another shopkeeper) to stand on."""
    d = json.loads((ROOT / "assets" / "maps" / f"{town.lower()}.json").read_text())
    keepers = {(n["x"], n["y"]) for n in d["npcs"] if n["tile"] == 16}
    under = {(n["x"], n["y"]): n["underlying"] for n in d["npcs"]}
    stands = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        px, py = x - 2 * dx, y - 2 * dy
        if not (0 <= px < 64 and 0 <= py < 64) or (px, py) in keepers:
            continue
        if 37 <= d["tiles"][y - dy][x - dx] <= 57 and under.get((px, py), d["tiles"][py][px]) in (1, 2, 8):
            stands.append((px, py))
    return stands


def test_transact_every_shop_type_is_its_counter_row(assets):
    """UltimaMain.c:2313-2324: Transact needs a counter tile (0x94..0xE7)
    with the merchant (0x40) behind it, and the shop is ``shopNum = (ypos &
    0x07)``, the party's row. Every vendor in vendor.xml is such a merchant
    and each spot a party can Transact with it from selects its own shop
    type. (LCB's Alfred, boxed in behind Ethelred, has no spot until he
    walks.)"""
    for vtype, vc in assets.vendor_classes.items():
        for v in vc.vendors:
            stands = _counter_stands(v.id, v.start_x, v.start_y)
            assert stands or v.owner == "Alfred", (v.id, v.owner)
            assert all(_LW_SHOP[py & 7] == vtype for _px, py in stands), (v.id, v.owner, vtype)


def test_transact_lairware_shop_list(assets):
    """UltimaMain.c:2313-2324 on the town maps: Devil Guard has the horse
    shop at (11, 13) (stand row 15 -> 7), Grey has none; Death Gulch
    (52, 35), Montor West (32, 51) and Moon (18, 51) have grocers (row & 7
    == 1); the Castle British cook at (16, 21) has no counter, so he talks
    ("Like the food?") and sells nothing."""
    def at(town, x, y):
        return assets.get_vendor(town, x, y)

    assert at("DEVIL", 11, 13).vendor_type == "HORSE"
    assert all(v.id.upper() != "GREY" for v in assets.vendor_classes["HORSE"].vendors)
    for town, x, y in (("DEATH", 52, 35), ("MONTOR_W", 32, 51), ("MOON", 18, 51)):
        assert at(town, x, y).vendor_type == "FOOD", town
    assert at("BRITISH", 16, 21) is None


# --- Weapons and armour: prices, Dawn's stock, the 99 cap --------------------


def test_weaponlist_prices_and_dawn_stock(assets):
    """UltimaMisc.c:1794-1796, 1897-1899: ``opnum = 'I'; if (Party[4] == 37)
    opnum = 'P';`` (armour 'F' / 'H'): Dawn (Sosaria x 37) sells weapons
    B..O and armour B..G, every other shop B..H and B..E, at WeaponsArmour
    prices (index input + 25 / input + 41)."""
    weapons = [5, 30, 60, 125, 350, 200, 250, 400, 1050, 800, 1200, 2700, 6550, 4550]
    armour = [75, 195, 575, 2500, 6130, 8250]
    for v in assets.vendor_classes["WEAPON"].vendors:
        n = 14 if v.id.upper() == "DAWN" else 7
        assert [i.price for i in v.items] == weapons[:n], v.owner
        assert [i.choice for i in v.items] == [chr(ord("b") + k) for k in range(n)]
    for v in assets.vendor_classes["ARMOR"].vendors:
        n = 6 if v.id.upper() == "DAWN" else 4
        assert [i.price for i in v.items] == armour[:n], v.owner


def test_shop_weapon_buy_refused_at_99(assets):
    """UltimaMisc.c:1835-1840: ``if (Player[rosNum][49 + input] > 98) {
    UPrintMessageRewrapped(260); ... goto shop3; }`` -- the count includes
    the readied weapon; at 99 the shop says "Not enough room!" and asks
    again, charging nothing."""
    party = _party(5000)
    m = party.members[0]
    m.weapon = WeaponType.DAGGER
    m.weapons[WeaponType.DAGGER] = 98  # 99 with the readied one
    town = _shop(_vendor(assets, "LCB", "WEAPON"), party)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    assert "Not enough room!" in _log(town)
    assert m.gold == 5000 and m.weapons[WeaponType.DAGGER] == 98
    assert "Your Interest?" in town.text_log.current_prompt


def test_shop_weapon_buy_up_to_99(assets):
    """UltimaMisc.c:1835-1848: one more fits at 98 (98 -> 99); a count that
    would pass 99 is refused with message 260 and nothing is charged."""
    party = _party(5000)
    m = party.members[0]
    m.weapons[WeaponType.DAGGER] = 97
    town = _shop(_vendor(assets, "LCB", "WEAPON"), party)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    town.text_log.submit_input("3")
    assert "Not enough room!" in _log(town)
    assert m.gold == 5000 and m.weapons[WeaponType.DAGGER] == 97
    town.text_log.submit_input("b")
    town.text_log.submit_input("2")
    assert m.weapons[WeaponType.DAGGER] == 99 and m.gold == 4990


def test_shop_armour_buy_refused_at_99(assets):
    """UltimaMisc.c:1938-1943: ``if (Player[rosNum][41 + input] > 98)`` ->
    message 260, nothing charged (worn armour counts)."""
    party = _party(5000)
    m = party.members[0]
    m.armor = ArmorType.CLOTH
    m.armors[ArmorType.CLOTH] = 98
    town = _shop(_vendor(assets, "LCB", "ARMOR"), party)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    assert "Not enough room!" in _log(town)
    assert m.gold == 5000 and m.armors[ArmorType.CLOTH] == 98


def test_autoplay_walks_away_from_a_full_stack(assets):
    """Autoplay answers the item question again after message 260 "Not
    enough room!" (UltimaMisc.c:1835-1840 re-asks) with ESC, not the same
    letter forever."""
    import pygame

    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.state_machine import StateMachine

    party = _party(5000)
    m = party.members[0]
    m.weapons[WeaponType.DAGGER] = 99
    town = _shop(_vendor(assets, "LCB", "WEAPON"), party)
    town.text_log.submit_input("b")
    town.text_log.submit_input("b")
    assert "Not enough room!" in _log(town)
    ctrl = AutoPlayController(enabled=True)
    ctrl._shop_item_letter = "b"
    sm = StateMachine(asset_mgr=assets, audio=None)
    assert ctrl._handle_town_prompt(sm, town) == pygame.K_ESCAPE


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


# --- Pub -------------------------------------------------------------------------


def _pub(assets, gold: int = 500):
    party = _party(gold)
    town = _shop(_vendor(assets, "FAWN", "TAVERNINFO"), party)
    town.text_log.submit_input("a")
    return party.members[0], town


def test_pub_drink_costs_seven(assets):
    """UltimaMisc.c:1609-1619 (message 186 "It cost 7 g.p."): ``if (input <
    7)`` -> "LEAVE MY SHOP! YOU SCUM!!" and the visit ends, nothing paid."""
    m, town = _pub(assets)
    assert "7gp" in _log(town)
    town.text_log.submit_input("6")
    assert m.gold == 500
    assert not town.text_log.is_waiting_for_input


@pytest.mark.parametrize(
    "pay, clue",
    [
        (7, "Thank you, kindly!"),
        (9, "Thank you, kindly!"),
        (10, "Ambrosia, ever heard of it?"),
        (29, "Dawn, the city of myths & magic!"),
        (30, "The conjunction of the moons finds link!"),
        (45, "Nasty creatures, nasty dark"),
        (50, "None return or so I'm told"),
        (60, "Shrines of knowledge"),
        (70, "Fountains fair & fountains foul"),
        (80, "EXODUS: Ultima III, which is next?"),
        (99, "Seek ye out the Lord of Time"),
    ],
)
def test_pub_clue_by_amount_paid(assets, pay, clue):
    """UltimaMisc.c:1628-1632: the whole payment is taken and the line is
    ``Pub[input / 10]`` (Pub.plist, ten lines for 7-9, 10-19, ... 90-99)."""
    m, town = _pub(assets)
    town.text_log.submit_input(str(pay))
    assert m.gold == 500 - pay
    assert clue in _log(town)


def test_pub_pays_at_most_two_digits(assets):
    """UltimaMisc.c:1612 ``input = UInputNum(tx, ty);`` and UltimaText.c:469-
    479: UInputNum reads two characters, so 99 is the most a drink costs."""
    m, town = _pub(assets)
    town.text_log.submit_input("150")
    assert m.gold == 500 - 15
    assert "Ambrosia, ever heard of it?" in _log(town)
