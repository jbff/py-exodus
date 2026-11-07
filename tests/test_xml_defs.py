"""Tests for XML rules, entity definitions, and AssetManager XML ingestion."""
from py_exodus.assets import AssetManager
from py_exodus.constants import Profession
from py_exodus.entities.defs import CaseInsensitiveDict


def test_xml_entity_loading():
    """Baseline test specified in SDD plan."""
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()
    assert "orc" in am.creatures
    assert am.creatures["orc"].hp > 0
    assert "dagger" in am.weapons
    assert "cloth" in am.armors
    assert 0 in am.map_defs  # Sosaria
    assert am.map_defs[0].fname.lower() == "sosaria.ult"


def test_creatures_parsing():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    # Verify key creatures exist and have correct attributes
    assert "orc" in am.creatures
    orc = am.creatures["orc"]
    assert orc.name.lower() == "orc"
    assert orc.hp == 30
    assert orc.basehp == 30
    assert orc.exp == 3
    assert orc.level == 1
    assert orc.weak_against == "repond"

    skeleton = am.creatures["skeleton"]
    assert skeleton.undead is True
    assert skeleton.weak_against == "pontori"

    dragon = am.creatures["dragon"]
    assert dragon.ranged is True
    assert dragon.ranged_hit_tile == "fire"
    assert dragon.hp == 228

    balron = am.creatures["balron"]
    assert balron.poisons is True
    assert balron.ranged is True

    pirate = am.creatures["pirate"]
    assert pirate.sails is True

    serpent = am.creatures["serpent"]
    assert serpent.swims is True
    assert serpent.no_chest is True


def test_weapons_parsing_and_constraints():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    assert "dagger" in am.weapons
    dagger = am.weapons["dagger"]
    assert dagger.range == 16
    assert dagger.dmin == 4
    assert dagger.dmax == 7
    assert dagger.lose_when_ranged is True

    # Check constraints on 2-Handed Sword
    sword2h = am.weapons["sword_2h"]
    assert sword2h.dmax == 25
    # Fighter, Paladin, Barbarian, Lark, Ranger can use it
    assert sword2h.can_use(Profession.FIGHTER) is True
    assert sword2h.can_use(Profession.PALADIN) is True
    assert sword2h.can_use(Profession.BARBARIAN) is True
    # Wizard, Cleric, Thief cannot use 2H Sword
    assert sword2h.can_use(Profession.WIZARD) is False
    assert sword2h.can_use(Profession.CLERIC) is False
    assert sword2h.can_use(Profession.THIEF) is False


def test_armors_parsing_and_constraints():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    assert "cloth" in am.armors
    cloth = am.armors["cloth"]
    assert cloth.defense == 136

    plate = am.armors["plate"]
    assert plate.defense == 176
    assert plate.can_use(Profession.FIGHTER) is True
    assert plate.can_use(Profession.PALADIN) is True
    assert plate.can_use(Profession.RANGER) is True
    assert plate.can_use(Profession.WIZARD) is False
    assert plate.can_use(Profession.CLERIC) is False


def test_maps_parsing():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    # Map 0 is Sosaria overworld
    sosaria = am.map_defs[0]
    assert sosaria.id == 0
    assert sosaria.fname.lower() == "sosaria.ult"
    assert sosaria.width == 64
    assert sosaria.height == 64
    assert sosaria.border_behavior == "wrap"
    assert sosaria.music == "OUTSIDE"

    # Portals on Sosaria
    assert len(sosaria.portals) >= 19
    portal_to_british = next(p for p in sosaria.portals if p.dest_map_id == 1)
    assert portal_to_british.x == 45
    assert portal_to_british.y == 18
    assert portal_to_british.start_x == 32
    assert portal_to_british.start_y == 61

    # Moongates on Sosaria (8 moon phases)
    assert len(sosaria.moongates) == 8
    newmoon = next(m for m in sosaria.moongates if m.phase == 0)
    assert newmoon.name == "newmoon"
    assert newmoon.x == 7
    assert newmoon.y == 8
    assert (newmoon.d1, newmoon.d2, newmoon.d3) == (0, 1, 2)

    # Labels on Sosaria
    exotic_armor_lbl = next(lbl for lbl in sosaria.labels if lbl.name == "EXOTIC_ARMOR")
    assert exotic_armor_lbl.x == 79
    assert exotic_armor_lbl.y == 176

    # Dungeon Perinian (Map 14)
    perinian = am.map_defs[14]
    assert perinian.map_type == "dungeon"
    assert perinian.levels == 8
    assert len(perinian.labels) > 0

    # Combat map 33
    cnflct_a = am.map_defs[33]
    assert cnflct_a.map_type == "combat"
    assert cnflct_a.no_line_of_sight is True


