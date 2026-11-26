"""Live input-driver AutoPlayController for Full Autoplay ("Watch Mode")."""
from __future__ import annotations

import logging
import sys

import random
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from py_exodus.autoplay.equipment import (
    excess_gear,
    SPARE_BOW,
    SPARE_BOW_PRICE,
    spare_bow_purchase,
    food_hand_off,
    hand_offer,
    best_owned_armor,
    best_owned_weapon,
    best_shop_upgrade,
)
from py_exodus.entities.party import headwind, objects_on
from py_exodus.autoplay.nav import (
    find_2d_step,
    find_2d_step_and_cost,
    dungeon_tiles_within,
    find_dungeon_step,
    locked_door_passable,
    reachable_2d,
)
from py_exodus.autoplay.planner import (
    AMBROSIA_ENTRY_FOOD,
    ambrosia_trip_due,
    DEATH_GULCH_BRIBE_GOLD,
    DEATH_GULCH_KEYS,
    Goal,
    evaluate_goal,
    SHRINE_RESERVE,
    alcort_wisdom_gap,
    gold_has_a_use,
    optional_purchase_ok,
    next_shrine_goal,
    needs_heal,
    TOWN_REST_BELOW_PCT,
    prefer_ranged_weapons,
    raid_gold_target,
    DESCEND_MP,
    descend_mp_short,
    dungeon_hp_need,
    dungeon_may_resume,
    dungeon_turn_back,
    mark_reachable,
    next_mark_dungeon,
    rod_plan,
    rod_safe,
    ROD_BURN,
    DEATH_GULCH_GOLD_CAP,
    return_trip_gold,
)
from py_exodus.autoplay.threats import (
    SEA_MONSTERS,
    compute_threats,
    creature_name,
    foot_escape,
    lane_tiles_for,
    manhattan,
    ship_escape,
    wrap_delta,
)
from py_exodus.autoplay.trip import (
    Destination,
    Leg,
    Transition,
    TripPlan,
    plan_trip,
    terrain_for,
)
from py_exodus.constants import (
    ArmorType,
    Direction,
    Profession,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.ui.renderer import can_move_to
from py_exodus.world import tile_effects
from py_exodus.world.map import DungeonTile

if TYPE_CHECKING:
    from py_exodus.state_machine import StateMachine

_DIR_TO_KEY: dict[Direction, int] = {
    Direction.NORTH: pygame.K_UP,
    Direction.SOUTH: pygame.K_DOWN,
    Direction.WEST: pygame.K_LEFT,
    Direction.EAST: pygame.K_RIGHT,
}
_KEY_TO_DIR: dict[int, Direction] = {v: k for k, v in _DIR_TO_KEY.items()}

# Returned by the trip follower when the party stands at its destination.
_ARRIVED = object()
_REST_INDOORS = object()
_log = logging.getLogger(__name__)

# Where to look when Sosaria shows no whirlpool (it should never happen,
# see the SAIL_WHIRLPOOL destination): LairWare's start (MAPS 420, 47,17),
# then Java's two fixed spots.
_WHIRLPOOL_GUESSES = ((47, 17), (50, 13), (17, 48))

_TRIP_REPLAN_TURNS = 300
_TRIP_STUCK_TURNS = 30
_NEIGHBOURS4 = ((0, -1), (0, 1), (-1, 0), (1, 0))
_GATE_WAIT_TURNS = 6  # be at the gate this many turns before it opens
_GATE_ROAM_RADIUS = 5
# Turns within _GATE_ROAM_RADIUS of a gate before its leg gives up: two
# full moon cycles (96 turns each). One always brings the hop round.
_GATE_LEG_MAX_TURNS = 2 * 96
_CHASE_RADIUS = 8  # land monsters this close count as chasing
_SHIP_CHEST_CLEAR = 6  # no sea monster this close to go ashore for a chest
# Turns on one tile, whatever the replans, before the trip bars the next
# tile of its path: two replan periods (_TRIP_STUCK_TURNS), past any headwind
# wait or creature in the way that the first replan already covers.
_TRIP_STILL_TURNS = 60
_BLOCK_TURNS = 40  # a refused threatened tile stays barred this long
# The whirlpool and a parked ship (batch 67c0de5 b5 seed 44). LairWare
# WhirlPool (UltimaMain.c:2959-3013) moves it one tile, in any of eight
# directions, every 4th key-wait poll: about one move per 4 autoplay turns
# at the command line (none in prompts or combat). Seven times in eight it
# keeps its heading; land ahead, or the 1-in-8 roll, gives it a new one. An
# empty frigate on its next tile (0x2C) is sunk; the party's own ship is
# engulfed instead (Ambrosia, and back aboard a frigate). So a parked ship
# is at risk only from a whirlpool next to it (Chebyshev 1), and one two
# tiles off needs two moves (~8 turns) on a heading straight at it.
#
# Landing: X waits aboard while the whirlpool is within _WHIRL_LANDING_CLEAR
# of the landing tile: a walk ashore and back alone gives it those two moves.
# Farther off, the party goes and the reboard guard watches the ship. The
# wait stands off a tile when the whirlpool comes next to the ship, and is
# bounded: _WHIRL_HOLD_TURNS (8 moves), then the party lands anyway, and no
# new wait starts for _WHIRL_HOLD_COOLDOWN turns.
_WHIRL_LANDING_CLEAR = 2
_WHIRL_HOLD_TURNS = 32
_WHIRL_HOLD_COOLDOWN = 200
# Ashore: when the whirlpool comes next to the ship the party left, and the
# ship is at most _WHIRL_REBOARD_STEPS away (under one move), the errand is
# cut short and the party boards again; at most once per
# _WHIRL_REBOARD_COOLDOWN turns, so land-reboard can't loop.
_WHIRL_REBOARD_STEPS = 3
_WHIRL_REBOARD_COOLDOWN = 200

# A dragon on Sosaria follows the party on foot (batch 67c0de5 b6 seed 57):
# LairWare MoveMonsters steps it toward the party every turn the party
# moves, so dodging its breath in a straight line keeps it three tiles
# behind, breathing, until the party is ruined. moveshoot fires only from
# the 11x11 view, _SHOOT_VIEW tiles each way (UltimaMisc.c:1245-1278).
_SHOOT_VIEW = 5
# Refuge: a town or castle gate at most _REFUGE_STEPS steps away, reached
# before any monster can engage (LairWare's greedy monster step simulated
# along the walk). 6 is about the breath a party can afford on the walk:
# a turn in line costs each member up to (rand & 0x77) + 8, half the time,
# and a level-6 Cleric (557 of 650 HP in the trace) takes four worst-case
# hits. Farther than that the walk costs what it saves, the simulation of
# monster steps and spawns grows unreliable, and the path search (4^N)
# gets dear.
_REFUGE_STEPS = 6
# After a refuge, no new one for this many turns: the dragon waits outside
# (the overworld is still while the party is indoors), so the way out is
# the fight, not a step back in. One town visit, rest included, is about
# 20-200 turns; any later refuge is a fresh threat.
_REFUGE_COOLDOWN = 200
# The escape has failed after this many turns with a dragon still in view
# and the party's HP lower than when it began. An escape that works leaves
# a dragon's 3-tile breath in 1-3 steps; one still in range after 4 is
# following, and at a 50% breath rate four turns without a hit is 1 in 16,
# so "HP lower" is a reliable second test.
_ESCAPE_CAP_TURNS = 4
# Map ids never taken as a refuge: Exodus and Death Gulch are hostile (user
# ruling: no town fights), Dawn is rarely there.
_NO_REFUGE_MAPS = (2, 10, 11)


def _cheb(w: int, h: int, a: tuple[int, int], b: tuple[int, int]) -> int:
    """Wrap-aware Chebyshev distance: the whirlpool's moves from a to b."""
    dx, dy = abs(a[0] - b[0]) % w, abs(a[1] - b[1]) % h
    return max(min(dx, w - dx), min(dy, h - dy))


# Planning cost for entering a tile under threat when the trip is planned.
_DANGER_HARD = 60.0
_DANGER_SQUID_COAST = 5.0

_BRITAIN_PORTAL = (46, 19)
_CASTLE_BRITISH = (45, 18)
_DAWN_PORTAL = (37, 53)
_AMBROSIA_EXIT = (32, 58)
_EXOTIC_ARMOR_SITE = (19, 44)
_EXOTIC_WEAPON_SITE = (33, 3)

# Ship broadside targets (pirates excluded: the lane rule escapes or closes in).
_CANNON_TARGETS = frozenset({
    "serpent", "squid",
    "dragon", "devil", "balron", "gargoyle", "daemon",
    "griffin", "wyvern", "minotaur", "hydra", "lich",
    "giant", "troll", "pincher", "snatch", "mage", "wizard",
})


def party_has_low_hp(party) -> bool:
    """Any living member under 40% HP: too weak to pick a fight."""
    return any(not m.is_dead() and m.max_hp > 0 and m.hp * 10 < m.max_hp * 4 for m in party.members)

_MAP_SOSARIA = 0
_DEATH_GULCH_GOLD_CAP = DEATH_GULCH_GOLD_CAP  # same cap as the raid inside
_DRAGON_CHASE_LEVEL = 8  # the grind leaves dragons alone below this
# A party this strong walks up to pirates and fights them from land.
_PIRATE_HUNT_MIN_LEVEL = 8
_PIRATE_HUNT_RANGE = 10
# A capture hunt whose nearest pirate has not come closer for this many
# capture turns in a row is stalled (live trace 2026-11-25: a shadowing
# pirate kept the hunt pacing two tiles for ~9,000 steps). A normal approach
# closes in almost every turn; a lane-free detour around one pirate column
# costs a sidestep or two, and a pirate may drift back a turn, so 5 lets
# those through while a pace is caught within a few steps.
_CAPTURE_STALL_TURNS = 5
# One LairWare moveshoot hit costs each living member (rand & 0x77) + 8 HP
# at most (threats.py). The dash walks a lane only if all can take two.
_BROADSIDE_MAX = 0x77 + 8
# A frigate this many foot steps away is walked to through the lanes
# (_board_dash): Fawn's strip is three tiles from its gate's frigate.
_BOARD_DASH_STEPS = 3
# _board_dash on the frigate: leave the turn to the trip, which boards.
_YIELD_TO_TRIP = -1
# A stalled capture the party is too weak to dash leaves the pirate alone
# this many capture turns (patrols the coast instead of pacing).
_CAPTURE_SHUN_TURNS = 30
_MAP_CASTLE_LB = 1
_MAP_EXODUS = 2
_MAP_DEATH_GULCH = 10
_MAP_AMBROSIA = 13
_PIRATE_SEA_MAPS: tuple[int, ...] = (_MAP_SOSARIA, _MAP_AMBROSIA)
_UNSAFE_REST_TOWN_MAPS: tuple[int, ...] = (_MAP_EXODUS, _MAP_DEATH_GULCH)
# ~2x a typical mainland town food run; leaves HP margin before starvation ticks kill a 0-food party.
_STARVING_AVOID_MAX_STEPS = 40
# A ship's headwind hold (_move_toward). It holds only when no step the wind
# allows gets nearer by the wind-free route, and for at most
# min(_WIND_HOLD_MAX, detour's extra turns) turns in a row: waiting no
# longer than the detour would add never costs more than twice the better
# choice in hindsight. 20 turns is about a wind period at autoplay's default
# pace (DoWind re-rolls every 33 polls, 2.75 s of play, ~34 steps at 0.08 s;
# the new wind is the headwind again only 1 time in 7). Then it sails the
# wind-legal route, unless that adds more than _WIND_DETOUR_MAX turns (a
# trip round a continent or the world): the wind changes on the clock, so
# waiting it out is cheaper there.
_WIND_HOLD_MAX = 20
# Goals this close to a committed hold's goals are the same destination (a
# drifting whirlpool), so the commitment to the wind-legal route stands.
_WIND_GOAL_DRIFT = 4
_WIND_DETOUR_MAX = 60
_TOWN_DASH_STEPS = 4  # this close to a town gate, firing lanes don't block the walk in

# EXODUS card panels: (x, y, bit_mask, card_letter, card_index)
_EXODUS_PANELS: tuple[tuple[int, int, int, str, int], ...] = (
    (30, 12, 0x1, "l", 3),  # Love
    (31, 12, 0x2, "s", 1),  # Sol
    (32, 12, 0x4, "m", 2),  # Moons
    (33, 12, 0x8, "d", 0),  # Death
)

# Ambrosia card sites: (x, y, card_index)
_AMBROSIA_CARD_SITES: tuple[tuple[int, int, int], ...] = (
    (55, 27, 0),  # Death
    (45, 52, 1),  # Sol
    (6, 6, 2),    # Moons
    (4, 36, 3),   # Love
)

# Towns with Weapon & Armor vendors reachable on foot: map_id -> (portal_x, portal_y, wep_stand_xy, arm_stand_xy)
_SHOP_TOWNS: dict[int, tuple[int, int, tuple[int, int], tuple[int, int]]] = {
    3: (46, 19, (39, 19), (50, 20)),   # Britain
    6: (7, 44, (29, 43), (35, 44)),    # Grey
    8: (49, 58, (26, 11), (35, 12)),   # Montor East
    9: (47, 58, (50, 35), (51, 28)),   # Montor West
    11: (37, 53, (27, 19), (19, 20)),  # Dawn
}

# Sell talks per town visit at most: a refused sale can't loop the party.
_SELL_TALKS_PER_VISIT = 12
# Spare-Bow talks per town visit at most (item B), for the same reason.
_BOW_TALKS_PER_VISIT = 4

# Towns with Guild shops reachable on foot: map_id -> (portal_x, portal_y, guild_stand_xy)
# Every guild sells a torches, b gems, c keys, d powder; the stand is two
# tiles in front of the keeper, across the sign row. User rule (2026-11-21):
# buy at Devil Guard / Fawn; Dawn only when it happens to be open. Grey's
# guild is off the list (user ruling): its only corridor, past the Tap
# House, is regularly plugged by a thief who never moves out of it.
_GUILD_TOWNS: dict[int, tuple[int, int, tuple[int, int]]] = {
    6: (7, 44, (33, 21)),    # Grey, The Guild (back 2026-11-22: its thief now
                             # moves and attacks, so it no longer plugs the corridor)
    7: (18, 31, (48, 53)),   # Devil Guard, The Thieves Guild
    12: (30, 2, (32, 13)),   # Fawn, Tools of Trade
    11: (37, 53, (34, 21)),  # Dawn (only while open)
}

# Towns with Food shops reachable on foot: map_id -> (portal_x, portal_y, food_stand_xy)
# Rations are 1 gold each everywhere (LairWare Shop case 1).
# Castle British has none: its cook has no counter (LairWare Transact).
_FOOD_TOWNS: dict[int, tuple[int, int, tuple[int, int]]] = {
    3: (46, 19, (48, 49)),   # Britain
    4: (34, 16, (31, 17)),   # Yew
    6: (7, 44, (26, 25)),    # Grey
    11: (37, 53, (29, 41)),  # Dawn (only selected when Dawn is open)
    # Fawn's Food For Thought (vendor.xml; Mintol at (25, 51) behind the
    # counter, Shop case 1 from row 49): the food run left it out, and a
    # party on Fawn's strip, two steps from the gate, sailed past a pirate
    # for Yew (batch 89c1bf4 b9 seed 90 starved there with 4,665 gold).
    12: (30, 2, (25, 49)),   # Fawn
    10: (56, 31, (52, 33)),  # Death Gulch (only from its own strip, below)
}
# Death Gulch's gate and its grocer: a party on the town's strip (55-58,
# 31-40, walled by water and mountains; gate 7's site (58, 31) is in a
# mountain pocket) has no way off but a ship. Waiting for a pirate there it
# buys its food in Death Gulch (seed 8 at bdbd73a starved on the strip with
# 4,976 gold). From anywhere else Death Gulch is never a food run.
_DEATH_GULCH_PORTAL = (56, 31)
# Death Gulch's way to its grocer: two locked doors, (12, 32) and (33, 32),
# a key each, and two guards to bribe, 100 gold each (_death_gulch_way).
_DG_FOOD_KEYS = 2
_DG_FOOD_BRIBES = 200

# Towns with Healers reachable on foot: map_id -> (portal_x, portal_y, healer_stand_xy)
_HEALER_TOWNS: dict[int, tuple[int, int, tuple[int, int]]] = {
    1: (45, 18, (46, 26)),   # Castle British
    4: (34, 16, (48, 10)),   # Yew
    5: (6, 13, (50, 50)),    # Moon
    11: (37, 53, (21, 42)),  # Dawn
}

# Broad Sosaria mainland patrol route for grinding & exploration
_SOSARIA_PATROL: tuple[tuple[int, int], ...] = (
    (44, 22),
    (34, 18),
    (24, 24),
    (14, 34),
    (12, 42),
    (28, 46),
    (38, 48),
    (50, 48),
    (52, 32),
    (48, 22),
)


def _key_to_unicode(key: int) -> str:
    """Return the pygame unicode string corresponding to a key constant."""
    if pygame.K_a <= key <= pygame.K_z:
        return chr(ord("a") + (key - pygame.K_a))
    if pygame.K_0 <= key <= pygame.K_9:
        return chr(ord("0") + (key - pygame.K_0))
    if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        return "\r"
    if key == pygame.K_SPACE:
        return " "
    return ""


def _able(party) -> list[tuple[int, Any]]:
    """``(1-based index, member)`` for members who can Transact or bribe:
    neither dead nor ashes (LairWare Transact, UltimaMain.c:2302-2305, and
    Other's CheckAlive; "Incapacitated!"). Seed 3 at bdbd73a picked its
    food buyer by least food among the not-dead, the Fighter in ashes, and
    Talked through it at Britain's grocer ~44,000 times until all starved."""
    return [(i + 1, m) for i, m in enumerate(party.members) if not m.is_disabled()]


def _char_to_key(ch: str) -> int | None:
    """Map a single ASCII character to its pygame.K_* constant."""
    c = ch.lower()
    if "a" <= c <= "z":
        return pygame.K_a + (ord(c) - ord("a"))
    if "0" <= c <= "9":
        return pygame.K_0 + (ord(c) - ord("0"))
    if c == " ":
        return pygame.K_SPACE
    if c in ("\r", "\n"):
        return pygame.K_RETURN
    return None


class AutoPlayController:
    """Drives the live StateMachine via real pygame.KEYDOWN events."""

    MIN_INTERVAL = 0.01
    MAX_INTERVAL = 0.50

    def __init__(self, enabled: bool = False, step_interval: float = 0.08, tracer=None) -> None:
        self.enabled = enabled
        self.tracer = tracer
        self.step_interval = max(self.MIN_INTERVAL, min(self.MAX_INTERVAL, step_interval))
        self._timer: float = 0.0
        self._key_queue: deque[int] = deque()
        self._patrol_idx: int = 0
        self._shop_member_idx: int = 1
        self._shop_item_letter: str = "b"
        self._ready_member_idx: int = 1
        self._ready_item_letter: str = "b"
        self._wear_member_idx: int = 1
        self._wear_item_letter: str = "b"
        self._join_gold_member_idx: int = 1
        self._town_danger_tiles: set[tuple[int, int]] = set()
        self._hand_from_idx: int = 1
        self._hand_to_idx: int = 2
        self._hand_item: tuple[str, str] = ("w", "b")
        self._food_packs: int = 1
        self._heal_patient_idx: int = 1
        self._talk_dir_key: int = pygame.K_UP
        # Overworld threat geometry for this tick (None off the overworld).
        self._threats = None
        self._overworld_avoid: set[tuple[int, int]] = set()
        # Trip follower state (the single owner of B/X).
        self._trip: TripPlan | None = None
        self._trip_frigates: frozenset[tuple[int, int]] = frozenset()
        self._trip_planned_at = 0
        self._whirl_guess = 0
        # Headwind hold (_move_toward): turns held in a row, and the wind held for.
        self._wind_hold_n = 0
        self._wind_hold_wind = None
        # (wind, goals) a hold was given up for: the wind-legal route rules.
        self._wind_commit = None
        self._whirl_missing = False
        # Landing hold near the whirlpool: turn it began, and the turn
        # before which no new hold starts.
        self._whirl_hold_from: int | None = None
        self._whirl_hold_until = 0
        self._whirl_reboard_until = 0
        self._trip_stuck = 0
        self._trip_still = 0  # turns on one tile; only a move resets it
        self._cure_latch = None  # the dungeon state whose poison went dire
        self._cure_mode = False
        self._trip_last_pos: tuple[int, int] | None = None
        self._patrol_target: tuple[int, int] | None = None
        # [(gate src, dst), turns near it]: the bound on a moongate leg.
        self._gate_wait: list | None = None
        # Land tile the pirate hunt committed to (see _hunt_target).
        self._hunt_target: tuple[int, int] | None = None
        self._reach_cache = None
        # Coast tiles where a capture wait timed out, per map id.
        self._last_transition: Transition | None = None
        self._ow_turn = 0
        self._blocked_tiles: dict[tuple[int, int], int] = {}
        self._fleeing = False
        # Dragon breath on foot: [first turn, HP then, last turn] of the
        # escape, and the turn before which no new refuge starts.
        self._escape_log: list[int] | None = None
        self._refuge_until = 0
        # A member lacking a wanted mark is not safe for its rod (dungeon).
        self._rod_heal_wanted = False
        # Turning back in a dungeon (item 5), latched per dungeon visit.
        self._retreating = False
        self._retreat_state = None
        self._ladder_wait_at = None
        self._ladder_waited = 0
        self._gave_up_state = None

    def toggle(self) -> bool:
        """Flip autoplay enabled state and clear any queued keystrokes."""
        self.enabled = not self.enabled
        self._key_queue.clear()
        self._timer = 0.0
        return self.enabled

    def adjust_speed(self, faster: bool) -> float:
        """Adjust step interval faster or slower, clamped to [0.01, 0.50]."""
        if faster:
            self.step_interval = max(self.MIN_INTERVAL, round(self.step_interval * 0.7, 3))
        else:
            self.step_interval = min(self.MAX_INTERVAL, round(self.step_interval / 0.7, 3))
        return self.step_interval

    def update(self, dt: float, state_machine: StateMachine) -> bool:
        """Advance step timer and emit steps when enabled."""
        state_machine.autoplay_enabled = self.enabled
        state_machine.autoplay_step_interval = self.step_interval
        if not self.enabled:
            return False
        self._timer += dt
        stepped = False
        steps_this_frame = 0
        while self._timer >= self.step_interval and steps_this_frame < 4:
            self._timer -= self.step_interval
            self.step(state_machine)
            stepped = True
            steps_this_frame += 1
        if self._timer >= self.step_interval:
            # Cap backlog so slow frames never starve pygame.event.get() (F9 toggle).
            self._timer = 0.0
        return stepped

    _WHY_SKIP = frozenset({"_emit_key", "_step_or_unlock", "_move_toward", "_attack"})

    def _emit_key(self, state_machine: StateMachine, key: int | str, guarded: bool = True) -> int:
        typed = None
        if isinstance(key, str):  # a shifted letter from _queue_text(keep_case=True)
            typed, key = key, _char_to_key(key)
        # Trace "why": the autoplay functions that chose this key (nearest
        # first), so a loop in a trace names its branch.
        f = sys._getframe(1)
        why: list[str] = []
        while f is not None and len(why) < 3:
            name = f.f_code.co_name
            if name in ("step", "_step"):
                break
            if name not in self._WHY_SKIP and f.f_code.co_filename == __file__:
                why.append(f"{name}:{f.f_lineno}")
            f = f.f_back
        self._last_why = "<".join(why) or None
        if guarded:
            key = self._lane_guard(state_machine, key)
        event = pygame.event.Event(
            pygame.KEYDOWN,
            key=key,
            mod=pygame.KMOD_SHIFT if typed else 0,
            unicode=typed or _key_to_unicode(key),
        )
        state_machine.handle_event(event)
        return key

    def _queue_text(self, text: str, enter: bool = True, keep_case: bool = False) -> None:
        """Queue ``text`` as key presses. With ``keep_case`` an uppercase
        letter is queued as the character itself and sent shifted, so a
        typed name keeps its capitals."""
        for ch in text:
            k = _char_to_key(ch)
            if k is not None:
                self._key_queue.append(ch if keep_case and ch.isupper() else k)
        if enter:
            self._key_queue.append(pygame.K_RETURN)

    def step(self, state_machine: StateMachine) -> int | None:
        """Emit one logical input step for the active screen (traced when a tracer is set)."""
        self._last_why = None
        key = self._step(state_machine)
        if self.tracer is not None:
            self.tracer.record_step(state_machine, key, why=self._last_why)
        return key

    def _step(self, state_machine: StateMachine) -> int | None:
        state_machine.autoplay_enabled = self.enabled
        state_machine.autoplay_step_interval = self.step_interval
        screen = state_machine.current_screen
        self._threats = None
        self._overworld_avoid = set()
        if screen is None:
            return None

        screen_name = type(screen).__name__
        if screen_name == "FinalScreen":
            self._key_queue.clear()
            return None

        screen_party = getattr(screen, "party", None)
        # The game is won: no goal is left, so autoplay switches itself off
        # (the way the toggle does) and never answers the player's prompts.
        if screen_party is not None and (
            getattr(screen_party, "exodus_defeated", 0) > 0 or getattr(screen_party, "exodus_cards_status", 0) == 0xF
        ):
            self._key_queue.clear()
            self.enabled = False
            state_machine.autoplay_enabled = False
            return None
        if (
            screen_name not in ("StartScreen", "RosterScreen")
            and screen_party is not None
            and bool(screen_party.members)
            and screen_party.is_party_dead()
        ):
            self._key_queue.clear()
            self.enabled = False
            state_machine.autoplay_enabled = False
            return None

        if self._key_queue:
            return self._emit_key(state_machine, self._key_queue.popleft())

        if screen_name == "StartScreen":
            if getattr(screen, "game_over", False):
                self._key_queue.clear()
                self.enabled = False
                state_machine.autoplay_enabled = False
                return None
            return self._step_start(state_machine)
        if screen_name == "RosterScreen":
            return self._step_roster(state_machine, screen)
        if screen_name == "CombatScreen":
            return self._step_combat(state_machine, screen)
        if screen_name == "DungeonScreen":
            return self._step_dungeon(state_machine, screen)
        if screen_name in ("OverworldScreen", "TownScreen"):
            return self._step_2d(state_machine, screen)

        return None

    def _step_start(self, state_machine: StateMachine) -> int:
        save_path = Path("saves/party.json")
        if save_path.exists():
            return self._emit_key(state_machine, pygame.K_j)
        return self._emit_key(state_machine, pygame.K_2)

    def _step_roster(self, state_machine: StateMachine, screen) -> int | None:
        if screen.text_log.is_waiting_for_input:
            prompt = (getattr(screen.text_log, "current_prompt", "") or "").lower()
            # An empty roster gets the one tested party, the same four that
            # scripts/reset_new_game.py writes (user 2026-11-22).
            from py_exodus.autoplay.batch import PARTY_SETUP

            name, sex, race, prof, st, dx, it, ws = PARTY_SETUP[len(screen.roster) % len(PARTY_SETUP)]
            if "name" in prompt:
                self._queue_text(name, enter=True, keep_case=True)
            elif "strength" in prompt:
                self._queue_text(str(st), enter=True)
            elif "dexterity" in prompt:
                self._queue_text(str(dx), enter=True)
            elif "intelligence" in prompt:
                self._queue_text(str(it), enter=True)
            elif "wisdom" in prompt:
                self._queue_text(str(ws), enter=True)
            elif "sex" in prompt:
                self._queue_text(sex, enter=False)
            elif "race" in prompt:
                self._queue_text(race[0], enter=False)  # Elf, Dwarf, Bobbit, Fuzzy
            elif "profession" in prompt or "class" in prompt:
                self._queue_text(prof[0], enter=False)  # Thief, Fighter, Cleric, Wizard
            else:
                return self._emit_key(state_machine, pygame.K_RETURN)
            if self._key_queue:
                return self._emit_key(state_machine, self._key_queue.popleft())
            return None

        if len(screen.party.members) < 4:
            if len(screen.roster) > len(screen.party.members):
                char = screen.roster[screen.selected_roster_idx]
                in_party = any(m.character is char for m in screen.party.members)
                if in_party:
                    return self._emit_key(state_machine, pygame.K_DOWN)
                return self._emit_key(state_machine, pygame.K_a)
            return self._emit_key(state_machine, pygame.K_c)

        return self._emit_key(state_machine, pygame.K_e)

    def _step_combat(self, state_machine: StateMachine, screen) -> int | None:
        self._grind_dead = 0  # a fight: the grind's spot is not dead
        if hasattr(screen, "auto_combat_interval"):
            screen.auto_combat_interval = self.step_interval
            if getattr(screen, "_auto_combat_timer", 0.0) > self.step_interval:
                screen._auto_combat_timer = self.step_interval
        if screen.arena.is_finished:
            self._key_queue.clear()
            return self._emit_key(state_machine, pygame.K_RETURN)
        if not screen.auto_combat:
            return self._emit_key(state_machine, pygame.K_TAB)
        return None

    def _step_shrine(self, state_machine: StateMachine, screen) -> int | None:
        """Answer the LairWare shrine prompts: offer toward the current
        planner.SHRINE_PLAN step only; offer 0 (or pick nobody) when that
        step belongs to another shrine or is out of gold."""
        from py_exodus.world import shrine

        party = screen.party
        goal = next_shrine_goal(party)
        on_plan = goal is not None and goal[1] == shrine.shrine_stat(party.x)
        member = party.members[goal[0]] if on_plan else None
        spendable = max(0, party.gold - SHRINE_RESERVE) // 100
        if screen.text_log.current_prompt == shrine.PROMPT_WHO:
            if member is not None and member.gold >= 100 and spendable >= 1:
                return self._emit_key(state_machine, pygame.K_1 + goal[0])
            return self._emit_key(state_machine, pygame.K_0)
        chosen = party.get_member(screen.shrine_member or 0)
        if member is None or chosen is not member:
            return self._emit_key(state_machine, pygame.K_0)
        amt = min(9, member.gold // 100, spendable, goal[3] - getattr(member, goal[1], 0))
        return self._emit_key(state_machine, pygame.K_0 + max(0, amt))


    @staticmethod
    def _screen_map_id(screen, party) -> int:
        raw_id = getattr(getattr(screen, "game_map", None), "id", None)
        if raw_id is None:
            raw_id = getattr(screen, "map_id", getattr(party, "map_id", 0))
        if isinstance(raw_id, str) and raw_id.lower() == "ambrosia":
            return 13
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            return getattr(party, "map_id", 0)

    def _step_dungeon(self, state_machine: StateMachine, screen) -> int | None:
        party = screen.party
        # The mark a living member still needs here (the red-hot rod).
        mark_map = {
            DungeonTile.MARK_KINGS: 0,
            DungeonTile.MARK_FIRE: 1,
            DungeonTile.MARK_SNAKE: 2,
            DungeonTile.MARK_FORCE: 3,
        }
        cur_tile = getattr(screen.state, "current_tile", None)
        # On a mark: touch it with a member who is safe to burn, heal one
        # first, or (neither) step off. ``rod`` is None off a mark or when
        # nobody living needs this one.
        rod = self._rod_plan(party, mark_map[cur_tile]) if cur_tile in mark_map else None
        need_idx = rod[1] if rod is not None and rod[0] == "touch" else None

        if screen.text_log.is_waiting_for_input:
            # LairWare dungeonmech (UltimaDngn.c:300-318, ledger D-12): every
            # command on a mark asks who touches the rod; one member per ask.
            prompt = (getattr(screen.text_log, "current_prompt", "") or "").lower()
            if "touch" in prompt and need_idx is not None:
                return self._emit_key(state_machine, pygame.K_0 + need_idx)
            # A fountain asks who drinks after every command on it, and again
            # after each drink (UltimaDngn.c:228-279): a heal or cure
            # fountain gets the members who need it, one per ask; acid,
            # poison and plain ones never (autoplay round 1, item 1).
            if "drink" in prompt:
                drinker = self._fountain_drinker(party, cur_tile)
                if drinker is not None:
                    return self._emit_key(state_machine, pygame.K_0 + drinker)
            # Anything else, a fountain nobody needs included, is left with Esc.
            return self._emit_key(state_machine, pygame.K_ESCAPE)

        dmap = getattr(screen, "dungeon_map", None) or getattr(screen, "dmap", None) or screen.state.dmap
        goal = evaluate_goal(party, map_id=self._screen_map_id(screen, party))

        # A member out of food is fed from the others before anything else
        # (seed 3: the Fighter at 0 while two others had 100 in the Fires
        # of Hell; it starved to death and kept dying after each raising).
        feed_key = self._maybe_feed(state_machine, party)
        if feed_key is not None:
            return feed_key

        # A fight in here can end with a member's spare Bow readied (brief
        # item B, user ruling 2026-11-25): ready the Exotic again first. On
        # the surface and in towns ``_maybe_manage_gear`` does it.
        bow_idx = next(
            (
                i + 1
                for i, m in enumerate(party.members)
                if not m.is_dead() and best_owned_weapon(m) == WeaponType.EXOTIC
                and m.weapon == SPARE_BOW
            ),
            None,
        )
        if bow_idx is not None:
            letter = chr(ord("a") + list(WeaponType).index(WeaponType.EXOTIC))
            self._queue_text(f"{bow_idx}{letter}", enter=False)
            return self._emit_key(state_machine, pygame.K_r)

        # On a mark that a living member still needs: pass a turn, and the
        # rod asks again (S is not a dungeon command, UltimaDngn.c:152).
        if need_idx is not None:
            return self._emit_key(state_machine, pygame.K_SPACE)
        # A member who needs the mark but would be left under half health:
        # heal on the spot first (the rod asks again after the cast).
        if rod is not None and rod[0] == "heal":
            self._queue_text(rod[1], enter=False)
            return self._emit_key(state_machine, pygame.K_c)

        # The marks wanted here: the goal's, while a living member lacks one
        # and can be made safe for its rod (now, by a cast or a wait, or at
        # a heal fountain within a level of the mark; item 2).
        mark_tiles = {0: DungeonTile.MARK_KINGS, 1: DungeonTile.MARK_FIRE,
                      2: DungeonTile.MARK_SNAKE, 3: DungeonTile.MARK_FORCE}
        goal_marks = (
            (0,) if goal == Goal.GET_MARK_KINGS
            else (1, 2, 3) if goal == Goal.GET_REMAINING_MARKS
            else ()
        )

        def _reachable(mark_idx: int) -> bool:
            plan = self._rod_plan(party, mark_idx)
            if plan is None:
                return False
            if plan[0] != "off":
                return True
            # "off": nobody safe, no heal, no wait helps. A heal fountain
            # near the mark still does, unless someone is under 10 rations.
            if not mark_reachable(party, mark_idx):
                return False
            marks = self._find_dungeon_tiles(dmap, {mark_tiles[mark_idx]})
            heals = self._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_HEAL})
            return any(abs(hz - mz) <= self._FOUNTAIN_LEVELS for *_m, mz in marks for *_h, hz in heals)

        wanted_marks = [
            i for i in goal_marks
            if self._find_dungeon_tiles(dmap, {mark_tiles[i]}) and _reachable(i)
        ]
        # A member who lacks a wanted mark and is not safe to burn (the rod
        # would wait, or can do nothing) wants a heal fountain first.
        self._rod_heal_wanted = any(
            (plan := self._rod_plan(party, i)) is not None and plan[0] in ("wait", "off")
            for i in wanted_marks
        )

        # A chest underfoot: open it the safe way (APPAR UNEM, or G with no
        # caster alive in a party strong enough for a trap). Never waits for
        # MP and never goes looking for chests (user 2026-11-22).
        if cur_tile == DungeonTile.CHEST:
            opener = self._chest_opener(party)
            weak = any(m.is_dead() for m in party.members) or any(
                m.level < self._CHEST_RISK_LEVEL for m in party.members
            )
            if opener is not None and (opener[0] == "cast" or not weak):
                return self._open_chest(state_machine, party)

        # Item 5: turn back when a living member is under the bar for this
        # level or the next one down on the way to the mark (planner
        # dungeon_turn_back); go on again only past the mark level's bar
        # plus a margin (dungeon_may_resume), so it never see-saws on a
        # ladder. The latch belongs to this dungeon visit.
        starving = any(not m.is_dead() and m.food <= 0 for m in party.members)
        if self._retreat_state is not screen.state:
            self._retreat_state = screen.state
            self._retreating = False
        mark_z = None
        if wanted_marks and not starving:
            mark_z = min(
                z for *_xy, z in self._find_dungeon_tiles(dmap, {mark_tiles[i] for i in wanted_marks})
            )
            if self._retreating:
                if dungeon_may_resume(party, mark_z):
                    self._retreating = False
            elif dungeon_turn_back(party, screen.state.z, mark_z):
                self._retreating = True
        else:
            self._retreating = False

        # Poison: ALCORT on the spot when a Cleric or Druid has the 35 MP.
        poisoned = next(
            (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.status == Status.POISONED),
            None,
        )
        # Cure mode latches once poison is dire, until nobody is poisoned or
        # the party leaves (a new dungeon state): the bar is lower a level
        # up, so a climb toward a cure used to drop the cure and walk back
        # down, see-sawing on the ladder (review 2026-11-25).
        if poisoned is None:
            self._cure_latch = None
        elif self._poison_dire(party, screen.state.z):
            self._cure_latch = screen.state
        self._cure_mode = poisoned is not None and self._cure_latch is screen.state
        if self._cure_mode:
            alcort = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=35)
            if alcort is not None:
                self._queue_text(self._cleric_cast(party, alcort[0], f"h{poisoned}"), enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # A cure fountain (poison, any level, nearest by steps) or a heal
        # fountain (a real HP need, this level or one up or down) comes
        # before leaving: free, and no MP spent (autoplay round 1, item 1).
        # Not while anyone starves (that leaves at once, below).
        if not any(not m.is_dead() and m.food <= 0 for m in party.members):
            fountains = self._fountain_goals(
                party, dmap, screen.state.z, (screen.state.x, screen.state.y)
            )
            here = (screen.state.x, screen.state.y, screen.state.z)
            if here in fountains and self._fountain_drinker(party, cur_tile) is not None:
                # On it with someone to drink: a pass, and the fixture asks.
                return self._emit_key(state_machine, pygame.K_SPACE)
            fountains.discard(here)
            if fountains:
                key = find_dungeon_step(
                    dmap, screen.state.x, screen.state.y, screen.state.z, screen.state.dir,
                    fountains,
                    penalty_tiles=self._find_dungeon_tiles(dmap, {DungeonTile.GREMLINS}),
                )
                # A fountain trip down a ladder waits for the healer's MP
                # like any other descent (item 5).
                if key == pygame.K_d and descend_mp_short(party) and self._gave_up_state is not screen.state:
                    return self._ladder_wait(state_machine, screen)
                if key is not None:
                    return self._move_lit(state_machine, screen, party, cur_tile, key)

        # Nobody safe, no MP yet, no heal fountain near, but standing here
        # gets there (a healer's MP or HP regen): pass the turn on the rod
        # (no encounter roll on a fixture, UltimaDngn.c:183-341).
        if rod is not None and rod[0] == "wait":
            return self._emit_key(state_machine, pygame.K_SPACE)

        # A mark nobody can touch safely and nothing here can fix (see
        # _reachable) is not walked to or back onto: the party leaves, and
        # the planner's loop guard (planner.mark_reachable) keeps it from
        # walking straight back in. The mark stays a goal until every
        # living member has it, so the party comes back for it.
        # Turning back with no fountain near: a healer with MP heals the
        # member furthest under the mark level's bar on the spot; otherwise
        # the party leaves, if the surface can heal it (it rests indoors).
        # A party that can't be healed out there gains nothing by leaving
        # and walking back in: it goes on.
        # A ladder wait that could not end (_ladder_wait) leaves for the
        # rest of this visit.
        leaving = self._gave_up_state is screen.state
        if self._retreating and mark_z is not None:
            cast = self._dungeon_heal_cast(party, mark_z)
            if cast is not None:
                self._queue_text(cast, enter=False)
                return self._emit_key(state_machine, pygame.K_c)
            # A give-up stands: a retreat that can't rest outside must not
            # turn it back into a descent past the MP wait (review
            # 2026-11-25).
            leaving = leaving or self._can_rest_indoors(party, goal)

        target_tiles: set[tuple[int, int, int]] = set()
        if wanted_marks and not leaving:
            target_tiles = self._find_dungeon_tiles(dmap, {mark_tiles[i] for i in wanted_marks})

        # Anyone at 0 food is starving every step: leave now, Mark or not
        # (batch 1c7525f: members hit 0 on the Fire dungeon's level 4 and
        # the party went on down to level 7).
        if any(not m.is_dead() and m.food <= 0 for m in party.members):
            target_tiles = set()

        if not target_tiles:
            target_tiles = {(1, 1, 0)}

        if (screen.state.x, screen.state.y, screen.state.z) == (1, 1, 0) and target_tiles == {(1, 1, 0)}:
            return self._emit_key(state_machine, pygame.K_k)

        # Gremlins take 100 food from a member per tile stepped on (batch
        # 1c7525f: about 13 of 49 wipes starved after the Fire dungeon).
        # Cross as few as possible; the tile clears once triggered.
        key = find_dungeon_step(
            dmap,
            screen.state.x,
            screen.state.y,
            screen.state.z,
            screen.state.dir,
            target_tiles,
            penalty_tiles=self._find_dungeon_tiles(dmap, {DungeonTile.GREMLINS}),
        )
        # Down a ladder only with the healer's two Sanctus: short, wait on
        # the ladder (no encounter roll there) while the food allows.
        if key == pygame.K_d and descend_mp_short(party) and self._gave_up_state is not screen.state:
            return self._ladder_wait(state_machine, screen)
        if key is not None:
            return self._move_lit(state_machine, screen, party, cur_tile, key)
        return self._emit_key(state_machine, pygame.K_k)

    # A ladder MP wait that runs this long has an end it can't reach (the
    # healer gains about 1 MP per 4 turns, so 20 MP takes ~80): for the
    # rest of this visit the party heads for the exit and waits on no
    # ladder (the way out may itself go down: Fires of Hell z 6 at
    # (15, 12) is reached only from z 7). Live trace 2026-11-25,
    # trace_20261125-174431.
    _LADDER_WAIT_MAX = 160

    def _ladder_wait(self, state_machine, screen) -> int:
        """Pass on the ladder (no encounter roll there) for the healer's MP;
        past _LADDER_WAIT_MAX turns in a row, leave the dungeon instead."""
        st = screen.state
        here = (st.x, st.y, st.z)
        if self._ladder_wait_at != (st, here):
            self._ladder_wait_at = (st, here)
            self._ladder_waited = 0
        self._ladder_waited += 1
        if self._ladder_waited > self._LADDER_WAIT_MAX:
            self._gave_up_state = st
        return self._emit_key(state_machine, pygame.K_SPACE)

    # Light: a torch, else a Wizard's spell, else a Cleric's only when its
    # MP stays at the healer reserve the ladder wait and the heals need.
    _LIGHT_KEYS = (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_d)

    def _move_lit(self, state_machine, screen, party, cur_tile, key: int) -> int:
        """Emit a move, lighting the way first when the light is out. Only
        a move needs light: waiting (a ladder, the rod, a fountain) never
        lights. Live trace 2026-11-25 (trace_20261125-174431): the party
        waited on a Fires of Hell ladder for the Cleric's 20 MP, the light
        spell (10 turns) ran out, the light block cast it again at 15 MP,
        and the Cleric never reached 20 for ~8,000 steps. Not on the
        strange wind: it puts the light out after every command there
        (LairWare UltimaDngn.c:280-283, ledger D-12)."""
        if (
            key in self._LIGHT_KEYS
            and not getattr(screen.state, "is_torch_on", False)
            and cur_tile != DungeonTile.WIND_TRAP
        ):
            holder = next(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.torches > 0),
                None,
            )
            if holder is not None:
                # Ignite asks whose torch (LairWare Ignite, UltimaMain.c:1962-1966).
                self._queue_text(str(holder), enter=False)
                return self._emit_key(state_machine, pygame.K_i)
            wiz = self._find_caster(party, (Profession.WIZARD,), min_mp=10)
            if wiz is not None:
                self._queue_text(f"{wiz[0]}c", enter=False)
                return self._emit_key(state_machine, pygame.K_c)
            cleric = next(
                (
                    i + 1
                    for i, m in enumerate(party.members)
                    if not m.is_dead()
                    and m.profession == Profession.CLERIC
                    and m.mp - 15 >= min(m.max_mp, DESCEND_MP)
                ),
                None,
            )
            if cleric is not None:
                self._queue_text(f"{cleric}d", enter=False)
                return self._emit_key(state_machine, pygame.K_c)
        return self._emit_key(state_machine, key)

    def _step_2d(self, state_machine: StateMachine, screen) -> int | None:
        if screen.text_log.is_waiting_for_input:
            from py_exodus.world import shrine

            if screen.text_log.current_prompt in (shrine.PROMPT_WHO, shrine.PROMPT_OFFER):
                return self._step_shrine(state_machine, screen)
            return self._handle_town_prompt(state_machine, screen)

        party = screen.party
        goal = evaluate_goal(party, map_id=self._screen_map_id(screen, party))
        if goal == Goal.DONE:
            return None

        if hasattr(screen, "avatar_x"):
            px, py = screen.avatar_x, screen.avatar_y
        else:
            px, py = party.x, party.y

        # Pirate firing lanes and squid reach come before anything that
        # spends a turn (spells included).
        if type(screen).__name__ == "OverworldScreen" and getattr(screen, "game_map", None) is not None:
            escape_key = self._threat_escape(state_machine, screen, party, px, py)
            if escape_key is not None:
                return escape_key

        # A member out of food is fed from the others first (seed 3), the
        # dead included, so a raised member does not starve again at once.
        feed_key = self._maybe_feed(state_machine, party)
        if feed_key is not None:
            return feed_key

        # Cast resurrection spell on the spot if a Cleric has enough MP
        dead_idx = next((i + 1 for i, m in enumerate(party.members) if m.status == Status.DEAD), None)
        if dead_idx is not None:
            caster = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=65)
            if caster is not None:
                self._queue_text(self._cleric_cast(party, caster[0], f"n{dead_idx}"), enter=False)
                return self._emit_key(state_machine, pygame.K_c)
        ash_idx = next((i + 1 for i, m in enumerate(party.members) if m.status == Status.ASH), None)
        if ash_idx is not None:
            caster = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=75)
            if caster is not None:
                self._queue_text(self._cleric_cast(party, caster[0], f"p{ash_idx}"), enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # Cast ALCORT to cure poison on the spot if a Cleric/Druid has >= 35 MP
        poison_idx = next((i + 1 for i, m in enumerate(party.members) if m.status == Status.POISONED), None)
        if poison_idx is not None:
            caster = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=35)
            if caster is not None:
                self._queue_text(self._cleric_cast(party, caster[0], f"h{poison_idx}"), enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # Heal detour if hurt (skip during BUY_FOOD/starvation, and skip/save MP during CURE_POISON unless <= 25 HP).
        # In a town or castle it is the town rest's decision (70% to start).
        in_town = type(screen).__name__ == "TownScreen"
        if (
            (self._town_heal_due(screen, party) if in_town else needs_heal(party))
            and goal != Goal.BUY_FOOD
            and party.food > 0
            and (
                goal != Goal.CURE_POISON
                or any(not m.is_dead() and m.hp <= 25 for m in party.members)
            )
        ):
            saving_for_alcort = poison_idx is not None and all(
                m.hp > 25 for m in party.members if not m.is_dead()
            )
            caster = next(
                (
                    (i + 1, m.profession)
                    for i, m in enumerate(party.members)
                    if not m.is_dead()
                    and m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
                    and m.mp >= 10
                    and not (
                        saving_for_alcort
                        and m.profession in (Profession.CLERIC, Profession.DRUID)
                        and m.max_mp >= 35
                    )
                ),
                None,
            )
            if caster is not None:
                hurt_candidates = [
                    (i + 1, m) for i, m in enumerate(party.members) if not m.is_dead() and m.hp < m.max_hp
                ]
                hurt_idx = (
                    min(hurt_candidates, key=lambda im: im[1].hp / max(1, im[1].max_hp))[0]
                    if hurt_candidates
                    else 1
                )
                self._queue_text(self._cleric_cast(party, caster[0], f"c{hurt_idx}"), enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # TownScreen / City maps
        if type(screen).__name__ == "TownScreen":
            return self._step_town(state_machine, screen, party, px, py, goal)

        # OverworldScreen (Sosaria = 0, Ambrosia = 13)
        return self._step_overworld(state_machine, screen, party, px, py, goal)

    def _step_town(
        self, state_machine: StateMachine, screen, party, px: int, py: int, goal: Goal,
        roamers_ok: bool = False,
    ) -> int | None:
        self._sell_plan = None  # a talk in progress answers prompts, not steps
        gmap = screen.game_map
        map_id = getattr(gmap, "id", getattr(screen, "map_id", party.map_id))
        # Ledger B-15 (LairWare Combat, UltimaSpellCombat.c:873-876): any
        # town fight turns every guard and Lord British into hunters for
        # the visit. Eight guards come to that fight (B-09) and Lord British
        # can't be hurt (B-11), so it is a hard fight at best. Keep out of
        # reach of hostile people, and once the guards hunt, bribe the one
        # at hand or walk out.
        pen_danger, roam_danger = self._town_danger_parts(gmap, map_id)
        full_danger = pen_danger | roam_danger
        if self._town_alarm(gmap, map_id):
            self._town_danger_tiles = full_danger
            return self._flee_town(state_machine, gmap, party, px, py, full_danger)
        # A roaming hostile (Grey's thief) can stand across every route to a
        # goal; then go anyway (second pass, roamers_ok) rather than walk out
        # and back in forever. Penned ones (shop merchants) stay avoided.
        danger = pen_danger if roamers_ok else full_danger
        self._town_danger_tiles = danger
        # Lord British raises max HP without healing (LairWare Transact,
        # UltimaMain.c:2373-2380), so level first, rest after.
        british_levels = map_id == 1 and any(self._can_level_at_british(m) for m in party.members)
        if (
            map_id not in _UNSAFE_REST_TOWN_MAPS
            and (px, py) not in full_danger
            and not british_levels
            and self._town_heal_due(screen, party)
            and self._can_rest_indoors(party, goal)
        ):
            return self._emit_key(state_machine, pygame.K_SPACE)
        if map_id == 2:  # EXODUS (Castle of Death)
            status = getattr(party, "exodus_cards_status", 0)
            for tx, ty, bit, letter, card_idx in _EXODUS_PANELS:
                if not (status & bit):
                    if (px, py) == (tx, ty):
                        m_idx = next(
                            (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.cards[card_idx] > 0),
                            1,
                        )
                        self._queue_text("INSERT", enter=True)
                        self._queue_text(f"{m_idx}{letter}", enter=False)
                        return self._emit_key(state_machine, pygame.K_o)
                    d = find_2d_step(gmap, (px, py), (tx, ty), Transport.FOOT, party=party)
                    if d is not None:
                        return self._emit_key(state_machine, _DIR_TO_KEY[d])
                    # Path blocked by Exodus ATTACK_AVATAR NPCs (e.g. animated floor traps):
                    # route treating hostile NPCs as passable so bumping them clears the way.
                    hostile_coords = {
                        (npc.x, npc.y)
                        for npc in getattr(gmap, "npcs", ())
                        if getattr(npc, "movement", None) == "ATTACK_AVATAR"
                    }
                    if hostile_coords:
                        from py_exodus.screens.overworld import can_move_to

                        has_fire = any(not m.is_dead() and m.marks[1] > 0 for m in party.members)
                        has_force = tile_effects.all_members_mark_of_force(party)
                        q_ex: deque[tuple[int, int, Direction | None]] = deque([(px, py, None)])
                        vis_ex = {(px, py)}
                        while q_ex:
                            cx, cy, first_d = q_ex.popleft()
                            for cand in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                                nx, ny = cx + cand.dx, cy + cand.dy
                                if (nx, ny) in vis_ex or not (0 <= nx < gmap.width and 0 <= ny < gmap.height):
                                    continue
                                t = gmap.get_tile(nx, ny)
                                tname = str(getattr(t, "name", "")).lower() if t else ""
                                if tname in ("lava", "fire") and not has_fire:
                                    continue
                                if tname in ("energy_field", "force_field") and not has_force:
                                    continue
                                if (nx, ny) in hostile_coords or can_move_to(gmap, nx, ny, Transport.FOOT, party=party):
                                    step_d = first_d or cand
                                    if (nx, ny) == (tx, ty):
                                        return self._emit_key(state_machine, _DIR_TO_KEY[step_d])
                                    vis_ex.add((nx, ny))
                                    q_ex.append((nx, ny, step_d))
                    return self._emit_key(state_machine, pygame.K_SPACE)

        npc_tiles = {(npc.x, npc.y) for npc in getattr(gmap, "npcs", [])}
        npc_tiles |= danger - {(px, py)}

        can_alcort = any(
            not m.is_dead() and m.profession in (Profession.CLERIC, Profession.DRUID) and m.max_mp >= 35
            for m in party.members
        )
        if (
            map_id == 10
            and (
                goal in (Goal.GRIND_AND_LEVEL, Goal.BUY_KEYS)
                or (goal == Goal.CURE_POISON and can_alcort)
            )
            and party.gold < raid_gold_target(party, _DEATH_GULCH_GOLD_CAP)
            and gold_has_a_use(party)
            and party.food >= 40
            and all(not m.is_dead() and m.hp > 100 for m in party.members)
            # User report (2026-11-21): G with a low-dex Thief once the MP
            # ran out poisoned the party on nearly every raid. Raid only
            # while a chest can be opened safely (APPAR UNEM or dex 74+);
            # otherwise wait in town for the caster's MP (below).
            and (self._chest_opener(party) is not None or self._mana_caster(party) is not None)
        ):
            opener = self._chest_opener(party)
            dg_chests = {
                (x, y)
                for y in range(gmap.height)
                for x in range(gmap.width)
                if "chest" in str(getattr(gmap.get_tile(x, y), "name", "")).lower()
            }
            if opener is not None and (px, py) in dg_chests and (px, py) not in danger:
                return self._open_chest(state_machine, party)
            has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
            # Only chests the party can actually reach, people who move
            # treated as passing (they step aside); FIXED people stay walls.
            # The pub's chests behind its counters are never reachable:
            # chasing them, re-routed every turn around the pub's wandering
            # thieves, circled (53-54,32-33) for thousands of steps (live
            # trace 2026-11-22, turns 52,690-57,100).
            fixed_npcs = [n for n in gmap.npcs if getattr(n, "movement", "FIXED") == "FIXED"]
            saved_npcs = gmap.npcs
            gmap.npcs = fixed_npcs
            try:
                reach = reachable_2d(
                    gmap, (px, py), Transport.FOOT, party=party,
                    avoid_tiles={(n.x, n.y) for n in fixed_npcs}, allow_locked_doors=has_key,
                )
            finally:
                gmap.npcs = saved_npcs
            # Chests next to a hostile merchant's walk (the armour shop's row
            # 55) are left: opening one starts a fight that sets the guards
            # hunting (B-15).
            open_chests = (dg_chests & reach) - danger
            # Out of MP for APPAR UNEM with chests still to open: wait here
            # until the caster has several casts' worth. Walking toward the
            # exit at 0-4 MP and back at 5 cost a round trip per chest.
            caster = self._mana_caster(party)
            if (
                caster is not None and open_chests and (px, py) not in danger
                and (opener is None or self._mana_waiting)
            ):
                if caster.mp < min(caster.max_mp, self._RAID_MANA_TARGET):
                    self._mana_waiting = True
                    return self._emit_key(state_machine, pygame.K_SPACE)
            self._mana_waiting = False
            if opener is not None and open_chests:
                key = self._town_step_patient(state_machine, gmap, party, px, py, open_chests, npc_tiles)
                if key is not None:
                    return key
            if dg_chests:
                # Path to chests blocked by a guard: only bribe a guard standing in a
                # chokepoint that separates us from unvisited passable tiles.
                guards = {
                    (npc.x, npc.y)
                    for npc in getattr(gmap, "npcs", [])
                    if "guard" in str(getattr(npc, "tile_name", getattr(npc, "tile", ""))).lower()
                }
                living = _able(party)
                if guards and living and party.gold >= 100:
                    from py_exodus.screens.overworld import can_move_to

                    # Moving people are not walls (they step aside); only
                    # FIXED ones close off a room.
                    fixed_tiles = {(n.x, n.y) for n in fixed_npcs}

                    reachable = {(px, py)}
                    rq = deque([(px, py)])
                    while rq:
                        rx, ry = rq.popleft()
                        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                            nx, ny = rx + dx, ry + dy
                            if (nx, ny) in reachable or not (0 <= nx < gmap.width and 0 <= ny < gmap.height):
                                continue
                            if (nx, ny) in fixed_tiles:
                                continue
                            t = gmap.get_tile(nx, ny)
                            tname = str(getattr(t, "name", "")).lower() if t else ""
                            if can_move_to(gmap, nx, ny, Transport.FOOT, party=party) or (
                                has_key and tname == "locked_door"
                            ):
                                reachable.add((nx, ny))
                                rq.append((nx, ny))

                    def _tile_open(tx: int, ty: int) -> bool:
                        if not (0 <= tx < gmap.width and 0 <= ty < gmap.height):
                            return False
                        t = gmap.get_tile(tx, ty)
                        tname = str(getattr(t, "name", "")).lower() if t else ""
                        if tname in ("wall", "brick", "mountains", "mountain", "water", "whirlpool"):
                            return False
                        return True

                    blocking_guards = {
                        (gx, gy)
                        for gx, gy in guards
                        if any(
                            _tile_open(gx + dx, gy + dy)
                            and (gx + dx, gy + dy) not in reachable
                            and (gx + dx, gy + dy) not in npc_tiles
                            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                        )
                    }
                    if blocking_guards:
                        briber_idx, briber = max(living, key=lambda im: im[1].gold)
                        if briber.gold < 100:
                            self._join_gold_member_idx = briber_idx
                            return self._emit_key(state_machine, pygame.K_j)
                        for d_g in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                            if (px + d_g.dx, py + d_g.dy) in blocking_guards:
                                self._queue_text("BRIBE", enter=True)
                                self._queue_text(f"{briber_idx}{d_g.name[0].lower()}", enter=False)
                                return self._emit_key(state_machine, pygame.K_o)
                        adj_guard = {
                            (gx + dx, gy + dy)
                            for gx, gy in blocking_guards
                            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                            if 0 <= gx + dx < gmap.width and 0 <= gy + dy < gmap.height
                        } - npc_tiles
                        d_adj = find_2d_step(
                            gmap, (px, py), adj_guard, Transport.FOOT, party=party,
                            avoid_tiles=npc_tiles, allow_locked_doors=has_key,
                        )
                        if d_adj is not None:
                            return self._step_or_unlock(state_machine, gmap, party, px, py, d_adj)

        if map_id == 1:  # Castle of Lord British
            level_idx = next(
                (i + 1 for i, m in enumerate(party.members) if self._can_level_at_british(m)),
                None,
            )
            if level_idx is not None:
                if (px, py) == (32, 15):
                    self._queue_text(f"{level_idx}n", enter=False)
                    return self._emit_key(state_machine, pygame.K_t)
                d = find_2d_step(
                    gmap, (px, py), (32, 15), Transport.FOOT, party=party,
                    avoid_tiles=npc_tiles, prefer_paths=True,
                )
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        gear_key = self._maybe_manage_gear(state_machine, party, prefer_ranged=prefer_ranged_weapons(party))
        if gear_key is not None:
            return gear_key

        if (
            map_id in _SHOP_TOWNS
            and (goal == Goal.OUTFIT_BRITAIN or map_id == 11)
            and getattr(self, "_food_shop_target", None) is None
        ):
            upgrade = best_shop_upgrade(party, include_wizard_dagger=True, include_dawn=(map_id == 11))
            if upgrade is not None and (not upgrade.dawn_only or map_id == 11):
                key = self._buy_upgrade(state_machine, gmap, party, map_id, px, py, npc_tiles, upgrade)
                if key is not None:
                    return key

        if map_id in _GUILD_TOWNS and goal in (Goal.BUY_KEYS, Goal.BUY_TORCHES):
            _, _, guild_xy = _GUILD_TOWNS[map_id]
            guild_xy = self._shop_spot(gmap, (px, py), guild_xy)
            living = _able(party)
            if living:
                if goal == Goal.BUY_KEYS:
                    cost, letter = 50, "c"
                else:
                    cost, letter = 30, "a"
                buyer_idx, buyer = max(living, key=lambda im: im[1].gold)
                if buyer.gold < cost:
                    self._join_gold_member_idx = buyer_idx
                    return self._emit_key(state_machine, pygame.K_j)
                if (px, py) == guild_xy:
                    self._shop_member_idx = buyer_idx
                    self._shop_item_letter = letter
                    self._talk_dir_key = self._direction_to_npc(gmap, px, py)
                    return self._emit_key(state_machine, pygame.K_t)
                key = self._town_step_patient(state_machine, gmap, party, px, py, guild_xy, npc_tiles)
                if key is not None:
                    return key

        if (
            map_id in _FOOD_TOWNS
            and goal not in (Goal.CURE_POISON, Goal.RESURRECT_DEAD)
            # Death Gulch's grocer is the stranded party's food run only:
            # a target left from an earlier run must not take a raid there.
            and (map_id != _MAP_DEATH_GULCH or goal == Goal.BUY_FOOD)
        ):
            _, _, food_xy = _FOOD_TOWNS[map_id]
            food_xy = self._shop_spot(gmap, (px, py), food_xy)
            living = _able(party)
            if living:
                total_gold = party.gold
                food_price = 1  # a ration, LairWare Shop case 1
                if goal == Goal.BUY_FOOD and getattr(self, "_food_shop_target", None) is None:
                    trip_gold = return_trip_gold(party)
                    # Item 7's trip too: its gold gate (ambrosia_trip_gold)
                    # budgets food up to the entry food only, so filling to
                    # 400 dropped the party ~760 under it, back to grinding,
                    # and the next food run did it again (review 2026-11-25).
                    if (trip_gold and total_gold >= trip_gold) or ambrosia_trip_due(party):
                        # Stocking for a return trip: only the entry food
                        # the trip's gold target counts. Filling to 400
                        # dropped a party under the target and back to
                        # raiding (user live trace 2026-11-22,
                        # trace_20261122-154730: 1,752 -> 762 gold).
                        self._food_shop_target = AMBROSIA_ENTRY_FOOD
                    elif total_gold >= 1500:
                        self._food_shop_target = 400
                    elif total_gold >= 700:
                        # >= AMBROSIA_ENTRY_FOOD, so a pre-Ambrosia food run
                        # never ends short of the entry budget.
                        self._food_shop_target = 300
                    else:
                        self._food_shop_target = 150
                shop_target = getattr(self, "_food_shop_target", None)
                if (
                    shop_target is not None
                    and total_gold >= food_price
                    and any(m.food < shop_target for _, m in living)
                ):
                    buyer_idx, buyer = min(living, key=lambda im: im[1].food)
                    # Rations, in the 25s it bought as Java packs (a meal
                    # eaten on the way out must not leave it 1 short).
                    packs_needed = max(1, (shop_target - buyer.food + 24) // 25) * 25
                    low_food_count = sum(1 for _, m in living if m.food < shop_target)
                    if low_food_count > 1:
                        fair_packs = max(1, (total_gold // food_price) // low_food_count)
                        packs_needed = min(packs_needed, fair_packs)
                    if buyer.gold < total_gold and buyer.gold < min(packs_needed * food_price, 500):
                        self._join_gold_member_idx = buyer_idx
                        return self._emit_key(state_machine, pygame.K_j)
                    if (px, py) == food_xy:
                        self._food_packs = max(1, min(500, packs_needed, buyer.gold // food_price))
                        self._shop_member_idx = buyer_idx
                        self._talk_dir_key = self._direction_to_npc(gmap, px, py)
                        return self._emit_key(state_machine, pygame.K_t)
                    if map_id != _MAP_DEATH_GULCH:
                        # Patient: Fawn's grocery has four wandering thieves
                        # across its only row in (24-27, 48); with no route
                        # this turn the party walked out and back in forever.
                        key = self._town_step_patient(state_machine, gmap, party, px, py, food_xy, npc_tiles)
                        if key is not None:
                            return key
                    d = find_2d_step(
                        gmap, (px, py), food_xy, Transport.FOOT, party=party,
                        avoid_tiles=npc_tiles, prefer_paths=True,
                    )
                    if d is not None:
                        return self._emit_key(state_machine, _DIR_TO_KEY[d])
                    if map_id == _MAP_DEATH_GULCH:
                        key = self._death_gulch_way(state_machine, gmap, party, px, py, food_xy, npc_tiles)
                        if key is not None:
                            return key
                else:
                    self._food_shop_target = None

        if map_id in _HEALER_TOWNS and goal in (Goal.RESURRECT_DEAD, Goal.CURE_POISON):
            _, _, healer_stand = _HEALER_TOWNS[map_id]
            healer_xy = self._shop_spot(gmap, (px, py), healer_stand)
            if healer_xy != healer_stand and find_2d_step(
                gmap, (px, py), healer_xy, Transport.FOOT, party=party, avoid_tiles=npc_tiles,
            ) is None:
                # The healer follows the party along his counter; a spot
                # facing him can be a nook no route reaches (Moon's (47,50),
                # behind a fixed cleric). Go to his stand and let him come
                # (trace 2026-11-25: Moon entered and left ~8000 steps).
                healer_xy = healer_stand
                if (px, py) == healer_stand:
                    return self._emit_key(state_machine, pygame.K_SPACE)
            living = _able(party)
            if goal == Goal.RESURRECT_DEAD:
                patient = next(
                    (
                        (i + 1, m, (900 if m.status == Status.ASH else 500), ("d" if m.status == Status.ASH else "c"))
                        for i, m in enumerate(party.members)
                        if m.status in (Status.DEAD, Status.ASH)
                    ),
                    None,
                )
            else:
                patient = next(
                    (
                        (i + 1, m, 100, "a")
                        for i, m in enumerate(party.members)
                        if m.status == Status.POISONED
                    ),
                    None,
                )
            if living and patient is not None:
                patient_idx, _, cost, letter = patient
                payer_idx, payer = max(living, key=lambda im: im[1].gold)
                if payer.gold < cost:
                    self._join_gold_member_idx = payer_idx
                    return self._emit_key(state_machine, pygame.K_j)
                if (px, py) == healer_xy:
                    self._shop_member_idx = payer_idx
                    self._shop_item_letter = letter
                    self._heal_patient_idx = patient_idx
                    self._talk_dir_key = self._direction_to_npc(gmap, px, py)
                    return self._emit_key(state_machine, pygame.K_t)
                d = find_2d_step(
                    gmap, (px, py), healer_xy, Transport.FOOT, party=party,
                    avoid_tiles=npc_tiles, prefer_paths=True,
                )
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        # On the way out of a shop town: sell spare weapons and armour first.
        # Checked when leaving, not entering: buying during the visit is what
        # leaves gear spare (user 2026-11-23).
        key = self._sell_spare_gear(state_machine, screen, gmap, party, map_id, px, py, npc_tiles)
        if key is not None:
            return key

        # Item B (user ruling 2026-11-25): the spare plain Bow, on the way out
        # of any town with a weapon shop the party came to anyway (never a
        # trip of its own), with gold the plan isn't saving.
        if (
            map_id in _SHOP_TOWNS
            and goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON)
            and optional_purchase_ok(party, SPARE_BOW_PRICE)
        ):
            if self._bow_visit != id(screen):
                self._bow_visit, self._bow_talks = id(screen), 0
            upgrade = spare_bow_purchase(party)
            if upgrade is not None and self._bow_talks < _BOW_TALKS_PER_VISIT:
                key = self._buy_upgrade(state_machine, gmap, party, map_id, px, py, npc_tiles, upgrade)
                if key == pygame.K_t:
                    self._bow_talks += 1
                if key is not None:
                    return key

        if roam_danger and not roamers_ok:
            # No goal route kept clear of a roaming hostile: try once more
            # with only the people in the way before giving up on the town.
            return self._step_town(state_machine, screen, party, px, py, goal, roamers_ok=True)

        # Default in town: walk to nearest exit border (e.g. Britain's east gate)
        return self._walk_out_of_town(state_machine, gmap, party, px, py, npc_tiles)

    # A hostile person penned in a room this small (a shop's merchant, the
    # Castle British cell) is kept off by its whole pen; one that roams
    # the town by its current tile.
    _HUNTER_PEN_MAX = 40

    @staticmethod
    def _town_alarm(gmap, map_id) -> bool:
        """A guard or Lord British hunts the party (after a town fight or a
        failed steal; LairWare UltimaSpellCombat.c:873-876, UltimaMain.c:
        2266-2269). Castle Exodus is left to its own logic: its two guards
        hunt from the start."""
        if map_id == _MAP_EXODUS:
            return False
        return any(
            getattr(n, "tile_index", -1) in (18, 19) and getattr(n, "movement", None) == "ATTACK_AVATAR"
            for n in getattr(gmap, "npcs", ())
        )

    @classmethod
    def _town_danger(cls, gmap, map_id) -> set[tuple[int, int]]:
        pen, roam = cls._town_danger_parts(gmap, map_id)
        return pen | roam

    @classmethod
    def _town_danger_parts(cls, gmap, map_id) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        """(penned, roaming) danger: tiles where a hostile (0xC0) person can attack the party on its
        next move: LairWare MoveMonsters (UltimaMisc.c:1197-1203) attacks
        when the person's step toward the party lands on it, i.e. from any
        of the 8 neighbours, across a counter too. For a person penned in a
        small room: every tile next to the pen. For a roaming one: within 2
        of it (it closes 1 a turn). Not Castle Exodus (fought through)."""
        from py_exodus.screens.town import TownScreen

        pen_danger: set[tuple[int, int]] = set()
        roam_danger: set[tuple[int, int]] = set()
        if gmap is None or map_id == _MAP_EXODUS:
            return pen_danger, roam_danger
        for n in getattr(gmap, "npcs", ()):
            if getattr(n, "movement", None) != "ATTACK_AVATAR":
                continue
            kind = str(getattr(n, "tile_name", "")).lower()
            walk = (
                frozenset({"water"}) if kind in TownScreen._PEOPLE_SEA else TownScreen._PEOPLE_LAND_TILES
            )
            pen = {(n.x, n.y)}
            stack = [(n.x, n.y)]
            while stack and len(pen) <= cls._HUNTER_PEN_MAX:
                x, y = stack.pop()
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        q = (x + dx, y + dy)
                        if q in pen or not (0 <= q[0] < gmap.width and 0 <= q[1] < gmap.height):
                            continue
                        if str(getattr(gmap.get_tile(*q), "name", "")).lower() in walk:
                            pen.add(q)
                            stack.append(q)
            penned = len(pen) <= cls._HUNTER_PEN_MAX
            centres, r = (pen, 1) if penned else ({(n.x, n.y)}, 2)
            out = pen_danger if penned else roam_danger
            for cx, cy in centres:
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        out.add((cx + dx, cy + dy))
        return pen_danger, roam_danger

    def _flee_town(self, state_machine, gmap, party, px: int, py: int, danger) -> int | None:
        """The guards hunt (B-15): bribe a guard standing N/S/E/W of the
        party (LairWare Bribe, UltimaMisc.c:2446-2464: 100 gold, any guard
        leaves), else walk for the nearest exit keeping out of reach. No
        Join Gold first: that turn is the guard's attack, so with nobody
        holding 100 gold the party steps away instead."""
        living = _able(party)
        if living:
            briber_idx, briber = max(living, key=lambda im: im[1].gold)
            if briber.gold >= 100:
                for d_g in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                    at = (px + d_g.dx, py + d_g.dy)
                    if any(
                        (n.x, n.y) == at and getattr(n, "tile_index", -1) == 18
                        for n in getattr(gmap, "npcs", ())
                    ):
                        self._queue_text("BRIBE", enter=True)
                        self._queue_text(f"{briber_idx}{d_g.name[0].lower()}", enter=False)
                        return self._emit_key(state_machine, pygame.K_o)
        npc_tiles = {(n.x, n.y) for n in getattr(gmap, "npcs", ())}
        hunters = [
            (n.x, n.y) for n in getattr(gmap, "npcs", ())
            if getattr(n, "movement", None) == "ATTACK_AVATAR"
        ]
        return self._walk_out_of_town(
            state_machine, gmap, party, px, py, npc_tiles,
            safe=npc_tiles | (danger - {(px, py)}), hunters=hunters,
        )

    def _walk_out_of_town(
        self, state_machine, gmap, party, px, py, npc_tiles, safe=None, hunters=(),
    ) -> int | None:
        """Step for the nearest town edge: around ``safe`` tiles if given
        and a way exists, else around the people, else straight. On those
        fallbacks a step that would end next to a hunter (diagonals too:
        MoveMonsters attacks from all 8 neighbours, UltimaMisc.c:1197-1203)
        gives way to one at least 2 from every hunter, nearest the exit."""
        if py == gmap.height - 1:
            return self._emit_key(state_machine, pygame.K_DOWN)
        if py == 0:
            return self._emit_key(state_machine, pygame.K_UP)
        if px == gmap.width - 1:
            return self._emit_key(state_machine, pygame.K_RIGHT)
        if px == 0:
            return self._emit_key(state_machine, pygame.K_LEFT)
        exits = (
            {(x, 0) for x in range(gmap.width)}
            | {(x, gmap.height - 1) for x in range(gmap.width)}
            | {(0, y) for y in range(gmap.height)}
            | {(gmap.width - 1, y) for y in range(gmap.height)}
        )
        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        d = None
        if safe:
            d = find_2d_step(
                gmap, (px, py), exits, Transport.FOOT, party=party,
                avoid_tiles=safe, prefer_paths=True, allow_locked_doors=has_key,
            )
        fallback = d is None
        if d is None:
            d = find_2d_step(
                gmap, (px, py), exits, Transport.FOOT, party=party,
                avoid_tiles=npc_tiles, prefer_paths=True, allow_locked_doors=has_key,
            )
        if d is None and npc_tiles:
            d = find_2d_step(
                gmap, (px, py), exits, Transport.FOOT, party=party,
                prefer_paths=True, allow_locked_doors=has_key,
            )

        def _clear(xy) -> bool:
            return all(max(abs(xy[0] - hx), abs(xy[1] - hy)) >= 2 for hx, hy in hunters)

        if fallback and hunters and (d is None or not _clear((px + d.dx, py + d.dy))):
            best = None
            for cand in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                nxt = (px + cand.dx, py + cand.dy)
                if nxt in npc_tiles or not _clear(nxt):
                    continue
                if not (0 <= nxt[0] < gmap.width and 0 <= nxt[1] < gmap.height):
                    continue
                if not can_move_to(gmap, nxt[0], nxt[1], Transport.FOOT, party=party):
                    continue
                cost = find_2d_step_and_cost(
                    gmap, nxt, exits, Transport.FOOT, party=party,
                    avoid_tiles=npc_tiles, prefer_paths=True, allow_locked_doors=has_key,
                )[1]
                key = 0 if nxt in exits else (cost if cost is not None else 10**9)
                if best is None or key < best[0]:
                    best = (key, cand)
            if best is not None:
                d = best[1]
        if d is not None:
            return self._step_or_unlock(state_machine, gmap, party, px, py, d)
        return self._emit_key(state_machine, pygame.K_SPACE)

    _sell_plan: tuple[int, str, int] | None = None
    _sell_asked = False
    _sell_visit: int | None = None
    _sell_talks = 0

    _bow_visit: int | None = None
    _bow_talks = 0

    def _buy_upgrade(self, state_machine, gmap, party, map_id, px, py, npc_tiles, upgrade) -> int | None:
        """Pool gold to the buyer, walk to the shop's counter and Transact
        for ``upgrade``; ``None`` when the counter can't be reached."""
        _, _, wep_xy, arm_xy = _SHOP_TOWNS[map_id]
        buyer = party.members[upgrade.member_idx - 1]
        if buyer.gold < upgrade.price:
            self._join_gold_member_idx = upgrade.member_idx
            return self._emit_key(state_machine, pygame.K_j)
        stand_xy = self._shop_spot(gmap, (px, py), wep_xy if upgrade.kind == "weapon" else arm_xy)
        if (px, py) == stand_xy:
            self._shop_member_idx = upgrade.member_idx
            self._shop_item_letter = upgrade.item_letter
            self._talk_dir_key = self._direction_to_npc(gmap, px, py)
            return self._emit_key(state_machine, pygame.K_t)
        d = find_2d_step(
            gmap, (px, py), stand_xy, Transport.FOOT, party=party,
            avoid_tiles=npc_tiles, prefer_paths=True,
        )
        if d is not None:
            return self._emit_key(state_machine, _DIR_TO_KEY[d])
        return None

    def _sell_spare_gear(self, state_machine, screen, gmap, party, map_id, px, py, npc_tiles) -> int | None:
        """Sell the party's spare weapons and armour (``excess_gear``) to this
        town's shops, one piece type per talk. Only in a town with weapon and
        armour shops the party is in anyway: never a trip to sell (user
        2026-11-23). Skipped in an emergency (a poisoned member near death,
        anyone out of food): leaving comes first."""
        if map_id not in _SHOP_TOWNS:
            return None
        if self._sell_visit != id(screen):
            self._sell_visit, self._sell_talks = id(screen), 0
        if self._sell_talks >= _SELL_TALKS_PER_VISIT:
            return None
        living = [m for m in party.members if not m.is_dead()]
        if any(m.food <= 0 for m in living) or any(
            m.status == Status.POISONED and m.hp <= 25 for m in living
        ):
            return None
        asset_mgr = getattr(screen, "asset_mgr", None)
        if asset_mgr is None:
            return None
        from py_exodus.screens.vendor_dialog import _typed_key

        stock: dict[str, dict] = {"weapon": {}, "armor": {}}
        for v in asset_mgr.get_vendors_for_map(map_id):
            vt = (v.vendor_type or "").upper()
            for it in v.items:
                if vt == "WEAPON" and it.weapon_type:
                    stock["weapon"][_typed_key(WeaponType, it.weapon_type)] = it
                elif vt == "ARMOR" and it.armor_type:
                    stock["armor"][_typed_key(ArmorType, it.armor_type)] = it
        sales = excess_gear(
            party, set(stock["weapon"]), set(stock["armor"]),
            prefer_ranged=prefer_ranged_weapons(party),
        )
        _, _, wep_xy, arm_xy = _SHOP_TOWNS[map_id]
        for sale in sorted(sales, key=lambda s: s.kind != "weapon"):  # weapons first
            item = stock[sale.kind][sale.item]
            owner = party.members[sale.member_idx - 1]
            # A sale past 9999 gold is cancelled by the shop (LairWare).
            count = min(sale.count, max(0, 9999 - owner.gold) // max(1, item.price))
            if count <= 0:
                continue
            spot = self._shop_spot(gmap, (px, py), wep_xy if sale.kind == "weapon" else arm_xy)
            if (px, py) == spot:
                self._sell_plan = (sale.member_idx, item.choice, count)
                self._sell_asked = False
                self._sell_talks += 1
                self._shop_member_idx = sale.member_idx
                self._talk_dir_key = self._direction_to_npc(gmap, px, py)
                return self._emit_key(state_machine, pygame.K_t)
            d = find_2d_step(
                gmap, (px, py), spot, Transport.FOOT, party=party,
                avoid_tiles=npc_tiles, prefer_paths=True,
            )
            if d is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[d])
            return None
        return None

    def _death_gulch_way(self, state_machine, gmap, party, px, py, goal_xy, npc_tiles) -> int | None:
        """A step toward ``goal_xy`` in Death Gulch past its locked doors
        (Unlock with a key) and the guard who stands in the west passage
        (bribed, 100 gold, as a raid does): Death Gulch's grocer (52, 35)
        is behind both. Moving people are not walls; fixed guards are,
        unless one stands on the route, which is then bribed."""
        has_key = any(m.keys > 0 for _, m in _able(party))
        movers = {
            (n.x, n.y) for n in getattr(gmap, "npcs", ())
            if getattr(n, "movement", "FIXED") != "FIXED"
        }
        guards = {
            (n.x, n.y) for n in getattr(gmap, "npcs", ())
            if "guard" in str(getattr(n, "tile_name", "")).lower()
        }
        saved = gmap.npcs
        gmap.npcs = [n for n in saved if (n.x, n.y) not in guards]
        try:
            d = find_2d_step(
                gmap, (px, py), goal_xy, Transport.FOOT, party=party,
                avoid_tiles=(npc_tiles - movers - guards) | (self._town_danger_tiles - {(px, py)}),
                allow_locked_doors=has_key,
            )
        finally:
            gmap.npcs = saved
        if d is None:
            return None
        nxt = (px + d.dx, py + d.dy)
        if nxt in guards:
            able = _able(party)
            if not able or party.gold < 100:
                return None
            briber_idx, briber = max(able, key=lambda im: im[1].gold)
            if briber.gold < 100:
                self._join_gold_member_idx = briber_idx
                return self._emit_key(state_machine, pygame.K_j)
            self._queue_text("BRIBE", enter=True)
            self._queue_text(f"{briber_idx}{d.name[0].lower()}", enter=False)
            return self._emit_key(state_machine, pygame.K_o)
        if nxt in movers:
            return self._emit_key(state_machine, pygame.K_SPACE)  # they step aside
        return self._step_or_unlock(state_machine, gmap, party, px, py, d)

    def _step_or_unlock(self, state_machine: StateMachine, gmap, party, px: int, py: int, d: Direction) -> int:
        nx, ny = px + d.dx, py + d.dy
        nxt_tile = gmap.get_tile(nx, ny) if 0 <= nx < gmap.width and 0 <= ny < gmap.height else None
        if nxt_tile is not None and str(getattr(nxt_tile, "name", "")).lower() == "locked_door":
            key_idx = next((i for i, m in _able(party) if m.keys > 0), None)
            if key_idx is not None:
                self._queue_text(f"{key_idx}{d.name[0].lower()}", enter=False)
                return self._emit_key(state_machine, pygame.K_u)
        return self._emit_key(state_machine, _DIR_TO_KEY[d])

    # ------------------------------------------------------------------
    # Overworld (Sosaria = 0, Ambrosia = 13)
    #
    # Order every tick: pirate-lane / squid escape (in _step_2d, before any
    # spell), chests, gear, cannons, hurt evasion and rest, then the goal
    # names a Destination and the trip follower moves the party there. Only
    # the trip follower emits B or X.
    # ------------------------------------------------------------------

    def _threat_escape(self, state_machine: StateMachine, screen, party, px: int, py: int) -> int | None:
        """Never end a turn in a pirate firing lane or next to a squid (pre-ALCORT)."""
        gmap = screen.game_map
        # Squids (user rule 2026-11-21): from a ship the cannons deal with
        # them; on foot a healthy, unpoisoned party fights them.
        fight_squids = (
            party.transport != Transport.SHIP
            and not party_has_low_hp(party)
            and all(m.status != Status.POISONED for m in party.members if not m.is_dead())
        )
        # A strong party fights a dragon rather than dodging its breath: the
        # escape can't close on one, so a level-25 party hopped between two
        # tiles in its range until it wiped (batch dbeb0c9 seed 159).
        dragon_lanes = not self._strong_vs_pirates(party)
        th = compute_threats(
            gmap,
            party,
            getattr(screen, "creatures", ()) or (),
            fight_squids=fight_squids,
            dragon_lanes=dragon_lanes,
        )
        self._threats = th
        pos = (px, py)
        on_ship = party.transport == Transport.SHIP

        # The trip's moongate is open right now and one step away: take it,
        # lane or not; the gate carries the party out of reach. Escaping
        # the lane instead missed every opening (live trace 2026-11-22:
        # 1,800 steps beside gate (57,46) with a pirate offshore, starved).
        gate_key = self._open_gate_step(screen, gmap, party, pos)
        if gate_key is not None:
            return self._emit_key(state_machine, gate_key, guarded=False)

        # Standing on the frigate the trip boards next: boarding is the way
        # out, so leave it to the trip (the one owner of B). Stepping off the
        # lane instead undid every arrival (batch ccd5f52 seed 107: a dragon's
        # lane over the frigate at (31, 3), off and on for ~1,000 steps, the
        # party stranded on the Exotic island until it starved).
        plan = self._trip
        if (
            not on_ship
            and plan is not None
            and plan.legs
            and plan.legs[0].action == "B"
            and plan.legs[0].end == pos
            and pos in self._frigate_costs(party, screen)
        ):
            return None

        # A frigate a few steps away while the trip wants a ship: walk to
        # it through the lanes and board (batch 89c1bf4 b9 seed 90).
        board_key = self._board_dash(state_machine, screen, gmap, party, pos, th)
        if board_key == _YIELD_TO_TRIP:
            return None
        if board_key is not None:
            return board_key

        # A stalled capture's dash through the lanes: nothing else undoes it.
        dash_key = self._capture_dash(state_machine, screen, gmap, party, pos, th)
        if dash_key is not None:
            return dash_key

        # A pirate orthogonally adjacent: attack it (battle, then its frigate).
        if th.pirates and not party_has_low_hp(party):
            for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                n = ((px + d.dx) % gmap.width, (py + d.dy) % gmap.height)
                if n in th.pirates:
                    return self._attack(state_machine, d)

        # A strong party on foot goes and kills pirates it can reach from
        # land instead of dodging their lanes (user report 2026-11-22: a
        # 25/25/19/25 party stepped in and out of a castle-side pirate's
        # lane until it nearly died).
        if not on_ship and th.pirates and self._strong_vs_pirates(party):
            hunt = self._pirate_hunt_step(gmap, party, pos, th)
            if hunt is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[hunt], guarded=False)

        # A dragon following on foot: walk into a nearby town, or stop
        # running and fight it (batch 67c0de5 b6 seed 57).
        key = self._outrun_or_engage(state_machine, screen, gmap, party, pos, th, dragon_lanes)
        if key is not None:
            return key

        if not th.unsafe_end(pos):
            return None
        # A few steps from the town gate the trip is walking into
        # (batch 0442fe7 seed 128: the escape stepped off the lane at (8, 44)
        # beside the gate at (7, 44), the trip stepped back, and so on for
        # ~2,600 steps until the party starved with 884 gold). Only the
        # escape: checked before the pirate hunt it cut a strong party's hunt
        # off one step from Death Gulch's gate, and the hunt and the trip took
        # turns there for thousands of steps (batch 2eacc2d seeds 131-138).
        if (
            not on_ship
            and plan is not None
            and plan.legs
            and plan.legs[0].action == "ARRIVE"
            and self._last_steps_into_town(gmap, party, pos, {plan.legs[0].end})
        ):
            return None

        # Standing on a chest under fire: take it now (one action), then the
        # usual rule (fight or leave). Stepping off first made the party walk
        # back in for it, again and again (user report 2026-11-21).
        if not on_ship and not self._chest_too_risky(party) and any(
            str(o.get("tile", "")).lower() == "chest" and (o.get("x"), o.get("y")) == pos
            for o in objects_on(party, gmap)
        ):
            return self._open_chest(state_machine, party, guarded=False)

        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        if on_ship:
            move = ship_escape(
                gmap,
                party,
                pos,
                th,
                lambda x, y: can_move_to(gmap, x, y, Transport.SHIP, party=party)
                or (has_key and self._is_locked_door(gmap, x, y)
                    and locked_door_passable(gmap, x, y, Transport.SHIP, party)),
                prefer_engage=not party_has_low_hp(party),
            )
        else:
            move = foot_escape(
                gmap,
                party,
                pos,
                th,
                lambda x, y: can_move_to(gmap, x, y, Transport.FOOT, party=party),
                prefer_engage=not party_has_low_hp(party) and not th.squid_engage,
                rank=self._capture_escape_rank(gmap, party, th),
            )
        if move.key == "attack" and move.direction is not None:
            return self._attack(state_machine, move.direction)
        if move.key == "fire" and move.direction is not None:
            self._key_queue.append(_DIR_TO_KEY[move.direction])
            return self._emit_key(state_machine, pygame.K_f, guarded=False)
        if move.key == "move" and move.direction is not None:
            d = move.direction
            nx, ny = (px + d.dx) % gmap.width, (py + d.dy) % gmap.height
            if has_key and self._is_locked_door(gmap, nx, ny):
                # Advancing through a door (Ambrosia's water door): unlock it.
                key_idx = next(
                    i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.keys > 0
                )
                self._queue_text(f"{key_idx}{d.name[0].lower()}", enter=False)
                return self._emit_key(state_machine, pygame.K_u, guarded=False)
            return self._emit_key(state_machine, _DIR_TO_KEY[d], guarded=False)
        return self._emit_key(state_machine, pygame.K_SPACE, guarded=False)

    def _outrun_or_engage(self, state_machine, screen, gmap, party, pos, th, dragon_lanes) -> int | None:
        """A dragon chasing a party that dodges its breath on foot (batch
        67c0de5 b6 seed 57: fled 13 tiles south with the dragon three
        behind, ~2,000 HP lost, wiped). LairWare's dragon moves as fast as
        the party, so the lane escape never gets out of range.

        1. A town or castle gate within _REFUGE_STEPS that the party reaches
           before any monster can engage: walk in (re-checked every turn).
           Inside, the usual town rules heal or rest. At most one refuge per
           _REFUGE_COOLDOWN turns, so the dragon waiting at the gate can't
           make the party bounce in and out.
        2. The escape has run _ESCAPE_CAP_TURNS turns with the dragon still
           in view and HP lower than at its start, or a refuge was just
           used and the dragon is still there: a party that can take the
           breath steps up to it and fights. Otherwise None (the old escape).
        Pirates are left to the lane escape: they can't leave the water, so
        walking inland does get out of range."""
        if party.transport != Transport.FOOT or not dragon_lanes:
            self._escape_log = None
            return None
        w, h = gmap.width, gmap.height
        chasing = [
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", ()) or ()
            if "x" in c and "y" in c and creature_name(c) == "dragon"
            and manhattan(w, h, pos, (c["x"], c["y"])) <= _CHASE_RADIUS
        ]
        dragons = [d for d in chasing if _cheb(w, h, pos, d) <= _SHOOT_VIEW]
        if not chasing:
            self._escape_log = None
            return None
        now = party.moves
        hp = sum(m.hp for m in party.members if not m.is_dead())
        log = self._escape_log
        if log is not None and now - log[2] > 2:
            log = None
        if log is None and th.unsafe_end(pos):
            log = [now, hp, now]
        if log is not None:
            log[2] = now
        self._escape_log = log

        # Chasing (within _CHASE_RADIUS) is enough: the dragon comes on
        # whatever the party does, and by the time it is in view the gate
        # is often cut off (seed 57: Britain was open at distance 8 and
        # closed at 5, the dragon at the castle wall beside both gates).
        if now >= self._refuge_until:
            route = self._refuge_route(screen, gmap, party, pos)
            if route is not None:
                if not route:
                    self._refuge_until = now + _REFUGE_COOLDOWN
                    self._escape_log = None
                    return self._emit_key(state_machine, pygame.K_e, guarded=False)
                nxt = route[0]
                d = next(
                    d for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST)
                    if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) == nxt
                )
                return self._emit_key(state_machine, _DIR_TO_KEY[d], guarded=False)

        failed = log is not None and now - log[0] >= _ESCAPE_CAP_TURNS and hp < log[1]
        refuge_spent = now < self._refuge_until
        if dragons and (failed or refuge_spent) and not party_has_low_hp(party) and self._can_take_broadsides(party):
            for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) in dragons:
                    return self._attack(state_machine, d)
            step = self._pirate_hunt_step(gmap, party, pos, th, pirates=dragons)
            if step is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[step], guarded=False)
        return None

    def _refuge_route(self, screen, gmap, party, pos) -> list[tuple[int, int]] | None:
        """The walk (tiles after ``pos``) to a town or castle gate within
        _REFUGE_STEPS on which no monster engages, with the fewest turns in
        a dragon's or pirate's line, or None. Monsters move by LairWare's
        MoveMonsters (UltimaMisc.c:1191-1236): engaged at distance 1, else
        the diagonal step toward the party, then the vertical, then the
        horizontal one; a first step onto the party engages. Each turn
        ending in a shooter's line counts as a hit, and every member must be
        able to take all of them at their worst."""
        w, h = gmap.width, gmap.height
        portals = getattr(gmap, "portals", ()) or ()
        goals = {
            (p.x, p.y) for p in portals
            if 1 <= p.dest_map_id <= 12 and p.dest_map_id not in _NO_REFUGE_MAPS
            and manhattan(w, h, pos, (p.x, p.y)) <= _REFUGE_STEPS
        }
        if not goals:
            return None
        if pos in goals:
            return []
        barred = {(p.x, p.y) for p in portals}
        terrain_ok = getattr(screen, "_lw_monster_terrain_ok", None)
        am = getattr(screen, "asset_mgr", None)
        mons: list[tuple[str, tuple[int, int]]] = []
        for c in getattr(screen, "creatures", ()) or ():
            if "x" not in c or "y" not in c:
                continue
            kind = creature_name(c)
            if kind == "whirlpool" or _cheb(w, h, pos, (c["x"], c["y"])) > _REFUGE_STEPS + 3:
                continue
            cr_def = am.get_creature(kind) if am is not None else None
            if cr_def is not None and cr_def.wontattack and not c.get("hunts"):
                continue
            mons.append((kind, (c["x"], c["y"])))

        def heading(delta: int, span: int) -> int:
            delta = ((delta + span // 2) % span) - span // 2
            return (delta > 0) - (delta < 0)

        def monsters_turn(ms, at):
            """LairWare's monster phase after the party steps onto ``at``:
            (new positions, turns in a line) or None when one engages."""
            out = list(ms)
            hits = 0
            for i, (kind, (cx, cy)) in enumerate(out):
                if manhattan(w, h, (cx, cy), at) <= 1:
                    return None
                dx, dy = heading(at[0] - cx, w), heading(at[1] - cy, h)
                if ((cx + dx) % w, (cy + dy) % h) == at:
                    return None
                others = {q for j, (_k, q) in enumerate(out) if j != i}
                for sx, sy in ((dx, dy), (0, dy), (dx, 0)):
                    if sx == 0 and sy == 0:
                        continue
                    t = ((cx + sx) % w, (cy + sy) % h)
                    if t == at or t in barred or t in others:
                        continue
                    if terrain_ok is not None and terrain_ok(kind, *t):
                        out[i] = (kind, t)
                        break
                if kind in ("dragon", "pirate") and at in lane_tiles_for(w, h, out[i][1], gmap):
                    hits += 1
            return out, hits

        living = [m for m in party.members if not m.is_dead()]
        min_hp = min((m.hp for m in living), default=0)
        best: tuple[tuple[int, int], list[tuple[int, int]]] | None = None

        def walk(cur, ms, path, hits):
            nonlocal best
            if best is not None and (hits, len(path)) >= best[0]:
                return
            if cur in goals:
                best = ((hits, len(path)), list(path))
                return
            left = _REFUGE_STEPS - len(path)
            for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                n = ((cur[0] + d.dx) % w, (cur[1] + d.dy) % h)
                if n == pos or n in path or any(q == n for _k, q in ms):
                    continue
                if min(manhattan(w, h, n, g) for g in goals) > left - 1:
                    continue
                if not can_move_to(gmap, n[0], n[1], Transport.FOOT, party=party):
                    continue
                turn = monsters_turn(ms, n)
                if turn is None:
                    continue
                if (hits + turn[1]) * _BROADSIDE_MAX >= min_hp:
                    continue
                path.append(n)
                walk(n, turn[0], path, hits + turn[1])
                path.pop()

        walk(pos, mons, [], 0)
        return best[1] if best is not None else None

    @staticmethod
    def _strong_vs_pirates(party) -> bool:
        """Healthy, unpoisoned and every living member at level 8+."""
        living = [m for m in party.members if not m.is_dead()]
        return (
            bool(living)
            and not party_has_low_hp(party)
            and all(m.status != Status.POISONED and m.level >= _PIRATE_HUNT_MIN_LEVEL for m in living)
        )

    def _pirate_hunt_step(
        self, gmap, party, pos, th, pirates=None, limit: int = _PIRATE_HUNT_RANGE
    ) -> Direction | None:
        """First step of the shortest land path (lanes allowed) to a tile
        orthogonally next to a pirate (of ``pirates``, default all), within
        ``limit`` steps."""
        w, h = gmap.width, gmap.height
        reach = self._foot_reachable(gmap, party, pos)
        engage = {
            ((p[0] + dx) % w, (p[1] + dy) % h)
            for p in (th.pirates if pirates is None else pirates)
            for dx, dy in _NEIGHBOURS4
        } & reach
        if not engage:
            return None
        seen = {pos}
        frontier: list[tuple[tuple[int, int], Direction | None]] = [(pos, None)]
        for _ in range(limit):
            if not frontier:
                break
            nxt = []
            for cur, first in frontier:
                for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                    n = ((cur[0] + d.dx) % w, (cur[1] + d.dy) % h)
                    if n in seen or n not in reach or n in th.pirates:
                        continue
                    step = first or d
                    if n in engage:
                        return step
                    seen.add(n)
                    nxt.append((n, step))
            frontier = nxt
        return None

    @staticmethod
    def _is_locked_door(gmap, x: int, y: int) -> bool:
        t = gmap.get_tile(x, y)
        return t is not None and str(getattr(t, "name", "")).lower() == "locked_door"

    def _attack(self, state_machine: StateMachine, d: Direction) -> int:
        self._queue_text(d.name[0].lower(), enter=False)
        return self._emit_key(state_machine, pygame.K_a, guarded=False)

    def _lane_guard(self, state_machine: StateMachine, key: int) -> int:
        """Last check before a move: never step into a lane / squid reach."""
        th = self._threats
        if th is None or key not in _KEY_TO_DIR:
            return key
        screen = state_machine.current_screen
        if type(screen).__name__ != "OverworldScreen" or screen.text_log.is_waiting_for_input:
            return key
        party = screen.party
        d = _KEY_TO_DIR[key]
        gmap = screen.game_map
        dest = ((party.x + d.dx) % gmap.width, (party.y + d.dy) % gmap.height)
        here = (party.x, party.y)
        w, h = gmap.width, gmap.height
        healthy = not party_has_low_hp(party)
        if dest in th.lanes:
            # User rule (2026-11-21): step into a lane only to keep advancing
            # on the pirate (fight and take its ship) with a party that can
            # take the fire; otherwise go somewhere else. Never wait.
            if healthy and all(
                manhattan(w, h, dest, p) < manhattan(w, h, here, p)
                for p in th.lane_pirates(dest)
            ):
                return key
            return self._blocked_elsewhere(dest)
        if dest in th.squid_engage:
            # User rule: fight the squid on foot when healthy (from a ship the
            # cannons deal with it); a hurt or poisoned party goes elsewhere.
            if healthy and party.transport != Transport.SHIP and all(
                m.status != Status.POISONED for m in party.members if not m.is_dead()
            ):
                return key
            return self._blocked_elsewhere(dest)
        return key

    def _blocked_elsewhere(self, tile: tuple[int, int]) -> int:
        """Refuse a threatened step: bar the tile for a while and re-plan
        around it (or toward another destination) from the next tick."""
        self._blocked_tiles[tile] = self._ow_turn + _BLOCK_TURNS
        self._trip = None
        return pygame.K_SPACE

    def _active_blocks(self) -> set[tuple[int, int]]:
        now = self._ow_turn
        for t in [t for t, until in self._blocked_tiles.items() if until < now]:
            del self._blocked_tiles[t]
        return set(self._blocked_tiles)

    def _monster_avoid(self, screen, party, px: int, py: int, goal: Goal, living) -> set[tuple[int, int]]:
        """Soft avoid tiles for path planning (hard threats come from _threats)."""
        gmap = screen.game_map
        cur_map_id = self._screen_map_id(screen, party)
        avoid: set[tuple[int, int]] = set()
        th = self._threats
        if th is not None:
            avoid |= th.hard_avoid()
        avoid |= self._active_blocks()
        creatures = getattr(screen, "creatures", []) or []
        if cur_map_id in _PIRATE_SEA_MAPS and party.transport == Transport.SHIP:
            avg_max_hp = sum(m.max_hp for m in living) // max(1, len(living)) if living else 0
            for c in creatures:
                tname = creature_name(c)
                if "x" not in c or "y" not in c:
                    continue
                cx, cy = c["x"], c["y"]
                if tname == "whirlpool":
                    if cur_map_id == 0 and goal != Goal.SAIL_WHIRLPOOL:
                        avoid.add((cx, cy))
                        for ox, oy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                            avoid.add(((cx + ox) % gmap.width, (cy + oy) % gmap.height))
                    continue
                if tname not in ("serpent", "squid"):
                    continue
                rad = 3 if (tname == "serpent" and avg_max_hp < 600) else 2
                for ox in range(-rad, rad + 1):
                    for oy in range(-rad, rad + 1):
                        if abs(ox) + abs(oy) <= rad:
                            avoid.add(((cx + ox) % gmap.width, (cy + oy) % gmap.height))
        elif cur_map_id in _PIRATE_SEA_MAPS and party.transport != Transport.SHIP and living:
            if th is not None:
                avoid |= th.squid_coast
            # Frigate tiles are for boarding (trip legs target them directly);
            # never walk across one as a shortcut.
            avoid |= {
                (obj.get("x"), obj.get("y"))
                for obj in objects_on(party, gmap)
                if str(obj.get("tile", "")).lower() == "frigate"
            }
            avg_max_hp = sum(m.max_hp for m in party.members) // max(1, len(party.members))
            broke_and_starving_nav = (
                party.gold < 30
                and any(m.food == 0 for m in living)
                and all(m.hp * 10 >= m.max_hp * 3 for m in living)
            )
            # User rule (2026-11-21, being chased): steer around land
            # monsters only while outrunning them to a town (_flee_plan);
            # otherwise meet them (no zig-zagging).
            avoid_all_land = self._fleeing and not broke_and_starving_nav
            for c in creatures:
                tname = creature_name(c)
                if "x" not in c or "y" not in c or tname in ("whirlpool", "pirate"):
                    continue
                is_sea = tname in SEA_MONSTERS
                if tname == "squid" and not avoid_all_land and th is not None and not th.squid_engage:
                    continue  # fighting squids on foot (see _threat_escape)
                if (is_sea and (avg_max_hp < 400 or avoid_all_land)) or (not is_sea and avoid_all_land):
                    cx, cy = c["x"], c["y"]
                    rad = 2 if (avoid_all_land and (is_sea or goal in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON))) else 1
                    for ox in range(-rad, rad + 1):
                        for oy in range(-rad, rad + 1):
                            if abs(ox) + abs(oy) <= rad:
                                avoid.add(((cx + ox) % gmap.width, (cy + oy) % gmap.height))
        # Never walk through the active moongate by accident.
        if cur_map_id == 0:
            phase = getattr(screen, "trammel_phase", None)
            for g in getattr(gmap, "moongates", ()) or ():
                if g.phase == phase:
                    avoid.add((g.x, g.y))
        return avoid

    def _step_overworld(self, state_machine: StateMachine, screen, party, px: int, py: int, goal: Goal) -> int | None:
        gmap = screen.game_map
        cur_map_id = self._screen_map_id(screen, party)
        living = [m for m in party.members if not m.is_dead()]

        # The whirlpool next to the ship the party left: board it again
        # before it sinks (batch 67c0de5 b5 seed 44 starved on a two-tile
        # island after it sank the ship parked two steps away).
        key = self._whirl_reboard(state_machine, screen, gmap, party, (px, py), cur_map_id)
        if key is not None:
            return key

        # A chest dropped ashore by a fight fought from the ship (user rule
        # 2026-11-23): leave the ship, step over, open it, board again, a few
        # turns for gold and maybe gear, unless sea monsters are about or a
        # badly hurt party is in no state to spend them. The trip owns the
        # X and the B; the chest code below opens it once underfoot.
        if (
            cur_map_id in _PIRATE_SEA_MAPS
            and party.transport == Transport.SHIP
            and not self._chest_too_risky(party)
            and not party_has_low_hp(party)
            and not (
                goal == Goal.CURE_POISON
                and any(m.status == Status.POISONED and m.hp <= 25 for m in living)
            )
            and not any(
                "x" in c and "y" in c and creature_name(c) in SEA_MONSTERS
                and manhattan(gmap.width, gmap.height, (px, py), (c["x"], c["y"])) <= _SHIP_CHEST_CLEAR
                for c in getattr(screen, "creatures", ()) or ()
            )
        ):
            ashore = {
                (obj.get("x"), obj.get("y"))
                for obj in objects_on(party, gmap)
                if str(obj.get("tile", "")).lower() == "chest"
                and manhattan(gmap.width, gmap.height, (px, py), (obj.get("x"), obj.get("y"))) <= 2
            }
            # Same limits as on foot, or it lands for a chest the foot code
            # then won't fetch, boards, and lands again.
            lanes = self._threats.hard_avoid() if self._threats is not None else set()
            ashore -= lanes | set(self._active_blocks())
            if ashore:
                key = self._trip_drive(
                    state_machine, screen, gmap, party, px, py, cur_map_id,
                    Destination(frozenset(ashore), Transport.FOOT, "chest"),
                )
                if key is not None and key is not _ARRIVED:
                    return key

        # Loot dropped chests on foot on Sosaria or Ambrosia (prefer APPAR_UNEM, else G with member 1)
        if (
            cur_map_id in _PIRATE_SEA_MAPS
            and party.transport == Transport.FOOT
            and not self._chest_too_risky(party)
        ):
            chests = {
                (obj.get("x"), obj.get("y"))
                for obj in objects_on(party, gmap)
                if str(obj.get("tile", "")).lower() == "chest"
            }
            # User rule 2026-11-23: a dropped chest is two moves; pick it up
            # unless spending them courts catastrophe. Errands (food,
            # resurrection, a cure) take it too; the exceptions are a
            # poisoned member a few HP from death on the way to the cure,
            # and a badly hurt party with monsters closing in (the flee
            # below gets the turn). Chests in a firing lane are already
            # unreachable (the walk avoids lanes), and a weak party with no
            # safe opener leaves them (_chest_too_risky, above).
            emergency = (
                goal == Goal.CURE_POISON
                and any(m.status == Status.POISONED and m.hp <= 25 for m in living)
            ) or (
                party_has_low_hp(party)
                and any(
                    "x" in c and "y" in c
                    and creature_name(c) not in SEA_MONSTERS and creature_name(c) != "whirlpool"
                    and manhattan(gmap.width, gmap.height, (px, py), (c["x"], c["y"])) <= _CHASE_RADIUS
                    for c in getattr(screen, "creatures", ()) or ()
                )
            )
            if (px, py) in chests and not emergency:
                return self._open_chest(state_machine, party)
            if chests and not emergency:
                # Hurt, only the chests a few steps off (a fight's own drop):
                # chests anywhere on the map came before resting, and a
                # level 9-16 party walked from one to the next, fighting
                # on the way, from full HP down to a wipe in ~5,000 steps
                # with 1,500 gold (user run 2026-11-23).
                max_chest_dist = (
                    None
                    if goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN, Goal.AMBROSIA_CARDS_SHRINES)
                    and not needs_heal(party)
                    else 4
                )
                # The detour limit is a WALK, not a straight line: a chest 4
                # tiles off but 10 to walk led away from the trip's next leg,
                # one step past 4 the trip led back, and so on (batch 8d3aef0
                # seed 111: ~11,000 steps between (15, 11) and (16, 11)).
                # Reachable means by the walk the move will take, with the
                # same avoid tiles: a chest inside a firing lane passed a
                # plain path check, the move couldn't route to it and fell
                # back east, from one tile west it could, and the party
                # paced (44..48, 20) for ~10,000 steps without a fight and
                # starved (batch 493f49a seed 164).
                avoid = self._monster_avoid(screen, party, px, py, goal, living)

                def _walk(pos):
                    if pos in avoid:
                        return None
                    _d, cost = find_2d_step_and_cost(
                        gmap, start=(px, py), goals={pos}, transport=Transport.FOOT, party=party,
                        avoid_tiles=avoid or None,
                    )
                    return cost

                reachable_chests = {
                    pos for pos in chests
                    if (
                        _walk(pos) is not None
                        if max_chest_dist is None
                        else abs(pos[0] - px) + abs(pos[1] - py) <= max_chest_dist
                        and (_walk(pos) or 10_000) <= max_chest_dist
                    )
                }
                if reachable_chests:
                    # Head for ONE chest until it's taken or out of reach:
                    # aiming at the set, two chests ~30 tiles off either way
                    # traded "nearest" with every step and the party paced
                    # between them for ~10,000 steps, unfed, until it starved
                    # (batch 493f49a seed 164; seed 142 ~3,000 steps).
                    target = self._chest_target
                    if target not in reachable_chests:
                        costs = {c: _walk(c) for c in reachable_chests}
                        target = min(reachable_chests, key=lambda c: (costs[c] is None, costs[c] or 0, c))
                        self._chest_target = target
                    self._overworld_avoid = avoid
                    return self._move_toward(state_machine, gmap, party, (px, py), {target})

        gear_key = self._maybe_manage_gear(
            state_machine, party, prefer_ranged=prefer_ranged_weapons(party)
        )
        if gear_key is not None:
            return gear_key

        self._overworld_avoid = self._monster_avoid(screen, party, px, py, goal, living)

        # Ship broadsides at sea monsters in line (pirates are handled by the
        # lane rule: escape at 2-3, attack at 1). Squids are cannon targets
        # until the party can cure their poison (ALCORT).
        if cur_map_id in _PIRATE_SEA_MAPS and party.transport == Transport.SHIP:
            # LairWare Fire: any of the four directions, three tiles, wrapping.
            w, h = gmap.width, gmap.height
            for c in getattr(screen, "creatures", []):
                tname = creature_name(c)
                if tname not in _CANNON_TARGETS or "x" not in c or "y" not in c:
                    continue
                dx = (c["x"] - px + w // 2) % w - w // 2
                dy = (c["y"] - py + h // 2) % h - h // 2
                if getattr(self, "_last_cannon_state", None) == (px, py, party.moves):
                    break
                if dy == 0 and 1 <= abs(dx) <= 3:
                    self._last_cannon_state = (px, py, party.moves)
                    self._key_queue.append(pygame.K_RIGHT if dx > 0 else pygame.K_LEFT)
                    return self._emit_key(state_machine, pygame.K_f)
                if dx == 0 and 1 <= abs(dy) <= 3:
                    self._last_cannon_state = (px, py, party.moves)
                    self._key_queue.append(pygame.K_DOWN if dy > 0 else pygame.K_UP)
                    return self._emit_key(state_machine, pygame.K_f)

        # Broke (< 30 gold) and starving: earn food money from land monsters
        # before any trip (no food can be bought until then).
        if party.transport != Transport.SHIP and self._broke_and_starving(screen, gmap, party, px, py, living):
            prey = {
                (c["x"], c["y"])
                for c in getattr(screen, "creatures", ())
                if "x" in c and "y" in c
                and creature_name(c) not in SEA_MONSTERS and creature_name(c) != "whirlpool"
                and manhattan(gmap.width, gmap.height, (px, py), (c["x"], c["y"])) <= 12
            }
            if prey:
                d = find_2d_step(gmap, (px, py), prey, Transport.FOOT, party=party, avoid_tiles=self._overworld_avoid)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        self._fleeing = False
        if cur_map_id == _MAP_SOSARIA and party.transport != Transport.SHIP:
            flee_key = self._flee_plan(state_machine, screen, gmap, party, px, py, living, cur_map_id)
            if flee_key is not None:
                return flee_key

        if cur_map_id == _MAP_SOSARIA and needs_heal(party):
            rest_key = self._evade_or_rest(state_machine, screen, gmap, party, px, py, goal, living, cur_map_id)
            if rest_key is _REST_INDOORS:
                dest, on_arrive = self._rest_destination(state_machine, screen, gmap)
                if dest is not None:
                    key = self._trip_drive(state_machine, screen, gmap, party, px, py, cur_map_id, dest)
                    if key is _ARRIVED:
                        return on_arrive()
                    if key is not None:
                        return key
            elif rest_key is not None:
                return rest_key

        # Dawn opportunistically (user rule 2026-11-21): open right now, the
        # party is a few steps from it on foot, and it sells an upgrade we
        # can afford -> pop in. Never wait for it.
        if (
            cur_map_id == _MAP_SOSARIA
            and party.transport != Transport.SHIP
            and self._dawn_open(screen)
            and manhattan(gmap.width, gmap.height, (px, py), _DAWN_PORTAL) <= 3
            and goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON)
        ):
            up = best_shop_upgrade(party, include_dawn=True)
            if up is not None and up.dawn_only:
                if (px, py) == _DAWN_PORTAL:
                    return self._emit_key(state_machine, pygame.K_e)
                return self._move_toward(state_machine, gmap, party, (px, py), {_DAWN_PORTAL})

        # Item 5: never walk into a mark dungeon under the bar for its
        # first level down (it would turn straight back): rest indoors
        # first when that heals the party.
        if (
            cur_map_id == _MAP_SOSARIA
            and goal in (Goal.GET_MARK_KINGS, Goal.GET_REMAINING_MARKS)
            and any(m.hp < dungeon_hp_need(m, 1) for m in living)
            and self._can_rest_indoors(party, goal)
        ):
            dest, on_arrive = self._rest_destination(state_machine, screen, gmap)
            if dest is not None:
                key = self._trip_drive(state_machine, screen, gmap, party, px, py, cur_map_id, dest)
                if key is _ARRIVED:
                    return on_arrive()
                if key is not None:
                    return key

        dest, on_arrive = self._destination_for(state_machine, screen, gmap, party, px, py, goal, living, cur_map_id)
        if dest is not None:
            key = self._trip_drive(state_machine, screen, gmap, party, px, py, cur_map_id, dest)
            if key is _ARRIVED:
                if on_arrive is not None:
                    return on_arrive()
            elif key is not None:
                return key

        return self._grind_local(state_machine, screen, gmap, party, px, py, living)

    def _evade_or_rest(self, state_machine, screen, gmap, party, px, py, goal, living, cur_map_id) -> int | None:
        # Emergency step away only when a monster is within 1 tile (radius 2-3 is routed around via _overworld_avoid)
        # On foot a step away from an adjacent monster only delays the fight
        # (user rule: outrun it to a town, or fight it); ships still sheer off.
        evade_rad = 3 if party.transport == Transport.SHIP else -1
        # A ship sheers off only from what can follow it on the water: land
        # monsters ashore can't, and dodging them sent a level-25 party back
        # and forth off the coast for ~4,600 steps, food running out
        # (batch db59b20 seed 145, starved with 5,781 gold).
        on_ship = party.transport == Transport.SHIP
        nearby = [
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", [])
            if "x" in c and "y" in c
            and creature_name(c) != "whirlpool"
            and (not on_ship or creature_name(c) in SEA_MONSTERS)
            and manhattan(gmap.width, gmap.height, (c["x"], c["y"]), (px, py)) <= evade_rad
        ]
        if nearby:
            wind = getattr(party, "wind_direction", None)
            if party.transport == Transport.SHIP and wind is None:
                return self._emit_key(state_machine, pygame.K_SPACE)
            blocked_dir = headwind(wind) if party.transport == Transport.SHIP else None
            best_dir = None
            best_dist = -1
            for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                if d == blocked_dir:
                    continue
                nx, ny = (px + d.dx) % gmap.width, (py + d.dy) % gmap.height
                if not can_move_to(gmap, nx, ny, transport=party.transport, party=party):
                    continue
                if self._threats is not None and self._threats.unsafe_end((nx, ny)):
                    continue
                min_d = min(manhattan(gmap.width, gmap.height, (nx, ny), c) for c in nearby)
                if min_d > best_dist:
                    best_dist = min_d
                    best_dir = d
            if best_dir is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[best_dir])
        threat_near = any(
            "x" in c and "y" in c and creature_name(c) != "whirlpool" and max(
                abs(wrap_delta(px, c["x"], gmap.width)),
                abs(wrap_delta(py, c["y"], gmap.height)),
            ) <= 7
            for c in getattr(screen, "creatures", [])
        )
        cur_hp_sum = sum(m.hp for m in living)
        prev_ow = getattr(self, "_prev_ow_hp_state", None)
        took_hit_here = (
            prev_ow is not None
            and prev_ow[0] == cur_map_id
            and prev_ow[1] == px
            and prev_ow[2] == py
            and cur_hp_sum < prev_ow[3]
        )
        self._prev_ow_hp_state = (cur_map_id, px, py, cur_hp_sum)
        # Rest-guard stack (precedence):
        # 1. Evade nearby creatures before resting (above); lanes are escaped in _step_2d.
        # 2. Never pass turns when threat_near (<=7) or after taking damage on this tile.
        # 3. Never pass turns while starving (food == 0 / <100) or in town/urgent goals, or above 70% HP.
        if (
            not threat_near
            and not took_hit_here
            and party.food >= 100
            and not any(m.food == 0 for m in living)
            and any(not m.is_dead() and m.max_hp > 0 and m.hp * 10 < m.max_hp * 7 for m in living)
            and goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON)
            and self._can_rest_indoors(party, goal)
        ):
            # User rule (2026-11-21): pass time only inside a town or castle
            # (_step_town rests there under the same conditions).
            return _REST_INDOORS
        return None

    _town_heal_visit: int | None = None

    def _town_heal_due(self, screen, party) -> bool:
        """Rest or heal in a town or castle (user ruling 2026-11-25): start
        when a living member is under 70% of max HP (``TOWN_REST_BELOW_PCT``,
        the surface rest line), then go on until all are at 85% again
        (``needs_heal``), for the rest of this visit. Lord British adds 100
        max HP a level and heals nothing (LairWare Transact), so at 85% a
        level-up alone kept the party passing or casting beside him for up
        to ~550 turns a visit (trace_20261125-184644). Poison still counts
        (``needs_heal``'s poison clause)."""
        visit = id(screen)
        if needs_heal(party, TOWN_REST_BELOW_PCT):
            self._town_heal_visit = visit
            return True
        if self._town_heal_visit == visit and needs_heal(party):
            return True
        self._town_heal_visit = None
        return False

    @staticmethod
    def _can_rest_indoors(party, goal: Goal) -> bool:
        """Would a town or castle actually heal the party? The same test the
        town handler uses to rest there: fed, not on an urgent errand, no
        member about to die of poison, and a healer who can cast."""
        living = [m for m in party.members if not m.is_dead()]
        return (
            party.food >= 100
            and not any(m.food == 0 for m in living)
            and goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON)
            and not any(m.status == Status.POISONED and m.hp <= 25 for m in living)
            and any(
                m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
                and m.max_mp >= 10
                for m in living
            )
            # Poison drains HP every turn: resting only helps if it ends with
            # ALCORT (a Cleric/Druid whose MP pool reaches 35). Otherwise heal
            # spells never keep up (user report 2026-11-21): go earn the
            # healer's 100 gold instead.
            and (
                not any(m.status == Status.POISONED for m in living)
                or any(
                    m.profession in (Profession.CLERIC, Profession.DRUID) and m.max_mp >= 35
                    for m in living
                )
            )
        )

    def _flee_plan(self, state_machine, screen, gmap, party, px, py, living, cur_map_id) -> int | None:
        """Being chased (user rule 2026-11-21).

        If the fight looks deadly and the party can outrun its chasers to a
        town or castle (our route there is shorter than any chaser's distance
        to it), go there and heal; the chasers are fought on the way out.
        Otherwise return None: the party meets them (no dodging)."""
        w, h = gmap.width, gmap.height
        chasers = [
            (c["x"], c["y"], creature_name(c))
            for c in getattr(screen, "creatures", ()) or ()
            if "x" in c and "y" in c
            and creature_name(c) not in SEA_MONSTERS and creature_name(c) != "whirlpool"
            and manhattan(w, h, (px, py), (c["x"], c["y"])) <= _CHASE_RADIUS
        ]
        if not chasers or not living:
            return None
        hp = sum(m.hp for m in living)
        max_hp = sum(m.max_hp for m in living) or 1
        # Deadly = already badly hurt. (No "dragons are scary" clause: a
        # healthy party fights them; user ruling 2026-11-21.)
        deadly = hp * 2 < max_hp or any(m.hp * 10 < m.max_hp * 3 for m in living)
        if not deadly:
            return None
        # A town only helps if the party can rest there; otherwise running in
        # and straight back out is the worst of both (user report 2026-11-21).
        # (A healthy party chased by dragons gains nothing indoors either:
        # they wait outside. User report: in and out of Yew, dragons outside.)
        goal = evaluate_goal(party, cur_map_id)
        if not needs_heal(party) or not self._can_rest_indoors(party, goal):
            return None
        dest, on_arrive = self._rest_destination(state_machine, screen, gmap)
        if dest is None:
            return None
        if self._trip is None or self._trip.dest.label != "rest":
            self._replan(gmap, party, screen, cur_map_id, (px, py), party.transport, dest)
        plan = self._trip
        if plan is None or not plan.path:
            return None
        portal = (plan.path[-1][0], plan.path[-1][1])
        # Rest there only if the party will still want to once inside: the
        # goal can differ by map (batch 1c7525f seed 38: near the Exotic dig
        # site the food check waits, inside town 12 it fires, BUY_FOOD walks
        # out, and in and out for 3,600 steps until the party starved).
        dest_map = next(
            (p.dest_map_id for p in getattr(gmap, "portals", ()) if (p.x, p.y) == portal), None
        )
        if dest_map is not None and not self._can_rest_indoors(party, evaluate_goal(party, dest_map)):
            self._trip = None
            return None
        ours = len(plan.path) - 1
        if any(manhattan(w, h, (cx, cy), portal) <= ours for cx, cy, _ in chasers):
            self._trip = None
            return None  # cannot outrun them: fight
        self._fleeing = True
        self._overworld_avoid = self._monster_avoid(screen, party, px, py, Goal.GRIND_AND_LEVEL, living)
        key = self._trip_drive(state_machine, screen, gmap, party, px, py, cur_map_id, dest)
        if key is _ARRIVED:
            return on_arrive()
        return key

    def _rest_destination(self, state_machine, screen, gmap):
        """The towns and castles of this map that are safe to rest in."""
        portals = {
            (p.x, p.y)
            for p in getattr(gmap, "portals", ())
            if 1 <= p.dest_map_id <= 12
            and p.dest_map_id not in _UNSAFE_REST_TOWN_MAPS
            and p.dest_map_id != 11  # Dawn: rarely open
        }
        if not portals:
            return None, None
        return self._portal_dest(state_machine, screen, portals, "rest")

    # -- destinations ---------------------------------------------------

    def _wants_death_gulch(self, party, living, cur_map_id: int, goal: Goal) -> bool:
        return (
            cur_map_id == 0
            and goal == Goal.GRIND_AND_LEVEL
            and not any(self._can_level_at_british(m) for m in living)
            and all(
                (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
                and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
                for m in party.members
            )
            and all(m.marks[i] > 0 for m in living for i in (1, 2, 3))
            and len(living) == len(party.members)
            # Raid until the Ambrosia trip is paid for and beyond: stopping
            # at 4500 left parties short of 4500 + food + keys, grinding
            # slowly (user ruling 2026-11-22: amass more gold first). The
            # 400 floor is the guards' bribes (user 2026-11-22): a raid
            # needs keys AND gold.
            and DEATH_GULCH_BRIBE_GOLD <= party.gold < raid_gold_target(party, _DEATH_GULCH_GOLD_CAP)
            # Never raid for gold nothing will spend (user ruling 2026-11-22).
            and gold_has_a_use(party)
            and sum(m.keys for m in living) >= DEATH_GULCH_KEYS
        )

    def _portal_dest(self, state_machine, screen, portals, label: str):
        """A portal Destination; arriving enters it (waiting for Dawn's double new moon)."""

        def _enter() -> int:
            party = screen.party
            if (party.x, party.y) == _DAWN_PORTAL and not self._dawn_open(screen):
                return self._emit_key(state_machine, pygame.K_SPACE)
            if label == "death_gulch":
                # Fill the APPAR UNEM caster at the gate: MP comes back +1 a
                # turn out here, +1 every 4 inside, where a raid otherwise
                # waits for it (user 2026-11-22: the standing still on
                # raids is MP; entering with 1-8 MP was common). Re-entry
                # costs bribes and keys, so this is the free refill point.
                caster = self._mana_caster(party)
                if caster is not None and caster.mp < caster.max_mp:
                    return self._emit_key(state_machine, pygame.K_SPACE)
            if label == "exodus":
                key = self._ready_for_exodus(state_machine, party)
                if key is not None:
                    return key
            return self._emit_key(state_machine, pygame.K_e)

        return Destination(frozenset(portals), Transport.FOOT, label), _enter

    def _ready_for_exodus(self, state_machine, party) -> int | None:
        """At Castle Exodus's gate: everyone to full HP (heal spells while a
        healer has the MP), then pass turns until every caster's MP is full,
        then go in (user 2026-11-23). Nothing rests inside the castle, so
        this is the last refill before the final fight."""
        living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
        hurt = [(i, m) for i, m in living if m.hp < m.max_hp]
        if hurt:
            healer = next(
                (
                    i for i, m in living
                    if m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
                    and m.mp >= 10
                ),
                None,
            )
            if healer is not None:
                patient = min(hurt, key=lambda im: im[1].hp / max(1, im[1].max_hp))[0]
                self._queue_text(self._cleric_cast(party, healer, f"c{patient}"), enter=False)
                return self._emit_key(state_machine, pygame.K_c)
            return self._emit_key(state_machine, pygame.K_SPACE)
        if any(m.mp < m.max_mp for _, m in living):
            return self._emit_key(state_machine, pygame.K_SPACE)
        return None

    @staticmethod
    def _dawn_open(screen) -> bool:
        return getattr(screen, "trammel_phase", 0) == 0 and getattr(screen, "felucca_phase", 0) == 0

    def _mainland(self, gmap, party) -> frozenset[tuple[int, int]]:
        terr = terrain_for(gmap, party, 0)
        cache = getattr(self, "_mainland_cache", None)
        if cache is not None and cache[0] is terr:
            return cache[1]
        seen = {_BRITAIN_PORTAL}
        q = deque([_BRITAIN_PORTAL])
        while q:
            cx, cy = q.popleft()
            for n in terr.neighbours(cx, cy):
                if n not in seen and n in terr.foot:
                    seen.add(n)
                    q.append(n)
        result = frozenset(seen)
        self._mainland_cache = (terr, result)
        return result

    def _destination_for(self, state_machine, screen, gmap, party, px, py, goal, living, cur_map_id):
        """Name where the goal wants the party (and what to do on arrival)."""
        sm = state_machine

        if goal == Goal.DIG_EXOTICS:
            target = self._dig_target(gmap, party, px, py)
            if target is None:
                return None, None
            tx, ty, m_idx = target

            def _dig() -> int:
                self._queue_text("DIG", enter=True)
                self._queue_text(str(m_idx), enter=False)
                return self._emit_key(sm, pygame.K_o)

            return Destination(frozenset({(tx, ty)}), Transport.FOOT, f"dig{tx},{ty}"), _dig

        if goal == Goal.CONQUER_EXODUS:
            snake_tile = gmap.get_tile(10, 58)
            snake_active = snake_tile is not None and str(getattr(snake_tile, "name", "")).startswith("snake")
            # LairWare's EVOCARE carries the party three rows past the serpent,
            # which stays (UltimaMain.c:2569-2590): once inside Exodus's
            # enclosure (x 7-13, y 51-56) head for the castle.
            past_snake = 7 <= px <= 13 and 51 <= py <= 56
            if snake_active and cur_map_id == 0 and not past_snake:
                def _evocare() -> int:
                    snake_idx = next(
                        (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.marks[2] > 0),
                        1,
                    )
                    self._queue_text(str(snake_idx), enter=False)
                    self._queue_text("EVOCARE", enter=True)
                    return self._emit_key(sm, pygame.K_y)

                return Destination(frozenset({(10, 59)}), Transport.SHIP, "snake"), _evocare
            return self._portal_dest(sm, screen, {(10, 53)}, "exodus")

        if goal == Goal.AMBROSIA_CARDS_SHRINES:
            return self._ambrosia_destination(sm, party, px, py, living)

        if goal == Goal.EXIT_AMBROSIA:
            return (
                Destination(frozenset({_AMBROSIA_EXIT}), Transport.SHIP, "exit_ambrosia"),
                lambda: self._emit_key(sm, pygame.K_SPACE),
            )

        if goal == Goal.SAIL_WHIRLPOOL:
            whirlpools = frozenset(
                (c["x"], c["y"])
                for c in getattr(screen, "creatures", ())
                if creature_name(c) == "whirlpool" and "x" in c and "y" in c
            )
            if whirlpools:
                self._whirl_missing = False
                return (
                    Destination(whirlpools, Transport.SHIP, "whirlpool", moving=True),
                    lambda: self._emit_key(sm, pygame.K_SPACE),
                )
            # LairWare's whirlpool can't be removed (WhirlX/WhirlY sit outside
            # Monsters[]), and the creature list is read afresh every tick.
            # Should it be missing anyway, say so once and try the guessed
            # spots in turn, moving on from each one reached: never pass on
            # a guess (trace_20261125-184644 sat at Java's (17, 48) for
            # ~11,000 steps).
            if not getattr(self, "_whirl_missing", False):
                self._whirl_missing = True
                _log.warning("autoplay: no whirlpool on Sosaria; trying guessed spots")
            guess = _WHIRLPOOL_GUESSES[self._whirl_guess % len(_WHIRLPOOL_GUESSES)]

            def _next_guess() -> int:
                self._whirl_guess += 1
                return self._emit_key(sm, pygame.K_SPACE)

            return (
                Destination(frozenset({guess}), Transport.SHIP, f"whirlpool?{guess[0]},{guess[1]}"),
                _next_guess,
            )

        if goal == Goal.GET_MARK_KINGS:
            return self._portal_dest(sm, screen, {(46, 7)}, "dungeon_kings")

        if goal == Goal.GET_REMAINING_MARKS:
            # User ruling 2026-11-25: Fire and Force together in the Fires
            # of Hell, then Snake (planner.next_mark_dungeon).
            if next_mark_dungeon(party) == 19:
                return self._portal_dest(sm, screen, {(58, 44)}, "dungeon_snake")
            return self._portal_dest(sm, screen, {(49, 34)}, "dungeon_fire_force")

        if goal == Goal.BUY_FOOD:
            dawn = self._dawn_open(screen)
            portals = {
                (i[0], i[1]) for mid, i in _FOOD_TOWNS.items()
                if (mid != 11 or dawn) and mid != _MAP_DEATH_GULCH
            }
            if (
                cur_map_id == 0
                and self._can_shop_death_gulch(party)
                and self._on_death_gulch_strip(gmap, party, (px, py))
            ):
                portals = {_DEATH_GULCH_PORTAL}
            return self._portal_dest(sm, screen, portals, "food" + ("+dawn" if dawn else ""))

        if goal in (Goal.RESURRECT_DEAD, Goal.CURE_POISON):
            dawn = self._dawn_open(screen)
            portals = {(i[0], i[1]) for mid, i in _HEALER_TOWNS.items() if mid != 11 or dawn}
            return self._portal_dest(sm, screen, portals, "healer" + ("+dawn" if dawn else ""))

        if goal in (Goal.BUY_KEYS, Goal.BUY_TORCHES):
            dawn = self._dawn_open(screen)
            return self._portal_dest(
                sm, screen, {(i[0], i[1]) for mid, i in _GUILD_TOWNS.items() if mid != 11 or dawn}, "guild"
            )

        if goal == Goal.OUTFIT_BRITAIN:
            return self._portal_dest(
                sm, screen, {(i[0], i[1]) for mid, i in _SHOP_TOWNS.items() if mid != 11}, "shop"
            )

        # GRIND_AND_LEVEL (and any legacy goal): level up, Death Gulch, or the mainland.
        if cur_map_id != 0:
            return None, None
        if any(self._can_level_at_british(m) for m in living):
            return self._portal_dest(sm, screen, {_CASTLE_BRITISH}, "lord_british")
        if self._wants_death_gulch(party, living, cur_map_id, goal):
            return self._portal_dest(sm, screen, {(56, 31)}, "death_gulch")
        return Destination(self._mainland(gmap, party), Transport.FOOT, "mainland"), None

    def _dig_target(self, gmap, party, px, py) -> tuple[int, int, int] | None:
        need_wpn_idx = next(
            (
                i + 1
                for i, m in enumerate(party.members)
                if not m.is_dead() and m.weapon != WeaponType.EXOTIC and m.weapons.get(WeaponType.EXOTIC, 0) == 0
            ),
            None,
        )
        need_arm_idx = next(
            (
                i + 1
                for i, m in enumerate(party.members)
                if not m.is_dead() and m.armor != ArmorType.EXOTIC and m.armors.get(ArmorType.EXOTIC, 0) == 0
            ),
            None,
        )
        if need_wpn_idx is not None and need_arm_idx is not None:
            arm_d = manhattan(gmap.width, gmap.height, (px, py), _EXOTIC_ARMOR_SITE)
            wpn_d = manhattan(gmap.width, gmap.height, (px, py), _EXOTIC_WEAPON_SITE)
            if arm_d <= wpn_d:
                return (*_EXOTIC_ARMOR_SITE, need_arm_idx)
            return (*_EXOTIC_WEAPON_SITE, need_wpn_idx)
        if need_arm_idx is not None:
            return (*_EXOTIC_ARMOR_SITE, need_arm_idx)
        if need_wpn_idx is not None:
            return (*_EXOTIC_WEAPON_SITE, need_wpn_idx)
        return None

    def _ambrosia_destination(self, sm, party, px, py, living):
        """ALCORT wisdom first (it is why the trip is cheap to start), then
        the cards, then planner.SHRINE_PLAN in order with whatever gold is
        left above the reserve."""
        goal = next_shrine_goal(party)
        can_pay = party.gold >= SHRINE_RESERVE + 100
        if goal is not None and can_pay and goal[1] == "wisdom" and alcort_wisdom_gap(party):
            return self._shrine_dest(sm, party, goal)
        uncollected = [
            (tx, ty, card_idx)
            for tx, ty, card_idx in _AMBROSIA_CARD_SITES
            if not any(m.cards[card_idx] > 0 for m in living)
        ]
        living_idx = next((i + 1 for i, m in enumerate(party.members) if not m.is_dead()), 1)
        if uncollected:
            def _search() -> int:
                # LairWare's card search is the Other word SEARCH
                # (UltimaMisc.c:2445-2453); S is Steal (ledger C-23).
                self._queue_text("SEARCH", enter=True)
                self._queue_text(str(living_idx), enter=False)
                return self._emit_key(sm, pygame.K_o)

            return (
                Destination(frozenset((tx, ty) for tx, ty, _ in uncollected), Transport.FOOT, "cards"),
                _search,
            )

        if goal is None or not can_pay:
            return (
                Destination(frozenset({_AMBROSIA_EXIT}), Transport.SHIP, "exit_ambrosia"),
                lambda: self._emit_key(sm, pygame.K_SPACE),
            )
        return self._shrine_dest(sm, party, goal)

    _SHRINE_SITES = {
        "wisdom": (55, 27),
        "intelligence": (6, 6),
        "strength": (4, 36),
        "dexterity": (45, 52),
    }

    def _shrine_dest(self, sm, party, goal):
        """Walk to the shrine for ``goal``; on arrival pool gold on the
        member (J) when they cannot pay a point, then enter (E)."""
        m_idx = goal[0] + 1
        sx, sy = self._SHRINE_SITES[goal[1]]

        def _shrine() -> int:
            if party.members[m_idx - 1].gold < 100 and party.gold >= 100:
                self._join_gold_member_idx = m_idx
                return self._emit_key(sm, pygame.K_j)
            return self._emit_key(sm, pygame.K_e)

        return Destination(frozenset({(sx, sy)}), Transport.FOOT, f"shrine{sx},{sy}"), _shrine

    # -- trip follower: the ONLY place that emits B or X -----------------

    def _frigate_costs(self, party, screen) -> dict[tuple[int, int], float]:
        return {
            (obj.get("x"), obj.get("y")): 0.0
            for obj in objects_on(party, getattr(screen, "game_map", None))
            if str(obj.get("tile", "")).lower() == "frigate"
        }

    def _replan(self, gmap, party, screen, map_id, pos, mode, dest) -> TripPlan | None:
        frig = self._frigate_costs(party, screen)
        danger: dict[tuple[int, int], float] = {}
        th = self._threats
        if th is not None:
            for t in th.squid_coast:
                danger[t] = _DANGER_SQUID_COAST
            for t in th.lanes:
                danger[t] = _DANGER_HARD
            for t in th.squid_engage:
                danger[t] = _DANGER_HARD
        for t in self._active_blocks():
            danger[t] = float("inf")
        plan = plan_trip(
            gmap,
            party,
            map_id,
            pos,
            mode,
            dest,
            frig,
            pirates=frozenset(th.pirates) if th is not None else frozenset(),
            pirates_spawn=(map_id == 0),
            last_transition=self._last_transition,
            turn=self._ow_turn,
            danger=danger,
        )
        self._trip = plan
        self._trip_frigates = frozenset(frig)
        self._trip_planned_at = self._ow_turn
        self._trip_stuck = 0
        if self.tracer is not None and hasattr(self.tracer, "note"):
            self.tracer.note(
                "trip",
                None if plan is None else {
                    "dest": dest.label,
                    "cost": round(plan.cost, 1),
                    "legs": [(leg.mode.name, leg.end, leg.action) for leg in plan.legs],
                },
            )
        return plan

    @staticmethod
    def _next_path_tile(plan, pos) -> tuple[int, int] | None:
        """The tile after ``pos`` on the plan's path, else the first leg's end."""
        path = [(x, y) for x, y, _m in (plan.path or ())]
        for i, t in enumerate(path[:-1]):
            if t == pos:
                for n in path[i + 1:]:
                    if n != pos:
                        return n
        end = plan.legs[0].end
        return end if end != pos else None

    def _trip_drive(self, state_machine, screen, gmap, party, px, py, map_id, dest):
        """Advance the committed trip toward ``dest``. Returns a key, _ARRIVED or None (no route)."""
        self._ow_turn += 1
        pos = (px, py)
        mode = Transport.SHIP if party.transport == Transport.SHIP else Transport.FOOT
        if pos == self._trip_last_pos:
            self._trip_stuck += 1
            self._trip_still += 1
        else:
            self._trip_stuck = 0
            self._trip_still = 0
        self._trip_last_pos = pos

        plan = self._trip
        # A finished gate hop: we stand on the destination site.
        if plan is not None and plan.legs and plan.legs[0].action == "GATE":
            gates = getattr(gmap, "moongates", ()) or ()
            gd = plan.legs[0].gate_dest
            if gd is not None and gd < len(gates) and pos == (gates[gd].x, gates[gd].y):
                plan.legs.pop(0)
                self._trip_stuck = 0
                self._gate_wait = None
        frig_sig = frozenset(self._frigate_costs(party, screen))
        waiting = plan is not None and plan.legs and plan.legs[0].action in ("GATE", "CAPTURE") and pos == plan.legs[0].end
        # A gate leg never stands on its site (4b7046c): it waits beside it
        # or roams within _GATE_ROAM_RADIUS, and its own bound is
        # _GATE_LEG_MAX_TURNS. Barring tiles there after _TRIP_STILL_TURNS
        # barred the site itself every 60 turns (review of 4458b6f: the
        # 3-tile east strip by Castle Exodus, phase 18 reached food 0).
        if (
            not waiting and plan is not None and plan.legs and plan.legs[0].action == "GATE"
            and plan.legs[0].gate_src is not None
        ):
            gates = getattr(gmap, "moongates", ()) or ()
            src = plan.legs[0].gate_src
            if src < len(gates):
                waiting = manhattan(
                    gmap.width, gmap.height, pos, (gates[src].x, gates[src].y)
                ) <= _GATE_ROAM_RADIUS
        # No-progress guard. _trip_stuck drives the replan at
        # _TRIP_STUCK_TURNS and is reset by every replan; _trip_still only
        # by a change of tile. A replan that gives the same plan again means
        # a step the plan relies on is refused (a parked frigate on the
        # landing tile, live trace 2026-11-25, trace_20261125-180541,
        # ~3,200 turns). At _TRIP_STILL_TURNS on one tile the next tile of
        # the planned path is barred for _BLOCK_TURNS and the trip replans
        # around it. A destination tile is never barred (that would leave
        # the goal unreachable): the trip only replans, and the blocked
        # tile's neighbours stay open as other ways in.
        if (
            plan is not None
            and plan.legs
            and not waiting
            and self._trip_still >= _TRIP_STILL_TURNS
        ):
            nxt = self._next_path_tile(plan, pos)
            if nxt is not None and nxt not in dest.tiles:
                self._blocked_tiles[nxt] = self._ow_turn + _BLOCK_TURNS
            self._trip_still = 0
            plan = self._trip = None
        if (
            plan is None
            or plan.map_id != map_id
            or not plan.legs
            or plan.dest.label != dest.label
            or plan.dest.need != dest.need
            or (not dest.moving and plan.dest.tiles != dest.tiles)
            or plan.legs[0].mode != mode
            or frig_sig != self._trip_frigates
            or self._ow_turn - self._trip_planned_at > _TRIP_REPLAN_TURNS
            or (self._trip_stuck >= _TRIP_STUCK_TURNS and not waiting)
            or self._off_route(plan, pos, gmap)
        ):
            plan = self._replan(gmap, party, screen, map_id, pos, mode, dest)
        if plan is None or not plan.legs:
            return None

        leg = plan.legs[0]
        if leg.action != "GATE":
            self._gate_wait = None
        if leg.action == "ARRIVE":
            if pos in dest.tiles and (dest.need is None or dest.need == mode):
                self._wind_commit = None  # a headwind commitment ends on arrival
                return _ARRIVED
            # Head for the tile the plan chose; only drifting targets
            # (whirlpools) are re-read every tick.
            target = set(dest.tiles) if dest.moving else {leg.end}
            near = self._last_steps_into_town(gmap, party, pos, target)
            if near:
                saved = self._overworld_avoid
                self._overworld_avoid = set(saved or ()) - near
                try:
                    return self._move_toward(state_machine, gmap, party, pos, target)
                finally:
                    self._overworld_avoid = saved
            return self._move_toward(state_machine, gmap, party, pos, target)

        if leg.action == "GATE":
            return self._drive_gate(state_machine, screen, gmap, party, pos, leg)

        # A capture leg is a hunt/patrol along that water's coast: once the
        # planned coast tile is reachable on foot, the capture driver steers.
        # (Pulling the party back to leg.end first undid every patrol step,
        # pacing two tiles forever; rules-c84c7c6 batch, 2026-11-22.)
        if leg.action == "CAPTURE" and leg.end in self._foot_reachable(gmap, party, pos):
            return self._drive_capture(state_machine, screen, gmap, party, pos, leg, map_id)

        if leg.action == "X" and map_id == 0:
            key = self._whirl_landing_wait(state_machine, screen, gmap, party, pos, leg.end)
            if key is not None:
                return key

        if pos != leg.end:
            return self._move_toward(state_machine, gmap, party, pos, {leg.end})

        if leg.action == "B":
            if pos in frig_sig:
                plan.legs.pop(0)
                self._last_transition = Transition("B", pos, self._ow_turn)
                self._trip_frigates = frig_sig - {pos}
                return self._emit_key(state_machine, pygame.K_b)
            self._trip = None
            return self._emit_key(state_machine, pygame.K_SPACE)
        if leg.action == "X":
            plan.legs.pop(0)
            self._last_transition = Transition("X", pos, self._ow_turn)
            self._trip_frigates = frig_sig | {pos}
            return self._emit_key(state_machine, pygame.K_x)
        if leg.action == "CAPTURE":
            return self._drive_capture(state_machine, screen, gmap, party, pos, leg, map_id)
        return None

    @staticmethod
    def _whirl_tiles(screen) -> list[tuple[int, int]]:
        return [
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", ())
            if creature_name(c) == "whirlpool" and "x" in c and "y" in c
        ]

    def _whirl_landing_wait(self, state_machine, screen, gmap, party, pos, landing) -> int | None:
        """A key that keeps the ship off the landing while the whirlpool is
        within _WHIRL_LANDING_CLEAR of it, or None to land as planned.

        Only near the landing (3 tiles): farther out the ship sails on.
        Waiting, the ship passes turns, or stands off a tile when the
        whirlpool is next to it."""
        w, h = gmap.width, gmap.height
        whirls = self._whirl_tiles(screen)
        if not whirls or manhattan(w, h, pos, landing) > 3:
            return None
        near = min(_cheb(w, h, landing, t) for t in whirls) <= _WHIRL_LANDING_CLEAR
        if not self._whirl_hold_step(near):
            return None

        def room(t: tuple[int, int]) -> tuple[int, int]:
            return (
                min(_cheb(w, h, t, x) for x in whirls),
                min(manhattan(w, h, t, x) for x in whirls),
            )

        here = room(pos)
        if here[0] <= 1:
            # Stand off: the sea step that puts the most water between ship
            # and whirlpool, by Chebyshev then Manhattan distance, so a step
            # that stays alongside but opens the gap still counts.
            blocked = headwind(getattr(party, "wind_direction", None))
            frig = set(self._frigate_costs(party, screen))
            taken = {(c.get("x"), c.get("y")) for c in getattr(screen, "creatures", ())}
            best = None
            for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
                if d == blocked or getattr(party, "wind_direction", None) is None:
                    continue
                n = ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h)
                if n in frig or n in taken or not can_move_to(gmap, n[0], n[1], Transport.SHIP, party=party):
                    continue
                r = room(n)
                if r > here and (best is None or r > best[0]):
                    best = (r, d)
            if best is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[best[1]])
        return self._emit_key(state_machine, pygame.K_SPACE)

    def _whirl_reboard(self, state_machine, screen, gmap, party, pos, map_id) -> int | None:
        """Ashore with the whirlpool next to the ship the party left (its
        next move may sink it): walk back and board, when the ship is at
        most _WHIRL_REBOARD_STEPS away. None otherwise."""
        lt = self._last_transition
        if map_id != 0 or party.transport == Transport.SHIP or lt is None or lt.kind != "X":
            return None
        ship = lt.pos
        w, h = gmap.width, gmap.height
        if ship not in self._frigate_costs(party, screen):
            return None
        if not any(_cheb(w, h, ship, t) <= 1 for t in self._whirl_tiles(screen)):
            return None
        if manhattan(w, h, pos, ship) > _WHIRL_REBOARD_STEPS:
            return None
        trip = self._trip
        reboarding = trip is not None and trip.dest.label == "whirl_reboard"
        if not reboarding:
            if self._ow_turn < self._whirl_reboard_until:
                return None
            self._whirl_reboard_until = self._ow_turn + _WHIRL_REBOARD_COOLDOWN
        key = self._trip_drive(
            state_machine, screen, gmap, party, pos[0], pos[1], map_id,
            Destination(frozenset({ship}), Transport.SHIP, "whirl_reboard"),
        )
        if key is None or key is _ARRIVED:
            # No way back this turn: pass it rather than fall through to the
            # goal's trip, which would drive the trip a second time in one
            # step (89c1bf4 review). Bounded: the reboard trip is dropped,
            # and the cooldown keeps the next turn from starting another.
            self._trip = None
            return self._emit_key(state_machine, pygame.K_SPACE)
        return key

    def _whirl_hold_step(self, near: bool) -> bool:
        """One turn of the landing hold: True holds the ship (pass a turn).

        Bounded: a hold lasts _WHIRL_HOLD_TURNS at most, then the party goes
        ashore and accepts the risk, and no hold starts again for
        _WHIRL_HOLD_COOLDOWN turns, so landings can't hold-and-replan in a
        loop. The whirlpool moving out of reach lets the ship land at once,
        but doesn't end the hold's window: a whirlpool drifting in and out
        of reach gets the _WHIRL_HOLD_TURNS once, not afresh each time
        (89c1bf4 review), and the cooldown runs from the window's end."""
        turn = self._ow_turn
        start = self._whirl_hold_from
        if start is not None and turn - start >= _WHIRL_HOLD_TURNS:
            self._whirl_hold_from = None
            self._whirl_hold_until = start + _WHIRL_HOLD_TURNS + _WHIRL_HOLD_COOLDOWN
            start = None
            # A window that ran out long ago (the hold drifted out and no
            # landing came until now) is no reason to land beside the
            # whirlpool: past the cooldown a new hold may start (review of
            # 4ecd649). Inside it the ship lands, as before.
            if turn < self._whirl_hold_until:
                return False
        if not near:
            return False
        if start is None:
            if turn < self._whirl_hold_until:
                return False
            self._whirl_hold_from = turn
        return True

    @staticmethod
    def _off_route(plan: TripPlan, pos: tuple[int, int], gmap) -> bool:
        """Far (> 3 tiles) from every tile of the planned path: teleported or lost."""
        if not plan.path:
            return False
        w, h = gmap.width, gmap.height
        return all(manhattan(w, h, pos, (x, y)) > 3 for x, y, _ in plan.path)

    def _open_gate_step(self, screen, gmap, party, pos) -> int | None:
        """Key for the step onto the trip's moongate when it is open now
        (trammel == src, felucca == dst) and orthogonally adjacent; else None."""
        plan = self._trip
        if plan is None or not plan.legs or plan.legs[0].action != "GATE":
            return None
        leg = plan.legs[0]
        gates = getattr(gmap, "moongates", ()) or ()
        src, dst = leg.gate_src, leg.gate_dest
        if src is None or dst is None or src >= len(gates):
            return None
        if getattr(screen, "trammel_phase", -1) != src or getattr(screen, "felucca_phase", -1) != dst:
            return None
        site = (gates[src].x, gates[src].y)
        w, h = gmap.width, gmap.height
        for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
            if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) == site:
                return _DIR_TO_KEY[d]
        return None

    def _drive_gate(self, state_machine, screen, gmap, party, pos, leg: Leg) -> int:
        """Within a few steps of the moongate, firing lanes don't block the
        way in: through it, the threat is gone (batch 0442fe7 seed 125: a
        pirate's lanes covered the gate at (57, 46) and its one open
        neighbour; the party waited two tiles off for ~2,500 steps and
        starved with 974 gold)."""
        gates = getattr(gmap, "moongates", ()) or ()
        src = leg.gate_src
        th = self._threats
        if (
            th is not None
            and party.transport == Transport.FOOT
            and src is not None
            and src < len(gates)
            and manhattan(gmap.width, gmap.height, pos, (gates[src].x, gates[src].y)) <= _TOWN_DASH_STEPS
        ):
            saved = self._overworld_avoid
            self._overworld_avoid = set(saved or ()) - th.hard_avoid()
            try:
                return self._drive_gate_inner(state_machine, screen, gmap, party, pos, leg)
            finally:
                self._overworld_avoid = saved
        return self._drive_gate_inner(state_machine, screen, gmap, party, pos, leg)

    def _drive_gate_inner(self, state_machine, screen, gmap, party, pos, leg: Leg) -> int:
        """Take moongate ``src`` to ``dst`` without standing around.

        User rule (2026-11-21): watch the phases, roam the area fighting what
        comes until the gate is about to open, and be next to it in time.
        The phase steps every 4 surface turns; an open gate stays one phase.

        No step but the one through lands on a gate site, and the party never
        stands on one: the moon can turn on that very step, and whatever
        gate opens under the party then takes it (live check seed 2 at
        bdbd73a: the roam crossed (12, 55) as gate 5 opened to felucca 7,
        every 96 turns, until the party starved with 6,223 gold).
        Past ``_GATE_LEG_MAX_TURNS`` near the gate the leg gives up: the
        site is barred for ``_BLOCK_TURNS`` and the trip replans.
        """
        gates = getattr(gmap, "moongates", ()) or ()
        src, dst = leg.gate_src, leg.gate_dest
        if src is None or dst is None or src >= len(gates):
            self._trip = None
            return self._emit_key(state_machine, pygame.K_SPACE)
        site = (gates[src].x, gates[src].y)
        sites = frozenset((g.x, g.y) for g in gates)
        w, h = gmap.width, gmap.height
        self._trip_stuck = 0
        k = self._phases_until_gate(party, src, dst)
        turns_left = 4 * k
        dist = manhattan(w, h, pos, site)
        if dist <= _GATE_ROAM_RADIUS:
            if self._gate_wait is None or self._gate_wait[0] != (src, dst):
                self._gate_wait = [(src, dst), 0]
            self._gate_wait[1] += 1
            if self._gate_wait[1] > _GATE_LEG_MAX_TURNS:
                self._gate_wait = None
                self._blocked_tiles[site] = self._ow_turn + _BLOCK_TURNS
                self._trip = None
                return self._emit_key(state_machine, pygame.K_SPACE)
        adjacent = {
            ((site[0] + dx) % w, (site[1] + dy) % h)
            for dx, dy in _NEIGHBOURS4
        } - sites
        if pos in sites:
            off = {((pos[0] + dx) % w, (pos[1] + dy) % h) for dx, dy in _NEIGHBOURS4} - sites
            return self._move_toward(state_machine, gmap, party, pos, (adjacent & off) or off, never=sites)
        if dist == 1:
            if k == 0 and getattr(screen, "trammel_phase", -1) == src and getattr(screen, "felucca_phase", -1) == dst:
                d = next(
                    d for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST)
                    if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) == site
                )
                return self._emit_key(state_machine, _DIR_TO_KEY[d])
            if turns_left <= _GATE_WAIT_TURNS:
                return self._emit_key(state_machine, pygame.K_SPACE)  # opens in moments
        if turns_left <= dist + _GATE_WAIT_TURNS:
            if pos in adjacent:
                return self._emit_key(state_machine, pygame.K_SPACE)
            return self._move_toward(state_machine, gmap, party, pos, adjacent, never=sites)
        # Roam near the gate: fight what is around, else wander a little.
        prey = {
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", ()) or ()
            if "x" in c and "y" in c
            and creature_name(c) not in SEA_MONSTERS and creature_name(c) != "whirlpool"
            and manhattan(w, h, site, (c["x"], c["y"])) <= _GATE_ROAM_RADIUS + 3
        }
        if prey:
            return self._move_toward(state_machine, gmap, party, pos, prey, never=sites)
        reach = self._foot_reachable(gmap, party, pos, barred=sites)
        if self._patrol_target is None or pos == self._patrol_target or self._patrol_target not in reach \
                or manhattan(w, h, self._patrol_target, site) > _GATE_ROAM_RADIUS:
            near = [t for t in reach if 1 <= manhattan(w, h, t, site) <= _GATE_ROAM_RADIUS and t != pos]
            self._patrol_target = random.choice(near) if near else None
        if self._patrol_target is None:
            if pos in adjacent:
                return self._emit_key(state_machine, pygame.K_SPACE)
            return self._move_toward(state_machine, gmap, party, pos, adjacent, never=sites)
        return self._move_toward(state_machine, gmap, party, pos, {self._patrol_target}, never=sites)

    @staticmethod
    def _phases_until_gate(party, src: int, dst: int) -> int:
        """Phase steps until trammel == src and felucca == dst (0: open now)."""
        p0 = getattr(party, "moon_phase", 0)
        for k in range(24):
            p = (p0 + k) % 24
            if min(7, p // 3) == src and p % 8 == dst:
                return k
        return 24

    def _drive_capture(self, state_machine, screen, gmap, party, pos, leg: Leg, map_id: int) -> int:
        """Hunt a pirate from land, or patrol the coast until one appears.

        User rule (2026-11-21, "no dicking around"): never sit on one shore
        waiting. With a pirate in the planned body of water: attack it when
        orthogonally adjacent, else walk to a free tile next to it (outside
        firing lanes), else close in to the reachable coast nearest to it (it
        homes in on the party). With none there (Sosaria only; pirates spawn
        there): walk the coast to a far tile of that water, then another,
        meeting and fighting whatever comes.
        """
        self._trip_stuck = 0
        w, h = gmap.width, gmap.height
        terr = terrain_for(gmap, party, map_id)
        comps = {
            terr.sea_comp[n] for n in terr.neighbours(*leg.end) if n in terr.sea_comp
        }
        th = self._threats
        pirates = [p for p in (th.pirates if th is not None else []) if terr.sea_comp.get(p) in comps]
        if self._ow_turn < self._capture_shun_until:
            pirates = []  # a stalled hunt with no dash: patrol for a while
        for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
            if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) in pirates:
                self._dash = None
                return self._attack(state_machine, d)
        reach = self._foot_reachable(gmap, party, pos)
        if pirates and self._capture_stalled(w, h, pos, pirates):
            if self._can_take_broadsides(party):
                self._dash = (
                    frozenset(comps),
                    map_id,
                    self._trip.dest.label if self._trip is not None else None,
                    evaluate_goal(party, map_id),
                )
                key = self._capture_dash(state_machine, state_machine.current_screen, gmap, party, pos, th)
                if key is not None:
                    return key
                # No foot route reaches a tile beside it: a pirate snagged
                # on the coast (LairWare MoveMonsters steps only toward the
                # party, UltimaMisc.c:1191-1236) never comes. Leave it alone
                # and patrol, as a weak party does (seed 8 at bdbd73a passed
                # ~3,000 turns at (58, 40) for one at (58, 48), starved).
                self._dash = None
            self._capture_shun_until = self._ow_turn + _CAPTURE_SHUN_TURNS
            self._cap_best = None
            self._patrol_target = None
            pirates = []
        if pirates:
            engage = {
                ((p[0] + dx) % w, (p[1] + dy) % h)
                for p in pirates
                for dx, dy in _NEIGHBOURS4
            }
            engage = {t for t in engage if t in reach and not (th is not None and th.unsafe_end(t))}
            if engage:
                tgt = self._hunt_target_for(gmap, pos, reach, engage, pirates, th)
                return self._move_toward_off_lanes(state_machine, gmap, party, pos, {tgt}, th)
            coast = [
                t for t in reach
                if any(terr.sea_comp.get(n) in comps for n in terr.neighbours(*t))
                and not (th is not None and th.unsafe_end(t))
            ]
            if coast:
                best = min(min(manhattan(w, h, t, p) for p in pirates) for t in coast)
                closest = {t for t in coast if min(manhattan(w, h, t, p) for p in pirates) == best}
                if pos not in closest:
                    tgt = self._hunt_target_for(gmap, pos, reach, closest, pirates, th)
                    return self._move_toward_off_lanes(state_machine, gmap, party, pos, {tgt}, th)
            # As close as land allows: it is coming (pirates home in).
            return self._emit_key(state_machine, pygame.K_SPACE)
        # Patrol: a far reachable coast tile of this water, re-picked on arrival.
        if self._patrol_target is None or pos == self._patrol_target or self._patrol_target not in reach:
            coast = [
                t for t in reach
                if any(terr.sea_comp.get(n) in comps for n in terr.neighbours(*t))
            ]
            far = [t for t in coast if manhattan(w, h, t, pos) >= 12] or coast
            self._patrol_target = random.choice(far) if far else None
        if self._patrol_target is None:
            return self._emit_key(state_machine, pygame.K_SPACE)
        return self._move_toward(state_machine, gmap, party, pos, {self._patrol_target})

    _TOWN_WAIT_LIMIT = 40

    def _town_step_patient(self, sm, gmap, party, px, py, goal_xy, npc_tiles) -> int | None:
        """Step toward ``goal_xy`` in a town, waiting out the crowd.

        Town people move now (LW MoveMonsters), so a lane full of wanderers
        clears in a turn or two. If no route is open this turn but one is
        once people are ignored, walk it and pass a turn when a non-FIXED
        person stands on the next tile (user 2026-11-22: Grey's pub is
        crowded, but patience reaches the guild; autoplay used to give up
        and walk straight back out). Gives up after _TOWN_WAIT_LIMIT waits
        in a row; FIXED people stay walls."""
        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        d = find_2d_step(
            gmap, (px, py), goal_xy, Transport.FOOT, party=party,
            avoid_tiles=npc_tiles, prefer_paths=True, allow_locked_doors=has_key,
        )
        if d is not None:
            self._town_waits = 0
            return self._step_or_unlock(sm, gmap, party, px, py, d)
        saved = gmap.npcs
        fixed = [n for n in saved if getattr(n, "movement", "FIXED") == "FIXED"]
        gmap.npcs = fixed  # people who never move stay walls
        try:
            d = find_2d_step(
                gmap, (px, py), goal_xy, Transport.FOOT, party=party,
                avoid_tiles={(n.x, n.y) for n in fixed}
                | (getattr(self, "_town_danger_tiles", set()) - {(px, py)}),
                prefer_paths=True,
                allow_locked_doors=has_key,
            )
        finally:
            gmap.npcs = saved
        if d is None:
            return None
        nxt = (px + d.dx, py + d.dy)
        blocker = next((n for n in saved if (n.x, n.y) == nxt), None)
        if blocker is None:
            self._town_waits = 0
            return self._step_or_unlock(sm, gmap, party, px, py, d)
        self._town_waits = getattr(self, "_town_waits", 0) + 1
        if self._town_waits > self._TOWN_WAIT_LIMIT:
            return None
        return self._emit_key(sm, pygame.K_SPACE)

    _HUNT_KEEP_RADIUS = 3

    def _hunt_target_for(self, gmap, pos, reach, candidates, pirates, th) -> tuple[int, int]:
        """Commit to one land tile while hunting a pirate.

        A pirate shadows the party along the coast, so the set of tiles next
        to it shifts every turn; re-aiming at the nearest each turn flipped
        between routes on either side of a ridge and paced in place forever
        (batch bbceab3 seeds 79/85: 33k steps on Ambrosia, then starved).
        Keep the chosen tile while it stays reachable, safe and within a few
        tiles of a pirate; re-pick (shortest walk) on arrival or when it
        goes bad."""
        w, h = gmap.width, gmap.height
        t = self._hunt_target
        if (
            t is not None
            and t != pos
            and t in reach
            and not (th is not None and th.unsafe_end(t))
            and any(manhattan(w, h, t, p) <= self._HUNT_KEEP_RADIUS for p in pirates)
        ):
            return t
        dist = {pos: 0}
        frontier = [pos]
        best = None
        while frontier and best is None:
            nxt = []
            for cx, cy in frontier:
                for dx, dy in _NEIGHBOURS4:
                    n = ((cx + dx) % w, (cy + dy) % h)
                    if n in dist or n not in reach:
                        continue
                    dist[n] = dist[(cx, cy)] + 1
                    nxt.append(n)
            hits = sorted(n for n in nxt if n in candidates)
            if hits:
                best = hits[0]
            frontier = nxt
        self._hunt_target = best if best is not None else min(candidates)
        return self._hunt_target

    @staticmethod
    def _can_shop_death_gulch(party) -> bool:
        """Keys for both of Death Gulch's doors on able members, and the two
        bribes plus a ration a member in gold. Short of either the way in
        stops at a door, the party walks out and comes straight back, the
        town reset each time (review of 0bf9623: 745 entries in 1,500 steps
        with 0 keys); then the strip waits for a pirate as before."""
        able = _able(party)
        return (
            sum(m.keys for _, m in able) >= _DG_FOOD_KEYS
            and party.gold >= _DG_FOOD_BRIBES + len(able)
        )

    def _on_death_gulch_strip(self, gmap, party, pos) -> bool:
        """``pos`` is on foot reach of Death Gulch's gate on Sosaria (the
        strip a party can't leave but by ship)."""
        if getattr(party, "transport", Transport.FOOT) != Transport.FOOT:
            return False
        w, h = gmap.width, gmap.height
        reach = self._foot_reachable(gmap, party, pos)
        gx, gy = _DEATH_GULCH_PORTAL
        return _DEATH_GULCH_PORTAL in reach or any(
            ((gx + dx) % w, (gy + dy) % h) in reach for dx, dy in _NEIGHBOURS4
        )

    def _foot_reachable(self, gmap, party, pos, barred=frozenset()) -> frozenset[tuple[int, int]]:
        """Land tiles reachable on foot from ``pos`` without entering a
        ``barred`` tile (cached per map/turn)."""
        key = (id(gmap), pos, self._ow_turn, frozenset(barred))
        if self._reach_cache is not None and self._reach_cache[0] == key:
            return self._reach_cache[1]
        terr = terrain_for(gmap, party, getattr(gmap, "id", 0))
        seen = {pos}
        stack = [pos]
        while stack:
            cur = stack.pop()
            for n in terr.neighbours(*cur):
                if n not in seen and n in terr.foot and n not in barred:
                    seen.add(n)
                    stack.append(n)
        out = frozenset(seen)
        self._reach_cache = (key, out)
        return out

    # -- local grinding on the mainland ----------------------------------

    @staticmethod
    def _broke_and_starving(screen, gmap, party, px, py, living) -> bool:
        """< 30 gold, someone at 0 food, everyone >= 30% HP, no sea monster within 7."""
        naval_threat_near = any(
            creature_name(c) in SEA_MONSTERS
            and "x" in c and "y" in c
            and max(abs(wrap_delta(px, c["x"], gmap.width)), abs(wrap_delta(py, c["y"], gmap.height))) <= 7
            for c in getattr(screen, "creatures", [])
        )
        return (
            not naval_threat_near
            and party.gold < 30
            and any(m.food == 0 for m in living)
            and all(m.hp * 10 >= m.max_hp * 3 for m in living)
        )

    # Patrol moves with no land monster within 12 tiles before the early
    # Britain loop gives way to the wide Sosaria patrol.
    _GRIND_QUIET_LIMIT = 150
    _grind_quiet = 0
    # Grind turns with no fight and no land monster within _GRIND_SIGHT
    # (batch 67c0de5 b7 seed 61: a level-25 party paced (40, 41)-(40, 42)
    # for ~3,400 turns at a time, the chase walking north toward a monster
    # 12 tiles off behind the water at (29-32, 41-44), the patrol walking
    # back south once it was 13 off; each chase step reset the quiet count,
    # so the wide patrol never started, and food runs spent 5,379 gold).
    # LairWare never despawns and every monster steps toward the party each
    # turn, so a spot nothing reaches has Sosaria's 32 slots full of
    # monsters snagged on terrain: none spawn, none come. At
    # _GRIND_DEAD_LIMIT the grind stops chasing monsters it can't see and
    # takes the wide patrol until a fight or a monster in sight. 150, the
    # quiet limit: with a free slot SpawnMonster adds one every ~19 turns
    # (7 in 135), and they come on a tile a turn.
    _GRIND_DEAD_LIMIT = 150
    _GRIND_SIGHT = 8
    _grind_dead = 0

    def _grind_local(self, state_machine, screen, gmap, party, px, py, living) -> int:
        # Actively chase nearby reachable land creatures (skip if hurt,
        # unless broke & starving with no naval threat nearby so we can earn 30g for food!)
        transport = Transport.FOOT if party.transport != Transport.SHIP else Transport.SHIP
        broke_and_starving = self._broke_and_starving(screen, gmap, party, px, py, living)
        if transport == Transport.FOOT and (not needs_heal(party) or broke_and_starving):
            land_targets: set[tuple[int, int]] = set()
            # Not dragons while anyone is below level 8 (user OK 2026-11-22;
            # batch 1c7525f: about 15 of 49 wipes were level 1-5 parties
            # walking up to dragons). Fleeing is unchanged: chased, a
            # healthy party still fights them (user ruling 2026-11-21).
            green = any(m.level < _DRAGON_CHASE_LEVEL for m in living)
            in_sight = any(
                "x" in c and "y" in c
                and creature_name(c) != "whirlpool" and creature_name(c) not in SEA_MONSTERS
                and manhattan(gmap.width, gmap.height, (px, py), (c["x"], c["y"])) <= self._GRIND_SIGHT
                for c in getattr(screen, "creatures", [])
            )
            self._grind_dead = 0 if in_sight else self._grind_dead + 1
            reach = self._GRIND_SIGHT if self._grind_dead >= self._GRIND_DEAD_LIMIT else 12
            for c in getattr(screen, "creatures", []):
                tname = creature_name(c)
                if tname == "whirlpool" or tname in SEA_MONSTERS:
                    continue
                if green and tname == "dragon":
                    continue
                cx, cy = c.get("x"), c.get("y")
                if cx is None or cy is None:
                    continue
                if manhattan(gmap.width, gmap.height, (px, py), (cx, cy)) <= reach:
                    land_targets.add((cx, cy))
            if land_targets:
                d = find_2d_step(gmap, (px, py), land_targets, Transport.FOOT, party=party, avoid_tiles=self._overworld_avoid)
                if d is not None:
                    self._grind_quiet = 0  # a monster it can walk to
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        if transport == Transport.FOOT:
            # Every patrol move counts as quiet (user live trace
            # 2026-11-22, trace_20261122-145915: the count lived inside the
            # chase block, which is skipped while anyone needs healing, so
            # with a hurt level-2 Cleric it never grew; 4,000 steps on the
            # Britain loop, no fight, starved).
            self._grind_quiet += 1
            early_patrol = ((42, 18), (38, 17), (35, 17), (40, 22), (45, 22), (46, 20))
            # User 2026-11-22: circling Britain forever starves the party when
            # nothing turns up (batch 775884a seeds 35, 50, 60...: ~1,900
            # patrol steps, no fight, no gold, food to 0). Loop near Britain
            # for a while, then widen to the whole continent until a monster
            # shows up again.
            near_ok = self._grind_quiet < self._GRIND_QUIET_LIMIT
            patrol = (
                early_patrol
                if (near_ok and living and min(m.level for m in living) < 3)
                else _SOSARIA_PATROL
            )
            for _ in range(len(patrol)):
                target = patrol[self._patrol_idx % len(patrol)]
                if (px, py) == target:
                    self._patrol_idx += 1
                    continue
                d = find_2d_step(gmap, (px, py), {target}, Transport.FOOT, party=party, avoid_tiles=self._overworld_avoid)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])
                self._patrol_idx += 1
        return self._emit_key(state_machine, pygame.K_SPACE)

    def _maybe_feed(self, state_machine: StateMachine, party) -> int | None:
        """``H`` food from the fullest member to one under ``FEED_BELOW``
        (equipment.food_hand_off; LairWare HandEquip 'F',
        UltimaMain.c:1791-1814): from, to, F, the amount and Return."""
        feed = food_hand_off(party)
        if feed is None:
            return None
        giver, taker, amount = feed
        self._queue_text(f"{giver}{taker}f{amount}", enter=True)
        return self._emit_key(state_machine, pygame.K_h)

    def _maybe_manage_gear(
        self,
        state_machine: StateMachine,
        party,
        prefer_ranged: bool = True,
    ) -> int | None:
        """Equip best owned weapon/armor or hand off chest loot to a better-fit member."""
        for i, m in enumerate(party.members):
            if m.is_dead():
                continue
            better_w = best_owned_weapon(m, prefer_ranged=prefer_ranged)
            if better_w is not None:
                self._ready_member_idx = i + 1
                self._ready_item_letter = chr(ord("a") + list(WeaponType).index(better_w))
                return self._emit_key(state_machine, pygame.K_r)

        for i, m in enumerate(party.members):
            if m.is_dead():
                continue
            better_a = best_owned_armor(m)
            if better_a is not None:
                self._wear_member_idx = i + 1
                self._wear_item_letter = chr(ord("a") + list(ArmorType).index(better_a))
                return self._emit_key(state_machine, pygame.K_w)

        offer = hand_offer(party, prefer_ranged)
        if offer is not None:
            self._hand_from_idx, self._hand_to_idx, self._hand_item = offer
            return self._emit_key(state_machine, pygame.K_h)

        return None

    def _handle_town_prompt(self, state_machine: StateMachine, screen) -> int | None:
        prompt = (getattr(screen.text_log, "current_prompt", "") or "").lower()
        if "join gold" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._join_gold_member_idx)
        if "from plr" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._hand_from_idx)
        if "to plr" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._hand_to_idx)
        if "f,g,e,w,a" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._hand_item[0]))
        if "which weapon:" in prompt or "which armour:" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._hand_item[1]))
        if "ready" in prompt and "member" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._ready_member_idx)
        if "ready" in prompt or "weapon?" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._ready_item_letter) or pygame.K_b)
        if "wear" in prompt and "member" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._wear_member_idx)
        if "wear" in prompt or "armor?" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._wear_item_letter) or pygame.K_b)
        if "who is in need" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._heal_patient_idx)
        if self._sell_plan is not None:
            _idx, letter, count = self._sell_plan
            if "buy" in prompt and "sell" in prompt:
                if self._sell_asked:  # back at the question: refused, leave
                    self._sell_plan = None
                    return self._emit_key(state_machine, pygame.K_ESCAPE)
                self._sell_asked = True
                return self._emit_key(state_machine, pygame.K_s)
            if "wouldst you sell" in prompt:
                return self._emit_key(state_machine, _char_to_key(letter) or pygame.K_ESCAPE)
            if "like to sell" in prompt:
                self._queue_text(str(count), enter=True)
                return self._emit_key(state_machine, self._key_queue.popleft())
        # A stack at 99 (LairWare message 260) re-asks the item question:
        # walk away rather than pick the same item forever.
        recent = " ".join(str(x) for x in list(getattr(screen.text_log, "history", None) or ())[-25:]).lower()
        if "not enough room" in recent and (
            "your interest" in prompt or "wat'l it be" in prompt or "how many rations" in prompt
        ):
            return self._emit_key(state_machine, pygame.K_ESCAPE)
        if "your need" in prompt or "wat'l it be" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._shop_item_letter) or pygame.K_c)
        if "talk" in prompt or "which" in prompt or "who" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._shop_member_idx)
        if "direction" in prompt:
            return self._emit_key(state_machine, self._talk_dir_key)
        if "buy" in prompt and "sell" in prompt:
            return self._emit_key(state_machine, pygame.K_b)
        lines = getattr(screen.text_log, "lines", None) or ()
        last_msg = str(lines[-1]).lower() if lines else ""
        # The guild's "See more?" after a sale (GuildVendor ANYTHING_ELSE):
        # answering y bought again until the buyer's gold ran out (live
        # trace 2026-11-22: 44 keys for 2,200 gold at Grey). One per talk;
        # the goal brings the party back if it still needs more.
        if (
            "anything else" in prompt or "anything else" in last_msg or "see more" in last_msg
            or "see more" in prompt or "give blood" in prompt or "more help" in prompt
        ):
            return self._emit_key(state_machine, pygame.K_n)
        if "(y or n)" in prompt or "take it" in prompt or "deal" in prompt:
            return self._emit_key(state_machine, pygame.K_y)
        if "how many rations" in prompt:
            self._queue_text(str(self._food_packs), enter=True)
            return self._emit_key(state_machine, self._key_queue.popleft())
        if "how many" in prompt:
            self._queue_text("1", enter=True)
            return self._emit_key(state_machine, self._key_queue.popleft())
        # The tavern asks "What'll it be, Food er Ale?" as its prompt; it was
        # always walked away from, not answered with an item letter.
        if "food er ale" in prompt or "somethin' else" in prompt:
            return self._emit_key(state_machine, pygame.K_ESCAPE)
        if "buy" in prompt or "what" in prompt or "wat'l" in prompt or "choice" in prompt or "(a-" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._shop_item_letter) or pygame.K_b)
        return self._emit_key(state_machine, pygame.K_ESCAPE)

    def _last_steps_into_town(self, gmap, party, pos, target) -> set[tuple[int, int]]:
        """On foot within a few steps of a town gate: the firing lanes to drop
        from the avoid set. Inside, the threat is gone; one broadside costs
        less than dancing outside. (Batch ccd5f52 seed 103: a pirate bobbing
        between (5, 43) and (5, 44) lane-blocked each route to the gate at
        (7, 44) in turn; the party swapped routes ~1,900 times, three tiles
        from food, and starved.)"""
        th = self._threats
        if party.transport != Transport.FOOT or th is None or len(target) != 1:
            return set()
        gate = next(iter(target))
        if not any((p.x, p.y) == gate for p in getattr(gmap, "portals", ())):
            return set()
        if abs(gate[0] - pos[0]) + abs(gate[1] - pos[1]) > _TOWN_DASH_STEPS:
            return set()
        lanes = th.hard_avoid()
        _d, cost = find_2d_step_and_cost(gmap, start=pos, goals=target, transport=Transport.FOOT, party=party)
        if cost is None or cost > _TOWN_DASH_STEPS:
            return set()
        return lanes

    _chest_target: tuple[int, int] | None = None
    # Stalled-capture tracking (_capture_stalled / _capture_dash).
    _cap_best: int | None = None
    _cap_stall = 0
    _cap_seen_turn = -10
    _capture_shun_until = -1
    # (sea components, map id, trip label, goal) of a dash under way, or None.
    _dash: tuple | None = None

    def _capture_stalled(self, w, h, pos, pirates) -> bool:
        """Count capture turns in a row in which the nearest pirate came no
        closer than the closest it has been; stalled at _CAPTURE_STALL_TURNS."""
        d = min(manhattan(w, h, pos, p) for p in pirates)
        if self._cap_best is None or self._ow_turn - self._cap_seen_turn > 3 or d < self._cap_best:
            self._cap_best = d
            self._cap_stall = 0
        else:
            self._cap_stall += 1
        self._cap_seen_turn = self._ow_turn
        if self._cap_stall >= _CAPTURE_STALL_TURNS:
            self._cap_best = None
            self._cap_stall = 0
            return True
        return False

    def _board_dash(self, state_machine, screen, gmap, party, pos, th) -> int | None:
        """Walk through the firing lanes to a frigate within
        _BOARD_DASH_STEPS and board it, when the trip's next leg needs a
        ship (B or a capture) and every member can take a worst-case hit
        on each lane turn of the walk. Emitted unguarded: the lane guard
        and the lane escape would undo it.

        Batch 89c1bf4 b9 seed 90: the party left its frigate at (31, 2) for
        Fawn (30, 2), on a three-tile strip (27-29, 2). A pirate came to
        (32, 2) behind the empty frigate; LairWare's MoveMonsters steps it
        only west, onto the frigate's 0x2C, which ValidMonsterDir refuses
        (UltimaMisc.c:263-272, 1191-1236), so it stays there for good,
        its row shot reaching (29, 2) and (30, 2). The trip stepped onto
        (29, 2), the escape stepped back, and the party paced (28, 2)-(29, 2)
        for ~3,700 steps until it starved with 4,665 gold. Aboard at
        (31, 2) the pirate is orthogonally next to the ship: the usual
        rules fight it or sail away."""
        if party.transport != Transport.FOOT or th is None or not th.pirates:
            return None
        plan = self._trip
        if plan is None or not plan.legs or plan.legs[0].action not in ("B", "CAPTURE"):
            return None
        frigates = set(self._frigate_costs(party, screen))
        if not frigates:
            return None
        if pos in frigates:
            # On it: the trip, the one owner of B, boards (a capture plan is
            # dropped so the replan from here is the B leg).
            if plan.legs[0].action == "CAPTURE":
                self._trip = None
            return _YIELD_TO_TRIP
        if party_has_low_hp(party):
            return None
        terr = terrain_for(gmap, party, getattr(gmap, "id", 0))
        occupied = {
            (c["x"], c["y"]) for c in getattr(screen, "creatures", ()) or ()
            if "x" in c and "y" in c
        }
        # Shortest foot walk (BFS) to a frigate tile: land on the way, the
        # frigate's water tile only as the last step.
        prev: dict[tuple[int, int], tuple[int, int] | None] = {pos: None}
        frontier = [pos]
        found = None
        for _ in range(_BOARD_DASH_STEPS):
            nxt_front = []
            for cur in frontier:
                for n in terr.neighbours(*cur):
                    if n in prev or n in occupied:
                        continue
                    if n in frigates:
                        prev[n] = cur
                        found = n
                        break
                    if n in terr.foot and can_move_to(gmap, n[0], n[1], Transport.FOOT, party=party):
                        prev[n] = cur
                        nxt_front.append(n)
                if found is not None:
                    break
            if found is not None:
                break
            frontier = nxt_front
        if found is None:
            return None
        path = [found]
        while prev[path[-1]] != pos:
            path.append(prev[path[-1]])
        path.reverse()
        # Each turn ending in a lane is a possible hit; boarding on a lane
        # tile is one more turn there.
        hits = sum(1 for t in path if t in th.lanes) + (1 if found in th.lanes else 0)
        if any(not m.is_dead() and m.hp <= hits * _BROADSIDE_MAX for m in party.members):
            return None
        step = path[0]
        w, h = gmap.width, gmap.height
        d = next(
            d for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST)
            if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) == step
        )
        return self._emit_key(state_machine, _DIR_TO_KEY[d], guarded=False)

    @staticmethod
    def _can_take_broadsides(party) -> bool:
        """Every living member survives two worst-case LairWare broadsides."""
        living = [m for m in party.members if not m.is_dead()]
        return bool(living) and all(m.hp > 2 * _BROADSIDE_MAX for m in living)

    def _capture_dash(self, state_machine, screen, gmap, party, pos, th) -> int | None:
        """Walk a stalled capture through the firing lanes: the shortest foot
        route to a tile next to the pirate, attacking once orthogonally
        adjacent. Live trace 2026-11-25 (trace_20261125-163401): a pirate
        shadowing the party along Sosaria's coast turned every off-lane
        sidestep into its new lane, so the hunt paced (45,35)-(46,35) for
        ~9,000 steps. Emitted unguarded: the lane guard, the lane escape and
        the no-ending-in-a-lane rule don't undo it. Ends on the attack, when
        the pirate is gone, the goal or capture leg changes, or a member can
        no longer take two broadsides."""
        dash = self._dash
        if dash is None:
            return None
        comps, map_id, label, goal = dash
        plan = self._trip
        terr = terrain_for(gmap, party, map_id)
        pirates = [p for p in th.pirates if terr.sea_comp.get(p) in comps]
        if (
            party.transport != Transport.FOOT
            or self._screen_map_id(screen, party) != map_id
            or plan is None
            or not plan.legs
            or plan.legs[0].action != "CAPTURE"
            or plan.dest.label != label
            or not pirates
            or not self._can_take_broadsides(party)
            or evaluate_goal(party, map_id) != goal
        ):
            self._dash = None
            return None
        w, h = gmap.width, gmap.height
        for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
            if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) in pirates:
                self._dash = None
                return self._attack(state_machine, d)
        step = self._pirate_hunt_step(gmap, party, pos, th, pirates=pirates, limit=w * h)
        if step is None:
            self._dash = None
            return None
        # The foot route may pass a locked door (keys count as passable):
        # unlock it, don't walk into it. Batch seed 1 (round 1 report):
        # the dash pressed West into Ambrosia's door at (50, 6) from (51, 6)
        # for ~7,000 steps, keys in hand, until the food ran low.
        nx, ny = (pos[0] + step.dx) % w, (pos[1] + step.dy) % h
        if self._is_locked_door(gmap, nx, ny):
            key_idx = next(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.keys > 0),
                None,
            )
            if key_idx is None:
                self._dash = None
                return None
            self._queue_text(f"{key_idx}{step.name[0].lower()}", enter=False)
            return self._emit_key(state_machine, pygame.K_u, guarded=False)
        return self._emit_key(state_machine, _DIR_TO_KEY[step], guarded=False)

    _capture_goal: tuple[int, int] | None = None
    _capture_turn = -10

    def _capture_escape_rank(self, gmap, party, th):
        """While a pirate capture is under way (it acted this turn or last),
        rank lane-escape steps by their lane-free walk on to its target;
        with none, by the plain walk (lanes crossed), after every lane-free
        one.

        Live trace 2026-11-24 (Ambrosia's north bay): two pirates at the
        bay's tip can't step toward the party over land (LairWare
        MoveMonsters/ValidMonsterDir), so they never close in, and every
        tile next to them is ringed by their lanes. With no lane-free walk
        anywhere every step ranked the same, the escape took the one
        farthest from them, back where the capture had just stepped from,
        and the two undid each other for 7,000 steps under fire."""
        goal = self._capture_goal
        if goal is None or self._ow_turn - self._capture_turn > 1:
            return None
        avoid = th.hard_avoid() - {goal}

        def rank(tile):
            if tile == goal:
                return 0
            _d, cost = find_2d_step_and_cost(
                gmap, start=tile, goals={goal}, transport=Transport.FOOT, party=party, avoid_tiles=avoid
            )
            if cost is not None:
                return cost
            _d, cost = find_2d_step_and_cost(
                gmap, start=tile, goals={goal}, transport=Transport.FOOT, party=party
            )
            return 1_000 + cost if cost is not None else 10_000

        return rank

    def _move_toward_off_lanes(self, state_machine, gmap, party, pos, goals, th) -> int:
        """``_move_toward`` around pirate firing lanes when a lane-free route
        exists. Batch 1c7525f seed 2: the capture walked up a pirate's
        column into its lane, the lane escape stepped back out, and in and
        out it went, a broadside each time, until the party died."""
        self._capture_goal = next(iter(goals)) if len(goals) == 1 else None
        self._capture_turn = self._ow_turn
        lanes = th.hard_avoid() if th is not None else set()
        if lanes:
            base = getattr(self, "_overworld_avoid", None) or set()
            avoid = set(base) | (lanes - goals)
            if find_2d_step(gmap, pos, goals, party.transport, party=party, avoid_tiles=avoid) is not None:
                saved = self._overworld_avoid
                self._overworld_avoid = avoid
                try:
                    return self._move_toward(state_machine, gmap, party, pos, goals)
                finally:
                    self._overworld_avoid = saved
        return self._move_toward(state_machine, gmap, party, pos, goals)

    def _move_toward(
        self,
        state_machine: StateMachine,
        game_map,
        party,
        start: tuple[int, int],
        goals: set[tuple[int, int]],
        never: set[tuple[int, int]] | frozenset[tuple[int, int]] | None = None,
    ) -> int:
        """Step toward ``goals``. ``never`` tiles stay out of every route,
        the fallbacks' too (the soft avoid set is dropped when it walls the
        party in; these are not)."""
        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        never = set(never or ())
        starving_buy_food = (
            any(not m.is_dead() and m.food == 0 for m in party.members)
            and evaluate_goal(party, getattr(game_map, "id", getattr(party, "map_id", 0))) == Goal.BUY_FOOD
        )
        avoid = (set(getattr(self, "_overworld_avoid", None) or ()) | never) or None
        wind = getattr(party, "wind_direction", None)
        d, wind_cost = find_2d_step_and_cost(
            game_map,
            start=start,
            goals=goals,
            transport=party.transport,
            party=party,
            wind_direction=wind,
            avoid_tiles=avoid,
            allow_locked_doors=has_key,
        )
        if (
            starving_buy_food
            and avoid
            and (d is None or (wind_cost is not None and wind_cost > _STARVING_AVOID_MAX_STEPS))
        ):
            avoid = (set(self._threats.hard_avoid() if self._threats is not None else ()) | never) or None
            d, wind_cost = find_2d_step_and_cost(
                game_map,
                start=start,
                goals=goals,
                transport=party.transport,
                party=party,
                wind_direction=wind,
                avoid_tiles=avoid,
                allow_locked_doors=has_key,
            )
        # A hold given up under this wind for these goals: keep to the
        # wind-legal route while the wind holds. Letting the wind-free
        # heading back in walked the ship out and back for good (review of
        # 35aa3cd: hold 20, out, back, repeat).
        # The same destination is the same map and goals within
        # _WIND_GOAL_DRIFT tiles of the committed ones: the whirlpool drifts
        # a tile about every 4 steps, and keying on the exact tiles cleared
        # the commitment at each drift (final review of 8e3b26c).
        map_key = getattr(game_map, "id", None)
        goal_key = frozenset(goals)
        if self._wind_commit is not None:
            c_wind, c_map, c_goals = self._wind_commit
            gw, gh = game_map.width, game_map.height
            same_dest = c_map == map_key and any(
                manhattan(gw, gh, a, b) <= _WIND_GOAL_DRIFT for a in goal_key for b in c_goals
            )
            if c_wind != wind or not same_dest:
                self._wind_commit = None
            else:
                self._wind_commit = (c_wind, c_map, goal_key)  # follow the drift
            self._wind_hold_n = 0
        committed = self._wind_commit is not None and d is not None
        held = False
        if (
            party.transport == Transport.SHIP
            and wind is not None
            and party.food >= 100
            and start not in (avoid or ())
            and not getattr(self, "_ship_threat_near", False)
            and not committed
        ):
            free_d, free_cost = find_2d_step_and_cost(
                game_map,
                start=start,
                goals=goals,
                transport=party.transport,
                party=party,
                avoid_tiles=avoid,
                ignore_wind=True,
                # As the wind-legal search: without it a route through a
                # locked water door (Ambrosia's at (39, 61)) was no route,
                # and the ship passed until a wind allowed every heading the
                # route takes (trace_20261125-184644, ~2,260 steps).
                allow_locked_doors=has_key,
            )
            if free_d is not None and free_cost is not None and (
                d is None or (wind_cost is not None and wind_cost * 2 > free_cost * 3)
            ):
                if free_d != headwind(wind):
                    # Advance along the wind-free shortest route while its next
                    # heading is allowed.
                    d = free_d
                else:
                    prog = self._wind_progress_step(
                        game_map, start, goals, party, wind, avoid, has_key, free_cost
                    )
                    extra = (wind_cost - free_cost) if wind_cost is not None else None
                    if self._wind_hold_wind != wind:
                        self._wind_hold_wind, self._wind_hold_n = wind, 0
                    if prog is not None:
                        d = prog
                    elif (
                        d is None
                        or extra is None
                        or extra > _WIND_DETOUR_MAX
                        or self._wind_hold_n < min(_WIND_HOLD_MAX, extra)
                    ):
                        # Headwind on the short route and no allowed step
                        # gains on it: wait for the wind (see _WIND_HOLD_MAX).
                        held = True
                    else:
                        # Held long enough: sail the wind-legal route (d)
                        # from here on while this wind holds.
                        self._wind_commit = (wind, map_key, goal_key)
        if held:
            self._wind_hold_n += 1
            return self._emit_key(state_machine, pygame.K_SPACE)
        if self._wind_commit is None:
            self._wind_hold_n = 0  # a hold counts only turns held in a row
        if d is None and avoid:
            # Drop the soft avoidance but keep the hard threats (pirate lanes,
            # squid reach): the lane guard would refuse those steps anyway.
            hard = set(self._threats.hard_avoid() if self._threats is not None else ()) | never
            d = find_2d_step(
                game_map,
                start=start,
                goals=goals,
                transport=party.transport,
                party=party,
                wind_direction=wind,
                avoid_tiles=hard or None,
                allow_locked_doors=has_key,
            )
            if d is None and hard - never:
                # Walled in by threats: take the plain route; _lane_guard lets a
                # healthy party advance on the threat and bars the tile otherwise.
                d = find_2d_step(
                    game_map,
                    start=start,
                    goals=goals,
                    transport=party.transport,
                    party=party,
                    wind_direction=wind,
                    avoid_tiles=never or None,
                    allow_locked_doors=has_key,
                )
        if d is not None:
            nx = start[0] + d.dx
            ny = start[1] + d.dy
            if getattr(game_map, "border_behavior", "exit") == "wrap":
                nx %= game_map.width
                ny %= game_map.height
            nxt_tile = game_map.get_tile(nx, ny) if 0 <= nx < game_map.width and 0 <= ny < game_map.height else None
            if nxt_tile is not None and str(getattr(nxt_tile, "name", "")).lower() == "locked_door":
                key_idx = next(
                    (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.keys > 0),
                    None,
                )
                if key_idx is not None:
                    self._queue_text(f"{key_idx}{d.name[0].lower()}", enter=False)
                    return self._emit_key(state_machine, pygame.K_u)
            return self._emit_key(state_machine, _DIR_TO_KEY[d])
        return self._emit_key(state_machine, pygame.K_SPACE)

    @staticmethod
    def _wind_progress_step(game_map, start, goals, party, wind, avoid, has_key, free_cost):
        """A heading the wind allows whose next tile is nearer the goal by the
        wind-free route than ``start`` (cost below ``free_cost``), nearest
        first; None when every allowed step loses ground."""
        blocked = headwind(wind)
        w, h = game_map.width, game_map.height
        wraps = getattr(game_map, "border_behavior", "exit") == "wrap"
        best = None
        for dd in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
            if dd == blocked:
                continue
            nx, ny = start[0] + dd.dx, start[1] + dd.dy
            if wraps:
                nx, ny = nx % w, ny % h
            elif not (0 <= nx < w and 0 <= ny < h):
                continue
            nxt = (nx, ny)
            if nxt in goals:
                return dd
            if avoid and nxt in avoid:
                continue
            if not can_move_to(game_map, nx, ny, transport=party.transport, party=party):
                continue
            _d, cost = find_2d_step_and_cost(
                game_map, start=nxt, goals=goals, transport=party.transport, party=party,
                avoid_tiles=avoid, ignore_wind=True, allow_locked_doors=has_key,
            )
            if cost is not None and cost < free_cost and (best is None or cost < best[0]):
                best = (cost, dd)
        return best[1] if best is not None else None

    @staticmethod
    def _shop_spot(game_map, pos: tuple[int, int], stand: tuple[int, int]) -> tuple[int, int]:
        """The spot to Transact from: ``stand`` when a merchant is across its
        counter, else the nearest spot along the same counter that faces one.

        Merchants wander along the row behind their counter, and Talk only
        reaches the tile right behind the sign (TownScreen._talk_to_direction).
        Montor East's shops have two merchants each, and autoplay Transacted
        across the fixed stand to nobody (user 2026-11-23). Stands with no
        counter (adjacent keepers) are returned as they are."""
        npcs = list(getattr(game_map, "npcs", ()))
        merchants = {
            (n.x, n.y) for n in npcs
            if str(getattr(n, "tile_name", "")).lower() == "merchant"
        }
        anyone = {(n.x, n.y) for n in npcs}

        def is_sign(x: int, y: int) -> bool:
            t = game_map.get_tile(x, y)
            return t is not None and getattr(t, "rule", "") == "signs"

        sx, sy = stand
        counter = next(
            ((dx, dy) for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0)) if is_sign(sx + dx, sy + dy)),
            None,
        )
        if counter is None:
            return stand
        dx, dy = counter
        if (sx + 2 * dx, sy + 2 * dy) in anyone:
            return stand  # a keeper (merchant, healer, ...) is across already
        ux, uy = dy, dx  # along the counter
        best: tuple[int, int] | None = None
        for sign in (1, -1):
            for k in range(1, 8):
                x, y = sx + sign * k * ux, sy + sign * k * uy
                if not is_sign(x + dx, y + dy):
                    break  # end of this counter
                if (x + 2 * dx, y + 2 * dy) in merchants:
                    if (x, y) in anyone and (x, y) != tuple(pos):
                        # Someone stands on this spot (Moon's fixed cleric
                        # at (48,50)): no route reaches it, and autoplay
                        # left town and came back forever (trace 2026-11-25).
                        break
                    if best is None or (
                        abs(x - pos[0]) + abs(y - pos[1]) < abs(best[0] - pos[0]) + abs(best[1] - pos[1])
                    ):
                        best = (x, y)
                    break
        return best if best is not None else stand

    @staticmethod
    def _direction_to_npc(game_map, px: int, py: int) -> int:
        """Return the pygame key pointing toward the shopkeeper within 1-2
        tiles of (px, py). Every shop stand's keeper is a merchant, and town
        people move now: a guard who wandered up north of De Grocer won the
        old first-found scan and autoplay Transacted with him forever
        ("Funny, no response!", user 2026-11-22). Merchants first, then
        anyone."""
        npcs = list(getattr(game_map, "npcs", ()))
        merchants = {
            (n.x, n.y) for n in npcs
            if str(getattr(n, "tile_name", "")).lower() == "merchant"
        }
        anyone = {(n.x, n.y) for n in npcs}
        for coords in (merchants, anyone):
            for key, (dx, dy) in (
                (pygame.K_UP, (0, -1)),
                (pygame.K_DOWN, (0, 1)),
                (pygame.K_RIGHT, (1, 0)),
                (pygame.K_LEFT, (-1, 0)),
            ):
                for dist in (1, 2):
                    if (px + dx * dist, py + dy * dist) in coords:
                        return key
        return pygame.K_UP

    @staticmethod
    def _can_level_at_british(member) -> bool:
        """Return True iff ``member.meet_lord_british()`` would advance them
        (LairWare: one level per visit, experience hundreds >= the max-HP
        hundreds, the Mark of Kings past level 5, 25 while Exodus stands)."""
        if member.is_dead():
            return False
        hp_level = int(member.level)
        if hp_level >= 25 or member.exp // 100 < hp_level:
            return False
        return hp_level <= 4 or bool(member.marks and member.marks[0])

    # Who takes chests with G once no APPAR UNEM caster is left alive (user
    # ruling 2026-11-22): the Thief (LairWare's +128 disarm bonus), then the
    # Fighter, then anyone else, the Wizard last.
    _G_OPENER_ORDER = (Profession.THIEF, Profession.FIGHTER, Profession.CLERIC)

    def _chest_opener(self, party) -> tuple[str, int] | None:
        """Who opens a chest: APPAR UNEM from a Cleric/Paladin/Druid with 5
        MP; while such a caster lives but lacks the MP, None (wait for mana,
        no trap). With no caster alive, G by the Thief, else the Fighter,
        the Wizard last: under LairWare nobody is trap-proof, but a party
        that never opens a chest never gets the gold to resurrect."""
        caster = self._find_caster(
            party, (Profession.CLERIC, Profession.PALADIN, Profession.DRUID), min_mp=5
        )
        if caster is not None:
            return ("cast", caster[0])
        if self._mana_caster(party) is not None:
            return None
        living = [i + 1 for i, m in enumerate(party.members) if not m.is_dead()]
        if not living:
            return None

        def rank(idx: int) -> tuple[int, int]:
            prof = party.members[idx - 1].profession
            order = self._G_OPENER_ORDER
            first = order.index(prof) if prof in order else (
                len(order) + 1 if prof == Profession.WIZARD else len(order)
            )
            return (first, idx)

        return ("get", min(living, key=rank))

    _CHEST_RISK_LEVEL = 8
    _RAID_MANA_TARGET = 15
    _mana_waiting = False

    @staticmethod
    def _mana_caster(party):
        """The living APPAR UNEM caster (Cleric/Paladin/Druid) who can ever
        afford it (max MP >= 5), or None."""
        return next(
            (
                m for m in party.members
                if not m.is_dead()
                and m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
                and m.max_mp >= 5
            ),
            None,
        )

    def _chest_too_risky(self, party) -> bool:
        """Leave dropped chests alone when nobody can open one safely and
        the party is weak (someone dead, or any living member below level
        8). Live trace 2026-11-22: the Cleric lay dead for 5,900 steps, a
        DEX-25 G set off the trap, the poisoned level-5 party met dragons
        on the way to a cure and wiped."""
        if self._chest_opener(party) is not None:
            return False
        if any(m.is_dead() for m in party.members):
            return True
        return any(m.level < self._CHEST_RISK_LEVEL for m in party.members)

    def _open_chest(self, state_machine, party, guarded: bool = True) -> int:
        """Open the chest underfoot the safest way available (G with the
        highest-dex member when nobody is safe)."""
        opener = self._chest_opener(party)
        if opener is not None and opener[0] == "cast":
            self._queue_text(self._cleric_cast(party, opener[1], "b"), enter=False)
            return self._emit_key(state_machine, pygame.K_c, guarded=guarded)
        if opener is not None:
            idx = opener[1]
        else:
            idx = max(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead()),
                key=lambda i: party.members[i - 1].dex,
                default=1,
            )
        self._queue_text(str(idx), enter=False)
        return self._emit_key(state_machine, pygame.K_g, guarded=guarded)

    @staticmethod
    def _cleric_cast(party, idx: int, rest: str) -> str:
        """Keys after C for a cleric spell cast by member ``idx`` (1-based):
        a two-discipline caster (Druid, Ranger) is first asked "Wizard or
        Cleric?" and answers C (LairWare UltimaSpellCombat.c:73-76 EitherChoose,
        125-136; user ruling Q56)."""
        from py_exodus.combat.magic import get_castable_spell_types

        prof = party.members[idx - 1].profession
        book = "c" if len(get_castable_spell_types(prof)) > 1 else ""
        return f"{idx}{book}{rest}"

    _ROD_BURN = ROD_BURN

    @classmethod
    def _rod_safe(cls, m) -> bool:
        return rod_safe(m)

    @classmethod
    def _rod_plan(cls, party, mark_idx: int) -> tuple[str, Any] | None:
        """planner.rod_plan, with the keys for a heal: ``("heal", keys)``
        after C (Sanctu Mani K or Sanctu C on the needer)."""
        plan = rod_plan(party, mark_idx)
        if plan is None:
            return None
        if plan[0] == "heal":
            _kind, n, caster, letter = plan
            return ("heal", cls._cleric_cast(party, caster, f"{letter}{n}"))
        return (plan[0], plan[1] if plan[0] == "touch" else None)

    @staticmethod
    def _find_caster(
        party, professions: tuple[Profession, ...], min_mp: int
    ) -> tuple[int, Profession] | None:
        for i, m in enumerate(party.members):
            if not m.is_dead() and m.profession in professions and m.mp >= min_mp:
                return (i + 1, m.profession)
        return None

    # Fountains this many levels up or down count as near (item 1).
    _FOUNTAIN_LEVELS = 1

    # A cure fountain this many moves away (same level) is used for poison
    # that isn't dire yet: at most 4 out and 4 back, under a dozen turns
    # with the turns, no MP and no ladder; any further and the poison is
    # carried (user ruling 2026-11-25).
    _CURE_DETOUR = 4

    @staticmethod
    def _poison_dire(party, z: int) -> bool:
        """A poisoned living member is under item 5's bar for this level
        (dungeon_hp_need): only then is poison worth a cure trip or an
        ALCORT (user ruling 2026-11-25: a poisoned party walked back to a
        cure fountain every time and was poisoned again, many round trips
        in the Fires of Hell)."""
        return any(
            not m.is_dead() and m.status == Status.POISONED and m.hp < dungeon_hp_need(m, z)
            for m in party.members
        )

    @staticmethod
    def _fountain_drinker(party, tile) -> int | None:
        """Who drinks (1-based) from the fountain ``tile``, or None.

        Heal fountain (full HP): the living member with the lowest share of
        max HP still below max. Cure fountain: the first poisoned living
        member. Acid, poison and plain fountains: nobody, ever."""
        living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
        if tile == DungeonTile.FOUNTAIN_HEAL:
            hurt = [(n, m) for n, m in living if m.hp < m.max_hp]
            if hurt:
                return min(hurt, key=lambda nm: (nm[1].hp / max(1, nm[1].max_hp), nm[0]))[0]
        elif tile == DungeonTile.FOUNTAIN_CURE:
            return next((n for n, m in living if m.status == Status.POISONED), None)
        return None

    def _wants_heal_fountain(self, party, z: int) -> bool:
        """A real HP need: a living member under item 5's bar for this
        level (dungeon_hp_need), a member who lacks a wanted mark is not
        safe for its rod (item 2), or turning back (item 5)."""
        return (
            self._rod_heal_wanted
            or self._retreating
            or any(not m.is_dead() and m.hp < dungeon_hp_need(m, z) for m in party.members)
        )

    def _dungeon_heal_cast(self, party, mark_z: int) -> str | None:
        """Keys after C to heal the living member furthest under the mark
        level's resume bar: Sanctu Mani (Cleric, Druid, 50 MP) for a gap
        over Sanctu's 30, else Sanctu (Cleric, Druid, Paladin, 10 MP)."""
        short = [
            (min(m.max_hp, dungeon_hp_need(m, mark_z) + m.max_hp // 20) - m.hp, i + 1)
            for i, m in enumerate(party.members) if not m.is_dead()
        ]
        gap, n = max(short, default=(0, 0))
        if gap <= 0:
            return None
        mani = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=50)
        if gap > 30 and mani is not None:
            return self._cleric_cast(party, mani[0], f"k{n}")
        sanctu = self._find_caster(party, (Profession.CLERIC, Profession.DRUID, Profession.PALADIN), min_mp=10)
        if sanctu is not None:
            return self._cleric_cast(party, sanctu[0], f"c{n}")
        return None

    def _fountain_goals(
        self, party, dmap, z: int, xy: tuple[int, int] | None = None
    ) -> set[tuple[int, int, int]]:
        """Fountains worth walking to (the loader types each by x & 3, so
        autoplay knows them all).

        A HEAL fountain on this level or the next one up or down, for a real
        HP need only (_wants_heal_fountain); when HP is the need it comes
        first, before any cure. Drinking fills HP far over that bar, so the
        fountain and the mark never take turns.

        Poison wants a CURE fountain: a heal fountain never cures (live
        trace 2026-11-25, trace_20261125-173226: a poisoned party at 97%
        walked to and from a heal fountain for ~5,000 steps). Poison is
        carried until dire (_poison_dire, latched as _cure_mode until cured
        or out of the dungeon): before that only a cure fountain
        within _CURE_DETOUR moves on this level counts. Once dire the route
        search takes the nearest by steps, ladders counted, on any level,
        except while turning back or under the bar for the next level down
        (item 5): then only cure fountains on this level or above, so a
        cure never takes a weak party deeper (review 2026-11-25)."""
        living = [m for m in party.members if not m.is_dead()]
        if self._wants_heal_fountain(party, z):
            heal = {
                (x, y, fz)
                for x, y, fz in self._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_HEAL})
                if abs(fz - z) <= self._FOUNTAIN_LEVELS
            }
            if heal:
                return heal
        if not any(m.status == Status.POISONED for m in living):
            return set()
        cure = self._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_CURE})
        if not self._cure_mode:
            # Poison is carried until dire (user ruling 2026-11-25): only a
            # cure fountain a few steps away, nearly free, is worth it.
            if xy is None:
                return set()
            return cure & dungeon_tiles_within(dmap, xy[0], xy[1], z, self._CURE_DETOUR)
        weak = self._retreating or any(
            not m.is_dead() and m.hp < dungeon_hp_need(m, z + 1) for m in party.members
        )
        if weak:
            cure = {(x, y, fz) for x, y, fz in cure if fz <= z}
        return cure

    @staticmethod
    def _find_dungeon_tiles(dmap, tiles: set[DungeonTile]) -> set[tuple[int, int, int]]:
        found: set[tuple[int, int, int]] = set()
        for z in range(dmap.levels):
            for y in range(dmap.height):
                for x in range(dmap.width):
                    if dmap.get_tile(x, y, z) in tiles:
                        found.add((x, y, z))
        return found
