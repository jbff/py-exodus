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
from py_exodus.world.map import DungeonTile  # noqa: E402

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

    # level 2 (z=1): door straight ahead (framed box), border wall beside
    surf = pygame.Surface((176, 176))
    cam.render_wireframe(surf, dmap, 4, 1, 1, Direction.WEST, torch_lit=True)
    surf = pygame.transform.scale(surf, (580, 580))
    pygame.image.save(surf, os.path.join(out, "L2door_WEST.png"))

    # walk sequence along row 7 heading EAST toward a door 5 tiles out:
    # side walls appear at depth 2 and slide past as the party advances
    for i, wx in enumerate((3, 4, 6)):
        surf = pygame.Surface((176, 176))
        cam.render_wireframe(surf, dmap, wx, 7, 0, Direction.EAST, torch_lit=True)
        surf = pygame.transform.scale(surf, (580, 580))
        pygame.image.save(surf, os.path.join(out, f"walk1_{i}.png"))

    # wandering monsters in the view, from (8,3) facing EAST — perinian L1
    # row 3 is a long open corridor with an opening at (9,4): one monster
    # one tile ahead, one two ahead (visibly smaller), one through the
    # side opening at (9,4) (perinian.ult bytes; see the tile map dump).
    from py_exodus.entities.defs import CreatureDef  # noqa: E402
    from py_exodus.world.dungeon import WanderingCreature  # noqa: E402

    def _monster(tx, ty):
        return WanderingCreature(
            CreatureDef(id=10, name="Orc", tile="orc", basehp=30), tx, ty, 0
        )

    for name, cr in (
        ("monster_1_ahead", _monster(9, 3)),
        ("monster_2_ahead", _monster(10, 3)),
        ("monster_off_axis", _monster(9, 4)),
    ):
        surf = pygame.Surface((176, 176))
        cam.render_wireframe(
            surf, dmap, 8, 3, 0, Direction.EAST, torch_lit=True, creatures=[cr]
        )
        surf = pygame.transform.scale(surf, (580, 580))
        pygame.image.save(surf, os.path.join(out, f"{name}.png"))

    # The "cross/altar thing": Java draws no altar mesh and the dungeon data
    # holds no altar tiles at all (byte 0x01 is the Time Lord, byte 0x00 the
    # open floor; ALTAR's enum value collides with NOTHING so it can never be
    # produced by either the data or the maps.xml labels). The plus-shaped
    # sparkle the playtest read as a cross is the Mark pedestal — MARK lives
    # at byte 0x05 and the level-1 label turns (15,11) into a MARK_KINGS.
    # Sample that: the party facing the pedestal from two tiles away.
    surf = pygame.Surface((176, 176))
    dmap.set_tile(15, 10, 0, DungeonTile.NOTHING)  # keep the corridor clear
    cam.render_wireframe(
        surf, dmap, 15, 9, 0, Direction.SOUTH, torch_lit=True
    )
    surf = pygame.transform.scale(surf, (580, 580))
    pygame.image.save(surf, os.path.join(out, "mark_pedestal_SOUTH.png"))

    print("samples:", out)


if __name__ == "__main__":
    main()
