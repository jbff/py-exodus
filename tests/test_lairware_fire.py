"""LairWare's ship cannon and sailing (UltimaMain.c Fire, North()/ValidTrans).

User 2026-11-22: "allow fire in any of 4 directions and not bother to track
heading". LairWare's Fire: only aboard a ship ("Fire <-WHAT?" otherwise),
any direction, up to three tiles wrapping round the map, the first monster in
the path is hit half the time (a pirate shrugs off half of those) and
"destroyed!"; empty ships don't stop the shot. Ships sail straight off in any
direction the wind allows, with no turn-to-face press. Pirates and dragons
fire back (moveshoot), at the crew: LairWare ships have no hull.
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.overworld import OverworldScreen


@pytest.fixture
def ow(monkeypatch):
    pygame.init()
    am = AssetManager(assets_dir="assets")
    am.load_tiles()
    am.load_xml_definitions()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100)
    party = Party([PartyMember(hero)], x=20, y=20, gold=500, transport=Transport.SHIP)
    o = OverworldScreen(party=party, map_id=0, asset_mgr=am, start_x=20, start_y=20,
                        random_encounters=False)
    o.creatures = []
    monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
    o._check_moongates = lambda: None  # type: ignore[method-assign]
    return o


def _rolls(monkeypatch, *values):
    seq = list(values)
    monkeypatch.setattr(overworld_module.random, "randint", lambda a, b: seq.pop(0))


@pytest.mark.parametrize("d", [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST])
def test_fires_in_any_direction_and_destroys_on_a_high_roll(ow, monkeypatch, d):
    ow.creatures = [{"tile_name": "orc", "x": 20 + 2 * d.dx, "y": 20 + 2 * d.dy}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(d)
    assert ow.creatures == []
    assert "Orcs destroyed!" in ow.text_log.history
    assert ow.cannon_fx[0]["hit"] is True


def test_a_low_roll_misses_silently_and_stops_the_shot(ow, monkeypatch):
    orc = {"tile_name": "orc", "x": 21, "y": 20}
    behind = {"tile_name": "orc", "x": 22, "y": 20}
    ow.creatures = [orc, behind]
    _rolls(monkeypatch, 10)
    ow._fire_cannons(Direction.EAST)
    assert ow.creatures == [orc, behind]
    assert not any("destroyed" in m for m in ow.text_log.history)


def test_a_pirate_shrugs_off_half_the_hits(ow, monkeypatch):
    """LairWare checks Monsters[store] == 0x3C: map value 0x3C is the Pirate
    (tile 15), so pirates take a second roll; Balrons don't."""
    ow.creatures = [{"tile_name": "pirate", "x": 21, "y": 20}]
    _rolls(monkeypatch, 10)  # the pirate's own roll: shot shrugged off
    ow._fire_cannons(Direction.EAST)
    assert len(ow.creatures) == 1
    _rolls(monkeypatch, 200, 200)
    ow._fire_cannons(Direction.EAST)
    assert ow.creatures == [] and "Pirates destroyed!" in ow.text_log.history
    ow.creatures = [{"tile_name": "balron", "x": 21, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.EAST)
    assert ow.creatures == []


def test_range_is_three_tiles(ow, monkeypatch):
    ow.creatures = [{"tile_name": "serpent", "x": 24, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.EAST)
    assert len(ow.creatures) == 1
    assert ow.cannon_fx[0]["path"] == [(21, 20), (22, 20), (23, 20)]


def test_the_shot_wraps_round_the_map_edge(ow, monkeypatch):
    ow.party.x = 1
    ow.creatures = [{"tile_name": "squid", "x": 63, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.WEST)
    assert ow.creatures == [] and "Man-O-Wars destroyed!" in ow.text_log.history


def test_empty_ships_do_not_stop_the_shot(ow, monkeypatch):
    frigate = {"tile": "frigate", "x": 21, "y": 20, "hull": 50}
    ow.party.dynamic_objects.append(frigate)
    ow.creatures = [{"tile_name": "pirate", "x": 22, "y": 20}]
    _rolls(monkeypatch, 200, 200)
    ow._fire_cannons(Direction.EAST)
    assert frigate["hull"] == 50 and ow.creatures == []


def test_a_variant_is_named_in_the_plural(ow, monkeypatch):
    ow.creatures = [{"tile_name": "thief", "variant": 2, "x": 21, "y": 20}]
    _rolls(monkeypatch, 200)
    ow._fire_cannons(Direction.EAST)
    assert "Cutpurses destroyed!" in ow.text_log.history


def test_fire_on_foot_is_what(ow):
    ow.party.transport = Transport.FOOT
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f, unicode="f"))
    assert "Fire <-WHAT?" in ow.text_log.history


def test_cannon_fx_flies_and_clears(ow):
    ow._fire_cannons(Direction.NORTH)
    fx = ow.cannon_fx[0]
    assert fx["path"] == [(20, 19), (20, 18), (20, 17)] and fx["hit"] is False
    ow.update(0.40)
    assert ow.cannon_fx == []


def test_a_ship_sails_straight_off_without_turning(ow):
    ow.party.wind_direction = Direction.SOUTH
    for d, (x, y) in ((Direction.EAST, (21, 20)), (Direction.NORTH, (21, 19)),
                      (Direction.WEST, (20, 19))):
        ow._move_avatar(d)
        assert (ow.party.x, ow.party.y) == (x, y)
    assert not hasattr(ow, "heading")


# --- Monsters that shoot: LairWare moveshoot (UltimaMisc.c:1245-1278) ---


def _open_water(ow, x0=14, x1=27, y0=14, y1=27):
    water = ow.asset_mgr.get_tile_by_name("water")
    for x in range(x0, x1):
        for y in range(y0, y1):
            ow.game_map.set_tile(x, y, water)


@pytest.mark.parametrize("dx,dy", [(3, 0), (0, -3), (-2, 0), (2, 2), (-3, 3)])
def test_pirates_fire_along_rows_columns_and_diagonals(ow, monkeypatch, dx, dy):
    _open_water(ow)
    hp = [m.hp for m in ow.party.members]
    _rolls(monkeypatch, 100, 0)  # fires (<= 127); damage roll 0 & 0x77
    ow._lw_monster_shoot({"tile_name": "pirate", "x": 20 + dx, "y": 20 + dy})
    assert [m.hp for m in ow.party.members] == [h - 8 for h in hp]
    assert ow.cannon_fx[-1]["hit"] is True and ow.cannon_fx[-1]["path"][-1] == (20, 20)


def test_the_bomb_is_rand_and_0x77_plus_8_on_every_living_member(ow, monkeypatch):
    _open_water(ow)
    hero = ow.party.members[0]
    hero.hp = 500
    _rolls(monkeypatch, 0, 255)
    ow._lw_monster_shoot({"tile_name": "dragon", "x": 22, "y": 20})
    assert hero.hp == 500 - (0x77 + 8)


def test_half_the_time_they_hold_fire(ow, monkeypatch):
    _open_water(ow)
    _rolls(monkeypatch, 128)
    ow._lw_monster_shoot({"tile_name": "pirate", "x": 22, "y": 20})
    assert ow.cannon_fx == [] and ow.party.members[0].hp == 100


def test_off_line_shots_miss_and_range_is_three(ow, monkeypatch):
    _open_water(ow)
    _rolls(monkeypatch, 0)
    ow._lw_monster_shoot({"tile_name": "pirate", "x": 23, "y": 21})  # knight's move
    _rolls(monkeypatch, 0)
    ow._lw_monster_shoot({"tile_name": "pirate", "x": 24, "y": 20})  # 4 away
    assert ow.party.members[0].hp == 100
    assert all(not fx["hit"] for fx in ow.cannon_fx)


def test_mountains_stop_the_shot(ow, monkeypatch):
    _open_water(ow)
    ow.game_map.set_tile(21, 20, ow.asset_mgr.get_tile_by_name("mountains"))
    _rolls(monkeypatch, 0)
    ow._lw_monster_shoot({"tile_name": "pirate", "x": 22, "y": 20})
    assert ow.party.members[0].hp == 100


def test_a_lethal_bomb_kills(ow, monkeypatch):
    _open_water(ow)
    ow.party.members[0].hp = 5
    _rolls(monkeypatch, 0, 0)
    ow._lw_monster_shoot({"tile_name": "pirate", "x": 22, "y": 20})
    assert ow.party.members[0].is_dead()  # HPSubtract: under 1 HP is dead


def test_pirates_close_in_and_fire_each_turn(ow, monkeypatch):
    """A pirate moves like any monster (no turning to sail) and then fires;
    LairWare ships have no hull, so the crew takes it."""
    _open_water(ow)
    monkeypatch.setattr(overworld_module.random, "randint", lambda a, b: 0)
    ow.random_encounters_enabled = False
    ow.creatures = [{"tile_name": "pirate", "tile": "pirate", "x": 24, "y": 20}]
    ow._update_creatures()
    assert (ow.creatures[0]["x"], ow.creatures[0]["y"]) == (23, 20)
    assert ow.party.members[0].hp == 92
    assert not hasattr(ow.party, "ship_hull")


def test_a_shot_passes_through_the_whirlpool_and_never_removes_it(ow, monkeypatch):
    """LairWare Fire stops only where MonsterHere finds a monster
    (UltimaMain.c:1541-1543), and MonsterHere scans Monsters[] alone
    (UltimaMisc.c:429-442); the whirlpool is WhirlX/WhirlY, outside that
    table, so a shot flies through it. User live trace 2026-11-25
    (trace_20261125-184644, step ~110,048): autoplay fired at a sea monster
    with the whirlpool between, "Whirlpools destroyed!", and Sosaria had no
    whirlpool for the rest of the run."""
    wp = ow._lw_start_whirlpool()
    wp["x"], wp["y"] = 20, 21
    squid = {"tile_name": "squid", "x": 20, "y": 22}
    ow.creatures = [wp, squid]
    _rolls(monkeypatch, 200, 200, 200)
    ow._fire_cannons(Direction.SOUTH)
    assert wp in ow.creatures
    assert squid not in ow.creatures
    ow.creatures = [wp]
    _rolls(monkeypatch, 200, 200, 200)
    ow._fire_cannons(Direction.SOUTH)
    assert ow.creatures == [wp]
    assert not any("Whirlpool" in m for m in ow.text_log.history)


def test_attack_never_takes_the_whirlpool(ow):
    """LairWare Attack: ``monNum = MonsterHere(xs, ys); if (monNum == 255)
    NotHere();`` (UltimaMain.c:1329-1340): no fight with the whirlpool, and it
    stays."""
    wp = ow._lw_start_whirlpool()
    wp["x"], wp["y"] = 21, 20
    ow.creatures = [wp]
    ow._prompt_attack_overworld()
    ow.text_log._callback("E")
    assert ow.creatures == [wp]


def test_coming_back_onto_the_whirlpool_tile_keeps_it(ow):
    """on_enter's purge of creatures on the party's tile (a fight's monster)
    must not drop the whirlpool: back from a town or a fight with the
    whirlpool drifted onto the party's tile, Sosaria still has it."""
    wp = ow._lw_start_whirlpool()
    wp["x"], wp["y"] = 20, 20
    orc = {"tile_name": "orc", "x": 20, "y": 20}
    ow.creatures = [wp, orc]
    ow.on_enter()
    assert ow.creatures == [wp]
