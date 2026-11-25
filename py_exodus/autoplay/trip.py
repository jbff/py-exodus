"""Trip planner: the single owner of ship boarding (B) and leaving (X).

Goal handlers name a :class:`Destination`. :func:`plan_trip` returns a
committed, costed :class:`TripPlan` built from legs: walking, sailing our own
ship, capturing a ship at a coast, or stepping through a moongate. The
controller's ``TripFollower`` executes the plan's legs until arrival or until
the plan is invalidated; no other autoplay code emits B or X.

Search space: Dijkstra over ``(x, y, mode)`` with ``mode`` in {FOOT, SHIP}.

- FOOT step onto a walkable land tile (lava needs the Mark of Fire, energy
  fields need every member's Mark of Force, locked doors need a key), or onto
  the water tile of a frigate we can board.
- SHIP step onto a sailable tile. Wind is unknown in advance, so a sea step
  costs ``SAIL_STEP_COST``.
- B: FOOT -> SHIP on a frigate tile.
- X: SHIP -> FOOT on a water tile with an orthogonal walkable land neighbour
  (autoplay's own choice: LairWare's Exit allows any water tile, but a
  party left on foot at sea can only board again).
- CAPTURE: FOOT on a coast land tile -> SHIP on the adjacent water. With
  live ``pirates`` given, only coasts of a body of water holding a pirate
  qualify (cost grows with the distance to the nearest one); the follower
  hunts that pirate along the coast and fights it from land, and the
  defeated pirate leaves a frigate, which triggers a re-plan. Where pirates
  can still spawn (Sosaria), any coast is a patrol capture at a surcharge:
  the follower walks the coast until one shows up. Never a wait.
- GATE: FOOT on moongate site ``s`` -> FOOT on site ``d``. Phases follow
  ``moon_phase`` 0..23 (trammel = p // 3, felucca = p % 8), so site ``s``
  reaches ``{(3s + k) % 8 for k in 0..2}``. A full moon cycle is 96 surface
  turns, so a gate costs about half a cycle of waiting.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from py_exodus.autoplay.nav import locked_door_passable
from py_exodus.constants import Transport
from py_exodus.ui.renderer import can_move_to
from py_exodus.world import tile_effects

if TYPE_CHECKING:
    from collections.abc import Iterable

    from py_exodus.entities.party import Party
    from py_exodus.world.map import GameMap

FOOT = Transport.FOOT
SHIP = Transport.SHIP

WALK_STEP_COST = 1.0
SAIL_STEP_COST = 1.5
BOARD_COST = 1.0
EXIT_COST = 1.0
GATE_COST = 50.0
CAPTURE_COST = 250.0
PATROL_CAPTURE_EXTRA = 250.0
# Smallest body of water worth waiting on for a pirate to appear (or the
# map's largest, on small maps). Exodus
# island's inner pond (5 tiles behind the serpent) never gets one: routing
# a capture there left parties pacing its shore until they starved
# (rules-c84c7c6 batch, 2026-11-22).
OPEN_WATER_MIN = 100
REVERSE_TRANSITION_PENALTY = 200.0

_NEIGHBOURS = ((0, -1), (0, 1), (-1, 0), (1, 0))


@dataclass(frozen=True)
class Destination:
    """Where a goal wants the party, and in which transport mode.

    ``need`` is FOOT, SHIP or None (either). ``moving`` marks targets that
    drift every turn (whirlpools): the follower re-reads ``tiles`` each tick
    and the plan is kept while ``label`` stays the same.
    """

    tiles: frozenset[tuple[int, int]]
    need: Transport | None
    label: str
    moving: bool = False


@dataclass
class Leg:
    """One mode-homogeneous stretch of a trip and the action at its end.

    ``action``: "B" board, "X" leave ship, "GATE" moongate hop to
    ``gate_dest``, "CAPTURE" wait for a pirate to capture, "ARRIVE" done.
    """

    mode: Transport
    end: tuple[int, int]
    action: str
    gate_src: int | None = None
    gate_dest: int | None = None


@dataclass
class TripPlan:
    dest: Destination
    legs: list[Leg]
    cost: float
    map_id: int
    path: list[tuple[int, int, Transport]] = field(default_factory=list)


@dataclass(frozen=True)
class Transition:
    """The last B or X we emitted, for the reverse-transition penalty."""

    kind: str  # "B" or "X"
    pos: tuple[int, int]
    turn: int


class _Terrain:
    """Static per-map passability (cached by map id and the party's marks/keys)."""

    def __init__(self, gmap: GameMap, party: Party, has_key: bool) -> None:
        w, h = gmap.width, gmap.height
        self.width, self.height = w, h
        self.wraps = getattr(gmap, "border_behavior", "exit") == "wrap"
        has_fire = any(not m.is_dead() and m.marks[1] > 0 for m in party.members)
        has_force = tile_effects.all_members_mark_of_force(party)
        foot: set[tuple[int, int]] = set()
        sea: set[tuple[int, int]] = set()
        for y in range(h):
            for x in range(w):
                t = gmap.get_tile(x, y)
                if t is None:
                    continue
                name = str(getattr(t, "name", "")).lower()
                if can_move_to(gmap, x, y, SHIP, party=None):
                    sea.add((x, y))
                if has_key and name == "locked_door":
                    # Unlock opens it into the tile west of it on the surface
                    # (Ambrosia's water door admits ships only).
                    if locked_door_passable(gmap, x, y, FOOT, party):
                        foot.add((x, y))
                    if locked_door_passable(gmap, x, y, SHIP, None):
                        sea.add((x, y))
                    continue
                if not getattr(t, "walkable", False) and not getattr(t, "dispelable", False):
                    continue
                if name in ("lava", "fire") and not has_fire:
                    continue
                if name in ("energy_field", "force_field") and not has_force:
                    continue
                if can_move_to(gmap, x, y, FOOT, party=party):
                    foot.add((x, y))
        self.foot = frozenset(foot)
        self.sea = frozenset(sea)
        # Water tiles where X works: a walkable land neighbour.
        # Connected bodies of water (4-neighbour), for "which pirate can I
        # reach from this coast".
        comp: dict[tuple[int, int], int] = {}
        cid = -1
        for t0 in sorted(sea):
            if t0 in comp:
                continue
            cid += 1
            stack = [t0]
            comp[t0] = cid
            while stack:
                cx, cy = stack.pop()
                for dx, dy in _NEIGHBOURS:
                    n = self.wrap(cx + dx, cy + dy)
                    if n is not None and n in sea and n not in comp:
                        comp[n] = cid
                        stack.append(n)
        self.sea_comp = comp
        self.sea_comp_size: dict[int, int] = {}
        for c in comp.values():
            self.sea_comp_size[c] = self.sea_comp_size.get(c, 0) + 1
        self.landing = frozenset(
            (x, y)
            for (x, y) in sea
            if any(self.wrap(x + dx, y + dy) in foot for dx, dy in _NEIGHBOURS)
        )

    def wrap(self, x: int, y: int) -> tuple[int, int] | None:
        if self.wraps:
            return (x % self.width, y % self.height)
        if 0 <= x < self.width and 0 <= y < self.height:
            return (x, y)
        return None

    def neighbours(self, x: int, y: int) -> Iterable[tuple[int, int]]:
        for dx, dy in _NEIGHBOURS:
            n = self.wrap(x + dx, y + dy)
            if n is not None:
                yield n


_TERRAIN_CACHE: dict[tuple, _Terrain] = {}


def terrain_for(gmap: GameMap, party: Party, map_id: int) -> _Terrain:
    has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
    key = (
        map_id,
        id(gmap),
        getattr(gmap, "revision", 0),
        has_key,
        any(not m.is_dead() and m.marks[1] > 0 for m in party.members),
        tile_effects.all_members_mark_of_force(party),
        tile_effects.party_has_mark_of_force(party),
    )
    terr = _TERRAIN_CACHE.get(key)
    if terr is None:
        if len(_TERRAIN_CACHE) > 64:
            _TERRAIN_CACHE.clear()
        terr = _Terrain(gmap, party, has_key)
        _TERRAIN_CACHE[key] = terr
    return terr


def gate_hops(n_gates: int) -> dict[int, list[int]]:
    """Moongate site -> reachable destination sites (excluding itself)."""
    hops: dict[int, list[int]] = {}
    for s in range(n_gates):
        dests = []
        for p in range(24):
            if min(7, p // 3) == s:
                d = p % 8
                if d != s and d < n_gates and d not in dests:
                    dests.append(d)
        hops[s] = dests
    return hops


def plan_trip(
    gmap: GameMap,
    party: Party,
    map_id: int,
    start: tuple[int, int],
    mode: Transport,
    dest: Destination,
    frigates: dict[tuple[int, int], float],
    *,
    allow_capture: bool = True,
    banned_capture: frozenset[tuple[int, int]] = frozenset(),
    last_transition: Transition | None = None,
    turn: int = 0,
    gate_blocked: frozenset[tuple[int, int]] = frozenset(),
    danger: dict[tuple[int, int], float] | None = None,
    pirates: frozenset[tuple[int, int]] | None = None,
    pirates_spawn: bool = True,
) -> TripPlan | None:
    """Cheapest trip from ``(start, mode)`` to ``dest``, or None.

    ``frigates`` maps boardable frigate tiles to an extra boarding cost.
    ``danger`` adds a cost for entering a tile (pirate lanes, squid reach as
    seen when planning), so a blocked portal loses to a free one.
    """
    danger = danger or {}
    terr = terrain_for(gmap, party, map_id)
    # Pirates by body of water (None: legacy "any coast" captures).
    pirate_comp: dict[int, list[tuple[int, int]]] = {}
    for p in pirates or ():
        cid = terr.sea_comp.get(p)
        if cid is not None:
            pirate_comp.setdefault(cid, []).append(p)

    def capture_cost(n: tuple[int, int]) -> float | None:
        if pirates is None:
            return CAPTURE_COST
        ps = pirate_comp.get(terr.sea_comp.get(n, -1))
        if ps:
            w, h = terr.width, terr.height
            near = min(
                min(abs(n[0] - p[0]), w - abs(n[0] - p[0])) + min(abs(n[1] - p[1]), h - abs(n[1] - p[1]))
                for p in ps
            )
            return CAPTURE_COST + near
        if not pirates_spawn:
            return None
        size = terr.sea_comp_size.get(terr.sea_comp.get(n, -1), 0)
        if size < min(OPEN_WATER_MIN, max(terr.sea_comp_size.values(), default=0)):
            return None
        return CAPTURE_COST + PATROL_CAPTURE_EXTRA
    goal_tiles = dest.tiles
    if not goal_tiles:
        return None
    if mode == Transport.HORSE:
        mode = FOOT

    def arrived(pos: tuple[int, int], m: Transport) -> bool:
        return pos in goal_tiles and (dest.need is None or dest.need == m)

    if arrived(start, mode):
        return TripPlan(dest, [Leg(mode, start, "ARRIVE")], 0.0, map_id, [(start[0], start[1], mode)])

    gates = list(getattr(gmap, "moongates", ()) or ()) if map_id == 0 else []
    gate_sites = {(g.x, g.y): i for i, g in enumerate(gates)}
    hops = gate_hops(len(gates)) if gates else {}

    sail_cost = SAIL_STEP_COST

    def reverse_penalty(kind: str, pos: tuple[int, int]) -> float:
        lt = last_transition
        if lt is None or lt.pos != pos or turn - lt.turn > 50:
            return 0.0
        return REVERSE_TRANSITION_PENALTY if lt.kind != kind else 0.0

    State = tuple  # (x, y, mode)
    start_state: State = (start[0], start[1], mode)
    dist: dict[State, float] = {start_state: 0.0}
    # prev[state] = (prev_state, edge) where edge is "step", "B", "X", "CAPTURE", ("GATE", s, d)
    prev: dict[State, tuple[State, object]] = {}
    tie = 0
    pq: list[tuple[float, int, State]] = [(0.0, 0, start_state)]
    found: State | None = None

    def push(st: State, nst: State, ncost: float, edge: object) -> None:
        nonlocal tie
        if ncost < dist.get(nst, float("inf")):
            dist[nst] = ncost
            prev[nst] = (st, edge)
            tie += 1
            heapq.heappush(pq, (ncost, tie, nst))

    while pq:
        cost, _, st = heapq.heappop(pq)
        if cost > dist.get(st, float("inf")):
            continue
        x, y, m = st
        if arrived((x, y), m):
            found = st
            break

        on_water = (x, y) in terr.sea
        # A frigate's water tile is entered on foot only to board it: if we
        # walked onto it, the only way on is B (no stepping-stone shortcut).
        # After X, or at the trip's start, the party walks ashore as usual.
        stranded = m == FOOT and on_water and st in prev and prev[st][1] == "step"
        for n in ([] if stranded else terr.neighbours(x, y)):
            if m == FOOT:
                # Destination tiles (portals) are enterable even if not walkable;
                # a frigate's water tile is enterable from land (to board it).
                if (
                    (n in goal_tiles and dest.need in (None, FOOT))
                    or (n in terr.foot and n not in gate_blocked)
                    or (n in frigates and not on_water)
                ):
                    push(st, (n[0], n[1], FOOT), cost + WALK_STEP_COST + danger.get(n, 0.0), "step")
            # A ship never sails onto a parked frigate (the move is refused;
            # live trace 2026-11-25, trace_20261125-180541: a landing tile
            # held by the party's own earlier ship, ~3,200 turns refused).
            elif (n in terr.sea and n not in frigates) or (n in goal_tiles and dest.need in (None, SHIP)):
                push(st, (n[0], n[1], SHIP), cost + sail_cost + danger.get(n, 0.0), "step")

        if m == FOOT:
            if (x, y) in frigates:
                push(
                    st,
                    (x, y, SHIP),
                    cost + BOARD_COST + frigates[(x, y)] + reverse_penalty("B", (x, y)),
                    "B",
                )
            if allow_capture and not on_water and (x, y) not in banned_capture:
                for n in terr.neighbours(x, y):
                    if n in terr.sea and n not in frigates:
                        cc = capture_cost(n)
                        if cc is not None:
                            push(st, (n[0], n[1], SHIP), cost + cc, ("CAPTURE", (x, y)))
            if (x, y) in gate_sites:
                s = gate_sites[(x, y)]
                for d in hops.get(s, ()):
                    g = gates[d]
                    push(st, (g.x, g.y, FOOT), cost + GATE_COST, ("GATE", s, d))
        else:
            if (x, y) in terr.landing:
                push(st, (x, y, FOOT), cost + EXIT_COST + reverse_penalty("X", (x, y)), "X")

    if found is None:
        return None

    # Rebuild the state path, then cut it into legs.
    states: list[State] = [found]
    edges: list[object] = []
    cur = found
    while cur != start_state:
        p, e = prev[cur]
        states.append(p)
        edges.append(e)
        cur = p
    states.reverse()
    edges.reverse()

    legs: list[Leg] = []
    seg_mode = mode
    for i, e in enumerate(edges):
        here = states[i]
        if e == "step":
            continue
        if e == "B":
            legs.append(Leg(FOOT, (here[0], here[1]), "B"))
        elif e == "X":
            legs.append(Leg(SHIP, (here[0], here[1]), "X"))
        elif isinstance(e, tuple) and e[0] == "CAPTURE":
            legs.append(Leg(FOOT, e[1], "CAPTURE"))
        elif isinstance(e, tuple) and e[0] == "GATE":
            legs.append(Leg(FOOT, (here[0], here[1]), "GATE", gate_src=e[1], gate_dest=e[2]))
        seg_mode = states[i + 1][2]
    legs.append(Leg(seg_mode, (found[0], found[1]), "ARRIVE"))
    return TripPlan(
        dest=dest,
        legs=legs,
        cost=dist[found],
        map_id=map_id,
        path=[(s[0], s[1], s[2]) for s in states],
    )
