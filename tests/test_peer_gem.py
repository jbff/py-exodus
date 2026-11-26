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
- Dungeon P is LairWare dPeer (user ruling 2026-11-26), not Java's
  minimap toggle; covered by test_dungeon_peer.
- The picture is LairWare DrawMiniMap (UltimaGraphics.c:1433-1495): the
  whole map from shrunken real tiles in the map pane only, people and
  monsters at their places, the party in a blinking YELLOW box (see
  py_exodus/ui/gem_view.py).
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
from py_exodus.ui import gem_view
from py_exodus.ui.gem_view import (
    PEER_MESSAGE,
    marker_visible,
    peer_cell,
    peer_map_rect,
    render_gem_view,
)
from py_exodus.ui.text_log import EGA_WHITE, EGA_YELLOW
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


def peer(screen, who="1"):
    """P, then whose gem (LW PeerGem, UltimaMain.c:2143-2159)."""
    key(screen, pygame.K_p)
    assert "gem" in screen.text_log.current_prompt.lower()
    screen.text_log.submit_input(who)


def test_peer_gem_uses_chosen_member(ow, sample_party):
    sample_party.members[0].gems = 3
    sample_party.members[1].gems = 5
    peer(ow, "2")
    assert sample_party.members[0].gems == 3
    assert sample_party.members[1].gems == 4
    assert any(m == PEER_MESSAGE == "Peer at a Gem!" for m in ow.text_log.history)
    assert ow.gem_view_active is True


def test_peer_gem_gemless_member_none_left(ow, sample_party):
    sample_party.members[0].gems = 0
    sample_party.members[1].gems = 5
    peer(ow, "1")
    assert sample_party.members[1].gems == 5
    assert any(m == "None left!" for m in ow.text_log.history)
    assert ow.gem_view_active is False


def test_peer_gem_consumes_turn_without_gems(ow, sample_party, monkeypatch):
    ticks = []
    monkeypatch.setattr(ow, "_consume_pass_turn", lambda: ticks.append(1))
    peer(ow)
    assert ticks == [1]


def test_peer_gem_consumes_turn_with_gems(ow, sample_party, monkeypatch):
    sample_party.members[0].gems = 1
    ticks = []
    monkeypatch.setattr(ow, "_consume_pass_turn", lambda: ticks.append(1))
    peer(ow)
    assert ticks == [1]
    assert ow.gem_view_active is True


def test_gem_view_exit_consumes_no_turn(ow, sample_party, monkeypatch):
    sample_party.members[0].gems = 2
    peer(ow)
    assert ow.gem_view_active is True
    finish_calls = []
    monkeypatch.setattr(ow, "_finish_turn", lambda *a, **k: finish_calls.append(1))
    # Any key closes the view (GameScreen.java:1146-1152) with no turn.
    key(ow, pygame.K_RETURN)
    assert ow.gem_view_active is False
    assert finish_calls == []


def test_town_peer_gem_chosen_member_and_view(town, sample_party):
    sample_party.members[0].gems = 0
    sample_party.members[1].gems = 7
    peer(town, "2")
    assert sample_party.members[1].gems == 6
    assert any(m == "Peer at a Gem!" for m in town.text_log.history)
    assert town.gem_view_active is True


def test_town_peer_gem_none_left(town, sample_party):
    peer(town, "1")
    assert any(m == "None left!" for m in town.text_log.history)
    assert town.gem_view_active is False


def test_gem_view_render_deterministic_320x200(ow, sample_party):
    sample_party.members[0].gems = 1
    peer(ow)
    s1 = pygame.Surface((320, 200))
    s2 = pygame.Surface((320, 200))
    ow.render(s1)
    ow.render(s2)
    assert pygame.image.tobytes(s1, "RGB") == pygame.image.tobytes(s2, "RGB")


def test_town_gem_view_render_deterministic_320x200(town, sample_party):
    sample_party.members[0].gems = 1
    peer(town)
    s1 = pygame.Surface((320, 200))
    s2 = pygame.Surface((320, 200))
    town.render(s1)
    town.render(s2)
    assert pygame.image.tobytes(s1, "RGB") == pygame.image.tobytes(s2, "RGB")


