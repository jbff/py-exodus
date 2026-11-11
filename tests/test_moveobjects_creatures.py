"""Task: moveObjects creature-half parity (objects/BaseMap.java:421-610).

Java truth:
- ``objects/BaseMap.java:421-610`` ``moveObjects`` — every attack-capable
  creature ENGAGES at movement distance <= 1 (not same-tile), and engaged
  creatures are removed.
- ``objects/BaseMap.java:511-538`` — PIRATES fight with broadsides: with the
  avatar in the same row/column, range 2-3 on a broadsides heading fires the
  enemy cannons (``Utils.enemyfireCannon`` + ``animateCannonFire``); 2-3
  misaligned turns to a broadsides direction 1-in-2; adjacent aligned battles,
  adjacent misaligned turns. Pirate movement obeys the rotate-then-move rule
  (``511-578``): a pirate only sails when its intended dir equals its
  ``sailDir``, else it turns ``sailDir`` first and does NOT move this tick.
- ``objects/BaseMap.java:505-509`` — a creature whose movement distance
  exceeds ``MAX_CREATURE_DISTANCE`` (Constants.java:44 = 24) is removed,
  except whirlpools.
- ``objects/BaseMap.java:540-558`` — wontattack creatures never battle;
  whirlpools engulf at distance <= 1 (ported in Task 9, unchanged) and
  random-walk like the rest of the wontattack set.
- ``objects/BaseMap.java:633-717`` — ``getValidMovesMask``/``canCreatureMoveOn``
  govern legality: sailing creatures need SAILABLE, swimming need SWIMMABLE,
  walkers need non-UNWALKABLE; a creature never steps onto the avatar's tile
  unless ``canMoveOntoAvatar``, and never onto another creature.
- ``exodus/GameScreen.java:945-979`` + ``objects/BaseMap.java:719-735`` —
  boarding is exact-tile, so Java lets a FOOT avatar step ONTO the water tile
  holding a dropped frigate (``hasShipObjectAt``) to reach it; a dropped
  frigate object renders static (``objects/Drawable.java:46-52`` draws the
  atlas' first region, no frame cycle).
"""
from __future__ import annotations

import pytest
import pygame

from py_exodus.assets import TileDef
from py_exodus.constants import (
    Direction,
    Profession,
    Race,
    TileAttrib,
    Transport,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.overworld import OverworldScreen


@pytest.fixture
def asset_mgr():
    from py_exodus.assets import AssetManager

    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def sample_party():
    members = [
        PartyMember(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)),
        PartyMember(Character("Mage", "F", Race.ELF, Profession.WIZARD, strength=15, dexterity=20, hp=70)),
    ]
    return Party(members, x=10, y=10, transport=Transport.FOOT)


def _make_ow(asset_mgr, sample_party, monkeypatch, patch_move=True):
    """Overworld screen with gates disabled. Random encounters are off so the
    move path never runs creatures implicitly — tests drive _update_creatures
    directly, Java-style."""
    o = OverworldScreen(
        party=sample_party,
        map_id=0,
        asset_mgr=asset_mgr,
        start_x=10,
        start_y=10,
        random_encounters=False,
    )
    if patch_move:
        monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
    o._check_moongates = lambda: None  # type: ignore[method-assign]
    return o


@pytest.fixture
def ow(asset_mgr, sample_party, monkeypatch):
    return _make_ow(asset_mgr, sample_party, monkeypatch)


@pytest.fixture
def ow_real_move(asset_mgr, sample_party, monkeypatch):
    """Keeps the REAL can_move_to (for hasShipObjectAt boarding entry)."""
    return _make_ow(asset_mgr, sample_party, monkeypatch, patch_move=False)


@pytest.fixture
def combat_trigger(monkeypatch):
    """Captures _trigger_combat calls instead of building a CombatScreen."""
    calls: list[tuple[str, dict | None]] = []

    def _capture(self, creature_name, creature=None):
        calls.append((creature_name, creature))

    monkeypatch.setattr(OverworldScreen, "_trigger_combat", _capture)
    return calls


def water_tile(asset_mgr):
    t = asset_mgr.get_tile_by_name("water")
    assert t is not None and t.sailable and t.swimmable
    return t


def key_move(screen, direction):
    k = {
        Direction.NORTH: pygame.K_UP,
        Direction.SOUTH: pygame.K_DOWN,
        Direction.WEST: pygame.K_LEFT,
        Direction.EAST: pygame.K_RIGHT,
    }[direction]
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=""))


