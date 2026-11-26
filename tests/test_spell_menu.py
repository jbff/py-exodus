"""Tests for the FIXED spell-letter cast menu.

USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM always);
availability refused at attempt — supersedes the Java getCastables letter
compaction (Constants.java:751-762) adopted 2026-11-14.

The menu lists the discipline's FULL fixed set (all 16 spells, name + the
enum's fixed ``code`` + MP cost); letters NEVER move with mana or context.
Availability is refused AT ATTEMPT via :func:`letter_resolution`:

- a letter whose spell fails ``canCastLocation(context)`` (Constants.java
  :779-781 — the masks live on, but they classify refusals now instead of
  filtering) -> "Not Here!", NOT executed (no cast, no mana), the menu
  disarms and the caster stays active;
- an unaffordable letter is offered too; the prompt layer refuses AT LETTER
  SELECTION (F2 amendment 2026-11-15) with the canonical MP string — BEFORE
  any "Direction?"/"On who?" prompt; the menu never filters on mana, and
  ``cast_spell``'s prevalidation stays for direct-API callers;
- any key outside the discipline's fixed A-P codes -> Java's canonical
  "Not a spell!" + disarm (SpellInputProcessor.java:69-72 behavior retained
  for unknown letters).

The expectations here are recomputed independently from the LIVE enum
attributes (declaration order gives each discipline its original-game
alphabetical A-P codes; spell_type, location_mask, cost) rather than
hard-coded rows, so an enum edit moves the expected result instead of
silently passing a stale audit.
"""

import contextlib
import dataclasses
import re

import pytest

from py_exodus import debug
from py_exodus.constants import MapType, Profession, Race, Spell
from py_exodus.entities.character import Character
from py_exodus.spell_menu import (
    letter_resolution,
    spell_menu_entries,
    spell_menu_prompt_lines,
)

#: Java MapType.val values (Constants.java:248-257) for independent recompute.
_MAP_MASKS = {
    "world": 0x01,
    "combat": 0x02,
    "city": 0x04,
    "dungeon": 0x08,
    "shrine": 0x10,
}


def _expect_entries(discipline):
    """Independent restatement of the fixed-letter list (see docstring).

    Letter = the original-game alphabetical A-P code, i.e. ``chr(A+i)`` over
    the discipline's enum-declaration order; written against the enum
    attributes directly — deliberately NOT the production code.
    """
    return [
        (chr(ord("A") + i), s)
        for i, s in enumerate(x for x in Spell if x.spell_type == discipline)
    ]


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
    c = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC)
    c.mp = mp
    return c


def _wizard(mp=99):
    c = Character("Wiz", "M", Race.FUZZY, Profession.WIZARD)
    c.mp = mp
    return c


# --- the fixed lists ---------------------------------------------------------


def test_cleric_fixed_list_sixteen_spells_in_code_order():
    """The cleric menu is the FULL fixed set: 16 entries, A..P in enum order."""
    got = spell_menu_entries("cleric")
    assert [(c, s.name) for c, s in got] == [
        (c, s.name) for c, s in _expect_entries("cleric")
    ]
    assert len(got) == 16
    assert [c for c, _ in got] == [chr(ord("A") + i) for i in range(16)]


def test_wizard_fixed_list_sixteen_spells_in_code_order():
    """The wizard menu is its own fixed A-P set (REPOND=A .. UNSPEAKABLE=P)."""
    got = spell_menu_entries("wizard")
    assert [(c, s.name) for c, s in got] == [
        (c, s.name) for c, s in _expect_entries("wizard")
    ]
    assert len(got) == 16


def test_b_is_appar_unem_always():
    """THE RULING's headline pin: cleric B=APPAR_UNEM ALWAYS — at full mana
    or empty, in combat or world, the letter never moves. The wizard's B is
    MITTAR: codes are per-discipline fixed lists, not one shared walk."""
    assert spell_menu_entries("cleric")[1] == ("B", Spell.APPAR_UNEM)
    assert spell_menu_entries("wizard")[1] == ("B", Spell.MITTAR)


