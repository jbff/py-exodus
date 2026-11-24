"""LairWare parity, batch M (monsters outside combat).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "M - Monsters".
"""
from __future__ import annotations

import random

import pygame
import pytest

from py_exodus.aura import AuraType
from py_exodus.constants import Profession, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.map import MapNpc


def _member(name: str = "Hero", hp: int = 200, max_hp: int = 300) -> Character:
    return Character(
        name=name,
        profession=Profession.FIGHTER,
        hp=hp,
        max_hp=max_hp,
        mp=0,
        max_mp=0,
        food=150,
        gold=100,
        status=Status.GOOD,
    )


def _party(*members: Character) -> Party:
    party = Party()
    for m in members or (_member(),):
        party.add_member(m)
    for m in party.members:
        m.submorsels = 400  # no meal crossing inside a short test
    return party


def _key(screen, k: int) -> None:
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=""))


@pytest.fixture
def overworld(pygame_setup, asset_mgr):
    from py_exodus.screens.overworld import OverworldScreen

    def make(x: int, y: int, party: Party | None = None, encounters: bool = False,
             clear: bool = True):
        scr = OverworldScreen(
            party=party or _party(),
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=x,
            start_y=y,
            random_encounters=encounters,
        )
        scr.party.x, scr.party.y = x, y
        scr.party.objects_map_id = 0
        if clear:
            scr.creatures = []
        scr._check_moongates = lambda: None  # type: ignore[method-assign]
        return scr

    return make


class _Rolls:
    """random.randint stand-in: answers by bounds from a table of queues.

    ``table[(a, b)]`` is a list; each call pops the first value, and the last
    value repeats once the list is down to one. Unlisted bounds return ``a``.
    """

    def __init__(self, table: dict[tuple[int, int], list[int]]) -> None:
        self.table = {k: list(v) for k, v in table.items()}
        self.calls: list[tuple[int, int]] = []

    def __call__(self, a: int, b: int) -> int:
        self.calls.append((a, b))
        q = self.table.get((a, b))
        if not q:
            return a
        return q.pop(0) if len(q) > 1 else q[0]


def _monster(kind: str, x: int, y: int, **extra) -> dict:
    return {"name": kind.capitalize(), "tile_name": kind, "tile": kind, "x": x, "y": y, **extra}


def _whirlpools(scr) -> list[dict]:
    return [c for c in scr.creatures if c.get("tile_name") == "whirlpool"]


# --- M-03: spawn start terrain ----------------------------------------------


def test_spawnmonster_start_terrain_is_plain_water_or_grass_without_objects(
    overworld, monkeypatch
):
    """UltimaMisc.c:1165-1180 (SpawnMonster):

        Monsters[offset + TILEON] = MonBegin[type];
        ...
        if (GetXYVal(Monsters[offset + XMON], Monsters[offset + YMON]) != Monsters[offset + TILEON]) {
            Monsters[offset] = 0;
            goto spawn;

    MonBegin is 0 (water) for the sea types and 4 (grass) for the land types,
    and the map value must equal it exactly: a sea monster never starts on a
    snake tile, and nothing starts on a parked ship (0x2C), a horse (0x28) or
    a dropped chest (0x24), which are map values of their own in LairWare.
    """
    ow = overworld(20, 20)
    snake = ow.game_map.get_tile(10, 57)
    water = ow.game_map.get_tile(10, 56)
    rolls = _Rolls({(0, 12): [6]})  # 6 & 6 = type 6, the Sea Serpent
    monkeypatch.setattr(random, "randint", rolls)
    assert ow._pick_creature_for_tile(water) == "serpent"
    assert ow._pick_creature_for_tile(snake) is None

    # A parked frigate at (10, 56): the serpent cannot start there.
    ow.party.dynamic_objects = [{"tile": "frigate", "x": 10, "y": 56}]
    rolls = _Rolls({(0, 134): [134], (0, 63): [10, 56] * 40, (0, 12): [6], (0, 1): [0]})
    monkeypatch.setattr(random, "randint", rolls)
    ow._spawn_wandering_creature()
    assert ow.creatures == []
    # Without the frigate the same rolls place it.
    ow.party.dynamic_objects = []
    ow._spawn_wandering_creature()
    assert [(c["tile_name"], c["x"], c["y"]) for c in ow.creatures] == [("serpent", 10, 56)]


# --- M-04: monster terrain ----------------------------------------------------


def test_validmonsterdir_land_and_sea_terrain(overworld, asset_mgr):
    """UltimaMisc.c:263-272 (ValidMonsterDir):

        if (montype > 0x28 && montype < 0x40) {   // pirate/sea monster
            return (tile == 0) ? 0 : 255;
        } else {
            if (tile == 4 || tile == 8 || tile == 12 || tile == 32)
                return 0;

    Land monsters walk only on grass, brush, forest and floor; the serpent,
    Man-O-War and pirate only on plain water. Lava, snakes and the tiles of a
    parked ship, horse or dropped chest are closed to them.
    """
    ow = overworld(20, 20)
    orc = _monster("orc", 49, 36)
    orc_def = asset_mgr.get_creature("orc")
    assert ow._creature_can_enter(orc, orc_def, 49, 37) is False  # mountains
    assert ow._creature_can_enter(orc, orc_def, 48, 36) is True  # forest
    assert ow._creature_can_enter(orc, orc_def, 48, 35) is False  # lava
    ow.party.dynamic_objects = [{"tile": "chest", "x": 48, "y": 36}]
    assert ow._creature_can_enter(orc, orc_def, 48, 36) is False  # dropped chest

    serpent = _monster("serpent", 10, 56)
    s_def = asset_mgr.get_creature("serpent")
    assert ow._creature_can_enter(serpent, s_def, 10, 55) is True  # water
    assert ow._creature_can_enter(serpent, s_def, 10, 57) is False  # snake
    pirate = _monster("pirate", 10, 56)
    p_def = asset_mgr.get_creature("pirate")
    ow.party.dynamic_objects = [{"tile": "frigate", "x": 10, "y": 55}]
    assert ow._creature_can_enter(pirate, p_def, 10, 55) is False  # parked ship
