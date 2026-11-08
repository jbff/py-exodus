"""Tests for the shared chest pipeline (gold, traps, direction targeting) and dungeon Get (G)."""
import random
import re

import pygame
import pytest

from py_exodus.constants import Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.screens.dungeon_screen import DungeonScreen
from py_exodus.world import chests
from py_exodus.world.chests import ChestNotFound, open_chest
from py_exodus.world.map import DungeonMap, DungeonTile


class ScriptedRNG:
    """Deterministic stand-in for the random-module calls chests.open_chest makes.

    Rolls are consumed in order by randrange(n); an empty script yields 0.
    """

    def __init__(self, rolls: list[int]) -> None:
        self.rolls: list[int] = list(rolls)

    def randrange(self, n: int) -> int:
        value = self.rolls.pop(0) if self.rolls else 0
        assert 0 <= value < n, f"scripted roll {value} out of range for randrange({n})"
        return value

    def random(self) -> float:
        return 0.5


def make_member(name: str, **kwargs) -> PartyMember:
    defaults = {"hp": 100, "max_hp": 100, "gold": 150}
    defaults.update(kwargs)
    return PartyMember(
        Character(name, "M", Race.HUMAN, Profession.FIGHTER, **defaults)
    )


def make_party(members: list[PartyMember], gold: int | None = None, food: int | None = None) -> Party:
    """Per-member model (Task 4): gold and food live on each member's own
    record — there is no party pool. The optional gold/food arguments are
    split evenly across the members' purses."""
    party = Party(members, transport=Transport.FOOT)
    n = len(party.members)
    if n and gold is not None:
        share, rem = divmod(gold, n)
        for i, m in enumerate(party.members):
            m.gold = share + (1 if i < rem else 0)
    if n and food is not None:
        share, rem = divmod(food, n)
        for i, m in enumerate(party.members):
            m.food = share + (1 if i < rem else 0)
    return party


# --- Step 1: pipeline gold behavior ---

def test_chest_gold_credits_member_not_party_pool(monkeypatch):
    """Chest gold goes to member.gold within 10-66; other members are untouched
    and the party total rises only by the chest amount (per-member model)."""
    member = make_member("Fighter", dexterity=15)
    other = make_member("Cleric", dexterity=15)
    party = make_party([member, other], gold=500)

    # No trap (roll 1), then gold rolls: 25 of 50 + 6 of 8 + 10 = 41
    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 25, 6]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold"]
    assert member.gold == 250 + 41
    assert other.gold == 250
    assert party.gold == 500 + 41


def test_chest_gold_value_range_10_to_66(monkeypatch):
    """Over many seeded chests, credited gold is always 10-66 and member-only."""
    member = make_member("Fighter", dexterity=200)
    other = make_member("Cleric")
    party = make_party([member, other], gold=500)
    monkeypatch.setattr(chests, "random", random.Random(7))

    for _ in range(100):
        before = member.gold
        lines = open_chest(party, member, dungeon=False)
        delta = member.gold - before
        assert 10 <= delta <= 66
        assert lines[-1] == f"The Chest Holds: {delta} Gold"
        assert member.gold <= 9999
        assert other.gold == 250  # non-opening members are never credited


def test_chest_gold_caps_at_9999(monkeypatch):
    """A member's gold caps at 9999 on chest credit (Java adjustGold)."""
    member = make_member("Fighter", gold=9990, dexterity=200)
    party = make_party([member], gold=9990)
    monkeypatch.setattr(chests, "random", random.Random(3))

    open_chest(party, member, dungeon=False)
    assert member.gold == 9999


# --- Step 1: pipeline trap behavior ---

def test_high_dex_always_evades_traps(monkeypatch):
    """dex + 25 >= rand(100) always holds for dex=200: traps never harm the opener."""
    member = make_member("Fighter", dexterity=200)
    party = make_party([member])
    monkeypatch.setattr(chests, "random", random.Random(2024))

    before_gold = member.gold
    for _ in range(60):
        open_chest(party, member, dungeon=False)
        assert member.hp == 100
        assert member.status == Status.GOOD
    assert member.gold > before_gold


def test_acid_trap_damages_opener(monkeypatch):
    """A failed evade on the Acid trap applies the FIRE effect to that member."""
    member = make_member("Fighter")  # dex 15, no marks
    other = make_member("Cleric")
    party = make_party([member, other])

    # Trap present, evade roll 99 (hit for dex 15), acid, damage roll 5 -> 21, gold
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 0, 5, 25, 6]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Acid Trap!", "The Chest Holds: 41 Gold"]
    assert member.hp == 100 - 21
    assert member.status == Status.GOOD
    assert other.hp == 100  # acid hits only the opening member


def test_acid_trap_with_mark_of_fire_is_a_no_op(monkeypatch):
    """Mark of Fire immunity: the acid trap logs but deals no damage (no damage roll)."""
    member = make_member("Fighter", dexterity=0, marks=[0, 1, 0, 0])
    party = make_party([make_member("Cleric"), member])

    # Trap present, hit, acid; NO damage roll is consumed, then gold rolls
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 0, 25, 6]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Acid Trap!", "The Chest Holds: 41 Gold"]
    assert member.hp == 100
    assert member.status == Status.GOOD
    assert member.gold == 150 + 41