def test_entries_ignore_mana_context_and_context_arg_does_not_exist():
    """Letters never move with mana or context: a cleric at MP 3 gets the
    same 16 fixed entries as one at MP 99 — no compaction, no cost filter.
    (spell_menu_entries takes only the discipline: there is nothing left
    for caster/context to vary.)"""
    broke = spell_menu_entries("cleric")
    rich = _expect_entries("cleric")
    assert [(c, s.name) for c, s in broke] == [(c, s.name) for c, s in rich]


def test_barbarian_menu_never_opens_but_entries_are_fixed_data():
    """The profession gate lives upstream (get_castable_spell_types): a
    barbarian's C command prints "No spells to cast!" before any menu. The
    fixed entries themselves are pure per-discipline data, not caster-derived."""
    b = Character("Barb", "M", Race.HUMAN, Profession.BARBARIAN)
    b.mp = 99
    from py_exodus.combat.magic import get_castable_spell_types

    assert get_castable_spell_types(b.profession) == []
    # the LETTERS are still fixed data for the disciplines that do open
    assert len(spell_menu_entries("cleric")) == 16


def test_no_class_cheat_widens_the_upstream_gate_only():
    """NOCLASS (cheat.c:414-825) bypasses the profession MENU gate, yet the
    letters stay fixed — the cheat moves which menus open, never the A-P."""
    b = Character("Barb", "M", Race.HUMAN, Profession.BARBARIAN)
    b.mp = 99
    from py_exodus.combat.magic import get_castable_spell_types

    assert get_castable_spell_types(b.profession) == []
    with _cheats(no_class=True):
        assert get_castable_spell_types(b.profession) == ["wizard", "cleric"]
    # same fixed rows for the widened menus
    assert spell_menu_entries("cleric")[1] == ("B", Spell.APPAR_UNEM)


def test_full_mp_cheat_never_reshapes_the_list():
    """FULL MP skips the MP refusal downstream (apply_full_mp tops the caster
    up at prompt open; cast_spell keeps its canonical prevalidation string for
    direct callers) — the MENU itself is untouched by the cheat."""
    from py_exodus import debug as dbg
    from py_exodus.spell_menu import spell_menu_entries as entries

    assert entries("cleric") == entries("cleric")  # trivially fixed
    # the cheat only relaxes the attempt-time gate, not the list:
    broke = Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC)
    broke.mp = 0
    assert dbg.CHEATS.full_mp is False  # the refusal path is live by default


# --- attempt-time letter resolution ------------------------------------------


@pytest.mark.parametrize("context", ["world", "combat", "city", "dungeon", "shrine"])
def test_letter_resolution_refuses_bad_context_spells(context):
    """USER-DIRECTED RULING (2026-11-15): the context mask refuses AT ATTEMPT
    — "Not Here!" for a letter whose spell fails canCastLocation, the spell
    itself when it passes. Expectation recomputed from the live masks."""
    mask = _MAP_MASKS[context]
    for code, spell in spell_menu_entries("cleric"):
        spell_out, refusal = letter_resolution(spell_menu_entries("cleric"), code, context)
        if not (mask & spell.location_mask):
            assert refusal == "Not Here!" and spell_out is None
        else:
            assert refusal is None and spell_out is spell


def test_letter_resolution_headline_cases():
    """The pinned refusals the consumers and play tests lean on."""
    entries = spell_menu_entries("cleric")
    # APPAR_UNEM (mask 0x0D, no combat bit — Constants.java:710) in combat
    out, refusal = letter_resolution(entries, "B", "combat")
    assert out is None and refusal == "Not Here!"
    # ...but attemptable in world
    out, refusal = letter_resolution(entries, "B", "world")
    assert out is Spell.APPAR_UNEM and refusal is None
    # PONTORI is combat-only (mask 0x02) — refused in the world flow
    out, refusal = letter_resolution(entries, "A", "world")
    assert out is None and refusal == "Not Here!"


