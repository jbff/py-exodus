"""Task 26 (D3): functional Other commands — bribe, steal, dig, pray, search, score.

USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): functional Other command
(GBC menucmd3.c:1019-1236; menucmd2.c:1440-1540; LW UltimaMisc.c:2262-2503).

GBC truth:
- ``dobribe`` (menucmd3.c:1019-1103): <100 gold → "Cannot pay."; direction
  target must be the guard tile (0x18) with a monster standing there; removal
  restores the underlying map byte and deducts 100 gold; a guard tile with no
  creature returns silently without deducting; any other tile → "NO EFFECT.".
- ``dosteal`` (menucmd2.c:1440-1564): outside → "ONLY INSIDE."; the 3-tile
  chain in the direction is person (0x3C..0x56) → door/locked door
  (0x0B/0x16) → chest (0x0C); skill roll ``make_rnd(0) < dex(+0x80 thief /
  +0x40 other classes)``; success pays ``make_rnd(0x64) | 0x30`` (>0x64 →
  -0x64) with the 9999 cap, a 25% weapon/armor extra, and seals the chest as
  a door (0x0B); failure warns "WATCH OUT." 1-in-4 (GBC flags the town
  guards hostile) else "FAILED."; a wrong chain → "NOTHING".
- ``dodig`` (menucmd3.c:1120-1133): Sosaria surface only (GBC ``inside==0``);
  (33,3) → +1 exotic weapon, (19,44) → +1 exotic armor, both capped at 9,
  "EXOTICS."; else "NO EFFECT.".
- ``dopray`` (menucmd3.c:1199-1206): the EXODUS map at (48,48) → the EVOCARE
  vision; else "NO EFFECT.". The pre-existing Yew-area hint is kept (union of
  references, user ruling).
- ``dosearch`` (menucmd3.c:1151-1197): ONLY on Ambrosia — (4,36) love,
  (45,52) sol, (6,6) moons, (55,27) death; the card is credited per member.
- ``doscore`` (menucmd3.c:872-876) is a "NO EFFECT." stub in GBC; the move
  counter message is the user-directed amendment (2026-11-14).
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import MAP_NAME_TO_ID, TileDef
from py_exodus.constants import (
    ArmorType,
    Direction,
    MapType,
    Profession,
    Race,
    TileAttrib,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.town import TownScreen
from py_exodus.world.map import GameMap, MapNpc
import py_exodus.special_commands as special_commands


FLOOR = TileDef(index=8, name="floor", rule="floors")
DOOR = TileDef(index=35, name="door", rule="door", attribs=TileAttrib.DOOR)
LOCKED_DOOR = TileDef(
    index=100, name="locked_door", rule="locked_door", attribs=TileAttrib.LOCKEDDOOR
)
CHEST = TileDef(index=9, name="chest", rule="chest", attribs=TileAttrib.CHEST)


def make_map(map_type=MapType.CITY, map_id=1, width=64, height=64, npcs=None):
    tiles = [FLOOR] * (width * height)
    return GameMap(
        id=map_id,
        name="MAP",
        map_type=map_type,
        width=width,
        height=height,
        tiles=tiles,
        npcs=list(npcs or []),
    )


def person_npc(x, y, name="fighter", index=20):
    return MapNpc(
        tile_index=index,
        tile_name=name,
        x=x,
        y=y,
        start_x=x,
        start_y=y,
        tile_def=TileDef(index=index, name=name, rule="person"),
    )


def guard_npc(x, y):
    return person_npc(x, y, name="guard", index=18)


def make_member(prof=Profession.FIGHTER, dex=50, gold=200):
    return PartyMember(
        Character("Hero", "M", Race.HUMAN, prof, dexterity=dex, gold=gold)
    )


def make_party(member):
    return Party([member], x=10, y=10, map_id=1)


class SeqRandom:
    """Deterministic randrange stand-in: returns queued values in order."""

    def __init__(self, *values):
        self._values = list(values)

    def randrange(self, *args):
        assert len(args) == 1, f"unexpected randrange({args!r})"
        assert self._values, "unexpected extra roll"
        return self._values.pop(0)


class TestBribe:
    """do_bribe — GBC menucmd3.c:1019-1103."""

    def test_insufficient_gold_refuses_before_anything(self):
        member = make_member(gold=99)
        party = make_party(member)
        npc = guard_npc(11, 10)
        game_map = make_map(npcs=[npc])

        message = special_commands.do_bribe(
            party, member, 10, 10, Direction.EAST, game_map
        )

        assert message == "Cannot pay."  # cantpay (menucmd3.c:1028)
        assert member.gold == 99
        assert npc in game_map.npcs  # not touched

    def test_guard_target_removed_and_gold_deducted(self):
        member = make_member(gold=250)
        party = make_party(member)
        npc = guard_npc(11, 10)
        game_map = make_map(npcs=[npc])

        message = special_commands.do_bribe(
            party, member, 10, 10, Direction.EAST, game_map
        )

        # GBC bribe success has NO message (menucmd3.c:1079-1101)
        assert message == ""
        assert npc not in game_map.npcs
        assert member.gold == 150
        # The map grid never carried the NPC sprite: the underlying floor
        # tile is already in place at the guard's tile (GBC restores the
        # SRAM byte — py map_build writes `underlying` there at load).
        assert game_map.get_tile(11, 10) is FLOOR

    def test_guard_tile_without_a_guard_is_silent_no_effect(self):
        member = make_member(gold=250)
        party = make_party(member)
        game_map = make_map()  # no NPCs at all

        message = special_commands.do_bribe(
            party, member, 10, 10, Direction.EAST, game_map
        )

        assert message == "No effect."  # noeffectdat (menucmd3.c:1092-1099)
        assert member.gold == 250

    def test_creature_dict_guard_is_removed(self):
        member = make_member(gold=100)
        party = make_party(member)
        game_map = make_map()
        creatures = [{"tile": "guard", "x": 9, "y": 10}]

        message = special_commands.do_bribe(
            party, member, 10, 10, Direction.WEST, game_map, creatures=creatures
        )

        assert message == ""
        assert creatures == []
        assert member.gold == 0

    def test_wrong_direction_tile_not_guard(self):
        member = make_member(gold=600)
        party = make_party(member)
        game_map = make_map(npcs=[guard_npc(11, 10)])  # guard EAST, not NORTH

        message = special_commands.do_bribe(
            party, member, 10, 10, Direction.NORTH, game_map
        )

        assert message == "No effect."
        assert member.gold == 600


class TestSteal:
    """do_steal — GBC menucmd2.c:1440-1564."""

    def test_only_inside_towns(self):
        member = make_member()
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=0)

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, world
        )

        assert lines == ["Only inside."]  # onlyinsidedat (menucmd2.c:113-115, 1457)

    def test_dead_member_refused(self):
        member = make_member(gold=100)
        member.status = "D"
        party = make_party(member)
        game_map = make_map()

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map
        )

        assert lines == ["Player dead."]  # deaddat2 (menucmd2.c:253-255)

    def test_chain_requires_person_then_door_then_chest(self):
        member = make_member()
        party = make_party(member)
        game_map = make_map(npcs=[person_npc(11, 10)])  # no door/chest behind

        assert special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map
        ) == ["Nothing."]  # emptydat2 (menucmd2.c:249-251)

    def test_chain_wrong_order_nothing(self):
        member = make_member()
        party = make_party(member)
        game_map = make_map()
        # chest at +1 (door slot): reversed layout is not a steal chain
        game_map.tiles[10 * 64 + 11] = CHEST
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST

        assert special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map
        ) == ["Nothing."]

    def test_success_gold_and_chest_sealed(self):
        member = make_member(gold=100)  # FIGHTER: skill = 50 dex + 64
        party = make_party(member)
        game_map = make_map(
            npcs=[person_npc(11, 10)],
        )
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(10, 30, 1)  # skill roll 10 < 114; gold 30; no bonus roll (1)

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map, rng=rng
        )

        # successdat → successdat + formatted gold (menucmd2.c:1522-1531)
        assert lines[0] == "Success."
        assert lines[1] == "You stole 62 Gold."  # 30 | 0x30 = 62
        assert member.gold == 162
        # GBC seals the chest as a door (0x0B) — menucmd2.c:1561-1564
        assert isinstance(game_map.get_tile(13, 10), TileDef)
        assert game_map.get_tile(13, 10).rule == "door"

    def test_success_gold_over_100_scales_down(self):
        member = make_member(gold=0)
        party = make_party(member)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = LOCKED_DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(0, 90, 1)  # gold randrange(100)=90 → 90|0x30=122 → 122-100

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines == ["Success.", "You stole 22 Gold."]
        assert member.gold == 22
        assert game_map.get_tile(12, 10).rule == "locked_door"  # sealed chest only

    def test_failure_warns_fourth_of_the_time(self):
        member = make_member()
        party = make_party(member)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(255, 0)  # skill roll 255 >= 114 → fail; warn roll 0

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines == ["Watch out!"]  # watchoutdat (menucmd2.c:1508-1512)

    def test_failure_plain(self):
        member = make_member()
        party = make_party(member)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(255, 3)

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines == ["Failed."]  # faileddat (menucmd2.c:1514-1521)

    def test_thief_gets_plus_128(self):
        thief = make_member(prof=Profession.THIEF, dex=10)  # skill = 138
        party = make_party(thief)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(137, 30, 3)  # 137 < 138 succeeds ONLY with the +0x80

        lines = special_commands.do_steal(
            party, thief, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines[0] == "Success."

    def test_druid_gets_neither_bonus(self):
        druid = make_member(prof=Profession.DRUID, dex=10)  # skill = 10
        party = make_party(druid)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(74, 1)  # 74 >= 10: fails — the +0x40 set excludes Druid

        lines = special_commands.do_steal(
            party, druid, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines == ["Failed."]

    def test_illusionist_in_the_plus_64_set(self):
        ill = make_member(prof=Profession.ILLUSIONIST, dex=10)  # 74
        party = make_party(ill)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(73, 30, 3)  # 73 < 74 (+0x40 from the GBC set)

        lines = special_commands.do_steal(
            party, ill, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines[0] == "Success."

    def test_bonus_weapon_capped_falls_to_armor(self):
        member = make_member(gold=0)
        member.weapons[WeaponType.BOW] = 9  # GBC cap check (<9); BOW = index 5+1-1
        party = make_party(member)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(0, 30, 0, 4, 2)  # skill, gold, bonus hit, weapon idx, armor idx

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines[-1] == "and Chain!"  # GBC armor list index 1..3 (CLOTH..CHAIN)
        assert member.armors[ArmorType.CHAIN] == 1
        assert member.weapons[WeaponType.BOW] == 9  # capped: not granted

    def test_no_bonus_line_without_the_roll(self):
        member = make_member(gold=0)
        party = make_party(member)
        game_map = make_map(npcs=[person_npc(11, 10)])
        game_map.tiles[10 * 64 + 12] = DOOR
        game_map.tiles[10 * 64 + 13] = CHEST
        rng = SeqRandom(0, 30, 3)  # bonus roll 3 != 0

        lines = special_commands.do_steal(
            party, member, 10, 10, Direction.EAST, game_map, rng=rng
        )

        assert lines == ["Success.", "You stole 62 Gold."]


class TestDig:
    """do_dig — GBC menucmd3.c:1120-1133."""

    def test_outside_only(self):
        member = make_member()
        party = make_party(member)
        city = make_map(map_type=MapType.CITY, map_id=1)

        assert special_commands.do_dig(party, member, 33, 3, city) == "No effect."

    def test_exotic_weapon_site(self):
        member = make_member()
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=MAP_NAME_TO_ID["SOSARIA"])

        message = special_commands.do_dig(party, member, 33, 3, world)

        assert message == "Exotics."  # exoticdat (menucmd3.c:1098-1103)
        assert member.weapons[WeaponType.EXOTIC] == 1

    def test_exotic_weapon_stack_cap(self):
        member = make_member()
        member.weapons[WeaponType.EXOTIC] = 9
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=0)

        message = special_commands.do_dig(party, member, 33, 3, world)

        assert message == "Exotics."
        assert member.weapons[WeaponType.EXOTIC] == 9

    def test_exotic_armor_site(self):
        member = make_member()
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=0)

        message = special_commands.do_dig(party, member, 19, 44, world)

        assert message == "Exotics."
        assert member.armors[ArmorType.EXOTIC] == 1

    def test_other_site_no_effect(self):
        member = make_member()
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=0)

        assert special_commands.do_dig(party, member, 40, 40, world) == "No effect."
        assert member.weapons[WeaponType.EXOTIC] == 0


class TestPray:
    """do_pray — GBC menucmd3.c:1199-1206 (+ kept Yew hint)."""

    def test_exodus_map_site(self):
        assert (
            special_commands.do_pray(48, 48, MAP_NAME_TO_ID["EXODUS"])
            == "A vision appears: Yell 'EVOCARE'!"
        )

    def test_exodus_other_tile_no_effect(self):
        assert special_commands.do_pray(10, 10, MAP_NAME_TO_ID["EXODUS"]) == "No effect."

    def test_yew_hint_union_is_kept(self):
        assert (
            special_commands.do_pray(48, 48, 10)  # legacy "10"/"yew" hint area
            == "A vision appears: Yell 'EVOCARE'!"
        )

    def test_general_no_effect(self):
        assert special_commands.do_pray(10, 10, 0) == "No effect."


class TestSearch:
    """do_search — GBC menucmd3.c:1151-1197."""

    def test_ambrosia_card_sites(self):
        ambrosia = MAP_NAME_TO_ID["AMBROSIA"]
        cases = [(4, 36, 3), (45, 52, 1), (6, 6, 2), (55, 27, 0)]
        for x, y, card_index in cases:
            member = make_member()
            message = special_commands.do_search(member, x, y, ambrosia)
            assert message == "You found a Card with Strange Marks."
            assert member.cards[card_index] == 1

    def test_second_card_increments(self):
        member = make_member()
        member.cards[3] = 1
        special_commands.do_search(member, 4, 36, MAP_NAME_TO_ID["AMBROSIA"])
        assert member.cards[3] == 2

    def test_wrong_ambrosia_spot(self):
        member = make_member()
        assert (
            special_commands.do_search(member, 20, 20, MAP_NAME_TO_ID["AMBROSIA"])
            == "No effect."
        )
        assert member.cards == [0, 0, 0, 0]

    def test_not_ambrosia(self):
        member = make_member()
        assert special_commands.do_search(member, 4, 36, 0) == "No effect."
        assert special_commands.do_search(member, 55, 27, MAP_NAME_TO_ID["DEATH"]) == "No effect."
        assert member.cards == [0, 0, 0, 0]


class TestScore:
    """do_score — user-directed amendment (GBC SCORE entry is a stub)."""

    def test_message_shows_move_counter(self):
        party = make_party(make_member())
        party.moves = 4242
        assert (
            special_commands.do_score(party)
            == "Thou hast achieved a score of 4242!"
        )


class TestScreenWiring:
    """Both O prompts and the dungeon O handler delegate to the module."""

    @pytest.fixture
    def town(self, asset_mgr, sample_party):
        screen = TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)
        return screen

    @pytest.fixture
    def ow(self, asset_mgr, sample_party, monkeypatch):
        screen = OverworldScreen(
            party=sample_party,
            map_id=0,
            asset_mgr=asset_mgr,
            random_encounters=False,
        )
        monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
        screen._check_moongates = lambda: None  # type: ignore[method-assign]
        return screen

    @pytest.fixture
    def sample_party(self):
        return make_party(make_member(gold=500))

    def _key(self, screen, k):
        screen.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=k, unicode=chr(k) if 0 <= k < 256 else "")
        )

    def _answer(self, screen, text):
        screen.text_log.submit_input(text)

    def _install_town_map(self, town):
        town.game_map = make_map()
        town.avatar_x, town.avatar_y = 10, 10

    def test_town_bribe_removes_guard(self, town, sample_party):
        self._install_town_map(town)
        town.game_map.npcs.append(guard_npc(11, 10))

        self._key(town, pygame.K_o)
        assert town.text_log.is_waiting_for_input
        self._answer(town, "BRIBE")
        self._answer(town, "1")  # member
        self._answer(town, "E")  # direction

        assert town.game_map.npcs == []
        assert sample_party.members[0].gold == 400
        assert not town.text_log.is_waiting_for_input

    def test_town_kiss_removed_generic_fallthrough(self, town):
        self._install_town_map(town)
        self._key(town, pygame.K_o)
        self._answer(town, "KISS")

        messages = "\n".join(str(m) for m in town.text_log.history)
        assert "Nothing happened." in messages
        assert "smiles" not in messages  # the old KISS stub is gone

    def test_overworld_score(self, ow, sample_party):
        sample_party.moves = 77
        self._key(ow, pygame.K_o)
        self._answer(ow, "SCORE")

        joined = " ".join(str(m) for m in ow.text_log.history).replace("\n", " ")
        assert "Thou hast achieved" in joined
        assert "score of 77!" in joined

    def test_overworld_dig_exotics(self, ow, sample_party, monkeypatch):
        sample_party.x, sample_party.y = 33, 3
        self._key(ow, pygame.K_o)
        self._answer(ow, "DIG")
        self._answer(ow, "1")

        assert sample_party.members[0].weapons[WeaponType.EXOTIC] == 1
        messages = "\n".join(str(m) for m in ow.text_log.history)
        assert "Exotics." in messages

    def test_overworld_pray_miss_is_gbc_no_effect(self, ow):
        self._key(ow, pygame.K_o)
        self._answer(ow, "PRAY")

        messages = "\n".join(str(m) for m in ow.text_log.history)
        assert "No effect." in messages

    def test_overworld_steal_refuses_outside(self, ow):
        self._key(ow, pygame.K_o)
        # GBC dosteal answers "ONLY INSIDE." before the member prompt
        # (menucmd2.c:1456-1460) — the flow pre-checks the map type.
        self._answer(ow, "STEAL")

        messages = "\n".join(str(m) for m in ow.text_log.history)
        assert "Only inside." in messages
        assert not ow.text_log.is_waiting_for_input
