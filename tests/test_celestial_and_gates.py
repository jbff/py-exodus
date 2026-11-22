"""Tests for moon phases, Dawn double-new-moon conjunction, moongates, and Ambrosia whirlpool."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Direction, Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.overworld import OverworldScreen


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def party():
    members = [
        PartyMember(Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER, hp=100)),
    ]
    return Party(members, x=37, y=53, gold=500, transport=Transport.FOOT)


def test_dawn_portal_conjunction_restriction(asset_mgr, party):
    """Entering Dawn (dest_map_id 11) is permitted only during double new moon (0, 0)."""
    # Dawn portal on Sosaria is at (37, 53)
    party.x = 37
    party.y = 53
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=37, start_y=53)

    # When moons are NOT (0, 0), e.g. moon_phase = 10 (Trammel 3, Felucca 2)
    ow.moon_phase = 10
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))
    assert not ow.is_finished
    assert any("Dawn" in msg for msg in ow.text_log.history)

    # When moons ARE (0, 0), e.g. moon_phase = 0
    ow.moon_phase = 0
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))
    # Portal transition occurs
    assert ow.is_finished or ow.next_screen is not None


# USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): moongate model per refs —
# one visible gate at the slow-moon site, entry teleports to the fast-moon site
# (GBC funcs5.c:1134-1152; LW UltimaMisc.c:1511-1560; NES Bank0F MoonGateTbl:734-771)
# The old per-gate d1/d2/d3 destination tables (Java invention) are gone: the
# destination is always the fast-moon (Felucca) site of the same 8 sites.
def test_moongate_entry_teleports_to_fast_moon_site(asset_mgr, party):
    """Standing on the visible (slow-moon) gate teleports to site[fast]."""
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=7, start_y=8)

    # moon_phase = 1: Trammel (slow) 0 -> gate visible at site 0 = (7, 8);
    # Felucca (fast) 1 -> destination is site 1 = (57, 46).
    ow.moon_phase = 1
    party.x = 7
    party.y = 8

    ow._check_moongates()

    assert party.x == 57
    assert party.y == 46
    assert any("moongate" in msg.lower() for msg in ow.text_log.history)


def test_moongate_no_gate_at_other_sites(asset_mgr, party):
    """Only the slow-moon site is a gate: standing on any other site is inert."""
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=7, start_y=8)

    # moon_phase = 10: Trammel (slow) 3 -> gate visible at site 3 = (36, 58);
    # sites 0..7 other than 3 are inert. Party stands on site 0.
    ow.moon_phase = 10
    party.x = 7
    party.y = 8
    ow._check_moongates()
    assert (party.x, party.y) == (7, 8)
    assert not any("moongate" in msg.lower() for msg in ow.text_log.history)

    # Same phase, party stands on site 5 (12, 55) — also inert.
    party.x = 12
    party.y = 55
    ow._check_moongates()
    assert (party.x, party.y) == (12, 55)


def test_moongate_slow_equals_fast_is_inert(asset_mgr, party):
    """When the two moons agree the destination is the site the party is on."""
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=7, start_y=8)

    # moon_phase = 0: Trammel 0, Felucca 0 — destination is site 0 itself.
    ow.moon_phase = 0
    party.x = 7
    party.y = 8

    ow._check_moongates()

    assert (party.x, party.y) == (7, 8)


def test_moongate_routes_to_site_table_not_d_tables(asset_mgr, party):
    """Destination always equals site[felucca_phase] — every fast phase lands
    on the site coordinates defined for the gates (8x8 phase pairs sample)."""
    sosaria = asset_mgr.map_defs[0]
    sites = {g.phase: (g.x, g.y) for g in sosaria.moongates}
    assert len(sites) == 8

    for moon_phase in range(24):
        p = Party(
            [PartyMember(Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER, hp=100))],
            x=7, y=8, gold=500, transport=Transport.FOOT,
        )
        ow = OverworldScreen(party=p, map_id=0, asset_mgr=asset_mgr, start_x=7, start_y=8)
        ow.moon_phase = moon_phase
        p.x, p.y = sites[ow.trammel_phase]
        ow._check_moongates()
        assert (p.x, p.y) == sites[ow.felucca_phase], moon_phase


def test_moongate_renders_only_at_slow_moon_site(asset_mgr, party, monkeypatch):
    """The render path draws exactly one gate — at the slow-moon site."""
    from py_exodus.world.loader import MapLoader
    from py_exodus.ui.renderer import WorldRenderer

    wr = WorldRenderer(asset_mgr)
    real_get_surface = asset_mgr.get_tile_surface
    sentinel = pygame.Surface((16, 16))

    def fake_get_surface(name, frame=0, *a, **k):
        if name == "moongate":
            return sentinel
        return real_get_surface(name, frame, *a, **k)

    monkeypatch.setattr(asset_mgr, "get_tile_surface", fake_get_surface)

    gate_blits: list[tuple[int, int]] = []
    real_blit = pygame.Surface.blit

    class SpySurface(pygame.Surface):
        def blit(self, src, dest, *a, **k):
            if src is sentinel:
                gate_blits.append((dest[0], dest[1]))
            return super().blit(src, dest, *a, **k)

    game_map = MapLoader(asset_mgr).load_map(0)
    surf = SpySurface((176, 176))

    # The visible gate is site[slow]: with slow phase 0 the gate renders at
    # site 0 (7, 8), which sits dead-center when the viewport centers there.
    wr.render_viewport(surf, game_map, center_x=7, center_y=8, moon_phase=0)
    assert gate_blits == [(80, 80)]

    # A party elsewhere: the party's own site never renders a gate.
    gate_blits.clear()
    wr.render_viewport(surf, game_map, center_x=60, center_y=40, moon_phase=0)
    assert gate_blits == []


def test_overworld_render_passes_slow_phase_for_gate_visibility(asset_mgr, party):
    """The overworld render feeds the renderer the slow phase so only the
    visible gate's site renders."""
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)
    ow.moon_phase = 10  # Trammel 3, Felucca 2

    calls: list[dict] = []

    class SpyRenderer:
        def render_viewport(self, *a, **k):
            calls.append(k)

    ow.world_renderer = SpyRenderer()
    ow.render(pygame.Surface((640, 400)))

    assert calls
    assert all(k.get("moon_phase") == ow.trammel_phase for k in calls)


