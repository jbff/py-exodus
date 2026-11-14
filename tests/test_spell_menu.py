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
import re

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


# --- Task 3: the shared prompt flow consumes the mapping --------------------
# (combat/magic.py prompt_cast_party — the overworld/town/dungeon flow; the
# combat screen flow is pinned by the play-driver sequence tests.)

_SPELL_ROW = re.compile(r"^[A-Z] - [A-Z_]+ \(\d+\)$")


def _flow_party(mp: int):
    from py_exodus.entities.party import Party

    party = Party()
    party.add_member(_cleric(mp))
    return party


def _prompt_world_cleric(mp: int = 99):
    """Open the shared cast prompt and select the cleric; returns the TextLog."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.ui.text_log import TextLog

    log = TextLog()
    prompt_cast_party(log, _flow_party(mp))
    log.handle_char("1")  # the cleric is member 1
    return log


def test_dungeon_flow_walks_the_dungeon_mask():
    """The dungeon screen passes its DungeonState (SecondaryInputProcessor
    .java:443 passes MapType.dungeon in Java): the flow unwraps ``dmap`` the
    same way cast_spell's location gate does, so the dungeon-mask spells
    (APPAR_UNEM city|world|dungeon, REC_SU/REC_DU/SEQUITU dungeon-only) are
    walkable — LUMINAE is NEVER reachable from a world-context walk."""
    from types import SimpleNamespace

    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.entities.party import Party
    from py_exodus.ui.text_log import TextLog

    dungeon_state = SimpleNamespace(
        dmap=SimpleNamespace(map_type=MapType.DUNGEON)
    )
    party = Party()
    party.add_member(_cleric(40))
    log = TextLog()
    prompt_cast_party(log, party, world_map=dungeon_state)
    log.handle_char("1")  # the cleric
    rows = [str(line) for line in log.history if _SPELL_ROW.match(str(line))]
    names = [row.split(" - ")[1].split(" (")[0] for row in rows]
    assert "LUMINAE" in names
    assert "REC_SU" in names
    assert "SEQUITU" in names
    # The letters were recomputed from the live walk (context-aware).
    assert rows[0] == "A - APPAR_UNEM (5)"  # 0x0D includes the dungeon bit


def test_world_flow_prints_rows_after_member_selection():
    """The list rows print as the spell prompt opens (Java
    SpellInputProcessor.java:36-39 via SecondaryInputProcessor.java:283)."""
    log = _prompt_world_cleric()
    assert log.current_prompt == "Cleric Spell? (A-P):"
    rows = [
        str(line) for line in log.history if _SPELL_ROW.match(str(line))
    ]
    # World-context cleric walk (mp 99): APPAR_UNEM leads (PONTORI's mask is
    # combat-only), letters compact from A.. over the survivors.
    assert rows == [
        "A - APPAR_UNEM (5)",
        "B - SANCTU (10)",
        "C - ALCORT (35)",
        "D - SANCTU_MANI (50)",
        "E - VIEDA (55)",
        "F - SURMANDUM (65)",
        "G - ANJU_SERMANI (75)",
    ]


def test_unmapped_letter_is_a_silent_noop_prompt_stays_open():
    """A letter beyond the live list does nothing (silence): the old
    "Unknown spell!" path is gone and the menu keeps awaiting a mapped
    letter (Task-3 ruling 2026-11-14; Java's "Not a spell!" disarms instead
    — see the code commentary)."""
    log = _prompt_world_cleric(mp=15)  # list: A APPAR_UNEM (5), B SANCTU (10)
    assert log.current_prompt == "Cleric Spell? (A-P):"
    log.handle_char("D")  # beyond the two-entry list
    assert log.is_waiting_for_input
    assert log.current_prompt == "Cleric Spell? (A-P):"
    blob = "\n".join(str(line) for line in log.history)
    assert "Unknown spell!" not in blob
    assert "Not a spell!" not in blob


def test_unaffordable_spell_never_offers_mp_refusal():
    """MP 3 in context "world": every >3-cost spell is unlisted, so the
    prompt flow can never emit "Thou dost not have enough magic points!".
    A mage at MP 3 has an EMPTY world wizard list (DAG_ACRON 30, PABULUM 40,
    FAL_DIVI 45 are all unaffordable) — the Java empty-map canonical line
    prints instead of a prompt."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.entities.party import Party
    from py_exodus.ui.text_log import TextLog

    party = Party()
    party.add_member(_wizard(3))
    log = TextLog()
    prompt_cast_party(log, party)
    log.handle_char("1")
    blob = "\n".join(str(line) for line in log.history)
    assert "No spells to cast!" in blob
    assert "magic points" not in blob
    assert not log.is_waiting_for_input


def test_mapped_letter_dispatches_and_deducts_cost():
    """Selecting a listed letter casts exactly the mapped spell (the lookup
    resolves through the same get_castables list that printed the rows).
    SANCTU is listed at B for a cleric at MP 15 — the letter no longer
    means the fixed-code C."""
    log = _prompt_world_cleric(mp=15)
    log.handle_char("B")  # SANCTU (10)
    assert log.current_prompt == "On who? (1-4):"  # targeted restorative
    log.handle_char("1")  # target the cleric themselves
    assert not log.is_waiting_for_input
    blob = "\n".join(str(line) for line in log.history)
    assert "Unknown spell!" not in blob
    assert "cannot cast" not in blob
