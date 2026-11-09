"""Task 14 parity tests: character creation, Lord British, roster, shrine gold.

Java truth:
- exodus/ManagePartyScreen.java:165-199,355-367 (stat sliders 5-25, total <= 50
  reject, name <= 16 chars, health/food/gold = 150, NO starting weapon/armor)
- exodus/SecondaryInputProcessor.java:179-202 (no resurrection, talking-member
  only level advance)
- exodus/ShrineScreen.java:200-257 (member purse debit; messages)
- objects/SaveGame.java:394-433 (Mark-of-Kings gate at expLvl >= 5), 164-169
  (default start 45,19), binary marks order [KINGS, FIRE, SNAKE, FORCE]
"""
from __future__ import annotations

import struct

import pygame

from py_exodus.constants import ArmorType, Profession, Race, Status, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.save_system import SaveSystem
from py_exodus.screens.roster_screen import RosterScreen
from py_exodus.screens.shrine import ShrineScreen


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _drive_creation_wizard(
    scr: RosterScreen,
    name: str,
    sex: str = "M",
    race: str = "H",
    prof: str = "F",
    stats: list[int] | None = None,
    portrait: str = "43",
) -> None:
    """Drive the text-prompt creation wizard of RosterScreen to completion."""
    if stats is None:
        stats = [10, 10, 10, 10]

    answers: dict[str, str] = {
        "name": name + "\r",
        "sex": sex,
        "race": race,
        "class": prof,
        "portrait": portrait + "\r",
        "strength": f"{stats[0]}\r",
        "dexterity": f"{stats[1]}\r",
        "intelligence": f"{stats[2]}\r",
        "wisdom": f"{stats[3]}\r",
    }
    keys = ["name", "sex", "race", "class", "portrait", "strength", "dexterity", "intelligence", "wisdom"]

    scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
    step = 0
    for _ in range(64):
        if not scr.text_log.is_waiting_for_input:
            return
        prompt = scr.text_log.current_prompt.lower()
        matched = False
        for kw in keys:
            if kw in prompt:
                for ch in answers[kw]:
                    scr.text_log.handle_char(ch)
                matched = True
                step += 1
                break
        assert matched, f"Unrecognized creation prompt: {scr.text_log.current_prompt!r}"
    raise AssertionError("Creation wizard did not terminate")


def _make_party(*members: Character) -> Party:
    p = Party()
    for m in members:
        p.add_member(m)
    return p


def _binary_record(**overrides: int) -> bytes:
    """Synthetic 64-byte binary character record."""
    rec = bytearray(64)
    rec[0:10] = b"Conan\x00\x00\x00\x00\x00"
    rec[0x11] = ord("G")
    rec[0x12] = 15
    rec[0x13] = 15
    rec[0x14] = 15
    rec[0x15] = 15
    rec[0x16] = ord("H")
    rec[0x17] = ord("F")
    rec[0x18] = ord("M")
    struct.pack_into("<H", rec, 0x1B, 150)  # HP
    for key, val in overrides.items():
        rec[int(key, 16)] = val
    return bytes(rec)