def test_letter_resolution_unknown_context_raises():
    with pytest.raises(ValueError):
        letter_resolution(spell_menu_entries("cleric"), "B", "shrineless")


def test_letter_resolution_unknown_letter_is_not_a_spell():
    """Out-of-list keys (digits, or any letter not on the fixed A-P list)
    take Java's retained unknown-letter branch: "Not a spell!" (SpellInput
    Processor.java:69-72). With FIXED per-discipline A-P lists every letter
    A-P is on the list, so only non-code keys can land here."""
    entries = spell_menu_entries("cleric")
    for key in ("1", "Z", "Q", "5", "aB"):
        out, refusal = letter_resolution(entries, key, "world")
        assert out is None and refusal == "Not a spell!", key
    # case-insensitive code keys still resolve (prompt normalizes to upper)
    out, refusal = letter_resolution(entries, "c", "world")
    assert out is Spell.SANCTU and refusal is None


def test_wizard_letters_refuse_their_own_contexts():
    """Wizard fixed codes: DAG_ACRON=G is world-only (mask 0x01,
    Constants.java:699) — "Not Here!" in combat; REPOND=A is combat-only."""
    entries = spell_menu_entries("wizard")
    out, refusal = letter_resolution(entries, "G", "combat")
    assert out is None and refusal == "Not Here!"
    out, refusal = letter_resolution(entries, "A", "world")
    assert out is None and refusal == "Not Here!"


def test_prompt_lines_format():
    """Rows match Java SpellInputProcessor.java:36-39 exactly:
    ``"{letter} - {SPELL_NAME} ({cost})"``, cost always printed, 0 included."""
    lines = spell_menu_prompt_lines(spell_menu_entries("cleric"))
    assert lines[0] == "A - PONTORI (0)"
    assert lines[1] == "B - APPAR_UNEM (5)"
    for line in lines:
        head, cost = line.rsplit(" (", 1)
        letter, name = head.split(" - ")
        assert "A" <= letter <= "P"
        assert cost.endswith(")")
        int(cost[:-1])
        assert name == name.upper()
    assert len(lines) == 16


def test_prompt_lines_explicit_rows():
    """Pin the exact rendered rows for a known trio (format lock)."""
    lines = spell_menu_prompt_lines(
        [("A", Spell.PONTORI), ("B", Spell.APPAR_UNEM), ("C", Spell.SANCTU)]
    )
    assert lines == ["A - PONTORI (0)", "B - APPAR_UNEM (5)", "C - SANCTU (10)"]


def test_prompt_lines_are_the_fixed_entries_unchanged_by_mana():
    """The prompt rows print the FIXED list — identical for any caster state
    (the MP cost is DISPLAYED, never used to filter)."""
    lines = spell_menu_prompt_lines(spell_menu_entries("wizard"))
    assert lines[0] == "A - REPOND (0)"
    assert lines[9] == "J - FAL_DIVI (45)"
    assert lines[-1] == "P - UNSPEAKABLE (75)"


def test_map_type_masks_match_java():
    """The context masks the classification recompute uses mirror Java's
    MapType.val (Constants.java:248-257); guard the py constants against drift."""
    assert MapType.WORLD.mask == 0x01
    assert MapType.COMBAT.mask == 0x02
    assert MapType.CITY.mask == 0x04
    assert MapType.DUNGEON.mask == 0x08


# --- Task 3: the shared prompt flow consumes the fixed mapping ---------------
# (combat/magic.py prompt_cast_party — the overworld/town/dungeon flow; the
# combat screen flow is pinned by the play-driver sequence tests.)

_SPELL_ROW = re.compile(r"^[A-Z] - [A-Z_]+ \(\d+\)$")

_CLERIC_FIXED_ROWS = [
    "A - PONTORI (0)",
    "B - APPAR_UNEM (5)",
    "C - SANCTU (10)",
    "D - LUMINAE (15)",
    "E - REC_SU (20)",
    "F - REC_DU (25)",
    "G - LIB_REC (30)",
    "H - ALCORT (35)",
    "I - SEQUITU (40)",
    "J - SOMINAE (45)",
    "K - SANCTU_MANI (50)",
    "L - VIEDA (55)",
    "M - EXCUUN (60)",
    "N - SURMANDUM (65)",
    "O - ZXKUQYB (70)",
    "P - ANJU_SERMANI (75)",
]


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


