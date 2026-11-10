"""Render dungeon 3D wireframe view samples to PNG for visual inspection.

Not part of the test suite.  Usage:
    python -I scripts/render_dungeon_samples.py [outdir]

Renders the perinian (dungeon 1) level 1 view from a fixed spot with mixed
walls/openings/doors at each of the 4 facings, plus level 2 with doors, at
176px native and 33x scale (580x580).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from py_exodus.assets import AssetManager  # noqa: E402
from py_exodus.constants import Direction  # noqa: E402
from py_exodus.world.dungeon import DungeonCamera  # noqa: E402
from py_exodus.world.loader import MapLoader  # noqa: E402

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".superpowers", "dungeonrender-samples",
)

SPOT = (10, 1)  # L1: open ahead (door at depth 2), WALL left and right
DEEP_SPOT = (11, 2)  # L1: facing SOUTH — door ahead at depth 1, walls beside


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    os.makedirs(out, exist_ok=True)
    pygame.init()

    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    dmap = MapLoader(am).load_dungeon_map("perinian.ult")

    cam = DungeonCamera()
    for d in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
        surf = pygame.Surface((176, 176))
        cam.render_wireframe(surf, dmap, SPOT[0], SPOT[1], 0, d, torch_lit=True)
        surf = pygame.transform.scale(surf, (580, 580))
        pygame.image.save(surf, os.path.join(out, f"L1_{d.name}.png"))

    for d in (Direction.NORTH, Direction.SOUTH):
        surf = pygame.Surface((176, 176))
        cam.render_wireframe(surf, dmap, DEEP_SPOT[0], DEEP_SPOT[1], 0, d, torch_lit=True)
        surf = pygame.transform.scale(surf, (580, 580))
        pygame.image.save(surf, os.path.join(out, f"L1door_{d.name}.png"))

    # level 2 (z=1): door straight ahead, wall on the right, open left
    surf = pygame.Surface((176, 176))
    cam.render_wireframe(surf, dmap, 4, 1, 1, Direction.WEST, torch_lit=True)
    surf = pygame.transform.scale(surf, (580, 580))
    pygame.image.save(surf, os.path.join(out, "L2door_WEST.png"))

    print("samples:", out)


if __name__ == "__main__":
    main()