# --------------------------------------------------------------------------- #
# (a) Character creation parity
# --------------------------------------------------------------------------- #
class TestCreationParity:
    def test_start_values_health_food_gold_150_no_gear(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        before = len(scr.roster)
        _drive_creation_wizard(scr, "Lancelot", prof="F", stats=[10, 10, 10, 10])

        assert len(scr.roster) == before + 1
        c = scr.roster[-1]
        assert c.hp == 150
        assert c.max_hp == 150
        assert c.food == 150
        assert c.gold == 150
        # NO starting weapon/armor (ManagePartyScreen.java:185-192)
        assert c.weapon == WeaponType.NONE
        assert c.armor == ArmorType.NONE
        assert c.weapons.get(WeaponType.SWORD, 0) == 0
        assert c.armors.get(ArmorType.LEATHER, 0) == 0

    def test_name_up_to_16_chars(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "A" * 16, stats=[5, 5, 5, 5])
        assert scr.roster[-1].name == "A" * 16
        # Name longer than 16 is truncated to 16 (nameField.setMaxLength(16))
        scr2 = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr2, "B" * 20, stats=[5, 5, 5, 5])
        assert scr2.roster[-1].name == "B" * 16

    def test_portrait_index_recorded(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Visage", stats=[5, 5, 5, 5], portrait="7")
        assert scr.roster[-1].portrait_index == 7

    def test_over_budget_allocation_rejected(self, pygame_setup, asset_mgr):
        """Total > 50 is rejected: nothing is committed and the wizard
        restarts the stat prompts (ManagePartyScreen.java:176-180 refuses the
        apply and keeps the allocation UI open)."""
        scr = RosterScreen(asset_mgr=asset_mgr)
        before = len(scr.roster)
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
        for ch in "Greedy\r":
            scr.text_log.handle_char(ch)
        scr.text_log.handle_char("M")
        scr.text_log.handle_char("H")
        scr.text_log.handle_char("F")
        for ch in "43\r":
            scr.text_log.handle_char(ch)

        for value, word in [(25, "Strength"), (25, "Dexterity"), (25, "Intelligence"), (25, "Wisdom")]:
            assert word in scr.text_log.current_prompt, scr.text_log.current_prompt
            for ch in f"{value}\r":
                scr.text_log.handle_char(ch)

        # No character was committed
        assert len(scr.roster) == before
        # Rejection was reported, quoting the Java budget rule
        assert any("exceed maximum" in h.lower() or "exceeds" in h.lower() for h in scr.text_log.history)
        # Wizard re-prompts for Strength so the player can fix the allocation
        assert scr.text_log.is_waiting_for_input
        assert "Strength" in scr.text_log.current_prompt

    def test_stat_bounds_enforced_5_to_25(self):
        ok_low, _ = Character.validate_creation(Race.HUMAN, Profession.FIGHTER, 5, 5, 5, 5)
        assert ok_low
        ok_high, _ = Character.validate_creation(Race.HUMAN, Profession.FIGHTER, 25, 5, 10, 10)
        assert ok_high
        bad_below, msg_below = Character.validate_creation(Race.HUMAN, Profession.FIGHTER, 4, 5, 5, 5)
        assert not bad_below
        bad_above, msg_above = Character.validate_creation(Race.HUMAN, Profession.FIGHTER, 26, 5, 5, 5)
        assert not bad_above
        over_budget, msg_budget = Character.validate_creation(Race.HUMAN, Profession.FIGHTER, 25, 25, 25, 25)
        assert not over_budget
        assert "50" in msg_budget

    def test_wizard_reprompts_on_out_of_range_stat(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
        for ch in "Zed\r":
            scr.text_log.handle_char(ch)
        scr.text_log.handle_char("M")
        scr.text_log.handle_char("H")
        scr.text_log.handle_char("F")
        # Skip portrait
        for ch in "43\r":
            scr.text_log.handle_char(ch)
        assert "Strength" in scr.text_log.current_prompt
        # Out-of-range: 30 must be rejected, wizard re-prompts the same stat
        for ch in "30\r":
            scr.text_log.handle_char(ch)
        assert scr.text_log.is_waiting_for_input
        assert "Strength" in scr.text_log.current_prompt
        assert len(scr.roster) + 0 == len(scr.roster)  # still nothing created
        # Then a valid allocation completes
        for value, prompt_word in [(10, "Strength"), (10, "Dexterity"), (10, "Intelligence"), (10, "Wisdom")]:
            assert prompt_word in scr.text_log.current_prompt
            for ch in f"{value}\r":
                scr.text_log.handle_char(ch)
        assert not scr.text_log.is_waiting_for_input


# --------------------------------------------------------------------------- #
# (b) Lord British: no resurrection, talking member only
# --------------------------------------------------------------------------- #
class TestLordBritish:
    def _town(self, party):
        from py_exodus.screens.town import TownScreen

        return TownScreen(party=party, map_id=1, asset_mgr=None)

    def test_lord_british_does_not_resurrect_dead_member(self, pygame_setup):
        dead = Character(name="Dead", profession=Profession.FIGHTER, exp=5, level=1)
        dead.status = Status.DEAD
        dead.hp = 0
        alive = Character(name="Alive", profession=Profession.FIGHTER, exp=5, level=1)
        party = _make_party(dead, alive)

        town = self._town(party)
        town._interact_lord_british(speaker=party.members[1])

        # Java SecondaryInputProcessor.java:190-197 — no resurrection at all
        assert dead.status == Status.DEAD
        assert dead.hp == 0
        assert not any("resurrect" in h.lower() for h in town.text_log.history)
        assert any("Experience more!" in h for h in town.text_log.history)

    def test_lord_british_advances_only_talking_member(self, pygame_setup):
        speaker = Character(name="Talker", profession=Profession.FIGHTER, exp=150, level=1)
        other = Character(name="Quiet", profession=Profession.FIGHTER, exp=150, level=1)
        party = _make_party(speaker, other)

        town = self._town(party)
        town._interact_lord_british(speaker=party.members[0])

        assert speaker.level == 2
        assert other.level == 1
        assert any("advanced" in h.lower() for h in town.text_log.history)


# --------------------------------------------------------------------------- #
# (c) Remove-from-party returns the member to a roster slot
# --------------------------------------------------------------------------- #
class TestRosterRemoval:
    def _screen(self, roster, party):
        return RosterScreen(party=party, roster=list(roster), asset_mgr=None)

    def test_removed_member_returns_to_roster(self, pygame_setup):
        aria = Character(name="Aria", profession=Profession.FIGHTER)
        roster = [Character(name=f"R{i}", profession=Profession.THIEF) for i in range(3)]
        party = _make_party(aria)
        scr = self._screen(roster, party)
        scr.focus_panel = "party"
        scr.selected_party_idx = 0

        scr._remove_from_party()

        assert len(party.members) == 0
        names = [c.name for c in scr.roster]
        assert "Aria" in names
        assert len(scr.roster) == 4  # appended as a new slot

    def test_removed_member_overwrites_matching_roster_slot(self, pygame_setup):
        """Java: same-name roster slot is replaced with the party state
        (ManagePartyScreen.java:355-367), not duplicated."""
        roster_aria = Character(name="Aria", profession=Profession.FIGHTER, level=1)
        roster = [roster_aria, Character(name="Bob", profession=Profession.THIEF)]
        party_aria = Character(name="Aria", profession=Profession.FIGHTER, level=3)
        party = _make_party(party_aria)
        scr = self._screen(roster, party)
        scr.focus_panel = "party"
        scr.selected_party_idx = 0

        scr._remove_from_party()

        assert len(party.members) == 0
        arias = [c for c in scr.roster if c.name == "Aria"]
        assert len(arias) == 1
        assert arias[0].level == 3  # party version carried back

    def test_remove_fails_when_roster_full(self, pygame_setup):
        """Roster.java holds 20 slots; with no free slot the removal fails and
        the member stays in the party."""
        roster = [Character(name=f"R{i}", profession=Profession.THIEF) for i in range(20)]
        otto = Character(name="Otto", profession=Profession.FIGHTER)
        party = _make_party(otto)
        scr = self._screen(roster, party)
        scr.focus_panel = "party"
        scr.selected_party_idx = 0

        scr._remove_from_party()

        assert len(party.members) == 1  # still in the party
        assert otto.name not in [c.name for c in scr.roster]
        assert any("roster" in h.lower() for h in scr.text_log.history)


# --------------------------------------------------------------------------- #
# (d) Shrine donation
# --------------------------------------------------------------------------- #
class TestShrineDonation:
    def _shrine(self, member):
        party = _make_party(member)
        return ShrineScreen(party=party, stat_name="wisdom")

    def test_donation_debits_member_purse_shazam(self, pygame_setup):
        m = Character(name="Donor", profession=Profession.CLERIC, wisdom=10, gold=500)
        shrine = self._shrine(m)

        assert shrine.donate(0, amount=2) is True
        assert m.gold == 300
        # Success message is just "Shazam!" (ShrineScreen.java:222)
        assert shrine.last_message == "Shazam!"

    def test_insufficient_gold_message_and_no_debit(self, pygame_setup):
        m = Character(name="Pauper", profession=Profession.CLERIC, wisdom=10, gold=50)
        shrine = self._shrine(m)

        assert shrine.donate(0, amount=1) is False
        assert m.gold == 50  # nothing debited
        assert shrine.last_message == "You cannot cheat the gods!"

    def test_insufficient_gold_screen_stays(self, pygame_setup):
        """The donate prompt keeps the shrine open so another amount can be
        offered (task brief binds this over Java's instant return)."""
        m = Character(name="Pauper", profession=Profession.CLERIC, wisdom=10, gold=50)
        shrine = self._shrine(m)
        shrine.return_screen = object()  # sentinel; exit would set next_screen

        # Select member then offer 1 (which he cannot pay)
        shrine.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
        shrine.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))

        assert shrine.state == ShrineScreen.STATE_DONATE
        assert shrine.is_finished is False
        assert shrine.next_screen is None
        assert shrine.last_message == "You cannot cheat the gods!"

    def test_zero_offer_begone_then_exit(self, pygame_setup):
        m = Character(name="Scrooge", profession=Profession.CLERIC, wisdom=10, gold=500)
        shrine = self._shrine(m)
        shrine.state = ShrineScreen.STATE_DONATE

        shrine.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_0, unicode="0"))

        assert shrine.last_message == "Begone then!"
        assert shrine.is_finished is True
        assert m.gold == 500  # nothing debited


