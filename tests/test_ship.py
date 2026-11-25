"""Ships: boarding parity, wind, rendering, shoreline. LairWare ships have
no hull (the Java hull, sinking and repair rules are gone, 2026-11-22).

Java truth: ``exodus/GameScreen.java:945-979`` (board — exact-tile boarding,
"Board What?" / "Board: Can't!").
"""
from __future__ import annotations

import pytest
import pygame

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.overworld import OverworldScreen


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def sample_party():
    c1 = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)
    return Party([PartyMember(c1)], x=10, y=10, gold=500, transport=Transport.FOOT)


@pytest.fixture
def overworld(asset_mgr, sample_party, monkeypatch):
    """Overworld screen with movement always allowed and gates disabled."""
    o = OverworldScreen(
        party=sample_party,
        map_id=0,
        asset_mgr=asset_mgr,
        start_x=10,
        start_y=10,
        random_encounters=False,
    )
    monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
    o._check_moongates = lambda: None  # type: ignore[method-assign]
    return o


def key(screen, k):
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=chr(k) if k < 128 else ""))


class TestBoardingGate:
    """B requires the transport object exactly on the party's tile (Java
    GameScreen.java:951-972 — board(x, y) scans for cx == x && cy == y)."""

    def test_board_frigate_on_party_tile(self, overworld, sample_party):
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 10, "y": 10})
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.SHIP
        assert any("Board Frigate!" in m for m in overworld.text_log.history)
        assert not [o for o in sample_party.dynamic_objects if o.get("tile") == "frigate"]

    def test_board_adjacent_frigate_is_board_what(self, overworld, sample_party):
        """Java's Chebyshev-1 adjacency is wrong: only the exact tile boards."""
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 10, "y": 11})
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.FOOT
        assert any(m == "Board What?" for m in overworld.text_log.history)
        assert len([o for o in sample_party.dynamic_objects if o.get("tile") == "frigate"]) == 1

    def test_board_nothing_is_board_what_no_auto_mount(self, overworld, sample_party):
        """B with nothing boardable: "Board What?", never auto-mount a horse."""
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.FOOT
        assert any(m == "Board What?" for m in overworld.text_log.history)

    def test_board_while_on_ship_says_can_t(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.SHIP
        assert any(m == "Board: Can't!" for m in overworld.text_log.history)

    def test_board_while_on_horse_says_can_t(self, overworld, sample_party):
        sample_party.transport = Transport.HORSE
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.HORSE
        assert any(m == "Board: Can't!" for m in overworld.text_log.history)

    def test_mount_horse_on_party_tile(self, overworld, sample_party):
        sample_party.dynamic_objects.append({"tile": "horse", "x": 10, "y": 10})
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.HORSE
        assert any("Mount Horse!" in m for m in overworld.text_log.history)

    def test_mount_wandering_horse_exact_tile(self, overworld, sample_party):
        overworld.creatures = [{"tile_name": "horse", "x": 10, "y": 10, "hp": 100}]
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.HORSE
        assert len(overworld.creatures) == 0

    def test_adjacent_wandering_horse_is_board_what(self, overworld, sample_party):
        overworld.creatures = [{"tile_name": "horse", "x": 11, "y": 10, "hp": 100}]
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.FOOT
        assert any(m == "Board What?" for m in overworld.text_log.history)

    def test_frigate_wins_over_horse_on_same_tile(self, overworld, sample_party):
        """Java board() checks the frigate object list before the horse."""
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 10, "y": 10})
        overworld.creatures = [{"tile_name": "horse", "x": 10, "y": 10, "hp": 100}]
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.SHIP


class TestExactFrigateNameMatch:
    """Java matches the exact tile name: ``"frigate".equals(
    d.getTile().getName())`` in fireAt (util/Utils.java:538) and board
    (GameScreen.java:955). "ship" is not a tile name Java can match — the
    only ship-rule tile is "frigate" (assets/xml/tileset-base.xml:13) — so
    the port's defensive "frigate" | "ship" superset is wrong."""

    def test_board_ignores_ship_named_object(self, overworld, sample_party):
        obj = {"tile": "ship", "x": 10, "y": 10}
        sample_party.dynamic_objects.append(obj)
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.FOOT
        assert any(m == "Board What?" for m in overworld.text_log.history)
        assert obj in sample_party.dynamic_objects


    def test_town_board_ignores_ship_named_object(self, asset_mgr, sample_party):
        from py_exodus.screens.town import TownScreen

        town = TownScreen(
            party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10
        )
        obj = {"tile": "ship", "x": 10, "y": 10}
        sample_party.dynamic_objects.append(obj)
        town.board(10, 10)
        assert sample_party.transport == Transport.FOOT
        assert any(m == "Board What?" for m in town.text_log.history)
        assert obj in sample_party.dynamic_objects


