"""Tests for the dynamic castable spell mapping (Java getCastables).

Java truth: Constants.java:751-762 — walk ``Spell.values()`` in enum order,
keep spells where ``canCast(prof) && canCastLocation(mt) && cost <= mana``,
assign libgdx Keys A.. sequentially. Menu rows per SpellInputProcessor.java
:36-39: ``"%s - %s (%d)"`` — letter, enum NAME, cost (cost always printed,
including 0).

The expectations here are recomputed independently from the LIVE enum
attributes (declaration order, spell_type, castable_mask, location_mask,
cost) rather than hard-coded spell lists, so an enum edit changes the
expected result instead of silently passing a stale audit.
"""

import contextlib
import dataclasses

import pytest

from py_exodus import debug
from py_exodus.constants import MapType, Profession, Race, Spell
from py_exodus.entities.character import Character
from py_exodus.spell_menu import get_castables, spell_menu_prompt_lines

#: Java MapType.val values (Constants.java:248-257) for independent recompute.
_MAP_MASKS = {
    "world": 0x01,
    "combat": 0x02,
    "city": 0x04,
    "dungeon": 0x08,
    "shrine": 0x10,
}


def _recompute(profession, context, mana, *, no_class=False, full_mp=False, discipline=None):
    """Independent restatement of the Java walk (see module docstring).

    Written against the enum attributes directly — deliberately NOT the
    production code — so the audit expectation moves when the enum moves.
    """
    mask = _MAP_MASKS[context]
    out = []
    i = 0
    for s in Spell:
        if discipline is not None and s.spell_type != discipline:
            continue
        if not no_class and not (s.castable_mask & profession.mask):
            continue
        if not (s.location_mask & mask):
            continue
        if not full_mp and s.cost > mana:
            continue
        out.append((chr(ord("A") + i), s))
        i += 1
    return out


@contextlib.contextmanager
def _cheats(**flags):
    """Temporarily flip debug.CHEATS fields, restoring them afterwards."""
    saved = dataclasses.replace(debug.CHEATS)
    for name, value in flags.items():
        setattr(debug.CHEATS, name, value)
    try:
        yield
    finally:
        for f in dataclasses.fields(debug.CHEATS):
            setattr(debug.CHEATS, f.name, getattr(saved, f.name))


def _cleric(mp=99):
    c = Character("Cleric", "F", Race.BOBIT, Profession.CLERIC)
    c.mp = mp
    return c


def _wizard(mp=99):
    c = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD)
    c.mp = mp
    return c


def test_cleric_combat_matches_enum_walk():
    """Full-MP cleric in combat == the independently recomputed enum walk."""
    castables = get_castables(_cleric(99), "combat", "cleric", cheats_ok=False)
    spell_names = [s.name for _, s in castables]
    letters = [l for l, _ in castables]

    expected = _recompute(Profession.CLERIC, "combat", 99, discipline="cleric")
    assert spell_names == [s.name for _, s in expected]
    # PONTORI is 0-cost and first, so it takes A; letters run A.. sequentially
    # over the survivors, compacting past dropped entries.
    assert letters == [chr(ord("A") + i) for i in range(len(expected))]


def test_wizard_combat_matches_enum_walk():
    """Wizard profession in combat == the recomputed walk in enum order."""
    castables = get_castables(_wizard(99), "combat", "wizard", cheats_ok=False)
    expected = _recompute(Profession.WIZARD, "combat", 99, discipline="wizard")
    assert [(l, s.name) for l, s in castables] == [(l, s.name) for l, s in expected]
    assert len(castables) > 0  # sanity: the walk is non-empty


def test_low_mp_compacts_letters():
    """A cleric at MP 3 drops >3-cost entries; letters compact to A.."""
    castables = get_castables(_cleric(3), "combat", "cleric", cheats_ok=False)
    expected = _recompute(Profession.CLERIC, "combat", 3, discipline="cleric")
    assert [(l, s.name) for l, s in castables] == [(l, s.name) for l, s in expected]
    # 0-cost PONTORI survives at A; every other cleric spell costs >= 5.
    assert [s.name for _, s in castables] == ["PONTORI"]
    assert [l for l, _ in castables] == ["A"]


def test_appar_unem_location_mask():
    """APPAR_UNEM (city|world|dungeon mask) is absent in combat, present in world."""
    combat = get_castables(_cleric(99), "combat", "cleric", cheats_ok=False)
    assert "APPAR_UNEM" not in [s.name for _, s in combat]

    world = get_castables(_cleric(99), "world", "cleric", cheats_ok=False)
    names = [s.name for _, s in world]
    assert "APPAR_UNEM" in names
    assert names == [s.name for _, s in _recompute(Profession.CLERIC, "world", 99, discipline="cleric")]