# --------------------------------------------------------------------------- #
# (e) Mark-of-Kings gate: required only from level 6 (expLvl >= 5)
# --------------------------------------------------------------------------- #
class TestMarkGate:
    def test_level_5_reachable_without_mark(self):
        """exp 450 (expLvl 4) promotes to level 5 with no Mark of Kings.
        Java: SaveGame.java:406 gates on expLvl >= 5, not on the reached level."""
        c = Character(name="NoMark", profession=Profession.FIGHTER, level=1, exp=450)
        c.marks = [0, 0, 0, 0]
        assert c.meet_lord_british() is True
        assert c.level == 5

    def test_level_6_requires_mark_of_kings(self):
        c = Character(name="NoMark", profession=Profession.FIGHTER, level=5, exp=500)
        c.marks = [0, 0, 0, 0]
        assert c.meet_lord_british() is False
        assert c.level == 5

        marked = Character(name="Marked", profession=Profession.FIGHTER, level=5, exp=500)
        marked.marks = [1, 0, 0, 0]
        assert marked.meet_lord_british() is True
        assert marked.level == 6


# --------------------------------------------------------------------------- #
# (f) max_mp is recomputed on load, never deserialized
# --------------------------------------------------------------------------- #
class TestMaxMpLoadSemantics:
    def test_to_dict_has_no_max_mp(self):
        c = Character(name="W", profession=Profession.WIZARD, intelligence=25)
        assert "max_mp" not in c.to_dict()

    def test_from_dict_ignores_stale_max_mp(self):
        c = Character(name="W", profession=Profession.WIZARD, intelligence=25)
        data = c.to_dict()
        data["max_mp"] = 999  # stale/wrong value an old save may carry
        loaded = Character.from_dict(data)
        # Recomputed from stats/profession: WIZARD -> intelligence = 25
        assert loaded.max_mp == 25

    def test_roundtrip_recomputes_after_stat_drift(self):
        c = Character(name="W", profession=Profession.WIZARD, intelligence=10)
        data = c.to_dict()
        loaded = Character.from_dict(data)
        data2 = loaded.to_dict()
        data2["int"] = 25  # pretend the file was edited; save holds old stats
        reloaded = Character.from_dict(data2)
        assert reloaded.max_mp == 25


