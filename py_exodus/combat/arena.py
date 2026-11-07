"""11x11 Tactical Combat Arena, turn sequencing, monster AI, and victory/defeat management."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import random
from typing import TYPE_CHECKING, Any

from py_exodus.constants import (
    ArmorType,
    Direction,
    Status,
    TileAttrib,
    Transport,
    WeaponType,
)
from py_exodus.combat.resolver import (
    AttackResolution,
    AttackResult,
    calculate_monster_damage,
    calculate_player_damage,
    resolve_monster_attack,
    resolve_player_attack,
    trace_projectile_path,
)
from py_exodus.entities.defs import CreatureDef

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.constants import Spell
    from py_exodus.entities.character import Character
    from py_exodus.entities.party import Party, PartyMember
    from py_exodus.world.map import ConflictMap


class ActionType(str, Enum):
    """Actions available to players during tactical combat turns."""

    MOVE = "move"
    ATTACK = "attack"
    PASS = "pass"
    CAST = "cast"
    READY = "ready"
    WEAR = "wear"
    USE = "use"
    FLEE = "flee"


@dataclass
class Action:
    """Player tactical combat action definition."""

    type: ActionType
    direction: Direction | None = None
    target_x: int | None = None
    target_y: int | None = None
    spell: Any | None = None
    weapon: WeaponType | None = None
    armor: ArmorType | None = None
    item: str | None = None

    @classmethod
    def move(cls, direction: Direction | str) -> Action:
        d = direction if isinstance(direction, Direction) else Direction.from_name_or_key(direction)
        return cls(ActionType.MOVE, direction=d)

    @classmethod
    def attack(cls, direction: Direction | str) -> Action:
        d = direction if isinstance(direction, Direction) else Direction.from_name_or_key(direction)
        return cls(ActionType.ATTACK, direction=d)

    @classmethod
    def pass_turn(cls) -> Action:
        return cls(ActionType.PASS)

    @classmethod
    def flee(cls, direction: Direction | str) -> Action:
        d = direction if isinstance(direction, Direction) else Direction.from_name_or_key(direction)
        return cls(ActionType.FLEE, direction=d)

    @classmethod
    def cast(cls, spell: Any, direction: Direction | str | None = None) -> Action:
        d = (
            (direction if isinstance(direction, Direction) else Direction.from_name_or_key(direction))
            if direction is not None
            else None
        )
        return cls(ActionType.CAST, spell=spell, direction=d)


@dataclass
class ActionResult:
    """Outcome of a player's combat turn."""

    success: bool
    action: Action
    message: str = ""
    attack_res: AttackResolution | None = None
    fled: bool = False


@dataclass
class MonsterTurnResult:
    """Outcome of a single monster's combat turn."""

    monster_name: str
    action_type: str
    from_pos: tuple[int, int]
    to_pos: tuple[int, int]
    attack_res: AttackResolution | None = None
    message: str = ""


class CombatMonster:
    """Active monster instance placed within the tactical combat arena."""

    def __init__(self, definition: CreatureDef, x: int, y: int) -> None:
        self.definition = definition
        self.name = definition.name or definition.tile.capitalize()
        self.tile = definition.tile
        self.basehp = definition.basehp if definition.basehp > 0 else 48
        self.hp = definition.hp if definition.hp > 0 else self.basehp
        self.max_hp = self.hp
        self.exp = definition.exp
        self.x = x
        self.y = y
        self.visible = True
        self.ranged = definition.ranged
        self.ranged_hit_tile = definition.ranged_hit_tile
        self.poisons = definition.poisons
        self.teleports = definition.teleports
        self.steals = definition.steals
        self.no_chest = definition.no_chest
        self.fled = False

    @property
    def is_dead(self) -> bool:
        return self.hp <= 0 or self.fled

    @property
    def nochest(self) -> bool:
        return self.no_chest

    def get_attack_bonus(self) -> int:
        return 0

    def get_defense(self) -> int:
        return 128

    def take_damage(self, amount: int) -> int:
        self.hp = max(0, self.hp - amount)
        return self.hp

    def __repr__(self) -> str:
        return f"CombatMonster({self.name}, hp={self.hp}/{self.max_hp}, pos=({self.x}, {self.y}))"