def test_ambrosia_whirlpool_routes_to_sosaria_coast(asset_mgr, party, monkeypatch):
    """Stepping ONTO the Ambrosia whirlpool portal (preMove) transports the
    party to a random Sosaria coast tile (x=48..53, y=0..8) — Java
    GameScreen.java:661-670. Pressing E there goes to the portal's fixed
    start (1,1) instead (GameScreen.java:538-556).
    """
    # Ambrosia map 13, whirlpool portal is at (32, 58)
    party.x = 32
    party.y = 57
    import py_exodus.screens.overworld as overworld_module

    from py_exodus.constants import Direction

    ow = OverworldScreen(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=57)
    monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
    ow.heading = Direction.SOUTH

    # Sail onto (32, 58) — the finish-turn whirlpool scan fires via the
    # preMove intercept (Java GameScreen.java:661-670).
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, unicode=""))
    # Party should be in Sosaria (map_id 0) at coast (Java preMove)
    assert 48 <= party.x <= 53
    assert 0 <= party.y <= 8
    assert ow.map_id == 0


def test_ambrosia_whirlpool_ship_sailing_exits_to_sosaria(asset_mgr, party):
    """Sailing Transport.SHIP SOUTH from (32, 57) onto Ambrosia's whirlpool at
    (32, 58) transitions to Sosaria (map_id=0) without monkeypatching can_move_to,
    while Transport.FOOT still cannot walk onto water (32, 57) — Item 49 /
    Java GameScreen.java:661-670.
    """
    from py_exodus.ui.renderer import can_move_to

    party.transport = Transport.SHIP
    party.wind_direction = Direction.SOUTH
    party.x = 32
    party.y = 57
    ow = OverworldScreen(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=57)
    ambrosia_map = ow.game_map
    assert can_move_to(ambrosia_map, 32, 57, transport=Transport.FOOT, party=party) is False

    ow.heading = Direction.SOUTH
    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, unicode=""))

    assert ow.map_id == 0
    assert 48 <= party.x <= 53
    assert 0 <= party.y <= 8