class TestCombatRoundEndTurn:
    """LairWare (ledger B-01, user ruling 2026-11-25): a combat round counts
    no move; it runs AgeChars, which off Sosaria acts every 4th call
    (UltimaMisc.c:1405-1410, UltimaSpellCombat.c:883, 920-923)."""

    def test_combat_age_chars_counts_no_move(self, sample_party):
        sample_party.members[0].submorsels = 45
        sample_party.members[0].food = 10
        moves_before = sample_party.moves
        sample_party.age_chars(sosaria=False)  # the first call ticks
        assert sample_party.moves == moves_before
        assert sample_party.members[0].submorsels == 5
        for _ in range(3):
            sample_party.age_chars(sosaria=False)
        assert sample_party.members[0].submorsels == 5
        assert sample_party.members[0].food == 10


class TestWindRules:
    """Task 20: GBC wind rules — becalmed blocks sailing, headwind blocks
    sailing, and the wind re-rolls to a DIFFERENT outcome every 20th
    consumed move.

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): wind blocks when
    becalmed/against headwind; forced re-roll per 20 moves (GBC
    postexo1.c:1848-1852; menucmd3.c:1449-1467). Supersedes py's
    "Sailing against headwinds slows thee!" and the 4-second wall-clock
    wind timer (wind is move-driven now, like the moons since Task 19).

    The move-driven counter is Party.moves itself (GBC's ``moves`` modulo,
    Party.end_turn's counter), checked on the overworld turn end.
    """

    def _sailing_party(self, sample_party):
        sample_party.transport = Transport.SHIP
        sample_party.ship_hull = 50
        sample_party.moves = 7  # clear of the 20-move re-roll slots
        return sample_party

    def test_becalmed_blocks_sailing(self, overworld, sample_party):
        self._sailing_party(sample_party)
        sample_party.wind_direction = None  # calm/becalmed
        overworld.heading = Direction.EAST
        key(overworld, pygame.K_RIGHT)
        assert (sample_party.x, sample_party.y) == (10, 10)
        assert any(
            m == "The ship is becalmed!" for m in overworld.text_log.history
        )

    def test_headwind_blocks_sailing(self, overworld, sample_party):
        self._sailing_party(sample_party)
        sample_party.wind_direction = Direction.SOUTH  # from the south (LW ValidTrans, Q25)
        overworld.heading = Direction.SOUTH
        key(overworld, pygame.K_DOWN)
        assert (sample_party.x, sample_party.y) == (10, 10)
        assert any(
            m == "Headwinds block thy ship!"
            for m in overworld.text_log.history
        )
        # The old slow-down message is gone, not just amended.
        assert not any(m == "Sailing against headwinds slows thee!" for m in overworld.text_log.history)

    def test_non_headwind_still_sails(self, overworld, sample_party):
        self._sailing_party(sample_party)
        sample_party.wind_direction = Direction.EAST
        overworld.heading = Direction.NORTH
        key(overworld, pygame.K_UP)
        assert (sample_party.x, sample_party.y) == (10, 9)

    def test_wind_rerolls_every_20th_move_never_repeating(self, overworld, sample_party):
        import random as _random

        _random.seed(319)
        changes = []
        before = sample_party.wind_direction
        for _ in range(100):
            overworld._finish_turn()
            wind = sample_party.wind_direction
            if wind != before:
                changes.append(sample_party.moves)
                # Forced re-roll: never repeats the outgoing value.
                assert wind != before
                before = wind
        # 100 moves → exactly the multiples of 20 re-roll.
        assert len(changes) == 5
        assert all(m % 20 == 0 for m in changes)

    def test_display_sites_tolerate_calm(self, asset_mgr, sample_party):
        from py_exodus.screens.overworld import sky_strip_texts

        sample_party.wind_direction = None
        o = OverworldScreen(
            party=sample_party,
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=10,
            start_y=10,
            random_encounters=False,
        )
        # Screen-entry message names the calm instead of crashing on .name.
        assert any("The wind is calm." in m for m in o.text_log.history)
        # Sky strip renders the calm wind (no arrow).
        strip = o.sky_strip_texts()
        assert any(t == "Wind CALM" for t in strip)
        # Full render path must not crash on the None wind.
        o.render(pygame.Surface((320, 200)))


