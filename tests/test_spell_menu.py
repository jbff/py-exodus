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


def test_out_of_list_letter_logs_not_a_spell_and_disarms():
    """A key outside the live list logs Java's canonical "Not a spell!" and
    DISARMS the menu — the prompt closes with no row re-print and the
    player re-presses C to see the list again (Java
    SpellInputProcessor.java:69-72: any key failing the ``A..size`` guard —
    letters past the list length, digits, ESC — takes this same branch)."""
    log = _prompt_world_cleric(mp=15)  # list: A APPAR_UNEM (5), B SANCTU (10)
    assert log.current_prompt == "Cleric Spell? (A-P):"
    log.handle_char("D")  # beyond the two-entry list
    assert not log.is_waiting_for_input
    assert log.current_prompt == ""
    blob = "\n".join(str(line) for line in log.history)
    assert "Not a spell!" in blob
    assert "Unknown spell!" not in blob


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


# --- Task 7: context-availability audit — Java masks vs GBC battle tables ----
#
# Java truth for every spell row: Constants.java:693-726 ( Spell enum; the
# professions' bit values are Constants.java:579-589: BARBARIAN 0x001,
# DRUID 0x002, ALCHEMIST 0x004, RANGER 0x008, FIGHTER 0x010, WIZARD 0x020,
# THIEF 0x040, LARK 0x080, ILLUSIONIST 0x100, CLERIC 0x200, PALADIN 0x400 ),
# and the map-type bit values are Constants.java:248-257 (world 0x01,
# combat 0x02, city 0x04, dungeon 0x08). The walk itself is
# Constants.java:751-762 (getCastables).
#
# GBC truth for the battle menus: refs/ult3src/sdk/gbz80-gb/2-1-5/examples/
# u3/battle.c — clericspellsdat (battle.c:127, consumed by
# getmenuselection(6, clericspellsdat, ...) at battle.c:1042) offers
# PONTORI SANCTU ALCORT SANCTUM EXCUM ZXKUQYB with the SURMANDUM and
# ANJU_SERMANI rows commented out; wizardspellsdat (battle.c:191, consumed
# by getmenuselection(11, wizardspellsdat, ...) at battle.c:1222) offers
# REPOND MITTAR FULGAR MENTAR FALDIVI NOXUM DECORP ALTAIR DAGMENT NECORP
# and a XXXXXXX filler for the multi-death-bolt slot (no PABULUM).
#
# RECORDED RULING (plan Task 7, binding): where Java's mask walk and the GBC
# battle menu disagree for "combat", the JAVA list governs — the GBC
# omissions (cleric SURMANDUM / ANJU_SERMANI, wizard PABULUM) are the GBC
# port's own menu curation, not a rules change. These tests assert the Java
# list and record the GBC delta in comments.

#: Java Constants.java:693-724, transcribed row by row (name, cost,
#: castable_mask, location_mask) in Spell enum declaration order. The masks
#: are the Java expressions evaluated: 0x0AE = ALCHEMIST|DRUID|LARK|RANGER|WIZARD,
#: 0x0A6 = ALCHEMIST|DRUID|LARK|WIZARD, 0x020 = WIZARD alone,
#: 0x70A = CLERIC|ILLUSIONIST|PALADIN|RANGER|DRUID, 0x702 = CLERIC|ILLUSIONIST|PALADIN|DRUID,
#: 0x200 = CLERIC alone; locations 0x02 combat, 0x08 dungeon, 0x01 world,
#: 0x0D city|world|dungeon, 0x05 world|city, 0xff everywhere.
_JAVA_SPELLS = [
    ("REPOND", 0, 0x0AE, 0x02),  # Constants.java:693
    ("MITTAR", 5, 0x0AE, 0x02),  # Constants.java:694
    ("LORUM", 10, 0x0AE, 0x08),  # Constants.java:695
    ("DOR_ACRON", 15, 0x0AE, 0x08),  # Constants.java:696
    ("SUR_ACRON", 20, 0x0AE, 0x08),  # Constants.java:697
    ("FULGAR", 25, 0x0AE, 0x02),  # Constants.java:698
    ("DAG_ACRON", 30, 0x0AE, 0x01),  # Constants.java:699
    ("MENTAR", 35, 0x0AE, 0x02),  # Constants.java:700
    ("PABULUM", 40, 0x0A6, 0xFF),  # Constants.java:701
    ("FAL_DIVI", 45, 0x0A6, 0xFF),  # Constants.java:702
    ("NOXUM", 50, 0x020, 0x02),  # Constants.java:703
    ("DECORP", 55, 0x020, 0x02),  # Constants.java:704
    ("ALTAIR", 60, 0x020, 0xFF),  # Constants.java:705
    ("DAG_MENTAR", 65, 0x020, 0x02),  # Constants.java:706
    ("NECORP", 70, 0x020, 0x02),  # Constants.java:707
    ("UNSPEAKABLE", 75, 0x020, 0x02),  # Constants.java:708
    ("PONTORI", 0, 0x70A, 0x02),  # Constants.java:709
    ("APPAR_UNEM", 5, 0x70A, 0x0D),  # Constants.java:710
    ("SANCTU", 10, 0x70A, 0xFF),  # Constants.java:711
    ("LUMINAE", 15, 0x70A, 0x08),  # Constants.java:712
    ("REC_SU", 20, 0x70A, 0x08),  # Constants.java:713
    ("REC_DU", 25, 0x70A, 0x08),  # Constants.java:714
    ("LIB_REC", 30, 0x70A, 0x08),  # Constants.java:715
    ("ALCORT", 35, 0x70A, 0xFF),  # Constants.java:716
    ("SEQUITU", 40, 0x70A, 0x08),  # Constants.java:717
    ("SOMINAE", 45, 0x702, 0x08),  # Constants.java:718
    ("SANCTU_MANI", 50, 0x702, 0xFF),  # Constants.java:719
    ("VIEDA", 55, 0x200, 0x05),  # Constants.java:720
    ("EXCUUN", 60, 0x200, 0x02),  # Constants.java:721
    ("SURMANDUM", 65, 0x200, 0xFF),  # Constants.java:722
    ("ZXKUQYB", 70, 0x200, 0x02),  # Constants.java:723
    ("ANJU_SERMANI", 75, 0x200, 0xFF),  # Constants.java:724
]