def test_ambrosia_whirlpool_portal_e_fixed_start(asset_mgr, party):
    """Pressing E at Ambrosia's WHIRLPOOL portal uses the portal's fixed
    startx/starty (maps.xml startx="1" starty="1") — GameScreen.java:538-556."""
    party.x = 32
    party.y = 58
    ow = OverworldScreen(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=58)

    ow.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))

    assert (party.x, party.y) == (1, 1)
    assert ow.map_id == 0


# --------------------------------------------------------------------------- #
# Overworld HUD sky strip (wind + moon phases) — Java GameScreen.java:180-196
# --------------------------------------------------------------------------- #
class TestSkyStrip:
    """Sosaria-only top strip of the main pane: two moon-phase glyphs (Trammel
    and Felucca), the wind direction with its arrow, and the aura label when
    active (Java GameScreen.java:180-196 draws the phase_* atlas icons and
    "Wind <direction>"; the port adapts them to text plus clipped circle-with-
    shadow glyphs in its EGA text/cell style). Hull stays in the stats panel.

    Source rule: the phases are read from this screen's live counters
    (self.trammel_phase / self.felucca_phase — the same properties the
    moongate routing reads) and the wind from party.wind_direction, never
    copies of them.
    """

    def test_strip_on_sosaria_and_ambrosia_moons_on_sosaria(self, asset_mgr, party):
        from py_exodus.screens.overworld import OverworldScreen as OW

        ow0 = OW(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)
        assert ow0.sky_strip_active is True
        ow13 = OW(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=57)
        # LairWare shows the wind on Ambrosia (it steers ships there too).
        assert ow13.sky_strip_active is True
        assert ow0.moons_shown is True and ow13.moons_shown is False

    def test_strip_texts_wind_and_moons(self, asset_mgr, party):
        from py_exodus.aura import AuraType
        from py_exodus.screens.overworld import sky_strip_texts

        texts = sky_strip_texts(Direction.NORTH, 3, 0)
        assert "Wind NORTH" in texts
        assert not any(t.startswith("T:") for t in texts)

        # User ruling 2026-11-22: the direction in words, no arrow glyph.
        assert "Wind SOUTH" in sky_strip_texts(Direction.SOUTH, 0, 7)
        assert "Wind EAST" in sky_strip_texts(Direction.EAST, 1, 1)
        assert "Wind WEST" in sky_strip_texts(Direction.WEST, 7, 4)

        # Aura label appears only when an aura is active.
        assert "QUICKNESS" in sky_strip_texts(Direction.NORTH, 0, 0, aura=AuraType.QUICKNESS)
        assert not any(
            "QUICKNESS" in t for t in sky_strip_texts(Direction.NORTH, 0, 0, aura=AuraType.NONE)
        )

    def test_strip_reads_live_state_not_copies(self, asset_mgr, party, monkeypatch):
        ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)
        texts = ow.sky_strip_texts()
        assert any("Wind NORTH" in t for t in texts)
        assert not any(t.startswith("T:") for t in texts)

        # Same source the moongate code reads: bump the phase counters.
        ow.moon_phase = 10  # Trammel 3, Felucca 2
        assert (ow.trammel_phase, ow.felucca_phase) == (3, 2)

        # Wind comes from the party record the sailing code tracks.
        party.wind_direction = Direction.SOUTH
        assert any("Wind SOUTH" in t for t in ow.sky_strip_texts())

        # Phase advances on consumed turns, not wall-clock: four consumed
        # turns move the fast moon one step (GBC funcs5.c:1272-1279).
        ow.moon_phase = 0
        for _ in range(4):
            ow._finish_turn(None)
        assert ow.moon_phase == 1
        assert (ow.trammel_phase, ow.felucca_phase) == (0, 1)

    def test_moon_glyph_eight_distinct_phases(self, pygame_setup):
        """Two visible phase indicators: one glyph per moon, 8 distinct phase
        renderings, new moon dark / full moon lit at the disc center."""
        import pygame as pg

        from py_exodus.screens.overworld import draw_moon_glyph
        from py_exodus.ui.text_log import EGA_DARK_GRAY, EGA_WHITE

        r = 5
        glyphs = []
        for phase in range(8):
            surf = pg.Surface((2 * r + 2, 2 * r + 2), pg.SRCALPHA)
            draw_moon_glyph(surf, surf.get_width() // 2, surf.get_height() // 2, r, phase)
            glyphs.append(surf)
        # All 8 phases are visually distinct whole-glyph renderings.
        dumps = {
            tuple(tuple(surf.get_at((x, y))[:3]) for x in range(surf.get_width()) for y in range(surf.get_height()))
            for surf in glyphs
        }
        assert len(dumps) == 8

        # Phase 0 is the eclipsed/new disc: dark, not lit, at center.
        center = (r + 1, r + 1)
        assert glyphs[0].get_at(center)[:3] == EGA_DARK_GRAY
        assert glyphs[0].get_at(center)[:3] != EGA_WHITE
        # Phase 4 is the full moon: lit at center, and different from phase 0.
        assert glyphs[4].get_at(center)[:3] == EGA_WHITE

    def test_render_draws_strip_on_map0(self, asset_mgr, party, monkeypatch):
        import py_exodus.screens.overworld as ow_module

        ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)
        ow.moon_phase = 24  # Trammel 0, Felucca 0 (both glyphs still drawn)

        # The real render path draws exactly the two moon glyphs on Sosaria.
        calls: list[tuple[int, int]] = []
        real_glyph = ow_module.draw_moon_glyph

        def spy(surface, cx, cy, radius, phase, *a, **k):
            calls.append((cx, phase))
            return real_glyph(surface, cx, cy, radius, phase, *a, **k)

        monkeypatch.setattr(ow_module, "draw_moon_glyph", spy)
        ow.render(pygame.Surface((640, 400)))
        assert len(calls) == 2
        assert calls[0][1] == ow.trammel_phase
        assert calls[1][1] == ow.felucca_phase

        # On a clean surface the strip's wind text and glyph pixels appear.
        strip = pygame.Surface((176, 40))
        ow._render_sky_strip(strip, pane_right=176, pane_top=0)
        lit = sum(
            1
            for x in range(176)
            for y in range(40)
            if strip.get_at((x, y))[:3] != (0, 0, 0)
        )
        assert lit > 50  # wind text row plus both dark moon discs

    def test_render_skips_strip_on_map13(self, asset_mgr, party, monkeypatch):
        import py_exodus.screens.overworld as ow_module

        ow = OverworldScreen(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=57)
        calls: list[tuple] = []
        monkeypatch.setattr(ow_module, "draw_moon_glyph", lambda *a, **k: calls.append(a))
        ow.render(pygame.Surface((640, 400)))
        assert calls == []


