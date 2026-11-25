"""Party management, party members, and active game exploration state."""
from __future__ import annotations

import random
from typing import Any

from py_exodus.constants import (
    MAX_PARTY_MEMBERS,
    Direction,
    Profession,
    Status,
    Transport,
)
from py_exodus import debug
from py_exodus.aura import Aura
from py_exodus.entities.character import Character


# LairWare EatFood (UltimaMisc.c:1468-1474): a borrow does `Player[34] -=
# 157`, adding 256 - 157 = 99 to the fraction byte that AgeChars eats 10 of
# a tick. In the port's pool (40 a tick = 10 fraction points x 4) one food
# is 99 x 4 = 396, and the residual is carried: 9.9 ticks a ration.
SUBMORSELS_PER_FOOD = 396

class PartyDeathException(Exception):
    """Raised when non-combat damage leaves every party member dead.

    Java truth: ``exodus/Party.java:556-577`` — ``PartyMember.applyDamage``
    throws ``PartyDeathException`` when ``!combatRelatedDamage`` damage kills
    the last living member. Screens catch it and route to the start screen
    (``GameScreen.java:444-446`` ``partyDeath()``); combat-related damage never
    raises here because a combat loss is routed when combat ends
    (``CombatScreen.java:562-589`` → ``GameScreen.java:433-446``).
    """


