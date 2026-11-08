"""Task 9: overworld/town command parity (E, X, J, N, L, U, S, G, T, Y, H).

Java truth:
- ``exodus/GameScreen.java:538-556`` (E on every map incl. towns), ``584-596``
  (X dismounts to FOOT and never leaves a town), ``1089-1100`` (negateTime —
  "Stop time with a powder!" / "None!", first member's powder, QUICKNESS 6).
- ``exodus/SecondaryInputProcessor.java:152-277`` (T/L/U/S/J/G member and
  direction flows, ``308-311`` single-tile G), ``522-577`` (YellInputAdapter —
  EVOCARE snake replacement only with marks[2], "No effect." / "What?").
- ``exodus/objects/BaseMap.java:540-553`` (whirlpool engulf — 4 log lines,
  transport FOOT, party to Ambrosia (32,54)), ``804-831`` (doors).
- ``exodus/GameScreen.java:111-121`` (the two Sosaria whirlpools at (50,13)
  and (17,48)); ``exodus/HandDialog.java:114-146`` (hand dialog moves any
  unequipped weapon OR armor — there is no gold transfer).
"""
from __future__ import annotations

import pytest
import pygame

from py_exodus.assets import AssetManager, TileDef
from py_exodus.aura import Aura, AuraType
from py_exodus.constants import (
    ArmorType,
    Direction,
    Profession,
    Race,
    TileAttrib,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.town import TownScreen


@pytest.fixture
def sample_party():
    members = [
        PartyMember(
            Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)
        ),
        PartyMember(
            Character("Mage", "F", Race.ELF, Profession.WIZARD, strength=15, dexterity=20, hp=70)
        ),
        PartyMember(
            Character("Druid", "F", Race.BOBIT, Profession.DRUID, strength=18, dexterity=20, hp=80)
        ),
    ]
    return Party(members, x=10, y=10, transport=Transport.FOOT)


@pytest.fixture
def ow_factory(asset_mgr, sample_party, monkeypatch):
    """Overworld screen factory with movement always allowed and gates disabled."""
    created = []

    def make(map_id=0):
        o = OverworldScreen(
            party=sample_party,
            map_id=map_id,
            asset_mgr=asset_mgr,
            random_encounters=False,
        )
        monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
        o._check_moongates = lambda: None  # type: ignore[method-assign]
        created.append(o)
        return o

    return make


@pytest.fixture
def ow(ow_factory):
    return ow_factory(0)


@pytest.fixture
def town(asset_mgr, sample_party):
    return TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)


def key(screen, k, unicode=None):
    if unicode is None and 0 <= k < 256:
        unicode = chr(k)
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode))


def answer(screen, text):
    """Answer the active prompt with arbitrary text."""
    screen.text_log.submit_input(text)


def press_direction(screen, direction):
    """Commit a waiting direction prompt via the arrow key (auto-commit)."""
    k = {
        Direction.NORTH: pygame.K_UP,
        Direction.SOUTH: pygame.K_DOWN,
        Direction.EAST: pygame.K_RIGHT,
        Direction.WEST: pygame.K_LEFT,
    }[direction]
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))


def move(screen, direction):
    key(
        screen,
        {
            Direction.NORTH: pygame.K_UP,
            Direction.SOUTH: pygame.K_DOWN,
            Direction.WEST: pygame.K_LEFT,
            Direction.EAST: pygame.K_RIGHT,
        }[direction],
        unicode="",
    )


ENGULF_LINES = [
    "A huge swirling Whirlpool engulfs you and your ship dragging both to a watery grave!",
    "As the water enters your lungs you pass into Darkness!",
    "You awaken on the shores of a forgotten Land.",
    "Your ship and crew lost to the sea!",
]


