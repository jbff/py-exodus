"""Tests for 2D World Viewport Renderer, Camera, Field of View, and Collision."""
import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.constants import Profession, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.ui.renderer import WorldRenderer, can_move_to, check_collision
from py_exodus.world.field_of_view import compute_fov
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import GameMap, MapNpc


@pytest.fixture(scope="module")
def asset_mgr() -> AssetManager:
    """Fixture providing initialized AssetManager with loaded tiles and XML definitions."""
    pygame.init()
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture(scope="module")
def map_loader(asset_mgr: AssetManager) -> MapLoader:
    """Fixture providing MapLoader."""
    return MapLoader(asset_mgr)


def test_viewport_rendering(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify basic 11x11 viewport rendering onto a 176x176 surface."""
    surf = pygame.Surface((176, 176))
    m = map_loader.load_map(0)  # Sosaria
    renderer = WorldRenderer(asset_mgr)
    renderer.render_viewport(surf, m, 45, 18, anim_frame=0)
    assert surf.get_at((0, 0)) is not None
    # Center tile (45, 18) is Lord British's castle, rendered at (80, 80)
    center_color = surf.get_at((80, 80))
    assert center_color is not None


def test_viewport_wrapping(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify viewport camera wraps correctly around Sosaria 64x64 edges."""
    surf = pygame.Surface((176, 176))
    m = map_loader.load_map(0)
    assert m.border_behavior == "wrap"

    renderer = WorldRenderer(asset_mgr)
    # Render at map boundary (0, 0)
    renderer.render_viewport(surf, m, 0, 0, anim_frame=0)
    # Corner (0, 0) in viewport corresponds to (-5, -5) -> (59, 59)
    # Verify no exception and valid surface colors
    assert surf.get_at((0, 0)) is not None
    assert surf.get_at((175, 175)) is not None


def test_viewport_non_wrapping_bounds(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify viewport handles fixed and exit border behaviors without crashing."""
    surf = pygame.Surface((176, 176))
    # Map 37 is a Combat map (11x11, borderbehavior=fixed, nolineofsight=true)
    m = map_loader.load_map(37)
    assert m.border_behavior == "fixed"

    renderer = WorldRenderer(asset_mgr)
    # Render at (0, 0): top-left tiles are out of bounds and should be black
    renderer.render_viewport(surf, m, 0, 0, anim_frame=0)
    # Top-left of viewport (0, 0) is (-5, -5) -> out of bounds -> black (0, 0, 0)
    assert surf.get_at((0, 0))[:3] == (0, 0, 0)


def test_animation_frame_cycling(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify animated tiles change appearance across animation frames."""
    surf0 = pygame.Surface((176, 176))
    surf1 = pygame.Surface((176, 176))

    m = map_loader.load_map(0)
    renderer = WorldRenderer(asset_mgr)

    # (0, 20) is ocean/water in Sosaria
    renderer.render_viewport(surf0, m, 0, 20, anim_frame=0)
    renderer.render_viewport(surf1, m, 0, 20, anim_frame=1)

    # Surface bytes or colors should differ between water animation frames
    bytes0 = pygame.image.tobytes(surf0, "RGBA")
    bytes1 = pygame.image.tobytes(surf1, "RGBA")
    assert bytes0 != bytes1


def test_dynamic_objects_rendering(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify dynamic objects (frigate, horse, chest) render at their grid locations."""
    surf_empty = pygame.Surface((176, 176))
    surf_objs = pygame.Surface((176, 176))

    m = map_loader.load_map(0)
    renderer = WorldRenderer(asset_mgr)

    # Render without dynamic objects
    renderer.render_viewport(surf_empty, m, 45, 18, anim_frame=0)

    # Create party with dynamic objects near (45, 18)
    party = Party(
        members=[Character(name="Hero", profession=Profession.PALADIN)],
        x=45,
        y=18,
    )
    # Chest at (46, 18) -> pixel (96, 80)
    party.dynamic_objects.append({"tile_name": "chest", "x": 46, "y": 18})
    # Horse at (45, 17) -> pixel (80, 64)
    party.dynamic_objects.append({"tile_name": "horse", "x": 45, "y": 17})

    renderer.render_viewport(surf_objs, m, 45, 18, anim_frame=0, party=party)

    # Pixel (104, 88) (center of chest tile at 96, 80) must differ from empty terrain
    assert surf_objs.get_at((104, 88)) != surf_empty.get_at((104, 88))
    # Pixel (88, 72) (center of horse tile at 80, 64) must differ
    assert surf_objs.get_at((88, 72)) != surf_empty.get_at((88, 72))


def test_party_avatar_rendering(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify party avatar renders according to transport mode (foot, horse, ship)."""
    m = map_loader.load_map(0)
    renderer = WorldRenderer(asset_mgr)

    # Foot transport
    p_foot = Party(
        members=[Character(name="Mage", profession=Profession.WIZARD)],
        x=45,
        y=18,
        transport=Transport.FOOT,
    )
    surf_foot = pygame.Surface((176, 176))
    renderer.render_viewport(surf_foot, m, 45, 18, anim_frame=0, party=p_foot)

    # Horse transport
    p_horse = Party(
        members=[Character(name="Mage", profession=Profession.WIZARD)],
        x=45,
        y=18,
        transport=Transport.HORSE,
    )
    surf_horse = pygame.Surface((176, 176))
    renderer.render_viewport(surf_horse, m, 45, 18, anim_frame=0, party=p_horse)

    # Ship transport
    p_ship = Party(
        members=[Character(name="Mage", profession=Profession.WIZARD)],
        x=45,
        y=18,
        transport=Transport.SHIP,
    )
    surf_ship = pygame.Surface((176, 176))
    renderer.render_viewport(surf_ship, m, 45, 18, anim_frame=0, party=p_ship)

    # Center of party avatar tile (88, 88) should differ between foot, horse, and ship avatars
    center_foot = surf_foot.get_at((88, 88))
    center_horse = surf_horse.get_at((88, 88))
    center_ship = surf_ship.get_at((88, 88))
    assert center_foot != center_horse
    assert center_foot != center_ship


def test_npc_rendering(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify NPCs in town/castle maps render at their designated coordinates."""
    # Map 1 is British castle with Lord British and guards
    m = map_loader.load_map(1)
    assert len(m.npcs) > 0

    npc = m.npcs[0]
    surf = pygame.Surface((176, 176))
    renderer = WorldRenderer(asset_mgr)
    renderer.render_viewport(surf, m, npc.x, npc.y, anim_frame=0)

    # NPC is centered at (80, 80)
    assert surf.get_at((80, 80)) is not None


def test_field_of_view_open_field(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify compute_fov calculates visible tiles in unobstructed terrain."""
    m = map_loader.load_map(0)
    # Origin at (30, 30), radius = 4
    fov = compute_fov(m, 30, 30, radius=4)

    assert (30, 30) in fov
    # Immediate cardinal neighbors should be visible
    assert (30, 29) in fov
    assert (30, 31) in fov
    assert (29, 30) in fov
    assert (31, 30) in fov
    # Tiles beyond radius (e.g. distance 6) should not be visible
    assert (30, 36) not in fov


def test_field_of_view_opaque_blocking(asset_mgr: AssetManager) -> None:
    """Verify compute_fov blocks line of sight behind opaque tiles (walls, mountains, forest)."""
    # Create a small custom test map
    grass = asset_mgr.get_tile_by_name("grass")
    wall = asset_mgr.get_tile_by_name("wall")
    assert wall.opaque is True

    test_map = GameMap(
        id=99,
        name="Test",
        width=11,
        height=11,
        border_behavior="fixed",
        no_line_of_sight=False,
        tiles=[grass] * 121,
    )
    # Place a wall at (6, 5) directly east of origin (5, 5)
    test_map.set_tile(6, 5, wall)

    fov = compute_fov(test_map, 5, 5, radius=4)

    # Origin and wall itself are visible
    assert (5, 5) in fov
    assert (6, 5) in fov
    # Tile directly behind the wall (7, 5) and (8, 5) should be blocked by shadow
    assert (7, 5) not in fov
    assert (8, 5) not in fov


def test_field_of_view_no_line_of_sight(asset_mgr: AssetManager) -> None:
    """Verify maps with no_line_of_sight=True do not cast shadows."""
    grass = asset_mgr.get_tile_by_name("grass")
    wall = asset_mgr.get_tile_by_name("wall")

    test_map = GameMap(
        id=99,
        name="Arena",
        width=11,
        height=11,
        border_behavior="fixed",
        no_line_of_sight=True,  # Line of sight disabled
        tiles=[grass] * 121,
    )
    test_map.set_tile(6, 5, wall)

    fov = compute_fov(test_map, 5, 5, radius=4)

    # Behind the wall SHOULD be visible because line of sight is disabled
    assert (7, 5) in fov
    assert (8, 5) in fov


def test_field_of_view_wrapping(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify compute_fov wraps coordinates on Sosaria (64x64)."""
    m = map_loader.load_map(0)
    assert m.border_behavior == "wrap"

    # Origin at (0, 0), radius = 3
    fov = compute_fov(m, 0, 0, radius=3)

    assert (0, 0) in fov
    # West neighbor wraps to (63, 0)
    assert (63, 0) in fov or (-1, 0) in fov
    # North neighbor wraps to (0, 63)
    assert (0, 63) in fov or (0, -1) in fov


def test_collision_checks(asset_mgr: AssetManager, map_loader: MapLoader) -> None:
    """Verify collision and movement validation for various terrains and transport modes."""
    m = map_loader.load_map(0)

    # Grass is walkable on foot
    grass_x, grass_y = 40, 13
    assert can_move_to(m, grass_x, grass_y, Transport.FOOT) is True
    assert check_collision(m, grass_x, grass_y, Transport.FOOT) is False

    # Water is unwalkable on foot, but sailable with SHIP
    water_x, water_y = 0, 20
    assert can_move_to(m, water_x, water_y, Transport.FOOT) is False
    assert check_collision(m, water_x, water_y, Transport.FOOT) is True
    assert can_move_to(m, water_x, water_y, Transport.SHIP) is True
    assert check_collision(m, water_x, water_y, Transport.SHIP) is False

    # Mountains are unwalkable on foot and with ship
    mountain_tile = asset_mgr.get_tile_by_name("mountains")
    m.set_tile(30, 30, mountain_tile)
    assert can_move_to(m, 30, 30, Transport.FOOT) is False
    assert can_move_to(m, 30, 30, Transport.SHIP) is False
    assert can_move_to(m, 30, 30, Transport.HORSE) is False

    # NPC on a tile blocks movement
    m.npcs.append(MapNpc(tile_index=1, tile_name="guard", x=31, y=31, start_x=31, start_y=31))
    assert can_move_to(m, 31, 31, Transport.FOOT) is False
    assert check_collision(m, 31, 31, Transport.FOOT) is True