class TestAdjacencyEngagement:
    """BaseMap.java:540-558 — attack-capable creatures engage at distance <= 1
    (wrapping distance), not only on same-tile contact."""

    def test_adjacent_non_pirate_engages(self, ow, sample_party, combat_trigger):
        ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 11, "y": 10}]
        ow._update_creatures()
        assert [c[0] for c in combat_trigger] == ["orc"]
        assert ow.creatures == []  # engaged creature removed (Java 447/556)

    def test_diagonal_adjacent_does_not_engage(self, ow, sample_party, combat_trigger):
        """Java's movementDistance (Utils.java:314-357) walks one axis per
        step — a diagonal neighbour is distance 2, so it does NOT engage."""
        ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 11, "y": 11}]
        ow._update_creatures()
        assert combat_trigger == []
        assert len(ow.creatures) == 1

    def test_same_tile_engages_and_is_purged(self, ow, combat_trigger):
        ow.creatures = [{"tile_name": "giant", "tile": "giant", "x": 10, "y": 10}]
        ow._update_creatures()
        assert [c[0] for c in combat_trigger] == ["giant"]

    def test_distance_two_does_not_engage_yet(self, ow, sample_party, combat_trigger):
        ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 12, "y": 10}]
        ow._update_creatures()
        assert combat_trigger == []
        assert len(ow.creatures) == 1

    def test_wontattack_creature_adjacent_does_not_engage(self, ow, sample_party, combat_trigger):
        """BaseMap.java:542-553 — wontattack creatures never battle."""
        ow.creatures = [
            {"tile_name": "horse", "tile": "horse", "x": 11, "y": 10, "wontattack": True}
        ]
        ow._update_creatures()
        assert combat_trigger == []


class TestFaithfulBreak:
    """BaseMap.java:532-533 / 553-557 — the loop BREAKS at the first
    engagement: creatures after the engaging one get no movement tick and
    are not silently deleted that tick."""

    def test_farther_creature_unticked_and_survives(self, ow, sample_party, combat_trigger, asset_mgr):
        # Ensure the farther orc's whole lane is walker-friendly (the real
        # map has water at (18..19, 10)).
        land = asset_mgr.get_tile_by_name("grass")
        for x in (13, 14):
            ow.game_map.set_tile(x, 10, land)
        ow.creatures = [
            {"tile_name": "orc", "tile": "orc", "x": 11, "y": 10},  # adjacent: engages
            {"tile_name": "orc", "tile": "orc", "x": 14, "y": 10},  # would march west
        ]
        ow._update_creatures()
        assert [c[0] for c in combat_trigger] == ["orc"]
        assert len(combat_trigger) == 1
        farther = [c for c in ow.creatures if c["x"] == 14]
        assert len(farther) == 1  # present, un-deleted
        assert farther[0]["y"] == 10 and farther[0]["x"] == 14  # no movement tick

        # Next tick (engaged creature gone) the farther one finally marches.
        ow._update_creatures()
        assert [c for c in ow.creatures if c["tile_name"] == "orc"][0]["x"] == 13

    def test_two_adjacent_engage_same_tick_only_first_battles(
        self, ow, sample_party, combat_trigger
    ):
        ow.creatures = [
            {"tile_name": "orc", "tile": "orc", "x": 9, "y": 10},
            {"tile_name": "orc", "tile": "orc", "x": 11, "y": 10},
        ]
        ow._update_creatures()
        assert [c[0] for c in combat_trigger] == ["orc"]
        assert len(combat_trigger) == 1
        # The second creature was never processed: still at (11, 10).
        assert (11, 10) in [(c["x"], c["y"]) for c in ow.creatures]


