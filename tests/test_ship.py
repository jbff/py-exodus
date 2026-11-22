"""Task 6: ship hull lifecycle, boarding parity, sailing facing movement.

Java truth: ``exodus/GameScreen.java:945-979`` (board — exact-tile boarding,
hull reset to 50 for a fresh frigate, "Board What?" / "Board: Can't!"),
``1181-1197`` (checkHullIntegrity — "Thy ship sinks!" + killAll → partyDeath),
``461-529`` (ship facing — an arrow first turns the ship, consuming the turn),
``exodus/Party.java:633-638`` (1-in-4 hull repair per endTurn on Sosaria) and
``exodus/Context.java:242-246`` (damageShip).
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


class TestHullLifecycle:
    """Boarding hull rules (GameScreen.java:958-959) and the sink path
    (GameScreen.java:1181-1192)."""

    def test_boarding_fresh_frigate_resets_hull_to_50(self, overworld, sample_party):
        sample_party.ship_hull = 23
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 10, "y": 10})
        key(overworld, pygame.K_b)
        assert sample_party.ship_hull == 50

    def test_reboarding_last_ship_keeps_hull(self, overworld, sample_party, monkeypatch):
        # Board, damage, disembark: the left-behind frigate is last_ship.
        # B/X now consume a turn (Java keyUp tail), so pin Java's 1-in-4
        # Sosaria hull repair off (randint → 1, no repair) to stay
        # deterministic about the hull value.
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 10, "y": 10})
        key(overworld, pygame.K_b)
        sample_party.adjust_ship_hull(-10)
        assert sample_party.ship_hull == 40
        key(overworld, pygame.K_x)  # disembark
        assert sample_party.transport == Transport.FOOT
        hulls = [o for o in sample_party.dynamic_objects if o.get("tile") == "frigate"]
        assert len(hulls) == 1
        assert sample_party.last_ship is hulls[0]

        # Board the same frigate again: hull is preserved.
        key(overworld, pygame.K_b)
        assert sample_party.transport == Transport.SHIP
        assert sample_party.ship_hull == 40

    def test_ship_sinks_at_zero_hull_routes_to_game_over(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        sample_party.ship_hull = 0
        key(overworld, pygame.K_SPACE)  # pass → finishTurn → checkHullIntegrity
        assert any("Thy ship sinks!" in m for m in overworld.text_log.history)
        assert sample_party.is_party_dead()
        assert overworld.is_finished
        from py_exodus.screens.start import StartScreen
        assert isinstance(overworld.next_screen, StartScreen)

    def test_ship_survives_positive_hull(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        sample_party.ship_hull = 1
        key(overworld, pygame.K_SPACE)
        assert not sample_party.is_party_dead()
        assert not any("sinks" in m for m in overworld.text_log.history)


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

    def test_cannons_ignore_ship_named_object(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        obj = {"tile": "ship", "x": 11, "y": 10, "hull": 50}
        sample_party.dynamic_objects.append(obj)
        overworld._fire_cannons(Direction.EAST)
        assert obj["hull"] == 50
        assert not any("unmanned frigate" in m for m in overworld.text_log.history)

    def test_enemy_broadside_ignores_ship_named_object(self, overworld, sample_party):
        sample_party.x, sample_party.y = 30, 30
        pirate = {"tile": "pirate", "x": 3, "y": 3}
        obj = {"tile": "ship", "x": 4, "y": 3, "hull": 50}
        sample_party.dynamic_objects.append(obj)
        overworld._enemy_fire_cannons(pirate, Direction.EAST)
        assert obj["hull"] == 50
        assert not any("unmanned frigate" in m for m in overworld.text_log.history)

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


class TestSosariaHullRepair:
    """Party.java:633-638 — 1-in-4 per endTurn on Sosaria while hull < 50."""

    def test_repair_when_rand_hits(self, sample_party, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 0)
        sample_party.ship_hull = 40
        sample_party.end_turn(surface=True, sosaria=True)
        assert sample_party.ship_hull == 41

    def test_no_repair_when_rand_misses(self, sample_party, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        sample_party.ship_hull = 40
        sample_party.end_turn(surface=True, sosaria=True)
        assert sample_party.ship_hull == 40

    def test_no_repair_off_sosaria(self, sample_party, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 0)
        sample_party.ship_hull = 40
        sample_party.end_turn(surface=True, sosaria=False)
        sample_party.end_turn(surface=False, sosaria=False)
        assert sample_party.ship_hull == 40

    def test_repair_caps_at_50(self, sample_party, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 0)
        sample_party.ship_hull = 50
        for _ in range(5):
            sample_party.end_turn(surface=True, sosaria=True)
        assert sample_party.ship_hull == 50


class TestCombatRoundEndTurn:
    """Pending item 2 — Java Party.endTurn's combat gate (Party.java:600):
    under mapType == combat the meal block is skipped; only the move counter
    (Party.java:594) and the Sosaria hull roll (Party.java:633-638) run. The
    arena caller is CombatScreen.finishTurn's round-end endTurn
    (CombatScreen.java:472)."""

    def test_combat_end_turn_counts_the_move_and_skips_the_meal_block(
        self, sample_party
    ):
        sample_party.members[0].submorsels = 45  # a surface turn would cross it
        sample_party.members[0].food = 10
        moves_before = sample_party.moves
        sample_party.end_turn(surface=True, sosaria=False, combat=True)
        assert sample_party.moves == moves_before + 1
        assert sample_party.members[0].submorsels == 45
        assert sample_party.members[0].food == 10
        assert sample_party.members[0].hp == sample_party.members[0].max_hp


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
        sample_party.wind_direction = Direction.NORTH
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


class TestCannonTraceStopsAtMapEdge:
    """util/Utils.java:484-490 getDirectionalActionPath — a traced tile off
    the map (``nx > width-1 || nx < 0 || ny > height-1 || ny < 0``) breaks
    the trace before it is used. Cannonballs never wrap across a map seam,
    on either the avatar's or the pirate's volley."""


    def test_enemy_broadside_does_not_wrap_across_west_seam(self, overworld, sample_party):
        sample_party.x, sample_party.y = 30, 30
        pirate = {"tile": "pirate", "x": 2, "y": 10}
        frigate = {"tile": "frigate", "x": 63, "y": 10, "hull": 50}
        sample_party.dynamic_objects.append(frigate)
        overworld._enemy_fire_cannons(pirate, Direction.WEST)
        # Wrap would place step 3 on x=63; Java breaks the trace at x=-1.
        assert frigate["hull"] == 50
        assert frigate in sample_party.dynamic_objects

    def test_enemy_broadside_does_not_wrap_across_north_seam(self, overworld, sample_party):
        sample_party.x, sample_party.y = 30, 30
        pirate = {"tile": "pirate", "x": 20, "y": 1}
        frigate = {"tile": "frigate", "x": 20, "y": 63, "hull": 50}
        sample_party.dynamic_objects.append(frigate)
        overworld._enemy_fire_cannons(pirate, Direction.NORTH)
        # Wrap would place steps 3-4 on y=63; Java breaks the trace at y=-1.
        assert frigate["hull"] == 50
        assert frigate in sample_party.dynamic_objects


class TestSunkFrigateRemoved:
    """utils/Utils.java:509-514 animateCannonFire — a cannon hit that leaves
    an unmanned frigate with hull <= 0 removes it from the map
    (``map.removeObject``). A sunk hull is not left boardable."""


    def test_enemy_broadside_removes_sunk_frigate(self, overworld, sample_party):
        sample_party.x, sample_party.y = 30, 30
        pirate = {"tile": "pirate", "x": 3, "y": 3}
        frigate = {"tile": "frigate", "x": 4, "y": 3, "hull": 10}
        sample_party.dynamic_objects.append(frigate)
        overworld._enemy_fire_cannons(pirate, Direction.EAST)
        assert frigate["hull"] == 0
        assert frigate not in sample_party.dynamic_objects


class TestStackedFrigateLastMatch:
    """util/Utils.java:536-547 fireAt — scans all objects without early
    break, so the last matching ``frigate`` on the target tile takes 10
    hull damage while earlier stacked frigates remain untouched."""


    def test_enemy_broadside_damages_last_stacked_frigate(self, overworld, sample_party):
        sample_party.x, sample_party.y = 30, 30
        pirate = {"tile": "pirate", "x": 3, "y": 3}
        frigate_first = {"tile": "frigate", "x": 4, "y": 3, "hull": 50}
        frigate_last = {"tile": "frigate", "x": 4, "y": 3, "hull": 50}
        sample_party.dynamic_objects.extend([frigate_first, frigate_last])
        overworld._enemy_fire_cannons(pirate, Direction.EAST)
        assert frigate_first["hull"] == 50
        assert frigate_last["hull"] == 40


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

    def test_disembark_requires_shoreline(self, overworld):
        overworld.party.x, overworld.party.y = 50, 10  # Open ocean (no adjacent land)
        overworld.party.transport = Transport.SHIP

        overworld._exit_transport()

        assert overworld.party.transport == Transport.SHIP
        assert any("shoreline" in msg.lower() for msg in overworld.text_log.lines)

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

    def test_disembark_requires_shoreline(self, overworld):
        overworld.party.x, overworld.party.y = 50, 10  # Open ocean (no adjacent land)
        overworld.party.transport = Transport.SHIP

        overworld._exit_transport()

        assert overworld.party.transport == Transport.SHIP
        assert any("shoreline" in msg.lower() for msg in overworld.text_log.lines)


