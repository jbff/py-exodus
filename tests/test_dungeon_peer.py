"""Dungeon Peer (P), Vieda and the Stone view at screen level.

User ruling 2026-11-26: with a useful first-person view there is no free
overhead plan any more. The level map costs a gem or a spell.

- P is LairWare dPeer (UltimaDngn.c:440-454): whose gem (message 75); a key
  outside 1-4 returns; a member with none gets message 67 and keeps
  everything; otherwise one gem goes and DrawMiniDng(0) shows the level
  until a key is pressed. Every dungeon command ends in dungeonmech
  (UltimaDngn.c:149, 161, 183), so the turn passes in all three cases.
- Vieda in a dungeon shows the same map (UltimaSpellCombat.c:322-327).
- DrawMiniDng (UltimaGraphics.c:1526-1586) maps byte values to pieces; a
  secret door (0xA0, piece 1) is not a wall (0x80, piece 2).
- The PEER cheat (debug menu) makes P show the map anywhere, for no gem.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pygame
import pytest

from py_exodus import debug
from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, MapType, Profession, Race, Spell
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.ui import gem_view
from py_exodus.world.map import DungeonMap, DungeonTile


@pytest.fixture(scope="module", autouse=True)
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield


@pytest.fixture
def cheat_state():
    saved = (debug.DEBUG_MODE, dataclasses.replace(debug.CHEATS))
    yield debug.CHEATS
    debug.DEBUG_MODE, state = saved
    for f in dataclasses.fields(debug.CHEATS):
        setattr(debug.CHEATS, f.name, getattr(state, f.name))


def make_dmap() -> DungeonMap:
    dmap = DungeonMap(id=99, name="TestDungeon", width=16, height=16, levels=8)
    dmap.tiles = [
        [
            [
                DungeonTile.WALL if x in (0, 15) or y in (0, 15) else DungeonTile.FLOOR
                for x in range(16)
            ]
            for y in range(16)
        ]
        for _z in range(8)
    ]
    return dmap


def make_party() -> Party:
    p = Party(food=200, gold=100)
    p.add_member(Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=100, max_hp=100, torches=5))
    p.add_member(Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=60, hp=80, max_hp=80))
    return p


def make_screen(party: Party | None = None, dmap: DungeonMap | None = None, lit: bool = True) -> DungeonScreen:
    scr = DungeonScreen(
        party=party or make_party(),
        dungeon_map=dmap or make_dmap(),
        map_id=99,
        asset_mgr=None,
        audio=MagicMock(),
        start_x=5,
        start_y=5,
    )
    scr.state.random_encounters_enabled = False
    scr.state.torchtime = 200 if lit else 0
    scr.state.dir = Direction.NORTH
    return scr


def press(screen, key: int) -> None:
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))


def turn_meter(party: Party):
    """dungeonmech runs AgeChars once per command: count the calls."""
    turns = [0]
    real = party.age_chars

    def counted(*a, **k):
        turns[0] += 1
        return real(*a, **k)

    party.age_chars = counted
    return lambda: turns[0]


def frame(scr, size=(960, 600)) -> pygame.Surface:
    surf = pygame.Surface(size)
    scr.render(surf)
    return surf


def same(a: pygame.Surface, b: pygame.Surface, rect: pygame.Rect) -> bool:
    return pygame.image.tobytes(a.subsurface(rect), "RGB") == pygame.image.tobytes(b.subsurface(rect), "RGB")


PANE = pygame.Rect(0, 0, 528, 528)


# --- P: LairWare dPeer -------------------------------------------------------


def test_p_spends_one_gem_of_the_chosen_member_only():
    scr = make_screen()
    scr.party.members[0].gems = 3
    scr.party.members[1].gems = 2
    press(scr, pygame.K_p)
    assert "Whose gem?" in scr.text_log.current_prompt
    scr.text_log.handle_char("2")
    assert scr.party.members[0].gems == 3
    assert scr.party.members[1].gems == 1
    assert scr.gem_view_active is True


def test_p_with_no_gems_says_so_and_spends_nothing():
    scr = make_screen()
    scr.party.members[1].gems = 4
    turns = turn_meter(scr.party)
    press(scr, pygame.K_p)
    scr.text_log.handle_char("1")  # Hero has none
    assert "None left!" in scr.text_log.history[-1]
    assert scr.gem_view_active is False
    assert scr.party.members[1].gems == 4
    assert scr.party.gems == 4
    assert turns() == 1  # dungeonmech still follows


@pytest.mark.parametrize("answer", ["X", "5", "0", " "])
def test_p_cancelled_by_a_key_outside_1_to_4_spends_nothing(answer):
    scr = make_screen()
    for m in scr.party.members:
        m.gems = 2
    turns = turn_meter(scr.party)
    press(scr, pygame.K_p)
    scr.text_log.handle_char(answer)
    assert scr.gem_view_active is False
    assert [m.gems for m in scr.party.members] == [2, 2]
    assert not scr.text_log.is_waiting_for_input
    assert turns() == 1


def test_map_shows_then_any_key_returns_to_the_view():
    scr = make_screen()
    scr.party.members[0].gems = 1
    view = frame(scr)
    turns = turn_meter(scr.party)
    press(scr, pygame.K_p)
    scr.text_log.handle_char("1")
    assert scr.gem_view_active
    assert turns() == 0  # the turn follows the map (dPeer, then dungeonmech)
    mapped = frame(scr)
    assert not same(view, mapped, PANE)

    # Any key ends the map and is swallowed: Up does not move the party.
    press(scr, pygame.K_UP)
    assert scr.gem_view_active is False
    assert (scr.state.x, scr.state.y) == (5, 5)
    assert turns() == 1
    assert same(view, frame(scr), PANE)
    # and the next key is a command again
    press(scr, pygame.K_UP)
    assert (scr.state.x, scr.state.y) == (5, 4)


def test_map_is_the_whole_level_with_a_blinking_party_box():
    dmap = make_dmap()
    scr = make_screen(dmap=dmap)
    scr.party.members[0].gems = 1
    press(scr, pygame.K_p)
    scr.text_log.handle_char("1")
    on = frame(scr)
    cell = gem_view.peer_cell(528, 16, 16, 3)
    rect = gem_view.peer_map_rect(PANE, 16, 16, 3)
    # walls round the edge, floor inside: two different pieces
    wall = on.get_at((rect.x + cell // 2 + 3, rect.y + cell // 2 + 3))
    floor = on.get_at((rect.x + 8 * cell + cell // 2, rect.y + 8 * cell + cell // 2))
    assert wall != floor
    # the party box blinks on the 0.2 s frame: 0.4 s on, 0.4 s off
    scr.update(0.5)
    off = frame(scr)
    box = pygame.Rect(rect.x + 5 * cell, rect.y + 5 * cell, cell, cell).inflate(8, 8)
    assert not same(on, off, box)
    scr.update(0.4)
    assert same(on, frame(scr), box)
    # the party panel and the log are untouched by the map
    side = pygame.Rect(528, 0, 432, 600)
    assert same(on, off, side)


def test_map_needs_no_torch():
    scr = make_screen(lit=False)
    scr.party.members[0].gems = 1
    dark = frame(scr)
    press(scr, pygame.K_p)
    scr.text_log.handle_char("1")
    assert not same(dark, frame(scr), PANE)


def test_idle_pass_and_fixtures_wait_for_the_map():
    """DrawMiniDng waits in its own loop: no idle pass under the map, and
    the fountain's question (dungeonmech) comes when the map is gone."""
    dmap = make_dmap()
    dmap.set_tile(5, 5, 0, DungeonTile.FOUNTAIN_HEAL)
    scr = make_screen(dmap=dmap)
    scr.party.members[0].gems = 1
    turns = turn_meter(scr.party)
    press(scr, pygame.K_p)
    scr.text_log.handle_char("1")
    assert scr.gem_view_active and not scr.text_log.is_waiting_for_input
    scr.update(30.0)
    assert scr.gem_view_active and turns() == 0
    press(scr, pygame.K_SPACE)
    assert not scr.gem_view_active
    assert scr.text_log.is_waiting_for_input  # who drinks?


