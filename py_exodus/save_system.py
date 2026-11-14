"""JSON save system for Ultima III party, roster, and overworld state.

Save integrity envelope (Task 27 / D2):

    USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): save integrity envelope
    (GBC SRAM checksum pattern; ult3.c:1743-1757, menucmd2.c:1137-1139).

Every party or roster save this module writes is a
``{"magic": "U3PY", "checksum": int, "payload": ...}`` document, where
``payload`` is the party dict (or roster list) exactly as the older bare
format produced, and ``checksum`` is
``zlib.crc32(json.dumps(payload, sort_keys=True, indent=None).encode())``.
Loads accept BOTH formats: a document carrying the magic is verified and
raises :class:`SaveChecksumError` (message includes the file path) on a
checksum mismatch; any other document loads exactly as before, so legacy
saves written before the envelope keep loading unchanged.

The checksum is computed at SAVE time only. The GBC original recomputes it
at every state mutation because its battery-backed SRAM is mutable in place
between saves (menucmd2.c:1137-1139 re-verifies on load against a value
ult3.c:1743-1757 keeps current through play); Python's JSON saves are
written as a whole file in one operation, so nothing mutates an enveloped
save behind the checksum's back between writes — verifying at load time
against the save-time value is sufficient (ledger ruling).
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any

from py_exodus.constants import (
    ArmorType,
    Profession,
    Race,
    Sex,
    Status,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party

SAVE_MAGIC = "U3PY"


class SaveChecksumError(Exception):
    """Raised when an enveloped save file's checksum does not match its payload.

    The message includes the save file's path."""


def _save_checksum(payload: Any) -> int:
    """CRC32 over the canonical JSON encoding of ``payload``."""
    return zlib.crc32(json.dumps(payload, sort_keys=True, indent=None).encode())


def _wrap_save(payload: Any) -> dict[str, Any]:
    """Envelope ``payload`` (party dict or roster list) for writing."""
    return {"magic": SAVE_MAGIC, "checksum": _save_checksum(payload), "payload": payload}


def _unwrap_save(raw: Any, path: str | Path) -> Any:
    """Return the payload of an enveloped save, or ``raw`` itself for legacy saves.

    A document with the U3PY magic is a checksummed envelope: verify and
    return ``raw["payload"]``, raising :class:`SaveChecksumError` (with the
    path in the message) on a mismatch or a malformed envelope. Anything
    else is a legacy (pre-envelope) record and loads exactly as before.
    """
    if isinstance(raw, dict) and raw.get("magic") == SAVE_MAGIC:
        if "payload" not in raw:
            raise SaveChecksumError(f"Malformed enveloped save (no payload): {path}")
        expected = _save_checksum(raw["payload"])
        if raw.get("checksum") != expected:
            raise SaveChecksumError(
                f"Save checksum mismatch in {path}: "
                f"stored {raw.get('checksum')!r}, computed {expected}"
            )
        return raw["payload"]
    return raw


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
            json.dump(_wrap_save(data), f, indent=2)

    @classmethod
    def load_game(cls, path: str | Path) -> Party:
        """Load party from JSON save file.

        Accepts the enveloped (verified) format and the legacy bare party
        dict; see the module docstring for the envelope contract.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Save file not found: {path}")

        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)

        return Party.from_dict(_unwrap_save(raw, p))

    @classmethod
    def load_game_data(cls, path: str | Path) -> dict[str, Any]:
        """Load the save record: the party dict plus any screen-side
        ``extra`` context (DungeonScreen's dungeon block, OverworldScreen's
        ``overworld`` block). The integrity envelope (see module docstring),
        when present, is unwrapped: the returned dict is the payload —
        i.e. the same document legacy saves stored bare. Callers that need
        the extras (Journey Onward's world-state restore) build the party
        themselves via ``Party.from_dict``.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Save file not found: {path}")

        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)

        data = _unwrap_save(raw, p)
        if not isinstance(data, dict):
            raise SaveChecksumError(f"Party save is not a record: {path}")
        return data

    @classmethod
    def save_roster(cls, roster: list[Character], path: str | Path) -> None:
        """Save a list of roster characters to JSON (enveloped; see module docstring)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [char.to_dict() for char in roster]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_wrap_save(data), f, indent=2)

    @classmethod
    def load_roster(cls, path: str | Path) -> list[Character]:
        """Load a character roster from a JSON array of character records.

        Accepts the enveloped (verified) format and the legacy bare array;
        see the module docstring for the envelope contract.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Roster file not found: {path}")

        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)

        data = _unwrap_save(raw, p)
        if not isinstance(data, list):
            raise SaveChecksumError(f"Roster save is not a list of characters: {path}")
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
        # Marks, high nibble: Kings=0x80, Fire=0x20, Snake=0x40, Force=0x10.
        # Java stores marks as a 4-array indexed [0]=KINGS, [1]=FIRE,
        # [2]=SNAKE, [3]=FORCE (Party.java:703-706; SaveGame.java:218-221
        # writes them in that order) — mirror that order here.
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
            1 if (b_cm & 0x40) else 0,
            1 if (b_cm & 0x10) else 0,
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

        # 0x18: Sex. "O" -> OTHER is the user-directed original-rules deviation
        # (constants.Sex documents it); unknown bytes keep the historic
        # MALE/FEMALE fallback, and the new value must not break the binary
        # decode path.
        b_sex = data[0x18]
        if b_sex == ord("F") or b_sex == 1:
            sex = Sex.FEMALE
        elif b_sex == ord("O"):
            sex = Sex.OTHER
        else:
            sex = Sex.MALE

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