class CombatArena:
    """11x11 Tactical Combat Arena managing turns, pathfinding, and combat resolution."""

    def __init__(
        self,
        party: Party,
        combat_map: ConflictMap,
        creature_tile: str = "orc",
        asset_mgr: AssetManager | None = None,
        monster_count: int | None = None,
    ) -> None:
        self.party = party
        self.combat_map = combat_map
        self.creature_tile = creature_tile
        self.asset_mgr = asset_mgr

        # State tracking
        self.is_finished = False
        self.is_victory = False
        self.is_defeat = False
        self.is_fled = False
        self.chest_spawned = False
        self.round_count = 1
        self.is_party_round_done = False
        self.log_messages: list[str] = []
        self.last_monster_death_pos: tuple[int, int] | None = None

        # Resolve creature definition
        self.creature_def = self._resolve_creature_def(creature_tile)

        # Spawn monsters
        self.monsters: list[CombatMonster] = self._spawn_monsters(monster_count)

        # Place player characters
        self.player_positions: dict[int, tuple[int, int]] = {}
        self._place_players()

        # Set initial active party member index
        self.active_party_member_idx: int = self._find_first_eligible_member_idx()

        # Check immediate end conditions (e.g. empty party)
        if not self._get_living_party_members():
            self.is_finished = True
            self.is_defeat = True
        elif not self.monsters:
            self._handle_victory()

    @classmethod
    def start_encounter(
        cls,
        party: Party,
        combat_map: ConflictMap,
        creature_type: str,
        asset_mgr: AssetManager | None = None,
        monster_count: int | None = None,
    ) -> CombatArena:
        """Factory method to initialize and start a tactical combat encounter."""
        return cls(
            party=party,
            combat_map=combat_map,
            creature_tile=creature_type,
            asset_mgr=asset_mgr,
            monster_count=monster_count,
        )

    # --- Setup & Spawning ---

    def _resolve_creature_def(self, creature_tile: str) -> CreatureDef:
        base_tile = creature_tile.strip().lower()
        if base_tile == "pirate":
            base_tile = "thief"

        c_def = None
        if self.asset_mgr is not None:
            c_def = self.asset_mgr.get_creature(base_tile)

        if c_def is None:
            c_def = CreatureDef(
                id=1,
                name=creature_tile.capitalize(),
                tile=creature_tile,
                basehp=48,
                hp=48,
                exp=5,
            )
        return c_def

    def _spawn_monsters(self, explicit_count: int | None = None) -> list[CombatMonster]:
        starts = self.combat_map.monster_starts or [(5, 1), (4, 2), (6, 2), (3, 3), (7, 3), (2, 4), (8, 4), (5, 0)]
        max_slots = len(starts)

        if explicit_count is not None:
            count = max(1, min(max_slots, explicit_count))
        else:
            living_count = len(self._get_living_party_members())
            if living_count == 0:
                living_count = 1
            max_monsters = min(max_slots, living_count * 2)

            if self.creature_def.tile.lower() == "guard" or self.creature_tile.lower() == "guard":
                count = max_monsters
            else:
                count = random.randint(1, max_monsters)

        # Distribute monsters into crSlots
        slots: list[int] = list(range(max_slots))
        chosen_slots = sorted(random.sample(slots, count))

        monsters: list[CombatMonster] = []
        for slot_idx in chosen_slots:
            sx, sy = starts[slot_idx]
            monsters.append(CombatMonster(self.creature_def, sx, sy))

        return monsters

    def _place_players(self) -> None:
        starts = self.combat_map.player_starts or [(5, 9), (4, 8), (6, 8), (5, 10)]
        for i, member in enumerate(self.party.members):
            member.fled = False
            member.combat_map_exit_direction = None
            if not member.is_dead() and member.hp > 0:
                sx, sy = starts[i % len(starts)]
                self.player_positions[i] = (sx, sy)
                member.combat_x = sx
                member.combat_y = sy
                member.x = sx
                member.y = sy

    def _get_living_party_members(self) -> list[PartyMember]:
        if hasattr(self.party, "living_members"):
            return self.party.living_members
        return [m for m in self.party.members if not m.is_dead()]

    def _find_first_eligible_member_idx(self) -> int:
        for i, member in enumerate(self.party.members):
            if self._is_member_eligible_for_turn(i):
                return i
        return 0

    def _is_member_eligible_for_turn(self, member_idx: int) -> bool:
        if member_idx not in self.player_positions:
            return False
        if member_idx >= len(self.party.members):
            return False
        member = self.party.members[member_idx]
        if member.fled or member.is_disabled() or member.is_dead() or member.hp <= 0:
            return False
        return True

    # --- Player Turn Execution ---

    def execute_player_action(
        self, member_idx: int, action: Action | ActionType | Direction | str
    ) -> ActionResult:
        """Execute action for specified party member, update arena state, and advance turn."""
        if self.is_finished:
            return ActionResult(success=False, action=Action.pass_turn(), message="Combat is already finished.")

        # Normalize action input
        act = self._normalize_action(action)

        if not self._is_member_eligible_for_turn(member_idx):
            # Member cannot act - advance and return
            self._advance_player_turn(member_idx)
            return ActionResult(success=False, action=act, message="Character is unable to act.")

        member = self.party.members[member_idx]
        cur_pos = self.player_positions[member_idx]

        res: ActionResult
        if act.type == ActionType.MOVE:
            res = self._handle_player_move(member_idx, member, cur_pos, act)
        elif act.type == ActionType.ATTACK:
            res = self._handle_player_attack(member_idx, member, cur_pos, act)
        elif act.type == ActionType.FLEE:
            res = self._handle_player_flee(member_idx, member, act.direction or Direction.SOUTH)
        elif act.type == ActionType.PASS:
            res = ActionResult(success=True, action=act, message=f"{member.name} passes.")
        else:
            # Other actions (READY, WEAR, CAST, USE)
            res = ActionResult(success=True, action=act, message=f"{member.name} acts.")

        self.log_messages.append(res.message)

        # Remove dead monsters
        self._cleanup_dead_monsters()

        # Check combat victory
        if len(self.monsters) == 0:
            self._handle_victory()
            return res

        # Check if combat finished because all players fled or died
        if not self.player_positions:
            self._evaluate_party_status()
            return res

        # Advance to next eligible member
        self._advance_player_turn(member_idx)

        return res

    def _normalize_action(self, action: Action | ActionType | Direction | str) -> Action:
        if isinstance(action, Action):
            return action
        if isinstance(action, ActionType):
            return Action(action)
        if isinstance(action, Direction):
            return Action.move(action)
        if isinstance(action, str):
            s = action.strip().lower()
            if s in ("pass", "wait", "space"):
                return Action.pass_turn()
            for d in Direction:
                if s == d.name.lower():
                    return Action.move(d)
            parsed_d = Direction.from_name_or_key(s)
            if parsed_d:
                return Action.move(parsed_d)
            if s.startswith("attack"):
                parts = s.split()
                if len(parts) > 1:
                    ad = Direction.from_name_or_key(parts[1])
                    if ad:
                        return Action.attack(ad)
                return Action.attack(Direction.NORTH)
        return Action.pass_turn()

    def _handle_player_move(
        self, member_idx: int, member: PartyMember, cur_pos: tuple[int, int], action: Action
    ) -> ActionResult:
        dir_val = action.direction or Direction.NORTH
        nx = cur_pos[0] + dir_val.dx
        ny = cur_pos[1] + dir_val.dy

        # Boundary check: stepping off boundary = retreat/flee
        if not (0 <= nx < self.combat_map.width and 0 <= ny < self.combat_map.height):
            return self._handle_player_flee(member_idx, member, dir_val)

        # Check if tile unwalkable
        tile = self.combat_map.get_tile(nx, ny)
        if tile is not None:
            attribs = getattr(tile, "attribs", TileAttrib.NONE)
            if bool(attribs & TileAttrib.UNWALKABLE):
                return ActionResult(
                    success=False, action=action, message=f"{member.name} is blocked by terrain."
                )

        # Check if occupied by another player
        for p_idx, pos in self.player_positions.items():
            if p_idx != member_idx and pos == (nx, ny):
                return ActionResult(
                    success=False, action=action, message=f"{member.name} is blocked by an ally."
                )

        # Check if occupied by a monster
        for m in self.monsters:
            if not m.is_dead and (m.x, m.y) == (nx, ny):
                return ActionResult(
                    success=False, action=action, message=f"{member.name} is blocked by {m.name}."
                )

        # Move succeeds
        self.player_positions[member_idx] = (nx, ny)
        member.combat_x = nx
        member.combat_y = ny
        member.x = nx
        member.y = ny

        return ActionResult(
            success=True,
            action=action,
            message=f"{member.name} moves {dir_val.name.lower()}.",
        )

    def _handle_player_flee(
        self, member_idx: int, member: PartyMember, direction: Direction
    ) -> ActionResult:
        member.fled = True
        member.combat_map_exit_direction = direction
        self.player_positions.pop(member_idx, None)

        msg = f"{member.name} retreats from combat!"
        return ActionResult(
            success=True, action=Action.flee(direction), message=msg, fled=True
        )

    def _handle_player_attack(
        self, member_idx: int, member: PartyMember, cur_pos: tuple[int, int], action: Action
    ) -> ActionResult:
        direction = action.direction or Direction.NORTH
        weapon_def = None
        if self.asset_mgr is not None and hasattr(member, "weapon"):
            w_name = member.weapon.value if isinstance(member.weapon, WeaponType) else str(member.weapon)
            weapon_def = self.asset_mgr.get_weapon(w_name)

        is_ranged = weapon_def is not None and weapon_def.range > 1

        if is_ranged:
            # Trace projectile path
            max_range = weapon_def.range
            attack_through = weapon_def.attack_through_objects
            path = trace_projectile_path(
                combat_map=self.combat_map,
                start_x=cur_pos[0],
                start_y=cur_pos[1],
                direction=direction,
                max_range=max_range,
                attack_through_objects=attack_through,
                monsters=self.monsters,
                players=self.player_positions,
            )

            # Check if projectile reached a monster
            target_monster = None
            dist = 1
            for pt in path:
                for m in self.monsters:
                    if not m.is_dead and (m.x, m.y) == pt:
                        target_monster = m
                        break
                if target_monster is not None:
                    break
                dist += 1

            if target_monster is None:
                return ActionResult(
                    success=True,
                    action=action,
                    message=f"{member.name} fired {direction.name.lower()} - Missed!",
                    attack_res=AttackResolution(
                        hit=False, result=AttackResult.MISS, projectile_path=path
                    ),
                )

            attack_res = resolve_player_attack(
                character=member.player,
                weapon_def=weapon_def,
                target_monster=target_monster,
                distance=dist,
            )
            attack_res.projectile_path = path

            if attack_res.killed:
                self.last_monster_death_pos = (target_monster.x, target_monster.y)

            return ActionResult(
                success=True,
                action=action,
                message=attack_res.message,
                attack_res=attack_res,
            )
        else:
            # Melee attack at distance 1
            tx = cur_pos[0] + direction.dx
            ty = cur_pos[1] + direction.dy

            target_monster = None
            for m in self.monsters:
                if not m.is_dead and (m.x, m.y) == (tx, ty):
                    target_monster = m
                    break

            if target_monster is None:
                return ActionResult(
                    success=True,
                    action=action,
                    message=f"{member.name} swings {direction.name.lower()} into empty space.",
                    attack_res=AttackResolution(
                        hit=False, result=AttackResult.MISS, target_pos=(tx, ty)
                    ),
                )

            attack_res = resolve_player_attack(
                character=member.player,
                weapon_def=weapon_def,
                target_monster=target_monster,
                distance=1,
            )
            if attack_res.killed:
                self.last_monster_death_pos = (target_monster.x, target_monster.y)

            return ActionResult(
                success=True,
                action=action,
                message=attack_res.message,
                attack_res=attack_res,
            )

    def _advance_player_turn(self, current_member_idx: int) -> None:
        count = len(self.party.members)
        next_idx = None
        for i in range(current_member_idx + 1, count):
            if self._is_member_eligible_for_turn(i):
                next_idx = i
                break

        if next_idx is not None:
            self.active_party_member_idx = next_idx
        else:
            # Party round has concluded
            self.is_party_round_done = True

    def _cleanup_dead_monsters(self) -> None:
        self.monsters = [m for m in self.monsters if not m.is_dead]

    # --- Monster Turn Execution & AI ---

    def execute_monster_turns(self) -> list[MonsterTurnResult]:
        """Execute turn for each active monster, apply poison damage, and check win/loss."""
        if self.is_finished:
            return []

        results: list[MonsterTurnResult] = []

        # Each active monster takes an action
        for monster in list(self.monsters):
            if monster.is_dead or self.is_finished:
                continue

            res = self._execute_single_monster_ai(monster)
            if res is not None:
                results.append(res)
                self.log_messages.append(res.message)

            self._evaluate_party_status()
            if self.is_finished:
                break

        # Remove dead or fled monsters
        self._cleanup_dead_monsters()

        # Poison damage tick at round end
        self._apply_poison_tick()

        # Evaluate combat completion
        self._evaluate_party_status()
        if len(self.monsters) == 0 and not self.is_finished:
            self._handle_victory()

        # Reset turn order for next round
        self.round_count += 1
        self.is_party_round_done = False
        self.active_party_member_idx = self._find_first_eligible_member_idx()

        return results

    def _execute_single_monster_ai(self, monster: CombatMonster) -> MonsterTurnResult | None:
        target_idx, target_member, dist = self._find_nearest_player(monster.x, monster.y)
        if target_idx is None or target_member is None:
            return None

        target_pos = self.player_positions[target_idx]
        from_pos = (monster.x, monster.y)

        # 1. Teleport check (25% chance for teleporters)
        if monster.teleports and random.randint(0, 3) == 0:
            rx = random.randint(0, self.combat_map.width - 1)
            ry = random.randint(0, self.combat_map.height - 1)
            if self._is_tile_passable_for_creature(rx, ry):
                monster.x = rx
                monster.y = ry
                return MonsterTurnResult(
                    monster_name=monster.name,
                    action_type="teleport",
                    from_pos=from_pos,
                    to_pos=(rx, ry),
                    message=f"{monster.name} teleports to ({rx}, {ry})!",
                )

        # 2. Ranged attack check (if ranged, distance > 1)
        if monster.ranged and dist > 1 and dist <= 11:
            dir_to_player = self._direction_towards(monster.x, monster.y, target_pos[0], target_pos[1])
            if dir_to_player:
                path = trace_projectile_path(
                    combat_map=self.combat_map,
                    start_x=monster.x,
                    start_y=monster.y,
                    direction=dir_to_player,
                    max_range=11,
                    attack_through_objects=False,
                    monsters=self.monsters,
                    players=self.player_positions,
                )
                if path and path[-1] == target_pos:
                    # Clear line of sight - attack!
                    armor_def = self._get_player_armor(target_member)
                    attack_res = resolve_monster_attack(
                        monster=monster, target_player=target_member, armor_def=armor_def, is_ranged=True
                    )
                    attack_res.projectile_path = path
                    return MonsterTurnResult(
                        monster_name=monster.name,
                        action_type="ranged",
                        from_pos=from_pos,
                        to_pos=target_pos,
                        attack_res=attack_res,
                        message=attack_res.message,
                    )

        # 3. Melee attack if adjacent (distance == 1 in Manhattan distance)
        dx = abs(monster.x - target_pos[0])
        dy = abs(monster.y - target_pos[1])
        if (dx + dy) == 1:
            armor_def = self._get_player_armor(target_member)
            attack_res = resolve_monster_attack(
                monster=monster, target_player=target_member, armor_def=armor_def, is_ranged=False
            )
            return MonsterTurnResult(
                monster_name=monster.name,
                action_type="attack",
                from_pos=from_pos,
                to_pos=target_pos,
                attack_res=attack_res,
                message=attack_res.message,
            )

        # 4. Advance towards closest player
        step_dir = self._find_ai_path_step(monster.x, monster.y, target_pos[0], target_pos[1])
        if step_dir is not None:
            nx = monster.x + step_dir.dx
            ny = monster.y + step_dir.dy

            # Check if step leaves arena
            if not (0 <= nx < self.combat_map.width and 0 <= ny < self.combat_map.height):
                monster.fled = True
                return MonsterTurnResult(
                    monster_name=monster.name,
                    action_type="flee",
                    from_pos=from_pos,
                    to_pos=(nx, ny),
                    message=f"{monster.name} flees from battle!",
                )

            monster.x = nx
            monster.y = ny
            return MonsterTurnResult(
                monster_name=monster.name,
                action_type="advance",
                from_pos=from_pos,
                to_pos=(nx, ny),
                message=f"{monster.name} advances {step_dir.name.lower()}.",
            )

        return None

    def _find_nearest_player(
        self, from_x: int, from_y: int
    ) -> tuple[int | None, PartyMember | None, int]:
        best_idx: int | None = None
        best_member: PartyMember | None = None
        least_dist = 9999

        for p_idx, pos in self.player_positions.items():
            member = self.party.members[p_idx]
            if member.fled or member.is_dead() or member.hp <= 0:
                continue
            dist = abs(from_x - pos[0]) + abs(from_y - pos[1])
            if dist < least_dist:
                least_dist = dist
                best_idx = p_idx
                best_member = member

        return best_idx, best_member, least_dist

    def _direction_towards(self, fx: int, fy: int, tx: int, ty: int) -> Direction | None:
        dx = tx - fx
        dy = ty - fy
        if dx == 0 and dy < 0:
            return Direction.NORTH
        if dx == 0 and dy > 0:
            return Direction.SOUTH
        if dy == 0 and dx > 0:
            return Direction.EAST
        if dy == 0 and dx < 0:
            return Direction.WEST
        return None

    def _find_ai_path_step(self, fx: int, fy: int, tx: int, ty: int) -> Direction | None:
        dx = tx - fx
        dy = ty - fy

        # Prioritize axis with larger delta
        directions: list[Direction] = []
        if abs(dx) >= abs(dy):
            if dx > 0:
                directions.append(Direction.EAST)
            elif dx < 0:
                directions.append(Direction.WEST)
            if dy > 0:
                directions.append(Direction.SOUTH)
            elif dy < 0:
                directions.append(Direction.NORTH)
        else:
            if dy > 0:
                directions.append(Direction.SOUTH)
            elif dy < 0:
                directions.append(Direction.NORTH)
            if dx > 0:
                directions.append(Direction.EAST)
            elif dx < 0:
                directions.append(Direction.WEST)

        for d in directions:
            nx = fx + d.dx
            ny = fy + d.dy
            if self._is_tile_passable_for_creature(nx, ny):
                return d
        return None

    def _is_tile_passable_for_creature(self, x: int, y: int) -> bool:
        if not (0 <= x < self.combat_map.width and 0 <= y < self.combat_map.height):
            return False

        tile = self.combat_map.get_tile(x, y)
        if tile is not None:
            attribs = getattr(tile, "attribs", TileAttrib.NONE)
            if bool(attribs & TileAttrib.UNWALKABLE) or bool(attribs & TileAttrib.CREATUREUNWALKABLE):
                return False

        # Cannot step onto another living monster
        for m in self.monsters:
            if not m.is_dead and (m.x, m.y) == (x, y):
                return False

        # Cannot step onto a living player
        for pos in self.player_positions.values():
            if pos == (x, y):
                return False

        return True

    def _get_player_armor(self, member: PartyMember) -> Any:
        if self.asset_mgr is not None and hasattr(member, "armor"):
            a_name = member.armor.value if isinstance(member.armor, ArmorType) else str(member.armor)
            return self.asset_mgr.get_armor(a_name)
        return None

    # --- End of Round Checks & Completion ---

    def _apply_poison_tick(self) -> None:
        for member in self.party.members:
            if not member.is_dead() and member.hp > 0:
                if member.status in (Status.POISON, Status.POISONED):
                    member.hp = max(0, member.hp - 2)
                    self.log_messages.append(f"{member.name} takes 2 poison damage.")
                    if member.hp == 0:
                        member.status = Status.DEAD
                        self.log_messages.append(f"{member.name} succumbed to poison!")

    def _evaluate_party_status(self) -> None:
        living_on_board = [
            i for i, pos in self.player_positions.items()
            if not self.party.members[i].is_dead() and self.party.members[i].hp > 0
        ]
        any_survivor_fled = any(m.fled for m in self.party.members)
        any_alive = any(not m.is_dead() and m.hp > 0 for m in self.party.members)

        if not living_on_board:
            self.is_finished = True
            if not any_alive:
                self.is_defeat = True
                self.is_victory = False
            elif any_survivor_fled:
                self.is_fled = True
                self.is_defeat = False
                self.is_victory = False

    def _handle_victory(self) -> None:
        self.is_finished = True
        self.is_victory = True
        self.is_defeat = False

        # Chest spawning rule:
        # Spawn unless creature has nochest or combat is ship combat (transport is SHIP)
        is_ship_combat = self.party.transport == Transport.SHIP
        is_nochest = getattr(self.creature_def, "no_chest", False) or getattr(self.creature_def, "nochest", False)

        if not is_nochest and not is_ship_combat:
            self.chest_spawned = True
            # Spawn chest in party dynamic objects if present
            if hasattr(self.party, "dynamic_objects"):
                self.party.dynamic_objects.append({"tile": "chest", "x": self.party.x, "y": self.party.y})

            # Replace tile on combat map if chest tile definition exists
            if self.asset_mgr is not None and "chest" in self.asset_mgr.tile_defs_by_name:
                chest_tile = self.asset_mgr.tile_defs_by_name["chest"]
                cx, cy = self.last_monster_death_pos or (5, 5)
                self.combat_map.set_tile(cx, cy, chest_tile)
        else:
            self.chest_spawned = False
