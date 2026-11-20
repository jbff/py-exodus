"""Live input-driver AutoPlayController for Full Autoplay ("Watch Mode")."""
from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from py_exodus.autoplay.economy_runtime import EconomyRuntime
from py_exodus.autoplay.hazard_runtime import HazardRuntime
from py_exodus.autoplay.equipment import (
    best_hand_transfer,
    best_owned_armor,
    best_owned_weapon,
    best_shop_upgrade,
)
from py_exodus.autoplay.nn_policy import CombatNNPolicy
from py_exodus.autoplay.nav import find_2d_step, find_2d_step_and_cost, find_dungeon_step
from py_exodus.autoplay.planner import (
    Goal,
    evaluate_goal,
    member_needs_shrine_stat,
    needs_heal,
    prefer_ranged_weapons,
)
from py_exodus.constants import ArmorType, Direction, Profession, Status, Transport, WeaponType
from py_exodus.world.map import DungeonTile

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from py_exodus.state_machine import StateMachine

_DIR_TO_KEY: dict[Direction, int] = {
    Direction.NORTH: pygame.K_UP,
    Direction.SOUTH: pygame.K_DOWN,
    Direction.WEST: pygame.K_LEFT,
    Direction.EAST: pygame.K_RIGHT,
}

_MAP_SOSARIA = 0
_MAP_CASTLE_LB = 1
_MAP_EXODUS = 2
_MAP_DEATH_GULCH = 10
_MAP_AMBROSIA = 13
_PIRATE_SEA_MAPS: tuple[int, ...] = (_MAP_SOSARIA, _MAP_AMBROSIA)
_UNSAFE_REST_TOWN_MAPS: tuple[int, ...] = (_MAP_EXODUS, _MAP_DEATH_GULCH)
_PIRATE_STANDOFF_DIST = 3
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
_GUILD_TOWNS: dict[int, tuple[int, int, tuple[int, int]]] = {
    11: (37, 53, (34, 21)),  # Dawn
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

    def __init__(
        self,
        enabled: bool = False,
        step_interval: float = 0.08,
        nn_combat: bool = False,
        nn_device: str = "auto",
    ) -> None:
        self.enabled = enabled
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
        # Loop-breaker state (memory layer): emitted-key history + optional
        # transport lock. See the loop-breaker block near _emit_key.
        # NN strategy layer: hazard critic risk maps -> A* edge costs;
        # economy critic -> yield-scored prey selection. Both inert unless
        # trained checkpoints exist AND their env flags are set.
        self._hazard = HazardRuntime()
        self._economy = EconomyRuntime()
        self._step_history: deque[tuple] = deque(maxlen=self._HISTORY_MAX)
        self._transport_locked: str | None = None
        self._lock_no_cycle_ticks: int = 0
        self._lock_age_ticks: int = 0
        # NN combat policy: loaded once at startup and kept resident for the
        # whole session (combat is frequent; reloading per fight is a no-go).
        self.nn_combat_policy: CombatNNPolicy | None = (
            CombatNNPolicy(device=nn_device) if nn_combat else None
        )

    def toggle(self) -> bool:
        """Flip autoplay enabled state and clear any queued keystrokes."""
        self.enabled = not self.enabled
        self._key_queue.clear()
        self._timer = 0.0
        return self.enabled

    #: Full Autoplay is built and trained around exactly one party shape:
    #: Thief + Fighter + Cleric + Wizard (4 members). A user party with
    #: other professions would take the controller down untested paths —
    #: refuse to engage on those (F9 does nothing; a mid-session --autoplay
    #: gets disabled at the first gameplay screen).
    CANONICAL_PROFESSIONS = frozenset(
        {"THIEF", "FIGHTER", "CLERIC", "WIZARD"}
    )

    @staticmethod
    def _party_is_canonical(screen) -> bool | None:
        """True/False if the screen's party composition is checkable."""
        party = getattr(screen, "party", None)
        if party is None:
            return None
        members = list(getattr(party, "members", []) or [])
        if len(members) != 4:
            return False
        professions = {
            getattr(getattr(m, "profession", None), "name", "").upper() for m in members
        }
        return professions == AutoPlayController.CANONICAL_PROFESSIONS

    def can_engage(self, state_machine: StateMachine) -> bool:
        """Whether F9 engagement is allowed for the current screen.

        Start/Roster screens are exempt: autoplay builds the canonical
        party itself there. Screens without a party (menus, etc.) are too.
        """
        screen = state_machine.current_screen
        if screen is None or type(screen).__name__ in ("StartScreen", "RosterScreen"):
            return True
        return self._party_is_canonical(screen) is not False

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

    def _emit_key(self, state_machine: StateMachine, key: int) -> int:
        self._record_step(self._current_step_signature(state_machine, key))
        event = pygame.event.Event(
            pygame.KEYDOWN,
            key=key,
            mod=0,
            unicode=_key_to_unicode(key),
        )
        state_machine.handle_event(event)
        return key

    # --- loop-breaker (memory layer over the goal ladder) --------------------
    #
    # Root cause it addresses (2026-11-20 B/X starvation at Britain): the
    # controller is an if-ladder with no memory, so two branches that both
    # fire on the same party state oscillate forever (FOOT "board" branch
    # vs SHIP "disembark-to-shop" branch), burning a food unit per pass.
    # The break: record emitted-key signatures, detect a repeating
    # transport-action cycle, derive the goal-correct transport, and lock
    # out the contrary transport action until the pattern actually stops.

    _HISTORY_MAX = 16
    _OSC_MIN_HISTORY = 6
    _LOCK_RELEASE_TICKS = 12
    _LOCK_MAX_TICKS = 600
    #: The observed oscillation class: alternating board/disembark.
    _TRANSPORT_CYCLE_KEYS = frozenset({pygame.K_b, pygame.K_x})

    def _current_step_signature(self, state_machine: StateMachine, key: int) -> tuple:
        screen = state_machine.current_screen
        party = getattr(screen, "party", None)
        if party is not None:
            if hasattr(screen, "avatar_x"):
                pos = (screen.avatar_x, screen.avatar_y)
            else:
                pos = (party.x, party.y)
            map_id = self._screen_map_id(screen, party)
        else:
            pos, map_id = (-1, -1), -1
        return (type(screen).__name__, map_id, pos, key)

    def _record_step(self, signature: tuple) -> None:
        self._step_history.append(signature)

    def _detect_transport_oscillation(self) -> bool:
        """True when the recent history repeats a board/disembark cycle.

        Only alternating transport-action cycles (B/X) are treated as
        oscillation — standing still and repeating one action (grinding
        attacks, waiting at a shrine) is not one.
        """
        h = self._step_history
        if len(h) < self._OSC_MIN_HISTORY:
            return False
        tail = tuple(h)[-8:]
        n = len(tail)
        # Period-2: ... A B A B (>= 4 entries), all at one position.
        if n >= 4:
            a, b = tail[-2], tail[-1]
            if (
                a != b
                and a[3] in self._TRANSPORT_CYCLE_KEYS
                and b[3] in self._TRANSPORT_CYCLE_KEYS
                and a[:3] == b[:3]
                and tail[-4] == a
                and tail[-3] == b
            ):
                return True
        # Longer period-2 core with noise: A B A B A at one position.
        if n >= 5:
            seq = [(s[0], s[1], s[2], s[3]) for s in tail]
            for start in range(0, n - 4):
                w = seq[start : start + 5]
                if (
                    w[0] == w[2] == w[4]
                    and w[1] == w[3]
                    and w[0] != w[1]
                    and w[0][3] in self._TRANSPORT_CYCLE_KEYS
                    and w[1][3] in self._TRANSPORT_CYCLE_KEYS
                ):
                    return True
        return False

    def _desired_transport(self, goal_name: str, party) -> str:
        """The transport the goal actually wants, mirroring the branch rules."""
        if goal_name in ("SAIL_WHIRLPOOL", "CAPTURE_SHIP", "DIG_EXOTICS", "CONQUER_EXODUS"):
            return "SHIP"
        if goal_name in ("OUTFIT_BRITAIN", "BUY_FOOD", "RESURRECT_DEAD", "CURE_POISON"):
            return "FOOT"
        if goal_name in ("GRIND_AND_LEVEL", "GET_MARK_KINGS"):
            from py_exodus.constants import ArmorType, WeaponType

            living = [m for m in party.members if not m.is_dead()]
            ready_for_sea = bool(living) and all(
                m.level >= 5 and m.marks[0] > 0 for m in living
            ) and all(m.marks[0] > 0 for m in party.members)
            has_exotics = all(
                (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
                and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
                for m in party.members
            )
            return "SHIP" if ready_for_sea and not has_exotics else "FOOT"
        return "FOOT"

    def _engage_transport_lock(self, desired: str, reason: str = "") -> None:
        self._transport_locked = desired
        self._lock_no_cycle_ticks = 0
        self._lock_age_ticks = 0
        logger.warning(
            "Autoplay loop-breaker: transport lock engaged (%s, desired=%s) "
            "after repeating %s cycle; history tail: %s",
            reason,
            desired,
            reason,
            list(self._step_history)[-6:],
        )

    def _release_transport_lock(self) -> None:
        self._transport_locked = None
        self._lock_no_cycle_ticks = 0

    def _tick_loop_breaker(self, state_machine: StateMachine) -> None:
        if self._detect_transport_oscillation():
            self._lock_no_cycle_ticks = 0
            if self._transport_locked is None:
                screen = state_machine.current_screen
                party = getattr(screen, "party", None)
                if party is None:
                    return
                goal = evaluate_goal(
                    party, map_id=self._screen_map_id(screen, party)
                )
                self._engage_transport_lock(
                    self._desired_transport(goal.name, party),
                    reason=f"{goal.name}",
                )
        elif self._transport_locked is not None:
            self._lock_no_cycle_ticks += 1
            self._lock_age_ticks += 1
            if (
                self._lock_no_cycle_ticks >= self._LOCK_RELEASE_TICKS
                or self._lock_age_ticks >= self._LOCK_MAX_TICKS
            ):
                self._release_transport_lock()

    def _transport_action_allowed(self, key: int, desired: str, safety: bool = False) -> bool:
        """Gate for transport actions: safety disembarks always pass."""
        if safety:
            return True
        if self._transport_locked is None:
            return True
        if desired == "SHIP":
            return key != pygame.K_x  # block disembark, not board
        if desired == "FOOT":
            return key != pygame.K_b  # block board, not disembark
        return True

    def _transport_emit_allowed(self, state_machine: StateMachine, key: int) -> bool:
        """Gate for board/disembark emission sites (goal-aware)."""
        if self._transport_locked is None:
            return True
        screen = state_machine.current_screen
        party = getattr(screen, "party", None)
        if party is None:
            return True
        goal = evaluate_goal(party, map_id=self._screen_map_id(screen, party))
        return self._transport_action_allowed(
            key, self._desired_transport(goal.name, party)
        )

    def _queue_text(self, text: str, enter: bool = True) -> None:
        for ch in text:
            k = _char_to_key(ch)
            if k is not None:
                self._key_queue.append(k)
        if enter:
            self._key_queue.append(pygame.K_RETURN)

    def step(self, state_machine: StateMachine) -> int | None:
        """Emit one logical input step for the active screen."""
        state_machine.autoplay_enabled = self.enabled
        state_machine.autoplay_step_interval = self.step_interval
        screen = state_machine.current_screen
        if screen is None:
            return None

        self._tick_loop_breaker(state_machine)

        screen_name = type(screen).__name__
        if screen_name == "FinalScreen":
            self._key_queue.clear()
            return None

        # Composition guard: refuse to run on any non-canonical party.
        # Roster building is exempt (autoplay constructs the party there);
        # party.members keeps dead members, so a wipe mid-run never trips.
        if self.enabled and screen_name not in ("StartScreen", "RosterScreen"):
            if self._party_is_canonical(screen) is False:
                self.enabled = False
                state_machine.autoplay_enabled = False
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
        # NN combat policy drives the arena directly (hybrid_eval pattern).
        # No symbolic fallback on this branch: an NN failure raises.
        # step_combat returns None after acting, or a key to emit.
        policy = self.nn_combat_policy
        if policy is not None:
            key = policy.step_combat(state_machine, screen)
            if key is None:
                return None  # policy acted directly on the arena
            return self._emit_key(state_machine, key)
        if screen.arena.is_finished:
            self._key_queue.clear()
            return self._emit_key(state_machine, pygame.K_RETURN)
        if not screen.auto_combat:
            return self._emit_key(state_machine, pygame.K_TAB)
        return None

    def _step_shrine(self, state_machine: StateMachine, screen) -> int | None:
        if screen.state == screen.STATE_WHO:
            stat_attr = getattr(screen, "stat_attr", "strength")
            cap_attr = getattr(screen, "stat_cap_attr", "max_str")
            needed_idx = next(
                (
                    i + 1
                    for i, m in enumerate(screen.party.members)
                    if m.gold >= 100 and member_needs_shrine_stat(m, stat_attr, cap_attr)
                ),
                None,
            )
            if needed_idx is None:
                needed_idx = next(
                    (i + 1 for i, m in enumerate(screen.party.members) if not m.is_dead() and m.gold >= 100),
                    1,
                )
            return self._emit_key(state_machine, pygame.K_0 + needed_idx)
        if screen.state == screen.STATE_DONATE:
            member = screen.party.get_member(screen.selected_member_idx)
            gold = member.gold if member is not None else 0
            stat_attr = getattr(screen, "stat_attr", "strength")
            cap_attr = getattr(screen, "stat_cap_attr", "max_str")
            room = (
                max(0, getattr(member, cap_attr, 99) - getattr(member, stat_attr, 0))
                if member is not None
                else 9
            )
            spendable = max(0, screen.party.gold - 150)
            amt = min(9, gold // 100, spendable // 100, max(1, room))
            if amt >= 1:
                return self._emit_key(state_machine, pygame.K_0 + amt)
            return self._emit_key(state_machine, pygame.K_0)
        return self._emit_key(state_machine, pygame.K_ESCAPE)

    _CRITICAL_HULL_THRESHOLD = 30

    @classmethod
    def _is_hull_critical(cls, party, screen=None) -> bool:
        """Return True when the active ship hull is at or below the critical threshold (<= 30)."""
        hull = getattr(screen, "ship_hull", None) if screen is not None else None
        if hull is None:
            hull = getattr(party, "ship_hull", 50)
        return hull <= cls._CRITICAL_HULL_THRESHOLD

    def _get_any_shore_water(self, gmap, party) -> frozenset[tuple[int, int]]:
        """Return cached water tiles adjacent to FOOT-walkable land on this map."""
        from py_exodus.screens.overworld import can_move_to

        has_fire = any(not m.is_dead() and m.marks[1] > 0 for m in party.members)
        has_force = any(not m.is_dead() and m.marks[2] > 0 for m in party.members)
        cache = getattr(self, "_any_shore_water_cache", None)
        if cache is None:
            cache = {}
            self._any_shore_water_cache = cache
        key = (getattr(gmap, "id", 0), has_fire, has_force)
        if key not in cache:
            cache[key] = frozenset(
                (wx, wy)
                for wy in range(gmap.height)
                for wx in range(gmap.width)
                if str(getattr(gmap.get_tile(wx, wy), "name", "")).lower() == "water"
                and any(
                    can_move_to(
                        gmap,
                        (wx + dx) % gmap.width,
                        (wy + dy) % gmap.height,
                        Transport.FOOT,
                        party=party,
                    )
                    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                )
            )
        return cache[key]

    @staticmethod
    def _safe_shore_water(
        gmap,
        party,
        screen,
        shore_tiles: set[tuple[int, int]] | frozenset[tuple[int, int]],
    ) -> set[tuple[int, int]]:
        """Filter out shore tiles whose walkable land is pirate-adjacent when an alternate exists."""
        from py_exodus.screens.overworld import can_move_to

        pirates = [
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", ())
            if str(c.get("tile_name") or c.get("tile") or "").lower() == "pirate"
            and "x" in c and "y" in c
        ]
        if not pirates:
            return set(shore_tiles)

        def _is_pirate_adjacent_landing(wx: int, wy: int) -> bool:
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                lx, ly = (wx + dx) % gmap.width, (wy + dy) % gmap.height
                ntile = gmap.get_tile(lx, ly)
                if (
                    ntile is not None
                    and not getattr(ntile, "swimmable", False)
                    and can_move_to(gmap, lx, ly, Transport.FOOT, party=party)
                    and any(
                        min((lx - px_) % gmap.width, (px_ - lx) % gmap.width)
                        + min((ly - py_) % gmap.height, (py_ - ly) % gmap.height) <= 1
                        for px_, py_ in pirates
                    )
                ):
                    return True
            return False

        safe = {pt for pt in shore_tiles if not _is_pirate_adjacent_landing(*pt)}
        return safe if safe else set(shore_tiles)

    @classmethod
    def _boardable_frigates(cls, party, include_damaged: bool = False, screen=None) -> set[tuple[int, int]]:
        """Return frigate coordinates, skipping a critically damaged last_ship."""
        last_ship = getattr(party, "last_ship", None)
        low_hull = cls._is_hull_critical(party, screen)
        return {
            (obj.get("x"), obj.get("y"))
            for obj in getattr(party, "dynamic_objects", ())
            if str(obj.get("tile", "")).lower() == "frigate"
            and (include_damaged or not (low_hull and (obj is last_ship or last_ship is None)))
        }

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
            and party.food >= 100
            and not any(not m.is_dead() and m.food == 0 for m in party.members)
            and goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON)
            and not any(not m.is_dead() and m.status == Status.POISONED and m.hp <= 25 for m in party.members)
            and any(
                not m.is_dead()
                and m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
                and m.max_mp >= 10
                for m in party.members
            )
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
                        has_force = any(not m.is_dead() and m.marks[2] > 0 for m in party.members)
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
            and party.gold < 9000
            and party.food >= 40
            and all(not m.is_dead() and m.hp > 100 for m in party.members)
        ):
            dg_chests = {
                (x, y)
                for y in range(gmap.height)
                for x in range(gmap.width)
                if "chest" in str(getattr(gmap.get_tile(x, y), "name", "")).lower()
            }
            if (px, py) in dg_chests:
                caster = self._find_caster(
                    party, (Profession.CLERIC, Profession.PALADIN, Profession.DRUID), min_mp=5
                )
                if caster is not None:
                    self._queue_text(f"{caster[0]}b", enter=False)
                    return self._emit_key(state_machine, pygame.K_c)
                self._queue_text("1", enter=False)
                return self._emit_key(state_machine, pygame.K_g)
            has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
            if dg_chests:
                d = find_2d_step(
                    gmap, (px, py), dg_chests, Transport.FOOT, party=party,
                    avoid_tiles=npc_tiles, allow_locked_doors=has_key,
                )
                if d is not None:
                    return self._step_or_unlock(state_machine, gmap, party, px, py, d)
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

                    reachable = {(px, py)}
                    rq = deque([(px, py)])
                    while rq:
                        rx, ry = rq.popleft()
                        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                            nx, ny = rx + dx, ry + dy
                            if (nx, ny) in reachable or not (0 <= nx < gmap.width and 0 <= ny < gmap.height):
                                continue
                            if (nx, ny) in npc_tiles:
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

        if map_id in _SHOP_TOWNS and goal == Goal.OUTFIT_BRITAIN and getattr(self, "_food_shop_target", None) is None:
            _, _, wep_xy, arm_xy = _SHOP_TOWNS[map_id]
            upgrade = best_shop_upgrade(party, include_wizard_dagger=True)
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
                d = find_2d_step(
                    gmap, (px, py), guild_xy, Transport.FOOT, party=party,
                    avoid_tiles=npc_tiles, prefer_paths=True,
                )
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

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
                        self._food_shop_target = 200
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

    def _hunt_starving_prey_or_patrol(
        self, state_machine: StateMachine, screen, gmap, party, px: int, py: int, living
    ) -> int:
        if any(m.food == 0 for m in living) and party.gold < 30:
            land_prey = {
                (c["x"], c["y"])
                for c in getattr(screen, "creatures", ())
                if str(c.get("tile_name") or c.get("tile") or "").lower()
                not in ("pirate", "serpent", "squid", "manowar", "whirlpool")
                and "x" in c and "y" in c
                and find_2d_step(gmap, (px, py), {(c["x"], c["y"])}, Transport.FOOT, party=party) is not None
            }
            if land_prey:
                return self._move_toward(state_machine, gmap, party, (px, py), land_prey)
        coast = [
            (45, 12), (47, 20), (43, 37), (30, 43), (19, 41), (8, 45),
            (19, 41), (30, 43), (43, 37), (47, 20), (44, 16),
        ]
        reachable_coast = [
            pt for pt in coast
            if pt == (px, py) or find_2d_step(gmap, (px, py), {pt}, Transport.FOOT, party=party) is not None
        ]
        if not reachable_coast:
            from collections import deque
            from py_exodus.screens.overworld import can_move_to

            island = {(px, py)}
            iq = deque([(px, py)])
            while iq:
                cx, cy = iq.popleft()
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    nx, ny = (cx + dx) % gmap.width, (cy + dy) % gmap.height
                    if (nx, ny) not in island and can_move_to(gmap, nx, ny, Transport.FOOT, party=party):
                        island.add((nx, ny))
                        iq.append((nx, ny))
            reachable_coast = sorted(
                {
                    (ix, iy)
                    for ix, iy in island
                    if any(
                        str(getattr(gmap.get_tile((ix + dx) % gmap.width, (iy + dy) % gmap.height), "name", "")).lower() == "water"
                        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                    )
                }
            ) or coast
        pirates = [
            (c["x"], c["y"])
            for c in getattr(screen, "creatures", ())
            if str(c.get("tile_name") or c.get("tile") or "").lower() == "pirate"
            and "x" in c and "y" in c
        ]
        if pirates:
            target = min(
                reachable_coast,
                key=lambda pt: min(abs(pt[0] - px_) + abs(pt[1] - py_) for px_, py_ in pirates),
            )
            pirate_near_target = any(
                abs(target[0] - px_) + abs(target[1] - py_) <= 6 for px_, py_ in pirates
            )
            if (px, py) == target and not pirate_near_target:
                self._patrol_idx += 1
                target = reachable_coast[self._patrol_idx % len(reachable_coast)]
        else:
            target = reachable_coast[self._patrol_idx % len(reachable_coast)]
            if (px, py) == target:
                self._patrol_idx += 1
                target = reachable_coast[self._patrol_idx % len(reachable_coast)]
        return self._move_toward(state_machine, gmap, party, (px, py), {target})

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

    def _step_overworld(self, state_machine: StateMachine, screen, party, px: int, py: int, goal: Goal) -> int | None:
        gmap = screen.game_map
        cur_map_id = self._screen_map_id(screen, party)
        living = [m for m in party.members if not m.is_dead()]

        # CURE_POISON on the overworld: with no on-the-spot ALCORT caster
        # (2026-11-20 live-run stall at the Death Gulch portal — the goal
        # previously only had an in-town handler), walk to the nearest
        # reachable healer-town entry. On SHIP, disembark at any walkable
        # coast first; once on FOOT this branch takes over and enters the
        # town.
        if goal == Goal.CURE_POISON and cur_map_id == 0:
            if party.transport == Transport.SHIP:
                from py_exodus.screens.overworld import can_move_to

                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    lx, ly = (px + dx) % gmap.width, (py + dy) % gmap.height
                    if can_move_to(gmap, lx, ly, Transport.FOOT, party=party):
                        return self._emit_key(state_machine, pygame.K_x)
            else:
                healer_entries = [
                    (t[0], t[1]) for t in _HEALER_TOWNS.values()
                ]
                reachable = [
                    entry
                    for entry in healer_entries
                    if find_2d_step(gmap, (px, py), {entry}, Transport.FOOT, party=party) is not None
                ]
                if reachable:
                    best = min(
                        reachable,
                        key=lambda e: (
                            find_2d_step_and_cost(gmap, (px, py), {e}, Transport.FOOT, party=party)[1]
                            or 10**9
                        ),
                    )
                    return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, best)

        # Loot dropped chests on foot on Sosaria or Ambrosia (prefer APPAR_UNEM, else G with member 1)
        if cur_map_id in _PIRATE_SEA_MAPS and party.transport == Transport.FOOT:
            chests = {
                (obj.get("x"), obj.get("y"))
                for obj in getattr(party, "dynamic_objects", [])
                if str(obj.get("tile", "")).lower() == "chest"
            }
            if (px, py) in chests:
                caster = self._find_caster(
                    party, (Profession.CLERIC, Profession.PALADIN, Profession.DRUID), min_mp=5
                )
                if caster is not None:
                    self._queue_text(f"{caster[0]}b", enter=False)
                    return self._emit_key(state_machine, pygame.K_c)
                self._queue_text("1", enter=False)
                return self._emit_key(state_machine, pygame.K_g)
            if chests and (
                goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN, Goal.CAPTURE_SHIP, Goal.AMBROSIA_CARDS_SHRINES)
                or (goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON) and not needs_heal(party))
            ):
                max_chest_dist = None if goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN, Goal.CAPTURE_SHIP, Goal.AMBROSIA_CARDS_SHRINES) else 4
                reachable_chests = {
                    pos for pos in chests
                    if (max_chest_dist is None or abs(pos[0] - px) + abs(pos[1] - py) <= max_chest_dist)
                    and find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
                }
                if reachable_chests:
                    return self._move_toward(state_machine, gmap, party, (px, py), reachable_chests)
            has_exotics = all(
                (m.weapon == WeaponType.EXOTIC or m.weapons.get(WeaponType.EXOTIC, 0) > 0)
                and (m.armor == ArmorType.EXOTIC or m.armors.get(ArmorType.EXOTIC, 0) > 0)
                for m in living
            )
            on_mainland = (px, py) == (46, 19) or find_2d_step(gmap, (px, py), {(46, 19)}, Transport.FOOT, party=party) is not None
            ready_for_sea = all(m.level >= 5 for m in living) and all(m.marks[0] > 0 for m in party.members)
            has_remaining_marks = all(any(m.marks[i] > 0 for m in living) for i in (1, 2, 3))
            wants_death_gulch = (
                goal == Goal.GRIND_AND_LEVEL
                and not any(self._can_level_at_british(m) for m in living)
                and has_exotics
                and has_remaining_marks
                and len(living) == len(party.members)
                and 400 <= party.gold < 4500
                and sum(m.keys for m in living) >= 4
            )
            if not wants_death_gulch and goal not in (
                Goal.DIG_EXOTICS,
                Goal.AMBROSIA_CARDS_SHRINES,
                Goal.EXIT_AMBROSIA,
                Goal.GET_MARK_KINGS,
                Goal.GET_REMAINING_MARKS,
                Goal.CONQUER_EXODUS,
            ) and (
                (
                    not has_exotics
                    and ready_for_sea
                    and goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN, Goal.GET_MARK_KINGS)
                )
                or not on_mainland
            ):
                hull_val = getattr(screen, "ship_hull", getattr(party, "ship_hull", 50))
                frigates = self._boardable_frigates(
                    party,
                    include_damaged=(
                        not on_mainland
                        and not self._is_hull_critical(party, screen)
                        and goal != Goal.GET_REMAINING_MARKS
                    ),
                    screen=screen,
                )
                if (px, py) in frigates:
                    if self._transport_emit_allowed(state_machine, pygame.K_b):
                        return self._emit_key(state_machine, pygame.K_b)
                    return None  # loop-breaker: boarding locked out this cycle
                reachable_frigates = {
                    pos for pos in frigates
                    if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
                }
                if reachable_frigates:
                    return self._move_toward(state_machine, gmap, party, (px, py), reachable_frigates)

        gear_key = self._maybe_manage_gear(
            state_machine, party, prefer_ranged=prefer_ranged_weapons(party)
        )
        if gear_key is not None:
            return gear_key

        # Low-level parties on foot avoid coastal sea monsters; ships avoid sea monsters & fire broadsides
        avoid_monsters: set[tuple[int, int]] = set()
        self._ship_threat_near = False
        if cur_map_id in _PIRATE_SEA_MAPS and party.transport == Transport.SHIP:
            heading = getattr(screen, "heading", Direction.EAST)
            broadsides_horiz = heading in (Direction.NORTH, Direction.SOUTH)
            cannon_targets = {
                "pirate", "serpent", "squid",
                "dragon", "devil", "balron", "gargoyle", "daemon",
                "griffin", "wyvern", "minotaur", "hydra", "lich",
                "giant", "troll", "pincher", "snatch", "mage", "wizard",
            }
            for c in getattr(screen, "creatures", []):
                tname = str(c.get("tile_name") or c.get("tile") or "").lower()
                if "x" not in c or "y" not in c:
                    continue
                cx, cy = c["x"], c["y"]
                if tname == "whirlpool" and cur_map_id == 0 and goal != Goal.SAIL_WHIRLPOOL:
                    avoid_monsters.add((cx, cy))
                    for ox, oy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                        avoid_monsters.add(((cx + ox) % gmap.width, (cy + oy) % gmap.height))
                    continue
                if tname not in cannon_targets:
                    continue
                dx_e = cx - px
                dx_w = px - cx
                dy_s = cy - py
                dy_n = py - cy
                if (
                    broadsides_horiz
                    and cy == py
                    and (1 <= dx_e <= 3 or 1 <= dx_w <= 3)
                    and getattr(self, "_last_cannon_state", None) != (px, py, party.moves)
                ):
                    self._last_cannon_state = (px, py, party.moves)
                    self._key_queue.append(pygame.K_RIGHT if 1 <= dx_e <= 3 else pygame.K_LEFT)
                    return self._emit_key(state_machine, pygame.K_f)
                if (
                    not broadsides_horiz
                    and cx == px
                    and (1 <= dy_s <= 3 or 1 <= dy_n <= 3)
                    and getattr(self, "_last_cannon_state", None) != (px, py, party.moves)
                ):
                    self._last_cannon_state = (px, py, party.moves)
                    self._key_queue.append(pygame.K_DOWN if 1 <= dy_s <= 3 else pygame.K_UP)
                    return self._emit_key(state_machine, pygame.K_f)
                if tname in ("pirate", "serpent", "squid") and goal != Goal.CAPTURE_SHIP:
                    if abs(cx - px) + abs(cy - py) <= 5:
                        self._ship_threat_near = True
                    avg_max_hp = (
                        sum(m.max_hp for m in living) // max(1, len(living))
                        if living
                        else 0
                    )
                    rad = 3 if (tname in ("serpent", "squid") and avg_max_hp < 600) else 2
                    for ox in range(-rad, rad + 1):
                        for oy in range(-rad, rad + 1):
                            if abs(ox) + abs(oy) <= rad:
                                avoid_monsters.add(((cx + ox) % gmap.width, (cy + oy) % gmap.height))
                    if tname == "pirate":
                        for step_d in range(1, 5):
                            for dx_p, dy_p in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                                lx, ly = cx + dx_p * step_d, cy + dy_p * step_d
                                if 0 <= lx < gmap.width and 0 <= ly < gmap.height:
                                    avoid_monsters.add((lx, ly))
        elif cur_map_id == 0 and party.transport != Transport.SHIP and living:
            avg_max_hp = sum(m.max_hp for m in party.members) // max(1, len(party.members))
            broke_and_starving_nav = (
                party.gold < 30
                and any(m.food == 0 for m in living)
                and all(m.hp * 10 >= m.max_hp * 3 for m in living)
            )
            avoid_all_land = (
                goal in (Goal.RESURRECT_DEAD, Goal.CURE_POISON, Goal.BUY_FOOD)
                or (needs_heal(party) and not broke_and_starving_nav)
            )
            for c in getattr(screen, "creatures", []):
                tname = str(c.get("tile_name") or c.get("tile") or "").lower()
                if "x" not in c or "y" not in c or tname == "whirlpool":
                    continue
                is_sea = tname in ("pirate", "serpent", "squid")
                if (is_sea and (avg_max_hp < 400 or avoid_all_land)) or (not is_sea and avoid_all_land):
                    cx, cy = c["x"], c["y"]
                    rad = 2 if (avoid_all_land and (is_sea or goal in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON))) else 1
                    for ox in range(-rad, rad + 1):
                        for oy in range(-rad, rad + 1):
                            if abs(ox) + abs(oy) <= rad:
                                avoid_monsters.add(((cx + ox) % gmap.width, (cy + oy) % gmap.height))
        self._overworld_avoid = avoid_monsters

        if (
            cur_map_id in _PIRATE_SEA_MAPS
            and party.transport == Transport.SHIP
            and self._is_hull_critical(party, screen)
        ):
            shore_water = self._safe_shore_water(
                gmap, party, screen, self._get_any_shore_water(gmap, party)
            )
            if (px, py) in shore_water:
                return self._emit_key(state_machine, pygame.K_x)
            if shore_water:
                return self._move_toward(state_machine, gmap, party, (px, py), shore_water)

        if goal == Goal.DIG_EXOTICS:
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
            dig_target: tuple[int, int, int] | None = None
            if need_wpn_idx is not None and need_arm_idx is not None:
                def _wrap_dist(tx: int, ty: int) -> int:
                    dx = abs(tx - px)
                    dy = abs(ty - py)
                    return min(dx, gmap.width - dx) + min(dy, gmap.height - dy)
                if _wrap_dist(19, 44) <= _wrap_dist(33, 3):
                    dig_target = (19, 44, need_arm_idx)
                else:
                    dig_target = (33, 3, need_wpn_idx)
            elif need_arm_idx is not None:
                dig_target = (19, 44, need_arm_idx)
            elif need_wpn_idx is not None:
                dig_target = (33, 3, need_wpn_idx)

            if dig_target is not None:
                tx, ty, m_idx = dig_target
                if (px, py) == (tx, ty):
                    if party.transport == Transport.SHIP:
                        return self._emit_key(state_machine, pygame.K_x)
                    self._queue_text("DIG", enter=True)
                    self._queue_text(str(m_idx), enter=False)
                    return self._emit_key(state_machine, pygame.K_o)
                if party.transport == Transport.SHIP:
                    adj_water = {
                        ((tx + dx) % gmap.width, (ty + dy) % gmap.height)
                        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                        if str(getattr(gmap.get_tile((tx + dx) % gmap.width, (ty + dy) % gmap.height), "name", "")).lower() == "water"
                    }
                    if (px, py) in adj_water:
                        return self._emit_key(state_machine, pygame.K_x)
                    return self._move_toward(state_machine, gmap, party, (px, py), adj_water or {(tx, ty)})
                if find_2d_step(gmap, (px, py), {(tx, ty)}, Transport.FOOT, party=party) is not None:
                    return self._move_toward(state_machine, gmap, party, (px, py), {(tx, ty)})
                hull_val = getattr(screen, "ship_hull", getattr(party, "ship_hull", 50))
                frigates = self._boardable_frigates(
                    party,
                    include_damaged=(
                        not on_mainland
                        and not self._is_hull_critical(party, screen)
                        and goal != Goal.GET_REMAINING_MARKS
                    ),
                    screen=screen,
                )
                if (px, py) in frigates:
                    if self._transport_emit_allowed(state_machine, pygame.K_b):
                        return self._emit_key(state_machine, pygame.K_b)
                    return None  # loop-breaker: boarding locked out this cycle
                reachable_frigates = {
                    pos for pos in frigates
                    if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
                }
                if reachable_frigates:
                    return self._move_toward(state_machine, gmap, party, (px, py), reachable_frigates)
                return self._hunt_starving_prey_or_patrol(state_machine, screen, gmap, party, px, py, living)

        if goal == Goal.CONQUER_EXODUS:
            snake_tile = gmap.get_tile(10, 58)
            snake_active = snake_tile is not None and str(getattr(snake_tile, "name", "")).startswith("snake")
            if snake_active and cur_map_id == 0:
                if (px, py) == (10, 59) and party.transport == Transport.SHIP:
                    snake_idx = next(
                        (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.marks[2] > 0),
                        1,
                    )
                    self._queue_text(str(snake_idx), enter=False)
                    self._queue_text("EVOCARE", enter=True)
                    return self._emit_key(state_machine, pygame.K_y)
                if party.transport == Transport.SHIP:
                    return self._move_toward(state_machine, gmap, party, (px, py), {(10, 59)})
                frigates = self._boardable_frigates(party, screen=screen)
                if (px, py) in frigates:
                    if self._transport_emit_allowed(state_machine, pygame.K_b):
                        return self._emit_key(state_machine, pygame.K_b)
                    return None  # loop-breaker: boarding locked out this cycle
                reachable_frigates = {
                    pos for pos in frigates
                    if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
                }
                if reachable_frigates:
                    return self._move_toward(state_machine, gmap, party, (px, py), reachable_frigates)
                return self._hunt_starving_prey_or_patrol(state_machine, screen, gmap, party, px, py, living)
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (10, 53))

        if goal in (Goal.AMBROSIA_CARDS_SHRINES, Goal.EXIT_AMBROSIA):
            return self._step_ambrosia(state_machine, gmap, party, px, py, goal, living)

        if goal == Goal.SAIL_WHIRLPOOL:
            whirlpools = {
                (c["x"], c["y"])
                for c in getattr(screen, "creatures", ())
                if str(c.get("tile_name") or c.get("tile") or "").lower() == "whirlpool"
                and "x" in c and "y" in c
            }
            return self._move_toward(
                state_machine, gmap, party, (px, py), whirlpools or {(50, 13), (17, 48)}
            )

        if goal == Goal.CAPTURE_SHIP:
            frigates = self._boardable_frigates(party, include_damaged=False)
            if (px, py) in frigates:
                if self._transport_emit_allowed(state_machine, pygame.K_b):
                    return self._emit_key(state_machine, pygame.K_b)
                return None  # loop-breaker: boarding locked out this cycle
            reachable_frigates = {
                pos
                for pos in frigates
                if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
            }
            if reachable_frigates:
                return self._move_toward(state_machine, gmap, party, (px, py), reachable_frigates)
            return self._hunt_starving_prey_or_patrol(state_machine, screen, gmap, party, px, py, living)

        starving_on_food_route = (
            goal == Goal.BUY_FOOD
            and any(not m.is_dead() and m.food == 0 for m in living)
        )
        if (
            cur_map_id in _PIRATE_SEA_MAPS
            and party.transport == Transport.SHIP
            and goal != Goal.CAPTURE_SHIP
            and not starving_on_food_route
        ):
            nearby_pirates = [
                (c["x"], c["y"])
                for c in getattr(screen, "creatures", ())
                if str(c.get("tile_name") or c.get("tile") or "").lower() == "pirate"
                and "x" in c and "y" in c
                and min((c["x"] - px) % gmap.width, (px - c["x"]) % gmap.width)
                + min((c["y"] - py) % gmap.height, (py - c["y"]) % gmap.height) < _PIRATE_STANDOFF_DIST
            ]
            if nearby_pirates:
                from py_exodus.screens.overworld import can_move_to

                wind = getattr(party, "wind_direction", None)
                blocked_dir = wind.reverse() if wind is not None else None
                best_dir = None
                best_dist = -1
                for d, (dx, dy) in (
                    (Direction.NORTH, (0, -1)),
                    (Direction.SOUTH, (0, 1)),
                    (Direction.WEST, (-1, 0)),
                    (Direction.EAST, (1, 0)),
                ):
                    if wind is None or d == blocked_dir:
                        continue
                    nx, ny = (px + dx) % gmap.width, (py + dy) % gmap.height
                    if not can_move_to(gmap, nx, ny, transport=Transport.SHIP, party=party):
                        continue
                    min_d = min(
                        min((nx - cx) % gmap.width, (cx - nx) % gmap.width)
                        + min((ny - cy) % gmap.height, (cy - ny) % gmap.height)
                        for cx, cy in nearby_pirates
                    )
                    if min_d > best_dist:
                        best_dist = min_d
                        best_dir = d
                if best_dir is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[best_dir])

        if cur_map_id == _MAP_SOSARIA and needs_heal(party):
            # Emergency step away only when a monster is within 1 tile (radius 2-3 is routed around via _overworld_avoid)
            evade_rad = 3 if party.transport == Transport.SHIP else 1
            nearby = [
                (c["x"], c["y"])
                for c in getattr(screen, "creatures", [])
                if "x" in c and "y" in c and abs(c["x"] - px) + abs(c["y"] - py) <= evade_rad
            ]
            if nearby:
                wind = getattr(party, "wind_direction", None)
                if party.transport == Transport.SHIP and wind is None:
                    return self._emit_key(state_machine, pygame.K_SPACE)
                from py_exodus.screens.overworld import can_move_to

                blocked_dir = wind.reverse() if (party.transport == Transport.SHIP and wind is not None) else None
                best_dir = None
                best_dist = -1
                for d, (dx, dy) in ((Direction.NORTH, (0, -1)), (Direction.SOUTH, (0, 1)), (Direction.WEST, (-1, 0)), (Direction.EAST, (1, 0))):
                    if d == blocked_dir:
                        continue
                    nx, ny = (px + dx) % gmap.width, (py + dy) % gmap.height
                    if not can_move_to(gmap, nx, ny, transport=party.transport, party=party):
                        continue
                    min_d = min(abs(nx - cx) + abs(ny - cy) for cx, cy in nearby)
                    if min_d > best_dist:
                        best_dist = min_d
                        best_dir = d
                if best_dir is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[best_dir])
            threat_near = any(
                "x" in c and "y" in c and max(
                    min((c["x"] - px) % gmap.width, (px - c["x"]) % gmap.width),
                    min((c["y"] - py) % gmap.height, (py - c["y"]) % gmap.height),
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
            # 1. Evade nearby creatures (<=5) before resting (handled above).
            # 2. Never pass turns on SHIP, when threat_near (<=7), or after taking damage on this tile.
            # 3. Never pass turns while starving (food == 0 / <100) or in town/urgent goals, or above 70% HP.
            if (
                not threat_near
                and not took_hit_here
                and party.food >= 100
                and not any(m.food == 0 for m in living)
                and any(not m.is_dead() and m.max_hp > 0 and m.hp * 10 < m.max_hp * 7 for m in living)
                and goal not in (Goal.BUY_FOOD, Goal.RESURRECT_DEAD, Goal.CURE_POISON)
                and any(
                    not m.is_dead()
                    and m.profession in (Profession.CLERIC, Profession.PALADIN, Profession.DRUID)
                    and m.max_mp >= 10
                    for m in party.members
                )
            ):
                return self._emit_key(state_machine, pygame.K_SPACE)

        if goal == Goal.GET_MARK_KINGS:
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (46, 7))

        if goal == Goal.GET_REMAINING_MARKS:
            if not all(m.marks[1] > 0 and m.marks[3] > 0 for m in living):
                return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (49, 34))
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (58, 44))

        if goal == Goal.BUY_FOOD:
            dawn_open = (
                getattr(screen, "trammel_phase", 0) == 0
                and getattr(screen, "felucca_phase", 0) == 0
            )
            food_portals = [
                (info[0], info[1])
                for mid, info in _FOOD_TOWNS.items()
                if mid != 11 or dawn_open
            ]
            target_portal = self._nearest_reachable_portal(
                gmap, px, py, party.transport, food_portals, party=party
            )
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, target_portal)

        if goal in (Goal.RESURRECT_DEAD, Goal.CURE_POISON):
            dawn_open = (
                getattr(screen, "trammel_phase", 0) == 0
                and getattr(screen, "felucca_phase", 0) == 0
            )
            healer_portals = [
                (info[0], info[1])
                for mid, info in _HEALER_TOWNS.items()
                if mid != 11 or dawn_open
            ]
            target_portal = self._nearest_reachable_portal(
                gmap, px, py, party.transport, healer_portals, party=party
            )
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, target_portal)

        if goal in (Goal.BUY_KEYS, Goal.BUY_GEMS, Goal.BUY_TORCHES):
            guild_portals = [(info[0], info[1]) for info in _GUILD_TOWNS.values()]
            target_portal = self._nearest_reachable_portal(
                gmap, px, py, party.transport, guild_portals, party=party
            )
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, target_portal)

        if goal == Goal.OUTFIT_BRITAIN:
            upgrade = best_shop_upgrade(party)
            if upgrade is not None and upgrade.dawn_only:
                target_portal = (_SHOP_TOWNS[11][0], _SHOP_TOWNS[11][1])
            else:
                target_portal = self._nearest_shop_town_portal(gmap, px, py, party.transport, party=party)
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, target_portal)

        wants_death_gulch = (
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
            and 400 <= party.gold < 4500
            and sum(m.keys for m in living) >= 4
        )

        if cur_map_id == 0 and party.transport == Transport.SHIP and not wants_death_gulch and goal not in (
            Goal.SAIL_WHIRLPOOL,
            Goal.CAPTURE_SHIP,
            Goal.DIG_EXOTICS,
        ):
            from py_exodus.screens.overworld import can_move_to

            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                lx, ly = (px + dx) % gmap.width, (py + dy) % gmap.height
                if can_move_to(gmap, lx, ly, Transport.FOOT, party=party) and (
                    (lx, ly) == (46, 19) or find_2d_step(gmap, (lx, ly), {(46, 19)}, Transport.FOOT, party=party) is not None
                ):
                    # Loop-breaker: when a transport cycle lock holds against
                    # disembarking, fall through to the sailing fallback
                    # below instead of oscillating.
                    if self._transport_emit_allowed(state_machine, pygame.K_x):
                        return self._emit_key(state_machine, pygame.K_x)
            return self._move_toward(
                state_machine,
                gmap,
                party,
                (px, py),
                {
                    (46, 12), (46, 13), (46, 14), (45, 15), (45, 16),
                    (48, 22), (48, 23), (49, 24), (24, 42), (25, 42),
                },
            )

        # GRIND_AND_LEVEL
        if cur_map_id == 0 and party.transport == Transport.FOOT and not on_mainland and not wants_death_gulch:
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (45, 18))
        if any(self._can_level_at_british(m) for m in living):
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (45, 18))
        if wants_death_gulch:
            return self._enter_portal_or_wait_dawn(state_machine, screen, gmap, party, px, py, (56, 31))

        # Actively chase nearby reachable land creatures on Sosaria (skip if hurt,
        # unless broke & starving with no naval threat nearby so we can earn 30g for food!)
        naval_threat_near = any(
            str(c.get("tile_name") or c.get("tile") or "").lower() in ("pirate", "serpent", "squid")
            and "x" in c and "y" in c
            and max(
                min((c["x"] - px) % gmap.width, (px - c["x"]) % gmap.width),
                min((c["y"] - py) % gmap.height, (py - c["y"]) % gmap.height),
            ) <= 7
            for c in getattr(screen, "creatures", [])
        )
        broke_and_starving = (
            not naval_threat_near
            and party.gold < 30
            and any(m.food == 0 for m in living)
            and all(m.hp * 10 >= m.max_hp * 3 for m in living)
        )
        if not needs_heal(party) or broke_and_starving:
            candidate_prey: list[tuple[str, int, int]] = []
            for c in getattr(screen, "creatures", []):
                tname = str(c.get("tile_name") or c.get("tile") or "").lower()
                if tname in ("whirlpool", "pirate", "serpent", "squid"):
                    continue
                cx, cy = c.get("x"), c.get("y")
                if cx is None or cy is None:
                    continue
                dx = min((cx - px) % gmap.width, (px - cx) % gmap.width)
                dy = min((cy - py) % gmap.height, (py - cy) % gmap.height)
                if dx + dy <= 12:
                    candidate_prey.append((tname, cx, cy))
            # Economy critic (inert by default): prefer prey that actually
            # pays gold at the party's power level.
            land_targets = self._economy.select_prey(
                party, state_machine.current_screen, candidate_prey
            )
            if land_targets is None:
                land_targets = {(x, y) for _t, x, y in candidate_prey}
            if land_targets:
                d = find_2d_step(gmap, (px, py), land_targets, party.transport, party=party, avoid_tiles=self._overworld_avoid)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        early_patrol = ((42, 18), (38, 17), (35, 17), (40, 22), (45, 22), (46, 20))
        patrol = early_patrol if (living and min(m.level for m in living) < 3) else _SOSARIA_PATROL
        for _ in range(len(patrol)):
            target = patrol[self._patrol_idx % len(patrol)]
            if (px, py) == target:
                self._patrol_idx += 1
                continue
            d = find_2d_step(gmap, (px, py), {target}, party.transport, party=party, avoid_tiles=self._overworld_avoid)
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

    @staticmethod
    def _pick_moongate_dest(gmap, src_idx: int, target_portal: tuple[int, int], party) -> int:
        """Pick the first-hop Felucca phase reachable from src_idx toward target_portal."""
        gates = getattr(gmap, "moongates", ())
        n = len(gates)
        if n == 0:
            return 0
        goal_gates = {
            i
            for i, gate in enumerate(gates)
            if find_2d_step(gmap, (gate.x, gate.y), {target_portal}, Transport.FOOT, party=party) is not None
        }
        q: deque[tuple[int, int | None]] = deque([(src_idx, None)])
        visited = {src_idx}
        while q:
            cur, first_hop = q.popleft()
            for k in range(3):
                nxt = (cur * 3 + k) % n
                hop = nxt if first_hop is None else first_hop
                if nxt in goal_gates:
                    return hop
                if nxt not in visited:
                    visited.add(nxt)
                    q.append((nxt, hop))
        return (src_idx * 3) % n

    def _step_ambrosia(
        self,
        state_machine: StateMachine,
        gmap,
        party,
        px: int,
        py: int,
        goal: Goal,
        living: list,
    ) -> int:
        """Navigate Ambrosia's land, locked doors, and inland bays for cards and exit."""
        from py_exodus.screens.overworld import can_move_to

        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        living_idx = next((i + 1 for i, m in enumerate(party.members) if not m.is_dead()), 1)

        def _is_walkable_land(x: int, y: int) -> bool:
            if can_move_to(gmap, x, y, Transport.FOOT, party=party):
                return True
            if has_key:
                t = gmap.get_tile(x, y)
                return t is not None and str(getattr(t, "name", "")).lower() == "locked_door"
            return False

        def _flood(start: tuple[int, int], pred) -> set[tuple[int, int]]:
            q = deque([start])
            vis = {start}
            while q:
                cx, cy = q.popleft()
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    nx, ny = (cx + dx) % gmap.width, (cy + dy) % gmap.height
                    if (nx, ny) not in vis and pred(nx, ny):
                        vis.add((nx, ny))
                        q.append((nx, ny))
            return vis

        if goal == Goal.AMBROSIA_CARDS_SHRINES:
            uncollected = [
                (tx, ty, card_idx)
                for tx, ty, card_idx in _AMBROSIA_CARD_SITES
                if not any(m.cards[card_idx] > 0 for m in living)
            ]
            if any((px, py) == (tx, ty) for tx, ty, _ in uncollected):
                self._queue_text(str(living_idx), enter=False)
                return self._emit_key(state_machine, pygame.K_s)

            shrine_target: tuple[int, int, int] | None = None
            if not uncollected:
                primary_shrines: list[tuple[int, int, str, str, tuple[Profession, ...]]] = [
                    (55, 27, "wisdom", "max_wis", (Profession.CLERIC, Profession.DRUID)),
                    (6, 6, "intelligence", "max_int", (Profession.WIZARD, Profession.ALCHEMIST, Profession.ILLUSIONIST)),
                    (4, 36, "strength", "max_str", (Profession.FIGHTER, Profession.PALADIN, Profession.RANGER, Profession.BARBARIAN)),
                    (45, 52, "dexterity", "max_dex", (Profession.THIEF, Profession.LARK)),
                ]
                for sx, sy, stat_attr, cap_attr, profs in primary_shrines:
                    m_need = next(
                        (
                            i + 1
                            for i, m in enumerate(party.members)
                            if not m.is_dead()
                            and m.profession in profs
                            and getattr(m, stat_attr, 0) < getattr(m, cap_attr, 99)
                        ),
                        None,
                    )
                    if m_need is not None:
                        shrine_target = (sx, sy, m_need)
                        break
                if shrine_target is None:
                    for sx, sy, stat_attr, cap_attr, _ in primary_shrines:
                        m_need = next(
                            (
                                i + 1
                                for i, m in enumerate(party.members)
                                if member_needs_shrine_stat(m, stat_attr, cap_attr)
                            ),
                            None,
                        )
                        if m_need is not None:
                            shrine_target = (sx, sy, m_need)
                            break

            if shrine_target is not None:
                sx, sy, m_need = shrine_target
                if (px, py) == (sx, sy):
                    if party.members[m_need - 1].gold < 100 and party.gold >= 100:
                        self._join_gold_member_idx = m_need
                        return self._emit_key(state_machine, pygame.K_j)
                    return self._emit_key(state_machine, pygame.K_e)
                amb_targets = [(sx, sy, -1)]
            else:
                amb_targets = uncollected

            if party.transport == Transport.FOOT and amb_targets:
                foot_reachable = {
                    (tx, ty)
                    for tx, ty, _ in amb_targets
                    if find_2d_step(
                        gmap, (px, py), {(tx, ty)}, Transport.FOOT, party=party, allow_locked_doors=has_key
                    ) is not None
                }
                if foot_reachable:
                    return self._move_toward(state_machine, gmap, party, (px, py), foot_reachable)

            tx, ty, _ = amb_targets[0]
            target_island = _flood((tx, ty), _is_walkable_land)
            target_water = {
                ((ix + dx) % gmap.width, (iy + dy) % gmap.height)
                for ix, iy in target_island
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                if str(getattr(gmap.get_tile((ix + dx) % gmap.width, (iy + dy) % gmap.height), "name", "")).lower() == "water"
            }
        else:
            target_island = {(32, 58)}
            target_water = {
                ((32 + dx) % gmap.width, (58 + dy) % gmap.height)
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
            }

        if party.transport == Transport.SHIP:
            if goal in (
                Goal.EXIT_AMBROSIA,
                Goal.BUY_FOOD,
                Goal.BUY_KEYS,
                Goal.RESURRECT_DEAD,
                Goal.CURE_POISON,
            ):
                for d, (dx, dy) in (
                    (Direction.NORTH, (0, -1)),
                    (Direction.SOUTH, (0, 1)),
                    (Direction.WEST, (-1, 0)),
                    (Direction.EAST, (1, 0)),
                ):
                    if ((px + dx) % gmap.width, (py + dy) % gmap.height) == (32, 58):
                        wind = getattr(party, "wind_direction", None)
                        if wind is None or wind == d.reverse():
                            return self._emit_key(state_machine, pygame.K_SPACE)
                        return self._emit_key(state_machine, _DIR_TO_KEY[d])
            else:
                if any(
                    ((px + dx) % gmap.width, (py + dy) % gmap.height) in target_island
                    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                ):
                    return self._emit_key(state_machine, pygame.K_x)
            if target_water and find_2d_step(
                gmap,
                (px, py),
                target_water,
                Transport.SHIP,
                party=party,
                ignore_wind=True,
            ) is not None:
                return self._move_toward(state_machine, gmap, party, (px, py), target_water)
            mainland = _flood((32, 54), _is_walkable_land)
            if any(
                ((px + dx) % gmap.width, (py + dy) % gmap.height) in mainland
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
            ):
                return self._emit_key(state_machine, pygame.K_x)
            mainland_water = {
                ((mx + dx) % gmap.width, (my + dy) % gmap.height)
                for mx, my in mainland
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                if str(getattr(gmap.get_tile((mx + dx) % gmap.width, (my + dy) % gmap.height), "name", "")).lower() == "water"
            }
            if mainland_water and find_2d_step(
                gmap,
                (px, py),
                mainland_water,
                Transport.SHIP,
                party=party,
                ignore_wind=True,
            ) is not None:
                return self._move_toward(state_machine, gmap, party, (px, py), mainland_water)
            any_shore_water = self._safe_shore_water(
                gmap, party, state_machine.current_screen, self._get_any_shore_water(gmap, party)
            )
            if (px, py) in any_shore_water:
                return self._emit_key(state_machine, pygame.K_x)
            if any_shore_water and find_2d_step(
                gmap,
                (px, py),
                any_shore_water,
                Transport.SHIP,
                party=party,
                ignore_wind=True,
            ) is not None:
                return self._move_toward(state_machine, gmap, party, (px, py), any_shore_water)
            return self._emit_key(state_machine, pygame.K_x)

        water_comp: set[tuple[int, int]] = set()
        for w in target_water:
            if w not in water_comp:
                water_comp |= _flood(
                    w,
                    lambda x, y: str(getattr(gmap.get_tile(x, y), "name", "")).lower() in ("water", "whirlpool"),
                )

        frigates = {
            (obj.get("x"), obj.get("y"))
            for obj in getattr(party, "dynamic_objects", ())
            if str(obj.get("tile", "")).lower() == "frigate"
        }
        if (px, py) in frigates and (px, py) in water_comp:
            return self._emit_key(state_machine, pygame.K_b)
        usable_frigates = {
            pos
            for pos in frigates
            if pos in water_comp
            and find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party, allow_locked_doors=has_key) is not None
        }
        if usable_frigates:
            return self._move_toward(state_machine, gmap, party, (px, py), usable_frigates)
        reachable_land = _flood((px, py), _is_walkable_land)
        shore_tiles = {
            ((wx + dx) % gmap.width, (wy + dy) % gmap.height)
            for wx, wy in water_comp
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
            if ((wx + dx) % gmap.width, (wy + dy) % gmap.height) in reachable_land
        }
        if shore_tiles:
            pirates_in_bay = [
                (c["x"], c["y"])
                for c in getattr(state_machine.current_screen, "creatures", ())
                if str(c.get("tile_name") or c.get("tile") or "").lower() == "pirate"
                and (c.get("x"), c.get("y")) in water_comp
            ]
            if pirates_in_bay:
                best_shore = min(
                    shore_tiles,
                    key=lambda st: min(abs(st[0] - px_) + abs(st[1] - py_) for px_, py_ in pirates_in_bay),
                )
                if (px, py) == best_shore:
                    return self._emit_key(state_machine, pygame.K_SPACE)
                return self._move_toward(state_machine, gmap, party, (px, py), {best_shore})
            vantage_tiles = sorted(
                {
                    ((wx + dx) % gmap.width, (wy + dy) % gmap.height)
                    for wx, wy in water_comp
                    for dx in (-10, 10)
                    for dy in (-10, 10)
                    if ((wx + dx) % gmap.width, (wy + dy) % gmap.height) in reachable_land
                }
            )
            if vantage_tiles:
                target = vantage_tiles[self._patrol_idx % len(vantage_tiles)]
                if (px, py) == target or self._patrol_idx == 0:
                    self._patrol_idx = (self._patrol_idx + 1) % len(vantage_tiles)
                    target = vantage_tiles[self._patrol_idx]
                return self._move_toward(state_machine, gmap, party, (px, py), {target})
            if (px, py) in shore_tiles:
                return self._emit_key(state_machine, pygame.K_SPACE)
            return self._move_toward(state_machine, gmap, party, (px, py), shore_tiles)
        if (px, py) in frigates:
            return self._emit_key(state_machine, pygame.K_b)
        any_frigates = {
            pos
            for pos in frigates
            if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party, allow_locked_doors=has_key) is not None
        }
        if any_frigates:
            return self._move_toward(state_machine, gmap, party, (px, py), any_frigates)
        return self._emit_key(state_machine, pygame.K_SPACE)

    def _enter_portal_or_wait_dawn(
        self,
        state_machine: StateMachine,
        screen,
        gmap,
        party,
        px: int,
        py: int,
        target_portal: tuple[int, int],
    ) -> int:
        if (px, py) == target_portal:
            if target_portal == (37, 53) and not (
                getattr(screen, "trammel_phase", 0) == 0
                and getattr(screen, "felucca_phase", 0) == 0
            ):
                return self._emit_key(state_machine, pygame.K_SPACE)
            return self._emit_key(state_machine, pygame.K_e)
        if (
            self._screen_map_id(screen, party) == 0
            and party.transport == Transport.FOOT
            and find_2d_step(gmap, (px, py), {target_portal}, Transport.FOOT, party=party) is None
        ):
            frigates = self._boardable_frigates(party, screen=screen)
            if (px, py) in frigates:
                return self._emit_key(state_machine, pygame.K_b)
            reachable_frigates = {
                pos for pos in frigates
                if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
            }
            if reachable_frigates:
                return self._move_toward(state_machine, gmap, party, (px, py), reachable_frigates)
            for src_idx, gate in enumerate(getattr(gmap, "moongates", ())):
                if (
                    abs(px - gate.x) + abs(py - gate.y) <= 1
                    or find_2d_step(gmap, (px, py), {(gate.x, gate.y)}, Transport.FOOT, party=party) is not None
                ):
                    dest_idx = self._pick_moongate_dest(gmap, src_idx, target_portal, party)
                    return self._step_moongate(state_machine, screen, gmap, party, px, py, src_idx=src_idx, dest_idx=dest_idx)
            hull_val = getattr(screen, "ship_hull", getattr(party, "ship_hull", 50))
            if hull_val > 5:
                fallback_frigates = self._boardable_frigates(party, include_damaged=True, screen=screen)
                if (px, py) in fallback_frigates:
                    return self._emit_key(state_machine, pygame.K_b)
                reachable_fallback = {
                    pos for pos in fallback_frigates
                    if find_2d_step(gmap, (px, py), {pos}, Transport.FOOT, party=party) is not None
                }
                if reachable_fallback:
                    return self._move_toward(state_machine, gmap, party, (px, py), reachable_fallback)
            living = [m for m in party.members if not m.is_dead()]
            return self._hunt_starving_prey_or_patrol(state_machine, screen, gmap, party, px, py, living)
        if self._screen_map_id(screen, party) == 0 and party.transport == Transport.SHIP:
            has_fire = any(not m.is_dead() and m.marks[1] > 0 for m in party.members)
            has_force = any(not m.is_dead() and m.marks[2] > 0 for m in party.members)
            shore_cache = getattr(self, "_portal_shore_cache", None)
            if shore_cache is None:
                shore_cache = {}
                self._portal_shore_cache = shore_cache
            cache_key = (target_portal, has_fire, has_force)
            if cache_key not in shore_cache:
                from py_exodus.screens.overworld import can_move_to

                land = {target_portal}
                q = deque([target_portal])
                while q:
                    cx, cy = q.popleft()
                    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                        nx, ny = (cx + dx) % gmap.width, (cy + dy) % gmap.height
                        if (nx, ny) not in land and can_move_to(gmap, nx, ny, Transport.FOOT, party=party):
                            t = gmap.get_tile(nx, ny)
                            tname = str(getattr(t, "name", "")).lower() if t else ""
                            if tname in ("lava", "fire") and not has_fire:
                                continue
                            if tname in ("energy_field", "force_field") and not has_force:
                                continue
                            land.add((nx, ny))
                            q.append((nx, ny))
                shore_water = frozenset(
                    ((lx + dx) % gmap.width, (ly + dy) % gmap.height)
                    for lx, ly in land
                    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                    if str(getattr(gmap.get_tile((lx + dx) % gmap.width, (ly + dy) % gmap.height), "name", "")).lower() == "water"
                )
                shore_cache[cache_key] = shore_water
            shore_water = self._safe_shore_water(gmap, party, screen, shore_cache[cache_key])
            if (px, py) in shore_water:
                return self._emit_key(state_machine, pygame.K_x)
            if shore_water:
                return self._move_toward(state_machine, gmap, party, (px, py), shore_water)
        return self._move_toward(state_machine, gmap, party, (px, py), {target_portal})

    def _step_moongate(
        self,
        state_machine: StateMachine,
        screen,
        gmap,
        party,
        px: int,
        py: int,
        src_idx: int,
        dest_idx: int,
    ) -> int:
        """Walk to an adjoining tile of moongate[src_idx], pass turns until aligned, then step in."""
        gates = getattr(gmap, "moongates", ())
        if not (0 <= src_idx < len(gates)):
            return self._emit_key(state_machine, pygame.K_SPACE)
        gx, gy = gates[src_idx].x, gates[src_idx].y
        if abs(px - gx) + abs(py - gy) == 1:
            if getattr(screen, "trammel_phase", 0) == src_idx and getattr(screen, "felucca_phase", 0) == dest_idx:
                return self._move_toward(state_machine, gmap, party, (px, py), {(gx, gy)})
            return self._emit_key(state_machine, pygame.K_SPACE)
        adjacent = {
            ((gx + dx) % gmap.width, (gy + dy) % gmap.height)
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
        }
        return self._move_toward(state_machine, gmap, party, (px, py), adjacent)

    def _hazard_hazard_costs(self, state_machine: StateMachine, party):
        """Scaled hazard costs for the current position (None when inert)."""
        runtime = getattr(self, "_hazard", None)
        if runtime is None or not runtime.active:
            return None
        screen = state_machine.current_screen
        if screen is None or getattr(screen, "game_map", None) is None:
            return None
        try:
            return runtime.hazard_costs(party, screen)
        except Exception as exc:  # strategy layer must never break the run
            logger.warning("hazard critic error: %s", exc)
            return None

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
        hz_costs = self._hazard_hazard_costs(state_machine, party)
        hz_alpha = self._hazard.alpha if self._hazard.active else 0.0
        d, wind_cost = find_2d_step_and_cost(
            game_map,
            start=start,
            goals=goals,
            transport=party.transport,
            party=party,
            wind_direction=wind,
            avoid_tiles=avoid,
            allow_locked_doors=(has_key and party.transport == Transport.FOOT),
            hazard_costs=hz_costs,
            hazard_alpha=hz_alpha,
        )
        if (
            starving_buy_food
            and avoid
            and (d is None or (wind_cost is not None and wind_cost > _STARVING_AVOID_MAX_STEPS))
        ):
            avoid = None
            d, wind_cost = find_2d_step_and_cost(
                game_map,
                start=start,
                goals=goals,
                transport=party.transport,
                party=party,
                wind_direction=wind,
                avoid_tiles=None,
                allow_locked_doors=(has_key and party.transport == Transport.FOOT),
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
            d = find_2d_step(
                game_map,
                start=start,
                goals=goals,
                transport=party.transport,
                party=party,
                wind_direction=wind,
                allow_locked_doors=(has_key and party.transport == Transport.FOOT),
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
        """Return the pygame key pointing toward an NPC within 1-2 tiles of (px, py)."""
        npc_coords = {(npc.x, npc.y) for npc in getattr(game_map, "npcs", ())}
        for key, (dx, dy) in (
            (pygame.K_UP, (0, -1)),
            (pygame.K_DOWN, (0, 1)),
            (pygame.K_RIGHT, (1, 0)),
            (pygame.K_LEFT, (-1, 0)),
        ):
            for dist in (1, 2):
                if (px + dx * dist, py + dy * dist) in npc_coords:
                    return key
        return pygame.K_UP

    @staticmethod
    def _nearest_reachable_portal(
        game_map,
        px: int,
        py: int,
        transport: Transport,
        portals: list[tuple[int, int]],
        party=None,
    ) -> tuple[int, int]:
        def _dist(tx_ty: tuple[int, int]) -> int:
            tx, ty = tx_ty
            dx = min((tx - px) % game_map.width, (px - tx) % game_map.width)
            dy = min((ty - py) % game_map.height, (py - ty) % game_map.height)
            return dx + dy

        ordered = sorted(portals, key=_dist)
        if (px, py) in portals:
            return (px, py)
        best_portal = None
        best_cost = None
        for portal in ordered:
            _, cost = find_2d_step_and_cost(game_map, (px, py), {portal}, transport, party=party)
            if cost is not None and (best_cost is None or cost < best_cost):
                best_cost = cost
                best_portal = portal
        return best_portal if best_portal is not None else ordered[0]

    @classmethod
    def _nearest_shop_town_portal(
        cls, game_map, px: int, py: int, transport: Transport, party=None
    ) -> tuple[int, int]:
        portals = [(info[0], info[1]) for info in _SHOP_TOWNS.values()]
        return cls._nearest_reachable_portal(game_map, px, py, transport, portals, party=party)

    @staticmethod
    def _can_level_at_british(member) -> bool:
        """Return True iff ``member.meet_lord_british()`` would actually advance their level."""
        if member.is_dead() or member.level >= 25:
            return False
        eligible_level = member.exp // 100 + 1
        if not member.marks or member.marks[0] == 0:
            eligible_level = min(eligible_level, 5)
        return eligible_level > member.level

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