def test_barbarian_empty():
    """No spell's castable_mask includes the barbarian bit — combat list is empty."""
    b = Character("Barb", "M", Race.HUMAN, Profession.BARBARIAN)
    b.mp = 99
    assert get_castables(b, "combat", "cleric", cheats_ok=False) == []
    assert get_castables(b, "combat", "wizard", cheats_ok=False) == []
    assert get_castables(b, "combat", None, cheats_ok=False) == []


def test_no_class_cheat_widens():
    """NOCLASS: the per-spell profession gate opens (cheat.c:414-825)."""
    b = Character("Barb", "M", Race.HUMAN, Profession.BARBARIAN)
    b.mp = 99
    with _cheats(no_class=True):
        got = get_castables(b, "combat", None)
    assert [(l, s.name) for l, s in got] == [
        (l, s.name) for l, s in _recompute(Profession.BARBARIAN, "combat", 99, no_class=True)
    ]
    assert len(got) > 0

    # cheats_ok=False ignores CHEATS even when toggled on.
    with _cheats(no_class=True):
        assert get_castables(b, "combat", None, cheats_ok=False) == []


def test_full_mp_bypasses_cost_filter():
    """FULL MP: the cost <= mana filter is skipped (mana is never consulted)."""
    broke = _cleric(0)
    with _cheats(full_mp=True):
        got = get_castables(broke, "combat", "cleric")
    assert [(l, s.name) for l, s in got] == [
        (l, s.name)
        for l, s in _recompute(Profession.CLERIC, "combat", 0, full_mp=True, discipline="cleric")
    ]
    # Same list shape as a full-MP cleric: every location-matching spell is in.
    rich = get_castables(_cleric(99), "combat", "cleric", cheats_ok=False)
    assert [s.name for _, s in got] == [s.name for _, s in rich]


def test_context_maps_to_java_maptype():
    """city context admits city-mask spells; dungeon admits dungeon masks."""
    city = get_castables(_cleric(99), "city", "cleric", cheats_ok=False)
    assert "VIEDA" in [s.name for _, s in city]  # mask world|city
    assert "SANCTU" in [s.name for _, s in city]  # mask 0xFF

    dungeon = get_castables(_cleric(99), "dungeon", "cleric", cheats_ok=False)
    assert "LUMINAE" in [s.name for _, s in dungeon]
    assert "EXCUUN" not in [s.name for _, s in dungeon]  # combat-only mask


def test_undivided_walk_matches_java_no_discipline_split():
    """discipline=None reproduces Java's single interleaved walk.

    Java has no discipline argument (Constants.java:751-762): a druid sees
    wizard and cleric spells interleaved in one letter map. py passes the
    resolved discipline only because its prompt flow splits the menus.
    """
    druid = Character("Druid", "F", Race.HUMAN, Profession.DRUID)
    druid.mp = 99
    got = get_castables(druid, "combat", None, cheats_ok=False)
    assert [(l, s.name) for l, s in got] == [
        (l, s.name) for l, s in _recompute(Profession.DRUID, "combat", 99)
    ]
    types = {s.spell_type for _, s in got}
    assert types == {"wizard", "cleric"}


def test_unknown_context_raises():
    with pytest.raises(ValueError):
        get_castables(_cleric(99), "shrineless", "cleric")


def test_prompt_lines_format():
    """Rows match Java SpellInputProcessor.java:36-39 exactly.

    Java: screen.log(String.format("%s - %s (%d)", key, spell, cost)) — the
    enum NAME (not the description), and the cost is always printed, 0
    included ("A - PONTORI (0)").
    """
    sample = [(l, s) for l, s in get_castables(_cleric(99), "combat", "cleric", cheats_ok=False)]
    lines = spell_menu_prompt_lines(sample)
    assert lines[0] == "A - PONTORI (0)"
    assert lines[1] == "B - SANCTU (10)"
    for line in lines[2:]:
        # every row: "<letter> - <NAME> (<int>)"
        head, cost = line.rsplit(" (", 1)
        letter, name = head.split(" - ")
        assert "A" <= letter <= "Z"
        assert cost.endswith(")")
        int(cost[:-1])
        assert name == name.upper()


def test_prompt_lines_explicit_rows():
    """Pin the exact rendered rows for a known pair (format lock)."""
    lines = spell_menu_prompt_lines(
        [("A", Spell.PONTORI), ("B", Spell.APPAR_UNEM), ("C", Spell.SANCTU)]
    )
    assert lines == ["A - PONTORI (0)", "B - APPAR_UNEM (5)", "C - SANCTU (10)"]


def test_map_type_masks_match_java():
    """The context masks the test recompute uses mirror Java's MapType.val
    (Constants.java:248-257); guard the py constants against drift."""
    assert MapType.WORLD.mask == 0x01
    assert MapType.COMBAT.mask == 0x02
    assert MapType.CITY.mask == 0x04
    assert MapType.DUNGEON.mask == 0x08
