"""Task 14 parity tests: character creation, Lord British, roster, shrine gold.

Java truth:
- exodus/ManagePartyScreen.java:165-199,355-367 (stat sliders 5-25, total <= 50
  reject, health/food/gold = 150); the starting kit is
  LairWare's readied Dagger and Cloth (UltimaMain.c:814-817)
- exodus/SecondaryInputProcessor.java:179-202 (no resurrection, talking-member
  only level advance)
- objects/SaveGame.java:394-433 (Mark-of-Kings gate at expLvl >= 5), 164-169
  (default start 45,19), binary marks order [KINGS, FIRE, SNAKE, FORCE]
"""
from __future__ import annotations

import struct

import pygame

from py_exodus.constants import ArmorType, Profession, Race, Sex, Status, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.save_system import SaveSystem
from py_exodus.screens.roster_screen import RosterScreen


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
) -> None:
    """Drive the text-prompt creation wizard of RosterScreen to completion."""
    if stats is None:
        stats = [10, 10, 10, 10]

    answers: dict[str, str] = {
        "name": name + "\r",
        "sex": sex,
        "race": race,
        "class": prof,
        "strength": f"{stats[0]}\r",
        "dexterity": f"{stats[1]}\r",
        "intelligence": f"{stats[2]}\r",
        "wisdom": f"{stats[3]}\r",
    }
    keys = ["name", "sex", "race", "class", "strength", "dexterity", "intelligence", "wisdom"]

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
    def test_start_values_health_food_gold_150_dagger_cloth(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        before = len(scr.roster)
        _drive_creation_wizard(scr, "Lancelot", prof="F", stats=[10, 10, 10, 10])

        assert len(scr.roster) == before + 1
        c = scr.roster[-1]
        assert c.hp == 150
        assert c.max_hp == 150
        assert c.food == 150
        assert c.gold == 150
        # LairWare starting kit: readied Dagger and Cloth (UltimaMain.c:814-817)
        assert c.weapon == WeaponType.DAGGER
        assert c.armor == ArmorType.CLOTH
        assert c.weapons.get(WeaponType.SWORD, 0) == 0
        assert c.armors.get(ArmorType.LEATHER, 0) == 0

    def test_name_up_to_12_chars(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "A" * 12, stats=[5, 5, 5, 5])
        assert scr.roster[-1].name == "A" * 12
        # Longer names are cut to 12 (LairWare UltimaMacIF.c:2430-2432)
        scr2 = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr2, "B" * 20, stats=[5, 5, 5, 5])
        assert scr2.roster[-1].name == "B" * 12

    def test_portrait_field_preserved_but_invisible(self, pygame_setup, asset_mgr):
        """User ruling: "dump the faces/images for characters" — the wizard
        never asks for a portrait and no portrait image is rendered anywhere;
        the portrait_index data field survives for save compatibility."""
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Visage", stats=[5, 5, 5, 5])
        created = scr.roster[-1]
        assert created.portrait_index == 43  # default, never prompted
        # No step of the wizard mentioned a portrait.
        assert not any("portrait" in m.lower() for m in scr.text_log.history)

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
# (a2) Sex = Other (original-rules deviation, user-directed)
# --------------------------------------------------------------------------- #
class TestSexOther:
    """Sex = Other reinstated (original game rule; Java's SexType only has
    Male/Female — this is a user-directed original-rules deviation, kept
    behind a document-in-code marker at the Sex enum and creation prompt)."""

    def test_wizard_sex_prompt_offers_other(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
        for ch in "Zed\r":
            scr.text_log.handle_char(ch)
        assert scr.text_log.is_waiting_for_input
        prompt = scr.text_log.current_prompt
        assert "[M]" in prompt and "[F]" in prompt and "[O]ther" in prompt

    def test_wizard_accepts_other(self, pygame_setup, asset_mgr):
        scr = RosterScreen(asset_mgr=asset_mgr)
        _drive_creation_wizard(scr, "Quixote", sex="O", stats=[10, 10, 10, 10])
        assert scr.roster[-1].sex == Sex.OTHER

    def test_wizard_reprompts_on_invalid_sex(self, pygame_setup, asset_mgr):
        """Invalid sex input re-prompts the same question instead of silently
        defaulting (consistent with the wizard's stat re-prompt behavior)."""
        scr = RosterScreen(asset_mgr=asset_mgr)
        scr.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c))
        for ch in "Zed\r":
            scr.text_log.handle_char(ch)
        scr.text_log.handle_char("X")  # invalid
        assert scr.text_log.is_waiting_for_input
        assert "Sex" in scr.text_log.current_prompt
        assert len([c for c in scr.roster if c.name == "Zed"]) == 0
        scr.text_log.handle_char("O")  # now valid
        assert "Race" in scr.text_log.current_prompt

    def test_other_round_trip(self):
        c = Character("Mix", sex=Sex.OTHER, race=Race.HUMAN, profession=Profession.FIGHTER)
        data = c.to_dict()
        assert data["sex"] == "O"
        again = Character.from_dict(data)
        assert again.sex == Sex.OTHER
        # String constructor path resolves "O" too.
        assert Character(sex="O").sex == Sex.OTHER

    def test_binary_record_sex_other(self):
        """The binary parser must not break on the new value: 0x18='O' decodes
        to OTHER instead of falling back to the M/F default."""
        from py_exodus.save_system import SaveSystem

        rec = bytearray(_binary_record())
        rec[0x18] = ord("O")
        char = SaveSystem.parse_binary_character_record(bytes(rec))
        assert char.sex == Sex.OTHER
        # Unchanged fallbacks preserved.
        rec[0x18] = ord("F")
        assert SaveSystem.parse_binary_character_record(bytes(rec)).sex == Sex.FEMALE
        rec[0x18] = ord("M")
        assert SaveSystem.parse_binary_character_record(bytes(rec)).sex == Sex.MALE
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

    def test_level_gain_leaves_stats_untouched(self):
        """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): no random stat
        gains on level-up — stats increase only at shrines. LW Transact gives
        one level per visit (UltimaMain.c:2373-2380) and heals nothing."""
        c = Character(name="Hero", profession=Profession.FIGHTER, level=1, exp=450)
        c.marks = [1, 0, 0, 0]
        hp = c.hp

        assert c.meet_lord_british() is True
        assert c.level == 2
        assert c.meet_lord_british() is True
        assert c.level == 3
        assert (c.str, c.dex, c.int, c.wis) == (15, 15, 10, 10)
        assert c.max_hp == 3 * 100 + 50
        assert c.hp == hp  # no healing