def test_vendors_parsing():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    # Look up vendors by owner and name
    assert "winston" in am.vendors
    winston = am.vendors["winston"]
    assert winston.name == "Windsor Weaponry"
    assert winston.id == "DAWN"
    assert winston.vendor_type == "WEAPON"
    assert winston.start_x == 27
    assert winston.start_y == 17
    assert len(winston.items) > 0

    item_b = winston.get_item("b")
    assert item_b is not None
    assert item_b.name == "Dagger"
    assert item_b.price == 5

    # Check vendor classes
    assert "WEAPON" in am.vendor_classes
    assert "ARMOR" in am.vendor_classes
    assert "FOOD" in am.vendor_classes
    assert "TAVERNINFO" in am.vendor_classes
    assert "HEALER" in am.vendor_classes


def test_helper_getters_and_query_methods():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    # Case-insensitive entity getters
    assert am.get_creature("ORC") is not None
    assert am.get_creature("orc") is not None
    assert am.get_creature("nonexistent") is None

    assert am.get_weapon("DAGGER") is not None
    assert am.get_weapon("dagger") is not None

    assert am.get_armor("CLOTH") is not None
    assert am.get_armor("cloth") is not None

    # Map getters by ID, name, and filename
    assert am.get_map_def(0) is not None
    assert am.get_map_def("0") is not None
    assert am.get_map_def("14") is not None
    assert am.get_map_def("SOSARIA") is not None
    assert am.get_map_def("sosaria.ult") is not None
    assert am.get_map_def("sosaria") is not None

    # Vendor getters by map and coordinates
    winston = am.get_vendor("DAWN", 27, 17)
    assert winston is not None
    assert winston.owner == "Winston"

    winston_by_num = am.get_vendor(11, 27, 17)
    assert winston_by_num is not None
    assert winston_by_num.owner == "Winston"

    winston_by_str_num = am.get_vendor("11", 27, 17)
    assert winston_by_str_num is not None
    assert winston_by_str_num.owner == "Winston"

    dawn_vendors = am.get_vendors_for_map("DAWN")
    assert len(dawn_vendors) >= 5

    dawn_vendors_by_num = am.get_vendors_for_map(11)
    assert len(dawn_vendors_by_num) >= 5

    dawn_vendors_by_str_num = am.get_vendors_for_map("11")
    assert len(dawn_vendors_by_str_num) >= 5


def test_map_def_helper_methods():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_xml_definitions()

    sosaria = am.map_defs[0]
    portal = sosaria.get_portal(45, 18)
    assert portal is not None
    assert portal.dest_map_id == 1

    portals_to_1 = sosaria.get_portals_to(1)
    assert len(portals_to_1) == 1
    assert portals_to_1[0].x == 45

    gate = sosaria.get_moongate(0)
    assert gate is not None
    assert gate.name == "newmoon"

    lbls = sosaria.get_labels("EXOTIC_ARMOR")
    assert len(lbls) == 1
    assert lbls[0].x == 79


def test_case_insensitive_dict():
    d = CaseInsensitiveDict()

    # Setting with different casing replaces the existing key cleanly
    d["Orc"] = 1
    assert len(d) == 1
    assert d["orc"] == 1
    assert d["Orc"] == 1
    assert "orc" in d

    d["ORC"] = 2
    assert len(d) == 1
    assert d["orc"] == 2
    assert d["ORC"] == 2
    assert list(d.keys()) == ["ORC"]

    # Pop behavior
    val = d.pop("orc")
    assert val == 2
    assert len(d) == 0
    assert "orc" not in d
    assert d.get("orc") is None

    # Pop with default
    assert d.pop("nonexistent", 42) == 42

    # Setdefault behavior
    d.setdefault("Dagger", 10)
    assert d["dagger"] == 10
    d.setdefault("DAGGER", 20)
    assert d["dagger"] == 10

    # Popitem behavior
    k, v = d.popitem()
    assert k == "Dagger"
    assert v == 10
    assert "dagger" not in d

    # Clear behavior
    d["Skeleton"] = 5
    d["Dragon"] = 99
    assert "skeleton" in d
    assert "dragon" in d
    assert len(d) == 2

    d.clear()
    assert len(d) == 0
    assert "skeleton" not in d
    assert "dragon" not in d
    assert d.get("skeleton") is None
    assert d._lower_map == {}


