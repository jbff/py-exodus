"""JSON and binary save system for Ultima III party, roster, and overworld state."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from py_exodus.constants import (
    ArmorType,
    Profession,
    Race,
    Sex,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party


class SaveSystem:
    """Manages serialization of party, character roster, and dynamic overworld deltas."""

    @classmethod
    def save_game(
        cls,
        party: Party,
        path: str | Path,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Save active party state and dynamic overworld delta to human-readable JSON.

        ``extra`` carries screen-side location context Java's
        ``Context.saveGame`` stores alongside the party record — for a
        dungeon save, DungeonScreen passes the dungeon x/y/level/dir and map
        id (DungeonScreen.java:983-986). Unknown keys are ignored by
        ``Party.from_dict``.
        """
        data = party.to_dict()
        if extra:
            data.update(extra)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load_game(cls, path: str | Path) -> Party:
        """Load party from JSON save file (or binary .ult file if specified)."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Save file not found: {path}")

        if p.suffix.lower() == ".ult":
            return cls.load_binary_party(p)

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        return Party.from_dict(data)

    @classmethod
    def save_roster(cls, roster: list[Character], path: str | Path) -> None:
        """Save a list of roster characters to JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [char.to_dict() for char in roster]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load_roster(cls, path: str | Path) -> list[Character]:
        """Load a character roster from JSON or binary roster.ult file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Roster file not found: {path}")

        if p.suffix.lower() in (".ult", ".sav"):
            return cls.load_binary_roster(p)

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        return [Character.from_dict(cd) for cd in data]

    @classmethod
    def parse_binary_character_record(cls, data: bytes) -> Character | None:
        """Parse a 64-byte Ultima III character binary record into a Character."""
        if len(data) < 64:
            return None

        # 0x00..0x09: Name (up to 10 bytes null-padded ASCII)
        raw_name = data[0:10].split(b"\x00")[0]
        name = raw_name.decode("ascii", errors="replace").strip()

        # If name is completely empty and remaining bytes are zeros, return empty character
        is_empty = not name and all(b == 0 for b in data)
        if is_empty:
            return Character(name="")

        # 0x0E: Cards and Marks bitmask
        # Cards: Love=0x01, Sol=0x02, Moon=0x04, Death=0x08
        # Marks: Kings=0x80, Fire=0x20, Force=0x10, Snake=0x40
        b_cm = data[0x0E]
        cards = [
            1 if (b_cm & 0x01) else 0,
            1 if (b_cm & 0x02) else 0,
            1 if (b_cm & 0x04) else 0,
            1 if (b_cm & 0x08) else 0,
        ]
        marks = [
            1 if (b_cm & 0x80) else 0,
            1 if (b_cm & 0x20) else 0,
            1 if (b_cm & 0x10) else 0,
            1 if (b_cm & 0x40) else 0,
        ]

        # 0x0F: Torches
        torches = data[0x0F]

        # 0x11: Status
        b_st = data[0x11]
        status_map = {
            ord("G"): Status.GOOD,
            ord("P"): Status.POISONED,
            ord("D"): Status.DEAD,
            ord("A"): Status.ASH,
            0: Status.GOOD,
            1: Status.POISONED,
            2: Status.DEAD,
            3: Status.ASH,
        }
        status = status_map.get(b_st, Status.GOOD)

        # 0x12..0x15: STR, DEX, INT, WIS
        str_val = data[0x12]
        dex_val = data[0x13]
        int_val = data[0x14]
        wis_val = data[0x15]

        # 0x16: Race
        b_race = data[0x16]
        race_map = {
            ord("H"): Race.HUMAN,
            ord("E"): Race.ELF,
            ord("D"): Race.DWARF,
            ord("B"): Race.BOBIT,
            ord("F"): Race.FUZZY,
            0: Race.HUMAN,
            1: Race.ELF,
            2: Race.DWARF,
            3: Race.BOBIT,
            4: Race.FUZZY,
        }
        race = race_map.get(b_race, Race.HUMAN)

        # 0x17: Profession
        b_prof = data[0x17]
        prof_map = {
            ord("F"): Profession.FIGHTER,
            ord("C"): Profession.CLERIC,
            ord("W"): Profession.WIZARD,
            ord("T"): Profession.THIEF,
            ord("P"): Profession.PALADIN,
            ord("B"): Profession.BARBARIAN,
            ord("L"): Profession.LARK,
            ord("I"): Profession.ILLUSIONIST,
            ord("D"): Profession.DRUID,
            ord("A"): Profession.ALCHEMIST,
            ord("R"): Profession.RANGER,
            0: Profession.BARBARIAN,
            1: Profession.DRUID,
            2: Profession.ALCHEMIST,
            3: Profession.RANGER,
            4: Profession.FIGHTER,
            5: Profession.WIZARD,
            6: Profession.THIEF,
            7: Profession.LARK,
            8: Profession.ILLUSIONIST,
            9: Profession.CLERIC,
            10: Profession.PALADIN,
        }
        profession = prof_map.get(b_prof, Profession.FIGHTER)

        # 0x18: Sex
        b_sex = data[0x18]
        sex = Sex.FEMALE if (b_sex == ord("F") or b_sex == 1) else Sex.MALE

        # 0x19..0x24: 16-bit numeric fields
        mp = struct.unpack_from("<H", data, 0x19)[0] if len(data) >= 0x1B else 0
        hp = struct.unpack_from("<H", data, 0x1B)[0] if len(data) >= 0x1D else 150
        max_hp = struct.unpack_from("<H", data, 0x1D)[0] if len(data) >= 0x1F else hp
        exp = struct.unpack_from("<H", data, 0x1F)[0] if len(data) >= 0x21 else 0
        food = struct.unpack_from("<H", data, 0x21)[0] if len(data) >= 0x23 else 150
        gold = struct.unpack_from("<H", data, 0x23)[0] if len(data) >= 0x25 else 150

        # Items
        gems = data[0x25] if len(data) > 0x25 else 0
        keys = data[0x26] if len(data) > 0x26 else 0
        powder = data[0x27] if len(data) > 0x27 else 0

        # Equipment
        eq_armor = data[0x28] if len(data) > 0x28 else 0
        eq_weapon = data[0x29] if len(data) > 0x29 else 0
        armor_list = list(ArmorType)
        weapon_list = list(WeaponType)
        armor = armor_list[eq_armor] if eq_armor < len(armor_list) else ArmorType.NONE
        weapon = weapon_list[eq_weapon] if eq_weapon < len(weapon_list) else WeaponType.NONE

        return Character(
            name=name,
            sex=sex,
            race=race,
            profession=profession,
            strength=str_val if str_val > 0 else 15,
            dexterity=dex_val if dex_val > 0 else 15,
            intelligence=int_val if int_val > 0 else 10,
            wisdom=wis_val if wis_val > 0 else 10,
            hp=hp if hp > 0 else 150,
            max_hp=max_hp if max_hp > 0 else 150,
            mp=mp,
            exp=exp,
            status=status,
            weapon=weapon,
            armor=armor,
            cards=cards,
            marks=marks,
            keys=keys,
            gems=gems,
            torches=torches,
            powder=powder,
            food=food,
            gold=gold,
        )

    @classmethod
    def load_binary_party(cls, path: str | Path) -> Party:
        """Load party from 274-byte binary party.ult."""
        with open(path, "rb") as f:
            data = f.read()

        p = Party()
        if len(data) >= 18:
            transport_code = data[0]
            lookup_t = {0: Transport.FOOT, 1: Transport.HORSE, 2: Transport.SHIP}
            p.transport = lookup_t.get(transport_code, Transport.FOOT)
            p.map_id = data[1]
            p.moves = struct.unpack_from("<I", data, 2)[0] if len(data) >= 6 else 0
            p.x = data[7] if data[7] != 0 or data[8] != 0 else 45
            p.y = data[8] if data[7] != 0 or data[8] != 0 else 18
            p.dungeon_level = data[9]
            # Ship hull
            if len(data) > 11 and data[11] > 0:
                p.ship_hull = data[11]

        # Parse up to 4 characters (64 bytes each starting at offset 18)
        offset = 18
        for _ in range(4):
            if offset + 64 <= len(data):
                char = cls.parse_binary_character_record(data[offset : offset + 64])
                if char is not None and char.name:
                    p.add_member(char)
                offset += 64

        return p

    @classmethod
    def load_binary_roster(cls, path: str | Path) -> list[Character]:
        """Load up to 20 characters from 1280-byte binary roster.ult."""
        with open(path, "rb") as f:
            data = f.read()

        roster: list[Character] = []
        offset = 0
        for _ in range(20):
            if offset + 64 <= len(data):
                char = cls.parse_binary_character_record(data[offset : offset + 64])
                if char is not None:
                    roster.append(char)
                offset += 64

        return roster
