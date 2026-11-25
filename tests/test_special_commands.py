"""Task 26 (D3): functional Other commands (now LairWare rules: see test_lw_parity_commands.py) — bribe, steal, dig, pray, search, score.

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
  (45,52) sol, (6,6) moons, (55,27) death; the card is credited per member
  (markcard |= is idempotent — coordinator fix round: a repeat grants
  nothing). STEAL's +64 set: thief +128; Barbarian/Illusionist/Ranger +64 —
  the Alchemist takes NO bonus (USER RULING 2026-11-14 fix round: the
  original-U3/Apple-II roster, LW UltimaMisc.c:500-526, Alchemist explicitly
  non-Apple-II at :523-530).
- ``doscore`` (menucmd3.c:872-876) is a "NO EFFECT." stub in GBC; the move
  counter message is the user-directed amendment (2026-11-14).
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.town import TownScreen
from py_exodus.world.dungeon import DungeonTile
from py_exodus.world.map import DungeonMap, GameMap, MapNpc
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


def make_dungeon():
    """An 8x8 single-view dungeon grid (borders walled), party at (2,2)."""
    dmap = DungeonMap(id=14, name="TEST DUNGEON", width=8, height=8, levels=8)
    dmap.tiles = [
        [
            [
                DungeonTile.WALL
                if x in (0, 7) or y in (0, 7)
                else DungeonTile.FLOOR
                for x in range(8)
            ]
            for y in range(8)
        ]
        for z in range(8)
    ]
    return dmap


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
        npc = guard_npc(11, 10)
        game_map = make_map(npcs=[npc])

        message = special_commands.do_bribe(
            member, 10, 10, Direction.EAST, game_map
        )

        assert message == "Cannot pay."  # LW "Not enough gold!" (UltimaMisc.c:2454)
        assert member.gold == 99
        assert npc in game_map.npcs  # not touched

    def test_guard_target_removed_and_gold_deducted(self):
        member = make_member(gold=250)
        npc = guard_npc(11, 10)
        game_map = make_map(npcs=[npc])

        message = special_commands.do_bribe(
            member, 10, 10, Direction.EAST, game_map
        )

        # GBC bribe success has NO message (menucmd3.c:1079-1101)
        assert message == ""
        assert npc not in game_map.npcs
        assert member.gold == 150
        # The map grid never carried the NPC sprite: the underlying floor
        # tile is already in place at the guard's tile (GBC restores the
        # SRAM byte — py map_build writes `underlying` there at load).
        assert game_map.get_tile(11, 10) is FLOOR

    def test_nobody_there_is_not_here_and_free(self):
        member = make_member(gold=250)
        game_map = make_map()  # no NPCs at all

        message = special_commands.do_bribe(
            member, 10, 10, Direction.EAST, game_map
        )

        assert message == special_commands.NOT_HERE  # LW UltimaMisc.c:2449-2452
        assert member.gold == 250

    def test_creature_dict_guard_is_removed(self):
        member = make_member(gold=100)
        game_map = make_map()
        creatures = [{"tile": "guard", "x": 9, "y": 10}]

        message = special_commands.do_bribe(
            member, 10, 10, Direction.WEST, game_map, creatures=creatures
        )

        assert message == ""
        assert creatures == []
        assert member.gold == 0

    def test_wrong_direction_nobody_there(self):
        member = make_member(gold=600)
        game_map = make_map(npcs=[guard_npc(11, 10)])  # guard EAST, not NORTH

        message = special_commands.do_bribe(
            member, 10, 10, Direction.NORTH, game_map
        )

        assert message == special_commands.NOT_HERE
        assert member.gold == 600


class TestSteal:
    """do_steal -- LairWare Steal (UltimaMain.c:2248-2287): StealDisarmFail,
    then a counter next to the thief and a chest three tiles out."""

    SIGN = TileDef(index=38, name="A", rule="signs")

    def _shop(self):
        game_map = make_map(npcs=[person_npc(12, 10, name="merchant", index=16)])
        game_map.tiles[10 * 64 + 11] = self.SIGN
        game_map.tiles[10 * 64 + 13] = CHEST
        return game_map

    def test_success_chest_becomes_floor(self, monkeypatch):
        from py_exodus.world import chests

        monkeypatch.setattr(chests, "random", SeqRandom(10, 200))  # gold 10 + 30, gate shut
        member = make_member(dex=50, gold=0)
        game_map = self._shop()
        lines = special_commands.do_steal(
            make_party(member), member, 10, 10, Direction.EAST, game_map, rng=SeqRandom(50)
        )
        assert lines == ["The Chest Holds: 40 Gold"]
        assert member.gold == 40
        assert game_map.get_tile(13, 10).name == "floor"

    def test_failure_warns_fourth_of_the_time(self):
        member = make_member()
        game_map = self._shop()
        lines = special_commands.do_steal(
            make_party(member), member, 10, 10, Direction.EAST, game_map, rng=SeqRandom(255, 0)
        )
        assert lines == ["Watch out!"]

    def test_failure_plain(self):
        member = make_member()
        game_map = self._shop()
        lines = special_commands.do_steal(
            make_party(member), member, 10, 10, Direction.EAST, game_map, rng=SeqRandom(255, 3)
        )
        assert lines == ["Failed."]

    def test_thief_gets_plus_128(self, monkeypatch):
        from py_exodus.world import chests

        monkeypatch.setattr(chests, "random", SeqRandom(10, 200))
        thief = make_member(prof=Profession.THIEF, dex=10)  # factor 138
        lines = special_commands.do_steal(
            make_party(thief), thief, 10, 10, Direction.EAST, self._shop(), rng=SeqRandom(138)
        )
        assert lines == ["The Chest Holds: 40 Gold"]

    def test_illusionist_in_the_plus_64_set(self, monkeypatch):
        from py_exodus.world import chests

        monkeypatch.setattr(chests, "random", SeqRandom(10, 200))
        ill = make_member(prof=Profession.ILLUSIONIST, dex=10)  # factor 74
        lines = special_commands.do_steal(
            make_party(ill), ill, 10, 10, Direction.EAST, self._shop(), rng=SeqRandom(74)
        )
        assert lines == ["The Chest Holds: 40 Gold"]

    def test_druid_gets_neither_bonus(self):
        druid = make_member(prof=Profession.DRUID, dex=10)  # factor 10
        lines = special_commands.do_steal(
            make_party(druid), druid, 10, 10, Direction.EAST, self._shop(), rng=SeqRandom(74, 1)
        )
        assert lines == ["Failed."]

    def test_alchemist_in_the_plus_64_set(self, monkeypatch):
        # LairWare StealDisarmFail (UltimaMisc.c:521-523) and the Book of
        # Lore ("some S&D"): user ruling 2026-11-25, ledger C-27.
        from py_exodus.world import chests

        monkeypatch.setattr(chests, "random", SeqRandom(10, 200))
        alch = make_member(prof=Profession.ALCHEMIST, dex=10)  # factor 74
        lines = special_commands.do_steal(
            make_party(alch), alch, 10, 10, Direction.EAST, self._shop(), rng=SeqRandom(74)
        )
        assert lines == ["The Chest Holds: 40 Gold"]


class TestDig:
    """do_dig — GBC menucmd3.c:1120-1133."""

    def test_outside_only(self):
        member = make_member()
        party = make_party(member)
        city = make_map(map_type=MapType.CITY, map_id=1)

        assert special_commands.do_dig(party, member, 33, 3, city) == special_commands.NOT_HERE

    def test_exotic_weapon_site(self):
        member = make_member()
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=MAP_NAME_TO_ID["SOSARIA"])

        message = special_commands.do_dig(party, member, 33, 3, world)

        assert message == "Exotics."  # exoticdat (menucmd3.c:1098-1103)
        assert member.weapons[WeaponType.EXOTIC] == 1

    def test_exotic_weapon_set_to_one(self):
        member = make_member()
        member.weapons[WeaponType.EXOTIC] = 9
        party = make_party(member)
        world = make_map(map_type=MapType.WORLD, map_id=0)

        message = special_commands.do_dig(party, member, 33, 3, world)

        assert message == "Exotics."
        assert member.weapons[WeaponType.EXOTIC] == 1  # LW sets the count to 1

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

        assert special_commands.do_dig(party, member, 40, 40, world) == special_commands.NOT_HERE
        assert member.weapons[WeaponType.EXOTIC] == 0


class TestPray:
    """do_pray — GBC menucmd3.c:1199-1206 (+ kept Yew hint)."""

    def test_exodus_map_site_is_no_effect(self):
        # LW Pray answers only in Yew (UltimaMisc.c:2466-2481).
        assert special_commands.do_pray(48, 48, MAP_NAME_TO_ID["EXODUS"]) == "No effect."

    def test_exodus_other_tile_no_effect(self):
        assert special_commands.do_pray(10, 10, MAP_NAME_TO_ID["EXODUS"]) == "No effect."

    def test_yew_site(self):
        assert (
            special_commands.do_pray(48, 48, MAP_NAME_TO_ID["YEW"])
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

    def test_repeat_grant_refused(self):
        member = make_member()
        member.cards[3] = 1
        # GBC markcard |= is idempotent (menucmd3.c:1195): the port's
        # search.py convention applies — nothing regrants, no message.
        assert (
            special_commands.do_search(member, 4, 36, MAP_NAME_TO_ID["AMBROSIA"])
            is None
        )
        assert member.cards[3] == 1

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

    def test_overworld_steal_asks_like_anywhere(self, ow):
        self._key(ow, pygame.K_o)
        # LW Steal has no inside-only gate (UltimaMain.c:2248-2258): on
        # Sosaria there is no counter, so a steal can only fail.
        self._answer(ow, "STEAL")

        assert ow.text_log.is_waiting_for_input

    def test_dungeon_other_refuses_outside_only_commands(self, pygame_setup):
        """Dungeon K_o prompts; BRIBE/STEAL/DIG take the GBC noeffectdat
        refusal (dungeon_screen.py _prompt_other) and SCORE passes through."""
        dungeon = DungeonScreen(
            party=make_party(make_member(gold=500)),
            dungeon_map=make_dungeon(),
            map_id=14,
            asset_mgr=None,
            audio=MagicMock(),
        )
        dungeon.party.moves = 12

        self._key(dungeon, pygame.K_o)
        assert dungeon.text_log.is_waiting_for_input
        self._answer(dungeon, "BRIBE")
        assert not dungeon.text_log.is_waiting_for_input
        messages = "\n".join(str(m) for m in dungeon.text_log.history)
        assert "No effect." in messages

        for cmd in ("STEAL", "DIG"):
            self._key(dungeon, pygame.K_o)
            self._answer(dungeon, cmd)
            # no member prompt opens for the refused commands
            assert not dungeon.text_log.is_waiting_for_input
        joined = "\n".join(str(m) for m in dungeon.text_log.history)
        assert joined.count("No effect.") == 3

        self._key(dungeon, pygame.K_o)
        self._answer(dungeon, "SCORE")
        joined = " ".join(str(m) for m in dungeon.text_log.history).replace("\n", " ")
        assert "score of 12!" in joined