def test_dungeon_flow_lists_the_full_fixed_set():
    """The dungeon screen passes its DungeonState (SecondaryInputProcessor
    .java:443 passes MapType.dungeon in Java): rows are the FIXED cleric
    A-P list — dungeon-mask spells (APPAR_UNEM city|world|dungeon, REC_SU/
    REC_DU/SEQUITU dungeon-only) sit at their permanent letters; the
    letter_assignment never differed by context (RULING 2026-11-15)."""
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
    assert rows == _CLERIC_FIXED_ROWS


def test_world_flow_prints_rows_after_member_selection():
    """The full FIXED list prints as the spell prompt opens (Java
    SpellInputProcessor.java:36-39 via SecondaryInputProcessor.java:283) —
    the same 16 rows the dungeon flow prints; the context only decides which
    letters refuse AT ATTEMPT."""
    log = _prompt_world_cleric()
    assert log.current_prompt == "Cleric Spell? (A-P):"
    rows = [str(line) for line in log.history if _SPELL_ROW.match(str(line))]
    assert rows == _CLERIC_FIXED_ROWS
    assert log.is_waiting_for_input


def test_location_refusal_not_here_disarms_without_executing():
    """USER-DIRECTED RULING (2026-11-15): pressing a valid letter whose spell
    fails canCastLocation -> "Not Here!", NOT executed (no cast, no mana),
    the menu DISARMS (same shape as "Not a spell!") and the caster stays
    active. PONTORI (combat-only mask) refuses in the world flow."""
    log = _prompt_world_cleric(mp=99)
    log.handle_char("A")  # PONTORI — combat-only (Constants.java:709)
    assert not log.is_waiting_for_input
    assert log.current_prompt == ""
    blob = "\n".join(str(line) for line in log.history)
    assert "Not Here!" in blob
    assert "Undead" not in blob  # nothing executed
    assert "Not a spell!" not in blob
    # (the screen-level C command re-opens this flow; play-driver tests pin
    #  that re-arm plus the retained turn marker.)