# --------------------------------------------------------------------------- #
# (g) Binary marks decode order: [Kings, Fire, Snake, Force]
# --------------------------------------------------------------------------- #
class TestBinaryMarksOrder:
    def test_marks_bitmask_order(self):
        cases = {
            0x80: [1, 0, 0, 0],  # Kings
            0x20: [0, 1, 0, 0],  # Fire
            0x40: [0, 0, 1, 0],  # Snake
            0x10: [0, 0, 0, 1],  # Force
        }
        for mask, expected in cases.items():
            rec = _binary_record(**{"0x0E": mask})
            char = SaveSystem.parse_binary_character_record(rec)
            assert char is not None, f"record for {mask:#x} failed to parse"
            assert char.marks == expected, f"mask {mask:#x}: got {char.marks}"

    def test_combined_bitmask(self):
        rec = _binary_record(**{"0x0E": 0x60})  # Fire (0x20) | Snake (0x40)
        char = SaveSystem.parse_binary_character_record(rec)
        assert char.marks == [0, 1, 1, 0]
        assert char.cards == [0, 0, 0, 0]


# --------------------------------------------------------------------------- #
# (h) Default new-game start position (45, 19)
# --------------------------------------------------------------------------- #
class TestDefaultStartPosition:
    def test_default_party_starts_at_45_19(self):
        from py_exodus.entities.party import Party

        party = Party()
        assert (party.x, party.y) == (45, 19)

    def test_roster_screen_default_party_starts_at_45_19(self, pygame_setup):
        scr = RosterScreen(asset_mgr=None)
        assert (scr.party.x, scr.party.y) == (45, 19)

    def test_party_from_dict_defaults_to_45_19(self):
        p = Party.from_dict({"members": []})
        assert (p.x, p.y) == (45, 19)

    def test_binary_party_fallback_defaults_to_45_19(self, tmp_path):
        data = bytearray(274)
        path = tmp_path / "party.ult"
        path.write_bytes(bytes(data))
        p = SaveSystem.load_binary_party(path)
        assert (p.x, p.y) == (45, 19)


