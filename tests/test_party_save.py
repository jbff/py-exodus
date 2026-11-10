"""Tests for Party, Character, Roster, Character Creation & JSON Save System."""
from __future__ import annotations

import os
import struct
import tempfile

import pygame
import pytest

from py_exodus.constants import Direction, Profession, Race, Sex, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.save_system import SaveSystem
from py_exodus.state_machine import StateMachine


def test_party_save_load():
    """Verify basic party creation, modification, and round-trip JSON persistence."""
    p = Party()
    c1 = Character(name="Fighter1", sex="M", race=Race.HUMAN, profession=Profession.FIGHTER)
    c1.hp = 150
    c1.max_hp = 150
    p.add_member(c1)
    p.gold = 500
    p.food = 800
    p.x, p.y = 45, 18
    p.map_id = 0

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_name = f.name

    try:
        SaveSystem.save_game(p, tmp_name)
        loaded = SaveSystem.load_game(tmp_name)
        assert len(loaded.members) == 1
        assert loaded.members[0].name == "Fighter1"
        assert loaded.gold == 500
        assert loaded.food == 800
        assert loaded.x == 45 and loaded.y == 18
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def test_character_creation_and_attributes():
    """Verify Character attribute defaults, accessors, aliases, and MP calculation."""
    c = Character(
        name="Shamino",
        sex=Sex.MALE,
        race=Race.ELF,
        profession=Profession.RANGER,
        strength=20,
        dexterity=25,
        intelligence=15,
        wisdom=10,
    )
    assert c.name == "Shamino"
    assert c.sex == Sex.MALE
    assert c.race == Race.ELF
    assert c.profession == Profession.RANGER
    assert c.str == 20
    assert c.dex == 25
    assert c.int == 15
    assert c.wis == 10
    # Ranger max MP is min(INT // 2, WIS // 2) = min(7, 5) = 5
    assert c.max_mp == 5

    # Check Wizard MP formula: INT
    wiz = Character(name="Mariah", race=Race.FUZZY, profession=Profession.WIZARD, intelligence=25)
    assert wiz.max_mp == 25

    # Check Cleric MP formula: WIS
    clr = Character(name="Jaana", race=Race.BOBIT, profession=Profession.CLERIC, wisdom=25)
    assert clr.max_mp == 25

    # Check Fighter MP formula: 0
    fig = Character(name="Geoffrey", race=Race.HUMAN, profession=Profession.FIGHTER)
    assert fig.max_mp == 0

    # Check Druid MP formula: max(INT // 2, WIS // 2)
    druid = Character(name="Iolo", race=Race.ELF, profession=Profession.DRUID, intelligence=20, wisdom=10)
    assert druid.max_mp == 10


def test_character_creation_validation():
    """Verify character creation rules (point cap, min/max bounds, race stat caps)."""
    # Valid character: total 50 points, 5-25 per stat, within Human caps (75 each)
    is_valid, msg = Character.validate_creation(
        race=Race.HUMAN,
        profession=Profession.FIGHTER,
        strength=15,
        dexterity=15,
        intelligence=10,
        wisdom=10,
    )
    assert is_valid is True
    assert msg == ""

    # Invalid: total points > 50
    is_valid, msg = Character.validate_creation(
        race=Race.HUMAN,
        profession=Profession.FIGHTER,
        strength=20,
        dexterity=20,
        intelligence=20,
        wisdom=20,
    )
    assert is_valid is False
    assert "points" in msg.lower() or "50" in msg

    # Invalid: stat < 5
    is_valid, msg = Character.validate_creation(
        race=Race.HUMAN,
        profession=Profession.FIGHTER,
        strength=4,
        dexterity=16,
        intelligence=15,
        wisdom=15,
    )
    assert is_valid is False
    assert "minimum" in msg.lower() or "5" in msg

    # Invalid: stat > 25
    is_valid, msg = Character.validate_creation(
        race=Race.HUMAN,
        profession=Profession.FIGHTER,
        strength=30,
        dexterity=5,
        intelligence=5,
        wisdom=10,
    )
    assert is_valid is False
    assert "maximum" in msg.lower() or "25" in msg

    # Invalid: Fuzzy has max STR of 25, trying 26 fails
    is_valid, msg = Character.validate_creation(
        race=Race.FUZZY,
        profession=Profession.FIGHTER,
        strength=26,
        dexterity=5,
        intelligence=10,
        wisdom=9,
    )
    assert is_valid is False


