"""Character entity and character creation validation for Ultima III."""
from __future__ import annotations

import random
from typing import Any

from py_exodus.constants import ArmorType, Profession, Race, Sex, Status, WeaponType


class CharacterMeta(type):
    """Metaclass allowing PartyMember wrappers to pass isinstance(obj, Character)."""

    def __instancecheck__(cls, instance: Any) -> bool:
        if type(instance).__name__ == "PartyMember":
            return True
        return super().__instancecheck__(instance)


class Character(metaclass=CharacterMeta):
    """Player character model with stats, equipment, condition, and inventory."""

    def __init__(
        self,
        name: str = "",
        sex: Sex | str = Sex.MALE,
        race: Race | str = Race.HUMAN,
        profession: Profession | str = Profession.FIGHTER,
        strength: int = 15,
        dexterity: int = 15,
        intelligence: int = 10,
        wisdom: int = 10,
        hp: int | None = None,
        max_hp: int | None = None,
        mp: int | None = None,
        max_mp: int | None = None,
        level: int = 1,
        exp: int = 0,
        status: Status | str = Status.GOOD,
        weapon: WeaponType | str = WeaponType.NONE,
        armor: ArmorType | str = ArmorType.NONE,
        cards: list[int] | None = None,
        marks: list[int] | None = None,
        keys: int = 0,
        gems: int = 0,
        torches: int = 0,
        powder: int = 0,
        food: int = 150,
        gold: int = 150,
        portrait_index: int = 43,
        **kwargs: Any,
    ) -> None:
        self.name = name

        # Sex resolution
        if isinstance(sex, Sex):
            self.sex = sex
        else:
            s = str(sex).strip().upper()
            self.sex = Sex.MALE if s.startswith("M") else Sex.FEMALE

        # Race resolution
        if isinstance(race, Race):
            self.race = race
        else:
            r = str(race).strip()
            if r.upper() in Race.__members__:
                self.race = Race[r.upper()]
            elif len(r) == 1:
                self.race = Race.from_code(r)
            else:
                self.race = Race(r.lower())

        # Profession resolution
        if isinstance(profession, Profession):
            self.profession = profession
        else:
            p = str(profession).strip().upper()
            if p in Profession.__members__:
                self.profession = Profession[p]
            else:
                self.profession = Profession(p.lower())

        # Stats resolution (allowing str/dex/int/wis in kwargs)
        str_arg = kwargs.get("str")
        dex_arg = kwargs.get("dex")
        int_arg = kwargs.get("int", kwargs.get("int_"))
        wis_arg = kwargs.get("wis")

        self._str = str_arg if str_arg is not None else strength
        self._dex = dex_arg if dex_arg is not None else dexterity
        self._int = int_arg if int_arg is not None else intelligence
        self._wis = wis_arg if wis_arg is not None else wisdom

        # Level & EXP
        self.level = level
        self.exp = exp

        # Status condition
        if isinstance(status, Status):
            self.status = status
        else:
            st = str(status).strip().upper()
            lookup = {
                "G": Status.GOOD,
                "GOOD": Status.GOOD,
                "P": Status.POISONED,
                "POISON": Status.POISONED,
                "POISONED": Status.POISONED,
                "D": Status.DEAD,
                "DEAD": Status.DEAD,
                "A": Status.ASH,
                "ASH": Status.ASH,
                "ASHES": Status.ASH,
            }
            self.status = lookup.get(st, Status.GOOD)

        # HP & Max HP
        if max_hp is not None:
            self._max_hp = max_hp
        elif hp is not None:
            self._max_hp = hp
        else:
            self._max_hp = self.level * 100 + 50

        self.hp = hp if hp is not None else self._max_hp

        # MP & Max MP
        self._max_mp = max_mp
        self.mp = mp if mp is not None else (self._max_mp if self._max_mp is not None else 0)

        # Equipment
        if isinstance(weapon, WeaponType):
            self.weapon = weapon
        else:
            w = str(weapon).strip().upper()
            self.weapon = WeaponType[w] if w in WeaponType.__members__ else WeaponType(w)

        if isinstance(armor, ArmorType):
            self.armor = armor
        else:
            a = str(armor).strip().upper()
            self.armor = ArmorType[a] if a in ArmorType.__members__ else ArmorType(a)

        self.weapons: dict[WeaponType, int] = {wt: 0 for wt in WeaponType}
        self.armors: dict[ArmorType, int] = {at: 0 for at in ArmorType}

        # Cards (Death, Sol, Moon, Love) & Marks (Kings, Fire, Force, Snake)
        self.cards = list(cards) if cards is not None else [0, 0, 0, 0]
        self.marks = list(marks) if marks is not None else [0, 0, 0, 0]

        # Consumables and items
        self.keys = keys
        self.gems = gems
        self.torches = torches
        self.powder = powder
        self.food = food
        self.gold = gold
        self.portrait_index = portrait_index

    # --- Stat properties & aliases ---
    @property
    def str(self) -> int:
        return self._str

    @str.setter
    def str(self, val: int) -> None:
        self._str = val

    @property
    def strength(self) -> int:
        return self._str

    @strength.setter
    def strength(self, val: int) -> None:
        self._str = val

    @property
    def dex(self) -> int:
        return self._dex

    @dex.setter
    def dex(self, val: int) -> None:
        self._dex = val

    @property
    def dexterity(self) -> int:
        return self._dex

    @dexterity.setter
    def dexterity(self, val: int) -> None:
        self._dex = val

    @property
    def int(self) -> int:
        return self._int

    @int.setter
    def int(self, val: int) -> None:
        self._int = val

    @property
    def intelligence(self) -> int:
        return self._int

    @intelligence.setter
    def intelligence(self, val: int) -> None:
        self._int = val

    @property
    def wis(self) -> int:
        return self._wis

    @wis.setter
    def wis(self, val: int) -> None:
        self._wis = val

    @property
    def wisdom(self) -> int:
        return self._wis

    @wisdom.setter
    def wisdom(self, val: int) -> None:
        self._wis = val

    # --- Health & Mana properties ---
    @property
    def max_hp(self) -> int:
        return self._max_hp

    @max_hp.setter
    def max_hp(self, val: int) -> None:
        self._max_hp = val

    @property
    def health(self) -> int:
        return self.hp

    @health.setter
    def health(self, val: int) -> None:
        self.hp = val

    @property
    def max_health(self) -> int:
        return self.max_hp

    @max_health.setter
    def max_health(self, val: int) -> None:
        self.max_hp = val

    @property
    def max_mp(self) -> int:
        if self._max_mp is not None:
            return self._max_mp
        return self.compute_max_mp()

    @max_mp.setter
    def max_mp(self, val: int | None) -> None:
        self._max_mp = val

    @property
    def mana(self) -> int:
        return self.mp

    @mana.setter
    def mana(self, val: int) -> None:
        self.mp = val

    @property
    def max_mana(self) -> int:
        return self.max_mp

    @max_mana.setter
    def max_mana(self, val: int | None) -> None:
        self.max_mp = val

    def compute_max_mp(self) -> int:
        """Calculate maximum MP based on profession and casting attributes."""
        prof = self.profession
        if prof in (Profession.BARBARIAN, Profession.FIGHTER, Profession.THIEF):
            return 0
        if prof == Profession.WIZARD:
            return self.intelligence
        if prof == Profession.CLERIC:
            return self.wisdom
        if prof in (Profession.ALCHEMIST, Profession.LARK):
            return self.intelligence // 2
        if prof in (Profession.PALADIN, Profession.ILLUSIONIST):
            return self.wisdom // 2
        if prof == Profession.DRUID:
            return max(self.intelligence // 2, self.wisdom // 2)
        if prof == Profession.RANGER:
            return min(self.intelligence // 2, self.wisdom // 2)
        return 0

    # --- Status condition queries ---
    def is_dead(self) -> bool:
        """Return True if character is dead."""
        return self.status == Status.DEAD

    def is_disabled(self) -> bool:
        """Return True if character cannot act (dead or ashes)."""
        return self.status in (Status.DEAD, Status.ASHES)

    # --- Progression & Lord British ---
    def meet_lord_british(self) -> bool:
        """Advance character level when visiting Lord British with sufficient EXP."""
        if self.level >= 25:
            return False

        eligible_level = self.exp // 100 + 1
        if eligible_level <= self.level:
            return False

        # Mark of Kings is required to advance past level 4 (to level 5+)
        if eligible_level >= 5 and (not self.marks or self.marks[0] == 0):
            return False

        levels_gained = eligible_level - self.level
        self.level = eligible_level
        self.status = Status.GOOD
        self.max_hp = self.level * 100 + 50
        self.hp = self.max_hp

        # Stat gains per level gained (up to race caps)
        for _ in range(levels_gained):
            self.str = min(self.str + random.randint(1, 8), self.race.max_str)
            self.dex = min(self.dex + random.randint(1, 8), self.race.max_dex)
            self.int = min(self.int + random.randint(1, 8), self.race.max_int)
            self.wis = min(self.wis + random.randint(1, 8), self.race.max_wis)

        return True

    # --- Character Creation Validation ---
    @classmethod
    def validate_creation(
        cls,
        race: Race | str,
        profession: Profession | str,
        strength: int,
        dexterity: int,
        intelligence: int,
        wisdom: int,
        max_points: int = 50,
        min_stat: int = 5,
        max_stat: int = 25,
    ) -> tuple[bool, str]:
        """Validate attribute allocations according to Ultima III character creation rules."""
        if isinstance(race, str):
            race = Race[race.upper()] if race.upper() in Race.__members__ else Race(race.lower())
        if isinstance(profession, str):
            prof_str = profession.strip().upper()
            profession = (
                Profession[prof_str]
                if prof_str in Profession.__members__
                else Profession(prof_str.lower())
            )

        total_points = strength + dexterity + intelligence + wisdom
        if total_points > max_points:
            return (
                False,
                f"Total allocated points ({total_points}) exceed maximum allowable ({max_points}).",
            )

        stats = [
            ("Strength", strength, race.max_str),
            ("Dexterity", dexterity, race.max_dex),
            ("Intelligence", intelligence, race.max_int),
            ("Wisdom", wisdom, race.max_wis),
        ]

        for name, val, cap in stats:
            if val < min_stat:
                return False, f"{name} ({val}) is below minimum allowable ({min_stat})."
            if val > max_stat:
                return False, f"{name} ({val}) exceeds character creation maximum ({max_stat})."
            if val > cap:
                return (
                    False,
                    f"{name} ({val}) exceeds racial maximum cap for {race.name} ({cap}).",
                )

        return True, ""

    @classmethod
    def create(
        cls,
        name: str,
        sex: Sex | str = Sex.MALE,
        race: Race | str = Race.HUMAN,
        profession: Profession | str = Profession.FIGHTER,
        strength: int = 15,
        dexterity: int = 15,
        intelligence: int = 10,
        wisdom: int = 10,
        validate: bool = True,
    ) -> Character:
        """Factory helper creating and optionally validating a character."""
        if validate:
            valid, err = cls.validate_creation(
                race=race,
                profession=profession,
                strength=strength,
                dexterity=dexterity,
                intelligence=intelligence,
                wisdom=wisdom,
            )
            if not valid:
                raise ValueError(f"Invalid character attributes: {err}")

        return cls(
            name=name,
            sex=sex,
            race=race,
            profession=profession,
            strength=strength,
            dexterity=dexterity,
            intelligence=intelligence,
            wisdom=wisdom,
        )

    # --- Serialization ---
    def to_dict(self) -> dict[str, Any]:
        """Serialize character state to dictionary."""
        return {
            "name": self.name,
            "sex": self.sex.value if isinstance(self.sex, Sex) else str(self.sex),
            "race": self.race.value if isinstance(self.race, Race) else str(self.race),
            "profession": (
                self.profession.value
                if isinstance(self.profession, Profession)
                else str(self.profession)
            ),
            "status": (
                self.status.value if isinstance(self.status, Status) else str(self.status)
            ),
            "hp": self.hp,
            "max_hp": self.max_hp,
            "mp": self.mp,
            "max_mp": self.max_mp,
            "level": self.level,
            "exp": self.exp,
            "str": self.str,
            "dex": self.dex,
            "int": self.int,
            "wis": self.wis,
            "weapon": (
                self.weapon.value
                if isinstance(self.weapon, WeaponType)
                else str(self.weapon)
            ),
            "armor": (
                self.armor.value
                if isinstance(self.armor, ArmorType)
                else str(self.armor)
            ),
            "cards": list(self.cards),
            "marks": list(self.marks),
            "keys": self.keys,
            "gems": self.gems,
            "torches": self.torches,
            "powder": self.powder,
            "food": self.food,
            "gold": self.gold,
            "portrait_index": self.portrait_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Character:
        """Instantiate character from serialized dictionary."""
        return cls(
            name=data.get("name", ""),
            sex=data.get("sex", Sex.MALE),
            race=data.get("race", Race.HUMAN),
            profession=data.get("profession", Profession.FIGHTER),
            strength=data.get("str", data.get("strength", 15)),
            dexterity=data.get("dex", data.get("dexterity", 15)),
            intelligence=data.get("int", data.get("intelligence", 10)),
            wisdom=data.get("wis", data.get("wisdom", 10)),
            hp=data.get("hp"),
            max_hp=data.get("max_hp"),
            mp=data.get("mp"),
            max_mp=data.get("max_mp"),
            level=data.get("level", 1),
            exp=data.get("exp", 0),
            status=data.get("status", Status.GOOD),
            weapon=data.get("weapon", WeaponType.NONE),
            armor=data.get("armor", ArmorType.NONE),
            cards=data.get("cards", [0, 0, 0, 0]),
            marks=data.get("marks", [0, 0, 0, 0]),
            keys=data.get("keys", 0),
            gems=data.get("gems", 0),
            torches=data.get("torches", 0),
            powder=data.get("powder", 0),
            food=data.get("food", 150),
            gold=data.get("gold", 150),
            portrait_index=data.get("portrait_index", 43),
        )

    def __repr__(self) -> str:
        race_name = self.race.name if isinstance(self.race, Race) else str(self.race)
        prof_name = (
            self.profession.name if isinstance(self.profession, Profession) else str(self.profession)
        )
        status_val = self.status.value if isinstance(self.status, Status) else str(self.status)
        return (
            f"Character({self.name!r}, {race_name}, {prof_name}, "
            f"Lvl:{self.level}, HP:{self.hp}/{self.max_hp}, MP:{self.mp}/{self.max_mp}, "
            f"Status:{status_val})"
        )