# --- Vieda -------------------------------------------------------------------


def test_vieda_may_be_cast_in_a_dungeon_but_not_in_combat():
    assert Spell.VIEDA.can_cast_location(MapType.DUNGEON)
    assert Spell.VIEDA.can_cast_location(MapType.WORLD)
    assert Spell.VIEDA.can_cast_location(MapType.CITY)
    assert not Spell.VIEDA.can_cast_location(MapType.COMBAT)


def test_vieda_in_a_dungeon_shows_the_map_and_charges_its_mp():
    scr = make_screen()
    cleric = scr.party.members[1]
    cleric.gems = 2
    view = frame(scr)
    press(scr, pygame.K_c)
    scr.text_log.handle_char("2")
    assert "Cleric Spell?" in scr.text_log.current_prompt
    scr.text_log.handle_char("L")
    assert "Not Here!" not in "\n".join(scr.text_log.history)
    assert scr.gem_view_active is True
    assert cleric.mp == 60 - Spell.VIEDA.cost
    assert cleric.gems == 2  # a spell, not a gem
    assert not same(view, frame(scr), PANE)
    press(scr, pygame.K_RETURN)
    assert scr.gem_view_active is False
    assert same(view, frame(scr), PANE)


def test_vieda_chip_is_lit_in_a_dungeon():
    from py_exodus.ui.ztats_view import spell_books

    cleric = make_party().members[1]
    cleric.max_mp = 60
    for map_type, want in ((MapType.DUNGEON, "lit"), (MapType.COMBAT, "faint")):
        books = spell_books(cleric, map_type=map_type)
        states = {spell: state for _book, spells in books for spell, state in spells}
        assert states[Spell.VIEDA] == want