class TestFrigateRendering:
    """LairWare's ship faces one way; TwiddleFlags swaps its flag between two
    cells (UltimaMain.c:3378-3381), whatever the heading."""

    @staticmethod
    def _center_tile_bytes(surface: pygame.Surface, tile_size: int = 16) -> bytes:
        half = 5  # VIEWPORT_TILES // 2
        rect = pygame.Rect(half * tile_size, half * tile_size, tile_size, tile_size)
        return pygame.image.tobytes(surface.subsurface(rect), "RGBA")

    @pytest.mark.parametrize("heading", list(Direction)[:4])
    def test_frigate_twiddles_its_flag_whatever_the_heading(
        self, overworld, sample_party, asset_mgr, monkeypatch, heading
    ):
        from py_exodus.ui.renderer import WorldRenderer

        grass = asset_mgr.get_tile_by_name("grass")
        monkeypatch.setattr(overworld.game_map, "get_tile", lambda x, y: grass)
        sample_party.transport = Transport.SHIP
        assert len(asset_mgr.tiles["frigate"]) == 2
        renderer = WorldRenderer(asset_mgr)
        shots = []
        for anim_frame in (0, 1, 2):
            surf = pygame.Surface((176, 176))
            renderer.render_viewport(
                surf, overworld.game_map, center_x=sample_party.x,
                center_y=sample_party.y, anim_frame=anim_frame,
                party=sample_party, heading=heading,
            )
            shots.append(self._center_tile_bytes(surf))
        assert shots[0] != shots[1] and shots[0] == shots[2]


class TestFrigateNoStacking:
    """Winning a pirate fight or disembarking must not stack duplicate frigates."""

    def test_pirate_victory_does_not_stack_frigate(self, asset_mgr, sample_party):
        from py_exodus.combat.arena import CombatArena
        from py_exodus.world.loader import MapLoader

        combat_map = MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT")
        sample_party.x, sample_party.y = 46, 18
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 46, "y": 18})

        arena = CombatArena(
            party=sample_party,
            combat_map=combat_map,
            creature_tile="pirate",
            asset_mgr=asset_mgr,
            monster_count=1,
            encounter_x=46,
            encounter_y=18,
            encounter_tile_walkable=False,
        )
        arena._handle_victory()

        frigates_at_tile = [
            o for o in sample_party.dynamic_objects
            if o.get("tile") == "frigate" and o.get("x") == 46 and o.get("y") == 18
        ]
        assert len(frigates_at_tile) == 1

    def test_disembark_at_open_sea(self, overworld):
        """LW Exit (UltimaMain.c:2523-2538) needs only water or grass under
        the ship; there is no shoreline rule."""
        overworld.party.x, overworld.party.y = 50, 10  # Open ocean (no adjacent land)
        overworld.party.transport = Transport.SHIP

        overworld._exit_transport()

        assert overworld.party.transport == Transport.FOOT

    def test_disembark_does_not_stack_frigate(self, overworld):
        overworld.party.x, overworld.party.y = 46, 18
        overworld.party.transport = Transport.SHIP
        overworld.party.dynamic_objects.append({"tile": "frigate", "x": 46, "y": 18})

        overworld._exit_transport()

        frigates_at_tile = [
            o for o in overworld.party.dynamic_objects
            if o.get("tile") == "frigate" and o.get("x") == 46 and o.get("y") == 18
        ]
        assert len(frigates_at_tile) == 1

    def test_disembark_at_open_sea(self, overworld):
        """LW Exit (UltimaMain.c:2523-2538) needs only water or grass under
        the ship; there is no shoreline rule."""
        overworld.party.x, overworld.party.y = 50, 10  # Open ocean (no adjacent land)
        overworld.party.transport = Transport.SHIP

        overworld._exit_transport()

        assert overworld.party.transport == Transport.FOOT