# --------------------------------------------------------------------------- #
# Move-driven moon clock + stop-time gates (Task 19, GBC funcs5.c:1272-1279)
# --------------------------------------------------------------------------- #
class TestMoveDrivenMoons:
    """Moons advance ONLY on consumed turns — every 4th on the world surface
    maps (the overworld screen: Sosaria AND Ambrosia, the outdoor worlds),
    every 16th otherwise (towns/dungeons) — and the QUICKNESS (stop-time)
    aura freezes both the moon advance and food consumption."""


    def _surface_ow(self, asset_mgr, party):
        return OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)

    def test_moons_advance_every_4th_consumed_surface_turn(self, asset_mgr, party):
        """Four consumed turns on the surface advance the phase by exactly 1."""
        ow = self._surface_ow(asset_mgr, party)
        ow.moon_phase = 0
        for _ in range(3):
            ow._finish_turn(None)
        assert ow.moon_phase == 0
        ow._finish_turn(None)
        assert ow.moon_phase == 1

    def test_moon_phase_wraps_at_24(self, party):
        from py_exodus.aura import Aura
        party.aura = Aura()
        party.moon_phase = 23
        for _ in range(4):
            party.advance_moons(surface=True)
        assert party.moon_phase == 0

    def test_moons_advance_every_16th_consumed_turn_underground(self, party):
        """Non-surface maps advance the phase on the 16th consumed turn."""
        for _ in range(15):
            party.advance_moons(surface=False)
        assert party.moon_phase == 0
        party.advance_moons(surface=False)
        assert party.moon_phase == 1

    def test_moon_counter_shared_across_maps(self, party):
        """One consumed-turn counter behind the cadence, like GBC's moves
        modulo: 3 surface + 12 underground spent turns leave the 16th one
        to trigger."""
        for _ in range(3):
            party.advance_moons(surface=True)
        for _ in range(12):
            party.advance_moons(surface=False)
        assert party.moon_phase == 0
        party.advance_moons(surface=False)
        assert party.moon_phase == 1

    def test_update_dt_never_advances_moons(self, asset_mgr, party, monkeypatch):
        """The wall-clock update() no longer touches the moon phase."""
        monkeypatch.setattr("py_exodus.screens.overworld.random.random", lambda: 0.99)
        ow = self._surface_ow(asset_mgr, party)
        ow.moon_phase = 5
        ow.update(1000.0)
        assert ow.moon_phase == 5

    def test_quickness_freezes_moon_advance(self, asset_mgr, party):
        from py_exodus.aura import AuraType

        ow = self._surface_ow(asset_mgr, party)
        ow.moon_phase = 7
        # Four turns frozen under the aura; the spent turns still counted
        # (GBC's moves modulo keeps ticking under stoptime), so the cadence
        # lands on the same shared 4th slots (turn 8 = 4th counted).
        party.aura.set(AuraType.QUICKNESS, 4)
        for _ in range(4):
            ow._finish_turn(None)
        assert ow.moon_phase == 7
        for _ in range(4):
            ow._finish_turn(None)
        assert ow.moon_phase == 8

    def test_quickness_freezes_food_consumption(self, party):
        from py_exodus.aura import AuraType

        m = party.members[0]
        m.submorsels = 39  # one surface decrement from the meal crossing
        food_before = m.food

        party.aura.set(AuraType.QUICKNESS, 2)
        party.end_turn(surface=True)
        assert m.submorsels == 39
        assert m.food == food_before

        # Control: with the aura gone the meal crossing fires again.
        from py_exodus.aura import Aura
        party.aura = Aura()
        party.end_turn(surface=True)
        assert m.submorsels == 400
        assert m.food == food_before - 1

    def test_save_round_trip_preserves_integer_phase(self, party, tmp_path):
        from py_exodus.save_system import SaveSystem

        party.moon_phase = 17
        party.moon_turns = 33
        path = tmp_path / "party.json"
        SaveSystem.save_game(party, path)
        loaded = SaveSystem.load_game(path)
        assert loaded.moon_phase == 17
        assert loaded.moon_turns == 33

    def test_old_save_without_moon_phase_loads_zero(self, party):
        data = party.to_dict()
        data.pop("moon_phase", None)
        data.pop("moon_turns", None)
        p2 = Party.from_dict(data)
        assert p2.moon_phase == 0
        assert p2.moon_turns == 0
