"""Live input-driver AutoPlayController for Full Autoplay ("Watch Mode")."""
from __future__ import annotations

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
    1: (45, 18, (16, 19)),   # Castle British (20gp / 25 food)
    3: (46, 19, (48, 49)),   # Britain (25gp / 25 food)
    6: (7, 44, (26, 25)),    # Grey (30gp / 25 food)
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
        self._join_gold_member_idx: int = 1
        self._hand_from_idx: int = 1
        self._hand_to_idx: int = 2
        self._food_packs: int = 1
        self._talk_dir_key: int = pygame.K_UP
        self._mapped_dungeon_levels: set[tuple[int, int]] = set()

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
        dmap = getattr(screen, "dungeon_map", None) or getattr(screen, "dmap", None) or screen.state.dmap
        goal = evaluate_goal(party)

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
        map_id = getattr(gmap, "id", getattr(screen, "map_id", party.map_id))
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

        npc_tiles = {(npc.x, npc.y) for npc in getattr(gmap, "npcs", [])}

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

        gear_key = self._maybe_manage_gear(state_machine, party)
        if gear_key is not None:
            return gear_key

        if map_id in _SHOP_TOWNS and goal == Goal.OUTFIT_BRITAIN:
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

        if map_id in _FOOD_TOWNS and goal == Goal.BUY_FOOD:
            _, _, food_xy = _FOOD_TOWNS[map_id]
            living = [(i + 1, m) for i, m in enumerate(party.members) if not m.is_dead()]
            if living:
                total_gold = sum(m.gold for _, m in living)
                buyer_idx, buyer = max(living, key=lambda im: im[1].gold)
                if buyer.gold < total_gold and buyer.gold < 300:
                    self._join_gold_member_idx = buyer_idx
                    return self._emit_key(state_machine, pygame.K_j)
                if (px, py) == food_xy:
                    packs_needed = max(1, (800 - party.food + 24) // 25)
                    self._food_packs = max(1, min(20, packs_needed, buyer.gold // 30))
                    self._shop_member_idx = buyer_idx
                    self._talk_dir_key = self._direction_to_npc(gmap, px, py)
                    return self._emit_key(state_machine, pygame.K_t)
                d = find_2d_step(
                    gmap, (px, py), food_xy, Transport.FOOT, party=party,
                    avoid_tiles=npc_tiles, prefer_paths=True,
                )
                if d is not None:
                    return self._emit_key(state_machine, _DIR_TO_KEY[d])

        # Default in town: walk to exit border (south edge)
        exits = {(x, gmap.height - 1) for x in range(gmap.width)}
        if py == gmap.height - 1:
            return self._emit_key(state_machine, pygame.K_DOWN)
        d = find_2d_step(
            gmap, (px, py), exits, Transport.FOOT, party=party,
            avoid_tiles=npc_tiles, prefer_paths=True,
        )
        if d is not None:
            return self._emit_key(state_machine, _DIR_TO_KEY[d])
        return self._emit_key(state_machine, pygame.K_DOWN)

    def _step_overworld(self, state_machine: StateMachine, screen, party, px: int, py: int, goal: Goal) -> int | None:
        gmap = screen.game_map
        living = [m for m in party.members if not m.is_dead()]

        # Loot dropped chests on foot on Sosaria (prefer APPAR_UNEM, else G with member 1)
        if party.map_id == 0 and party.transport == Transport.FOOT:
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
            if chests and goal in (Goal.GRIND_AND_LEVEL, Goal.OUTFIT_BRITAIN):
                return self._move_toward(state_machine, gmap, party, (px, py), chests)

        gear_key = self._maybe_manage_gear(state_machine, party)
        if gear_key is not None:
            return gear_key

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

        if goal == Goal.BUY_FOOD:
            food_portals = [(info[0], info[1]) for info in _FOOD_TOWNS.values()]
            target_portal = self._nearest_reachable_portal(
                gmap, px, py, party.transport, food_portals, party=party
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

        # GRIND_AND_LEVEL
        if any(self._can_level_at_british(m) for m in living):
            if (px, py) == (45, 18):
                return self._emit_key(state_machine, pygame.K_e)
            return self._move_toward(state_machine, gmap, party, (px, py), {(45, 18)})

        # Actively chase nearby reachable land creatures on Sosaria
        land_targets: set[tuple[int, int]] = set()
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
                land_targets.add((cx, cy))
        if land_targets:
            d = find_2d_step(gmap, (px, py), land_targets, party.transport, party=party)
            if d is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[d])

        for _ in range(len(_SOSARIA_PATROL)):
            target = _SOSARIA_PATROL[self._patrol_idx % len(_SOSARIA_PATROL)]
            if (px, py) == target:
                self._patrol_idx += 1
                continue
            d = find_2d_step(gmap, (px, py), {target}, party.transport, party=party)
            if d is not None:
                return self._emit_key(state_machine, _DIR_TO_KEY[d])
            self._patrol_idx += 1
        return self._emit_key(state_machine, pygame.K_SPACE)

    def _maybe_manage_gear(self, state_machine: StateMachine, party) -> int | None:
        """Equip best owned weapon/armor or hand off chest loot to a better-fit member."""
        for i, m in enumerate(party.members):
            if m.is_dead():
                continue
            better_w = best_owned_weapon(m)
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
        if "talk" in prompt or "which" in prompt or "who" in prompt:
            return self._emit_key(state_machine, pygame.K_0 + self._shop_member_idx)
        if "direction" in prompt:
            return self._emit_key(state_machine, self._talk_dir_key)
        if "buy" in prompt and "sell" in prompt:
            return self._emit_key(state_machine, pygame.K_b)
        if "anything else" in prompt:
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

    def _move_toward(
        self,
        state_machine: StateMachine,
        game_map,
        party,
        start: tuple[int, int],
        goals: set[tuple[int, int]],
    ) -> int:
        has_key = any(not m.is_dead() and m.keys > 0 for m in party.members)
        d = find_2d_step(
            game_map,
            start=start,
            goals=goals,
            transport=party.transport,
            party=party,
            wind_direction=getattr(party, "wind_direction", None),
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
        for portal in ordered:
            if (px, py) == portal or find_2d_step(game_map, (px, py), {portal}, transport, party=party) is not None:
                return portal
        return ordered[0]

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
        if eligible_level <= member.level:
            return False
        if member.exp // 100 >= 5 and (not member.marks or member.marks[0] == 0):
            return False
        return True

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