# --- no free overlay ---------------------------------------------------------


def test_no_overlay_and_p_no_longer_toggles_one(cheat_state):
    """Nothing but the gem, the spell or the PEER cheat puts a map up: the
    view pane is the same picture whatever P is pressed, and XRAY (which
    lights the view) draws no plan over it either."""
    scr = make_screen()
    assert not hasattr(scr, "show_minimap")
    assert not hasattr(scr, "_render_minimap")
    assert scr.gem_view_active is False
    before = frame(scr)
    for _ in range(2):
        press(scr, pygame.K_p)
        scr.text_log.handle_char("X")
        assert scr.gem_view_active is False
        assert same(before, frame(scr), PANE)
    debug.CHEATS.xray = True
    assert same(before, frame(scr), PANE)


def test_peer_cheat_shows_the_map_without_a_gem(cheat_state):
    scr = make_screen()
    debug.CHEATS.free_peer = True
    assert scr.party.gems == 0
    press(scr, pygame.K_p)
    assert scr.gem_view_active is True
    assert not scr.text_log.is_waiting_for_input
    assert scr.party.gems == 0
    press(scr, pygame.K_SPACE)
    assert scr.gem_view_active is False


def test_peer_cheat_works_on_the_surface_too(cheat_state):
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    party = make_party()
    party.x, party.y = 10, 10
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=am, random_encounters=False)
    ow._check_moongates = lambda: None  # type: ignore[method-assign]
    press(ow, pygame.K_p)
    assert ow.gem_view_active is False and ow.text_log.is_waiting_for_input
    ow.text_log.handle_char("X")
    debug.CHEATS.free_peer = True
    press(ow, pygame.K_p)
    assert ow.gem_view_active is True
    assert not ow.text_log.is_waiting_for_input
    assert party.gems == 0


# --- DrawMiniDng's pieces ----------------------------------------------------


