"""Party management, party members, and active game exploration state."""
from __future__ import annotations

from typing import Any

from py_exodus.constants import (
    MAX_PARTY_MEMBERS,
    Direction,
    Status,
    Transport,
)
from py_exodus.entities.character import Character


class PartyMember:
    """Character joined into an active adventuring Party with combat and turn state."""

    def __init__(
        self,
        *args: Any,
        party: Party | None = None,
        fled: bool = False,
        combat_map_exit_direction: Direction | None = None,
        used_free_spell_in_combat: bool = False,
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
        object.__setattr__(self, "used_free_spell_in_combat", used_free_spell_in_combat)

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
            "used_free_spell_in_combat",
        ):
            object.__setattr__(self, name, value)
        else:
            setattr(self.character, name, value)

    @classmethod
    def from_character(cls, char: Character, party: Party | None = None) -> PartyMember:
        """Promote an existing Character into a PartyMember."""
        return cls(char, party=party)

    def to_dict(self) -> dict[str, Any]:
        """Serialize party member state."""
        d = self.character.to_dict()
        d["fled"] = self.fled
        d["used_free_spell_in_combat"] = self.used_free_spell_in_combat
        return d

    def __repr__(self) -> str:
        return f"PartyMember({self.character!r}, fled={self.fled})"


class Party:
    """Active player party (1-4 members) with coordinates, transport, and pooled resources."""

    def __init__(
        self,
        members: list[Character | PartyMember] | None = None,
        x: int = 45,
        y: int = 18,
        map_id: int = 0,
        dungeon_level: int = 0,
        transport: Transport | str = Transport.FOOT,
        ship_hull: int = 50,
        wind_direction: Direction | str = Direction.NORTH,
        gold: int = 0,
        food: int = 0,
        moves: int = 0,
        torch_duration: int = 0,
        active_member_index: int = 0,
        dynamic_objects: list[dict[str, int]] | None = None,
        dynamic_monsters: list[dict[str, int]] | None = None,
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

        self.ship_hull = max(0, min(50, ship_hull))

        # Wind direction resolution
        if isinstance(wind_direction, Direction):
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

        self.gold = gold
        self.food = food
        self.moves = moves
        self.torch_duration = torch_duration
        self.active_member_index = active_member_index

        # Dynamic overworld delta: up to 24 mutable objects on Sosaria (e.g. docked ships, horses, chests)
        self.dynamic_objects: list[dict[str, int]] = (
            list(dynamic_objects) if dynamic_objects is not None else []
        )
        # Dynamic monsters delta: up to 8 active monsters on Sosaria
        self.dynamic_monsters: list[dict[str, int]] = (
            list(dynamic_monsters) if dynamic_monsters is not None else []
        )

    # --- Aliases & Properties ---
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
    def shiphull(self) -> int:
        """Alias for ship_hull."""
        return self.ship_hull

    @shiphull.setter
    def shiphull(self, val: int) -> None:
        self.ship_hull = max(0, min(50, val))

    @property
    def torchduration(self) -> int:
        """Alias for torch_duration."""
        return self.torch_duration

    @torchduration.setter
    def torchduration(self, val: int) -> None:
        self.torch_duration = val

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
    def pool_gold(self, target_index: int | None = None) -> int:
        """Pool all individual members' gold into party gold or a specific member."""
        total_member_gold = sum(m.gold for m in self.members)
        for m in self.members:
            m.gold = 0

        if target_index is None:
            self.gold += total_member_gold
            return self.gold
        else:
            if 0 <= target_index < len(self.members):
                total = self.gold + total_member_gold
                self.members[target_index].gold = total
                self.gold = 0
                return total
            self.gold += total_member_gold
            return self.gold

    def consume_food(self, amount: int | None = None) -> int:
        """Consume food for active members per turn; apply starvation damage if depleted."""
        if amount is None:
            living_members = [m for m in self.members if not m.is_dead()]
            req = len(living_members)
        else:
            req = amount

        if self.food >= req:
            self.food -= req
        else:
            self.food = 0
            # Apply starvation damage (2 HP) to all living members
            for m in self.members:
                if not m.is_dead():
                    m.hp = max(0, m.hp - 2)
                    if m.hp == 0:
                        m.status = Status.DEAD

        return self.food

    def adjust_ship_hull(self, val: int) -> int:
        """Adjust ship hull health between 0 and 50."""
        self.ship_hull = max(0, min(50, self.ship_hull + val))
        return self.ship_hull

    # --- Party Status Checks ---
    def is_anyone_alive(self) -> bool:
        """Return True if at least one member is alive."""
        return any(not m.is_dead() for m in self.members)

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
        for m in self.members:
            m.fled = False
            m.status = Status.DEAD
            m.hp = 0
        self.active_member_index = 0

    # --- Serialization ---
    def to_dict(self) -> dict[str, Any]:
        """Serialize full party state to dictionary."""
        return {
            "x": self.x,
            "y": self.y,
            "map_id": self.map_id,
            "dungeon_level": self.dungeon_level,
            "transport": self.transport.value,
            "ship_hull": self.ship_hull,
            "wind_direction": self.wind_direction.name,
            "gold": self.gold,
            "food": self.food,
            "moves": self.moves,
            "torch_duration": self.torch_duration,
            "active_member_index": self.active_member_index,
            "members": [m.to_dict() for m in self.members],
            "dynamic_objects": list(self.dynamic_objects),
            "dynamic_monsters": list(self.dynamic_monsters),
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
                used_free_spell_in_combat=mr.get("used_free_spell_in_combat", False),
            )
            members.append(pm)

        p = cls(
            members=members,
            x=p_data.get("x", 45),
            y=p_data.get("y", 18),
            map_id=p_data.get("map_id", 0),
            dungeon_level=p_data.get("dungeon_level", 0),
            transport=p_data.get("transport", Transport.FOOT),
            ship_hull=p_data.get("ship_hull", 50),
            wind_direction=p_data.get("wind_direction", Direction.NORTH),
            gold=p_data.get("gold", 0),
            food=p_data.get("food", 0),
            moves=p_data.get("moves", 0),
            torch_duration=p_data.get("torch_duration", 0),
            active_member_index=p_data.get("active_member_index", 0),
            dynamic_objects=data.get("dynamic_objects", p_data.get("dynamic_objects", [])),
            dynamic_monsters=data.get("dynamic_monsters", p_data.get("dynamic_monsters", [])),
        )
        return p