def test_character_status_and_progression():
    """Verify status conditions, leveling thresholds, and Lord British mechanics."""
    c = Character(name="Dupre", race=Race.HUMAN, profession=Profession.PALADIN)
    assert c.status == Status.GOOD
    assert not c.is_dead()

    c.status = Status.POISON
    assert c.status == Status.POISONED
    assert not c.is_dead()

    c.status = Status.DEAD
    assert c.is_dead()
    assert c.is_disabled()

    c.status = Status.ASHES
    assert c.status == Status.ASH
    assert c.is_disabled()

    # Reset and test leveling with Lord British
    c.status = Status.GOOD
    c.exp = 250
    c.level = 1
    # Level 1 max HP is 150 (level * 100 + 50)
    assert c.max_hp == 150

    promoted = c.meet_lord_british()
    assert promoted is True
    # Exp 250 allows reaching Level 3
    assert c.level == 3
    assert c.max_hp == 350
    assert c.hp == 350


def test_party_membership_and_swapping():
    """Verify party capacity (1-4), indexing, member swapping, and next active cycling."""
    p = Party()
    c1 = Character(name="C1", race=Race.HUMAN, profession=Profession.FIGHTER)
    c2 = Character(name="C2", race=Race.ELF, profession=Profession.WIZARD)
    c3 = Character(name="C3", race=Race.DWARF, profession=Profession.CLERIC)
    c4 = Character(name="C4", race=Race.BOBIT, profession=Profession.THIEF)
    c5 = Character(name="C5", race=Race.FUZZY, profession=Profession.DRUID)

    p.add_member(c1)
    p.add_member(c2)
    p.add_member(c3)
    p.add_member(c4)
    assert len(p.members) == 4

    # 5th member should raise ValueError
    with pytest.raises(ValueError):
        p.add_member(c5)

    assert p.active_member_index == 0
    assert p.active_member.name == "C1"

    # Swap member 0 and 2
    p.swap_members(0, 2)
    assert p.members[0].name == "C3"
    assert p.members[2].name == "C1"
    # Active index followed member C1 to index 2
    assert p.active_member_index == 2
    assert p.active_member.name == "C1"

    # Test cycling next active member
    p.members[0].status = Status.DEAD
    next_idx = p.get_next_active_index(from_index=0)
    assert next_idx == 1  # skips dead index 0


def test_party_gold_food_and_transport():
    """Verify gold pooling, food consumption per turn, starvation, transport, and hull health."""
    p = Party()
    c1 = Character(name="Hero1", gold=100, food=50)
    c2 = Character(name="Hero2", gold=200, food=60)
    p.add_member(c1)
    p.add_member(c2)

    # Pool gold into the first member (Java Party.poolGold(index))
    p.pool_gold(0)
    assert p.gold == 300
    assert c1.gold == 300
    assert c2.gold == 0

    # Submorsels tick (town interval 10): crossing eats one unit of food each
    for m in p.members:
        m.submorsels = 5
        m.food = 10
        m.hp = 100
    p.end_turn(surface=False)
    assert p.food == 18
    # Meal crossing decrements food ONLY — heal/poison/mana regen moved to
    # the per-turn original-rules tick (Party.tick_regen, user-directed
    # deviation 2026-11-10), so no heal lands at the crossing.
    assert c1.hp == 100
    assert c2.hp == 100

    # Starvation: food 0 → 2 damage per turn on the regen tick
    for m in p.members:
        m.food = 0
        m.submorsels = 5
    p.end_turn(surface=False)  # crossing decrements food only (stays 0)
    p.tick_regen(surface=False)  # first underground turn: -2 HP
    assert c1.hp == 98
    assert c2.hp == 98

    # Transport & Ship hull
    assert p.transport == Transport.FOOT
    p.transport = Transport.SHIP
    assert p.ship_hull == 50
    p.adjust_ship_hull(-15)
    assert p.ship_hull == 35
    p.adjust_ship_hull(30)
    assert p.ship_hull == 50  # capped at 50

    # Wind direction
    p.wind_direction = Direction.EAST
    assert p.wind_direction == Direction.EAST


