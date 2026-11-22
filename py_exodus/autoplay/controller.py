"""Live input-driver AutoPlayController for Full Autoplay ("Watch Mode")."""
from __future__ import annotations

import sys

import random
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from py_exodus.autoplay.equipment import (
    best_hand_transfer,
    best_owned_armor,
    best_owned_weapon,
    best_shop_upgrade,
)
from py_exodus.autoplay.nav import (
    find_2d_step,
    find_2d_step_and_cost,
    find_dungeon_step,
    locked_door_passable,
    reachable_2d,
)
from py_exodus.autoplay.planner import (
    Goal,
    evaluate_goal,
    SHRINE_RESERVE,
    alcort_wisdom_gap,
    gold_has_a_use,
    next_shrine_goal,
    needs_heal,
    prefer_ranged_weapons,
)
from py_exodus.autoplay.threats import (
    SEA_MONSTERS,
    compute_threats,
    creature_name,
    foot_escape,
    manhattan,
    ship_escape,
    wrap_delta,
)
from py_exodus.autoplay.trip import (
    CRITICAL_SHIP_BOARD_PENALTY,
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
_TRIP_REPLAN_TURNS = 300
_TRIP_STUCK_TURNS = 30
_NEIGHBOURS4 = ((0, -1), (0, 1), (-1, 0), (1, 0))
_GATE_WAIT_TURNS = 6  # be at the gate this many turns before it opens
_GATE_ROAM_RADIUS = 5
_CHASE_RADIUS = 8  # land monsters this close count as chasing
_BLOCK_TURNS = 40  # a refused threatened tile stays barred this long
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
_DEATH_GULCH_GOLD_CAP = 9000  # same cap as the raid inside
# A party this strong walks up to pirates and fights them from land.
_PIRATE_HUNT_MIN_LEVEL = 8
_PIRATE_HUNT_RANGE = 10
_MAP_CASTLE_LB = 1
_MAP_EXODUS = 2
_MAP_DEATH_GULCH = 10
_MAP_AMBROSIA = 13
_PIRATE_SEA_MAPS: tuple[int, ...] = (_MAP_SOSARIA, _MAP_AMBROSIA)
_UNSAFE_REST_TOWN_MAPS: tuple[int, ...] = (_MAP_EXODUS, _MAP_DEATH_GULCH)
# ~2x a typical mainland town food run; leaves HP margin before starvation ticks kill a 0-food party.
_STARVING_AVOID_MAX_STEPS = 40

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
_FOOD_TOWNS: dict[int, tuple[int, int, tuple[int, int]]] = {
    1: (45, 18, (16, 20)),   # Castle British (20gp / 25 food; no counter, stand adjacent)
    3: (46, 19, (48, 49)),   # Britain (25gp / 25 food)
    4: (34, 16, (31, 17)),   # Yew (20gp / 25 food)
    6: (7, 44, (26, 25)),    # Grey (30gp / 25 food)
    11: (37, 53, (29, 41)),  # Dawn (25gp / 25 food; only selected when Dawn is open)
}

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
        self._hand_from_idx: int = 1
        self._hand_to_idx: int = 2
        self._food_packs: int = 1
        self._heal_patient_idx: int = 1
        self._talk_dir_key: int = pygame.K_UP
        self._mapped_dungeon_levels: set[tuple[int, int]] = set()
        # Overworld threat geometry for this tick (None off the overworld).
        self._threats = None
        self._overworld_avoid: set[tuple[int, int]] = set()
        # Trip follower state (the single owner of B/X).
        self._trip: TripPlan | None = None
        self._trip_frigates: frozenset[tuple[int, int]] = frozenset()
        self._trip_planned_at = 0
        self._trip_stuck = 0
        self._trip_last_pos: tuple[int, int] | None = None
        self._patrol_target: tuple[int, int] | None = None
        # Land tile the pirate hunt committed to (see _hunt_target).
        self._hunt_target: tuple[int, int] | None = None
        self._reach_cache = None
        # Coast tiles where a capture wait timed out, per map id.
        self._last_transition: Transition | None = None
        self._ow_turn = 0
        self._blocked_tiles: dict[tuple[int, int], int] = {}
        self._fleeing = False

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

    def _emit_key(self, state_machine: StateMachine, key: int, guarded: bool = True) -> int:
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
            mod=0,
            unicode=_key_to_unicode(key),
        )
        state_machine.handle_event(event)
        return key

    def _queue_text(self, text: str, enter: bool = True) -> None:
        for ch in text:
            k = _char_to_key(ch)
            if k is not None:
                self._key_queue.append(k)
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
        if screen_name == "ShrineScreen":
            return self._step_shrine(state_machine, screen)
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
            prompt = (getattr(screen.text_log, "prompt_text", "") or "").lower()
            if "name" in prompt:
                idx = len(screen.roster) + 1
                self._queue_text(f"HERO{idx}", enter=True)
            elif "strength" in prompt or "dexterity" in prompt:
                self._queue_text("15", enter=True)
            elif "intelligence" in prompt or "wisdom" in prompt:
                self._queue_text("10", enter=True)
            elif "sex" in prompt:
                self._queue_text("M", enter=False)
            elif "race" in prompt:
                self._queue_text("H", enter=False)
            elif "profession" in prompt or "class" in prompt:
                self._queue_text("F", enter=False)
            else:
                return self._emit_key(state_machine, pygame.K_RETURN)
            if self._key_queue:
                return self._emit_key(state_machine, self._key_queue.popleft())
            return None

        if len(screen.party.members) < 4:
            if len(screen.roster) > len(screen.party.members):
                char = screen.roster[screen.selected_roster_idx]
                in_party = any(
                    m.name.upper() == char.name.upper() for m in screen.party.members
                )
                if in_party:
                    return self._emit_key(state_machine, pygame.K_DOWN)
                return self._emit_key(state_machine, pygame.K_a)
            return self._emit_key(state_machine, pygame.K_c)

        return self._emit_key(state_machine, pygame.K_e)

    def _step_combat(self, state_machine: StateMachine, screen) -> int | None:
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
        """Donate toward the current planner.SHRINE_PLAN step only; leave
        when that step belongs to another shrine or is out of gold."""
        party = screen.party
        goal = next_shrine_goal(party)
        stat_attr = getattr(screen, "stat_attr", "strength")
        on_plan = goal is not None and goal[1] == stat_attr
        member = party.members[goal[0]] if on_plan else None
        spendable = max(0, party.gold - SHRINE_RESERVE) // 100
        if screen.state == screen.STATE_WHO:
            if member is not None and member.gold >= 100 and spendable >= 1:
                return self._emit_key(state_machine, pygame.K_1 + goal[0])
            return self._emit_key(state_machine, pygame.K_ESCAPE)
        if screen.state == screen.STATE_DONATE:
            chosen = party.get_member(screen.selected_member_idx)
            if member is None or chosen is not member:
                return self._emit_key(state_machine, pygame.K_0)
            amt = min(9, member.gold // 100, spendable, goal[3] - getattr(member, stat_attr, 0))
            return self._emit_key(state_machine, pygame.K_0 + max(0, amt))
        return self._emit_key(state_machine, pygame.K_ESCAPE)

    _CRITICAL_HULL_THRESHOLD = 30

    @classmethod
    def _is_hull_critical(cls, party, screen=None) -> bool:
        """Return True when the active ship hull is at or below the critical threshold (<= 30)."""
        hull = getattr(screen, "ship_hull", None) if screen is not None else None
        if hull is None:
            hull = getattr(party, "ship_hull", 50)
        return hull <= cls._CRITICAL_HULL_THRESHOLD

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
        if screen.text_log.is_waiting_for_input:
            return self._emit_key(state_machine, pygame.K_ESCAPE)

        party = screen.party
        dmap = getattr(screen, "dungeon_map", None) or getattr(screen, "dmap", None) or screen.state.dmap
        goal = evaluate_goal(party, map_id=self._screen_map_id(screen, party))

        # Peer a gem once per unseen dungeon level to legitimately map its layout
        level_key = (int(getattr(dmap, "id", 0)), int(screen.state.z))
        if level_key not in self._mapped_dungeon_levels:
            self._mapped_dungeon_levels.add(level_key)
            gem_holder = next((m for m in party.members if not m.is_dead() and m.gems > 0), None)
            if gem_holder is not None:
                gem_holder.gems -= 1
                if not getattr(screen, "show_minimap", False):
                    return self._emit_key(state_machine, pygame.K_p)

        # Touch a Mark tile when standing on one that living members still need
        mark_map = {
            DungeonTile.MARK_KINGS: 0,
            DungeonTile.MARK_FIRE: 1,
            DungeonTile.MARK_SNAKE: 2,
            DungeonTile.MARK_FORCE: 3,
        }
        cur_tile = getattr(screen.state, "current_tile", None)
        if cur_tile in mark_map:
            mark_idx = mark_map[cur_tile]
            need_idx = next(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.marks[mark_idx] == 0),
                None,
            )
            if need_idx is not None:
                self._queue_text(str(need_idx), enter=False)
                return self._emit_key(state_machine, pygame.K_s)

        # Ignite a torch or cast light spell whenever dungeon light is out
        if not getattr(screen.state, "is_torch_on", False):
            if any(not m.is_dead() and m.torches > 0 for m in party.members):
                return self._emit_key(state_machine, pygame.K_i)
            wiz = self._find_caster(party, (Profession.WIZARD,), min_mp=10)
            if wiz is not None:
                self._queue_text(f"{wiz[0]}c", enter=False)
                return self._emit_key(state_machine, pygame.K_c)
            cleric = self._find_caster(party, (Profession.CLERIC,), min_mp=15)
            if cleric is not None:
                self._queue_text(f"{cleric[0]}d", enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        target_tiles: set[tuple[int, int, int]] = set()
        if goal == Goal.GET_MARK_KINGS:
            target_tiles = self._find_dungeon_tiles(dmap, {DungeonTile.MARK_KINGS})
        elif goal == Goal.GET_REMAINING_MARKS:
            wanted: set[DungeonTile] = set()
            living = [m for m in party.members if not m.is_dead()]
            if not all(m.marks[1] > 0 for m in living):
                wanted.add(DungeonTile.MARK_FIRE)
            if not all(m.marks[2] > 0 for m in living):
                wanted.add(DungeonTile.MARK_SNAKE)
            if not all(m.marks[3] > 0 for m in living):
                wanted.add(DungeonTile.MARK_FORCE)
            if wanted:
                target_tiles = self._find_dungeon_tiles(dmap, wanted)

        if not target_tiles:
            target_tiles = {(1, 1, 0)}

        if (screen.state.x, screen.state.y, screen.state.z) == (1, 1, 0) and target_tiles == {(1, 1, 0)}:
            return self._emit_key(state_machine, pygame.K_k)

        key = find_dungeon_step(
            dmap,
            screen.state.x,
            screen.state.y,
            screen.state.z,
            screen.state.dir,
            target_tiles,
        )
        if key is not None:
            return self._emit_key(state_machine, key)
        return self._emit_key(state_machine, pygame.K_k)

    def _step_2d(self, state_machine: StateMachine, screen) -> int | None:
        if screen.text_log.is_waiting_for_input:
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

        # Cast resurrection spell on the spot if a Cleric has enough MP
        dead_idx = next((i + 1 for i, m in enumerate(party.members) if m.status == Status.DEAD), None)
        if dead_idx is not None:
            caster = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=65)
            if caster is not None:
                self._queue_text(f"{caster[0]}n{dead_idx}", enter=False)
                return self._emit_key(state_machine, pygame.K_c)
        ash_idx = next((i + 1 for i, m in enumerate(party.members) if m.status == Status.ASH), None)
        if ash_idx is not None:
            caster = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=75)
            if caster is not None:
                self._queue_text(f"{caster[0]}p{ash_idx}", enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # Cast ALCORT to cure poison on the spot if a Cleric/Druid has >= 35 MP
        poison_idx = next((i + 1 for i, m in enumerate(party.members) if m.status == Status.POISONED), None)
        if poison_idx is not None:
            caster = self._find_caster(party, (Profession.CLERIC, Profession.DRUID), min_mp=35)
            if caster is not None:
                self._queue_text(f"{caster[0]}h{poison_idx}", enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # Heal detour if hurt (skip during BUY_FOOD/starvation, and skip/save MP during CURE_POISON unless <= 25 HP)
        if (
            needs_heal(party)
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
                self._queue_text(f"{caster[0]}c{hurt_idx}", enter=False)
                return self._emit_key(state_machine, pygame.K_c)

        # TownScreen / City maps
        if type(screen).__name__ == "TownScreen":
            return self._step_town(state_machine, screen, party, px, py, goal)

        # OverworldScreen (Sosaria = 0, Ambrosia = 13)
        return self._step_overworld(state_machine, screen, party, px, py, goal)

    def _step_town(self, state_machine: StateMachine, screen, party, px: int, py: int, goal: Goal) -> int | None:
        gmap = screen.game_map
        map_id = getattr(gmap, "id", getattr(screen, "map_id", party.map_id))
        if (
            map_id not in _UNSAFE_REST_TOWN_MAPS
            and needs_heal(party)
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
            and party.gold < _DEATH_GULCH_GOLD_CAP
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
            if opener is not None and (px, py) in dg_chests:
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
            open_chests = dg_chests & reach
            # Out of MP for APPAR UNEM with chests still to open: wait here
            # until the caster has several casts' worth. Walking toward the
            # exit at 0-4 MP and back at 5 cost a round trip per chest.
            caster = self._mana_caster(party)
            if caster is not None and open_chests and (opener is None or self._mana_waiting):
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
                living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
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
            _, _, wep_xy, arm_xy = _SHOP_TOWNS[map_id]
            upgrade = best_shop_upgrade(party, include_wizard_dagger=True, include_dawn=(map_id == 11))
            if upgrade is not None and (not upgrade.dawn_only or map_id == 11):
                buyer = party.members[upgrade.member_idx - 1]
                if buyer.gold < upgrade.price:
                    self._join_gold_member_idx = upgrade.member_idx
                    return self._emit_key(state_machine, pygame.K_j)
                stand_xy = wep_xy if upgrade.kind == "weapon" else arm_xy
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

        if map_id in _GUILD_TOWNS and goal in (Goal.BUY_KEYS, Goal.BUY_GEMS, Goal.BUY_TORCHES):
            _, _, guild_xy = _GUILD_TOWNS[map_id]
            living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
            if living:
                if goal == Goal.BUY_KEYS:
                    cost, letter = 50, "c"
                elif goal == Goal.BUY_GEMS:
                    cost, letter = 75, "b"
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

        if map_id in _FOOD_TOWNS and goal not in (Goal.CURE_POISON, Goal.RESURRECT_DEAD):
            _, _, food_xy = _FOOD_TOWNS[map_id]
            living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
            if living:
                total_gold = party.gold
                food_price = {1: 20, 3: 25, 4: 20, 6: 30, 11: 25}.get(map_id, 30)
                if goal == Goal.BUY_FOOD and getattr(self, "_food_shop_target", None) is None:
                    if total_gold >= 1500:
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
                    packs_needed = max(1, (shop_target - buyer.food + 24) // 25)
                    low_food_count = sum(1 for _, m in living if m.food < shop_target)
                    if low_food_count > 1:
                        fair_packs = max(1, (total_gold // food_price) // low_food_count)
                        packs_needed = min(packs_needed, fair_packs)
                    if buyer.gold < total_gold and buyer.gold < min(packs_needed * food_price, 500):
                        self._join_gold_member_idx = buyer_idx
                        return self._emit_key(state_machine, pygame.K_j)
                    if (px, py) == food_xy:
                        self._food_packs = max(1, min(20, packs_needed, buyer.gold // food_price))
                        self._shop_member_idx = buyer_idx
                        self._talk_dir_key = self._direction_to_npc(gmap, px, py)
                        return self._emit_key(state_machine, pygame.K_t)
                    d = find_2d_step(
                        gmap, (px, py), food_xy, Transport.FOOT, party=party,
                        avoid_tiles=npc_tiles, prefer_paths=True,
                    )
                    if d is not None:
                        return self._emit_key(state_machine, _DIR_TO_KEY[d])
                else:
                    self._food_shop_target = None

        if map_id in _HEALER_TOWNS and goal in (Goal.RESURRECT_DEAD, Goal.CURE_POISON):
            _, _, healer_xy = _HEALER_TOWNS[map_id]
            living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
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

        # Default in town: walk to nearest exit border (e.g. Britain's east gate)
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
        d = find_2d_step(
            gmap, (px, py), exits, Transport.FOOT, party=party,
            avoid_tiles=npc_tiles, prefer_paths=True, allow_locked_doors=has_key,
        )
        if d is None and npc_tiles:
            d = find_2d_step(
                gmap, (px, py), exits, Transport.FOOT, party=party,
                prefer_paths=True, allow_locked_doors=has_key,
            )
        if d is not None:
            return self._step_or_unlock(state_machine, gmap, party, px, py, d)
        return self._emit_key(state_machine, pygame.K_SPACE)

    def _step_or_unlock(self, state_machine: StateMachine, gmap, party, px: int, py: int, d: Direction) -> int:
        nx, ny = px + d.dx, py + d.dy
        nxt_tile = gmap.get_tile(nx, ny) if 0 <= nx < gmap.width and 0 <= ny < gmap.height else None
        if nxt_tile is not None and str(getattr(nxt_tile, "name", "")).lower() == "locked_door":
            key_idx = next(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.keys > 0),
                None,
            )
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
        th = compute_threats(gmap, party, getattr(screen, "creatures", ()) or (), fight_squids=fight_squids)
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

        if not th.unsafe_end(pos):
            return None

        # Standing on a chest under fire: take it now (one action), then the
        # usual rule (fight or leave). Stepping off first made the party walk
        # back in for it, again and again (user report 2026-11-21).
        if not on_ship and not self._chest_too_risky(party) and any(
            str(o.get("tile", "")).lower() == "chest" and (o.get("x"), o.get("y")) == pos
            for o in getattr(party, "dynamic_objects", ()) or ()
        ):
            return self._open_chest(state_machine, party, guarded=False)

        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        if on_ship:
            hull = getattr(party, "ship_hull", 50)
            move = ship_escape(
                gmap,
                party,
                pos,
                getattr(screen, "heading", Direction.NORTH),
                th,
                lambda x, y: can_move_to(gmap, x, y, Transport.SHIP, party=party)
                or (has_key and self._is_locked_door(gmap, x, y)
                    and locked_door_passable(gmap, x, y, Transport.SHIP, party)),
                prefer_engage=hull >= 20 and not party_has_low_hp(party),
            )
        else:
            move = foot_escape(
                gmap,
                party,
                pos,
                th,
                lambda x, y: can_move_to(gmap, x, y, Transport.FOOT, party=party),
                prefer_engage=not party_has_low_hp(party) and not th.squid_engage,
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

    @staticmethod
    def _strong_vs_pirates(party) -> bool:
        """Healthy, unpoisoned and every living member at level 8+."""
        living = [m for m in party.members if not m.is_dead()]
        return (
            bool(living)
            and not party_has_low_hp(party)
            and all(m.status != Status.POISONED and m.level >= _PIRATE_HUNT_MIN_LEVEL for m in living)
        )

    def _pirate_hunt_step(self, gmap, party, pos, th) -> Direction | None:
        """First step of the shortest land path (lanes allowed) to a tile
        orthogonally next to a pirate, within _PIRATE_HUNT_RANGE steps."""
        w, h = gmap.width, gmap.height
        reach = self._foot_reachable(gmap, party, pos)
        engage = {
            ((p[0] + dx) % w, (p[1] + dy) % h)
            for p in th.pirates
            for dx, dy in _NEIGHBOURS4
        } & reach
        if not engage:
            return None
        seen = {pos}
        frontier: list[tuple[tuple[int, int], Direction | None]] = [(pos, None)]
        for _ in range(_PIRATE_HUNT_RANGE):
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
        if party.transport == Transport.SHIP and getattr(screen, "heading", d) != d:
            return key  # a turn: the ship stays on its (already safe) tile
        gmap = screen.game_map
        dest = ((party.x + d.dx) % gmap.width, (party.y + d.dy) % gmap.height)
        here = (party.x, party.y)
        w, h = gmap.width, gmap.height
        healthy = not party_has_low_hp(party) and (
            party.transport != Transport.SHIP or getattr(party, "ship_hull", 50) >= 20
        )
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
                for obj in getattr(party, "dynamic_objects", ())
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

        # Loot dropped chests on foot on Sosaria or Ambrosia (prefer APPAR_UNEM, else G with member 1)
        if (
            cur_map_id in _PIRATE_SEA_MAPS
            and party.transport == Transport.FOOT
            and not self._chest_too_risky(party)
        ):
            chests = {
                (obj.get("x"), obj.get("y"))
                for obj in getattr(party, "dynamic_objects", [])
                if str(obj.get("tile", "")).lower() == "chest"
            }
            if (px, py) in chests:
                return self._open_chest(state_machine, party)
            if chests and (
                goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN, Goal.AMBROSIA_CARDS_SHRINES)
                or (goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON) and not needs_heal(party))
            ):
                max_chest_dist = None if goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN, Goal.AMBROSIA_CARDS_SHRINES) else 4
                reachable_chests = {
                    pos for pos in chests
                    if (max_chest_dist is None or abs(pos[0] - px) + abs(pos[1] - py) <= max_chest_dist)
                    and find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
                }
                if reachable_chests:
                    self._overworld_avoid = self._monster_avoid(screen, party, px, py, goal, living)
                    return self._move_toward(state_machine, gmap, party, (px, py), reachable_chests)

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
            heading = getattr(screen, "heading", Direction.EAST)
            broadsides_horiz = heading in (Direction.NORTH, Direction.SOUTH)
            for c in getattr(screen, "creatures", []):
                tname = creature_name(c)
                if tname not in _CANNON_TARGETS or "x" not in c or "y" not in c:
                    continue
                # The cannon trace does not wrap (overworld _fire_cannons).
                dx = c["x"] - px
                dy = c["y"] - py
                if getattr(self, "_last_cannon_state", None) == (px, py, party.moves):
                    break
                if broadsides_horiz and dy == 0 and 1 <= abs(dx) <= 3:
                    self._last_cannon_state = (px, py, party.moves)
                    self._key_queue.append(pygame.K_RIGHT if dx > 0 else pygame.K_LEFT)
                    return self._emit_key(state_machine, pygame.K_f)
                if not broadsides_horiz and dx == 0 and 1 <= abs(dy) <= 3:
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
        nearby = [
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", [])
            if "x" in c and "y" in c
            and creature_name(c) != "whirlpool"
            and manhattan(gmap.width, gmap.height, (c["x"], c["y"]), (px, py)) <= evade_rad
        ]
        if nearby:
            wind = getattr(party, "wind_direction", None)
            if party.transport == Transport.SHIP and wind is None:
                return self._emit_key(state_machine, pygame.K_SPACE)
            blocked_dir = wind.reverse() if (party.transport == Transport.SHIP and wind is not None) else None
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
            and all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))
            and len(living) == len(party.members)
            # Raid until the Ambrosia trip is paid for and beyond: stopping
            # at 4500 left parties short of 4500 + food + keys, grinding
            # slowly (user ruling 2026-11-22: amass more gold first).
            and 400 <= party.gold < _DEATH_GULCH_GOLD_CAP
            # Never raid for gold nothing will spend (user ruling 2026-11-22).
            and gold_has_a_use(party)
            and sum(m.keys for m in living) >= 4
        )

    def _portal_dest(self, state_machine, screen, portals, label: str):
        """A portal Destination; arriving enters it (waiting for Dawn's double new moon)."""

        def _enter() -> int:
            party = screen.party
            if (party.x, party.y) == _DAWN_PORTAL and not self._dawn_open(screen):
                return self._emit_key(state_machine, pygame.K_SPACE)
            return self._emit_key(state_machine, pygame.K_e)

        return Destination(frozenset(portals), Transport.FOOT, label), _enter

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
            if snake_active and cur_map_id == 0:
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
            ) or frozenset({(50, 13), (17, 48)})
            return (
                Destination(whirlpools, Transport.SHIP, "whirlpool", moving=True),
                lambda: self._emit_key(sm, pygame.K_SPACE),
            )

        if goal == Goal.GET_MARK_KINGS:
            return self._portal_dest(sm, screen, {(46, 7)}, "dungeon_kings")

        if goal == Goal.GET_REMAINING_MARKS:
            if not all(m.marks[1] > 0 and m.marks[3] > 0 for m in living):
                return self._portal_dest(sm, screen, {(49, 34)}, "dungeon_fire_force")
            return self._portal_dest(sm, screen, {(58, 44)}, "dungeon_snake")

        if goal == Goal.BUY_FOOD:
            dawn = self._dawn_open(screen)
            portals = {(i[0], i[1]) for mid, i in _FOOD_TOWNS.items() if mid != 11 or dawn}
            return self._portal_dest(sm, screen, portals, "food" + ("+dawn" if dawn else ""))

        if goal in (Goal.RESURRECT_DEAD, Goal.CURE_POISON):
            dawn = self._dawn_open(screen)
            portals = {(i[0], i[1]) for mid, i in _HEALER_TOWNS.items() if mid != 11 or dawn}
            return self._portal_dest(sm, screen, portals, "healer" + ("+dawn" if dawn else ""))

        if goal in (Goal.BUY_KEYS, Goal.BUY_GEMS, Goal.BUY_TORCHES):
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
                self._queue_text(str(living_idx), enter=False)
                return self._emit_key(sm, pygame.K_s)

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
        last_ship = getattr(party, "last_ship", None)
        low_hull = self._is_hull_critical(party, screen)
        out: dict[tuple[int, int], float] = {}
        for obj in getattr(party, "dynamic_objects", ()):
            if str(obj.get("tile", "")).lower() != "frigate":
                continue
            wreck = low_hull and (obj is last_ship or last_ship is None)
            out[(obj.get("x"), obj.get("y"))] = CRITICAL_SHIP_BOARD_PENALTY if wreck else 0.0
        return out

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
            hull_critical=(mode == Transport.SHIP and self._is_hull_critical(party, screen)),
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

    def _trip_drive(self, state_machine, screen, gmap, party, px, py, map_id, dest):
        """Advance the committed trip toward ``dest``. Returns a key, _ARRIVED or None (no route)."""
        self._ow_turn += 1
        pos = (px, py)
        mode = Transport.SHIP if party.transport == Transport.SHIP else Transport.FOOT
        if pos == self._trip_last_pos:
            self._trip_stuck += 1
        else:
            self._trip_stuck = 0
        self._trip_last_pos = pos

        plan = self._trip
        # A finished gate hop: we stand on the destination site.
        if plan is not None and plan.legs and plan.legs[0].action == "GATE":
            gates = getattr(gmap, "moongates", ()) or ()
            gd = plan.legs[0].gate_dest
            if gd is not None and gd < len(gates) and pos == (gates[gd].x, gates[gd].y):
                plan.legs.pop(0)
                self._trip_stuck = 0
        frig_sig = frozenset(self._frigate_costs(party, screen))
        waiting = plan is not None and plan.legs and plan.legs[0].action in ("GATE", "CAPTURE") and pos == plan.legs[0].end
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
        if leg.action == "ARRIVE":
            if pos in dest.tiles and (dest.need is None or dest.need == mode):
                return _ARRIVED
            # Head for the tile the plan chose; only drifting targets
            # (whirlpools) are re-read every tick.
            target = set(dest.tiles) if dest.moving else {leg.end}
            return self._move_toward(state_machine, gmap, party, pos, target)

        if leg.action == "GATE":
            return self._drive_gate(state_machine, screen, gmap, party, pos, leg)

        # A capture leg is a hunt/patrol along that water's coast: once the
        # planned coast tile is reachable on foot, the capture driver steers.
        # (Pulling the party back to leg.end first undid every patrol step,
        # pacing two tiles forever; rules-c84c7c6 batch, 2026-11-22.)
        if leg.action == "CAPTURE" and leg.end in self._foot_reachable(gmap, party, pos):
            return self._drive_capture(state_machine, screen, gmap, party, pos, leg, map_id)

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
        """Take moongate ``src`` to ``dst`` without standing around.

        User rule (2026-11-21): watch the phases, roam the area fighting what
        comes until the gate is about to open, and be next to it in time.
        The phase steps every 4 surface turns; an open gate stays one phase.
        """
        gates = getattr(gmap, "moongates", ()) or ()
        src, dst = leg.gate_src, leg.gate_dest
        if src is None or dst is None or src >= len(gates):
            self._trip = None
            return self._emit_key(state_machine, pygame.K_SPACE)
        site = (gates[src].x, gates[src].y)
        w, h = gmap.width, gmap.height
        self._trip_stuck = 0
        k = self._phases_until_gate(party, src, dst)
        turns_left = 4 * k
        dist = manhattan(w, h, pos, site)
        if dist == 1:
            if k == 0 and getattr(screen, "trammel_phase", -1) == src and getattr(screen, "felucca_phase", -1) == dst:
                d = next(
                    d for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST)
                    if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) == site
                )
                return self._emit_key(state_machine, _DIR_TO_KEY[d])
            if turns_left <= _GATE_WAIT_TURNS:
                return self._emit_key(state_machine, pygame.K_SPACE)  # opens in moments
        adjacent = {
            ((site[0] + dx) % w, (site[1] + dy) % h)
            for dx, dy in _NEIGHBOURS4
        }
        if turns_left <= dist + _GATE_WAIT_TURNS:
            return self._move_toward(state_machine, gmap, party, pos, adjacent)
        # Roam near the gate: fight what is around, else wander a little.
        prey = {
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", ()) or ()
            if "x" in c and "y" in c
            and creature_name(c) not in SEA_MONSTERS and creature_name(c) != "whirlpool"
            and manhattan(w, h, site, (c["x"], c["y"])) <= _GATE_ROAM_RADIUS + 3
        }
        if prey:
            return self._move_toward(state_machine, gmap, party, pos, prey)
        reach = self._foot_reachable(gmap, party, pos)
        if self._patrol_target is None or pos == self._patrol_target or self._patrol_target not in reach \
                or manhattan(w, h, self._patrol_target, site) > _GATE_ROAM_RADIUS:
            near = [t for t in reach if 1 <= manhattan(w, h, t, site) <= _GATE_ROAM_RADIUS and t != pos]
            self._patrol_target = random.choice(near) if near else None
        if self._patrol_target is None:
            return self._move_toward(state_machine, gmap, party, pos, adjacent)
        return self._move_toward(state_machine, gmap, party, pos, {self._patrol_target})

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
        for d in (Direction.NORTH, Direction.SOUTH, Direction.WEST, Direction.EAST):
            if ((pos[0] + d.dx) % w, (pos[1] + d.dy) % h) in pirates:
                return self._attack(state_machine, d)
        reach = self._foot_reachable(gmap, party, pos)
        if pirates:
            engage = {
                ((p[0] + dx) % w, (p[1] + dy) % h)
                for p in pirates
                for dx, dy in _NEIGHBOURS4
            }
            engage = {t for t in engage if t in reach and not (th is not None and th.unsafe_end(t))}
            if engage:
                tgt = self._hunt_target_for(gmap, pos, reach, engage, pirates, th)
                return self._move_toward(state_machine, gmap, party, pos, {tgt})
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
                    return self._move_toward(state_machine, gmap, party, pos, {tgt})
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
                avoid_tiles={(n.x, n.y) for n in fixed}, prefer_paths=True,
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

    def _foot_reachable(self, gmap, party, pos) -> frozenset[tuple[int, int]]:
        """Land tiles reachable on foot from ``pos`` (cached per map/turn)."""
        key = (id(gmap), pos, self._ow_turn)
        if self._reach_cache is not None and self._reach_cache[0] == key:
            return self._reach_cache[1]
        terr = terrain_for(gmap, party, getattr(gmap, "id", 0))
        seen = {pos}
        stack = [pos]
        while stack:
            cur = stack.pop()
            for n in terr.neighbours(*cur):
                if n not in seen and n in terr.foot:
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

    def _grind_local(self, state_machine, screen, gmap, party, px, py, living) -> int:
        # Actively chase nearby reachable land creatures (skip if hurt,
        # unless broke & starving with no naval threat nearby so we can earn 30g for food!)
        transport = Transport.FOOT if party.transport != Transport.SHIP else Transport.SHIP
        broke_and_starving = self._broke_and_starving(screen, gmap, party, px, py, living)
        if transport == Transport.FOOT and (not needs_heal(party) or broke_and_starving):
            land_targets: set[tuple[int, int]] = set()
            for c in getattr(screen, "creatures", []):
                tname = creature_name(c)
                if tname == "whirlpool" or tname in SEA_MONSTERS:
                    continue
                cx, cy = c.get("x"), c.get("y")
                if cx is None or cy is None:
                    continue
                if manhattan(gmap.width, gmap.height, (px, py), (cx, cy)) <= 12:
                    land_targets.add((cx, cy))
            if land_targets:
                d = find_2d_step(gmap, (px, py), land_targets, Transport.FOOT, party=party, avoid_tiles=self._overworld_avoid)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        if transport == Transport.FOOT:
            early_patrol = ((42, 18), (38, 17), (35, 17), (40, 22), (45, 22), (46, 20))
            patrol = early_patrol if (living and min(m.level for m in living) < 3) else _SOSARIA_PATROL
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

        transfer = best_hand_transfer(party)
        if transfer is not None:
            self._hand_from_idx, self._hand_to_idx = transfer
            return self._emit_key(state_machine, pygame.K_h)

        return None

    def _handle_town_prompt(self, state_machine: StateMachine, screen) -> int | None:
        prompt = (getattr(screen.text_log, "current_prompt", "") or "").lower()
        if "join gold" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._join_gold_member_idx)
        if "from member" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._hand_from_idx)
        if "to member" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._hand_to_idx)
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
        if "anything else" in prompt or "anything else" in last_msg or "give blood" in prompt or "more help" in prompt:
            return self._emit_key(state_machine, pygame.K_n)
        if "(y or n)" in prompt or "take it" in prompt or "deal" in prompt:
            return self._emit_key(state_machine, pygame.K_y)
        if "how many packs" in prompt:
            self._queue_text(str(self._food_packs), enter=True)
            return self._emit_key(state_machine, self._key_queue.popleft())
        if "how many" in prompt:
            self._queue_text("1", enter=True)
            return self._emit_key(state_machine, self._key_queue.popleft())
        if "buy" in prompt or "what" in prompt or "wat'l" in prompt or "choice" in prompt or "(a-" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._shop_item_letter) or pygame.K_b)
        return self._emit_key(state_machine, pygame.K_ESCAPE)

    def _move_toward(
        self,
        state_machine: StateMachine,
        game_map,
        party,
        start: tuple[int, int],
        goals: set[tuple[int, int]],
    ) -> int:
        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        starving_buy_food = (
            any(not m.is_dead() and m.food == 0 for m in party.members)
            and evaluate_goal(party, getattr(game_map, "id", getattr(party, "map_id", 0))) == Goal.BUY_FOOD
        )
        avoid = getattr(self, "_overworld_avoid", None) or None
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
            avoid = (self._threats.hard_avoid() if self._threats is not None else None) or None
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
            party.transport == Transport.SHIP
            and wind is not None
            and party.food >= 100
            and start not in (avoid or ())
            and not getattr(self, "_ship_threat_near", False)
        ):
            free_d, free_cost = find_2d_step_and_cost(
                game_map,
                start=start,
                goals=goals,
                transport=party.transport,
                party=party,
                avoid_tiles=avoid,
                ignore_wind=True,
            )
            if free_d is not None and free_cost is not None and (
                d is None or (wind_cost is not None and wind_cost * 2 > free_cost * 3)
            ):
                if free_d == wind.reverse():
                    return self._emit_key(state_machine, pygame.K_SPACE)
                # Advance along the wind-free shortest route while its next heading is allowed,
                # holding only when reaching the pinch/turn where wind actually blocks free_d.
                d = free_d
        if d is None and avoid:
            # Drop the soft avoidance but keep the hard threats (pirate lanes,
            # squid reach): the lane guard would refuse those steps anyway.
            hard = self._threats.hard_avoid() if self._threats is not None else set()
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
            if d is None and hard:
                # Walled in by threats: take the plain route; _lane_guard lets a
                # healthy party advance on the threat and bars the tile otherwise.
                d = find_2d_step(
                    game_map,
                    start=start,
                    goals=goals,
                    transport=party.transport,
                    party=party,
                    wind_direction=wind,
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
        """Return True iff ``member.meet_lord_british()`` would actually advance their level."""
        if member.is_dead() or member.level >= 25:
            return False
        eligible_level = member.exp // 100 + 1
        if not member.marks or member.marks[0] == 0:
            eligible_level = min(eligible_level, 5)
        return eligible_level > member.level

    # dex + 25 >= randrange(100) always evades a chest trap (chests.py).
    _TRAP_PROOF_DEX = 74

    def _chest_opener(self, party) -> tuple[str, int] | None:
        """Who opens a chest without risking a trap: APPAR UNEM from a
        Cleric/Paladin/Druid with 5 MP, else G by a member whose dexterity
        always dodges (74+). None = nobody can open one safely."""
        caster = self._find_caster(
            party, (Profession.CLERIC, Profession.PALADIN, Profession.DRUID), min_mp=5
        )
        if caster is not None:
            return ("cast", caster[0])
        idx = next(
            (i + 1 for i, m in enumerate(party.members)
             if not m.is_dead() and m.dex >= self._TRAP_PROOF_DEX),
            None,
        )
        return ("get", idx) if idx is not None else None

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
            self._queue_text(f"{opener[1]}b", enter=False)
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
    def _find_caster(
        party, professions: tuple[Profession, ...], min_mp: int
    ) -> tuple[int, Profession] | None:
        for i, m in enumerate(party.members):
            if not m.is_dead() and m.profession in professions and m.mp >= min_mp:
                return (i + 1, m.profession)
        return None

    @staticmethod
    def _find_dungeon_tiles(dmap, tiles: set[DungeonTile]) -> set[tuple[int, int, int]]:
        found: set[tuple[int, int, int]] = set()
        for z in range(dmap.levels):
            for y in range(dmap.height):
                for x in range(dmap.width):
                    if dmap.get_tile(x, y, z) in tiles:
                        found.add((x, y, z))
        return found