class TestEnterAndWhirlpool:
    """(a) E in town + whirlpool engulf on step-in; Ambrosia return portal."""

    def test_whirlpool_engulf_on_step_in(self, ow, sample_party):
        """Java GameScreen.java:661-670 / BaseMap.java:540-553 — Sailing within
        one tile of a whirlpool engulfs the ship: 4 log lines, transport FOOT,
        party ferried to Ambrosia (32,54)."""
        sample_party.transport = Transport.SHIP
        ow.creatures.append({"tile_name": "whirlpool", "tile": "whirlpool", "x": 11, "y": 10})
        move(ow, Direction.EAST)
        assert sample_party.transport == Transport.FOOT
        assert (sample_party.x, sample_party.y) == (32, 54)
        assert ow.map_id == 13
        joined = " ".join(ow.text_log.history)
        for line in ENGULF_LINES:
            assert line in joined

    def test_whirlpool_too_far_no_engulf(self, ow, sample_party):
        sample_party.transport = Transport.SHIP
        ow.heading = Direction.EAST  # already facing: the press sails
        ow.creatures.append({"tile_name": "whirlpool", "tile": "whirlpool", "x": 13, "y": 10})
        move(ow, Direction.EAST)
        assert sample_party.transport == Transport.SHIP
        assert (sample_party.x, sample_party.y) == (11, 10)
        assert not any("Whirlpool" in m for m in ow.text_log.history)

    def test_sosaria_spawns_two_whirlpools(self, ow_factory):
        """Java GameScreen.java:111-121 — (50,13) and (17,48) exist from the start."""
        o = ow_factory(0)
        spots = {(c["x"], c["y"]) for c in o.creatures if c.get("tile_name") == "whirlpool"}
        assert (50, 13) in spots
        assert (17, 48) in spots

    def test_ambrosia_whirlpool_portal_e_fixed_start(self, ow_factory, sample_party):
        """Java GameScreen.java:538-556 — E at Ambrosia's WHIRLPOOL portal
        uses the portal's fixed startx/starty (1,1), not a random coast."""
        o = ow_factory(13)
        sample_party.x, sample_party.y = 32, 58
        key(o, pygame.K_e)
        assert (sample_party.x, sample_party.y) == (1, 1)
        assert o.map_id == 0

    def test_e_in_town_with_no_portal(self, town, sample_party):
        """E is now handled on every map including towns (GameScreen.java:538-556)."""
        key(town, pygame.K_e)
        assert any("Nothing to enter here!" in m for m in town.text_log.history)
        assert (town.avatar_x, town.avatar_y) == (10, 10)
        assert not town.is_finished

    def test_whirlpool_never_triggers_combat_or_wanders(self, ow, sample_party):
        """Whirlpools never move and never start combat (wontattack creature)."""
        ow.creatures.append({"tile_name": "whirlpool", "tile": "whirlpool", "x": 6, "y": 6})
        ow._update_creatures()
        assert (6, 6) in [(c["x"], c["y"]) for c in ow.creatures]

    def test_whirlpool_fixtures_reseeded_after_ambrosia_round_trip(self, ow, sample_party):
        """Fix round 3: the two Sosaria whirlpools are re-seeded on every map
        load — otherwise Ambrosia's only sea route dies after one return."""
        # Round 1: the (50, 13) fixture engulfs the party at (49, 13)
        sample_party.transport = Transport.SHIP
        sample_party.x, sample_party.y = 49, 13
        move(ow, Direction.EAST)
        assert sample_party.transport == Transport.FOOT
        assert (sample_party.x, sample_party.y) == (32, 54)
        assert ow.map_id == 13
        assert not [c for c in ow.creatures if c.get("tile_name") == "whirlpool"]

        # Return through Ambrosia's WHIRLPOOL portal (E → fixed (1, 1))
        sample_party.x, sample_party.y = 32, 58
        key(ow, pygame.K_e)
        assert (sample_party.x, sample_party.y) == (1, 1)
        spots = {(c["x"], c["y"]) for c in ow.creatures if c.get("tile_name") == "whirlpool"}
        assert spots == {(50, 13), (17, 48)}

        # Round 2: the re-seeded fixture engulfs again
        sample_party.transport = Transport.SHIP
        sample_party.x, sample_party.y = 49, 13
        move(ow, Direction.EAST)
        assert (sample_party.x, sample_party.y) == (32, 54)
        assert ow.map_id == 13


class TestExitTransport:
    """(b) X = dismount/set FOOT everywhere; never exits a town."""

    def test_town_x_dismounts_horse_never_exits(self, town, sample_party):
        sample_party.transport = Transport.HORSE
        key(town, pygame.K_x)
        assert sample_party.transport == Transport.FOOT
        assert {"tile": "horse", "x": 10, "y": 10} in sample_party.dynamic_objects
        assert not town.is_finished

    def test_town_x_without_transport_stays_in_town(self, town, sample_party):
        key(town, pygame.K_x)
        assert sample_party.transport == Transport.FOOT
        assert not town.is_finished