def test_pieces_follow_lairware_draw_mini_dng():
    """UltimaGraphics.c:1540-1555: seven named values, piece 7 for the rest."""
    T = DungeonTile
    want = {
        T.DOOR: 0, T.SECRET_DOOR: 1, T.WALL: 2, T.LADDER_UP_DOWN: 3,
        T.LADDER_UP: 4, T.LADDER_DOWN: 5, T.NOTHING: 6, T.FLOOR: 6,
        T.CHEST: 7, T.FOUNTAIN_HEAL: 7, T.MARK_FIRE: 7, T.PIT_TRAP: 7,
        T.WIND_TRAP: 7, T.GREMLINS: 7, T.TIME_LORD: 7, T.MISTY_WRITINGS: 7,
    }
    for tile, piece in want.items():
        assert gem_view.dungeon_piece(tile) == piece, tile.name
    # LairWare's raw bytes land on the same pieces
    for byte, piece in ((0xC0, 0), (0xA0, 1), (0x80, 2), (0x30, 3), (0x10, 4), (0x20, 5), (0x00, 6), (0x40, 7)):
        assert gem_view.dungeon_piece(T.get_tile_by_value(byte)) == piece, hex(byte)


@pytest.mark.parametrize("size,scale", [((960, 600), 3), ((320, 200), 1)])
def test_every_piece_is_its_own_picture(size, scale):
    """A secret door is not drawn as a wall on the map (LairWare piece 1 vs
    piece 2), unlike in the first-person view."""
    T = DungeonTile
    tiles = [T.DOOR, T.SECRET_DOOR, T.WALL, T.LADDER_UP_DOWN, T.LADDER_UP, T.LADDER_DOWN, T.NOTHING, T.CHEST]
    dmap = make_dmap()
    for i, tile in enumerate(tiles):
        dmap.set_tile(2 + i, 2, 0, tile)
    surf = pygame.Surface(size)
    pane = pygame.Rect(0, 0, 176 * scale, 176 * scale)
    gem_view.render_dungeon_gem_view(surf, pane, dmap, 0, (8, 8), marker_on=False)
    cell = gem_view.peer_cell(pane.w, 16, 16, scale)
    rect = gem_view.peer_map_rect(pane, 16, 16, scale)
    cells = [
        pygame.image.tobytes(surf.subsurface((rect.x + (2 + i) * cell, rect.y + 2 * cell, cell, cell)), "RGB")
        for i in range(len(tiles))
    ]
    assert len(set(cells)) == len(tiles)


# --- the Stone view on the screen --------------------------------------------


@pytest.mark.parametrize("size,pane", [((960, 600), 528), ((320, 200), 176)])
def test_both_sizes_render_the_view(size, pane):
    scr = make_screen()
    surf = frame(scr, size)
    view = surf.subsurface((0, 0, pane, pane))
    colours = {tuple(view.get_at((x, y))[:3]) for x in range(0, pane, pane // 16) for y in range(0, pane, pane // 16)}
    assert len(colours) > 4  # stone, floor and ceiling, not a blank pane
    # the picture is the 176px view enlarged: wall on both sides, mirror image
    assert view.get_at((pane // 20, pane // 2 + pane // 10)) == view.get_at((pane - 1 - pane // 20, pane // 2 + pane // 10))


def test_no_torch_is_black_and_xray_lights_it(cheat_state):
    scr = make_screen(lit=False)
    surf = frame(scr)
    # below the LVL/DIR line the whole pane is black
    assert not any(surf.get_at((x, y))[:3] != (0, 0, 0) for x in range(0, 528, 8) for y in range(40, 528, 8))
    debug.CHEATS.xray = True
    lit = frame(scr)
    assert any(lit.get_at((x, y))[:3] != (0, 0, 0) for x in range(0, 528, 8) for y in range(40, 528, 8))


@pytest.mark.parametrize("tile", [DungeonTile.FOUNTAIN_CURE, DungeonTile.MARK_KINGS])
def test_closeup_shows_only_while_standing_on_it(tile):
    dmap = make_dmap()
    dmap.set_tile(5, 4, 0, tile)
    scr = make_screen(dmap=dmap)
    scr.state.dir = Direction.NORTH
    ahead = frame(scr)
    scr.state.dir = Direction.EAST
    assert not same(ahead, frame(scr), pygame.Rect(0, 40, 528, 488))  # a corridor: facing matters
    scr.state.y = 4  # now on it
    on_north = frame(scr)
    scr.state.dir = Direction.SOUTH
    assert same(on_north, frame(scr), pygame.Rect(0, 40, 528, 488))  # the close-up: it does not
    assert not same(ahead, on_north, PANE)