def test_save_system_full_delta():
    """Verify JSON persistence with dynamic overworld delta (24 objects, 8 monsters)."""
    p = Party()
    c1 = Character(name="LordBritish", race=Race.HUMAN, profession=Profession.PALADIN)
    c1.keys = 5
    c1.gems = 10
    c1.torches = 15
    c1.cards = [1, 1, 0, 0]
    c1.marks = [1, 0, 1, 0]
    p.add_member(c1)

    p.x, p.y = 23, 42
    p.map_id = 0
    p.transport = Transport.HORSE
    p.gold = 1200
    p.food = 2500
    p.moves = 142

    # Add dynamic objects (e.g. docked frigate, chest, horse left behind)
    p.dynamic_objects.append({"tile_id": 16, "x": 10, "y": 15})  # docked frigate
    p.dynamic_objects.append({"tile_id": 14, "x": 22, "y": 40})  # horse
    p.dynamic_objects.append({"tile_id": 40, "x": 30, "y": 30})  # chest

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_name = f.name

    try:
        SaveSystem.save_game(p, tmp_name)
        loaded = SaveSystem.load_game(tmp_name)

        assert loaded.x == 23 and loaded.y == 42
        assert loaded.transport == Transport.HORSE
        assert loaded.gold == 1200
        assert loaded.food == 2500
        assert loaded.moves == 142
        assert len(loaded.members) == 1

        m = loaded.members[0]
        assert m.name == "LordBritish"
        assert m.keys == 5
        assert m.gems == 10
        assert m.torches == 15
        assert m.cards == [1, 1, 0, 0]
        assert m.marks == [1, 0, 1, 0]

        # Verify dynamic objects round-trip
        assert len(loaded.dynamic_objects) >= 3
        assert loaded.dynamic_objects[0]["tile_id"] == 16
        assert loaded.dynamic_objects[0]["x"] == 10
        assert loaded.dynamic_objects[0]["y"] == 15
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def test_legacy_save_pool_migration():
    """Pre-parity saves keep the wallet at party level; loading gathers it
    into member 0 (Java pool_gold(0) idiom) instead of silently dropping it."""
    legacy = {
        "x": 44,
        "y": 18,
        "map_id": 0,
        "dungeon_level": 0,
        "transport": "FOOT",
        "ship_hull": 50,
        "wind_direction": "NORTH",
        "gold": 500,
        "food": 800,
        "moves": 0,
        "torch_duration": 0,
        "active_member_index": 0,
        "exodus_cards_status": 0,
        "dynamic_objects": [],
        "dynamic_monsters": [],
        "members": [
            {
                "name": "Hero",
                "gold": 0,
                "food": 0,
            },
            {
                "name": "Mage",
                "gold": 0,
                "food": 0,
            },
        ],
    }

    loaded = Party.from_dict(legacy)

    # Legacy-migration: the party-level wallet lands on member 0.
    assert loaded.members[0].gold == 500
    assert loaded.members[0].food == 800
    assert loaded.members[1].gold == 0
    assert loaded.members[1].food == 0
    assert loaded.gold == 500
    assert loaded.food == 800


def test_legacy_migration_clamps_to_java_ranges():
    """The migration credit runs through Java's clamp semantics: gold adjusts
    within 0..9999 (CharacterRecord.adjustGold, SaveGame.java:390-392) and
    food within 0..999900 (Utils.adjustValue(food, v, 999900, 0) — the same
    call Party.endTurn uses, Party.java:604). An oversized legacy pool clamps
    instead of corrupting the save."""
    legacy = {
        "x": 44,
        "y": 18,
        "map_id": 0,
        "transport": "FOOT",
        "gold": 50000,
        "food": 2000000,
        "members": [
            {"name": "Hero", "gold": 120, "food": 300},
            {"name": "Mage", "gold": 0, "food": 0},
        ],
    }

    loaded = Party.from_dict(legacy)

    # Pooled 120 + legacy 50000 clamps at the 9999 cap, not 50120.
    assert loaded.members[0].gold == 9999
    assert loaded.gold == 9999
    # Pooled 300 + legacy 2000000 clamps at 999900, not 2000300.
    assert loaded.members[0].food == 999900
    assert loaded.food == 999900


def test_legacy_keys_in_modern_saves_do_not_double_credit():
    """A modern save's party-level gold/food are derived sums equal to the
    member purses; loading must not re-gather or double them."""
    p = Party()
    c1 = Character(name="Hero", gold=300, food=500)
    c2 = Character(name="Mage", gold=100, food=200)
    p.add_member(c1)
    p.add_member(c2)

    data = p.to_dict()
    assert data["gold"] == 400 and data["food"] == 700

    loaded = Party.from_dict(data)

    assert loaded.members[0].gold == 300
    assert loaded.members[0].food == 500
    assert loaded.members[1].gold == 100
    assert loaded.members[1].food == 200
    assert loaded.gold == 400
    assert loaded.food == 700


