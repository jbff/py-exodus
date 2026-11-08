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

    def test_cannon_damages_empty_frigate(self, overworld, sample_party):
        """Utils.fireAt (Utils.java:540-546): an empty frigate in the path is
        a hit and takes 10 hull damage, stopping the trace."""
        sample_party.transport = Transport.SHIP
        overworld.heading = Direction.NORTH
        frigate = {"tile": "frigate", "x": 11, "y": 10, "hull": 50}
        sample_party.dynamic_objects.append(frigate)
        overworld._fire_cannons(Direction.EAST)
        assert frigate["hull"] == 40


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


class TestSailingFacing:
    """GameScreen.java:461-529 — on a ship an arrow first turns the ship
    (turn consumed, no motion); a matching arrow moves. Horses do not turn."""

    def test_arrow_first_turns_ship(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        overworld.heading = Direction.NORTH
        key(overworld, pygame.K_RIGHT)  # EAST
        assert overworld.heading == Direction.EAST
        assert sample_party.x == 10 and sample_party.y == 10  # did not move
        assert sample_party.moves == 1  # turn consumed

    def test_second_press_moves(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        overworld.heading = Direction.NORTH
        key(overworld, pygame.K_RIGHT)  # turn only
        key(overworld, pygame.K_RIGHT)  # now move
        assert (sample_party.x, sample_party.y) == (11, 10)
        assert sample_party.moves == 2

    def test_matching_direction_moves_immediately(self, overworld, sample_party):
        sample_party.transport = Transport.SHIP
        overworld.heading = Direction.EAST
        key(overworld, pygame.K_RIGHT)
        assert (sample_party.x, sample_party.y) == (11, 10)
        assert sample_party.moves == 1

    def test_horse_moves_without_facing(self, overworld, sample_party):
        sample_party.transport = Transport.HORSE
        overworld.heading = Direction.NORTH
        key(overworld, pygame.K_RIGHT)
        assert (sample_party.x, sample_party.y) == (11, 10)
        assert sample_party.moves == 1

    def test_foot_moves_without_facing(self, overworld, sample_party):
        overworld.heading = Direction.NORTH
        key(overworld, pygame.K_RIGHT)
        assert (sample_party.x, sample_party.y) == (11, 10)

    def test_facings_are_independent_per_screen(self, overworld, sample_party):
        """Facing persists from foot movement, is not reset by boarding."""
        key(overworld, pygame.K_RIGHT)  # foot move east, heading → EAST
        sample_party.transport = Transport.SHIP
        key(overworld, pygame.K_RIGHT)  # already facing east: moves
        assert (sample_party.x, sample_party.y) == (12, 10)
