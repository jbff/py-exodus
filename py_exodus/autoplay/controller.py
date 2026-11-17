"""Live input-driver AutoPlayController for Full Autoplay ("Watch Mode")."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from py_exodus.autoplay.nav import find_2d_step, find_dungeon_step
from py_exodus.autoplay.planner import Goal, evaluate_goal, needs_heal
from py_exodus.constants import ArmorType, Direction, Profession, Transport, WeaponType
from py_exodus.world.map import DungeonTile

if TYPE_CHECKING:
    from py_exodus.state_machine import StateMachine

_DIR_TO_KEY: dict[Direction, int] = {
    Direction.NORTH: pygame.K_UP,
    Direction.SOUTH: pygame.K_DOWN,
    Direction.WEST: pygame.K_LEFT,
    Direction.EAST: pygame.K_RIGHT,
}

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

    def __init__(self, enabled: bool = False, step_interval: float = 0.08) -> None:
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
        if not self.enabled:
            return False
        self._timer += dt
        stepped = False
        while self._timer >= self.step_interval:
            self._timer -= self.step_interval
            self.step(state_machine)
            stepped = True
        return stepped

    def _emit_key(self, state_machine: StateMachine, key: int) -> int:
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
        """Emit one logical input step for the active screen."""
        screen = state_machine.current_screen
        if screen is None:
            return None

        screen_name = type(screen).__name__
        if screen_name == "FinalScreen":
            self._key_queue.clear()
            return None

        if self._key_queue:
            return self._emit_key(state_machine, self._key_queue.popleft())

        if screen_name == "StartScreen":
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
        if screen.arena.is_finished:
            self._key_queue.clear()
            return self._emit_key(state_machine, pygame.K_RETURN)
        if not screen.auto_combat:
            return self._emit_key(state_machine, pygame.K_TAB)
        return None

    def _step_shrine(self, state_machine: StateMachine, screen) -> int | None:
        if screen.state == screen.STATE_WHO:
            return self._emit_key(state_machine, pygame.K_1)
        if screen.state == screen.STATE_DONATE:
            member = screen.party.get_member(screen.selected_member_idx)
            gold = member.gold if member is not None else 0
            amt = min(9, gold // 100)
            if amt >= 1:
                return self._emit_key(state_machine, pygame.K_0 + amt)
            return self._emit_key(state_machine, pygame.K_0)
        return self._emit_key(state_machine, pygame.K_ESCAPE)

    def _step_dungeon(self, state_machine: StateMachine, screen) -> int | None:
        if screen.text_log.is_waiting_for_input:
            return self._emit_key(state_machine, pygame.K_ESCAPE)

        party = screen.party
        dmap = screen.dmap
        goal = evaluate_goal(party)

        # Light spell if dark
        if party.torch_duration <= 1:
            caster = self._find_caster(party, (Profession.WIZARD, Profession.CLERIC), min_mp=10)
            if caster is not None:
                c_idx, prof = caster
                spell_key = "c" if prof == Profession.WIZARD else "d"
                self._queue_text(f"{c_idx}{spell_key}", enter=False)
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
            if type(screen).__name__ == "TownScreen":
                return self._handle_town_prompt(state_machine, screen)
            return self._emit_key(state_machine, pygame.K_ESCAPE)

        party = screen.party
        goal = evaluate_goal(party)
        if goal == Goal.DONE:
            return None

        if hasattr(screen, "avatar_x"):
            px, py = screen.avatar_x, screen.avatar_y
        else:
            px, py = party.x, party.y

        # Heal detour if hurt
        if needs_heal(party):
            caster = self._find_caster(party, (Profession.CLERIC, Profession.PALADIN, Profession.DRUID), min_mp=10)
            if caster is not None:
                hurt_idx = next(
                    (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.hp < m.max_hp),
                    1,
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
        map_id = getattr(screen, "map_id", party.map_id)
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
                    return self._emit_key(state_machine, pygame.K_SPACE)

        if map_id == 1:  # Castle of Lord British
            living = [m for m in party.members if not m.is_dead()]
            can_level = any(m.exp >= m.level * 100 for m in living)
            if can_level:
                if (px, py) == (32, 15):
                    self._queue_text("1", enter=False)
                    self._queue_text("n", enter=False)
                    return self._emit_key(state_machine, pygame.K_t)
                d = find_2d_step(gmap, (px, py), (32, 15), Transport.FOOT, party=party)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        if map_id == 3 and goal == Goal.OUTFIT_BRITAIN:  # Britain
            # 1. Equip any owned unequipped weapons
            for i, m in enumerate(party.members):
                if m.is_dead() or m.weapon != WeaponType.NONE:
                    continue
                owned_w = next(
                    (
                        w
                        for w, cnt in m.weapons.items()
                        if w != WeaponType.NONE
                        and cnt > 0
                        and (m.profession != Profession.WIZARD or w in (WeaponType.DAGGER, WeaponType.EXOTIC))
                    ),
                    None,
                )
                if owned_w is not None:
                    self._ready_member_idx = i + 1
                    self._ready_item_letter = chr(ord("a") + list(WeaponType).index(owned_w))
                    return self._emit_key(state_machine, pygame.K_r)

            # 2. Equip any owned unequipped armor
            for i, m in enumerate(party.members):
                if m.is_dead() or m.armor != ArmorType.NONE:
                    continue
                owned_a = next(
                    (a for a, cnt in m.armors.items() if a != ArmorType.NONE and cnt > 0),
                    None,
                )
                if owned_a is not None:
                    self._wear_member_idx = i + 1
                    self._wear_item_letter = chr(ord("a") + list(ArmorType).index(owned_a))
                    return self._emit_key(state_machine, pygame.K_w)

            # 3. Buy starter weapon at Osbert's Weaponry (39, 19)
            for i, m in enumerate(party.members):
                if m.is_dead() or m.weapon != WeaponType.NONE or m.gold < 5:
                    continue
                if m.profession == Profession.THIEF and m.gold >= 60:
                    letter = "d"  # Sling
                elif m.profession != Profession.WIZARD and m.gold >= 30:
                    letter = "c"  # Mace
                else:
                    letter = "b"  # Dagger
                if (px, py) == (39, 19):
                    self._shop_member_idx = i + 1
                    self._shop_item_letter = letter
                    return self._emit_key(state_machine, pygame.K_t)
                d = find_2d_step(gmap, (px, py), (39, 19), Transport.FOOT, party=party)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

            # 4. Buy Cloth armor at British Armour (50, 20)
            for i, m in enumerate(party.members):
                if m.is_dead() or m.armor != ArmorType.NONE or m.gold < 75:
                    continue
                if (px, py) == (50, 20):
                    self._shop_member_idx = i + 1
                    self._shop_item_letter = "b"  # Cloth
                    return self._emit_key(state_machine, pygame.K_t)
                d = find_2d_step(gmap, (px, py), (50, 20), Transport.FOOT, party=party)
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        # Default in town: walk to exit border (south edge)
        exits = {(x, gmap.height - 1) for x in range(gmap.width)}
        if py == gmap.height - 1:
            return self._emit_key(state_machine, pygame.K_DOWN)
        d = find_2d_step(gmap, (px, py), exits, Transport.FOOT, party=party)
        if d is not None:
            return self._emit_key(state_machine, _DIR_TO_KEY[d])
        return self._emit_key(state_machine, pygame.K_DOWN)

    def _step_overworld(self, state_machine: StateMachine, screen, party, px: int, py: int, goal: Goal) -> int | None:
        gmap = screen.game_map
        living = [m for m in party.members if not m.is_dead()]

        if goal == Goal.DIG_EXOTICS:
            # Weapon site (33, 3)
            need_wpn_idx = next(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.weapons.get(WeaponType.EXOTIC, 0) == 0),
                None,
            )
            if need_wpn_idx is not None:
                if (px, py) == (33, 3):
                    self._queue_text("DIG", enter=True)
                    self._queue_text(str(need_wpn_idx), enter=False)
                    return self._emit_key(state_machine, pygame.K_o)
                return self._move_toward(state_machine, gmap, party, (px, py), {(33, 3)})

            # Armor site (19, 44)
            need_arm_idx = next(
                (i + 1 for i, m in enumerate(party.members) if not m.is_dead() and m.armors.get(ArmorType.EXOTIC, 0) == 0),
                None,
            )
            if need_arm_idx is not None:
                if (px, py) == (19, 44):
                    self._queue_text("DIG", enter=True)
                    self._queue_text(str(need_arm_idx), enter=False)
                    return self._emit_key(state_machine, pygame.K_o)
                return self._move_toward(state_machine, gmap, party, (px, py), {(19, 44)})

        if goal == Goal.CONQUER_EXODUS:
            if (px, py) == (10, 53):
                return self._emit_key(state_machine, pygame.K_e)
            return self._move_toward(state_machine, gmap, party, (px, py), {(10, 53)})

        if goal == Goal.AMBROSIA_CARDS_SHRINES:
            for tx, ty, card_idx in _AMBROSIA_CARD_SITES:
                if not any(m.cards[card_idx] > 0 for m in living):
                    if (px, py) == (tx, ty):
                        self._queue_text("SEARCH", enter=True)
                        self._queue_text("1", enter=False)
                        return self._emit_key(state_machine, pygame.K_o)
                    return self._move_toward(state_machine, gmap, party, (px, py), {(tx, ty)})

        if goal == Goal.EXIT_AMBROSIA:
            return self._move_toward(state_machine, gmap, party, (px, py), {(32, 58)})

        if goal == Goal.SAIL_WHIRLPOOL:
            return self._move_toward(state_machine, gmap, party, (px, py), {(50, 13), (17, 48)})

        if goal == Goal.CAPTURE_SHIP:
            frigates = {
                (obj.get("x"), obj.get("y"))
                for obj in getattr(party, "dynamic_objects", [])
                if str(obj.get("tile", "")).lower() == "frigate"
            }
            if (px, py) in frigates:
                return self._emit_key(state_machine, pygame.K_b)
            if frigates:
                return self._move_toward(state_machine, gmap, party, (px, py), frigates)
            coast = [(48, 12), (50, 14), (48, 16), (46, 14)]
            target = coast[self._patrol_idx % len(coast)]
            if (px, py) == target:
                self._patrol_idx += 1
                target = coast[self._patrol_idx % len(coast)]
            return self._move_toward(state_machine, gmap, party, (px, py), {target})

        if goal == Goal.GET_MARK_KINGS:
            if (px, py) == (46, 7):
                return self._emit_key(state_machine, pygame.K_e)
            return self._move_toward(state_machine, gmap, party, (px, py), {(46, 7)})

        if goal == Goal.GET_REMAINING_MARKS:
            if not all(m.marks[1] > 0 and m.marks[3] > 0 for m in living):
                if (px, py) == (49, 34):
                    return self._emit_key(state_machine, pygame.K_e)
                return self._move_toward(state_machine, gmap, party, (px, py), {(49, 34)})
            if (px, py) == (58, 44):
                return self._emit_key(state_machine, pygame.K_e)
            return self._move_toward(state_machine, gmap, party, (px, py), {(58, 44)})

        if goal == Goal.OUTFIT_BRITAIN:
            if (px, py) == (46, 19):
                return self._emit_key(state_machine, pygame.K_e)
            return self._move_toward(state_machine, gmap, party, (px, py), {(46, 19)})

        # GRIND_AND_LEVEL
        if any(m.exp >= m.level * 100 and m.level < 5 for m in living):
            if (px, py) == (45, 18):
                return self._emit_key(state_machine, pygame.K_e)
            return self._move_toward(state_machine, gmap, party, (px, py), {(45, 18)})

        patrol = [(43, 21), (45, 21), (45, 23), (43, 23)]
        target = patrol[self._patrol_idx % len(patrol)]
        if (px, py) == target:
            self._patrol_idx += 1
            target = patrol[self._patrol_idx % len(patrol)]
        return self._move_toward(state_machine, gmap, party, (px, py), {target})

    def _handle_town_prompt(self, state_machine: StateMachine, screen) -> int | None:
        prompt = (getattr(screen.text_log, "current_prompt", "") or "").lower()
        if "ready" in prompt and "member" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._ready_member_idx)
        if "ready" in prompt or "weapon?" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._ready_item_letter) or pygame.K_b)
        if "wear" in prompt and "member" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._wear_member_idx)
        if "wear" in prompt or "armor?" in prompt:
            return self._emit_key(state_machine, _char_to_key(self._wear_item_letter) or pygame.K_b)
        if "talk" in prompt or "which" in prompt or "who" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._shop_member_idx)
        if "direction" in prompt:
            return self._emit_key(state_machine, pygame.K_UP)
        if "buy" in prompt and "sell" in prompt:
            return self._emit_key(state_machine, pygame.K_b)
        if "take it" in prompt or "deal" in prompt:
            return self._emit_key(state_machine, pygame.K_y)
        if "anything else" in prompt:
            return self._emit_key(state_machine, pygame.K_n)
        if "how many" in prompt:
            self._queue_text("1", enter=True)
            return self._emit_key(state_machine, self._key_queue.popleft())
        if "buy" in prompt or "what" in prompt or "choice" in prompt or "(a-" in prompt:
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
        d = find_2d_step(
            game_map,
            start=start,
            goals=goals,
            transport=party.transport,
            party=party,
            wind_direction=getattr(party, "wind_direction", None),
        )
        if d is not None:
            return self._emit_key(state_machine, _DIR_TO_KEY[d])
        return self._emit_key(state_machine, pygame.K_SPACE)

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
