"""11x11 Tactical Combat Arena, turn sequencing, monster AI, and victory/defeat management."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
from typing import TYPE_CHECKING, Any

from py_exodus.aura import AuraType
from py_exodus.assets import MAP_NAME_TO_ID
from py_exodus.constants import (
    ArmorType,
    Direction,
    TileAttrib,
    TileEffect,
    WeaponType,
)
from py_exodus.combat.resolver import (
    AttackResolution,
    AttackResult,
    get_relative_direction_mask,
    resolve_monster_attack,
    resolve_monster_ranged_attack,
    resolve_player_attack,
    trace_directional_path,
    trace_projectile_path,
)
from py_exodus.entities.defs import CreatureDef
from py_exodus.world.tile_effects import apply_effect_rolled, slowed_by_tile

if TYPE_CHECKING:
    from py_exodus.assets import AssetManager
    from py_exodus.entities.party import Party, PartyMember
    from py_exodus.world.map import ConflictMap


#: Java ``Maps.EXODUS``: the Castle of Death. Creature
#: attacks auto-hit non-EXOTIC defenders there and non-EXOTIC player attacks
#: are refused (CombatScreen.java:605, 723; SecondaryInputProcessor.java:345).
EXODUS_MAP_ID = MAP_NAME_TO_ID["EXODUS"]


class ActionType(str, Enum):
    """Actions available to players during tactical combat turns.

    Java CombatScreen.keyUp (CombatScreen.java:285-362): SPACE pass, arrow
    moves, A attack, C cast, N negate, R ready, W wear. FLEE is intentionally
    absent — Java commented the off-edge retreat out of ``preMove``; stepping
    off the arena is BLOCKED, not an escape.
    """

    MOVE = "move"
    ATTACK = "attack"
    PASS = "pass"
    CAST = "cast"
    READY = "ready"
    WEAR = "wear"
    USE = "use"


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
    target_member: Any | None = None

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
    def cast(
        cls,
        spell: Any,
        direction: Direction | str | None = None,
        target_member: Any | None = None,
    ) -> Action:
        d = (
            (direction if isinstance(direction, Direction) else Direction.from_name_or_key(direction))
            if direction is not None
            else None
        )
        return cls(ActionType.CAST, spell=spell, direction=d, target_member=target_member)


@dataclass
class ActionResult:
    """Outcome of a player's combat turn."""

    success: bool
    action: Action
    message: str = ""
    attack_res: AttackResolution | None = None
    fled: bool = False
    spell_res: Any | None = None
    # Java SpellUtil: LORUM, PABULUM, ALTAIR, DAG_ACRON and the dungeon spells
    # never call finishPlayerTurn — in combat the caster acts again. The turn
    # is consumed by every other successful combat spell (and by failures).
    consume_turn: bool = True


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
        context_map_id: int | None = None,
        encounter_x: int | None = None,
        encounter_y: int | None = None,
        encounter_tile_walkable: bool | None = None,
    ) -> None:
        self.party = party
        self.combat_map = combat_map
        self.creature_tile = creature_tile
        self.asset_mgr = asset_mgr
        # The map combat happens ON (Java CombatScreen.contextMap). Defaults to
        # the party's current map id; drives the Castle of Death (EXODUS) rules.
        self.context_map_id = (
            context_map_id if context_map_id is not None else getattr(party, "map_id", None)
        )
        # The encounter's overworld creature tile (Java GameScreen.endCombat's
        # currentEncounter.currentX/currentY): where the victory chest/frigate
        # lands (GameScreen.java:421-431).
        self.encounter_x = encounter_x
        self.encounter_y = encounter_y
        self.encounter_tile_walkable = encounter_tile_walkable

        # Reset free combat spell per encounter
        for m in self.party.members:
            m.used_free_spell_in_combat = False
            char = getattr(m, "character", m)
            if hasattr(char, "used_free_spell_in_combat"):
                char.used_free_spell_in_combat = False

        # State tracking
        self.is_finished = False
        self.is_victory = False
        self.is_defeat = False
        self.is_fled = False
        self.chest_spawned = False
        self.round_count = 1
        self.freeze_rounds = 0
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
        **kwargs: Any,
    ) -> CombatArena:
        """Factory method to initialize and start a tactical combat encounter."""
        return cls(
            party=party,
            combat_map=combat_map,
            creature_tile=creature_type,
            asset_mgr=asset_mgr,
            monster_count=monster_count,
            **kwargs,
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
            # Java CombatScreen.java:193-202 — maxCreatures counts EVERY party
            # member (dead included, Party.getMembers().size()). Guards always
            # take the full count; everyone else rolls
            # rand.nextInt(min(8, size * 2)) + 1.
            party_size = len(self.party.members)
            max_monsters = min(max_slots, party_size * 2)

            if self.creature_def.tile.lower() == "guard" or self.creature_tile.lower() == "guard":
                count = max_monsters
            elif max_monsters > 0:
                count = random.randint(1, min(8, max_monsters))
            else:
                count = 0

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
            member.used_free_spell_in_combat = False
            if hasattr(member, "character") and hasattr(member.character, "used_free_spell_in_combat"):
                member.character.used_free_spell_in_combat = False
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

    def execute_turn(self, action: Action | ActionType | Direction | str) -> ActionResult:
        """Execute turn for the current active party member, triggering monster AI if round ends."""
        idx = self.active_party_member_idx
        res = self.execute_player_action(idx, action)
        if self.is_party_round_done and not self.is_finished:
            self.execute_monster_turns()
        return res

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
        elif act.type == ActionType.CAST:
            res = self._handle_player_cast(member_idx, member, act)
        elif act.type == ActionType.PASS:
            res = ActionResult(success=True, action=act, message=f"{member.name} passes.")
        else:
            # Other actions (READY, WEAR, USE)
            res = ActionResult(success=True, action=act, message=f"{member.name} acts.")

        if res.message:
            # Java's log stays silent wherever it only plays a sound (e.g. the
            # refused EXODUS attack) — an empty result message writes nothing.
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

        # Java's finishPlayerTurn gate: LORUM/PABULUM/ALTAIR/DAG_ACRON and the
        # dungeon spells leave the caster active (SpellUtil.java:87-237).
        if res.consume_turn:
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

        # Java CombatScreen.preMove (CombatScreen.java:394-446): stepping off
        # the arena is BLOCKED (FLEE is commented out) and writes nothing.
        if not (0 <= nx < self.combat_map.width and 0 <= ny < self.combat_map.height):
            return ActionResult(success=False, action=action, message="")

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

        # Java CombatScreen.checkTileAffects (CombatScreen.java:364-379): the
        # moved-onto tile's rule effect rolls for the MOVER through
        # Party.applyEffect(PartyMember, effect) — the rolled single-member
        # overload (Party.java:285-306).
        if tile is not None:
            effect = getattr(tile, "effect", TileEffect.NONE)
            self._check_tile_affects(member, effect)

        return ActionResult(
            success=True,
            action=action,
            message=f"{member.name} moves {dir_val.name.lower()}.",
        )

    def _check_tile_affects(self, member: PartyMember, effect: TileEffect) -> None:
        """Java ``CombatScreen.checkTileAffects`` (CombatScreen.java:364-379).

        The die-rolled single-member overload — LAVA/FIRE/GREMLINS 1-in-2,
        POISON/POISONFIELD 1-in-5, ELECTRICITY unconditional — is
        ``Party.applyEffect(PartyMember, effect)`` (Party.java:285-306).
        ``tile_effects.apply_effect_rolled`` is the roll home; the mover-only
        roster view routes the roll to the one member that entered the tile.
        A wipe raises ``PartyDeathException`` (Java keyUp catches it and routes
        ``returnScreen.partyDeath()``); CombatScreen catches and converts it.
        """
        if effect == TileEffect.NONE:
            return

        class _MoverRoster:
            """View of just the mover, for the apply_effect_rolled roll."""

            def __init__(self, target: PartyMember) -> None:
                self.members = [target]

        apply_effect_rolled(_MoverRoster(member), effect)

    def _handle_player_attack(
        self, member_idx: int, member: PartyMember, cur_pos: tuple[int, int], action: Action
    ) -> ActionResult:
        direction = action.direction or Direction.NORTH

        # Java SecondaryInputProcessor.java:342-352: on Maps.EXODUS every
        # weapon other than EXOTIC is refused — a NEGATIVE_EFFECT cue, no
        # message, and the turn passes through finishPlayerTurn.
        if self._is_exodus_map():
            weapon_val = getattr(member, "weapon", WeaponType.NONE)
            weapon_val = weapon_val.value if isinstance(weapon_val, WeaponType) else str(weapon_val)
            if weapon_val != WeaponType.EXOTIC.value:
                return ActionResult(success=False, action=action, message="")

        weapon_def = None
        if self.asset_mgr is not None and hasattr(member, "weapon"):
            w_name = member.weapon.value if isinstance(member.weapon, WeaponType) else str(member.weapon)
            weapon_def = self.asset_mgr.get_weapon(w_name)

        is_ranged = weapon_def is not None and weapon_def.range > 1

        if is_ranged and weapon_def is not None:
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

            message = f"{member.name} fired {direction.name.lower()} - Missed!"
            attack_res = AttackResolution(
                hit=False, result=AttackResult.MISS, projectile_path=path
            )
            if target_monster is not None:
                attack_res = resolve_player_attack(
                    character=member.player,
                    weapon_def=weapon_def,
                    target_monster=target_monster,
                    distance=dist,
                )
                attack_res.projectile_path = path
                if attack_res.killed:
                    self.last_monster_death_pos = (target_monster.x, target_monster.y)
                message = attack_res.message
            else:
                attack_res.projectile_path = path

            message = self._apply_weapon_loss(
                member, weapon_def, found_target=target_monster is not None,
                distance=dist if target_monster is not None else 1,
                message=message,
            )

            return ActionResult(
                success=True,
                action=action,
                message=message,
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

            message = f"{member.name} swings {direction.name.lower()} into empty space."
            attack_res = AttackResolution(
                hit=False, result=AttackResult.MISS, target_pos=(tx, ty)
            )
            if target_monster is not None:
                attack_res = resolve_player_attack(
                    character=member.player,
                    weapon_def=weapon_def,
                    target_monster=target_monster,
                    distance=1,
                )
                if attack_res.killed:
                    self.last_monster_death_pos = (target_monster.x, target_monster.y)
                message = attack_res.message

            message = self._apply_weapon_loss(
                member, weapon_def, found_target=target_monster is not None,
                distance=1, message=message,
            )

            return ActionResult(
                success=True,
                action=action,
                message=message,
                attack_res=attack_res,
            )

    def _apply_weapon_loss(
        self,
        member: PartyMember,
        weapon_def: Any,
        found_target: bool,
        distance: int,
        message: str,
    ) -> str:
        """Java ``Utils.attack`` (Utils.java:732-736): after every weapon
        attack the equipped weapon is lost when ``lose`` is set, or when
        ``losewhenranged`` is set and the shot missed or was fired beyond
        distance 1. Losing the last item drops the wielder to ``NONE`` —
        ``PartyMember.loseWeapon`` returns ``NONE`` (Party.java:460-470) and
        Java logs "Last One!" (Utils.java:733-735).
        """
        if weapon_def is None:
            return message
        if not (weapon_def.lose or (weapon_def.lose_when_ranged and (not found_target or distance > 1))):
            return message

        wt = member.weapon
        if not isinstance(wt, WeaponType) or wt == WeaponType.NONE:
            return message
        weapons = getattr(member, "weapons", None)
        if not isinstance(weapons, dict):
            return message
        count = weapons.get(wt, 0)
        if count > 0:
            weapons[wt] = count - 1
            return message
        member.weapon = WeaponType.NONE
        return f"{message}\nLast One!" if message else "Last One!"

    def _is_exodus_map(self) -> bool:
        """True when the combat runs on the Castle of Death (Maps.EXODUS)."""
        return self.context_map_id == EXODUS_MAP_ID

    def _handle_player_cast(
        self, member_idx: int, member: PartyMember, action: Action
    ) -> ActionResult:
        from py_exodus.combat.magic import NO_TURN_SPELLS, cast_spell, resolve_spell

        resolved = resolve_spell(action.spell, caster=member)
        if resolved is None:
            resolved = action.spell
        spell_res = cast_spell(
            spell=resolved,
            caster=member,
            target_dir=action.direction,
            arena=self,
            target_member=action.target_member,
            party=self.party,
        )
        # Java: an effect that never calls finishPlayerTurn leaves the caster
        # active; failed casts fall back to consuming the turn attempt.
        consumes = not (spell_res.success and resolved in NO_TURN_SPELLS)
        return ActionResult(
            success=spell_res.success,
            action=action,
            message=spell_res.message,
            spell_res=spell_res,
            consume_turn=consumes,
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
        """Execute turn for each active monster and check win/loss.

        Java CombatScreen.finishTurn (CombatScreen.java:479-502): the aura
        passes a turn every round and a live QUICKNESS aura skips the
        creature-action sequence entirely (silent in Java). There is NO
        per-round poison tick in combat (party.endTurn runs the exploration
        tick at the round level; it is out of this arena's scope).
        """
        if self.is_finished:
            return []

        aura = getattr(self.party, "aura", None)
        if aura is not None:
            aura.pass_turn()
            if aura.get_type() == AuraType.QUICKNESS:
                # The monster phase is skipped outright — no movement, no attack.
                self._evaluate_party_status()
                if len(self.monsters) == 0 and not self.is_finished:
                    self._handle_victory()
                self.round_count += 1
                self.is_party_round_done = False
                self.active_party_member_idx = self._find_first_eligible_member_idx()
                return []

        results: list[MonsterTurnResult] = []

        # Each active monster takes an action
        for monster in list(self.monsters):
            if monster.is_dead or self.is_finished:
                continue

            res = self._execute_single_monster_ai(monster)
            if res is not None:
                results.append(res)
                if res.message:
                    self.log_messages.append(res.message)

            self._evaluate_party_status()
            if self.is_finished:
                break

        # Remove dead or fled monsters
        self._cleanup_dead_monsters()

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
        """Java ``CombatScreen.creatureAction`` (CombatScreen.java:688-805).

        Action selection (696-713): TELEPORT on rand.nextInt(100) <= 25 for
        teleporters, else RANGED on nextInt(100) <= 33 — regardless of
        distance — else ATTACK, which becomes ADVANCE when the (movement)
        distance exceeds 1.
        """
        # Java creatureAction:692-694 — JINX leaves no targetable member, so
        # the creature does nothing this round.
        aura = getattr(self.party, "aura", None)
        if aura is not None and aura.get_type() == AuraType.JINX:
            return None

        # 1. Teleport check (Java:697 — rand.nextInt(100) <= 25, i.e. 26/100).
        teleports = monster.teleports and random.randrange(100) <= 25

        # 2. Ranged check (Java:699 — nextInt(100) <= 33, i.e. 34/100, no
        # distance gate). The roll only happens for non-teleporters.
        ranged = (
            monster.ranged
            and not teleports
            and random.randrange(100) <= 33
        )

        target_idx, target_member, movement_dist = self._find_nearest_player(
            monster.x, monster.y, ranged=ranged
        )
        if target_idx is None or target_member is None:
            return None

        target_pos = self.player_positions[target_idx]
        from_pos = (monster.x, monster.y)

        if teleports:
            return self._monster_teleport(monster, from_pos)

        if ranged:
            return self._monster_ranged_attack(monster, target_idx, from_pos)

        # Java:711-713 — ATTACK with dist > 1 becomes ADVANCE.
        if movement_dist > 1:
            return self._monster_advance(monster, target_pos, from_pos)

        # Melee ATTACK against an adjacent target (Java:720-745).
        armor_def = self._get_player_armor(target_member)
        attack_res = resolve_monster_attack(
            monster=monster,
            target_player=target_member,
            armor_def=armor_def,
            is_ranged=False,
            context_map_id=self.context_map_id,
        )
        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="attack",
            from_pos=from_pos,
            to_pos=target_pos,
            attack_res=attack_res,
            message=attack_res.message,
        )

    def _monster_teleport(self, monster: CombatMonster, from_pos: tuple[int, int]) -> MonsterTurnResult:
        """Java ``CombatScreen.creatureAction`` case TELEPORT (748-768): five
        tries at a random tile (rejected when the rule blocks creatures), then
        moveCreature steps ONE tile toward it through the movement mask."""
        for _ in range(5):
            rx = random.randrange(self.combat_map.width)
            ry = random.randrange(self.combat_map.height)
            tile = self.combat_map.get_tile(rx, ry)
            if tile is None:
                continue
            attribs = getattr(tile, "attribs", TileAttrib.NONE)
            if bool(attribs & TileAttrib.CREATUREUNWALKABLE):
                continue
            step_dir = self._advance_direction(monster.x, monster.y, rx, ry)
            if step_dir is None:
                return MonsterTurnResult(
                    monster_name=monster.name,
                    action_type="teleport",
                    from_pos=from_pos,
                    to_pos=from_pos,
                    message="",
                )
            nx = monster.x + step_dir.dx
            ny = monster.y + step_dir.dy
            if self._move_is_too_slow(monster, nx, ny):
                return MonsterTurnResult(
                    monster_name=monster.name,
                    action_type="teleport",
                    from_pos=from_pos,
                    to_pos=from_pos,
                    message="",
                )
            monster.x = nx
            monster.y = ny
            return MonsterTurnResult(
                monster_name=monster.name,
                action_type="teleport",
                from_pos=from_pos,
                to_pos=(nx, ny),
                message="",
            )
        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="teleport",
            from_pos=from_pos,
            to_pos=from_pos,
            message="",
        )

    def _monster_ranged_attack(
        self, monster: CombatMonster, target_idx: int, from_pos: tuple[int, int]
    ) -> MonsterTurnResult:
        """Java ``CombatScreen.creatureAction`` case RANGED (770-785) plus
        ``rangedAttackAt`` (591-678): the relative-direction mask may hold two
        bits, so the bolt can step diagonally; every party member standing on
        a path tile takes the hit until one bolt HITS."""
        tx, ty = self.player_positions[target_idx]
        dirmask = get_relative_direction_mask(
            self.combat_map.width,
            self.combat_map.height,
            tx,
            ty,
            monster.x,
            monster.y,
        )
        path = trace_directional_path(
            self.combat_map,
            dirmask,
            monster.x,
            monster.y,
            min_distance=1,
            max_distance=11,
            attack_through_objects=False,
            check_for_creatures=False,
            monsters=[],  # Java passes checkForCreatures=false for creature bolts
        )

        attack_res: AttackResolution | None = None
        hit_pos = from_pos
        for pt in path:
            member = self._member_at(pt[0], pt[1])
            if member is None:
                continue
            armor_def = self._get_player_armor(member)
            attack_res = resolve_monster_ranged_attack(
                monster=monster,
                target_player=member,
                armor_def=armor_def,
                context_map_id=self.context_map_id,
            )
            hit_pos = (member.x, member.y)
            if attack_res.hit:
                break

        if attack_res is None:
            return MonsterTurnResult(
                monster_name=monster.name,
                action_type="ranged",
                from_pos=from_pos,
                to_pos=path[-1] if path else from_pos,
                message="",
            )

        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="ranged",
            from_pos=from_pos,
            to_pos=hit_pos,
            attack_res=attack_res,
            message=attack_res.message,
        )

    def _monster_advance(
        self,
        monster: CombatMonster,
        target_pos: tuple[int, int],
        from_pos: tuple[int, int],
    ) -> MonsterTurnResult:
        """Java ``CombatScreen.moveCreature`` (886-957) for the ADVANCE action:
        ``Utils.getPath`` intersects the toward-directions with the valid-move
        mask and ``Direction.getRandomValidDirection`` rolls among what is
        left; no direction survives → no move. The mask excludes null tiles,
        so a creature can never step off the map (the old "flees from battle!"
        escape is gone — Java's FLEE branch is dead code)."""
        step_dir = self._advance_direction(monster.x, monster.y, target_pos[0], target_pos[1])
        if step_dir is None:
            return None

        nx = monster.x + step_dir.dx
        ny = monster.y + step_dir.dy
        if self._move_is_too_slow(monster, nx, ny):
            return None

        monster.x = nx
        monster.y = ny
        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="advance",
            from_pos=from_pos,
            to_pos=(nx, ny),
            message="",
        )

    def _advance_direction(self, fx: int, fy: int, tx: int, ty: int) -> Direction | None:
        """``Utils.getPath`` + ``Direction.getRandomValidDirection``
        (Utils.java:299-312, Constants.java:319-333): the toward-directions
        filtered to passable tiles, randomized uniformly; none → None."""
        toward_mask = get_relative_direction_mask(
            self.combat_map.width, self.combat_map.height, tx, ty, fx, fy
        )
        if toward_mask == 0:
            return None
        candidates: list[Direction] = []
        # Java iterates Direction.values() (NORTH, SOUTH, EAST, WEST) order.
        for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
            if not (d.mask & toward_mask):
                continue
            if self._is_tile_passable_for_creature(fx + d.dx, fy + d.dy):
                candidates.append(d)
        if not candidates:
            return None
        return random.choice(candidates)

    def _move_is_too_slow(self, monster: CombatMonster, nx: int, ny: int) -> bool:
        """Java ``moveCreature`` slowed-type gate (CombatScreen.java:925-956).
        Swimmers/sailors are never slowed (wind handling is commented out),
        fliers never; walkers lose the move on the tile's Context.slowedByTile
        roll (Context.java:215-240)."""
        if getattr(monster.definition, "swims", False) or getattr(monster.definition, "sails", False):
            return False
        if getattr(monster.definition, "flies", False):
            return False
        tile = self.combat_map.get_tile(nx, ny)
        if tile is None:
            return False
        return slowed_by_tile(tile)

    def _member_at(self, x: int, y: int) -> PartyMember | None:
        """The party member occupying a tile (Java rangedAttackAt's defender
        scan, CombatScreen.java:593-599 — dead members still stand there)."""
        for p_idx, pos in self.player_positions.items():
            if pos == (x, y):
                return self.party.members[p_idx]
        return None

    def _find_nearest_player(
        self, from_x: int, from_y: int, ranged: bool = False
    ) -> tuple[int | None, PartyMember | None, int]:
        """Java ``CombatScreen.nearestPartyMember`` (807-840).

        Ranged attacks pick by the diagonal distance (Utils.distance),
        everything else by movement distance (Utils.movementDistance, the
        Manhattan walk). A JINX aura yields no target; ties give the further
        candidate a 1-in-2 chance (Java:828)."""
        best_idx: int | None = None
        best_member: PartyMember | None = None
        least_dist = 9999

        for p_idx, pos in self.player_positions.items():
            member = self.party.members[p_idx]
            if member.fled or member.is_dead() or member.hp <= 0:
                continue
            dx = abs(from_x - pos[0])
            dy = abs(from_y - pos[1])
            if ranged:
                # Utils.distance: movement distance minus the diagonal saving
                # (Utils.java:664-675) === max(dx, dy).
                dist = max(dx, dy)
            else:
                dist = dx + dy
            if dist < least_dist or (dist == least_dist and random.randrange(2) == 0):
                least_dist = dist
                best_idx = p_idx
                best_member = member

        return best_idx, best_member, least_dist

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

        # Java GameScreen.endCombat (GameScreen.java:421-431): a won battle
        # drops a chest on the ENCOUNTER CREATURE's overworld tile unless the
        # creature has nochest or that tile's rule is unwalkable; a defeated
        # pirate leaves a boardable frigate on the creature's tile instead.
        is_nochest = getattr(self.creature_def, "no_chest", False) or getattr(self.creature_def, "nochest", False)
        is_pirate = str(self.creature_tile).lower() == "pirate" or (
            self.creature_def is not None and getattr(self.creature_def, "name", "").lower() == "pirate"
        )

        # Walkability: the creature's overworld tile (Java re-reads the tile's
        # rule at endCombat). A combat raised without encounter info (direct
        # arena use, tests) falls back to the party tile as walkable ground.
        chest_x = self.encounter_x if self.encounter_x is not None else self.party.x
        chest_y = self.encounter_y if self.encounter_y is not None else self.party.y
        walkable = self.encounter_tile_walkable if self.encounter_tile_walkable is not None else True

        if not is_nochest and walkable:
            self.chest_spawned = True
            if hasattr(self.party, "dynamic_objects"):
                self.party.dynamic_objects.append({"tile": "chest", "x": chest_x, "y": chest_y})
        elif is_pirate:
            self.chest_spawned = False
            if hasattr(self.party, "dynamic_objects"):
                self.party.dynamic_objects.append({"tile": "frigate", "x": chest_x, "y": chest_y})
        else:
            self.chest_spawned = False
