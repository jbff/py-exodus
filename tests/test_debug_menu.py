"""Task 28 (D1): GBC debug/cheat harness tests (GBC cheat.c:414-825).

GBC truth:
- ``cheat.c:439-479`` ``domaxall`` — gold 9999, keys/gems/powders/torches 99,
  currHP/maxHP 9999, markcard 0xFF, magic/dex/str/wis/intel 99, food 9999,
  exp 9999, level 99, armors memset 9, weapons memset 9, and the party
  special-item bits (``party_specials = 0x0F/0x0FFF``).
- ``cheat.c:768-825`` ``docheat`` — an 8-item menu (MUSIC picker omitted in
  the py port; the other 7 map onto the 6 toggles + MAX ALL).
- ``cheatdescdat`` (``cheat.c:77-102``) supplies the GBC description strings
  the menu prints for each item.

The cheat state is runtime-only: nothing may reach a ``to_dict()``/save path
(tested below). The ``--debug`` flag parse is factored into
``py_exodus.__main__.parse_args`` so these tests never boot the game loop.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

import pygame
import pytest

from py_exodus import debug
from py_exodus.__main__ import parse_args
from py_exodus.assets import AssetManager
from py_exodus.combat.magic import get_castable_spell_types, prompt_cast_party
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.ui.renderer import WorldRenderer, can_move_to
from py_exodus.ui.text_log import TextLog
from py_exodus.world.map import GameMap


@pytest.fixture
def text_log() -> TextLog:
    return TextLog(max_lines=100, wrap_width=60)


@pytest.fixture
def cheat_state():
    """Snapshot and restore the module flag + CHEATS singleton around a test."""
    saved = (debug.DEBUG_MODE, dataclasses.replace(debug.CHEATS))
    yield debug.CHEATS
    debug.DEBUG_MODE, state = saved
    for f in dataclasses.fields(debug.CHEATS):
        setattr(debug.CHEATS, f.name, getattr(state, f.name))


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


def make_party() -> Party:
    members = [
        PartyMember(
            Character(
                "Hero",
                "M",
                Race.HUMAN,
                Profession.FIGHTER,
                strength=20,
                dexterity=20,
                hp=100,
            )
        ),
        PartyMember(
            Character(
                "Mage",
                "F",
                Race.ELF,
                Profession.WIZARD,
                strength=15,
                dexterity=20,
                mp=5,
                max_mp=30,
                hp=70,
            )
        ),
    ]
    return Party(members, x=10, y=10, transport=Transport.FOOT)


class TestDebugFlagParse:
    def test_parse_args_debug_flag_sets_true(self) -> None:
        assert parse_args(["--debug"]).debug is True

    def test_parse_args_default_off(self) -> None:
        assert parse_args([]).debug is False

    def test_set_debug_sets_module_flag(self, cheat_state: Any) -> None:
        debug.set_debug(True)
        assert debug.DEBUG_MODE is True
        debug.set_debug(False)
        assert debug.DEBUG_MODE is False


class TestCheatMenu:
    def test_menu_lists_all_eight_items(self, text_log: TextLog, cheat_state: Any) -> None:
        debug.DEBUG_MODE = True
        debug.open_cheat_menu(text_log)
        blob = "\n".join(text_log.history)
        for label in (
            "XRAY",
            "NOFIGHT",
            "NOHURT",
            "NOBLOCK",
            "FULL MP",
            "NOCLASS",
            "PEER",
            "MAXALL",
        ):
            assert label in blob
        # GBC description strings (cheat.c:77-102 cheatdescdat).
        for desc in (
            "SEE THROUGH ANY TILE",
            "AUTO WIN EVERY BATTLE",
            "HP NEVER DECREASES",
            "WALK THROUGH ANY TILE",
            "MP NEVER DECREASES",
            "ANY CHAR CAN CAST ANY SPELL",
            "P SHOWS THE MAP ANYWHERE, NO GEM",
            "MAX OUT EVERYTHING FOR EVERYONE",
        ):
            assert desc in blob
        # MUSIC jukebox is omitted (no track-picker widget; D5 deferral).
        assert "MUSIC" not in blob

    def test_menu_opens_only_in_debug_mode(self, text_log: TextLog, cheat_state: Any) -> None:
        debug.DEBUG_MODE = False
        debug.open_cheat_menu(text_log)
        assert not text_log.is_waiting_for_input
        debug.DEBUG_MODE = True
        debug.open_cheat_menu(text_log)
        assert text_log.is_waiting_for_input

    def test_submenu_digit_toggles_then_resets(self, text_log: TextLog, cheat_state: Any) -> None:
        """Two menu opens: FULL MP on, then off."""
        assert debug.CHEATS.full_mp is False
        debug.DEBUG_MODE = True
        debug.open_cheat_menu(text_log)
        text_log.submit_input("5")
        assert not text_log.is_waiting_for_input
        assert debug.CHEATS.full_mp is True
        debug.open_cheat_menu(text_log)
        text_log.submit_input("5")
        assert debug.CHEATS.full_mp is False

    def test_index_seven_toggles_the_peer_cheat(self, text_log: TextLog, cheat_state: Any) -> None:
        """The port's own cheat (user request 2026-11-26) sits after the six
        GBC toggles; MAXALL moves to 8."""
        party = make_party()
        debug.DEBUG_MODE = True
        debug.open_cheat_menu(text_log, party)
        assert "1-7, 8/M=Max all" in text_log.current_prompt
        text_log.submit_input("7")
        assert debug.CHEATS.free_peer is True
        assert party.members[0].character.gold != 9999
        debug.open_cheat_menu(text_log, party)
        text_log.submit_input("7")
        assert debug.CHEATS.free_peer is False

    def test_max_all_choice_and_index_eight(self, text_log: TextLog, cheat_state: Any) -> None:
        party = make_party()
        debug.DEBUG_MODE = True
        debug.open_cheat_menu(text_log, party)
        text_log.submit_input("8")
        assert party.members[0].character.gold == 9999
        debug.open_cheat_menu(text_log, party)
        text_log.submit_input("M")
        assert party.members[1].character.gold == 9999

    def test_escape_cancels_without_change(self, text_log: TextLog, cheat_state: Any) -> None:
        debug.open_cheat_menu(text_log)
        text_log.handle_escape()
        assert not text_log.is_waiting_for_input
        assert debug.CHEATS.xray is False

    def test_invalid_entry_is_a_no_op(self, text_log: TextLog, cheat_state: Any) -> None:
        debug.open_cheat_menu(text_log)
        text_log.submit_input("9")
        assert not text_log.is_waiting_for_input
        assert debug.CHEATS.xray is False


class TestXray:
    def test_xray_reveals_tiles_behind_walls(
        self, asset_mgr: AssetManager, cheat_state: Any
    ) -> None:
        forest = asset_mgr.get_tile_by_name("forest")
        wall = asset_mgr.get_tile_by_name("wall")
        m = GameMap(
            id=99,
            name="Test",
            width=11,
            height=11,
            border_behavior="fixed",
            no_line_of_sight=False,
            tiles=[forest] * 121,
        )
        m.set_tile(6, 5, wall)
        surf = pygame.Surface((176, 176))
        renderer = WorldRenderer(asset_mgr)

        # Behind-wall tile (8, 5) (viewport col 3, row 5) is shadowed off.
        renderer.render_viewport(surf, m, 5, 5, anim_frame=0)
        px, py = 3 * 16 + 8, 5 * 16 + 8
        assert surf.get_at((px, py)) == pygame.Color(0, 0, 0)

        debug.CHEATS.xray = True
        surf2 = pygame.Surface((176, 176))
        renderer.render_viewport(surf2, m, 5, 5, anim_frame=0)
        assert surf2.get_at((px, py)) != pygame.Color(0, 0, 0)


class TestNohurt:
    def test_would_be_fatal_hit_is_fully_ignored(self, cheat_state: Any) -> None:
        pm = PartyMember(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
        party = Party([pm], x=10, y=10)
        pm.party = party
        debug.CHEATS.nohurt = True
        assert pm.apply_damage(500, False) is True  # damage "takes place"
        assert pm.character.hp == 100
        assert pm.character.status is not None
        assert pm.is_dead() is False
        # Status untouched (GOOD), no wipe path fired.
        assert party.is_anyone_alive() is True

    def test_without_toggle_fatal_hit_still_kills(self, cheat_state: Any) -> None:
        pm = PartyMember(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100))
        Party([pm], x=10, y=10)
        debug.CHEATS.nohurt = False
        pm.apply_damage(500, True)
        assert pm.is_dead() is True


class TestNoblock:
    def test_walk_through_mountain(self, asset_mgr: AssetManager, cheat_state: Any) -> None:
        grass = asset_mgr.get_tile_by_name("grass")
        mountain = asset_mgr.get_tile_by_name("mountain")
        m = GameMap(
            id=99,
            name="Test",
            width=11,
            height=11,
            border_behavior="fixed",
            no_line_of_sight=False,
            tiles=[grass] * 121,
        )
        m.set_tile(3, 3, mountain)
        assert can_move_to(m, 3, 3) is False
        debug.CHEATS.noblock = True
        assert can_move_to(m, 3, 3) is True


class TestNofight:
    @pytest.fixture
    def overworld(self, asset_mgr: AssetManager, monkeypatch: pytest.MonkeyPatch):
        party = make_party()
        o = OverworldScreen(
            party=party,
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=10,
            start_y=10,
            random_encounters=False,
        )
        o._check_moongates = lambda: None  # type: ignore[method-assign]
        return o

    @pytest.fixture
    def combat_trigger(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[tuple[str, dict[str, Any] | None]] = []

        def _capture(self, creature_name: str, creature: dict[str, Any] | None = None) -> None:
            calls.append((creature_name, creature))

        monkeypatch.setattr(OverworldScreen, "_trigger_combat", _capture)
        return calls

    def test_creature_contact_triggers_combat_normally(
        self, overworld: OverworldScreen, combat_trigger: Any, cheat_state: Any
    ) -> None:
        overworld.creatures = [{"tile_name": "orc", "tile": "orc", "x": 11, "y": 10}]
        overworld._update_creatures()
        assert [c[0] for c in combat_trigger] == ["orc"]

    def test_nofight_skips_combat_entry(
        self, overworld: OverworldScreen, combat_trigger: Any, cheat_state: Any
    ) -> None:
        debug.CHEATS.nofight = True
        overworld.creatures = [{"tile_name": "orc", "tile": "orc", "x": 11, "y": 10}]
        overworld._update_creatures()
        assert combat_trigger == []


class TestFullMp:
    def test_cast_prompt_tops_up_caster_mp(self, text_log: TextLog, cheat_state: Any) -> None:
        party = make_party()
        mage = party.members[1]
        assert mage.character.mp == 5
        debug.CHEATS.full_mp = True
        prompt_cast_party(text_log, party)
        text_log.submit_input("2")  # member selection
        assert mage.character.mp == 30

    def test_without_toggle_mp_not_topped_up(self, text_log: TextLog, cheat_state: Any) -> None:
        party = make_party()
        mage = party.members[1]
        prompt_cast_party(text_log, party)
        text_log.submit_input("2")
        assert mage.character.mp == 5


class TestNoClass:
    def test_both_disciplines_for_every_profession(self, cheat_state: Any) -> None:
        assert get_castable_spell_types(Profession.FIGHTER) == []
        debug.CHEATS.no_class = True
        assert get_castable_spell_types(Profession.FIGHTER) == ["wizard", "cleric"]
        assert get_castable_spell_types(Profession.WIZARD) == ["wizard", "cleric"]

    def test_any_char_can_cast_any_spell(self, text_log: TextLog, cheat_state: Any) -> None:
        """A fighter walks the whole cast prompt and lands a wizard spell."""
        party = make_party()
        hero = party.members[0]
        hero.character.mp = 50
        debug.CHEATS.no_class = True
        prompt_cast_party(text_log, party)
        text_log.submit_input("1")  # member
        text_log.submit_input("W")  # Spell Type?
        # DAG LORUM = I — its FIXED wizard code (USER-DIRECTED RULING
        # 2026-11-15: spell letters are fixed, never the dynamic walk).
        text_log.submit_input("I")
        blob = "\n".join(text_log.history)
        assert "cannot cast" not in blob
        assert hero.character.mp == 10  # 50 - 40

    def test_without_gate_fighter_is_refused(self, text_log: TextLog, cheat_state: Any) -> None:
        party = make_party()
        hero = party.members[0]
        hero.character.mp = 50
        prompt_cast_party(text_log, party)
        text_log.submit_input("1")
        blob = "\n".join(text_log.history)
        # Item 3: the empty-castables refusal uses Java's canonical line
        # (SecondaryInputProcessor.java:285/445; CombatScreen.java:326) —
        # the old "{name} ({prof}) cannot cast spells!" was invented.
        assert "No spells to cast!" in blob


class TestCheatMenuViaF10:
    def test_f10_opens_menu_in_debug_mode(
        self, asset_mgr: AssetManager, cheat_state: Any
    ) -> None:
        debug.DEBUG_MODE = True
        o = OverworldScreen(
            party=make_party(),
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=10,
            start_y=10,
            random_encounters=False,
        )
        o.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F10, unicode=""))
        assert o.text_log.is_waiting_for_input

    def test_f10_is_inert_without_debug(
        self, asset_mgr: AssetManager, cheat_state: Any
    ) -> None:
        debug.DEBUG_MODE = False
        o = OverworldScreen(
            party=make_party(),
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=10,
            start_y=10,
            random_encounters=False,
        )
        saved = dataclasses.replace(debug.CHEATS)
        o.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F10, unicode=""))
        assert o.text_log.is_waiting_for_input is False
        assert debug.CHEATS == saved


class TestMaxAll:
    def test_max_all_matches_gbc_domaxall(self, cheat_state: Any) -> None:
        party = make_party()
        for pm in party.members:
            char = pm.character
            char.marks = [0, 0, 0, 0]
            char.cards = [0, 0, 0, 0]

        debug.max_all(party)

        assert party.exodus_cards_status == 0xF  # party_specials = 0x0F
        for pm in party.members:
            char = pm.character
            assert char.gold == 9999
            assert char.keys == 99
            assert char.gems == 99
            assert char.torches == 99
            assert char.powder == 99
            assert char.hp == 9999
            assert char.max_hp == 9999
            assert char.str == 99
            assert char.dex == 99
            assert char.int == 99
            assert char.wis == 99
            assert char.food == 9999
            assert char.exp == 9999
            assert char.level == 99
            assert list(char.marks) == [1, 1, 1, 1]
            assert list(char.cards) == [1, 1, 1, 1]
            for stack in char.weapons.values():
                assert stack == 9
            for stack in char.armors.values():
                assert stack == 9
            # No mp field is touched: GBC's domaxall (cheat.c:441-479)
            # writes no mp; the mage keeps its pre-cheat mp/max_mp values.
            if char.name == "Mage":
                assert char.max_mp == 30
                assert char.mp == 5

    def test_max_all_reported_to_text_log(self, text_log: TextLog, cheat_state: Any) -> None:
        party = make_party()
        msg = debug.max_all(party)
        assert msg
        text_log.add_message(msg)


class TestCheatNeverSaved:
    """RUNTIME-ONLY: no cheat key may reach any to_dict()/save path."""

    CHEAT_TOKENS = (
        "xray",
        "nofight",
        "nohurt",
        "noblock",
        "full_mp",
        "no_class",
        "free_peer",
        "noclass",
        "fullmp",
        "cheat",
        "DEBUG_MODE",
    )

    def test_party_save_dict_carries_no_cheat_keys(self, cheat_state: Any) -> None:
        party = make_party()
        plain = json.dumps(party.to_dict()).lower()
        for token in self.CHEAT_TOKENS:
            assert token not in plain

    def test_max_all_does_not_change_save_schema(self, cheat_state: Any) -> None:
        party = make_party()
        before = set(party.to_dict().keys())
        char_before = set(party.members[0].to_dict().keys())
        debug.max_all(party)
        assert set(party.to_dict().keys()) == before
        assert set(party.members[0].to_dict().keys()) == char_before
        blob = json.dumps(party.to_dict()).lower()
        for token in self.CHEAT_TOKENS:
            assert token not in blob