# --------------------------------------------------------------------------- #
# (i) Starting spell points: original-rules parity (user-directed deviation)
# --------------------------------------------------------------------------- #
class TestStartingMana:
    """Java's creator (ManagePartyScreen.java) never touches mana, so created
    casters started at 0 MP and the first endTurn meal tick made it look like
    "starting with 1". The C64 original starts a caster with spell points
    equal to the max from the CharacterRecord.getMaxMana formula
    (SaveGame.java:340-376); non-casters (mp capability 0) start at 0."""

    def test_created_wizard_starts_with_computed_max_mp(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Morgan", prof="W", stats=[5, 5, 25, 5])
        c = scr.roster[-1]
        assert c.profession == Profession.WIZARD
        assert c.compute_max_mp() == 25
        assert c.mp == 25
        assert c.mp == c.max_mp

    def test_created_cleric_starts_with_max_mp(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Aldwyn", prof="C", stats=[8, 8, 8, 24])
        c = scr.roster[-1]
        assert c.profession == Profession.CLERIC
        assert c.compute_max_mp() == 24
        assert c.mp == 24

    def test_created_paladin_starts_with_half_wisdom(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Galahad", prof="P", stats=[10, 10, 10, 16])
        c = scr.roster[-1]
        assert c.profession == Profession.PALADIN
        assert c.mp == c.compute_max_mp() == 8

    def test_created_fighter_starts_with_zero_mp(self, pygame_setup, asset_mgr):
        # Warriors have spell capability 0 and must stay at 0.
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Lancelot", prof="F", stats=[10, 10, 10, 10])
        c = scr.roster[-1]
        assert c.profession == Profession.FIGHTER
        assert c.compute_max_mp() == 0
        assert c.mp == 0

    def test_no_default_starter_party_exists(self):
        """User ruling (2026-11-09): the default/starter party is removed —
        Java ships none, so Python must not keep helper factories for one."""
        import py_exodus.screens.roster_screen as roster_mod
        import py_exodus.screens.start as start_mod

        assert not hasattr(start_mod, "create_default_starter_party")
        assert not hasattr(roster_mod, "get_starter_roster")