class TestPirateBroadsides:
    """BaseMap.java:511-538 — the pirate block: cannon fire at range 2-3 on a
    broadsides heading, the 1-in-2 misaligned turn, and the adjacent rules."""

    def test_pirate_fires_broadsides_aligned_at_dist_2(
        self, ow, sample_party, combat_trigger, monkeypatch
    ):
        """relDir toward the avatar (EAST), range 2, and sailDir NORTH makes
        EAST a broadsides heading: enemy cannons fire (Utils.java:403-421)
        and the pirate loses its movement tick (Java 525 continue)."""
        sample_party.transport = Transport.SHIP
        sample_party.ship_hull = 50
        monkeypatch.setattr(
            "py_exodus.screens.overworld.random.randint", lambda a, b: 0
        )
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 12,
                "y": 10,
                "sail_dir": "NORTH",
            }
        ]
        ow._update_creatures()
        assert combat_trigger == []
        assert sample_party.ship_hull == 40  # fireAt: 1-in-3 hit, damageShip(10)
        assert any("pirate" in m.lower() for m in ow.text_log.history)

    def test_pirate_broadside_hit_damages_party_when_on_foot(
        self, ow, sample_party, combat_trigger, monkeypatch
    ):
        """Utils.java:580-585 — not on a ship: damageParty(10, 25), each
        member on a coin flip."""
        monkeypatch.setattr(
            "py_exodus.screens.overworld.random.randint", lambda a, b: a
        )  # hit rolls (0..2) hit, coin flips (0..1) hit, damage (10..25) = 10
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 12,
                "y": 10,
                "sail_dir": "NORTH",
            }
        ]
        before = [m.hp for m in sample_party.members]
        ow._update_creatures()
        after = [m.hp for m in sample_party.members]
        assert after == [100 - 10, 70 - 10]  # both members lose the coin flip

    def test_pirate_turns_to_broadsides_misaligned_coin_hit(
        self, ow, sample_party, combat_trigger, monkeypatch, asset_mgr
    ):
        """BaseMap.java:526-528 — range 2-3, aligned but NOT on a broadsides
        heading: 1-in-2 turn to goBroadsides(mask)."""
        ow.game_map.set_tile(11, 10, water_tile(asset_mgr))
        ow.game_map.set_tile(12, 10, water_tile(asset_mgr))
        monkeypatch.setattr(
            "py_exodus.screens.overworld.random.randint", lambda a, b: 0
        )
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 12,
                "y": 10,
                "sail_dir": "EAST",
            }
        ]
        ow._update_creatures()
        assert combat_trigger == []  # no cannons fired
        pirate = ow.creatures[0]
        # goBroadsides(N|S) returns the first mask hit in value order (W,N,E,S):
        # NORTH (Constants.java:386-395).
        assert pirate["sail_dir"] == "NORTH"
        assert (pirate["x"], pirate["y"]) == (12, 10)  # the turn ate the tick

    def test_pirate_misaligned_coin_miss_then_rotates_instead_of_moving(
        self, ow, sample_party, combat_trigger, monkeypatch, asset_mgr
    ):
        """BaseMap.java:573-578 — with the coin miss the pirate falls through
        to movement, and the rotate-then-move rule turns sailDir without
        moving when dir != sailDir."""
        ow.game_map.set_tile(11, 10, water_tile(asset_mgr))
        ow.game_map.set_tile(12, 10, water_tile(asset_mgr))
        rolls = {"n": 0}

        def _rand(a, b):
            rolls["n"] += 1
            return 1  # first roll (coin) misses; path has no roll here

        monkeypatch.setattr(
            "py_exodus.screens.overworld.random.randint", _rand
        )
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 12,
                "y": 10,
                "sail_dir": "EAST",
            }
        ]
        ow._update_creatures()
        pirate = ow.creatures[0]
        assert (pirate["x"], pirate["y"]) == (12, 10)
        assert pirate["sail_dir"] == "WEST"  # turned toward the avatar

    def test_pirate_adjacent_aligned_battles(
        self, ow, sample_party, combat_trigger, monkeypatch
    ):
        """BaseMap.java:529-533 — distance <= 1 on a broadsides heading:
        attackAt (battle), not cannons."""
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 11,
                "y": 10,
                "sail_dir": "NORTH",
            }
        ]
        ow._update_creatures()
        assert [c[0] for c in combat_trigger] == ["pirate"]

    def test_pirate_adjacent_misaligned_turns_not_battles(
        self, ow, sample_party, combat_trigger, monkeypatch
    ):
        """BaseMap.java:534-537 — adjacent but misaligned: turn broadsides."""
        monkeypatch.setattr(
            "py_exodus.screens.overworld.random.randint", lambda a, b: 0
        )
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 11,
                "y": 10,
                "sail_dir": "EAST",
            }
        ]
        ow._update_creatures()
        assert combat_trigger == []
        assert ow.creatures[0]["sail_dir"] == "NORTH"


