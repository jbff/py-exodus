#!/usr/bin/env python3
"""Reset saves/party.json and restore the optimal Level 1 starter roster."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from py_exodus.autoplay.batch import PARTY_SETUP
from py_exodus.constants import Profession, Race, Sex
from py_exodus.entities.character import Character
from py_exodus.save_system import SaveSystem


def reset_new_game(saves_dir: Path | None = None) -> None:
    """Remove saves/party.json and write a fresh optimal 4-member roster."""
    target_dir = saves_dir or (ROOT / "saves")
    target_dir.mkdir(parents=True, exist_ok=True)

    party_file = target_dir / "party.json"
    if party_file.exists():
        party_file.unlink()
        print(f"Removed {party_file}")
    else:
        print(f"No existing {party_file} to remove")

    roster = [
        Character(
            name, Sex.MALE if sex == "M" else Sex.FEMALE, Race[race], Profession[prof],
            strength=st, dexterity=dx, intelligence=it, wisdom=ws,
        )
        for name, sex, race, prof, st, dx, it, ws in PARTY_SETUP
    ]
    roster_file = target_dir / "roster.json"
    SaveSystem.save_roster(roster, roster_file)
    print(f"Restored optimal L1 roster to {roster_file}:")
    for i, c in enumerate(roster, start=1):
        print(
            f"  {i}. {c.name} ({c.race.value} {c.profession.value}) "
            f"L{c.level} HP={c.hp}/{c.max_hp} MP={c.mp} gold={c.gold} food={c.food}"
        )


if __name__ == "__main__":
    reset_new_game()