def test_peer_cell_size_64x64_both_resolutions():
    """LairWare minSize = pane / mapsize: 8 px cells in the 528 px pane at
    960x600, 2 px in the 176 px pane at 320x200; centred in the pane."""
    assert peer_cell(528, 64, 64, 3) == 8
    assert peer_cell(176, 64, 64, 1) == 2
    assert peer_cell(528, 32, 32, 3) == 16
    assert peer_cell(10, 64, 64, 1) == 1  # never 0
    # Frame room top/left, drop-shadow room bottom/right, all in the pane.
    r = peer_map_rect(pygame.Rect(0, 0, 528, 528), 64, 64, 3)
    assert r == pygame.Rect(4, 4, 512, 512)
    assert r.right + gem_view.shadow_width(3) <= 528
    r = peer_map_rect(pygame.Rect(0, 0, 176, 176), 64, 64, 1)
    assert r == pygame.Rect(23, 23, 128, 128)


def test_peer_drop_shadow_and_frame_scale_with_resolution(asset_mgr):
    """LW shadow (UltimaGraphics.c:1462-1469): a block band plus a
    half-block band blended grey, darker where both overlap; the frame's
    white and black lines are scaled."""
    gmap = _small_map(asset_mgr)
    pane = pygame.Rect(0, 0, 528, 528)
    surf = pygame.Surface((960, 600))
    render_gem_view(surf, pane, gmap, asset_mgr, (5, 7), marker_on=False)
    rect = peer_map_rect(pane, 32, 32, 3)
    sw = gem_view.shadow_width(3)
    mid = rect.centery
    inner = surf.get_at((rect.right + sw // 2 - 1, mid))[:3]
    outer = surf.get_at((rect.right + sw - 1, mid))[:3]
    assert inner[0] > outer[0] > 0
    assert surf.get_at((rect.right + sw // 2, rect.top + 1))[:3] == (0, 0, 0)  # offset down
    fw = gem_view.frame_width(3)
    assert fw == 2 and gem_view.frame_width(1) == 1
    for i in range(fw):
        assert surf.get_at((rect.x - 1 - i, mid))[:3] == EGA_WHITE


def test_peer_terrain_recomposes_when_a_tile_changes(asset_mgr):
    gmap = _small_map(asset_mgr)
    pane = pygame.Rect(0, 0, 528, 528)
    rect = peer_map_rect(pane, 32, 32, 3)
    cell = peer_cell(528, 32, 32, 3)
    surf = pygame.Surface((960, 600))
    render_gem_view(surf, pane, gmap, asset_mgr, (5, 7))
    first = gem_view._TERRAIN[1]
    render_gem_view(surf, pane, gmap, asset_mgr, (5, 7))
    assert gem_view._TERRAIN[1] is first  # reused, not recomposed
    gmap.tiles[3 * 32 + 2] = TileDef(index=3, name="forest")  # a changed tile
    render_gem_view(surf, pane, gmap, asset_mgr, (5, 7))
    assert gem_view._TERRAIN[1] is not first
    assert _cell_pixels(surf, rect, cell, 2, 3) == _tile_pixels(asset_mgr, "forest", cell)


def test_peer_shrunk_tile_cache_is_weak():
    import gc

    src = pygame.Surface((16, 16))
    gem_view._shrunk(src, 8)
    assert src in gem_view._SHRUNK
    n = len(gem_view._SHRUNK)
    del src
    gc.collect()
    assert len(gem_view._SHRUNK) == n - 1


@pytest.mark.parametrize("size", [(960, 600), (320, 200)])
@pytest.mark.parametrize("screen_name", ["ow", "town"])
def test_peer_picture_confined_to_map_pane(request, sample_party, size, screen_name):
    """The picture replaces only the map pane: the party panel and the
    message log are drawn exactly as without Peer."""
    scr = request.getfixturevalue(screen_name)
    scale = 3 if size[0] >= 640 else 1
    pane = 176 * scale
    plain = pygame.Surface(size)
    scr.render(plain)
    scr.gem_view_active = True
    peered = pygame.Surface(size)
    scr.render(peered)

    def crop(s, rect):
        return pygame.image.tobytes(s.subsurface(rect), "RGB")

    side = pygame.Rect(pane, 0, size[0] - pane, size[1])
    log = pygame.Rect(0, pane, pane, size[1] - pane)
    assert crop(peered, side) == crop(plain, side)
    assert crop(peered, log) == crop(plain, log)
    assert crop(peered, pygame.Rect(0, 0, pane, pane)) != crop(plain, pygame.Rect(0, 0, pane, pane))


def _small_map(asset_mgr, npcs=()):
    tiles = [TileDef(index=3, name="water") for _ in range(32 * 32)]
    return GameMap(
        id=99,
        name="Small",
        fname="SMALL.ULT",
        map_type=MapType.CITY,
        width=32,
        height=32,
        border_behavior="exit",
        tiles=tiles,
        npcs=list(npcs),
    )


def _cell_pixels(surf, rect, cell, x, y):
    """RGB bytes of the interior of map cell (x, y)."""
    return pygame.image.tobytes(
        surf.subsurface(pygame.Rect(rect.x + x * cell, rect.y + y * cell, cell, cell)), "RGB"
    )


def _tile_pixels(asset_mgr, name, cell):
    s = pygame.Surface((cell, cell))
    s.blit(gem_view._shrunk(asset_mgr.get_tile_surface(name, 0), cell), (0, 0))
    return pygame.image.tobytes(s, "RGB")


def test_peer_draws_real_tiles_people_and_monsters_at_their_positions(asset_mgr):
    gmap = _small_map(
        asset_mgr,
        npcs=[MapNpc(x=20, y=8, tile_index=3, tile_name="guard", start_x=20, start_y=8)],  # type: ignore
    )
    gmap.tiles[0] = TileDef(index=3, name="forest")
    surf = pygame.Surface((960, 600))
    pane = pygame.Rect(0, 0, 528, 528)
    sprites = gem_view.peer_sprites(gmap, None, [{"x": 3, "y": 4, "tile_name": "orc"}], asset_mgr)
    assert (20, 8, "guard") in sprites and (3, 4, "orc") in sprites
    render_gem_view(surf, pane, gmap, asset_mgr, (5, 7), sprites=sprites, party_tile="ranger", marker_on=False)
    rect = peer_map_rect(pane, 32, 32, 3)
    cell = peer_cell(528, 32, 32, 3)
    assert _cell_pixels(surf, rect, cell, 0, 0) == _tile_pixels(asset_mgr, "forest", cell)
    assert _cell_pixels(surf, rect, cell, 1, 0) == _tile_pixels(asset_mgr, "water", cell)
    assert _cell_pixels(surf, rect, cell, 20, 8) == _tile_pixels(asset_mgr, "guard", cell)
    assert _cell_pixels(surf, rect, cell, 3, 4) == _tile_pixels(asset_mgr, "orc", cell)
    assert _cell_pixels(surf, rect, cell, 5, 7) == _tile_pixels(asset_mgr, "ranger", cell)
    # White frame just outside the map.
    assert surf.get_at((rect.x - 1, rect.y + 10))[:3] == EGA_WHITE


def test_peer_sprites_include_parked_ship_and_whirlpool(asset_mgr, sample_party):
    gmap = _small_map(asset_mgr)
    gmap.id = 0
    sample_party.dynamic_objects.append({"x": 2, "y": 3, "tile": "frigate"})
    sample_party.objects_map_id = 0
    sprites = gem_view.peer_sprites(
        gmap, sample_party, [{"x": 9, "y": 9, "tile_name": "whirlpool", "tile": "whirlpool"}], asset_mgr
    )
    assert (2, 3, "frigate") in sprites
    assert (9, 9, "whirlpool") in sprites


def test_peer_party_marker_yellow_and_blinks(asset_mgr):
    """The party box is YELLOW and blinks: on 0.4 s, off 0.4 s on the
    screen's 0.2 s animation frame."""
    assert [marker_visible(f) for f in range(8)] == [True, True, False, False] * 2
    gmap = _small_map(asset_mgr)
    pane = pygame.Rect(0, 0, 528, 528)
    rect = peer_map_rect(pane, 32, 32, 3)
    cell = peer_cell(528, 32, 32, 3)
    on = pygame.Surface((960, 600))
    off = pygame.Surface((960, 600))
    render_gem_view(on, pane, gmap, asset_mgr, (5, 7), marker_on=True)
    render_gem_view(off, pane, gmap, asset_mgr, (5, 7), marker_on=False)
    # The box sits just outside the party's cell.
    edge = (rect.x + 5 * cell - 1, rect.y + 7 * cell + cell // 2)
    assert on.get_at(edge)[:3] == EGA_YELLOW
    assert off.get_at(edge)[:3] != EGA_YELLOW


def test_overworld_peer_marker_toggles_with_anim_frame(ow, sample_party):
    ow.gem_view_active = True
    gm = ow.game_map
    rect = peer_map_rect(pygame.Rect(0, 0, 528, 528), gm.width, gm.height, 3)
    cell = peer_cell(528, gm.width, gm.height, 3)
    edge = (rect.x + ow.party.x * cell - 1, rect.y + ow.party.y * cell + cell // 2)
    seen = []
    for frame in (0, 2):
        ow.anim_frame = frame
        s = pygame.Surface((960, 600))
        ow.render(s)
        seen.append(s.get_at(edge)[:3] == EGA_YELLOW)
    assert seen == [True, False]


# --- Task 25 (D4): VIEDA cast routes to the same gem-view render path ---

@pytest.fixture
def cast_party():
    """Fighter + Cleric, so the C command drives the flow without a type
    prompt and the cleric can cast VIEDA ('L')."""
    members = [
        PartyMember(
            Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)
        ),
        PartyMember(
            Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=60, hp=80)
        ),
    ]
    return Party(members, x=10, y=10, transport=Transport.FOOT)


@pytest.fixture
def ow_vieda(asset_mgr, cast_party, monkeypatch):
    o = OverworldScreen(
        party=cast_party,
        map_id=0,
        asset_mgr=asset_mgr,
        random_encounters=False,
    )
    o._check_moongates = lambda: None  # type: ignore[method-assign]
    return o


def test_vieda_cast_on_overworld_opens_peer_gem_view(ow_vieda, cast_party):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): VIEDA renders the
    peer-gem view through the same screen path as the P command (GBC
    menucmd.c:1379-1390 — dopeergem(1) after the 55 MP deduction; the
    spell branch skips choosechar2 and the gem decrement, so NO gem is
    paid unlike the P command)."""
    # Start with gems so the test proves they are NOT consumed by the spell.
    cast_party.members[1].gems = 7
    key(ow_vieda, pygame.K_c)
    assert "Which member?" in ow_vieda.text_log.current_prompt
    ow_vieda.text_log.handle_char("2")  # the Cleric
    assert "Cleric Spell?" in ow_vieda.text_log.current_prompt
    ow_vieda.text_log.handle_char("L")  # VIEDA — its FIXED cleric code (RULING 2026-11-15)

    # The spell's success opened the same gem view the P command opens.
    assert ow_vieda.gem_view_active is True
    # GBC dopeergem(1) never reaches the gem payment (menucmd.c:695-712 only
    # runs for dopeergem(0)) — the view costs no gem.
    assert cast_party.members[1].gems == 7


def test_fal_divi_cast_on_overworld_casts_vieda(asset_mgr, cast_party):
    """FAL_DIVI asks the same caster for a cleric letter and casts it
    (LairWare case 9, UltimaSpellCombat.c:231-235, ledger P-20): through
    Vieda the wizard opens the peer-gem view, 45 + 55 MP."""
    members = [
        PartyMember(
            Character("Mage", "M", Race.FUZZY, Profession.WIZARD, intelligence=50, mp=100)
        ),
    ]
    party = Party(members, x=10, y=10, transport=Transport.FOOT)
    o = OverworldScreen(
        party=party,
        map_id=0,
        asset_mgr=asset_mgr,
        random_encounters=False,
    )
    o._check_moongates = lambda: None  # type: ignore[method-assign]

    key(o, pygame.K_c)
    assert "Which member?" in o.text_log.current_prompt
    o.text_log.handle_char("1")  # the Mage
    assert "Wizard Spell?" in o.text_log.current_prompt
    o.text_log.handle_char("J")  # FAL_DIVI
    assert "Cleric Spell?" in o.text_log.current_prompt
    o.text_log.handle_char("L")  # VIEDA
    assert o.gem_view_active is True
    assert members[0].mp == 0
    member_prompts = sum(
        1 for line in o.text_log.history if "Which member?" in str(line)
    )
    assert member_prompts == 1


def test_vieda_cast_in_town_opens_peer_gem_view(asset_mgr):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): VIEDA in a town goes
    through the same dopeergem(1) as any other non-battle site (GBC
    menucmd.c:1379-1390) and the town already owns the gem-view machinery —
    the spell branch consumes no gem (menucmd.c:695-712 runs only for
    dopeergem(0)), so the gems stay put."""
    members = [
        PartyMember(
            Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=20, dexterity=20, hp=100)
        ),
        PartyMember(
            Character("Cleric", "F", Race.BOBBIT, Profession.CLERIC, wisdom=50, mp=60, hp=80)
        ),
    ]
    party = Party(members, x=10, y=10, transport=Transport.FOOT)
    members[1].gems = 7
    town = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)

    key(town, pygame.K_c)
    assert "Which member?" in town.text_log.current_prompt
    town.text_log.handle_char("2")  # the Cleric
    assert "Cleric Spell?" in town.text_log.current_prompt
    town.text_log.handle_char("L")  # VIEDA — its FIXED cleric code (RULING 2026-11-15)

    # The spell's success opened the same gem view the town P command opens,
    # with no gem paid.
    assert town.gem_view_active is True
    assert members[1].gems == 7
