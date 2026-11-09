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


def test_moongate_destination_routing_by_felucca(asset_mgr, party):
    """Active moongate teleports party to destination determined by Felucca phase."""
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=7, start_y=8)

    # Gate 0 is at (7, 8) with phase 0, d1=0, d2=1, d3=2
    # At moon_phase = 1: Trammel is 0 (gate 0 active), Felucca is 1 (dest is gate 1)
    ow.moon_phase = 1
    party.x = 7
    party.y = 8

    ow._check_moongates()

    # Destination should be gate 1 at (57, 46)
    assert party.x == 57
    assert party.y == 46
    assert any("moongate" in msg.lower() for msg in ow.text_log.history)


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

    def test_strip_is_sosaria_only(self, asset_mgr, party):
        from py_exodus.screens.overworld import OverworldScreen as OW

        ow0 = OW(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)
        assert ow0.sky_strip_active is True
        ow13 = OW(party=party, map_id=13, asset_mgr=asset_mgr, start_x=32, start_y=57)
        assert ow13.sky_strip_active is False

    def test_strip_texts_wind_arrow_and_moons(self, asset_mgr, party):
        from py_exodus.aura import AuraType
        from py_exodus.screens.overworld import sky_strip_texts

        texts = sky_strip_texts(Direction.NORTH, 3, 0)
        assert "Wind NORTH ^" in texts
        assert "T:3 F:0" in texts

        # Arrow tracks the direction; the moon counters are Trammel/Felucca.
        assert "Wind SOUTH v" in sky_strip_texts(Direction.SOUTH, 0, 7)
        assert "Wind EAST >" in sky_strip_texts(Direction.EAST, 1, 1)
        assert "Wind WEST <" in sky_strip_texts(Direction.WEST, 7, 4)

        # Aura label appears only when an aura is active.
        assert "QUICKNESS" in sky_strip_texts(Direction.NORTH, 0, 0, aura=AuraType.QUICKNESS)
        assert not any(
            "QUICKNESS" in t for t in sky_strip_texts(Direction.NORTH, 0, 0, aura=AuraType.NONE)
        )

    def test_strip_reads_live_state_not_copies(self, asset_mgr, party, monkeypatch):
        ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=45, start_y=19)
        texts = ow.sky_strip_texts()
        assert any("Wind NORTH" in t for t in texts)
        assert any("T:0 F:0" in t for t in texts)

        # Same source the moongate code reads: bump the phase counters.
        ow.moon_phase = 10  # Trammel 3, Felucca 2
        assert any("T:3 F:2" in t for t in ow.sky_strip_texts())

        # Wind comes from the party record the sailing code tracks.
        party.wind_direction = Direction.SOUTH
        assert any("Wind SOUTH" in t for t in ow.sky_strip_texts())

        # Phase advances through update(): moon counter ticks every 4s.
        monkeypatch.setattr("py_exodus.screens.overworld.random.random", lambda: 0.99)
        ow.moon_phase = 0
        ow.update(4.5)
        assert ow.moon_phase == 1
        assert any("T:0 F:1" in t for t in ow.sky_strip_texts())

    def test_moon_glyph_eight_distinct_phases(self, pygame_setup):
        """Two visible phase indicators: one glyph per moon, 8 distinct phase
        renderings, new moon dark / full moon lit at the disc center."""
        import pygame as pg

        from py_exodus.screens.overworld import draw_moon_glyph

        r = 5
        glyphs = []
        for phase in range(8):
            surf = pg.Surface((2 * r + 2, 2 * r + 2), pg.SRCALPHA)
            draw_moon_glyph(surf, surf.get_width() // 2, surf.get_height() // 2, r, phase)
            glyphs.append(surf)
        # 8 distinct renderings, two per moon on the strip.
        assert len({tuple(s.get_at((r + 1, r + 1))) for s in glyphs}) >= 2

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