class TestJoinGold:
    """(c) J prompts member 1-4 and pools via Party.pool_gold(index)."""

    def test_overworld_j_prompt_and_pool(self, ow, sample_party):
        sample_party.members[0].gold = 100
        sample_party.members[1].gold = 250
        sample_party.members[2].gold = 5
        key(ow, pygame.K_j)
        assert ow.text_log.is_waiting_for_input
        assert "JOIN GOLD" in ow.text_log.current_prompt
        answer(ow, "2")
        assert sample_party.members[0].gold == 0
        assert sample_party.members[1].gold == 355
        assert sample_party.members[2].gold == 0

    def test_town_j_prompt_and_pool(self, town, sample_party):
        sample_party.members[0].gold = 40
        sample_party.members[1].gold = 60
        sample_party.members[2].gold = 0
        key(town, pygame.K_j)
        assert town.text_log.is_waiting_for_input
        answer(town, "3")
        assert sample_party.members[0].gold == 0
        assert sample_party.members[2].gold == 100

    def test_overworld_j_non_digit_is_silent(self, ow, sample_party):
        """Java's J falls through silently for a non-digit (SIP:271-277)."""
        gold_before = sample_party.members[0].gold
        key(ow, pygame.K_j)
        answer(ow, "x")
        assert not any("Invalid member #!" in m for m in ow.text_log.history)
        assert not any("Nobody selected!" in m for m in ow.text_log.history)
        assert sample_party.members[0].gold == gold_before


class TestNegateTime:
    """(d) N consumes the first member's powder → QUICKNESS aura for 6 turns."""

    def test_negate_time_first_member_powder(self, ow, sample_party):
        sample_party.members[0].powder = 1
        sample_party.members[1].powder = 2
        key(ow, pygame.K_n)
        assert any("Stop time with a powder!" in m for m in ow.text_log.history)
        assert sample_party.members[0].powder == 0
        assert sample_party.members[1].powder == 2
        assert sample_party.aura.get_type() == AuraType.QUICKNESS
        assert sample_party.aura.get_duration() == 6

    def test_negate_time_none(self, ow, sample_party):
        key(ow, pygame.K_n)
        assert any(m == "None!" for m in ow.text_log.history)
        assert sample_party.aura.get_type() == AuraType.NONE

    def test_town_negate_time_consumes_powder(self, town, sample_party):
        sample_party.members[0].powder = 1
        key(town, pygame.K_n)
        assert sample_party.members[0].powder == 0
        assert sample_party.aura.get_type() == AuraType.QUICKNESS
        assert any("Stop time with a powder!" in m for m in town.text_log.history)
        assert not any("None owned!" in m for m in town.text_log.history)

    def test_town_negate_time_none_when_out_of_powder(self, town, sample_party):
        key(town, pygame.K_n)
        assert any(m == "None!" for m in town.text_log.history)

    def test_aura_pass_turn_decrements(self, sample_party):
        aura = sample_party.aura
        assert isinstance(aura, Aura)
        aura.set(AuraType.QUICKNESS, 2)
        aura.pass_turn()
        assert aura.get_duration() == 1
        assert aura.get_type() == AuraType.QUICKNESS
        aura.pass_turn()
        assert aura.get_duration() == 0
        assert aura.get_type() == AuraType.NONE
        assert not aura.is_active()

    def test_invented_foe_freeze_removed(self, ow):
        """The 15-turn time_stopped_turns freeze must be gone."""
        assert not hasattr(ow, "time_stopped_turns")


class TestAuraQuicknessHook:
    """QUICKNESS skips wandering-creature movement for its duration
    (Java GameScreen.java:728-731 — moveObjects skipped while quick)."""

    def test_creatures_do_not_advance_during_quickness(self, ow, sample_party):
        sample_party.aura.set(AuraType.QUICKNESS, 6)
        ow.creatures.append({"tile_name": "orc", "tile": "orc", "x": 12, "y": 10})
        ow._update_creatures()
        assert (12, 10) in [(c["x"], c["y"]) for c in ow.creatures]


