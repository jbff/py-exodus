"""LairWare parity, batch R (character creation and roster).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "R - Roster".
"""
from __future__ import annotations

import pygame

from py_exodus.constants import ArmorType, Profession, Race, Sex, WeaponType
from py_exodus.entities.character import Character
from py_exodus.save_system import SaveSystem
from py_exodus.screens.roster_screen import RosterScreen


def _create(scr: RosterScreen, name: str, prof: str = "F", stats=(10, 10, 10, 10)) -> None:
    """Drive the roster screen's creation wizard to the end."""
    answers = {
        "name": name + "\r",
        "sex": "M",
        "race": "H",
        "class": prof,
        "strength": f"{stats[0]}\r",
        "dexterity": f"{stats[1]}\r",
        "intelligence": f"{stats[2]}\r",
        "wisdom": f"{stats[3]}\r",
    }
    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
    for _ in range(64):
        if not scr.text_log.is_waiting_for_input:
            return
        prompt = scr.text_log.current_prompt.lower()
        key = next(k for k in answers if k in prompt)
        for ch in answers[key]:
            scr.text_log.handle_char(ch)
    raise AssertionError("creation wizard did not finish")


def test_createchar_starts_with_readied_dagger_and_cloth(pygame_setup, asset_mgr):
    """UltimaMain.c:814-817 (CreateChar):

        Player[player][41] = 1;      // Cloth
        Player[player][40] = 1;      // pre-readied
        Player[player][49] = 1;      // Dagger
        Player[player][48] = 1;      // pre-readied

    Every new character owns one Cloth armour and one Dagger, both readied
    (the port's readied item is held in ``weapon``/``armor``, outside the
    spare-item counts).
    """
    for prof in ("F", "W", "C", "T"):
        scr = RosterScreen(asset_mgr=asset_mgr, roster=[])
        _create(scr, "Kit", prof=prof)
        c = scr.roster[-1]
        assert c.weapon == WeaponType.DAGGER, prof
        assert c.armor == ArmorType.CLOTH, prof
        assert c.weapons[WeaponType.DAGGER] == 0
        assert c.armors[ArmorType.CLOTH] == 0


def test_charactercreatedialog_name_is_at_most_12_letters(pygame_setup, asset_mgr):
    """UltimaMacIF.c:2430-2432 (CharacterCreateDialog, name field):

        if (tempStr[0] > 12) {
            tempStr[0] = 12;

    and UltimaMacIF.c:2492-2496 stores only name bytes 0..11
    (``for (temp = 1; temp < 13; temp++)``). A name is at most 12 letters.
    """
    scr = RosterScreen(asset_mgr=asset_mgr, roster=[])
    _create(scr, "A" * 12)
    assert scr.roster[-1].name == "A" * 12
    _create(scr, "B" * 16)
    assert scr.roster[-1].name == "B" * 12


def test_old_roster_with_long_name_and_no_gear_still_loads(tmp_path):
    """Save compatibility for R-02/R-03 (UltimaMisc.c:709-719 GetRoster reads
    every stored record as is): a roster written before the 12-letter name
    and Dagger/Cloth kit rules loads unchanged, nothing truncated or added."""
    old = Character(
        name="SIXTEENLETTERSXX",
        sex=Sex.FEMALE,
        race=Race.ELF,
        profession=Profession.THIEF,
        strength=15,
        dexterity=25,
        intelligence=5,
        wisdom=5,
        hp=150,
        max_hp=150,
    )
    path = tmp_path / "roster.json"
    SaveSystem.save_roster([old], path)
    (loaded,) = SaveSystem.load_roster(path)
    assert loaded.name == "SIXTEENLETTERSXX"
    assert loaded.weapon == WeaponType.NONE
    assert loaded.armor == ArmorType.NONE
    assert loaded.max_hp == 150