def test_gas_trap_applies_lava_effect_to_party(monkeypatch):
    """Gas trap applies the LAVA effect through party.applyEffect (every living member)."""
    member = make_member("Fighter")
    other = make_member("Cleric")
    marked = make_member("Druid", marks=[0, 1, 0, 0])
    party = make_party([member, other, marked])

    # Trap, hit, gas; per-member LAVA damage rolls for the two unmarked members, then gold
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 3, 2, 4, 25, 6]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Gas Trap!", "The Chest Holds: 41 Gold"]
    assert member.hp == 100 - 18
    assert other.hp == 100 - 20
    assert marked.hp == 100  # Mark of Fire absorbs the LAVA effect


def test_poison_trap_poisons_opener(monkeypatch):
    """A poison trap sets the POISONED status on the opening member without damaging them."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 2, 25, 6]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Poison Trap!", "The Chest Holds: 41 Gold"]
    assert member.status == Status.POISONED
    assert member.hp == 100


def test_disarmed_chest_yields_gold_and_no_trap_roll(monkeypatch):
    """A disarmed (APPAR_UNEM) chest credits gold without rolling for traps."""
    member = make_member("Fighter", dexterity=0)
    party = make_party([make_member("Cleric"), member])

    # Only the two gold rolls exist in the script: the trap roll never happens.
    rng = ScriptedRNG([25, 6])
    monkeypatch.setattr(chests, "random", rng)

    lines = open_chest(party, member, dungeon=False, disarmed=True)

    assert lines == ["The Chest Holds: 41 Gold"]
    assert rng.rolls == []  # script fully consumed: only the gold rolls ran
    assert member.hp == 100
    assert member.status == Status.GOOD
    assert member.gold == 150 + 41


# --- Step 1: ChestNotFound ("Not Here!") ---

def test_take_chest_object_raises_when_no_chest():
    party = make_party([make_member("Fighter")], gold=0)
    with pytest.raises(ChestNotFound):
        chests.take_chest_object(party, 10, 10)

    party.dynamic_objects.append({"tile": "horse", "x": 10, "y": 10})
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 11})
    obj = chests.take_chest_object(party, 10, 10)
    assert obj["tile"] == "chest"
    assert party.dynamic_objects == [{"tile": "horse", "x": 10, "y": 10}]


# --- Step 1: dungeon Get (G) checks the party's own tile + crash fix ---

def make_dungeon_screen(party: Party) -> DungeonScreen:
    """An 8x8 interior dungeon with wall borders, party standing at (2,2)."""
    dmap = DungeonMap(id=99, name="TestDungeon", width=8, height=8, levels=8)
    dmap.tiles = [
        [
            [
                DungeonTile.WALL
                if x == 0 or x == 7 or y == 0 or y == 7
                else DungeonTile.FLOOR
                for x in range(8)
            ]
            for y in range(8)
        ]
        for z in range(8)
    ]
    return DungeonScreen(
        party=party, dungeon_map=dmap, start_x=2, start_y=2, start_z=0
    )


def press_and_answer(screen: DungeonScreen, answers: list[str]) -> None:
    """Press G, answer each successive prompt with the given single characters."""
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g))
    for answer in answers:
        assert screen.text_log.is_waiting_for_input
        screen.text_log.handle_char(answer)


def test_dungeon_get_opens_chest_on_party_tile(monkeypatch):
    """Dungeon G prompts for the member and opens the chest on the party's own tile."""
    member = make_member("Fighter", dexterity=200)
    party = make_party([member, make_member("Cleric")])
    screen = make_dungeon_screen(party)
    # Chest under the party's feet
    screen.dungeon_map.set_tile(2, 2, 0, DungeonTile.CHEST)
    moves_before = party.moves

    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 25, 6]))

    press_and_answer(screen, ["1"])

    assert not screen.text_log.is_waiting_for_input
    assert screen.dungeon_map.get_tile(2, 2, 0) == DungeonTile.NOTHING
    assert member.gold == 150 + 41
    assert party.gold == member.gold + 150  # per-member total: the opener's purse plus the untouched Cleric
    assert any("The Chest Holds: 41 Gold" in msg for msg in screen.text_log.history)
    assert party.moves == moves_before + 1  # G consumes a turn (finishTurn)


def test_dungeon_get_chest_not_here_consumes_turn(monkeypatch):
    """G on a chestless tile completes the prompt, logs 'Not Here!', consumes a turn."""
    member = make_member("Fighter", dexterity=200)
    party = make_party([member])
    screen = make_dungeon_screen(party)
    moves_before = party.moves

    press_and_answer(screen, ["1"])

    assert not screen.text_log.is_waiting_for_input
    assert any("Not Here!" in msg for msg in screen.text_log.history)
    assert party.moves == moves_before + 1


def test_dungeon_get_checks_only_party_tile(monkeypatch):
    """Only the party's own tile is checked: an adjacent chest is 'Not Here!'."""
    member = make_member("Fighter", dexterity=200)
    party = make_party([member])
    screen = make_dungeon_screen(party)
    screen.dungeon_map.set_tile(2, 1, 0, DungeonTile.CHEST)  # north of the party

    press_and_answer(screen, ["1"])

    assert any("Not Here!" in msg for msg in screen.text_log.history)
    assert screen.dungeon_map.get_tile(2, 1, 0) == DungeonTile.CHEST