class TestOpen:
    """(e) L on the overworld = OPEN (direction prompt, "Opened!"/"Can't!")."""

    def test_l_prompts_direction_and_cant_without_door(self, ow):
        key(ow, pygame.K_l)
        assert ow.text_log.is_waiting_for_input
        assert "OPEN" in ow.text_log.current_prompt
        answer(ow, "N")
        assert any(m == "Can't!" for m in ow.text_log.history)

    def test_l_opens_unlocked_door(self, ow):
        ow.game_map.set_tile(
            10, 9,
            TileDef(index=35, name="door", rule="door", attribs=TileAttrib.DOOR),
        )
        key(ow, pygame.K_l)
        press_direction(ow, Direction.NORTH)
        assert any(m == "Opened!" for m in ow.text_log.history)
        assert ow.game_map.get_tile(10, 9).rule != "door"

    def test_l_locked_door_cant(self, ow):
        ow.game_map.set_tile(
            10, 9,
            TileDef(index=100, name="locked_door", rule="locked_door", attribs=TileAttrib.LOCKEDDOOR),
        )
        key(ow, pygame.K_l)
        press_direction(ow, Direction.NORTH)
        assert any(m == "Can't!" for m in ow.text_log.history)
        assert ow.game_map.get_tile(10, 9).rule == "locked_door"

    def test_town_l_opened(self, town):
        town.game_map.set_tile(
            10, 9,
            TileDef(index=35, name="door", rule="door", attribs=TileAttrib.DOOR),
        )
        key(town, pygame.K_l)
        press_direction(town, Direction.NORTH)
        assert any(m == "Opened!" for m in town.text_log.history)


class TestUnlock:
    """(f) U requires member keys > 0 and bm.unlockDoor(x, y), then decrements."""

    def _place_locked_door(self, map_):
        map_.set_tile(
            10, 9,
            TileDef(index=100, name="locked_door", rule="locked_door", attribs=TileAttrib.LOCKEDDOOR),
        )

    def test_overworld_u_unlocks_with_key(self, ow, sample_party):
        self._place_locked_door(ow.game_map)
        sample_party.members[0].keys = 1
        key(ow, pygame.K_u)
        assert "UNLOCK" in ow.text_log.current_prompt
        answer(ow, "1")
        assert "Direction?" in ow.text_log.current_prompt
        press_direction(ow, Direction.NORTH)
        assert any(m == "Unlocked!" for m in ow.text_log.history)
        assert sample_party.members[0].keys == 0
        assert ow.game_map.get_tile(10, 9).rule == "door"

    def test_overworld_u_cannot_without_keys(self, ow, sample_party):
        self._place_locked_door(ow.game_map)
        sample_party.members[1].keys = 0
        key(ow, pygame.K_u)
        answer(ow, "2")
        press_direction(ow, Direction.NORTH)
        assert any(m == "Can't!" for m in ow.text_log.history)
        assert sample_party.members[1].keys == 0
        assert ow.game_map.get_tile(10, 9).rule == "locked_door"

    def test_town_u_requires_member_key(self, town, sample_party):
        town.game_map.set_tile(
            10, 9,
            TileDef(index=100, name="locked_door", rule="locked_door", attribs=TileAttrib.LOCKEDDOOR),
        )
        sample_party.members[0].keys = 2
        key(town, pygame.K_u)
        answer(town, "1")
        press_direction(town, Direction.NORTH)
        assert any(m == "Unlocked!" for m in town.text_log.history)
        assert sample_party.members[0].keys == 1


