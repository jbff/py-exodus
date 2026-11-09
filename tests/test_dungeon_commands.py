"""Task 10 — dungeon command surface (R/W/M/V/P/Q), movement, torch, ladders.

Java truth: DungeonScreen.java:859-1052 (movement, K/D ladders, Q/V/I/P/M
keys), SecondaryInputProcessor.java:419-437 (dungeon G/R/W/C/S member
routing), GameScreen.java:557-563 (Q save restriction).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pygame

from py_exodus.constants import (
    ArmorType,
    Direction,
    WeaponType,
)
from py_exodus.aura import AuraType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture(scope="module")
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield
    pygame.quit()


def turn_meter(party: Party):
    """Java finishTurn opens with aura.passTurn() and NEVER calls
    Party.endTurn from a dungeon (DungeonScreen.java:1124-1142) — party.moves
    does not tick while exploring, so aura decrements are the turn meter."""
    party.aura.set(AuraType.QUICKNESS, 99)
    return party.aura.get_duration


def make_dmap() -> DungeonMap:
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    tiles = []
    for z in range(8):
        grid = []
        for y in range(16):
            row = []
            for x in range(16):
                if x == 0 or x == 15 or y == 0 or y == 15:
                    row.append(DungeonTile.WALL)
                else:
                    row.append(DungeonTile.FLOOR)
            grid.append(row)
        tiles.append(grid)
    dmap.tiles = tiles
    return dmap


def make_party() -> Party:
    p = Party(food=200, gold=100)
    c1 = Character("Hero", "M", "HUMAN", "FIGHTER", hp=100, max_hp=100, torches=5)
    c2 = Character("Mage", "F", "ELF", "WIZARD", hp=80, max_hp=80, torches=0)
    p.add_member(c1)
    p.add_member(c2)
    return p


def make_screen(party: Party | None = None, dmap: DungeonMap | None = None) -> DungeonScreen:
    return DungeonScreen(
        party=party or make_party(),
        dungeon_map=dmap or make_dmap(),
        map_id=99,
        asset_mgr=None,
        audio=MagicMock(),
    )


def press(screen: DungeonScreen, key: int) -> None:
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))


# --- (a) new command keys R / W / M / V / P / Q ------------------------


def test_dungeon_r_ready_weapon(pygame_setup):
    party = make_party()
    party.members[0].weapons[WeaponType.DAGGER] = 1
    party.members[0].weapon = WeaponType.NONE
    scr = make_screen(party)

    moves_before = party.moves
    ticks = turn_meter(party)
    press(scr, pygame.K_r)
    # Java DungeonScreen.java:1011-1013: the G/R/W/C/S branch falls through
    # to finishTurn, so pressing R itself consumes a turn.
    assert party.moves == moves_before
    assert ticks() == 98
    assert scr.text_log.is_waiting_for_input
    scr.text_log.submit_input("1")
    assert any("Ready Weapon for" in m for m in scr.text_log.history)
    scr.text_log.submit_input("B")  # B = DAGGER (2nd WeaponType entry)
    assert party.members[0].weapon == WeaponType.DAGGER
    assert any("Success!" in m for m in scr.text_log.history)  # SIP:479-483
    # Java SecondaryInputProcessor: R press falls through (1 tick), then
    # ReadyWearInputAdapter.keyUp runs finishTurn after the letter (tick 2).
    assert ticks() == 97


def test_dungeon_w_wear_armor(pygame_setup):
    party = make_party()
    party.members[1].armors[ArmorType.LEATHER] = 1
    party.members[1].armor = ArmorType.NONE
    scr = make_screen(party)

    press(scr, pygame.K_w)
    scr.text_log.submit_input("2")
    assert any("Wear Armor for" in m for m in scr.text_log.history)
    scr.text_log.submit_input("C")  # C = LEATHER (3rd ArmorType entry)
    assert party.members[1].armor == ArmorType.LEATHER
    assert any("Success!" in m for m in scr.text_log.history)

    # Java SIP:455-483 — a failed wear logs exactly "Failed!"
    scr = make_screen(party)
    press(scr, pygame.K_w)
    scr.text_log.submit_input("2")
    scr.text_log.submit_input("D")  # D = CHAIN, not owned
    assert any(m == "Failed!" for m in scr.text_log.history)


def test_dungeon_m_modify_order(pygame_setup):
    party = make_party()
    scr = make_screen(party)
    moves_before = party.moves

    press(scr, pygame.K_m)
    assert any("exhange #:" in m for m in scr.text_log.history)  # Java DungeonScreen.java:1028 typo
    assert scr.text_log.is_waiting_for_input
    scr.text_log.submit_input("1")
    scr.text_log.submit_input("2")
    assert party.members[0].name == "Mage"
    assert party.members[1].name == "Hero"
    # Java DungeonScreen.java:1024-1031 — M returns false; NewOrderInputAdapter
    # only finishes the turn from GameScreen, never from DungeonScreen.
    assert party.moves == moves_before


def test_dungeon_v_music_toggle(pygame_setup):
    scr = make_screen()
    audio = scr.audio
    enabled_before = audio.enabled
    ticks = turn_meter(scr.party)

    press(scr, pygame.K_v)
    assert audio.enabled != enabled_before
    # Java DungeonScreen.java:1013-1023 — V falls through to finishTurn.
    assert ticks() == 98


def test_dungeon_p_minimap_toggle(pygame_setup):
    scr = make_screen()
    ticks = turn_meter(scr.party)

    press(scr, pygame.K_p)
    # Java DungeonScreen.java:80 + 1012-1015 — P toggles the minimap; the
    # key falls through to finishTurn.
    assert ticks() == 98


def test_dungeon_q_saves_and_logs(pygame_setup, monkeypatch, tmp_path):
    party = make_party()
    scr = make_screen(party)
    scr.state.x, scr.state.y, scr.state.z = 7, 7, 2

    saved: dict = {}

    def fake_save(party_obj, path, extra=None):
        saved["called"] = True
        saved["party"] = party_obj
        saved["path"] = path
        saved["extra"] = extra

    from py_exodus import save_system

    monkeypatch.setattr(save_system.SaveSystem, "save_game", staticmethod(fake_save))

    moves_before = party.moves
    press(scr, pygame.K_q)
    assert any("Saved Game." in m for m in scr.text_log.history)
    assert saved["called"]
    assert saved["party"] is party
    assert saved["extra"]["dungeon"]["x"] == 7
    assert saved["extra"]["dungeon"]["level"] == 2
    # Java DungeonScreen.java:976-986 — Q returns false before the keyUp
    # tail, so saving does not consume a turn.
    assert party.moves == moves_before


# --- (b) DOWN arrow = one step backward, not a 180-degree turn ---------


def test_dungeon_down_arrow_backsteps(pygame_setup):
    scr = make_screen()
    scr.state.x, scr.state.y = 5, 5
    scr.state.dir = Direction.EAST
    moves_before = scr.party.moves
    ticks = turn_meter(scr.party)

    press(scr, pygame.K_DOWN)
    assert scr.state.x == 4
    assert scr.state.y == 5
    assert scr.state.dir == Direction.EAST
    assert ticks() == 98


def test_dungeon_down_arrow_backstep_wraps(pygame_setup):
    dmap = make_dmap()
    dmap.set_tile(15, 5, 0, DungeonTile.FLOOR)  # the wrapped target is open
    scr = make_screen(dmap=dmap)
    scr.state.x, scr.state.y = 0, 5
    scr.state.z = 0
    scr.state.dir = Direction.EAST

    press(scr, pygame.K_DOWN)
    assert scr.state.x == 15  # wrapped, not turned to WEST
    assert scr.state.dir == Direction.EAST


def test_dungeon_left_right_change_facing_without_turn_tick(pygame_setup):
    scr = make_screen()
    scr.state.dir = Direction.NORTH
    moves_before = scr.party.moves

    press(scr, pygame.K_LEFT)
    assert scr.state.dir == Direction.WEST
    # Java DungeonScreen.java:861-912 — LEFT/RIGHT only rotate the camera
    # and return before finishTurn; facing changes never consume a turn.
    assert scr.party.moves == moves_before


# --- (c) torch is a boolean toggle, not a rounds/dim model --------------


def test_dungeon_torch_toggle_consumption(pygame_setup):
    party = make_party()
    scr = make_screen(party)
    scr.state.x, scr.state.y = 5, 5
    scr.state.z = 0
    ticks = turn_meter(party)

    press(scr, pygame.K_i)
    assert scr.state.is_torch_on is True
    assert party.members[0].torches == 4  # one torch consumed
    assert not hasattr(scr.state, "torch_rounds")
    assert ticks() == 98  # Java I key falls through to finishTurn

    press(scr, pygame.K_i)
    assert scr.state.is_torch_on is False
    assert party.members[0].torches == 4  # extinguishing consumes no torch
    assert ticks() == 97

    party.members[0].torches = 0
    scr.state.is_torch_on = False
    press(scr, pygame.K_i)
    assert scr.state.is_torch_on is False
    assert any("No Torches!" in m for m in scr.text_log.history)


def test_dungeon_torch_spell_and_key_share_one_boolean(pygame_setup):
    scr = make_screen()
    # Java: LORUM/LUMINAE set isTorchOn=True; pressing I then extinguishes.
    scr.state.light_spell = True
    assert scr.state.is_torch_on is True
    scr.state.is_torch_on = False
    assert scr.state.light_spell is False


def test_dungeon_wind_trap_extinguishes_boolean(pygame_setup):
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, DungeonTile.WIND_TRAP)
    party = make_party()
    state = DungeonState(dmap, start_x=5, start_y=5, start_z=0, start_dir=Direction.NORTH, party=party)
    state.is_torch_on = True

    ev = state.move_forward()
    assert ev.type == DungeonEventType.WIND_TRAP
    assert state.is_torch_on is False
    assert not hasattr(state, "torch_rounds")


# --- unhandled keys consume a turn ("Pass") ----------------------------


def test_dungeon_unhandled_keys_pass_and_consume_turn(pygame_setup):
    party = make_party()
    scr = make_screen(party)
    ticks = turn_meter(party)

    press(scr, pygame.K_u)  # removed alias; Java dungeon has no U handler
    assert any("Pass" in m for m in scr.text_log.history)
    assert ticks() == 98

    press(scr, pygame.K_t)  # torch is keyed I in Java; T is unhandled
    assert ticks() == 97

    press(scr, pygame.K_SPACE)
    assert ticks() == 96


def test_dungeon_ladders_do_not_consume_turns(pygame_setup):
    party = make_party()
    scr = make_screen(party)
    scr.dungeon_map.set_tile(scr.state.x, scr.state.y, scr.state.z, DungeonTile.LADDER_DOWN)
    moves = party.moves

    press(scr, pygame.K_d)
    assert scr.state.z == 1
    assert any("Climbed down" in m for m in scr.text_log.history)
    # Java DungeonScreen.java:959-982 — K/D return false before finishTurn.
    assert party.moves == moves

    scr.dungeon_map.set_tile(scr.state.x, scr.state.y, scr.state.z, DungeonTile.LADDER_UP)
    press(scr, pygame.K_k)
    assert scr.state.z == 0
    assert party.moves == moves


# --- (e) ladder bounds clamp (Java DungeonScreen.java:959-982) ---------


def test_deepest_ladder_down_clamps_at_dungeon_levels():
    dmap = make_dmap()  # levels == 8 == Java DUNGEON_LVLS
    dmap.set_tile(5, 5, 7, DungeonTile.LADDER_DOWN)
    state = DungeonState(dmap, start_x=5, start_y=5, start_z=7)

    ev = state.klimb_down()
    assert ev.type == DungeonEventType.LADDER_DOWN
    # Java clamps currentLevel at DUNGEON_LVLS (8): the descent from level 7
    # is accepted, clamped one level past the last playable grid.
    assert state.z == 8


def test_ladder_up_at_surface_exits():
    dmap = make_dmap()
    dmap.set_tile(5, 5, 0, DungeonTile.LADDER_UP)
    state = DungeonState(dmap, start_x=5, start_y=5, start_z=0)

    ev = state.klimb_up()
    assert ev.type == DungeonEventType.EXIT_DUNGEON
    assert state.z == 0


def test_town_r_w_m_use_shared_member_flow(pygame_setup, asset_mgr):
    """Java town = GameScreen keyUp: R/W route to the shared
    SecondaryInputProcessor flow (one finishTurn at the ReadyWear letter,
    SecondaryInputProcessor.java:455-484) and M to NewOrderInputAdapter (one
    finishTurn after the second digit, BaseScreen.java:196-204). Town must
    not keep its own zero-turn forks."""
    from py_exodus.screens.town import TownScreen

    party = make_party()
    party.members[0].weapons[WeaponType.DAGGER] = 1
    party.members[0].armors[ArmorType.LEATHER] = 1
    town = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr)
    moves = party.moves

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    town.text_log.submit_input("1")
    town.text_log.submit_input("B")  # B = DAGGER
    assert party.members[0].weapon == WeaponType.DAGGER
    assert any(m == "Success!" for m in town.text_log.history)
    # The R press itself returns false on GameScreen; the finishTurn fires
    # once at the ReadyWear letter.
    assert party.moves == moves + 1

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w))
    town.text_log.submit_input("1")
    town.text_log.submit_input("C")  # C = LEATHER
    assert party.members[0].armor == ArmorType.LEATHER
    assert party.moves == moves + 2

    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m))
    assert any("exchange #:" in m for m in town.text_log.history)  # GameScreen-corrected spelling
    town.text_log.submit_input("1")
    town.text_log.submit_input("2")
    assert party.members[0].name == "Mage"
    assert party.moves == moves + 3  # NewOrderInputAdapter finishTurn


# --- overworld / town save restrictions and unhandled keys -------------


def test_overworld_save_allowed_only_on_sosaria(pygame_setup, asset_mgr, monkeypatch, tmp_path):
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus import save_system

    calls: list = []
    monkeypatch.setattr(
        save_system.SaveSystem, "save_game", staticmethod(lambda *a, **k: calls.append(a))
    )

    sosaria = OverworldScreen(party=make_party(), map_id=0, asset_mgr=asset_mgr)
    sosaria.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert any("Saved Game." in m for m in sosaria.text_log.history)
    assert calls  # save happened

    ambrosia = OverworldScreen(party=make_party(), map_id=13, asset_mgr=asset_mgr)
    ambrosia.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert any("Cannot save here!" in m for m in ambrosia.text_log.history)
    assert len(calls) == 1  # no save outside Sosaria


def test_town_save_always_refused(pygame_setup, asset_mgr):
    from py_exodus.screens.town import TownScreen

    town = TownScreen(party=make_party(), map_id=1, asset_mgr=asset_mgr)
    town.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
    assert any("Cannot save here!" in m for m in town.text_log.history)


def test_overworld_b_x_e_f_fall_through_ticks(pygame_setup, asset_mgr):
    """Java GameScreen keyUp tail — B and X have no early return (every press
    consumes a turn), E consumes a turn only when no portal is on the tile,
    and F off-ship falls through silently with no invented message."""
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.constants import Transport

    ow = OverworldScreen(party=make_party(), map_id=0, asset_mgr=asset_mgr)
    party = ow.party
    moves = party.moves

    # F not on a ship: silent tail turn (GameScreen.java:531-536 + 628)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    assert not any("Only frigates" in m for m in ow.text_log.history)
    assert party.moves == moves + 1

    # X on foot: Java X is silent but the keyUp tail still ticks
    # (GameScreen.java:584-596 + 628)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x))
    assert not any("Already on foot" in m for m in ow.text_log.history)
    assert party.moves == moves + 2

    # B with nothing to board: "Board What?" + tail turn (GameScreen.java:578-580)
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert any(m == "Board What?" for m in ow.text_log.history)
    assert party.moves == moves + 3

    # B already mounted: "Board: Can't!" + tail turn
    party.transport = Transport.HORSE
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    assert any("Board: Can't!" in m for m in ow.text_log.history)
    assert party.moves == moves + 4
    party.transport = Transport.FOOT

    # E with a portal: early return, no turn consumed (GameScreen.java:538-556)
    from py_exodus.entities.defs import PortalDef
    ow.game_map.portals.append(PortalDef(x=party.x, y=party.y, dest_map_id=0, start_x=party.x, start_y=party.y))
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))
    assert party.moves == moves + 4

    # E with no portal: silent tail turn
    ow.game_map.portals.clear()
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e))
    assert party.moves == moves + 5


def test_overworld_d_i_k_are_unhandled_consumes_turn(pygame_setup, asset_mgr):
    from py_exodus.screens.overworld import OverworldScreen

    ow = OverworldScreen(party=make_party(), map_id=0, asset_mgr=asset_mgr)
    party = ow.party
    moves = party.moves

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i))
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_k))
    assert ow.text_log.history[-3:] == [] or not any(
        ("Descend:" in m or "Klimb:" in m or "Torch ignited" in m) for m in ow.text_log.history
    )
    assert party.moves == moves + 3
    assert party.members[0].torches == 5  # I no longer invents a torch burn


def test_dungeon_g_c_s_press_consumes_turn(pygame_setup):
    scr = make_screen()
    ticks = turn_meter(scr.party)
    press(scr, pygame.K_s)
    assert ticks() == 98
    scr.text_log.handle_escape()
    ticks = turn_meter(scr.party)
    press(scr, pygame.K_c)
    assert ticks() == 98
