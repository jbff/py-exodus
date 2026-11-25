"""LairWare's real-time clocks, kept in game time.

LairWare's GetKeyMouse (UltimaMain.c:3441-3475) waits ``constrain * 5`` Mac
ticks (5/60 s) for an event; each idle poll runs FullUpdate (DoWind, :3345)
when gUpdateWhere == 3, and the main loop calls WhirlPool once per poll
(:1042-1043). The port counts those polls from the dt the screens' update()
gets, never from the wall clock, so a headless batch stepping a fixed
FRAME_DT stays deterministic.
"""
from __future__ import annotations

import random
from typing import Any

from py_exodus.constants import Direction

# One GetKeyMouse wait: ``constrain * 5`` ticks of 1/60 s (UltimaMain.c:3458).
LW_POLL_SECONDS = 5 / 60
# DoWind: ``WindCtr = 32; /* SUPPOSED TO BE 8! */`` (UltimaMain.c:3291).
WIND_CTR_RESET = 32
# WhirlPool: ``gWhirlCtr = 4;`` (UltimaMain.c:2967).
WHIRL_CTR_RESET = 4
# Main loop: ``count = 60; /* SUPPOSED TO BE 0x25! */`` (UltimaMain.c:1040):
# 60 idle polls (5 s) at the command prompt pass the turn.
IDLE_PASS_POLLS = 60
# DungeonStart: ``#define PASSTIME 360 // 6 seconds`` (UltimaDngn.c:55, 110).
DUNGEON_PASS_SECONDS = 6.0


def space_event() -> Any:
    """The Space key the idle pass presses (``gKeyPress = ' ';``)."""
    import pygame

    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ")


def autoplay_on(screen: Any) -> bool:
    """Autoplay answers every wait itself, as LairWare's Macro keys answer
    GetKeyMouse at once (UltimaMain.c:3449-3454): its pauses are never idle
    time, so the idle pass holds while it runs."""
    return bool(getattr(getattr(screen, "manager", None), "autoplay_enabled", False))

# WindDir 0..4: calm, then MoreMessages 43-47 "NORTH/EAST/SOUTH/WEST WIND";
# North() passes 1, East() 2, South() 3, West() 4 to ValidTrans.
WIND_CODES: tuple[Direction | None, ...] = (
    None,
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)


class PollClock:
    """Counts whole 5/60 s polls out of the dt fed to it."""

    def __init__(self) -> None:
        self.acc = 0.0

    def polls(self, dt: float) -> int:
        self.acc += max(0.0, dt)
        # The epsilon keeps five 1/60 s frames from landing a hair short.
        n = int((self.acc + 1e-9) // LW_POLL_SECONDS)
        if n:
            self.acc = max(0.0, self.acc - n * LW_POLL_SECONDS)
        return n


def roll_wind(current: Direction | None) -> Direction | None:
    """DoWind's re-roll (UltimaMain.c:3292-3297)::

        newdir = WindDir;
        while (newdir == WindDir) {
            newdir = RandNum(0, 8);
            if (newdir > 4) newdir -= 4;
        }

    Calm 1/9, each direction 2/9, re-rolled while equal to the current wind.
    """
    old = WIND_CODES.index(current) if current in WIND_CODES else -1
    new = old
    while new == old:
        new = random.randint(0, 8)
        if new > 4:
            new -= 4
    return WIND_CODES[new]


def do_wind(party: Any) -> bool:
    """One DoWind call (UltimaMain.c:3284-3300); True when the wind changed.
    The caller skips it in the dungeon (``if (Party[3] == 1) return;``)."""
    party.wind_ctr -= 1
    if party.wind_ctr < 0:
        party.wind_ctr = WIND_CTR_RESET
        old = party.wind_direction
        party.wind_direction = roll_wind(old)
        return party.wind_direction != old
    return False


def advance_wind(party: Any, dt: float) -> bool:
    """Run DoWind once per 5/60 s poll of game time in ``dt``. Called from
    the update() of the screens where LairWare's gUpdateWhere is 3: the
    surface, towns and combat (UltimaMain.c:1021; UltimaSpellCombat.c:886)."""
    if party is None or not hasattr(party, "wind_ctr"):
        return False
    changed = False
    for _ in range(party.wind_clock.polls(dt)):
        changed = do_wind(party) or changed
    return changed