class TestGetChest:
    """(g) G: member digit only — the chest at the party's OWN tile opens
    (fix round 2, final ruling: SIP x/y is a per-event local copy; arrows
    never reach getChest), "Not Here!" otherwise; the keydown consumes a
    turn (SIP finishTurn passes the party's tile)."""

    def test_overworld_g_chest_on_party_tile(self, ow, sample_party):
        sample_party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
        moves_before = sample_party.moves
        key(ow, pygame.K_g)
        assert "GET" in ow.text_log.current_prompt
        answer(ow, "1")
        assert any("The Chest Holds: " in m for m in ow.text_log.history)
        assert not [o for o in sample_party.dynamic_objects if o.get("tile") == "chest"]
        assert sample_party.moves == moves_before + 1

    def test_overworld_g_chestless_is_not_here(self, ow, sample_party):
        key(ow, pygame.K_g)
        answer(ow, "1")
        assert any(m == "Not Here!" for m in ow.text_log.history)

    def test_overworld_g_no_adjacency_scan(self, ow, sample_party):
        """A chest one tile away is NOT scanned for (dungeon-route contract)."""
        sample_party.dynamic_objects.append({"tile": "chest", "x": 11, "y": 10})
        key(ow, pygame.K_g)
        answer(ow, "1")
        assert any(m == "Not Here!" for m in ow.text_log.history)
        assert {"tile": "chest", "x": 11, "y": 10} in sample_party.dynamic_objects

    def test_overworld_g_non_digit_is_silent(self, ow, sample_party):
        """Java logs NOTHING but the typed prompt echo for a non-digit after
        G; the turn is still spent (SIP:459 fall-through)."""
        moves_before = sample_party.moves
        key(ow, pygame.K_g)
        answer(ow, "x")
        assert not any("Invalid member #!" in m for m in ow.text_log.history)
        assert not any("Nobody selected!" in m for m in ow.text_log.history)
        assert sample_party.moves == moves_before + 1

    def test_town_g_chest_tile_under_party(self, town):
        chest_tile = TileDef(index=3, name="chest", rule="chest", attribs=TileAttrib.NONE)
        town.game_map.set_tile(10, 10, chest_tile)
        key(town, pygame.K_g)
        answer(town, "1")
        assert any("The Chest Holds: " in m for m in town.text_log.history)
        assert town.game_map.get_tile(10, 10).name != "chest"

    def test_town_g_chestless_is_not_here_no_adjacency(self, town):
        """A chest tile one tile WEST is not scanned for."""
        chest_tile = TileDef(index=3, name="chest", rule="chest", attribs=TileAttrib.NONE)
        town.game_map.set_tile(9, 10, chest_tile)
        key(town, pygame.K_g)
        answer(town, "1")
        assert any(m == "Not Here!" for m in town.text_log.history)
        assert town.game_map.get_tile(9, 10).name == "chest"

    def test_town_g_non_digit_is_silent(self, town):
        key(town, pygame.K_g)
        answer(town, "q")
        assert not any("Invalid member #!" in m for m in town.text_log.history)
        assert not any("Nobody selected!" in m for m in town.text_log.history)
        assert not town.is_finished


class TestSearchTown:
    """(h) S in town: member prompt + searchLocation flow (labels / "Nothing here!")."""

    def test_town_search_finds_label(self, asset_mgr, sample_party):
        # Ambrosia (13) has CARD_OF_DEATH at (55, 27)
        town = TownScreen(party=sample_party, map_id=13, asset_mgr=asset_mgr, start_x=55, start_y=27)
        key(town, pygame.K_s)
        assert town.text_log.is_waiting_for_input
        answer(town, "1")
        assert any("You found Card of Death." in m for m in town.text_log.history)
        assert sample_party.members[0].cards[0] == 1

    def test_town_search_nothing_here(self, town):
        key(town, pygame.K_s)
        answer(town, "1")
        assert any(m == "Nothing here!" for m in town.text_log.history)


class TestTalkOverworld:
    """(h) T on the overworld routes to the real talk flow (no "Transact:" stub)."""

    def test_overworld_talk_flow(self, ow):
        key(ow, pygame.K_t)
        assert ow.text_log.is_waiting_for_input
        assert "TALK" in ow.text_log.current_prompt
        answer(ow, "1")
        assert "Direction?" in ow.text_log.current_prompt
        press_direction(ow, Direction.NORTH)
        assert any("Funny, no response!" in m for m in ow.text_log.history)
        assert not any("Transact" in m for m in ow.text_log.history)