def test_createchar_kit_also_in_batch_and_reset_parties(tmp_path):
    """UltimaMain.c:814-817 (CreateChar), user ruling Q55 (follow LairWare):

        Player[player][41] = 1;      // Cloth
        Player[player][40] = 1;      // pre-readied
        Player[player][49] = 1;      // Dagger
        Player[player][48] = 1;      // pre-readied

    The headless batch party (autoplay/batch.py ``build_party``) and the
    roster written by scripts/reset_new_game.py are new characters too, so
    they start with the same readied Dagger and Cloth as the roster screen's.
    """
    import importlib.util
    from pathlib import Path

    from py_exodus.autoplay import batch

    for m in batch.build_party().members:
        assert m.weapon == WeaponType.DAGGER, m.name
        assert m.armor == ArmorType.CLOTH, m.name

    script = Path(__file__).resolve().parent.parent / "scripts" / "reset_new_game.py"
    spec = importlib.util.spec_from_file_location("reset_new_game", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.reset_new_game(tmp_path)
    roster = SaveSystem.load_roster(tmp_path / "roster.json")
    assert len(roster) == 4
    for c in roster:
        assert c.weapon == WeaponType.DAGGER, c.name
        assert c.armor == ArmorType.CLOTH, c.name


# --- R-14 (user ruling Q4): a record is its roster slot, not its name ---------


def _two_same_named():
    a = Character(name="ARIA", profession=Profession.FIGHTER)
    b = Character(name="ARIA", profession=Profession.WIZARD)
    return a, b


def test_formpartydialog_two_same_named_characters_can_join(pygame_setup):
    """UltimaNew.c:157-185, 204-210, 247-250 (FormPartyDialog): the menus list roster
    slots ("1- ARIA", "2- ARIA") and the party stores slot numbers
    (``Party[temp + 6] = sel[i]``); only the same slot twice is refused
    (``sel[temp] == sel[i]``). Two characters with the same name can be in
    one party (user ruling Q4); the port refused the second by name."""
    a, b = _two_same_named()
    scr = RosterScreen(roster=[a, b], asset_mgr=None)
    scr.selected_roster_idx = 0
    scr._add_selected_to_party()
    scr.selected_roster_idx = 1
    scr._add_selected_to_party()
    assert [m.character for m in scr.party.members] == [a, b]
    scr.selected_roster_idx = 1
    scr._add_selected_to_party()  # the same record twice is still refused
    assert len(scr.party.members) == 2


def test_terminatecharacterdialog_removes_the_slot_picked(pygame_setup):
    """UltimaNew.c:60-79, 90-101 (TerminateCharacterDialog): the menu entry
    maps to its slot (``rosNum = menuEntry[i - 2]``) and Terminate clears
    that slot (``Player[rosNum][0] = 0``). With two ARIAs, terminating the
    second removes the second, never the first."""
    a, b = _two_same_named()
    scr = RosterScreen(roster=[a, b], asset_mgr=None)
    scr.selected_roster_idx = 1
    scr._delete_selected_roster()
    scr.text_log.handle_char("Y")
    assert scr.roster == [a]


def test_terminatecharacterdialog_refuses_only_the_member_in_the_party(pygame_setup):
    """UltimaNew.c:74-75: a slot marked in a party (``Player[i][16] != 0``)
    can't be picked for Terminate. Another record with the same name can."""
    a, b = _two_same_named()
    scr = RosterScreen(roster=[a, b], asset_mgr=None)
    scr.selected_roster_idx = 0
    scr._add_selected_to_party()
    scr.selected_roster_idx = 0
    scr._delete_selected_roster()
    assert not scr.text_log.is_waiting_for_input  # refused, no Y/N asked
    assert scr.roster == [a, b]
    scr.selected_roster_idx = 1
    scr._delete_selected_roster()
    scr.text_log.handle_char("Y")
    assert scr.roster == [a]


def test_roster_slots_persist_and_old_saves_get_them(pygame_setup, tmp_path):
    """Save compatibility for Q4: every roster record keeps a slot number
    (LairWare's Player[1..20] index). A roster saved before slots existed
    loads, and the roster screen numbers its records 1, 2, ... in order; a
    new character takes the lowest free slot."""
    import json

    a, b = _two_same_named()
    legacy = []
    for c in (a, b):
        d = c.to_dict()
        d.pop("roster_slot", None)
        legacy.append(d)
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(legacy))  # a bare pre-envelope roster list
    old = SaveSystem.load_roster(path)
    assert [c.roster_slot for c in old] == [0, 0]

    scr = RosterScreen(roster=old, asset_mgr=None)
    assert [c.roster_slot for c in scr.roster] == [1, 2]
    again = Character.from_dict(scr.roster[1].to_dict())
    assert again.roster_slot == 2

    scr.roster.pop(0)
    _create(scr, "NEW")
    assert scr.roster[-1].roster_slot == 1


def test_old_party_members_link_to_their_records_by_name_once(pygame_setup):
    """Save compatibility for Q4: a party saved before roster slots has
    members with no slot; each takes the slot of the one roster record of
    its name, so it is still that record (and two same-named records are
    never guessed between)."""
    from py_exodus.entities.party import Party
    from py_exodus.screens.roster_screen import same_record

    rec = Character(name="BORS", profession=Profession.FIGHTER)
    twin_a, twin_b = _two_same_named()
    party = Party()
    saved_bors = Character(name="BORS", profession=Profession.FIGHTER, level=3)
    saved_aria = Character(name="ARIA", profession=Profession.FIGHTER)
    party.add_member(saved_bors)
    party.add_member(saved_aria)
    scr = RosterScreen(party=party, roster=[rec, twin_a, twin_b], asset_mgr=None)
    assert same_record(saved_bors, rec)
    assert saved_aria.roster_slot == 0  # ambiguous: left unlinked