def test_binary_roster_and_party_loader():
    """Verify reading initial characters from binary 64-byte records and party.ult."""
    # Create synthetic 64-byte binary record for a character:
    # 0x00..0x09: Name (10 bytes null padded)
    # 0x0E: cards/marks bitmask
    # 0x0F: torches
    # 0x11: status ('G')
    # 0x12..0x15: STR, DEX, INT, WIS
    # 0x16: race ('H')
    # 0x17: profession ('F')
    # 0x18: sex ('M')
    # 0x1B..0x1C: HP (short 150)
    # 0x23..0x24: Gold (short 200)
    rec = bytearray(64)
    name = b"Conan\x00\x00\x00\x00\x00"
    rec[0:10] = name
    rec[0x0E] = 0x81  # Love card (0x01) + Kings mark (0x80)
    rec[0x0F] = 12    # Torches
    rec[0x11] = ord("G")
    rec[0x12] = 25    # STR
    rec[0x13] = 15    # DEX
    rec[0x14] = 5     # INT
    rec[0x15] = 5     # WIS
    rec[0x16] = ord("H")  # Human
    rec[0x17] = ord("F")  # Fighter
    rec[0x18] = ord("M")  # Male
    struct.pack_into("<H", rec, 0x1B, 150)  # HP
    struct.pack_into("<H", rec, 0x23, 200)  # Gold

    char = SaveSystem.parse_binary_character_record(bytes(rec))
    assert char is not None
    assert char.name == "Conan"
    assert char.race == Race.HUMAN
    assert char.profession == Profession.FIGHTER
    assert char.str == 25
    assert char.hp == 150
    assert char.gold == 200
    assert char.torches == 12
    assert char.cards[0] == 1  # Love card
    assert char.marks[0] == 1  # Kings mark

    # Verify loading existing asset party.ult if present
    asset_party_path = "src/main/resources/assets/data/party.ult"
    if os.path.exists(asset_party_path):
        binary_party = SaveSystem.load_binary_party(asset_party_path)
        assert isinstance(binary_party, Party)


def test_character_factory_and_aliases():
    """Verify Character.create factory, validation flag, property setters and aliases."""
    c = Character.create(
        name="Gwen",
        sex="F",
        race="Elf",
        profession="Lark",
        strength=10,
        dexterity=20,
        intelligence=15,
        wisdom=5,
    )
    assert c.name == "Gwen"
    assert c.sex == Sex.FEMALE
    assert c.race == Race.ELF
    assert c.profession == Profession.LARK

    # Test setter aliases
    c.strength = 18
    assert c.str == 18
    c.dexterity = 22
    assert c.dex == 22
    c.intelligence = 16
    assert c.int == 16
    c.wisdom = 8
    assert c.wis == 8

    c.health = 120
    assert c.hp == 120
    c.max_health = 160
    assert c.max_hp == 160

    c.mana = 7
    assert c.mp == 7
    c.max_mana = 14
    assert c.max_mp == 14

    # Factory validation failure
    with pytest.raises(ValueError):
        Character.create("BadChar", strength=30, dexterity=30)


def test_party_member_lifecycle():
    """Verify Party member removal, queries, revival, and total death handling."""
    p = Party()
    c1 = Character(name="Member1")
    c2 = Character(name="Member2")
    c3 = Character(name="Member3")

    p.add_member(c1)
    p.add_member(c2)
    p.add_member(c3)

    assert p.get_member(0).name == "Member1"
    assert p.get_member(1).name == "Member2"
    assert p.get_member(99) is None

    # Remove member by name
    removed = p.remove_member("Member2")
    assert removed is not None
    assert removed.name == "Member2"
    assert len(p.members) == 2

    # Remove member by index
    removed_idx = p.remove_member(0)
    assert removed_idx is not None
    assert removed_idx.name == "Member1"
    assert len(p.members) == 1

    # Kill and revive party
    assert p.is_anyone_alive()
    p.kill_all()
    assert p.is_party_dead()
    assert not p.is_anyone_alive()

    p.revive_all()
    assert p.is_anyone_alive()
    assert not p.is_party_dead()
    assert p.members[0].hp == p.members[0].max_hp


def test_roster_save_load_and_binary():
    """Verify save_roster and load_roster with JSON and binary roster.ult."""
    roster = [
        Character(name="R1", race=Race.HUMAN, profession=Profession.FIGHTER),
        Character(name="R2", race=Race.ELF, profession=Profession.WIZARD),
    ]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_name = f.name

    try:
        SaveSystem.save_roster(roster, tmp_name)
        loaded = SaveSystem.load_roster(tmp_name)
        assert len(loaded) == 2
        assert loaded[0].name == "R1"
        assert loaded[1].name == "R2"
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)

    # Load existing binary roster.ult asset if present
    asset_roster_path = "src/main/resources/assets/data/roster.ult"
    if os.path.exists(asset_roster_path):
        binary_roster = SaveSystem.load_roster(asset_roster_path)
        assert isinstance(binary_roster, list)
        assert len(binary_roster) == 20


