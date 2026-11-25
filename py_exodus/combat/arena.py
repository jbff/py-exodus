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
    Status,
    TileAttrib,
    TileEffect,
    Transport,
    WeaponType,
)
from py_exodus.combat.resolver import (
    AttackResolution,
    AttackResult,
    resolve_monster_attack,
    resolve_player_attack,
    trace_projectile_path,
    try_monster_magic_poke,
)
from py_exodus.entities.defs import CreatureDef
from py_exodus.world.tile_effects import apply_effect_rolled

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
    spell_res: Any | None = None
    # Java SpellUtil: LORUM, DAG_ACRON and the dungeon spells
    # never call finishPlayerTurn — in combat the caster acts again. The turn
    # is consumed by every other successful combat spell; failed casts never
    # consume it (SpellUtil.java:24-76 gates return before finishPlayerTurn).
    consume_turn: bool = True
    # True when the turn was an attack refused by the EXODUS non-exotic-weapon
    # rule (SecondaryInputProcessor.java:345-347) — the screen then plays
    # Sound.NEGATIVE_EFFECT instead of PC_ATTACK.
    attack_refused: bool = False


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
        self.variant = 0  # LairWare VARMON: 0 plain, 1/2 named variant
        self.basehp = definition.basehp if definition.basehp > 0 else 48
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): per-battle HP is
        # make_rnd(cap)|0x0F — the roll's low nibble is forced, so HP floors
        # at 15 and can exceed basehp when basehp's low nibble is not 0x0F
        # (cap 32 rolls 0x20|0x0F = 47). creatures.xml basehp doubles as the
        # per-tile GBC HP cap (the shared data source); a fixed hp set
        # explicitly on the CreatureDef (hp != the post_init basehp default)
        # is still honored. (GBC funcs5.c:1546-1554)
        if definition.hp > 0 and definition.hp != self.basehp:
            self.hp = definition.hp
        else:
            # randint(0, cap) rolls 0..cap inclusive, exactly GBC
            # make_rnd(cap + 1). randint (not randrange) on purpose: the
            # module-level randrange is the attribute RNG-scripted tests
            # stub, and spawn HP must not consume their sequences.
            self.hp = random.randint(0, self.basehp) | 0x0F
        self.max_hp = self.hp
        self.exp = definition.exp
        self.x = x
        self.y = y
        # Java Creature copy-ctor (Creature.java:70-72): a camouflaged combat
        # spawn lands on the board HIDDEN (isVisible = !camouflage). Item 4.
        self.visible = not definition.camouflage
        self.ranged = definition.ranged
        self.ranged_hit_tile = definition.ranged_hit_tile
        self.poisons = definition.poisons
        self.teleports = definition.teleports
        self.steals = definition.steals
        self.no_chest = definition.no_chest
        self.fled = False
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): set True by the
        # NECORP branch in magic.py — the GBC weakens-clamp (hp=5 +
        # monsterpower=10); the resolver halves a weakened creature's melee
        # damage.
        self.weakened = False

    @property
    def negates(self) -> bool:
        """Java ``Creature.negates`` (Creature.java:441-442): casts == "negate"."""
        return getattr(self.definition, "casts", None) == "negate"

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
        creature_variant: int = 0,
    ) -> None:
        self.party = party
        self.combat_map = combat_map
        self.creature_tile = creature_tile
        # LairWare gMonVarType (UltimaMain.c:1353): the encountered monster's
        # variant names every monster in the fight (Brigand, Devil...).
        self.creature_variant = creature_variant
        self.asset_mgr = asset_mgr
        # The map combat happens ON (Java CombatScreen.contextMap). Defaults to
        # the party's current map id; drives the Castle of Death (EXODUS) rules.
        self.context_map_id = (
            context_map_id if context_map_id is not None else getattr(party, "map_id", None)
        )
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the GBC ship-battle
        # condition is the party's transport at battle start — on a SHIP the
        # monster ranged branch becomes cannonfire (GBC battle3.c:507-536)
        self.ship_battle = getattr(party, "transport", None) == Transport.SHIP
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): per-battle 50% masskill flag gates PONTORI/REPOND (GBC funcs5.c:1354-1358; LW latch + cast-time roll is functionally equivalent)
        self.masskill: bool = random.randrange(2) == 0
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
        from py_exodus.world.monster_variants import variant_name

        vname = variant_name(self.creature_def.tile, creature_variant)
        for m in self.monsters:
            m.variant = creature_variant
            if vname is not None:
                m.name = vname

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
            # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): encounter size per
            # funcs5.c:1573-1608 (Java party-size formula superseded) — guard
            # battles spawn 8, battles fought on the Castle of Death
            # (inexodus ≡ Maps.EXODUS) spawn 8, and everything else rolls
            # rand.randint(1, 8); every count clamps to the available
            # monster_starts. Party size plays no part here. The creature
            # ``encounterSize`` XML attribute is parsed-but-unused dead data in
            # BOTH Java and the GBC port, so it is not consulted either.
            is_guard = self.creature_def.tile.lower() == "guard" or self.creature_tile.lower() == "guard"
            if is_guard or self._is_exodus_map():
                count = min(8, max_slots)
            else:
                count = min(random.randint(1, 8), max_slots)

        # Distribute monsters into crSlots
        slots: list[int] = list(range(max_slots))
        chosen_slots = sorted(random.sample(slots, count))

        monsters: list[CombatMonster] = []
        for slot_idx in chosen_slots:
            sx, sy = starts[slot_idx]
            monsters.append(CombatMonster(self.creature_def, sx, sy))

        return monsters

    def _place_players(self) -> None:
        """Members take start tiles by roster index. LairWare is the rule
        (user report 2026-11-22: a lone survivor was walled in by unseen
        corpses): only Good or Poisoned members are placed
        (UltimaSpellCombat.c:887-895, others get 0xFF = off the board), so
        the dead and ashes never occupy or block a tile. Java placed them."""
        starts = self.combat_map.player_starts or [(5, 9), (4, 8), (6, 8), (5, 10)]
        for i, member in enumerate(self.party.members):
            member.fled = False
            member.combat_map_exit_direction = None
            member.used_free_spell_in_combat = False
            if hasattr(member, "character") and hasattr(member.character, "used_free_spell_in_combat"):
                member.character.used_free_spell_in_combat = False
            sx, sy = starts[i % len(starts)]
            if not self._on_board(member):
                continue
            self.player_positions[i] = (sx, sy)
            member.combat_x = sx
            member.combat_y = sy
            member.x = sx
            member.y = sy

    @staticmethod
    def _on_board(member) -> bool:
        """LW: Good or Poisoned members stand on the board; a member who
        dies leaves it (UltimaSpellCombat.c:1239-1241)."""
        return not member.is_dead() and getattr(member, "status", None) not in (Status.ASH, Status.ASHES)

    def _board_positions(self) -> dict[int, tuple[int, int]]:
        """Tiles held by members still on the board (corpses hold none)."""
        return {
            i: pos for i, pos in self.player_positions.items()
            if self._on_board(self.party.members[i]) and not self.party.members[i].fled
        }

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
        if member.fled or member.is_disabled() or member.is_dead():
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
            # Member cannot act - advance and return. Java's keyUp logs the
            # same "Pass" line for a disabled member as for SPACE
            # (CombatScreen.java:291-292).
            self._advance_player_turn(member_idx)
            return ActionResult(success=False, action=act, message="Pass")

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
            # Java CombatScreen.java:292: the SPACE keypress logs "Pass" —
            # no member named, no turn summary.
            res = ActionResult(success=True, action=act, message="Pass")
        else:
            # Other actions (READY, WEAR, USE). Java routes these through the
            # ReadyWearInputAdapter (CombatScreen.java:959-999) rather than
            # the turn log, so this fallback stays a py UI-adaptation shim.
            res = ActionResult(success=True, action=act, message=f"{member.name} acts.")

        if res.message:
            # Java's log stays silent wherever it only plays a sound (e.g. the
            # refused EXODUS attack) — an empty result message writes nothing.
            self.log_messages.append(res.message)

        # Remove dead monsters
        self._cleanup_dead_monsters()

        # Check combat victory
        if len(self.monsters) == 0:
            # Pending item 2 (Java CombatScreen.java:448-465): the round that
            # empties combatMap IS done at once (roundIsDone via
            # combatMap.getCreatures().isEmpty(), CombatScreen.java:459) and
            # still runs endTurn before end() (CombatScreen.java:472-478) — a
            # killing action lands here before _advance_player_turn, so the
            # win round's tick runs here instead of execute_monster_turns.
            if self.ship_battle:
                self._ship_round_tick()
            self._handle_victory()
            return res

        # Check if combat finished because all players died
        if not self.player_positions:
            self._evaluate_party_status()
            return res

        # Java's finishPlayerTurn gate: failed casts leave the caster active
        # (SpellUtil.java:24-76), as do LORUM/DAG_ACRON and the
        # dungeon spells (SpellUtil.java:87-237).
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

        # Check if occupied by another player (corpses are off the board)
        for p_idx, pos in self._board_positions().items():
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
                # Flag the refusal so the screen plays Java's cue
                # (Sound.NEGATIVE_EFFECT — SecondaryInputProcessor.java:346)
                # instead of PC_ATTACK.
                return ActionResult(success=False, action=action, message="",
                                    attack_refused=True)

        weapon_def = None
        if self.asset_mgr is not None and hasattr(member, "weapon"):
            w_name = member.weapon.value if isinstance(member.weapon, WeaponType) else str(member.weapon)
            weapon_def = self.asset_mgr.get_weapon(w_name)

        is_ranged = weapon_def is not None and weapon_def.range > 1

        if is_ranged and weapon_def is not None:
            # Trace projectile path. LairWare Shoot (UltimaSpellCombat.c:
            # 708-731) steps on until a monster or the board edge with no
            # terrain test, so walls never stop a missile.
            max_range = weapon_def.range
            attack_through = True
            path = trace_projectile_path(
                combat_map=self.combat_map,
                start_x=cur_pos[0],
                start_y=cur_pos[1],
                direction=direction,
                max_range=max_range,
                attack_through_objects=attack_through,
                monsters=self.monsters,
                players=self._board_positions(),
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

            # Message parity (item 3): Java's `attackAt` logs NOTHING when the
            # shot's path carries no creature (Utils.java:841-845 returns NONE
            # silently) — the miss line is reserved for a rolled miss on a
            # reached target.
            message = ""
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

            # Message parity (item 3): with no creature on the melee tile
            # Java's `attackAt` also returns NONE silently (Utils.java:837-839
            # — no creature found, no log); the invented "swings into empty
            # space" line is gone.
            message = ""
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
        # Task 4 executed-vs-refusal rule (2026-11-14): Java never consumes a
        # PRE-execution refusal — every SpellUtil.spellCast gate
        # (SpellUtil.java:24-76 — bad target/direction, out of mana,
        # "Can't!" used free spell, NEGATE aura) returns false before any
        # finishPlayerTurn, and SpellInputProcessor (SpellInputProcessor.java:
        # 63/84/116) ignores the result — the caster REMAINS ACTIVE. But an
        # EXECUTED failure consumes: GBC battle.c:1052-1060 runs the
        # masskill-mismatch FAILED path through the effect branch and returns
        # 1 (the directional-cancel gate semantics differ per Java — those
        # stay refusals here). On success the turn is consumed unless the
        # spell is a NO_TURN spell (SpellUtil.java:87-237), whose effect
        # branch never calls finishPlayerTurn. This corrects P6's
        # over-breadth: the old success-based rule also granted a retry on
        # executed-but-failed casts.
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): FAL_DIVI re-dispatches
        # to the cleric spell menu (GBC menucmd.c:1519-1530; LW
        # UltimaSpellCombat.c corroboration) — GBC's fal-divi battle variant
        # was never wired (battle.c:1129-1160, the block is commented out), so
        # the combat site consumes the followup as a no-op rather than
        # re-opening a spell menu mid-round (LW's battle case 9 goes the other
        # way, ClericChoose; the GBC referee source settles it).
        consumes = bool(spell_res.executed and resolved not in NO_TURN_SPELLS)
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

    def _ship_round_tick(self) -> None:
        """Run Java's combat round-finish endTurn for a ship battle (pending
        item 2).

        Java truth: ``exodus/CombatScreen.java:470-496`` ``finishTurn`` — every
        combat round-finish opens with
        ``party.endTurn(Maps.get(combatMap.getId()), combatMap.getType())``
        (``CombatScreen.java:472``), i.e. the round counts as a move. The per-member meal block is skipped:
        Java gates it on ``mapType != MapType.combat`` (``Party.java:600``).

        Scoping note (pending item 2, ruled ship-once): Java runs this
        endTurn on EVERY combat round; the port routes only ship battles
        through it — plain combat rounds tick nothing (user ruling
        2026-11-13, flagged then implemented here).

        Nothing else: Java's round-end calls endTurn plus
        ``context.getAura().passTurn`` (``CombatScreen.java:474``) — the aura
        pass already lives in ``execute_monster_turns``; no moon advance (Java
        advances moons on GameScreen's turn hooks only,
        ``GameScreen.java:706-754``). This arena round-end is the only caller —
        the screen turn hooks (overworld ``_finish_turn``) do not run during
        combat.
        """
        sosaria = self.context_map_id == MAP_NAME_TO_ID["SOSARIA"]
        # surface=True is moot: the meal block is skipped under combat=True.
        self.party.end_turn(surface=True, sosaria=sosaria, combat=True)

    # --- Monster Turn Execution & AI ---

    def execute_monster_turns(self) -> list[MonsterTurnResult]:
        """Execute turn for each active monster and check win/loss.

        Java CombatScreen.finishTurn (CombatScreen.java:479-502): the aura
        passes a turn every round and a live QUICKNESS aura skips the
        creature-action sequence entirely (silent in Java). There is NO
        per-round poison tick in combat (party.endTurn runs the exploration
        tick at the round level; it is out of this arena's scope — except the
        ship-battle round tick above, which Java's round-finish endTurn
        carries; see _ship_round_tick).
        """
        if self.is_finished:
            return []

        # Pending item 2 (Java CombatScreen.java:472): the round-finish
        # endTurn runs before the aura pass and the creature phase — Java's
        # finishTurn opens with party.endTurn, then aura.passTurn
        # (CombatScreen.java:472-474).
        if self.ship_battle:
            self._ship_round_tick()

        aura = getattr(self.party, "aura", None)
        if aura is not None:
            # LairWare UltimaSpellCombat.c:1102-1105: `if (gTimeNegate != 0)
            # { gTimeNegate--; goto combatstart; }` - the count is tested
            # before it drops, so a stop of N skips N monster phases.
            stopped = aura.get_type() == AuraType.QUICKNESS and aura.is_active()
            aura.pass_turn()
            # USER-DIRECTED GBC-RULES DEVIATION (ruled item 16, 2026-11-14,
            # both referees): the QUICKNESS aura has NO effect during combat
            # on the EXODUS map — stop time does not function on the Castle of
            # Death, so the creature phase runs (GBC ult3.c:1024-1034; LW
            # UltimaSpellCombat.c:1082,1102-1105). The aura still ticks down.
            if stopped and not self._is_exodus_map():
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
        """One monster's turn, LairWare ``Combat`` monster loop
        (UltimaSpellCombat.c:1105-1250) with ``FigureNewMonPosition``
        (1359-1416).

        - A member within one step on both axes (diagonals too) is attacked
          (``zp[0xD0] == 0`` -> ``afternext``).
        - A dragon fires on RandNum(0, 255) < 128 along its heading
          (``monshoot``).
        - The spell casters (serpent, Man-O-War, wizard, daemon, dragon,
          balron) may cast at a member anywhere (``monmagic``).
        - Otherwise the monster steps toward its target (``monlb``), or
          stays when no member can be reached.

        Replaces Java ``CombatScreen.creatureAction`` (teleport, a 34% bolt
        for every ranged creature, Manhattan-only melee, random-direction
        moves slowed by terrain).
        """
        # Java creatureAction:692-694 — a negating creature sets the
        # player-side NEGATE aura (no creature in creatures.xml negates).
        aura = getattr(self.party, "aura", None)
        if monster.negates and aura is not None:
            aura.set(AuraType.NEGATE, 2)

        # A JINX aura leaves no targetable member (batch P owns the spell).
        if aura is not None and aura.get_type() == AuraType.JINX:
            return None

        from_pos = (monster.x, monster.y)
        target_idx, close, step, heading = self._figure_new_mon_position(monster)

        # UltimaSpellCombat.c:1117-1118: `if (zp[0xD0] == 0) goto afternext`.
        if close and target_idx is not None:
            return self._monster_melee(monster, target_idx, from_pos)

        # UltimaSpellCombat.c:1119-1124: a dragon fires half the time. With no
        # target of its own it has no heading and holds its fire (LW would
        # reuse a stale zp[0xF5]/zp[0xF6]).
        if str(monster.tile).lower() == "dragon" and target_idx is not None:
            if random.randint(0, 255) < 128:
                return self._monster_shoot(monster, heading, from_pos)

        # UltimaSpellCombat.c:1125-1140, 1145-1153 (monmagic): RandNum(0,
        # 0xC0) > 127 for a caster attacks a member anywhere. USER-DIRECTED
        # GBC-RULES DEVIATION (2026-11-14): the GBC magic poke picks a random
        # living member (LW: a random slot, only a Good member; ledger ask).
        poke_res = try_monster_magic_poke(
            monster, self._get_living_party_members(), context_map_id=self.context_map_id
        )
        if poke_res is not None:
            poke_member = (
                self._member_at(*poke_res.target_pos)
                if poke_res.target_pos is not None
                else None
            )
            return MonsterTurnResult(
                monster_name=monster.name,
                action_type="ranged",
                from_pos=from_pos,
                to_pos=(poke_res.target_pos or from_pos),
                attack_res=poke_res,
                message=self._compose_monster_message(
                    poke_res.message,
                    self._monster_hit_affordance_lines(monster.name, poke_member, poke_res),
                ),
            )

        # UltimaSpellCombat.c:1141-1144, 1154-1164 (nextplr/monlb): step to
        # zp[0xF7], zp[0xF8] when a member was found; otherwise stay.
        if target_idx is None or step is None:
            return None
        monster.x, monster.y = step
        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="advance",
            from_pos=from_pos,
            to_pos=step,
            message="",
        )

    def _figure_new_mon_position(
        self, monster: CombatMonster
    ) -> tuple[int | None, bool, tuple[int, int] | None, tuple[int, int]]:
        """LairWare ``FigureNewMonPosition`` (UltimaSpellCombat.c:1359-1416).

        Walks the members in slot order, skipping the dead and ashes. A
        member within one step on both axes is close: it becomes the target
        (``zp[0xD0] = 0``), and an orthogonal neighbour ends the search.
        Otherwise the nearest member by |dx| + |dy| that the monster can
        step toward is the target (a tie keeps the earlier member); the step
        is the diagonal (sign dx, sign dy), else the vertical, else the
        horizontal one (``CombatValidMove``). A member no step leads toward
        is skipped. Returns (target index, close, step, heading)."""
        best = 0xFF
        target: int | None = None
        step: tuple[int, int] | None = None
        heading = (0, 0)
        close = False
        mx, my = monster.x, monster.y
        for idx in range(len(self.party.members)):
            pos = self._board_positions().get(idx)
            if pos is None:
                continue
            dx, dy = pos[0] - mx, pos[1] - my
            adx, ady = abs(dx), abs(dy)
            if adx < 2 and ady < 2:
                # markclose (UltimaSpellCombat.c:1407-1411)
                best, target, close = 0, idx, True
                if adx + ady < 2:
                    break
                continue
            if adx + ady >= best:
                continue
            hx = (dx > 0) - (dx < 0)
            hy = (dy > 0) - (dy < 0)
            for nx, ny in ((mx + hx, my + hy), (mx, my + hy), (mx + hx, my)):
                if self._combat_valid_move(monster, nx, ny):
                    best, target, step, heading = adx + ady, idx, (nx, ny), (hx, hy)
                    break
        return target, close, (None if close else step), heading

    def _combat_valid_move(self, monster: CombatMonster, x: int, y: int) -> bool:
        """LairWare ``CombatValidMove`` (UltimaSpellCombat.c:616-631) on the
        board's tile: a sea monster (serpent, Man-O-War) enters only water;
        any other only grass, brush, forest or floor. Monsters and members
        show on the board, so their tiles never qualify. No terrain slows a
        monster."""
        if not (0 <= x < self.combat_map.width and 0 <= y < self.combat_map.height):
            return False
        tile = self.combat_map.get_tile(x, y)
        name = str(getattr(tile, "name", "") or "").lower()
        if tile is None:
            pass  # a bare test board without terrain
        elif getattr(monster.definition, "swims", False):
            if name != "water":
                return False
        elif name not in ("grass", "brush", "forest", "floor"):
            return False
        if any(not m.is_dead and (m.x, m.y) == (x, y) for m in self.monsters):
            return False
        return (x, y) not in self._board_positions().values()

    def _monster_melee(
        self, monster: CombatMonster, target_idx: int, from_pos: tuple[int, int]
    ) -> MonsterTurnResult:
        """LairWare ``afternext`` (UltimaSpellCombat.c:1196-1250): the armour
        roll and damage against the close member."""
        target_member = self.party.members[target_idx]
        target_pos = self.player_positions[target_idx]
        attack_res = resolve_monster_attack(
            monster=monster,
            target_player=target_member,
            armor_def=self._get_player_armor(target_member),
            is_ranged=False,
            context_map_id=self.context_map_id,
        )
        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="attack",
            from_pos=from_pos,
            to_pos=target_pos,
            attack_res=attack_res,
            message=self._compose_monster_message(
                attack_res.message,
                self._monster_hit_affordance_lines(monster.name, target_member, attack_res),
            ),
        )

    def _monster_shoot(
        self, monster: CombatMonster, heading: tuple[int, int], from_pos: tuple[int, int]
    ) -> MonsterTurnResult:
        """LairWare ``monshoot`` (UltimaSpellCombat.c:1165-1194): the fire
        steps along the heading to the board edge, over everything; the
        first member on its line takes the damage roll with no armour check
        (``goto c8777``, 1218-1226)."""
        hx, hy = heading
        x, y = monster.x, monster.y
        path: list[tuple[int, int]] = []
        while True:
            x, y = x + hx, y + hy
            if not (0 <= x < self.combat_map.width and 0 <= y < self.combat_map.height):
                break
            path.append((x, y))
            member = self._member_at(x, y)
            if member is None:
                continue
            from py_exodus.combat.resolver import (
                _deal_monster_damage_to_member,
                lw_monster_damage,
            )

            damage = lw_monster_damage(monster, member, self.context_map_id)
            _deal_monster_damage_to_member(member, damage)
            attack_res = AttackResolution(
                hit=True,
                damage=damage,
                killed=getattr(member, "status", None) == Status.DEAD,
                result=AttackResult.HIT,
                target_pos=(x, y),
                projectile_path=path,
                message="Fiery Hit!",
            )
            return MonsterTurnResult(
                monster_name=monster.name,
                action_type="ranged",
                from_pos=from_pos,
                to_pos=(x, y),
                attack_res=attack_res,
                message=self._compose_monster_message(
                    attack_res.message,
                    self._monster_hit_affordance_lines(monster.name, member, attack_res),
                ),
            )
        return MonsterTurnResult(
            monster_name=monster.name,
            action_type="ranged",
            from_pos=from_pos,
            to_pos=path[-1] if path else from_pos,
            message="",
        )

    # --- Monster-hit affordance (playtest-1 fix batch, item 4) -------------
    def _monster_hit_affordance_lines(self, monster_name: str, member, attack_res) -> list[str]:
        """PLAYABILITY AFFORDANCE — NOT message parity (user-approved
        deviation, 2026-11-15). Java logs NOTHING on any monster action (the
        melee branch is sounds-only, CombatScreen.java:720-745), but this
        port's combat channel is the text log, so a landed hit or a member
        death marks the transcript once per event, mirroring the task-6
        turn-marker pattern ("X's turn.", "Pass") — event-driven, never
        per-frame. Misses stay silent to keep the noise down (the approved
        scope covers HITS and DEATHS only)."""
        if attack_res is None or member is None:
            return []
        member_name = getattr(member, "name", "member")
        lines: list[str] = []
        damage = getattr(attack_res, "damage", 0) or 0
        if getattr(attack_res, "hit", False) and damage > 0:
            lines.append(f"{monster_name} hits {member_name} ({-damage}).")
        if getattr(attack_res, "killed", False):
            lines.append(f"{member_name} falls!")
        return lines

    @staticmethod
    def _compose_monster_message(base: str, lines: list[str]) -> str:
        """Join the mechanic feedback (e.g. "POISONED!", "Fiery Hit!",
        "Cannonball barrage!") and the hit/death affordance lines into the
        multi-line message the log pipeline already renders."""
        parts = [p for p in ([base, *lines]) if p]
        return "\n".join(parts)

    def _member_at(self, x: int, y: int) -> PartyMember | None:
        """The party member occupying a tile (Java rangedAttackAt's defender
        scan, CombatScreen.java:593-599); the dead are off the board (LW)."""
        for p_idx, pos in self._board_positions().items():
            if pos == (x, y):
                return self.party.members[p_idx]
        return None

    def _get_player_armor(self, member: PartyMember) -> Any:
        if self.asset_mgr is not None and hasattr(member, "armor"):
            a_name = member.armor.value if isinstance(member.armor, ArmorType) else str(member.armor)
            return self.asset_mgr.get_armor(a_name)
        return None

    # --- End of Round Checks & Completion ---

    def _evaluate_party_status(self) -> None:
        # Java has no fled-battle outcome left (FLEE is commented out of
        # CombatScreen) — combat ends in victory or defeat only. Party
        # members keep their ``fled`` flag purely for the blocking skip
        # (hasBlockingCombatPlayerAt skips fled members).
        living_on_board = [
            i for i, pos in self.player_positions.items()
            if not self.party.members[i].is_dead() and not self.party.members[i].fled
        ]
        any_alive = any(not m.is_dead() for m in self.party.members)

        if not living_on_board:
            self.is_finished = True
            if not any_alive:
                self.is_defeat = True
                self.is_victory = False

    def _handle_victory(self) -> None:
        self.is_finished = True
        self.is_victory = True
        self.is_defeat = False
        # LairWare Victory (UltimaSpellCombat.c:850): `gTimeNegate = ... = 0;`
        # stopped time ends with a won fight.
        aura = getattr(self.party, "aura", None)
        if aura is not None and aura.get_type() == AuraType.QUICKNESS:
            aura.set(AuraType.NONE, 0)

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
        # The drop belongs to the surface map the party's objects live on. A
        # fight raised in a town or castle (context_map_id 10, 12, ...) has
        # no encounter tile and fell back to the party's overworld x,y: the
        # Death Gulch pub merchant left a chest on Sosaria at the town's
        # gate (user ruling 2026-11-22: nothing crosses between maps).
        on_surface = self.context_map_id is None or str(self.context_map_id) == str(
            getattr(self.party, "objects_map_id", 0)
        )

        if not on_surface:
            self.chest_spawned = False
        elif not is_nochest and walkable:
            self.chest_spawned = True
            if hasattr(self.party, "dynamic_objects"):
                self.party.dynamic_objects.append({"tile": "chest", "x": chest_x, "y": chest_y})
        elif is_pirate:
            self.chest_spawned = False
            # LairWare AttackCode (UltimaMain.c:1354-1357): the pirate's tile
            # gets a frigate (0x2C) only `if (Party[1] != 0x16)`, i.e. when the
            # party is NOT aboard its ship; at sea the tile stays open water
            # (a frigate there would seal a one-tile channel).
            if self.party.transport != Transport.SHIP and hasattr(self.party, "dynamic_objects"):
                already_has_frigate = any(
                    str(obj.get("tile", "")).lower() == "frigate"
                    and obj.get("x") == chest_x
                    and obj.get("y") == chest_y
                    for obj in self.party.dynamic_objects
                )
                if not already_has_frigate:
                    self.party.dynamic_objects.append({"tile": "frigate", "x": chest_x, "y": chest_y})
        else:
            self.chest_spawned = False
