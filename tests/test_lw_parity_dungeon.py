"""LairWare parity, batch D (dungeons): pins LairWare dungeon rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "D - Dungeon".
"""
from __future__ import annotations

import random

import pytest

from py_exodus.constants import Direction, Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile


def _party(*members: Character) -> Party:
    p = Party(food=200, gold=0)
    for m in members or (
        Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=500, max_hp=500, torches=5),
        Character("Mage", "F", Race.ELF, Profession.WIZARD, hp=400, max_hp=400, torches=0),
    ):
        p.add_member(m)
    return p


def _dmap(fill: DungeonTile = DungeonTile.NOTHING) -> DungeonMap:
    dmap = DungeonMap(id=98, name="Test", width=16, height=16, levels=8)
    dmap.tiles = [[[fill for _x in range(16)] for _y in range(16)] for _z in range(8)]
    return dmap


class SeqRNG(random.Random):
    """randint answers from a script (LairWare RandNum(a, b) is inclusive)."""

    def __init__(self, ints):
        super().__init__(0)
        self.ints = list(ints)
        self.calls: list[tuple[int, int]] = []

    def randint(self, a, b):
        self.calls.append((a, b))
        return self.ints.pop(0)


# --- D-02 RelocateDungeon, DownLevel --------------------------------------


def test_relocatedungeon_rolls_randnum_0_16_until_an_empty_tile():
    """UltimaSpellCombat.c:576-586:
        value = -1;
        while (value != 0) {
            xs = RandNum(0, 16);
            ys = RandNum(0, 16);
            value = GetXYDng(xs, ys);
        }
    GetXYDng (758-768) wraps 16 to 0. The port tried 32 uniform 0-15 picks
    and stayed put when they all missed."""
    dmap = _dmap(DungeonTile.WALL)
    dmap.set_tile(0, 3, 1, DungeonTile.NOTHING)
    # 40 misses (more than the port's 32 tries), then x=16 (wraps to 0), y=3.
    rng = SeqRNG([5, 5] * 40 + [16, 3])
    state = DungeonState(dmap, start_x=1, start_y=1, start_z=0, party=_party(), rng=rng)
    state.spell_down()
    assert (state.x, state.y, state.z) == (0, 3, 1)
    assert set(rng.calls) == {(0, 16)}


def test_downlevel_spell_down_never_steps_past_the_last_level():
    """UltimaSpellCombat.c:594-597: `if (dungeonLevel > 6) { Failed(); return; }`.
    The port's spell_down stepped z to 8, a level that does not exist."""
    state = DungeonState(_dmap(), start_x=3, start_y=3, start_z=7, party=_party())
    evt = state.spell_down()
    assert state.z == 7
    assert (state.x, state.y) == (3, 3)
    assert evt.success is False