class PartyMember:
    """Character joined into an active adventuring Party with combat and turn state."""

    def __init__(
        self,
        *args: Any,
        party: Party | None = None,
        fled: bool = False,
        combat_map_exit_direction: Direction | None = None,
        **kwargs: Any,
    ) -> None:
        if args and (isinstance(args[0], PartyMember) or isinstance(args[0], Character)):
            char = getattr(args[0], "character", args[0])
        else:
            char = Character(*args, **kwargs)

        object.__setattr__(self, "character", char)
        object.__setattr__(self, "party", party)
        object.__setattr__(self, "fled", fled)
        object.__setattr__(self, "combat_map_exit_direction", combat_map_exit_direction)

    @property
    def player(self) -> Character:
        """Self-reference for compatibility with Java-style member.player."""
        return self.character

    def __getattr__(self, name: str) -> Any:
        return getattr(self.character, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in (
            "character",
            "party",
            "fled",
            "combat_map_exit_direction",
        ):
            object.__setattr__(self, name, value)
        else:
            setattr(self.character, name, value)

    def apply_damage(self, damage: int, combat_related_damage: bool = False) -> bool:
        """Apply damage to this member; DEAD when damage leaves hp below 1.

        Java truth: ``exodus/Party.java:556-577`` ``PartyMember.applyDamage``.
        This is the single damage-application chokepoint for the party death
        flow — Tasks 5 (tick engine), 6, 12, and 13 must route every direct
        damage path (starvation, tile effects, traps, monster attacks,
        spells) through it. A member whose hp is driven below 0 by damage is
        set DEAD with hp clamped to 0 — exactly 0 hp after a blow is dead too
        (LairWare HPSubtract ``if (hp < 1)``; Java's ``newHp < 0`` let it
        live). A non-combat blow that leaves the
        whole party dead raises ``PartyDeathException`` (only when the member
        belongs to an owned ``Party``); the screen that applied the damage
        catches it and calls ``BaseScreen.check_party_death()`` to route to
        the start screen. Returns False (no effect) for a member already DEAD.
        """
        # USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): debug cheat
        # harness (GBC cheat.c:414-825) — NOHURT: HP NEVER DECREASES. The
        # guard sits at this earliest chokepoint so no death/wipe check can
        # misfire downstream; the hit is reported as applied (True) but
        # hp/status stay untouched. Cheat path only: an already-DEAD member
        # returns True here too (the normal is_dead() -> False path below
        # is bypassed, so callers must not read this as a revive).
        if debug.CHEATS.nohurt:
            return True

        if self.is_dead():
            return False

        new_hp = self.hp - damage
        # LairWare HPSubtract (UltimaMain.c:3250-3258): `if (hp < 1)` the
        # member is dead, so a blow to exactly 0 kills (Java: < 0). User
        # ruling Q18. A member raised at 0 HP is alive until the next blow.
        if new_hp < 1:
            self.status = Status.DEAD
            new_hp = 0
        self.hp = new_hp

        if (
            not combat_related_damage
            and self.is_dead()
            and self.party is not None
            and not self.party.is_anyone_alive()
        ):
            raise PartyDeathException()

        return True

    @classmethod
    def from_character(cls, char: Character, party: Party | None = None) -> PartyMember:
        """Promote an existing Character into a PartyMember."""
        return cls(char, party=party)

    def heal(self, heal_type: object) -> bool:
        """Apply a healer service to this member (Java ``Party.java:381-433``
        ``PartyMember.heal(HealType)``).

        Need-checks return False and leave the member untouched — the caller
        (Java ``HealerService.java:58-64``) charges NOTHING when heal returns
        False.  CURE only when POISONED (status -> GOOD); FULLHEAL sets max
        HP for anyone, the dead and the ashes too, rejected only at full HP
        (LairWare); RESURRECT only when DEAD, RECALL only when ASH, each
        just -> GOOD with HP left as it is (LairWare; Java set 1); HEAL
        rejected when DEAD or full and adds 75 + (rand % 25).
        NOTE ``Party.java:416-422`` RECALL performs NO wisdom adjustment in
        this codebase (the ``wis -= 5`` variant is not present), so none is
        ported here.
        """
        kind = str(getattr(heal_type, "name", heal_type)).upper()

        if kind == "NONE":
            return True

        if kind == "CURE":
            if self.status != Status.POISONED:
                return False
            self.status = Status.GOOD

        elif kind == "FULLHEAL":
            # LairWare UltimaMisc.c:1747-1750: HP = max HP with no status
            # test, so the dead and the ashes are healed too (and stay so).
            if self.hp == self.max_hp:
                return False
            self.hp = self.max_hp

        elif kind == "RESURRECT":
            # LairWare UltimaMisc.c:1766-1767: 'D' -> 'G' and nothing else;
            # HP stays (0, or the max a Healing gave first). Java set 1.
            if self.status != Status.DEAD:
                return False
            self.status = Status.GOOD

        elif kind == "HEAL":
            if self.status == Status.DEAD or self.hp == self.max_hp:
                return False
            # Java: health += 75 + (rand.nextInt(256) % 25)
            self.hp += 75 + (random.randint(0, 255) % 25)

        elif kind == "RECALL":
            # LairWare UltimaMisc.c:1783-1784: 'A' -> 'G', HP untouched.
            if self.status != Status.ASH:
                return False
            self.status = Status.GOOD

        else:
            return False

        if self.hp > self.max_hp:
            self.hp = self.max_hp

        return True


    def to_dict(self) -> dict[str, Any]:
        """Serialize party member state."""
        d = self.character.to_dict()
        d["fled"] = self.fled
        return d

    def __repr__(self) -> str:
        return f"PartyMember({self.character!r}, fled={self.fled})"


class Party:
    """Active player party (1-4 members) with coordinates, transport, and pooled resources."""

    # NOT APPLIED since batch W: LairWare PutSosaria saves the whole map, so
    # every object is saved (UltimaMisc.c:838-843). Kept for reference.
    # Cap on the dynamic-objects list WRITTEN INTO SAVES (Java parity, item 9):
    # SaveGame.java:38-40 holds three byte[24] blocks (tileids/x/y), so the
    # saved block holds at most 24 objects.
    #
    # The "24 plus an off-by-one" question resolves as follows: Java's fill
    # loop (Context.java:158-166) writes `objects[count] = d` BEFORE testing
    # `if (count > 23) break;` against a 24-length array. The guard is dead
    # code — on a 25th map object, `objects[24]` throws
    # ArrayIndexOutOfBoundsException before the break can fire, and the
    # exception escapes saveGame uncaught (GameScreen.java:559 Q-key path),
    # so Java never completes a save once a 25th object exists. Java could
    # never legitimately hold 25 entries; 24 is the cap, and it is NOT a
    # count that includes the moving-party ship — while boarded, the
    # frigate is removed from map.objects (GameScreen.java:952-960) and
    # re-added on disembark (GameScreen.java:584-588), so the saved block
    # covers only disembarked frigates, dropped chests, etc. Java keeps the
    # FIRST 24 in insert order (BaseMap.objects is an append-ordered list,
    # BaseMap.java:987) = the OLDEST 24; the newest are lost. Py has no
    # crash to port (the py save must complete), so the cap is applied as a
    # write-time truncation at the save boundary (to_dict) with the same
    # oldest-first direction.
    DYNAMIC_OBJECTS_SAVE_CAP = 24
    # Java dynamic-monster cap (Context.java:176-185): saved block keeps at
    # most 8 entries in insertion order (oldest 8); write-time truncation only.
    DYNAMIC_MONSTERS_SAVE_CAP = 8

    def __init__(
        self,
        members: list[Character | PartyMember] | None = None,
        # Default new-game position: Java seeds (45, 19) (SaveGame.java:164-169)
        # — the grass tile one step south of the Castle British entrance (45,18).
        # USER-DIRECTED NIT (2026-11-15): spawn one south + one west of the Java
        # default (45,19), so fresh Journeys start at (44, 20).
        x: int = 44,
        y: int = 20,
        map_id: int = 0,
        dungeon_level: int = 0,
        transport: Transport | str = Transport.FOOT,
        wind_direction: Direction | str | None = Direction.NORTH,
        gold: int | None = None,
        food: int | None = None,
        moves: int = 0,
        age_count: int = 0,
        heal_count: int = 0,
        moon_phase: int = 12,
        moon_turns: int = 0,
        torch_duration: int = 0,
        active_member_index: int = 0,
        exodus_cards_status: int = 0,
        exodus_defeated: int = 0,
        dynamic_objects: list[dict[str, int]] | None = None,
        dynamic_monsters: list[dict[str, int]] | None = None,
        objects_map_id: int = 0,
        whirlpool_return: tuple[int, int] | None = None,
        sosaria_objects: list[dict[str, int]] | None = None,
    ) -> None:
        self.members: list[PartyMember] = []
        if members:
            for m in members:
                self.add_member(m)

        self.x = x
        self.y = y
        self.map_id = map_id
        self.dungeon_level = dungeon_level

        # Transport resolution
        if isinstance(transport, Transport):
            self.transport = transport
        else:
            t = str(transport).strip().lower()
            lookup_t = {
                "foot": Transport.FOOT,
                "horse": Transport.HORSE,
                "ship": Transport.SHIP,
            }
            self.transport = lookup_t.get(t, Transport.FOOT)

        self.active_member_index = active_member_index

        # Wind direction resolution. None is the becalmed/calm state
        # (LairWare WindDir 0): ValidTrans refuses every heading while calm
        # (UltimaMain.c:3228), and DoWind's re-roll can land on it.
        if wind_direction is None:
            self.wind_direction: Direction | None = None
        elif isinstance(wind_direction, Direction):
            self.wind_direction = wind_direction
        else:
            w_str = str(wind_direction).strip().upper()
            w_dir = Direction.from_name_or_key(w_str)
            if w_dir is not None:
                self.wind_direction = w_dir
            elif w_str in Direction.__members__:
                self.wind_direction = Direction[w_str]
            else:
                self.wind_direction = Direction.NORTH

        # LairWare DoWind's WindCtr (UltimaMain.c:69, 3288-3291): a plain
        # global, not saved, so it starts at 0 on every load. The poll clock
        # turns game time into 5/60 s GetKeyMouse polls (world/realtime.py).
        from py_exodus.world.realtime import PollClock  # world imports party

        self.wind_ctr = 0
        self.wind_clock = PollClock()
        # LairWare zp[0xCD] (FinishAll, UltimaMisc.c:1115-1118): one byte
        # for the surface and towns alike, flipped each mounted turn; not
        # saved, so it starts at 0.
        self.finish_all_flip = 0

        # Gold and food live on each member (Java CharacterRecord); these
        # optional constructor arguments RE-SEED the party's total via the
        # derived setters below. There is no party-level pool, and the
        # default of None leaves the members' own purses untouched.
        if gold is not None:
            self.gold = gold
        if food is not None:
            self.food = food
        self.moves = moves
        self.torch_duration = torch_duration

        # LairWare AgeChars counters (UltimaMisc.c:1405-1414): gTime[0]
        # counts the off-Sosaria calls (a tick every 4th), gTime[1] the ticks
        # (+1 HP every 10th). LW's globals start at 0. Persisted; saves
        # without them load 0 (the retired ``regen_turns`` is ignored).
        self.age_count = age_count
        self.heal_count = heal_count

        # Move-driven moon clock (LairWare MoonGateUpdate, ledger W-03):
        # ``moon_phase`` is the 0..23 combined celestial phase the moongate
        # routing and sky strip derive from; ``moon_turns`` counts Sosaria
        # turns (the moons stand still anywhere else), advancing every 4th.
        # Both persisted so a save/load resumes the same integer phase.
        # A new game starts at 12, both moons at phase 4 with fresh counters:
        # LairWare ``gMoon[2] = {12,4}, gMoonDisp[2] = {'4','4'}``
        # (UltimaMain.c:36). Trammel = phase // 3, Felucca = phase % 8.
        self.moon_phase = moon_phase % 24
        self.moon_turns = moon_turns

        # Exodus machine card-insertion status (SaveGame.exodusCardsStatus):
        # bit 0x1 love, 0x2 sol, 0x4 moons, 0x8 death.
        self.exodus_cards_status = exodus_cards_status & 0xF

        # Beat-Exodus flag (LW Party[16]): set to 1 when the final Exodus
        # card lands (LW UltimaMisc.c:2359); gates the post-Exodus shrine
        # race-cap lift (UltimaMisc.c:1091 — the maxval clamp runs only
        # while Party[16] == 0). Persisted with the party like LW's
        # own-save Party array.
        self.exodus_defeated = exodus_defeated

        # Dynamic overworld delta: up to 24 mutable objects on Sosaria (e.g. docked ships, horses, chests)
        self.dynamic_objects: list[dict[str, int]] = (
            list(dynamic_objects) if dynamic_objects is not None else []
        )
        # Which surface map ``dynamic_objects`` belongs to (0 Sosaria, 13
        # Ambrosia). LairWare keeps parked ships and horses IN the Sosaria
        # map grid: the whirlpool PushSosaria()s the whole map before loading
        # Ambrosia and PullSosaria()s it on the way back
        # (refs/ultima3/Sources/UltimaMain.c:3052,3090; UltimaMisc.c:923-968),
        # and Ambrosia is reloaded fresh from its resource every visit. So a
        # Sosaria ship never exists on Ambrosia and Ambrosia's objects are
        # gone once the party leaves (see ``enter_surface_map``).
        self.objects_map_id: int = objects_map_id
        # Where the Sosaria whirlpool took the party (LairWare Party[4]/[5],
        # UltimaMain.c:3043-3046): the Ambrosia whirlpool returns it there.
        self.whirlpool_return: tuple[int, int] | None = (
            tuple(whirlpool_return) if whirlpool_return else None
        )
        self.sosaria_objects: list[dict[str, int]] = (
            list(sosaria_objects) if sosaria_objects is not None else []
        )
        # Dynamic monsters delta: up to 8 active monsters on Sosaria
        self.dynamic_monsters: list[dict[str, int]] = (
            list(dynamic_monsters) if dynamic_monsters is not None else []
        )

        # The frigate most recently disembarked. Runtime-only. LairWare
        # ships have no hull, so this only tells autoplay which ship is its.
        self.last_ship: dict[str, int] | None = None

        # The single typed aura the party carries (Java Context.getAura,
        # objects/Aura.java): N (negate time) sets QUICKNESS (LairWare
        # gTimeNegate = 10, ledger T-13); FinishAll and the combat round
        # count it down via pass_turn.
        # Runtime-only: Java keeps it on Context, not the SaveGame.
        self.aura: Aura = Aura()

    # --- Aliases & Properties ---
    @property
    def moons(self) -> tuple[int, int]:
        """Return celestial moon phases (trammel, felucca)."""
        return getattr(self, "_moons", (0, 0))

    @moons.setter
    def moons(self, val: tuple[int, int]) -> None:
        self._moons = val

    @property
    def active_member(self) -> PartyMember | None:
        """Return currently active PartyMember or None."""
        if 0 <= self.active_member_index < len(self.members):
            return self.members[self.active_member_index]
        return None

    @property
    def active_player(self) -> int:
        """Alias for active_member_index."""
        return self.active_member_index

    @active_player.setter
    def active_player(self, val: int) -> None:
        self.active_member_index = val

    @property
    def torchduration(self) -> int:
        """Alias for torch_duration."""
        return self.torch_duration

    @torchduration.setter
    def torchduration(self, val: int) -> None:
        self.torch_duration = val

    @property
    def torches(self) -> int:
        return sum(getattr(m, "torches", 0) for m in self.members)

    @torches.setter
    def torches(self, val: int) -> None:
        cur = self.torches
        diff = val - cur
        if diff > 0 and self.members:
            target = self.active_member or self.members[0]
            target.torches = getattr(target, "torches", 0) + diff
        elif diff < 0:
            need = -diff
            for m in self.members:
                t = getattr(m, "torches", 0)
                take = min(t, need)
                m.torches = t - take
                need -= take
                if need <= 0:
                    break

    @property
    def gems(self) -> int:
        return sum(getattr(m, "gems", 0) for m in self.members)

    @gems.setter
    def gems(self, val: int) -> None:
        cur = self.gems
        diff = val - cur
        if diff > 0 and self.members:
            target = self.active_member or self.members[0]
            target.gems = getattr(target, "gems", 0) + diff
        elif diff < 0:
            need = -diff
            for m in self.members:
                t = getattr(m, "gems", 0)
                take = min(t, need)
                m.gems = t - take
                need -= take
                if need <= 0:
                    break

    @property
    def keys(self) -> int:
        return sum(getattr(m, "keys", 0) for m in self.members)

    @keys.setter
    def keys(self, val: int) -> None:
        cur = self.keys
        diff = val - cur
        if diff > 0 and self.members:
            target = self.active_member or self.members[0]
            target.keys = getattr(target, "keys", 0) + diff
        elif diff < 0:
            need = -diff
            for m in self.members:
                t = getattr(m, "keys", 0)
                take = min(t, need)
                m.keys = t - take
                need -= take
                if need <= 0:
                    break

    @property
    def powder(self) -> int:
        return sum(getattr(m, "powder", 0) for m in self.members)

    @powder.setter
    def powder(self, val: int) -> None:
        cur = self.powder
        diff = val - cur
        if diff > 0 and self.members:
            target = self.active_member or self.members[0]
            target.powder = getattr(target, "powder", 0) + diff
        elif diff < 0:
            need = -diff
            for m in self.members:
                t = getattr(m, "powder", 0)
                take = min(t, need)
                m.powder = t - take
                need -= take
                if need <= 0:
                    break

    # --- Party Member Management ---
    def add_member(self, member: Character | PartyMember) -> PartyMember:
        """Add a member to the party, ensuring maximum capacity is respected."""
        if len(self.members) >= MAX_PARTY_MEMBERS:
            raise ValueError(f"Party is full (maximum {MAX_PARTY_MEMBERS} members).")

        if isinstance(member, PartyMember):
            member.party = self
            pm = member
        else:
            pm = PartyMember(member, party=self)

        self.members.append(pm)
        return pm

    def remove_member(self, index_or_name: int | str) -> PartyMember | None:
        """Remove a party member by index or character name."""
        idx: int | None = None
        if isinstance(index_or_name, int):
            if 0 <= index_or_name < len(self.members):
                idx = index_or_name
        else:
            for i, m in enumerate(self.members):
                if m.name.lower() == index_or_name.lower():
                    idx = i
                    break

        if idx is None:
            return None

        removed = self.members.pop(idx)
        removed.party = None
        if self.active_member_index >= len(self.members):
            self.active_member_index = max(0, len(self.members) - 1)
        return removed

    def get_member(self, index: int) -> PartyMember | None:
        """Get party member at index safely."""
        if 0 <= index < len(self.members):
            return self.members[index]
        return None

    def swap_members(self, p1: int, p2: int) -> None:
        """Swap positions of two members in the party order."""
        size = len(self.members)
        if p1 >= size or p2 >= size or p1 < 0 or p2 < 0 or p1 == p2:
            return

        self.members[p1], self.members[p2] = self.members[p2], self.members[p1]

        # Update active member index to follow the active character
        if self.active_member_index == p1:
            self.active_member_index = p2
        elif self.active_member_index == p2:
            self.active_member_index = p1

    def swap_players(self, p1: int, p2: int) -> None:
        """Alias for swap_members."""
        self.swap_members(p1, p2)

    def get_next_active_index(self, from_index: int | None = None) -> int:
        """Find index of next non-disabled member in turn rotation."""
        if not self.members:
            return 0

        start = self.active_member_index if from_index is None else from_index
        count = len(self.members)
        for offset in range(1, count + 1):
            idx = (start + offset) % count
            if not self.members[idx].is_disabled():
                return idx

        return self.active_member_index

    @property
    def living_members(self) -> list[PartyMember]:
        """Return all party members that are alive."""
        return [m for m in self.members if not m.is_dead()]

    @property
    def able_combat_members(self) -> list[PartyMember]:
        """Return living party members able to take combat turns (not disabled and not fled)."""
        return [m for m in self.members if not m.is_disabled() and not m.fled and not m.is_dead()]

    # --- Resources & Turn Actions ---
    @property
    def gold(self) -> int:
        """Total gold carried by the party.

        Java truth: gold lives on each ``CharacterRecord`` (SaveGame.java:192)
        — there is no party-level pool. This property is the derived sum.
        The setter distributes the delta the same way the torches/gems/keys
        setters do: additions land on the active member, debits are taken
        member by member.
        """
        return sum(m.gold for m in self.members)

    @gold.setter
    def gold(self, val: int) -> None:
        cur = self.gold
        diff = val - cur
        if diff > 0 and self.members:
            target = self.active_member or self.members[0]
            target.gold = getattr(target, "gold", 0) + diff
        elif diff < 0:
            need = -diff
            for m in self.members:
                g = getattr(m, "gold", 0)
                take = min(g, need)
                m.gold = g - take
                need -= take
                if need <= 0:
                    break

    @property
    def food(self) -> int:
        """Total food carried by the party.

        Java truth: food lives on each ``CharacterRecord`` (SaveGame.java:190)
        — there is no party-level pool. This property is the derived sum; the
        setter distributes the delta like the gold setter.
        """
        return sum(m.food for m in self.members)

    @food.setter
    def food(self, val: int) -> None:
        cur = self.food
        diff = val - cur
        if diff > 0 and self.members:
            target = self.active_member or self.members[0]
            target.food = getattr(target, "food", 0) + diff
        elif diff < 0:
            need = -diff
            for m in self.members:
                f = getattr(m, "food", 0)
                take = min(f, need)
                m.food = f - take
                need -= take
                if need <= 0:
                    break

    def pool_gold(self, target_index: int = 0) -> int | None:
        """Pool every member's gold into member ``target_index``, up to 9999.

        LairWare ``JoinGold`` (UltimaMain.c:1976-2006): each other member, in
        order, hands over what fits under the 9999 cap and keeps the rest. The
        old port zeroed every purse and clamped the sum, destroying anything
        past 9999 (batch ba92658 seed 213: 19,246 gold became 9,999 at
        Grey's food stall).
        """
        if target_index >= len(self.members) or target_index < 0:
            return None

        target = self.members[target_index]
        total = target.gold
        for i, m in enumerate(self.members):
            if i == target_index:
                continue
            transfer = min(m.gold, 9999 - total)
            if transfer > 0:
                total += transfer
                m.gold -= transfer
        target.gold = total
        return target.gold

    def finish_all_skips(self) -> bool:
        """LairWare FinishAll's mounted flip (UltimaMisc.c:1115-1119)::

            if (Party[1] == 0x14 || Party[1] == 0x16) {
                zp[0xCD] = 255 - zp[0xCD];
                if (zp[0xCD] < 128) return;
            }

        True when this FinishAll returns before stopped time and the
        monsters: every other turn on horseback or aboard ship, on the
        surface and in towns and castles alike."""
        if self.transport in (Transport.HORSE, Transport.SHIP):
            self.finish_all_flip = 255 - self.finish_all_flip
            return self.finish_all_flip < 128
        return False

    def end_turn(self, sosaria: bool = True) -> None:
        """One consumed turn: LairWare Routine6E35 (UltimaMisc.c:1357-1374)
        runs IncMoves, MoonGateUpdate, then AgeChars.

        ``sosaria`` is True only on the Sosaria overworld (LW ``Party[3] ==
        0``); towns, castles and Ambrosia pass False. The moons turn only on
        Sosaria (MoonGateUpdate, UltimaMisc.c:1490-1493). Stopped time
        (QUICKNESS, LW gTimeNegate) is read only by FinishAll, so it stops
        none of this (ledger T-13). Damage routes through ``apply_damage``:
        a wipe raises ``PartyDeathException`` out of here, which every
        calling screen catches.
        """
        self.moves += 1
        if sosaria:
            self.advance_moons()
        self.age_chars(sosaria=sosaria)

    def age_chars(self, sosaria: bool = True) -> None:
        """LairWare AgeChars ($7470, UltimaMisc.c:1403-1468) with EatFood
        ($761D, 1470-1488): the one place food, starving, poison, healing and
        mana tick (user rulings 2026-11-25, ledger T-16..T-20, B-01, D-01).

        Off Sosaria (``Party[3] > 0``: towns, castles, dungeons, Ambrosia and
        every combat round, where Party[3] = 0x80) it acts on every 4th call
        (``gTime[0]``, here ``age_count``). Each tick, for every member:

        - mana +1 up to the class cap (MaxMana), dead and ashes included (the
          status test comes after). Druid: +2 up to the greater half, the
          Book of Lore's "Druids regain two points per turn" (user ruling
          2026-11-25, over LW's +1 per half it is under);
        - the dead and ashes stop there. Others eat 10 of a 99-point ration
          (the port's 40 of 396, residual carried: 9.9 ticks, T-14); a member with no food left (the fraction too)
          starves for 5 HP every tick, the pool staying empty (LW zeroes all
          three food bytes);
        - poisoned: -1 HP;
        - every 10th tick (``gTime[1]``, here ``heal_count``, one party
          counter) +1 HP, capped at max HP.
        """
        if not sosaria:
            self.age_count -= 1
            if self.age_count > 0:
                return
            self.age_count = 4
        self.heal_count -= 1
        if self.heal_count < 0:
            self.heal_count = 9
        for m in reversed(self.members):  # LW: for (x = 3; x >= 0; x--)
            cap = m.max_mp
            if m.mp < cap:
                gain = 2 if m.profession == Profession.DRUID else 1
                m.mp = min(cap, m.mp + gain)
            if m.is_disabled():
                continue
            m.submorsels -= 40
            if m.submorsels < 0:
                if m.food > 0:
                    # EatFood carries the residual (UltimaMisc.c:1472-1474,
                    # `Player[34] -= 157`): 99 points a ration, 9.9 ticks.
                    m.food -= 1
                    m.submorsels += SUBMORSELS_PER_FOOD
                else:
                    # EatFood underflow past 0: STARVING!, HPSubtract 5.
                    m.submorsels = 0
                    m.apply_damage(5, False)
            if m.status == Status.POISONED:
                m.apply_damage(1, False)  # POISON!
            if self.heal_count == 0 and not m.is_disabled():
                m.hp = min(m.max_hp, m.hp + 1)

    def advance_moons(self) -> None:
        """LairWare MoonGateUpdate ($6F5D, UltimaMisc.c:1490-1506), called
        by ``end_turn`` on Sosaria only (``if (Party[3] != 0) return;``):
        Trammel turns every 12 turns and Felucca every 4. The port's
        0..23 ``moon_phase`` steps every 4th Sosaria turn (Trammel = phase
        // 3, Felucca = phase % 8), the same rates (ledger W-03). Stopped
        time does not hold the moons (T-13)."""
        self.moon_turns += 1
        if self.moon_turns % 4 == 0:
            self.moon_phase = (self.moon_phase + 1) % 24

    # --- Party Status Checks ---
    def is_anyone_alive(self) -> bool:
        """Return True if at least one member is alive.

        LairWare CheckAlive (UltimaMain.c:2895-2903): only Good or Poisoned
        members are alive, so ashes count as dead for "ALL PLAYERS OUT!"
        (CheckAllDead, UltimaMain.c:2786-2798).
        """
        return any(not m.is_disabled() for m in self.members)

    def is_party_dead(self) -> bool:
        """Return True if all party members are dead."""
        return not self.is_anyone_alive()

    def revive_all(self) -> None:
        """Revive all party members to full health and GOOD status."""
        for m in self.members:
            m.fled = False
            m.status = Status.GOOD
            m.hp = m.max_hp
        self.active_member_index = 0

    def kill_all(self) -> None:
        """Kill all party members, setting health to 0 and status to DEAD."""
        if debug.CHEATS.nohurt:
            return
        for m in self.members:
            m.fled = False
            m.status = Status.DEAD
            m.hp = 0
        self.active_member_index = 0

    def objects_on(self, game_map: Any) -> list[dict[str, Any]]:
        """``dynamic_objects`` when ``game_map`` is the surface map they were
        left on, else an empty list. See :func:`objects_on`."""
        return objects_on(self, game_map)

    def enter_surface_map(self, map_id: int) -> None:
        """Swap ``dynamic_objects`` to the surface map being loaded.

        LairWare PushSosaria/PullSosaria (UltimaMisc.c:923-968): leaving
        Sosaria for Ambrosia stashes Sosaria's objects; Ambrosia starts with
        none; returning restores Sosaria's and drops Ambrosia's (Ambrosia is
        reloaded from its resource on every visit). Other map ids (towns,
        dungeons) never come through here.
        """
        if map_id not in (0, 13) or map_id == self.objects_map_id:
            return
        if map_id == 13:
            self.sosaria_objects = self.dynamic_objects
            self.dynamic_objects = []
        else:
            self.dynamic_objects = self.sosaria_objects
            self.sosaria_objects = []
        self.objects_map_id = map_id

    # --- Serialization ---
    def to_dict(self) -> dict[str, Any]:
        """Serialize full party state to dictionary."""
        return {
            "x": self.x,
            "y": self.y,
            "map_id": self.map_id,
            "dungeon_level": self.dungeon_level,
            "transport": self.transport.value,
            "wind_direction": (
                self.wind_direction.name if self.wind_direction is not None else None
            ),
            # Q25: the stored wind names where it blows FROM (LairWare). Saves
            # without this key stored where it blew TO; from_dict turns them.
            "wind_from": True,
            "gold": self.gold,
            "food": self.food,
            "moves": self.moves,
            "age_count": self.age_count,
            "heal_count": self.heal_count,
            "moon_phase": self.moon_phase,
            "moon_turns": self.moon_turns,
            "torch_duration": self.torch_duration,
            "active_member_index": self.active_member_index,
            # exodus_cards_status is not saved (user ruling C-29, 2026-11-25):
            # Castle Exodus resets on entry like every town, as LW's lastCard
            # restarts at Love each game (UltimaMain.c:1019).
            "exodus_defeated": self.exodus_defeated,
            "members": [m.to_dict() for m in self.members],
            # LairWare PutSosaria (UltimaMisc.c:838-843) writes the whole map
            # grid, so every parked ship, horse and chest is saved: no cap.
            "dynamic_objects": list(self.dynamic_objects),
            # Java dynamic-monster cap (Context.java:176-185): keep the OLDEST
            # 8 entries at save time without mutating in-memory state.
            "dynamic_monsters": list(
                self.dynamic_monsters[: Party.DYNAMIC_MONSTERS_SAVE_CAP]
            ),
            "objects_map_id": self.objects_map_id,
            "whirlpool_return": list(self.whirlpool_return) if self.whirlpool_return else None,
            "sosaria_objects": list(self.sosaria_objects),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Party:
        """Instantiate party from dictionary."""
        # Check if party data is nested under 'party'
        p_data = data.get("party", data)

        members_raw = p_data.get("members", [])
        members: list[PartyMember] = []
        for mr in members_raw:
            char = Character.from_dict(mr)
            pm = PartyMember(
                char,
                fled=mr.get("fled", False),
                # An old save's used_free_spell_in_combat is ignored: the
                # Repond/Pontori try is a per-battle latch (A-02).
            )
            members.append(pm)

        p = cls(
            members=members,
            # Save-load fallback for party.json with no recorded x/y: Java's
            # blank-save record seeds (45, 19) (SaveGame.java:164-169). The
            # fresh-Journey default is (44, 20) per USER-DIRECTED NIT
            # (2026-11-15); this fallback stays Java-true for legacy records.
            x=p_data.get("x", 45),
            y=p_data.get("y", 19),
            map_id=p_data.get("map_id", 0),
            dungeon_level=p_data.get("dungeon_level", 0),
            transport=p_data.get("transport", Transport.FOOT),
            wind_direction=_loaded_wind(p_data),
            # Per-member model (Java CharacterRecord, SaveGame.java:190-192):
            # gold and food live on the member records. Legacy-migration below
            # handles old saves that kept a party-level wallet.
            moves=p_data.get("moves", 0),
            age_count=p_data.get("age_count", 0),
            heal_count=p_data.get("heal_count", 0),
            # Integer moon_phase/moon_turns round-trip: an old save without
            # the keys loads phase 0 — the same integer the screen-side
            # counter produced before the clock moved onto the party record.
            moon_phase=p_data.get("moon_phase", 0),
            moon_turns=p_data.get("moon_turns", 0),
            torch_duration=p_data.get("torch_duration", 0),
            active_member_index=p_data.get("active_member_index", 0),
            # An old save's exodus_cards_status is ignored and loads as 0
            # (user ruling C-29: card progress lasts one castle visit).
            exodus_defeated=p_data.get("exodus_defeated", 0),
            dynamic_objects=data.get("dynamic_objects", p_data.get("dynamic_objects", [])),
            dynamic_monsters=data.get("dynamic_monsters", p_data.get("dynamic_monsters", [])),
            objects_map_id=data.get("objects_map_id", 0),
            whirlpool_return=data.get("whirlpool_return"),
            sosaria_objects=data.get("sosaria_objects", []),
        )

        # --- Legacy-migration (pre-parity JSON saves) -------------------------
        # Old saves stored the real wallet at party level ("gold"/"food")
        # while the per-member fields stayed at their creation defaults. A
        # modern save writes the derived sums here, so *mismatch* with the
        # members' derived total is the marker of a pre-parity save. On a
        # mismatch: gather every purse into member 0 (the Java pool_gold(0)
        # idiom, Party.java:88-97) and credit the legacy value on top, so the
        # stored gold is never silently dropped.
        legacy_gold = p_data.get("gold")
        legacy_food = p_data.get("food")
        if p.members:
            if legacy_gold is not None and legacy_gold != p.gold:
                # pool_gold(0) leaves the pooled total on member 0; credit
                # the legacy value on top through the Java clamp semantics —
                # CharacterRecord.adjustGold (SaveGame.java:390-392) clamps
                # 0..9999, so an oversized legacy pool clamps instead of
                # corrupting the save.
                p.pool_gold(0)
                p.members[0].adjust_gold(legacy_gold)
            if legacy_food is not None and legacy_food != p.food:
                food_total = p.food
                for m in p.members:
                    m.food = 0
                # Java clamp semantics: food adjusts within 0..999900
                # (Utils.adjustValue(food, v, 999900, 0) — Party.java:604).
                p.members[0].food = max(0, min(999900, food_total + legacy_food))
        return p


def _loaded_wind(p_data: dict[str, Any]) -> Direction | str | None:
    """A saved wind under LairWare's naming (Q25). A save written before
    ``wind_from`` stored the way the wind blew TO, so its direction is turned
    round: the same wind, stopping the same heading, under its new name."""
    wind = p_data.get("wind_direction", Direction.NORTH)
    if wind is None or p_data.get("wind_from"):
        return wind
    try:
        d = wind if isinstance(wind, Direction) else Direction[str(wind).strip().upper()]
    except KeyError:
        return wind
    return d.reverse()


def headwind(wind: Direction | None) -> Direction | None:
    """The heading a ship cannot sail into under ``wind`` (None when calm;
    a calm ship cannot sail at all).

    LairWare names a wind where it blows FROM: WindDir 1 shows as "NORTH
    WIND" (MoreMessages 44) and ValidTrans refuses the move whose code equals
    WindDir, North() passing 1 (UltimaMain.c:3222-3236, 1203-1207). So a
    NORTH wind stops a ship sailing north (user ruling Q25; the port used to
    stop the opposite heading)."""
    return wind


def objects_on(party: Any, game_map: Any) -> list[dict[str, Any]]:
    """The party's parked ships/horses and dropped chests, only on the
    surface map they belong to (``objects_map_id``); every other map gets an
    empty list. User ruling 2026-11-22: nothing parked on one map may show
    through on another. Unscoped, a frigate left on Sosaria at (54,31) made
    Death Gulch's counter letter at (54,31) walkable. A map without an
    ``id`` (test doubles) is taken as the objects' own map."""
    if party is None:
        return []
    objs = getattr(party, "dynamic_objects", None)
    if objs is None:
        return []
    if not hasattr(game_map, "id"):
        return objs
    if str(game_map.id) != str(getattr(party, "objects_map_id", 0)):
        return []
    return objs