def test_save_system_missing_file_errors():
    """Verify appropriate exceptions for missing save/roster files."""
    with pytest.raises(FileNotFoundError):
        SaveSystem.load_game("non_existent_save_game.json")

    with pytest.raises(FileNotFoundError):
        SaveSystem.load_roster("non_existent_roster.json")


def test_pool_gold_no_duplication():
    """Verify calling pool_gold(target_index) twice does not duplicate gold
    (Java Party.poolGold(index): total lands on member[index], rest zeroed)."""
    p = Party()
    c1 = Character(name="C1", gold=100)
    c2 = Character(name="C2", gold=200)
    p.add_member(c1)
    p.add_member(c2)

    # First pool into member 0
    total = p.pool_gold(0)
    assert total == 300
    assert p.members[0].gold == 300
    assert p.members[1].gold == 0
    assert p.gold == 300  # the sum is the whole gold in play

    # Pool again: idempotent — the total cannot grow
    p.pool_gold(0)
    assert p.gold == 300
    assert p.members[0].gold == 300
    assert p.members[1].gold == 0


def test_party_member_unwrap_order():
    """Verify PartyMember wrapping does not double-wrap an existing PartyMember."""
    char = Character(name="Original", gold=50)
    pm1 = PartyMember(char)
    assert pm1.character is char

    # Passing existing PartyMember to PartyMember constructor
    pm2 = PartyMember(pm1)
    assert pm2.character is char
    assert not isinstance(pm2.character, PartyMember)

    # Mutating via pm2 updates char directly
    pm2.gold = 75
    assert char.gold == 75
    assert pm1.gold == 75


def test_inventory_weapons_armors_serialization():
    """Verify carried weapons and armors count dictionary serialization."""
    from py_exodus.constants import ArmorType, WeaponType

    p = Party()
    c = Character(name="Armorer")
    c.weapons[WeaponType.DAGGER] = 3
    c.weapons[WeaponType.BOW] = 1
    c.armors[ArmorType.LEATHER] = 2
    c.armors[ArmorType.CHAIN] = 1
    p.add_member(c)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_name = f.name

    try:
        SaveSystem.save_game(p, tmp_name)
        loaded = SaveSystem.load_game(tmp_name)

        loaded_char = loaded.members[0]
        assert loaded_char.weapons[WeaponType.DAGGER] == 3
        assert loaded_char.weapons[WeaponType.BOW] == 1
        assert loaded_char.weapons[WeaponType.SWORD] == 0
        assert loaded_char.armors[ArmorType.LEATHER] == 2
        assert loaded_char.armors[ArmorType.CHAIN] == 1
        assert loaded_char.armors[ArmorType.PLATE] == 0
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


# --------------------------------------------------------------------------- #
# Party formation persistence (Java ManagePartyScreen.java:262-293)
# --------------------------------------------------------------------------- #
# Java's Save button writes BOTH records: the full roster to roster.sav and
# the formed party slots into saveGame.players[0..3] + numberInParty via
# saveGame.write(party.sav). A fresh party.sav carries only the loader
# defaults (FOOT transport, (45,19) start, Party defaults here), so the JSON
# written by SaveSystem.save_game matches what StartScreen's Journey Onward
# path reads back (start.py).


def _roster_char(name: str) -> Character:
    return Character(
        name=name,
        sex=Sex.MALE,
        race=Race.HUMAN,
        profession=Profession.FIGHTER,
        strength=10,
        dexterity=10,
        intelligence=10,
        wisdom=10,
        hp=150,
        max_hp=150,
        food=150,
        gold=150,
    )


def _form_party(scr) -> None:
    """Drive the roster screen: add the first two roster recruits to the party."""
    scr._add_selected_to_party()
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
    scr._add_selected_to_party()


