"""Peer Gem (P) command parity on the overworld and in towns.

Java truth:
- ``exodus/GameScreen.java:1076-1087`` — ``peerGem()`` scans the party in
  order, uses the FIRST member holding gems, decrements that member's gems,
  logs ``"Peer at a Gem!"`` and swaps input to ``PeerGemInputAdapter``; when
  no member has gems it logs ``"Thou dost have no gems!"``. No member prompt
  is raised (P never routes through SecondaryInputProcessor).
- ``exodus/GameScreen.java:1114-1152`` — the adapter renders the map-view
  image and sets ``gameTimer.active = False``; ANY key closes the view and
  restores the timer, with no turn passing while the view is up.
- ``exodus/GameScreen.java:604-605`` + ``628`` — P has no early return, so
  the press itself consumes a turn (finishTurn) with or without gems, before
  the view opens.
- ``exodus/DungeonScreen.java:1012-1015`` — dungeon P is only the minimap
  toggle (gems never enter it); covered by test_dungeon_commands.
- ``exodus/Util/Utils.java:865-1042`` — the gem picture: a region of map
  tiles around the party (wrapped for Sosaria, whole city for towns) with
  people/creatures as WHITE cells and the party position marked.

Presentation adaptation (documented at py_exodus/ui/gem_view.py): whole-map
colored-cell blit centered on the screen when the map fits at a usable cell
size (Java's city view), else a party-centered window at fixed 8px cells
(Java's world view); party marker YELLOW.
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import TileDef
from py_exodus.constants import Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.constants import Profession, Race
from py_exodus.screens import overworld as overworld_module
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.screens.town import TownScreen
from py_exodus.ui.gem_view import (
    CELL,
    NO_GEMS_MESSAGE,
    PEER_MESSAGE,
    WHOLE_MAP_MIN_CELL,
    render_gem_view,
    whole_map_cell,
)
from py_exodus.ui.text_log import (
    EGA_BLACK,
    EGA_BROWN,
    EGA_DARK_GRAY,
    EGA_GREEN,
    EGA_WHITE,
    EGA_YELLOW,
)
from py_exodus.world.map import GameMap, MapNpc, MapType


@pytest.fixture
def sample_party():
    members = [
        PartyMember(
            Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)
        ),
        PartyMember(
            Character("Mage", "F", Race.ELF, Profession.WIZARD, strength=15, dexterity=20, hp=70)
        ),
    ]
    return Party(members, x=10, y=10, transport=Transport.FOOT)


@pytest.fixture
def ow(asset_mgr, sample_party, monkeypatch):
    o = OverworldScreen(
        party=sample_party,
        map_id=0,
        asset_mgr=asset_mgr,
        random_encounters=False,
    )
    monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
    o._check_moongates = lambda: None  # type: ignore[method-assign]
    return o


@pytest.fixture
def town(asset_mgr, sample_party):
    return TownScreen(party=sample_party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)


def key(screen, k):
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))


def test_peer_gem_uses_first_member_with_gems(ow, sample_party):
    sample_party.members[0].gems = 3
    sample_party.members[1].gems = 5
    key(ow, pygame.K_p)
    # Java GameScreen.java:1077-1080 — the first member with gems pays.
    assert sample_party.members[0].gems == 2
    assert sample_party.members[1].gems == 5
    assert any(m == PEER_MESSAGE == "Peer at a Gem!" for m in ow.text_log.history)
    # The view opens after a paid gem (Java swaps to PeerGemInputAdapter).
    assert ow.gem_view_active is True


def test_peer_gem_skips_gemless_members(ow, sample_party):
    sample_party.members[0].gems = 0
    sample_party.members[1].gems = 5
    key(ow, pygame.K_p)
    assert sample_party.members[0].gems == 0
    assert sample_party.members[1].gems == 4
    assert any(m == "Peer at a Gem!" for m in ow.text_log.history)
    assert ow.gem_view_active is True


def test_peer_gem_no_gems_message_and_no_view(ow, sample_party):
    key(ow, pygame.K_p)
    assert any(m == NO_GEMS_MESSAGE == "Thou dost have no gems!" for m in ow.text_log.history)
    assert not any("None owned!" in m for m in ow.text_log.history)
    assert ow.gem_view_active is False
    assert all(m.gems == 0 for m in sample_party.members)


def test_peer_gem_consumes_turn_without_gems(ow, sample_party, monkeypatch):
    ticks = []
    monkeypatch.setattr(ow, "_consume_pass_turn", lambda: ticks.append(1))
    key(ow, pygame.K_p)
    # GameScreen.java:604-605 + 628 — P falls through the keyUp tail even
    # when peerGem logs the no-gems message.
    assert ticks == [1]


def test_peer_gem_consumes_turn_with_gems(ow, sample_party, monkeypatch):
    sample_party.members[0].gems = 1
    ticks = []
    monkeypatch.setattr(ow, "_consume_pass_turn", lambda: ticks.append(1))
    key(ow, pygame.K_p)
    assert ticks == [1]
    assert ow.gem_view_active is True


def test_gem_view_exit_consumes_no_turn(ow, sample_party, monkeypatch):
    sample_party.members[0].gems = 2
    key(ow, pygame.K_p)
    assert ow.gem_view_active is True
    finish_calls = []
    monkeypatch.setattr(ow, "_finish_turn", lambda *a, **k: finish_calls.append(1))
    # Any key closes the view (GameScreen.java:1146-1152) with no turn.
    key(ow, pygame.K_RETURN)
    assert ow.gem_view_active is False
    assert finish_calls == []
    # The exit did not grant a free turn: a fresh P still costs a gem and
    # the exit consumed nothing beyond the opening press.
    key(ow, pygame.K_p)
    assert sample_party.members[0].gems == 0


def test_town_peer_gem_first_member_and_view(town, sample_party):
    sample_party.members[0].gems = 0
    sample_party.members[1].gems = 7
    key(town, pygame.K_p)
    assert sample_party.members[1].gems == 6
    assert any(m == "Peer at a Gem!" for m in town.text_log.history)
    assert town.gem_view_active is True


def test_town_peer_gem_no_gems_message(town, sample_party):
    key(town, pygame.K_p)
    assert any(m == "Thou dost have no gems!" for m in town.text_log.history)
    assert town.gem_view_active is False


def test_town_peer_gem_pays_first_member(town, sample_party):
    sample_party.members[0].gems = 3
    sample_party.members[1].gems = 9
    key(town, pygame.K_p)
    assert sample_party.members[0].gems == 2
    assert sample_party.members[1].gems == 9


def test_gem_view_render_deterministic_320x200(ow, sample_party):
    sample_party.members[0].gems = 1
    key(ow, pygame.K_p)
    s1 = pygame.Surface((320, 200))
    s2 = pygame.Surface((320, 200))
    ow.render(s1)
    ow.render(s2)
    assert pygame.image.tobytes(s1, "RGB") == pygame.image.tobytes(s2, "RGB")


def test_town_gem_view_render_deterministic_320x200(town, sample_party):
    sample_party.members[0].gems = 1
    key(town, pygame.K_p)
    s1 = pygame.Surface((320, 200))
    s2 = pygame.Surface((320, 200))
    town.render(s1)
    town.render(s2)
    assert pygame.image.tobytes(s1, "RGB") == pygame.image.tobytes(s2, "RGB")


def test_gem_view_marks_party_cell_yellow(ow, sample_party):
    sample_party.members[0].gems = 1
    key(ow, pygame.K_p)
    surf = pygame.Surface((320, 200))
    ow.render(surf)
    # The 64x64 overworld fits whole-map mode; the party mark lands at its
    # TRUE map-scaled cell (Java city view, Utils.java:938-944), not the
    # region center.
    gm = ow.game_map
    cell = whole_map_cell(surf.get_width(), surf.get_height(), gm.width, gm.height)
    assert cell >= WHOLE_MAP_MIN_CELL  # whole-map mode is engaged
    off_x = (surf.get_width() - gm.width * cell) // 2
    off_y = (surf.get_height() - gm.height * cell) // 2
    assert surf.get_at((off_x + ow.party.x * cell, off_y + ow.party.y * cell))[
        :3
    ] == EGA_YELLOW


def test_gem_view_whole_map_party_and_corner_tiles(sample_party):
    """Java's city presentation (Utils.java:887-944): the WHOLE map blits
    centered on the screen, so far-from-party corner tiles are visible and
    the party mark sits at its true scaled position."""
    tiles = [TileDef(index=3, name="water") for _ in range(32 * 32)]
    gmap = GameMap(
        id=99,
        name="Small",
        fname="SMALL.ULT",
        map_type=MapType.CITY,
        width=32,
        height=32,
        border_behavior="exit",
        tiles=tiles,
        npcs=[MapNpc(x=20, y=8, tile_index=3, tile_name="guard", start_x=20, start_y=8)],  # type: ignore
    )
    corner_names = {(0, 0): "forest", (31, 0): "hills", (0, 31): "mountains", (31, 31): "brush"}
    for (cx, cy), name in corner_names.items():
        tiles[cy * 32 + cx] = TileDef(index=3, name=name)
    surf = pygame.Surface((320, 200))
    # Party away from the corners; whole-map mode makes them visible anyway.
    render_gem_view(surf, gmap, 5, 7, marks=[(20, 8)])

    cell = whole_map_cell(surf.get_width(), surf.get_height(), 32, 32)
    assert cell >= WHOLE_MAP_MIN_CELL
    off_x = (surf.get_width() - 32 * cell) // 2
    off_y = (surf.get_height() - 32 * cell) // 2

    for (cx, cy), name in corner_names.items():
        assert surf.get_at((off_x + cx * cell, off_y + cy * cell))[:3] == {
            "forest": EGA_GREEN,
            "hills": EGA_BROWN,
            "mountains": EGA_DARK_GRAY,
            "brush": EGA_GREEN,
        }[name], (cx, cy)
    # NPC mark at its true scaled cell; party at its own.
    assert surf.get_at((off_x + 20 * cell, off_y + 8 * cell))[:3] == EGA_WHITE
    assert surf.get_at((off_x + 5 * cell, off_y + 7 * cell))[:3] == EGA_YELLOW


def test_gem_view_window_fallback_clips_off_map_cells_black():
    """Maps too large to fit whole (128x128 exceeds 320x200 at 3px cells)
    use the party-centered window; cells past the map edge stay black."""
    gmap = GameMap(
        id=99,
        name="Big",
        fname="BIG.ULT",
        map_type=MapType.CITY,
        width=128,
        height=128,
        border_behavior="exit",
        tiles=[TileDef(index=3, name="floor") for _ in range(128 * 128)],
    )
    assert whole_map_cell(320, 200, 128, 128) == 0  # window fallback engaged
    surf = pygame.Surface((320, 200))
    render_gem_view(surf, gmap, 1, 1)  # party near the map corner
    # Windows clip at the map edge (Java world view blits a wrapped region
    # only for wrap maps; non-wrap maps clip as the town-port adaptation).
    assert surf.get_at((0, 0))[:3] == EGA_BLACK
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px, py))[:3] == EGA_YELLOW


def test_gem_view_window_fallback_npcs_drawn_white():
    gmap = GameMap(
        id=99,
        name="Big",
        fname="BIG.ULT",
        map_type=MapType.CITY,
        width=128,
        height=128,
        border_behavior="exit",
        tiles=[TileDef(index=3, name="floor") for _ in range(128 * 128)],
        npcs=[MapNpc(x=63, y=63, tile_index=3, tile_name="guard", start_x=63, start_y=63)],  # type: ignore
    )
    surf = pygame.Surface((320, 200))
    render_gem_view(surf, gmap, 64, 64, marks=[(63, 63)])
    # Npc cell (map 63,63) is one cell left / one cell up of the party at
    # the region center.
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px - CELL, py - CELL))[:3] == EGA_WHITE


def test_gem_view_window_wrap_marks_cross_the_seam():
    """The wrap branch of the mark math (WorldRenderer.map_to_viewport
    shortest-delta): a party at the seam edge draws NPCs from across the
    map edge at their wrapped window position, and window tiles come from
    the wrapped map side of the seam."""
    gmap = GameMap(
        id=99,
        name="WrapBig",
        fname="WRAPBIG.ULT",
        map_type=MapType.WORLD,
        width=128,
        height=128,
        border_behavior="wrap",
        tiles=[TileDef(index=3, name="water") for _ in range(128 * 128)],
        npcs=[MapNpc(x=127, y=127, tile_index=3, tile_name="guard", start_x=127, start_y=127)],  # type: ignore
    )
    # A distinct tile at the wrapped coordinate seen by the top-left window
    # cell (party (1,1): start (-19,-11) wraps to (109, 117)).
    gmap.tiles[117 * 128 + 109] = TileDef(index=3, name="mountains")
    assert whole_map_cell(320, 200, 128, 128) == 0  # window fallback engaged
    surf = pygame.Surface((320, 200))
    render_gem_view(surf, gmap, 1, 1, marks=[(127, 127)])
    # Wrapped seam tile visible at the window's top-left cell.
    assert surf.get_at((0, 0))[:3] == EGA_DARK_GRAY
    # NPC at (127,127) shortest-delta is (-2,-2) around the party: two cells
    # left/up of the window center.
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px - 2 * CELL, py - 2 * CELL))[:3] == EGA_WHITE


def test_gem_view_party_on_wrapped_window_seam():
    """Party across the seam from the window origin: the window tiles come
    from the wrapped side while the YELLOW party marker stays at the
    region center."""
    gmap = GameMap(
        id=99,
        name="WrapBig",
        fname="WRAPBIG.ULT",
        map_type=MapType.WORLD,
        width=128,
        height=128,
        border_behavior="wrap",
        tiles=[TileDef(index=3, name="water") for _ in range(128 * 128)],
    )
    # Party at (2,2): window start (-18,-10) wraps leftmost cell to (110,118).
    gmap.tiles[118 * 128 + 110] = TileDef(index=3, name="mountains")
    surf = pygame.Surface((320, 200))
    render_gem_view(surf, gmap, 2, 2)
    assert surf.get_at((0, 0))[:3] == EGA_DARK_GRAY
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px, py))[:3] == EGA_YELLOW