# Java declaration order: EXCUUN (M, Constants.java:721) precedes
# SURMANDUM (N, :722), which precedes ZXKUQYB (O, :723) — the walk
# interleaves them in that order even though the GBC menu lists ZXKUQYB
# directly after EXCUM.
_CLERIC_COMBAT_JAVA = ["PONTORI", "SANCTU", "ALCORT", "SANCTU_MANI", "EXCUUN", "SURMANDUM", "ZXKUQYB", "ANJU_SERMANI"]
_WIZARD_COMBAT_JAVA = [
    "REPOND", "MITTAR", "FULGAR", "MENTAR", "PABULUM", "FAL_DIVI",
    "NOXUM", "DECORP", "ALTAIR", "DAG_MENTAR", "NECORP", "UNSPEAKABLE",
]


def test_spell_enum_masks_match_java_every_row():
    """Every Spell row's cost/castable_mask/location_mask equals Java's
    Constants.java:693-724 — name AND declaration order included (the
    declaration order drives getCastables' letter assignment)."""
    got = [(s.name, s.cost, s.castable_mask, s.location_mask) for s in Spell]
    assert got == _JAVA_SPELLS


@pytest.mark.parametrize("context", ["combat", "world", "city", "dungeon"])
@pytest.mark.parametrize("discipline", ["cleric", "wizard"])
def test_context_matrix_equals_java_mask_walk(context, discipline):
    """Full-MP matrix: get_castables == the independent Java-mask walk
    (Constants.java:751-762) for every context x discipline cell — no
    hard-coded spell list: the expectation is recomputed from the enum
    attributes, so an enum edit moves the expectation."""
    prof = Profession.CLERIC if discipline == "cleric" else Profession.WIZARD
    caster = _cleric(99) if discipline == "cleric" else _wizard(99)
    got = get_castables(caster, context, discipline, cheats_ok=False)
    expected = _recompute(prof, context, 99, discipline=discipline)
    assert [(l, s.name) for l, s in got] == [(l, s.name) for l, s in expected]


def test_gbc_cleric_battle_delta_surmandum_anju_governed_by_java():
    """Cleric combat: the Java mask walk offers 8 (SURMANDUM, ANJU_SERMANI
    both 0xff-location per Constants.java:722,724) — the GBC battle menu
    (clericspellsdat, battle.c:127) offers only 6, with the SURMANDUM and
    ANJU_SERMANI rows commented out; getmenuselection(6, clericspellsdat,
    ...) at battle.c:1042 confirms the count. RULING: Java's list governs
    the letters; the GBC omission is its own menu curation."""
    names = [s.name for _, s in get_castables(_cleric(99), "combat", "cleric", cheats_ok=False)]
    assert names == _CLERIC_COMBAT_JAVA
    # the GBC delta items are offered per Java (absent on GBC)
    assert "SURMANDUM" in names
    assert "ANJU_SERMANI" in names
    assert len(names) == 8  # Java walk vs GBC's 6 (battle.c:1042)


def test_gbc_wizard_battle_delta_pabulum_governed_by_java():
    """Wizard combat: the Java mask walk offers 12 — the GBC battle menu
    (wizardspellsdat, battle.c:191) offers only 11, omitting PABULUM
    (Constants.java:701, 0xff location, feeds-the-many); getmenuselection(
    11, wizardspellsdat, ...) at battle.c:1222 confirms the count, and the
    GBC's 'p)' slot there is a XXXXXXX filler for the multi-death-bolt.
    RULING: Java's list governs; also DAG_ACRON (world-only,
    Constants.java:699) must never appear in a combat list."""
    names = [s.name for _, s in get_castables(_wizard(99), "combat", "wizard", cheats_ok=False)]
    assert names == _WIZARD_COMBAT_JAVA
    # the GBC delta item is offered per Java (absent on GBC); it takes
    # letter E, shifting FAL_DIVI to F and NOXUM to G vs the GBC menu's
    # FALDIVI=E / NOXUM=F (battle.c:191 table order)
    letters = {s.name: l for l, s in get_castables(_wizard(99), "combat", "wizard", cheats_ok=False)}
    assert letters["PABULUM"] == "E"
    assert letters["FAL_DIVI"] == "F"
    assert letters["NOXUM"] == "G"
    assert len(names) == 12  # Java walk vs GBC's 11 (battle.c:1222)
    assert "DAG_ACRON" not in names  # world-only mask (Constants.java:699)


def test_fal_divi_cleric_reentry_context_unchanged():
    """FAL_DIVI's mid-combat cleric re-entry (D4) sits on top of this walk:
    the wizard combat walk per discipline still lists FAL_DIVI (Java
    Constants.java:702 keeps it 0xff) and the cleric walk itself is not
    perturbed by it — the two discipline walks are independent calls."""
    wiz = get_castables(_wizard(99), "combat", "wizard", cheats_ok=False)
    assert "FAL_DIVI" in [s.name for _, s in wiz]
    cle = get_castables(_cleric(99), "combat", "cleric", cheats_ok=False)
    assert "FAL_DIVI" not in [s.name for _, s in cle]


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