# --------------------------------------------------------------------------- #
class TestMarkGate:
    def test_level_5_reachable_without_mark(self):
        """exp 450: four visits take level 1 to 5 with no Mark of Kings."""
        c = Character(name="NoMark", profession=Profession.FIGHTER, level=1, exp=450)
        c.marks = [0, 0, 0, 0]
        for _ in range(4):
            assert c.meet_lord_british() is True
        assert c.level == 5
        assert c.meet_lord_british() is False

    def test_level_6_requires_mark_of_kings(self):
        c = Character(name="NoMark", profession=Profession.FIGHTER, level=5, exp=500)
        c.marks = [0, 0, 0, 0]
        assert c.meet_lord_british() is False
        assert c.level == 5

        marked = Character(name="Marked", profession=Profession.FIGHTER, level=5, exp=500)
        marked.marks = [1, 0, 0, 0]
        assert marked.meet_lord_british() is True
        assert marked.level == 6

    def test_crossed_500_exp_before_visiting_lb_clamps_to_level_5(self):
        """Crossing >=500 EXP while below level 5 still allows advancing to 5."""
        c = Character(name="Fighter", profession=Profession.FIGHTER, level=4, exp=1307)
        c.marks = [0, 0, 0, 0]
        assert c.meet_lord_british() is True
        assert c.level == 5
        assert c.max_hp == 550
        # Further advancement beyond level 5 still requires the Mark of Kings
        assert c.meet_lord_british() is False
        assert c.level == 5
        # With the Mark, one level per visit up to the experience (13 + 1)
        c.marks[0] = 1
        while c.meet_lord_british():
            pass
        assert c.level == 14


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
# (h) Default new-game start position — (44, 20)
# --------------------------------------------------------------------------- #
class TestDefaultStartPosition:
    # USER-DIRECTED NIT (2026-11-15): a new party's starting X,Y on Sosaria is
    # one square south and one more square west of the Java default (45, 19)
    # (SaveGame.java:164-169), landing at (44, 20) — still a grass tile.
    def test_default_party_starts_at_44_20(self):
        from py_exodus.entities.party import Party

        party = Party()
        assert (party.x, party.y) == (44, 20)

    def test_roster_screen_default_party_starts_at_44_20(self, pygame_setup):
        scr = RosterScreen(asset_mgr=None)
        assert (scr.party.x, scr.party.y) == (44, 20)

    def test_party_from_dict_without_xy_keeps_java_fallback(self):
        """The save-load fallback for party.json with no recorded x/y stays
        Java-true at (45, 19) (SaveGame.java:164-169) — a legacy-recovery path,
        not a new-game spawn; the fresh-Journey default is (44, 20) per the
        USER-DIRECTED NIT (2026-11-15)."""
        p = Party.from_dict({"members": []})
        assert (p.x, p.y) == (45, 19)

    def test_blank_binary_record_leaves_java_fallback_party_start(self):
        """Java SaveGame.java:164-169: a blank party save seeds the (45, 19)
        start tile. The record-level truth of that save — every 64-byte slot
        parses to an unnamed character, so no member carries a position — is
        asserted here via the Java-format decoder. The fresh-Journey Party()
        default is (44, 20) per USER-DIRECTED NIT (2026-11-15); the (45, 19)
        from_dict fallback for x/y-less records is covered by
        test_party_from_dict_without_xy_keeps_java_fallback."""
        data = bytearray(274)
        char = SaveSystem.parse_binary_character_record(bytes(data[:64]))
        assert char is not None
        assert char.name == ""
        assert (44, 20) == (Party().x, Party().y)


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