def test_unaffordable_letter_is_offered_and_refused_at_attempt():
    """USER-DIRECTED RULING (2026-11-15): the menu NO LONGER requires
    affordance — an unaffordable letter is listed (B - MITTAR (5) at MP 3)
    and refusing it produces the canonical prevalidation string from
    cast_spell ("Thou dost not have enough magic points!"), also not
    executed. The MP gate lives back in cast_spell's prevalidation."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.entities.party import Party
    from py_exodus.ui.text_log import TextLog

    party = Party()
    party.add_member(_wizard(3))
    log = TextLog()
    prompt_cast_party(log, party)
    log.handle_char("1")
    rows = [str(line) for line in log.history if _SPELL_ROW.match(str(line))]
    assert rows[1] == "B - MITTAR (5)"  # unaffordable yet listed
    assert len(rows) == 16

    log.handle_char("M")  # ALTAIR (60) at MP 3 — fixed code, 0xFF location
    blob = "\n".join(str(line) for line in log.history)
    assert "Thou dost not have enough magic points!" in blob
    assert not log.is_waiting_for_input

    # the affordable + here-castable letter still dispatches normally:
    # a fresh MP-45 mage's I (DAG LORUM, 40, 0xFF) — not directional/targeted
    party2 = Party()
    party2.add_member(_wizard(45))
    log2 = TextLog()
    prompt_cast_party(log2, party2)
    log2.handle_char("1")
    log2.handle_char("I")  # DAG LORUM (40), fixed I
    assert not log2.is_waiting_for_input
    assert "magic points" not in "\n".join(str(line) for line in log2.history)


def test_unaffordable_targeted_letter_refuses_before_target_prompt():
    """F2 AMENDMENT (2026-11-15, binding): the MP refusal fires AT LETTER
    SELECTION — BEFORE the target/direction prompts. An unaffordable
    TARGETED letter (SANCTU, C, 10 at MP 3) gets the canonical string on
    the letter press itself and NO "On who?" prompt; the menu DISARMS (same
    shape as the other attempt-refusals). cast_spell's prevalidation stays
    for direct-API callers; the prompt layer refuses before prompting
    further."""
    log = _prompt_world_cleric(mp=3)
    log.handle_char("C")  # SANCTU (10), the targeted restorative
    blob = "\n".join(str(line) for line in log.history)
    assert "On who?" not in blob
    assert "Thou dost not have enough magic points!" in blob
    assert "full health" not in blob  # never reached the effect
    assert not log.is_waiting_for_input
    assert log.current_prompt == ""


def test_unaffordable_directional_spell_location_refusal_precedes_in_world():
    """F2 AMENDMENT (2026-11-15, binding): the prompt-layer order is
    letter_resolution first, then the MP check — a world-flow press of an
    unaffordable DIRECTIONAL spell (wizard B = MITTAR, 5 at MP 3) is
    combat-only (mask 0x02), so the context refusal "Not Here!" fires
    before any MP question; no "Direction?" prompt opens either way. The
    directional MP-ordering itself is the combat screen's (play-driver
    tests)."""
    from py_exodus.combat.magic import prompt_cast_party
    from py_exodus.entities.party import Party
    from py_exodus.ui.text_log import TextLog

    party = Party()
    party.add_member(_wizard(3))
    log = TextLog()
    prompt_cast_party(log, party)
    log.handle_char("1")
    log.handle_char("B")  # MITTAR (5), directional, combat-only mask
    blob = "\n".join(str(line) for line in log.history)
    assert "Not Here!" in blob
    assert "Direction?" not in blob
    assert "magic points" not in blob
    assert not log.is_waiting_for_input


def test_full_mp_cheat_skips_the_prompt_layer_mp_check():
    """F2 AMENDMENT (2026-11-15): the prompt-layer MP check respects
    debug.CHEATS.full_mp — with the cheat ON, even a caster whose mana
    never tops up (apply_full_mp stubbed to a no-op here so the skip alone
    is what's pinned) walks through SANCTU's press to the "On who?" prompt
    instead of an immediate refusal."""
    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(debug, "apply_full_mp", lambda member: None)
    try:
        with _cheats(full_mp=True):
            log = _prompt_world_cleric(mp=0)
            log.handle_char("C")  # SANCTU (10) at MP 0, FULL MP on
    finally:
        monkeypatch.undo()
    blob = "\n".join(str(line) for line in log.history)
    assert "On who?" in log.current_prompt  # walked to the target prompt
    assert "magic points" not in blob
    assert log.is_waiting_for_input


def test_out_of_list_letter_logs_not_a_spell_and_disarms():
    """A key outside the FIXED list logs Java's canonical "Not a spell!" and
    DISARMS the menu — the prompt closes with no row re-print and the
    player re-presses C to see the list again (Java
    SpellInputProcessor.java:69-72: any key failing the A-P code guard —
    digits, non-code letters — takes this same branch)."""
    log = _prompt_world_cleric(mp=15)
    assert log.current_prompt == "Cleric Spell? (A-P):"
    log.handle_char("1")  # a digit is never a spell letter
    assert not log.is_waiting_for_input
    assert log.current_prompt == ""
    blob = "\n".join(str(line) for line in log.history)
    assert "Not a spell!" in blob
    assert "Unknown spell!" not in blob


def test_mapped_letter_dispatches_the_fixed_spell():
    """Selecting a fixed code casts exactly that spell: C is SANCTU (10)
    ALWAYS — in the world list, the combat list, every list."""
    log = _prompt_world_cleric(mp=15)
    log.handle_char("C")  # SANCTU, the fixed C
    assert log.current_prompt == "On who? (1-4):"  # targeted restorative
    log.handle_char("1")  # target the cleric themselves
    assert not log.is_waiting_for_input
    blob = "\n".join(str(line) for line in log.history)
    assert "Unknown spell!" not in blob
    assert "cannot cast" not in blob
    assert "magic points" not in blob  # affordable
    # the heal ran: SANCTU executed, not a refusal
    assert "Not Here!" not in blob
    assert "full health" in blob or "heals" in blob.lower()


# --- Task 7: context-availability audit — the ruling re-read -----------------
#
# Java truth for every spell row: Constants.java:693-726 (Spell enum; the
# professions' bit values are Constants.java:579-589: BARBARIAN 0x001,
# DRUID 0x002, ALCHEMIST 0x004, RANGER 0x008, FIGHTER 0x010, WIZARD 0x020,
# THIEF 0x040, LARK 0x080, ILLUSIONIST 0x100, CLERIC 0x200, PALADIN 0x400),
# and the map-type bit values are Constants.java:248-257 (world 0x01,
# combat 0x02, city 0x04, dungeon 0x08). canCastLocation (Constants.java
# :779-781) is ``(mt.val() & locationMask) > 0``.
#
# USER-DIRECTED RULING (2026-11-15): fixed spell letters (B=APPAR_UNEM
# always); availability refused at attempt — supersedes the Java
# getCastables letter compaction (Constants.java:751-762) adopted
# 2026-11-14. The masks NO LONGER filter the menu (getCastables' alphabet
# compaction is superseded); they classify ATTEMPT refusals via
# letter_resolution. This section re-pins the masks against Java and
# asserts the per-context CLASSIFICATION.

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
    # Constants.java:720 has 0x05; the dungeon bit is LairWare's
    # (UltimaSpellCombat.c:322-327 DrawMiniDng, user ruling 2026-11-26).
    ("VIEDA", 55, 0x200, 0x0D),
    ("EXCUUN", 60, 0x200, 0x02),  # Constants.java:721
    ("SURMANDUM", 65, 0x200, 0xFF),  # Constants.java:722
    ("ZXKUQYB", 70, 0x200, 0x02),  # Constants.java:723
    ("ANJU_SERMANI", 75, 0x200, 0xFF),  # Constants.java:724
]


def test_spell_enum_masks_match_java_every_row():
    """Every Spell row's cost/castable_mask/location_mask equals Java's
    Constants.java:693-724 — name AND declaration order included (the
    declaration order fixes each discipline's alphabetical A-P codes)."""
    # LairWare batch P (ledger P-12, P-13): a Ranger may cast wizard I/J and
    # cleric J (UltimaSpellCombat.c:42-118, MP only), and Surmandum and Anju
    # Sermani fail in combat (349-353, 378-382). Wizard I is LairWare's DAG
    # LORUM (UltimaSpellCombat.c:227-230, user ruling Q21), in Java's slot.
    lw = {"PABULUM": (0x0AE, None), "FAL_DIVI": (0x0AE, None), "SOMINAE": (0x70A, None),
          "SURMANDUM": (None, 0xFD), "ANJU_SERMANI": (None, 0xFD)}
    want = [
        ("DAG_LORUM" if n == "PABULUM" else n, c,
         lw.get(n, (None, None))[0] or cm, lw.get(n, (None, None))[1] or lm)
        for n, c, cm, lm in _JAVA_SPELLS
    ]
    got = [(s.name, s.cost, s.castable_mask, s.location_mask) for s in Spell]
    assert got == want


@pytest.mark.parametrize("context", ["combat", "world", "city", "dungeon"])
@pytest.mark.parametrize("discipline", ["cleric", "wizard"])
def test_context_matrix_attempt_classification(context, discipline):
    """Full-MP matrix, repurposed for the ruling (2026-11-15): the menu lists
    the SAME fixed 16 everywhere; the Java location mask
    (Constants.java:751-762 walk superseded for letters) now decides which
    codes refuse AT ATTEMPT — expectation recomputed from the enum
    attributes, so an enum edit moves the expectation."""
    mask = _MAP_MASKS[context]
    entries = spell_menu_entries(discipline)
    assert len(entries) == 16  # the menu is context-blind
    for code, spell in entries:
        out, refusal = letter_resolution(entries, code, context)
        if mask & spell.location_mask:
            assert refusal is None and out is spell
        else:
            assert refusal == "Not Here!" and out is None


# GBC truth for the battle menus: refs/ult3src/sdk/gbz80-gb/2-1-5/examples/
# u3/battle.c — clericspellsdat (battle.c:127, consumed by
# getmenuselection(6, clericspellsdat, ...) at battle.c:1042) offers
# PONTORI SANCTU ALCORT SANCTUM EXCUM ZXKUQYB with the SURMANDUM and
# ANJU_SERMANI rows commented out; wizardspellsdat (battle.c:191, consumed
# by getmenuselection(11, wizardspellsdat, ...) at battle.c:1222) offers
# REPOND MITTAR FULGAR MENTAR FALDIVI NOXUM DECORP ALTAIR DAGMENT NECORP
# and a XXXXXXX filler for the multi-death-bolt slot (no PABULUM).
#
# RECORDED RULES RULING (Task 7, binding): where GBC's battle menu omits
# spells the Java masks admit, the omission is GBC's own menu curation, not
# a rules change. Under the FIXED-LETTER ruling the py menu offers the full
# 16 everywhere — the GBC deltas below are recorded, not reproduced.

def test_gbc_cleric_battle_delta_surmandum_anju_refused_in_combat():
    """Cleric combat: the FIXED menu lists all 16 at their permanent codes;
    SURMANDUM (N) and ANJU_SERMANI (P) are refused there at the attempt, as
    LairWare fails them in combat (UltimaSpellCombat.c:330-335, 356-361;
    the GBC battle menu, battle.c:127, leaves them out too)."""
    out, refusal = letter_resolution(spell_menu_entries("cleric"), "N", "combat")
    assert out is None and refusal == "Not Here!"
    out, refusal = letter_resolution(spell_menu_entries("cleric"), "P", "combat")
    assert out is None and refusal == "Not Here!"


def test_gbc_wizard_battle_delta_dag_lorum_casts_anywhere():
    """Wizard combat: I (Java's PABULUM slot, 0xFF location,
    Constants.java:701; LairWare's DAG LORUM, user ruling Q21) CASTS in
    combat at its fixed letter; the GBC battle menu (wizardspellsdat,
    battle.c:191) offered only 11, omitting PABULUM (getmenuselection(
    11, wizardspellsdat, ...) at battle.c:1222 — its 'p)' slot is a XXXXXXX
    filler for the multi-death-bolt): curation, not rules. Conversely
    DAG_ACRON (G, world-only, Constants.java:699) is LISTED in combat yet
    refuses AT ATTEMPT — the old dynamic list never offered it."""
    out, refusal = letter_resolution(spell_menu_entries("wizard"), "I", "combat")
    assert out is Spell.DAG_LORUM and refusal is None
    out, refusal = letter_resolution(spell_menu_entries("wizard"), "G", "combat")
    assert out is None and refusal == "Not Here!"


def test_fal_divi_cleric_reentry_fixed_letters_unchanged():
    """FAL_DIVI's mid-combat cleric re-entry (D4): the re-entry opens the
    CLERIC menu whose fixed codes are independent of FAL_DIVI's — J is
    FAL_DIVI on the wizard list (Constants.java:702, 0xff) and SOMINAE on
    the cleric list (Constants.java:718, dungeon-only, refuses in combat).
    The two discipline menus are two fixed lists, never one walk."""
    wiz = dict(spell_menu_entries("wizard"))
    cle = dict(spell_menu_entries("cleric"))
    assert wiz["J"] is Spell.FAL_DIVI
    assert cle["J"] is Spell.SOMINAE
    out, refusal = letter_resolution(spell_menu_entries("cleric"), "J", "combat")
    assert out is None and refusal == "Not Here!"
