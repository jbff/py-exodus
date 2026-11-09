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

Presentation adaptation (documented at py_exodus/ui/gem_view.py): fixed
8px colored cells instead of scaled sprites, party marker YELLOW.
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
    NO_GEMS_MESSAGE,
    PEER_MESSAGE,
    render_gem_view,
)
from py_exodus.ui.text_log import EGA_BLACK, EGA_WHITE, EGA_YELLOW
from py_exodus.world.map import GameMap, MapNpc, MapType

CELL = 8


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
    # Cell size 8 at 320x200 gives a 40x25 grid; the party sits at its center.
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px, py))[:3] == EGA_YELLOW


def test_gem_view_off_map_cells_black():
    gmap = GameMap(
        id=99,
        name="Tiny",
        fname="TINY.ULT",
        map_type=MapType.CITY,
        width=4,
        height=4,
        border_behavior="exit",
        tiles=[TileDef(index=3, name="floor") for _ in range(16)],
    )
    surf = pygame.Surface((320, 200))
    render_gem_view(surf, gmap, 1, 1)
    # Cells outside the 4x4 map (party centered) stay black; the map edge
    # clip is the town-port adaptation of the Java city view.
    assert surf.get_at((0, 0))[:3] == EGA_BLACK
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px, py))[:3] == EGA_YELLOW


def test_gem_view_npcs_drawn_white():
    gmap = GameMap(
        id=99,
        name="Tiny",
        fname="TINY.ULT",
        map_type=MapType.CITY,
        width=4,
        height=4,
        border_behavior="exit",
        tiles=[TileDef(index=3, name="floor") for _ in range(16)],
        npcs=[MapNpc(x=0, y=0, tile_index=3, tile_name="guard", start_x=0, start_y=0)],  # type: ignore
    )
    surf = pygame.Surface((320, 200))
    render_gem_view(surf, gmap, 1, 1, marks=[(0, 0)])
    # Npc cell (map 0,0) is one cell left / one cell up of the party center.
    px = (surf.get_width() // CELL // 2) * CELL
    py = (surf.get_height() // CELL // 2) * CELL
    assert surf.get_at((px - CELL, py - CELL))[:3] == EGA_WHITE