def test_formed_party_save_writes_party_and_roster_json(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """The roster screen's Save action commits BOTH records (Java
    ManagePartyScreen.java:262-293): saves/party.json (formed party, first
    member = slot 0) and saves/roster.json."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen

    roster = [_roster_char("Ariel"), _roster_char("Bors"), _roster_char("Cymric")]
    scr = RosterScreen(asset_mgr=asset_mgr, roster=roster)
    _form_party(scr)

    scr._save_party_formations()

    party_path = tmp_path / "saves" / "party.json"
    roster_path = tmp_path / "saves" / "roster.json"
    assert party_path.exists()
    assert roster_path.exists()

    loaded = SaveSystem.load_game(party_path)
    assert len(loaded.members) == 2
    assert loaded.members[0].name == "Ariel"
    assert loaded.members[1].name == "Bors"
    # Fresh-party defaults: FOOT transport and the (45,19) start tile
    # (Java SaveGame.java:164-169 loader fixup).
    assert loaded.transport == Transport.FOOT
    assert (loaded.x, loaded.y) == (45, 19)

    saved_roster = SaveSystem.load_roster(roster_path)
    assert [c.name for c in saved_roster] == ["Ariel", "Bors", "Cymric"]

    # Java's Save button returns to the start screen after writing.
    assert scr.is_finished


def test_embark_saves_party_and_roster_json(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Embarking also commits both records before the overworld opens."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen

    sm = StateMachine(asset_mgr)
    roster = [_roster_char("Ariel"), _roster_char("Bors")]
    scr = RosterScreen(asset_mgr=asset_mgr, roster=roster, manager=sm)
    sm.push_screen(scr)
    _form_party(scr)
    scr._embark()

    from py_exodus.screens.overworld import OverworldScreen

    assert isinstance(sm.current_screen, OverworldScreen)

    loaded = SaveSystem.load_game(tmp_path / "saves" / "party.json")
    assert loaded.members[0].name == "Ariel"
    saved_roster = SaveSystem.load_roster(tmp_path / "saves" / "roster.json")
    assert [c.name for c in saved_roster] == ["Ariel", "Bors"]


# --------------------------------------------------------------------------- #
# Journey Onward flow (Java StartScreen.java:100-117)
# --------------------------------------------------------------------------- #
# Java reads party.sav from disk; party.sav missing OR players[0] name empty
# → ManagePartyScreen. There is NO default party in Java.


def test_journey_onward_without_save_opens_roster(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """party.sav missing → ManagePartyScreen (Java StartScreen.java:101-102)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()

    assert isinstance(start.next_screen, RosterScreen)
    # No default party anywhere on this path, and the roster starts empty
    # (Java's fresh ManagePartyScreen registry is all <empty> records).
    assert start.next_screen.roster == []
    assert len(start.next_screen.party.members) == 0


def test_journey_onward_with_valid_save_opens_overworld(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """A valid party save → GameScreen (Java StartScreen.java:114-116)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    SaveSystem.save_game(party, tmp_path / "saves" / "party.json")

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()

    assert isinstance(start.next_screen, OverworldScreen)
    loaded = start.next_screen.party
    assert loaded.members[0].name == "Ariel"


def test_journey_onward_with_empty_first_member_name_opens_roster(
    pygame_setup, asset_mgr, monkeypatch, tmp_path
):
    """players[0] name empty → ManagePartyScreen (Java StartScreen.java:108-113),
    even when later slots carry named members."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    party = Party()
    party.members = [PartyMember(Character(name=""))]
    party.add_member(_roster_char("Bors"))
    SaveSystem.save_game(party, tmp_path / "saves" / "party.json")

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()

    assert isinstance(start.next_screen, RosterScreen)


def test_journey_onward_with_corrupt_save_opens_roster(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """An unreadable party save behaves like a missing one → roster."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    save_dir = tmp_path / "saves"
    save_dir.mkdir()
    (save_dir / "party.json").write_text("{not valid json", encoding="utf-8")

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()

    assert isinstance(start.next_screen, RosterScreen)


def test_journey_onward_ignores_screen_attached_party(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Java StartScreen.java:100-117 — Journey Onward reads party.sav, never
    screen-attached state: with no save on disk, an attached party does not
    launch the overworld."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.roster_screen import RosterScreen
    from py_exodus.screens.start import StartScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    start = StartScreen(asset_mgr=asset_mgr, party=party)
    start._start_journey()

    assert isinstance(start.next_screen, RosterScreen)


# ---------------------------------------------------------------------------
# User-reported save bug (2026-11-10): after playing, exiting, and resuming
# with Journey Onward, the map looked different (sea monsters gone) and
# purchased items were missing.
#
# Symptom 1 (items) is probed below with the REAL vendor flow: buy weapons
# through TownScreen/vendor dialogs, Q-save (SaveSystem.save_game), reload
# (Party.from_dict) and assert the purchase survives. Java truth: only the
# Q command writes party.sav (GameScreen.java:557-563) — there is no
# save-on-exit in Java either, so a purchase made after the last Q is lost
# by ordering, not by a serialization gap.
#
# Symptom 2 (world state) mirrors Java Context.saveGame (Context.java:138-193):
# a Sosaria save carries the first 8 map creatures (whirlpools skipped but
# slot-consuming) and the GameScreen.java:280-330 restore-on-load rebuilds
# them at their saved positions. The port saved nothing per-map.
# ---------------------------------------------------------------------------


def _make_weapon_vendor():
    from py_exodus.assets import AssetManager

    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()
    return am.vendors.get("windsor weaponry")


def test_probe_weapon_purchase_survives_save_load(pygame_setup, tmp_path):
    """The REAL vendor flow: TownScreen._start_vendor_shopping → buy
    daggers → SaveSystem.save_game → SaveSystem.load_game → purchase
    present and purse debited (user symptom: purchased items missing)."""
    from py_exodus.constants import WeaponType
    from py_exodus.screens.town import TownScreen

    gold_start = 1000
    members = [
        PartyMember(Character(f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
        for i in range(2)
    ]
    party = Party(members, x=10, y=10, transport=Transport.FOOT)
    party.members[0].gold = gold_start

    town = TownScreen(party=party, map_id=1)
    town._start_vendor_shopping(_make_weapon_vendor(), buyer=party.members[0])
    town.text_log.submit_input("b")  # Buy
    town.text_log.submit_input("b")  # Dagger
    town.text_log.submit_input("2")  # How many: 2

    assert party.members[0].weapons[WeaponType.DAGGER] == 2

    save_path = tmp_path / "saves" / "party.json"
    SaveSystem.save_game(party, save_path)
    loaded = SaveSystem.load_game(save_path)

    assert loaded.members[0].weapons[WeaponType.DAGGER] == 2
    assert loaded.members[0].gold == gold_start - 10


def test_overworld_save_carries_dynamic_world_state(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Java Context.java:138-193 — a Sosaria Q-save serializes the per-map
    dynamic objects (up to 24: disembarked frigates, dropped chests, horses)
    and the wandering/sea creatures: positions + tile ids. User ruling
    (2026-11-10 amendment): whirlpools are NOT excluded — the first 8
    creatures save in list order regardless of kind, so the two re-seeded
    whirlpool fixtures ride in the block (Java's skip-without-freeing-slot
    quirk is a documented deviation now)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr)

    # The screen re-seeds its two whirlpool fixtures on Sosaria; after an
    # engulf round trip (teleport → map reload) the two fixtures stand among
    # the creatures when Q is pressed.
    ow.creatures.clear()
    for wx, wy in ((50, 13), (17, 48)):
        ow.creatures.append({
            "name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool",
            "x": wx, "y": wy, "wontattack": True,
        })
    # User-visible state: a sea monster where it was, plus a stolen frigate
    # and a dropped chest on the map.
    ow.creatures.append({"name": "Pirate", "tile_name": "pirate", "tile": "pirate", "x": 30, "y": 40})
    ow.creatures.append({"name": "Serpent", "tile_name": "serpent", "tile": "serpent", "x": 31, "y": 41})
    party.dynamic_objects.append({"tile": "frigate", "x": 12, "y": 34})
    party.dynamic_objects.append({"tile": "chest", "x": 20, "y": 21})

    ow._save_game()

    import json

    data = json.loads((tmp_path / "saves" / "party.json").read_text())
    monsters = data["overworld"]["monsters"]
    # Whirlpool fixtures ride in the block like any other creature (the
    # restore adds the non-engaging fixture flag itself).
    assert monsters == [
        {"name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool", "x": 50, "y": 13},
        {"name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool", "x": 17, "y": 48},
        {"name": "Pirate", "tile_name": "pirate", "tile": "pirate", "x": 30, "y": 40},
        {"name": "Serpent", "tile_name": "serpent", "tile": "serpent", "x": 31, "y": 41},
    ]
    # Map objects round-trip through the party record itself: the dynamic
    # objects list is saved with the party (Java objects_save arrays).
    assert {"tile": "frigate", "x": 12, "y": 34} in data["dynamic_objects"]
    assert {"tile": "chest", "x": 20, "y": 21} in data["dynamic_objects"]


def test_overworld_save_creature_cap_is_8_including_whirlpools(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """The block holds the first 8 map creatures in list order regardless
    of kind (up to 8, GameScreen.java:300-312 restore cap) — a whirlpool
    among them takes its slot (user ruling 2026-11-10)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr)
    ow.creatures.clear()
    ow.creatures.append({"name": "W", "tile_name": "whirlpool", "tile": "whirlpool",
                         "x": 1, "y": 2, "wontattack": True})
    for i in range(3):
        ow.creatures.append({
            "name": f"P{i}", "tile_name": "pirate", "tile": "pirate", "x": i, "y": 50,
        })

    ow._save_game()

    import json

    data = json.loads((tmp_path / "saves" / "party.json").read_text())
    monsters = data["overworld"]["monsters"]
    assert monsters == [
        {"name": "W", "tile_name": "whirlpool", "tile": "whirlpool", "x": 1, "y": 2},
        {"name": "P0", "tile_name": "pirate", "tile": "pirate", "x": 0, "y": 50},
        {"name": "P1", "tile_name": "pirate", "tile": "pirate", "x": 1, "y": 50},
        {"name": "P2", "tile_name": "pirate", "tile": "pirate", "x": 2, "y": 50},
    ]


def test_journey_onward_restores_sea_monsters_and_objects(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """Full user flow (Java GameScreen.java:280-330): Q-save on Sosaria with
    sea monsters + the whirlpool fixtures + disembarked frigate, exit,
    Journey Onward — the creatures (fixtures included) come back at their
    saved positions with NO duplicate fixtures, and the frigate is
    boardable again (user ruling 2026-11-10: the block owns whirlpools)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr)
    ow.creatures.clear()
    for wx, wy in ((50, 13), (17, 48)):
        ow.creatures.append({
            "name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool",
            "x": wx, "y": wy, "wontattack": True,
        })
    ow.creatures.append({"name": "Pirate", "tile_name": "pirate", "tile": "pirate", "x": 30, "y": 40, "hp": 37})
    ow.creatures.append({"name": "Squid", "tile_name": "squid", "tile": "squid", "x": 8, "y": 9})
    party.dynamic_objects.append({"tile": "frigate", "x": 12, "y": 34})

    ow._save_game()

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()
    resumed = start.next_screen
    assert isinstance(resumed, OverworldScreen)

    # Restored creatures stand exactly where they were saved (with hp). The
    # resumed screen's normal wanderer spawns may add extra creatures, but
    # nothing duplicates: every position is unique.
    positions = [(c["x"], c["y"]) for c in resumed.creatures]
    assert len(positions) == len(set(positions))
    restored = {p: c for p, c in zip(positions, resumed.creatures)}
    assert restored[(30, 40)]["tile_name"] == "pirate" and restored[(30, 40)]["hp"] == 37
    assert restored[(8, 9)]["tile_name"] == "squid"
    # Both whirlpool fixtures come back from the save — exactly 2, none
    # re-seeded on the side.
    whirls = [c for c in resumed.creatures if c.get("tile_name") == "whirlpool"]
    assert sorted((c["x"], c["y"]) for c in whirls) == [(17, 48), (50, 13)]
    assert all(c.get("wontattack") for c in whirls)

    # Map objects: the stolen frigate is still on the map and boardable.
    resumed.party.x, resumed.party.y = 12, 34
    resumed._board_transport()
    assert resumed.party.transport == Transport.SHIP
    assert {"tile": "frigate", "x": 12, "y": 34} not in resumed.party.dynamic_objects


def test_journey_onward_legacy_save_still_reseeds_whirlpools(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """A legacy save with NO `overworld` block (pre-amendment party.json)
    keeps the Task 9 fallback: the two whirlpool fixtures re-seed free
    (Java GameScreen.java:111-121 adds them on every map prepare)."""
    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    SaveSystem.save_game(party, tmp_path / "saves" / "party.json")  # no extras

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()
    resumed = start.next_screen
    assert isinstance(resumed, OverworldScreen)

    whirls = [c for c in resumed.creatures if c.get("tile_name") == "whirlpool"]
    assert sorted((c["x"], c["y"]) for c in whirls) == [(17, 48), (50, 13)]
    assert all(c.get("wontattack") for c in whirls)


def test_journey_onward_malformed_overworld_block_loads(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    """R1 rider: a hand-edited save whose `overworld` block is not a dict
    (e.g. []) is treated as ABSENT — Journey Onward still loads (Java
    degrades to the roster screen on an unreadable record rather than
    crashing) and the whirlpool fixtures re-seed free."""
    import json

    monkeypatch.chdir(tmp_path)

    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.start import StartScreen

    party = Party()
    party.add_member(_roster_char("Ariel"))
    SaveSystem.save_game(party, tmp_path / "saves" / "party.json")

    save_p = tmp_path / "saves" / "party.json"
    data = json.loads(save_p.read_text())
    data["overworld"] = ["not", "a", "dict"]
    save_p.write_text(json.dumps(data))

    start = StartScreen(asset_mgr=asset_mgr)
    start._start_journey()
    resumed = start.next_screen
    assert isinstance(resumed, OverworldScreen)

    whirls = [c for c in resumed.creatures if c.get("tile_name") == "whirlpool"]
    assert sorted((c["x"], c["y"]) for c in whirls) == [(17, 48), (50, 13)]