class TestRotateThenMove:
    """BaseMap.java:573-578 — pirates sail only when the intended dir equals
    sailDir; else the sailDir turn consumes the tick."""

    def test_rotate_first_move_next_tick(self, ow, sample_party, asset_mgr):
        for x in (10, 11, 12, 13):
            ow.game_map.set_tile(x, 14, water_tile(asset_mgr))
        ow.game_map.set_tile(10, 13, water_tile(asset_mgr))
        ow.creatures = [
            {
                "tile_name": "pirate",
                "tile": "pirate",
                "x": 10,
                "y": 14,
                "sail_dir": "EAST",
            }
        ]
        ow._update_creatures()
        pirate = ow.creatures[0]
        assert (pirate["x"], pirate["y"]) == (10, 14)  # turn tick
        assert pirate["sail_dir"] == "NORTH"
        ow._update_creatures()
        pirate = ow.creatures[0]
        assert (pirate["x"], pirate["y"]) == (10, 13)  # now it sails

    def test_non_pirate_moves_without_rotation(self, ow, sample_party):
        ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 12, "y": 10}]
        ow._update_creatures()
        assert (ow.creatures[0]["x"], ow.creatures[0]["y"]) == (11, 10)


class TestDespawn:
    """BaseMap.java:505-509 — removal beyond MAX_CREATURE_DISTANCE (24,
    Constants.java:44), whirlpools excepted."""

    def test_creature_beyond_max_distance_removed(self, ow, combat_trigger):
        ow.creatures = [{"tile_name": "orc", "tile": "orc", "x": 40, "y": 10}]
        ow._update_creatures()
        assert combat_trigger == []
        assert ow.creatures == []

    def test_whirlpool_beyond_max_distance_survives(self, ow):
        ow.creatures = [
            {"tile_name": "whirlpool", "tile": "whirlpool", "x": 40, "y": 10, "wontattack": True}
        ]
        ow._update_creatures()
        assert len(ow.creatures) == 1


class TestShorelineStall:
    """BaseMap.java:633-717 — the mask governs movement: a swimming creature
    has no valid step into land, so it stalls at the shoreline."""

    def test_sea_creature_stalls_at_shore(self, ow, sample_party, combat_trigger, asset_mgr):
        ow.game_map.set_tile(10, 12, water_tile(asset_mgr))
        # (10, 11) and (9..11, 12) stay grass: no swimmable neighbour.
        ow.creatures = [{"tile_name": "serpent", "tile": "serpent", "x": 10, "y": 12}]
        ow._update_creatures()
        assert combat_trigger == []  # distance 2: not engaged
        assert (ow.creatures[0]["x"], ow.creatures[0]["y"]) == (10, 12)

    def test_whirlpool_random_walks_water_only(self, ow, sample_party, combat_trigger, asset_mgr):
        """BaseMap.java:564-565 — wontattack creatures random-walk within the
        mask; the whirlpool is part of that set and stays on water."""
        ow.game_map.set_tile(10, 12, water_tile(asset_mgr))
        ow.creatures = [
            {"tile_name": "whirlpool", "tile": "whirlpool", "x": 10, "y": 12, "wontattack": True}
        ]
        ow._update_creatures()
        whirl = ow.creatures[0]
        assert whirl["tile_name"] == "whirlpool"
        tile = ow.game_map.get_tile(whirl["x"], whirl["y"])
        assert bool(tile.attribs & TileAttrib.SWIMMABLE)


class TestWhirlpoolEngulf:
    """Task 9's engulf scan stays: distance <= 1 wraps, and the new adjacency
    rule must not turn the whirlpool into a combat encounter."""

    def test_whirlpool_adjacent_is_not_combat(self, ow, sample_party, combat_trigger):
        ow.creatures = [
            {"tile_name": "whirlpool", "tile": "whirlpool", "x": 11, "y": 10, "wontattack": True}
        ]
        ow._update_creatures()
        assert combat_trigger == []
        assert len(ow.creatures) == 1

    def test_engulf_triggers_at_distance_one(self, ow, sample_party):
        sample_party.transport = Transport.SHIP
        sample_party.x, sample_party.y = 11, 10
        ow.creatures = [
            {"tile_name": "whirlpool", "tile": "whirlpool", "x": 12, "y": 10, "wontattack": True}
        ]
        ow._check_whirlpool_engulf()
        assert sample_party.transport == Transport.FOOT
        assert (sample_party.x, sample_party.y) == (32, 54)
        assert ow.map_id == 13