class TestTalkSignsOnly:
    """T's pass-through rule is signs tiles ONLY (SIP:163-176) — no counter
    widening and no unconditional 2-tiles-away fallback."""

    def test_no_passthrough_without_sign(self, town):
        """Chuckles stands at (32,44); from (32,46) the intermediate tile
        (32,45) is floor — talking north must NOT reach him."""
        town.avatar_x, town.avatar_y = 32, 46
        key(town, pygame.K_t)
        answer(town, "1")
        press_direction(town, Direction.NORTH)
        assert any("Funny, no response!" in m for m in town.text_log.history)


class TestYell:
    """(i) Y: member + word prompts; EVOCARE replaces adjacent snake tiles
    with water only when the talker has marks[2]."""

    def _yell(self, screen, word, member="1"):
        key(screen, pygame.K_y)
        assert "YELL" in screen.text_log.current_prompt
        answer(screen, member)
        assert "Yell what?" in screen.text_log.current_prompt
        answer(screen, word)

    def test_yell_unknown_word_what(self, ow):
        self._yell(ow, "XYZZY")
        assert any(m == "What?" for m in ow.text_log.history)

    def test_evocare_far_from_snakes_no_effect(self, ow):
        self._yell(ow, "EVOCARE")
        assert any(m == "No effect." for m in ow.text_log.history)

    def test_evocare_with_mark_of_snake_replaces_tiles(self, ow, sample_party):
        sample_party.members[0].marks = [0, 0, 1, 0]
        sample_party.x, sample_party.y = 10, 56  # north tile (10,57) is snake
        self._yell(ow, "EVOCARE")
        assert ow.game_map.get_tile(10, 57).name == "water"
        assert ow.game_map.get_tile(10, 58).name == "water"
        assert not any(m == "No effect." for m in ow.text_log.history)

    def test_evocare_without_mark_no_effect(self, ow, sample_party):
        sample_party.x, sample_party.y = 10, 56
        snake_before = ow.game_map.get_tile(10, 57).name
        self._yell(ow, "EVOCARE")
        assert any(m == "No effect." for m in ow.text_log.history)
        assert ow.game_map.get_tile(10, 57).name == snake_before
        assert ow.game_map.get_tile(10, 58).name != "water"


class TestHandDialog:
    """(j) H transfers any unequipped weapon OR armor; there is no gold
    fallback (HandDialog.java:114-146)."""

    def test_hand_transfers_armor(self, town, sample_party):
        sample_party.members[0].armors[ArmorType.LEATHER] = 1
        sample_party.members[0].weapon = WeaponType.NONE
        sample_party.members[0].armor = ArmorType.NONE
        key(town, pygame.K_h)
        answer(town, "1")
        answer(town, "2")
        assert sample_party.members[0].armors[ArmorType.LEATHER] == 0
        assert sample_party.members[1].armors[ArmorType.LEATHER] == 1

    def test_hand_transfers_unequipped_weapon(self, ow, sample_party):
        sample_party.members[0].weapons[WeaponType.AXE] = 1
        key(ow, pygame.K_h)
        answer(ow, "1")
        answer(ow, "2")
        assert sample_party.members[1].weapons[WeaponType.AXE] == 1

    def test_hand_no_gold_fallback(self, ow, sample_party):
        sample_party.members[0].gold = 50
        sample_party.members[1].gold = 0
        key(ow, pygame.K_h)
        answer(ow, "1")
        answer(ow, "2")
        assert sample_party.members[0].gold == 50
        assert sample_party.members[1].gold == 0
        assert not any("handed" in m for m in ow.text_log.history)


class TestCannonTrace:
    """Cannon broadsides trace 4 tiles (Java Utils.java:539-546, 403-421)."""

    def test_broadside_hits_creature_at_4_tiles(self, ow, sample_party):
        sample_party.transport = Transport.SHIP
        ow.heading = Direction.NORTH  # broadside fires EAST/WEST
        ow.creatures.append({"tile_name": "squid", "tile": "squid", "x": 14, "y": 10})
        ow._fire_cannons(Direction.EAST)
        assert any("Direct hit" in m for m in ow.text_log.history)

    def test_broadside_stops_at_4_tiles(self, ow, sample_party):
        sample_party.transport = Transport.SHIP
        ow.heading = Direction.NORTH
        ow.creatures.append({"tile_name": "squid", "tile": "squid", "x": 15, "y": 10})
        ow._fire_cannons(Direction.EAST)
        assert not any("Direct hit" in m for m in ow.text_log.history)
