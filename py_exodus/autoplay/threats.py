"""Overworld threat geometry for autoplay: pirate firing lanes and squid zones.

Pirate firing lane (engine rule, ``OverworldScreen._update_creatures``): a
pirate fires a broadside whenever the party is in its row or column at
movement distance 2 or 3 and the pirate's broadside faces the party; a
misaligned pirate turns to face 1-in-2 and fires next tick. Firing forfeits
the pirate's move, so it fires every tick the party stays. The enemy cannon
hits 1-in-3: a ship loses 10 hull (0 = party lost), on foot every member
takes 10-25 on a coin flip. At distance 1 an aligned pirate battles instead
(the way a ship is captured).

Rule (applies on foot and at sea, before every move or wait): never end a
turn on a lane tile. Step off the line, back out past distance 3, or close
to distance 1 and fight.

Squids (Man-O-War): until a Cleric or Druid can cast ALCORT (35 MP), never
let one engage (distance <= 1) on foot or at sea; on foot stay off the coast
near them, at sea shoot them with the cannons.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from py_exodus.constants import Direction, Profession

SEA_MONSTERS = frozenset({"pirate", "serpent", "squid"})
_CARDINALS = (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST)


def creature_name(c: dict) -> str:
    return str(c.get("tile_name") or c.get("tile") or "").lower()


def wrap_delta(a: int, b: int, span: int) -> int:
    """Signed shortest offset from a to b on a wrapping axis."""
    d = (b - a) % span
    return d - span if d > span // 2 else d


def manhattan(w: int, h: int, a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(wrap_delta(a[0], b[0], w)) + abs(wrap_delta(a[1], b[1], h))


def lane_tiles_for(w: int, h: int, pirate: tuple[int, int]) -> set[tuple[int, int]]:
    px, py = pirate
    out: set[tuple[int, int]] = set()
    for dist in (2, 3):
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            out.add(((px + dx * dist) % w, (py + dy * dist) % h))
    return out


def party_has_alcort(party) -> bool:
    """A living Cleric or Druid whose MP pool can hold ALCORT (35 MP)."""
    return any(
        not m.is_dead()
        and m.profession in (Profession.CLERIC, Profession.DRUID)
        and m.max_mp >= 35
        for m in party.members
    )


@dataclass
class Threats:
    """Threat geometry for one overworld tick."""

    width: int
    height: int
    pirates: list[tuple[int, int]] = field(default_factory=list)
    lanes: set[tuple[int, int]] = field(default_factory=set)
    squids: list[tuple[int, int]] = field(default_factory=list)
    squid_engage: set[tuple[int, int]] = field(default_factory=set)
    squid_coast: set[tuple[int, int]] = field(default_factory=set)

    def in_lane(self, pos: tuple[int, int]) -> bool:
        return pos in self.lanes

    def lane_pirates(self, pos: tuple[int, int]) -> list[tuple[int, int]]:
        return [p for p in self.pirates if pos in lane_tiles_for(self.width, self.height, p)]

    def unsafe_end(self, pos: tuple[int, int]) -> bool:
        """True when ending a turn on ``pos`` invites cannon fire or a squid."""
        return pos in self.lanes or pos in self.squid_engage

    def hard_avoid(self) -> set[tuple[int, int]]:
        return self.lanes | self.squid_engage


def compute_threats(gmap, party, creatures, fight_squids: bool = False) -> Threats:
    """``fight_squids``: the party meets squids instead of keeping clear
    (user rule 2026-11-21: fight the squid on foot, cannon it from a ship)."""
    w, h = gmap.width, gmap.height
    th = Threats(w, h)
    avoid_squids = not party_has_alcort(party) and not fight_squids
    for c in creatures:
        if "x" not in c or "y" not in c:
            continue
        name = creature_name(c)
        pos = (c["x"], c["y"])
        if name == "pirate":
            th.pirates.append(pos)
            th.lanes |= lane_tiles_for(w, h, pos)
        elif name == "squid" and avoid_squids:
            th.squids.append(pos)
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    d = abs(dx) + abs(dy)
                    t = ((pos[0] + dx) % w, (pos[1] + dy) % h)
                    if d <= 1:
                        th.squid_engage.add(t)
                    if d <= 3:
                        th.squid_coast.add(t)
    # A pirate's own tile and its neighbours are never "lane" tiles.
    return th


@dataclass
class Move:
    key: str  # "move", "attack", "fire", "wait"
    direction: Direction | None = None


def foot_escape(
    gmap, party, pos: tuple[int, int], threats: Threats, can_enter, prefer_engage: bool
) -> Move:
    """Choose this turn's action when standing in a pirate lane on foot.

    ``can_enter(x, y)`` says whether the party may step onto a tile.
    Preference: attack an orthogonally adjacent pirate; step to a tile
    next to the lane pirate (engage next turn) when ``prefer_engage``; else
    step to the safe tile farthest from the lane pirates; else the least bad
    step.
    """
    w, h = threats.width, threats.height
    lane_p = threats.lane_pirates(pos) or threats.pirates
    for d in _CARDINALS:
        n = ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h)
        if n in threats.pirates:
            return Move("attack", d)
    best: tuple[tuple, Direction] | None = None
    for d in _CARDINALS:
        n = ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h)
        if not can_enter(*n):
            continue
        dmin = min((manhattan(w, h, n, p) for p in lane_p), default=99)
        engage = dmin == 1 and any(
            n[0] == p[0] or n[1] == p[1] for p in lane_p if manhattan(w, h, n, p) == 1
        )
        unsafe = threats.unsafe_end(n)
        score = (
            unsafe,
            not (engage and prefer_engage),
            -dmin if not (engage and prefer_engage) else 0,
        )
        if best is None or score < best[0]:
            best = (score, d)
    if best is not None:
        return Move("move", best[1])
    return Move("wait")


def ship_escape(
    gmap,
    party,
    pos: tuple[int, int],
    heading: Direction,
    threats: Threats,
    can_sail,
    prefer_engage: bool,
) -> Move:
    """Choose this turn's action when a ship sits in a pirate lane.

    A ship moves only along its heading; any other direction spends the turn
    turning (overworld ``_move_avatar``), and the wind blocks sailing into
    it. Preference: sail to a safe tile along the heading (closing to an
    engagement tile counts as safe); otherwise fire the broadside at a lane
    pirate it bears on; otherwise turn toward a direction that leads out.
    """
    w, h = threats.width, threats.height
    wind = getattr(party, "wind_direction", None)
    blocked = wind.reverse() if wind is not None else None
    lane_p = threats.lane_pirates(pos) or threats.pirates

    def dest(d: Direction) -> tuple[int, int]:
        return ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h)

    # 1. Sail straight on (no turn needed) to a safe tile.
    if wind is not None and heading != blocked:
        n = dest(heading)
        if can_sail(*n) and not threats.unsafe_end(n):
            dmin = min((manhattan(w, h, n, p) for p in lane_p), default=99)
            if dmin != 1 or prefer_engage:
                return Move("move", heading)
    # 1b. Commit: the heading points straight at a lane pirate (same line,
    # ahead of the bow). Sailing on closes to distance 1 and the battle
    # (that is how a ship is taken) within two ticks; user rule: in a lane,
    # keep advancing to fight or leave, never sit under fire.
    if prefer_engage and wind is not None and heading != blocked:
        n = dest(heading)
        if can_sail(*n) and n not in threats.squid_engage:
            for p in lane_p:
                d_now = manhattan(w, h, pos, p)
                d_next = manhattan(w, h, n, p)
                same_line = (n[0] == p[0]) or (n[1] == p[1])
                if same_line and d_next < d_now:
                    return Move("move", heading)
    # 2. Fire the broadside at a lane pirate it bears on (the cannon trace
    # stops at the map edge; it does not wrap).
    horiz = heading in (Direction.NORTH, Direction.SOUTH)
    for p in lane_p:
        dx = p[0] - pos[0]
        dy = p[1] - pos[1]
        if horiz and dy == 0 and 1 <= abs(dx) <= 3:
            return Move("fire", Direction.EAST if dx > 0 else Direction.WEST)
        if not horiz and dx == 0 and 1 <= abs(dy) <= 3:
            return Move("fire", Direction.SOUTH if dy > 0 else Direction.NORTH)
    # 3. Turn toward a direction whose next tile is safe (move next turn).
    best: tuple[tuple, Direction] | None = None
    for d in _CARDINALS:
        if d == heading or d == blocked:
            continue
        n = dest(d)
        if not can_sail(*n):
            continue
        dmin = min((manhattan(w, h, n, p) for p in lane_p), default=99)
        score = (threats.unsafe_end(n), -dmin)
        if best is None or score < best[0]:
            best = (score, d)
    if best is not None:
        return Move("move", best[1])
    return Move("wait")


def is_engage_tile(threats: Threats, pos: tuple[int, int]) -> bool:
    """Orthogonally adjacent to a pirate (where the battle starts)."""
    w, h = threats.width, threats.height
    return any(manhattan(w, h, pos, p) == 1 for p in threats.pirates)