class TestFrigateBoarding:
    """R2: the dropped post-battle frigate is boardable — Java's
    hasShipObjectAt (BaseMap.java:786-793) lets a FOOT avatar enter the water
    tile holding the frigate so the exact-tile B (GameScreen.java:945-979)
    can board it."""

    def test_foot_avatar_walks_onto_frigate_water_tile(
        self, ow_real_move, sample_party, asset_mgr
    ):
        # Java truth for the dropped frigate: it sits on WATER (a pirate
        # battle is a sea battle), so this exercises the real hasShipObjectAt
        # gate on an unwalkable tile.
        ow_real_move.game_map.set_tile(10, 11, water_tile(asset_mgr))
        frig = {"tile": "frigate", "x": 10, "y": 11}
        sample_party.dynamic_objects.append(frig)
        key_move(ow_real_move, Direction.SOUTH)
        assert (sample_party.x, sample_party.y) == (10, 11)

    def test_foot_avatar_blocked_by_water_without_frigate(
        self, ow_real_move, sample_party, asset_mgr
    ):
        ow_real_move.game_map.set_tile(10, 11, water_tile(asset_mgr))
        key_move(ow_real_move, Direction.SOUTH)
        assert (sample_party.x, sample_party.y) == (10, 10)

    def test_walk_onto_then_board(self, ow_real_move, sample_party, asset_mgr):
        ow_real_move.game_map.set_tile(10, 11, water_tile(asset_mgr))
        sample_party.ship_hull = 10
        frig = {"tile": "frigate", "x": 10, "y": 11}
        sample_party.dynamic_objects.append(frig)
        key_move(ow_real_move, Direction.SOUTH)
        ow_real_move.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b, unicode="b")
        )
        assert sample_party.transport == Transport.SHIP
        assert any("Board Frigate!" in m for m in ow_real_move.text_log.history)
        assert frig not in sample_party.dynamic_objects
        assert sample_party.ship_hull == 50  # fresh frigate resets the hull

    def test_dropped_frigate_persists_through_save_round_trip(self, sample_party):
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 3, "y": 4})
        restored = Party.from_dict(sample_party.to_dict())
        assert {"tile": "frigate", "x": 3, "y": 4} in restored.dynamic_objects


class TestFrigateRenderStatic:
    """A dropped/boardable frigate must not cycle its atlas frames
    (Drawable.java:46-52 draws the first region only)."""

    def test_frigate_object_static_across_frames(self, asset_mgr, sample_party):
        from py_exodus.ui.renderer import WorldRenderer
        from py_exodus.world.loader import MapLoader

        game_map = MapLoader(asset_mgr).load_map(0)
        # Settle the frigate on a single-frame grass tile so any per-frame
        # delta is the object's, not animated water beneath it.
        game_map.set_tile(46, 18, asset_mgr.get_tile_by_name("grass"))
        renderer = WorldRenderer(asset_mgr)
        sample_party.dynamic_objects.append({"tile": "frigate", "x": 46, "y": 18})

        surf0 = pygame.Surface((176, 176))
        surf1 = pygame.Surface((176, 176))
        renderer.render_viewport(surf0, game_map, 45, 18, anim_frame=0, party=sample_party)
        renderer.render_viewport(surf1, game_map, 45, 18, anim_frame=1, party=sample_party)

        tile0 = pygame.image.tobytes(surf0.subsurface((96, 80, 16, 16)), "RGBA")
        tile1 = pygame.image.tobytes(surf1.subsurface((96, 80, 16, 16)), "RGBA")
        assert tile0 == tile1

    def test_water_tiles_still_animate(self, asset_mgr):
        from py_exodus.ui.renderer import WorldRenderer
        from py_exodus.world.loader import MapLoader

        game_map = MapLoader(asset_mgr).load_map(0)
        renderer = WorldRenderer(asset_mgr)
        surf0 = pygame.Surface((176, 176))
        surf1 = pygame.Surface((176, 176))
        renderer.render_viewport(surf0, game_map, 0, 20, anim_frame=0)
        renderer.render_viewport(surf1, game_map, 0, 20, anim_frame=1)
        assert pygame.image.tobytes(surf0, "RGBA") != pygame.image.tobytes(surf1, "RGBA")


class TestR1ReadmeWording:
    """R1 — the trap-wiring open item names only the poison/fire field cues."""

    def test_readme_field_cue_wording_updated(self):
        import pathlib

        text = pathlib.Path("README.md").read_text()
        assert "poison/fire field" in text
