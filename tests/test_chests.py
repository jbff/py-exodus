"""Tests for the shared chest pipeline (gold, traps, direction targeting) and dungeon Get (G)."""
import random
import re

import pygame
import pytest

from py_exodus.constants import (
    ArmorType,
    Profession,
    Race,
    Status,
    Transport,
    WeaponType,
)
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException, PartyMember
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
    """Chest gold goes to member.gold within 30-100; other members are untouched
    and the party total rises only by the chest amount (per-member model)."""
    member = make_member("Fighter", dexterity=15)
    other = make_member("Cleric", dexterity=15)
    party = make_party([member, other], gold=500)

    # No trap (roll 1), then LW gold RandNum(0, 100) = 41 (30-100), then
    # the item gate misses (200 > 63).
    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 41, 200]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold"]
    assert member.gold == 250 + 41
    assert other.gold == 250
    assert party.gold == 500 + 41


def test_chest_gold_value_range_30_to_100(monkeypatch):
    """Over many seeded chests, credited gold is always 30-100 (LW
    GetChestBooty, UltimaMain.c:1686-1689) and member-only."""
    member = make_member("Fighter", dexterity=255)
    other = make_member("Cleric")
    party = make_party([member, other], gold=500)
    monkeypatch.setattr(chests, "random", random.Random(7))

    for _ in range(100):
        before = member.gold
        lines = open_chest(party, member, dungeon=False)
        delta = member.gold - before
        assert 30 <= delta <= 100
        gold_line = f"The Chest Holds: {delta} Gold"
        assert gold_line in lines
        assert lines.index(gold_line) == (1 if lines[0] == "Evaded!" else 0)
        assert member.gold <= 9999
        assert other.gold == 250  # non-opening members are never credited


def test_chest_gold_caps_at_9999(monkeypatch):
    """A member's gold caps at 9999 on chest credit (Java adjustGold)."""
    member = make_member("Fighter", gold=9990, dexterity=255)
    party = make_party([member], gold=9990)
    monkeypatch.setattr(chests, "random", random.Random(3))

    open_chest(party, member, dungeon=False)
    assert member.gold == 9999


# --- Step 1: pipeline trap behavior ---

def test_high_dex_always_evades_traps(monkeypatch):
    """LW: RandNum(0,255) > 255 never holds: a 255 factor never springs a trap."""
    member = make_member("Fighter", dexterity=255)
    party = make_party([member])
    monkeypatch.setattr(chests, "random", random.Random(2024))

    before_gold = member.gold
    for _ in range(60):
        open_chest(party, member, dungeon=False)
        assert member.hp == 100
        assert member.status == Status.GOOD
    assert member.gold > before_gold


def test_acid_trap_damages_opener(monkeypatch):
    """A failed evade on the Acid trap hurts that member RandNum(0,255) & 0x37
    (LW UltimaMain.c:1637-1646)."""
    member = make_member("Fighter")  # dex 15, no marks
    other = make_member("Cleric")
    party = make_party([member, other])

    # Trap present, evade roll 99 (hit for dex 15), acid, damage roll 21 & 0x37
    # = 21, gold 41, then the item gate misses
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 0, 0, 21, 41, 200]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Acid Trap!", "The Chest Holds: 41 Gold"]
    assert member.hp == 100 - 21
    assert member.status == Status.GOOD
    assert other.hp == 100  # acid hits only the opening member


def test_apply_fire_lava_exact_zero_hp_is_dead(monkeypatch):
    """Item 45: _apply_fire_lava routes through apply_damage, so exact 0 HP
    is dead (LairWare HPSubtract `hp < 1`, UltimaMain.c:3254; user ruling Q18)."""
    member = make_member("Fighter", hp=21, max_hp=100)
    make_party([member])
    # 21 & 0x37 == 21 exact damage
    monkeypatch.setattr(chests, "random", ScriptedRNG([21]))

    chests._apply_fire_lava(member)

    assert member.hp == 0
    assert member.status == Status.DEAD
    assert member.is_dead()


def test_apply_fire_lava_below_zero_kills_without_raising_out_of_open_chest(monkeypatch):
    """Item 45: lethal _apply_fire_lava kills via apply_damage while catching PartyDeathException
    so open_chest still yields its Acid Trap log before screen check_party_death."""
    member = make_member("Fighter", hp=20, max_hp=100)
    party = make_party([member])
    # Trap present, evade fails, Acid (0), damage 21 > 20 HP, gold 41, gate misses
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 0, 0, 21, 41, 200]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Acid Trap!", "The Chest Holds: 41 Gold"]
    assert member.hp == 0
    assert member.status == Status.DEAD
    assert member.is_dead()


def test_acid_trap_ignores_mark_of_fire(monkeypatch):
    """LW's acid trap is a plain HPSubtract (UltimaMain.c:1637-1646): the Mark
    of Fire (Java's FIRE/LAVA immunity) does not shield the opener."""
    member = make_member("Fighter", dexterity=0, marks=[0, 1, 0, 0])
    party = make_party([make_member("Cleric"), member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 0, 0, 21, 41, 200]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Acid Trap!", "The Chest Holds: 41 Gold"]
    assert member.hp == 100 - 21
    assert member.gold == 150 + 41


def test_gas_trap_poisons_whole_party(monkeypatch):
    """USER-DIRECTED GBC-RULES DEVIATION (2026-11-14): the Gas trap poisons
    every living member with no damage (GBC menucmd.c:1077-1147; LW
    UltimaMain.c:1718-1734 case 3 — every living member status 'P')."""
    member = make_member("Fighter")
    other = make_member("Cleric")
    already = make_member("Druid")
    dead = make_member("Wizard")
    party = make_party([member, other, already, dead])

    # Trap, hit, gas; no damage rolls exist under GBC rules, then gold, then
    # the drop rolls both miss (3, 3)
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 3, 3, 41, 200]))
    already.status = Status.POISONED
    dead.status = Status.DEAD

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Gas Trap!", "The Chest Holds: 41 Gold"]
    assert member.status == Status.POISONED
    assert other.status == Status.POISONED
    assert already.status == Status.POISONED
    assert all(m.hp == 100 for m in party.members)  # no fire/lava damage
    assert dead.status == Status.DEAD  # dead members are untouched


def test_gas_trap_hits_living_members_only(monkeypatch):
    """A Gas trap never resurrects a dead member or writes over its status."""
    member = make_member("Fighter")
    dead = make_member("Wizard")
    party = make_party([member, dead])

    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 3, 3, 41, 200]))
    dead.status = Status.DEAD
    dead.hp = 0

    open_chest(party, member, dungeon=False)

    assert dead.status == Status.DEAD
    assert dead.hp == 0
    assert member.status == Status.POISONED


def test_poison_trap_poisons_opener(monkeypatch):
    """A poison trap sets the POISONED status on the opening member without damaging them."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 1, 1, 41, 200]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Poison Trap!", "The Chest Holds: 41 Gold"]
    assert member.status == Status.POISONED
    assert member.hp == 100


def test_chest_trap_lw_typing_distribution_56_19_19_6(monkeypatch):
    """Item 28: LW UltimaMain.c:1628 uses (RandNum(0,255) & RandNum(0,255)) & 0x03,
    yielding 9/16 Acid (0), 3/16 Poison (1), 3/16 Bomb (2), 1/16 Gas (3)."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for a in range(4):
        for b in range(4):
            member = make_member("Fighter", dexterity=0, marks=[0, 1, 0, 0], max_hp=1000, hp=1000)
            party = make_party([member])
            monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, a, b, 0]))
            lines, _ = chests._chest_trap(party, member)
            assert len(lines) == 1
            counts[lines[0]] += 1

    assert counts == {
        "Acid Trap!": 9,
        "Poison Trap!": 3,
        "Bomb Trap!": 3,
        "Gas Trap!": 1,
    }


# --- Step: chest Bomb trap (LW BombTrap, UltimaMain.c:1662-1669 + 1728-1740) ---

def test_bomb_trap_damages_whole_party_living_only(monkeypatch):
    """The Bomb trap hits every living member through apply_damage with the
    LW formula (rnd255 & 0x77) + (dungeon_level + 1) * 8; dead members stay
    untouched, and LW case 2's early return (UltimaMain.c:1655-1663) credits
    NO gold or item drops — even when nobody dies."""
    member = make_member("Fighter")
    other = make_member("Cleric")
    dead = make_member("Wizard")
    dead.status = Status.DEAD
    dead.hp = 0
    party = make_party([member, other, dead])
    party.dungeon_level = 2  # dungeon level 3: bonus term (2 + 1) * 8 = 24
    member_gold, other_gold = member.gold, other.gold

    # Trap present, evade hit, Bomb; member roll 0x33 (51), other roll 0
    # (0x77 & roll). The script ends there: no gold or drop rolls exist.
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 2, 2, 0x33, 0]))

    lines = open_chest(party, member, dungeon=True)

    assert lines == ["Bomb Trap!"]
    assert member.hp == 100 - (51 + 24)
    assert other.hp == 100 - 24
    assert dead.status == Status.DEAD
    assert dead.hp == 0  # never resurrected, never damaged
    assert member.status == Status.GOOD
    assert member.gold == member_gold and other.gold == other_gold  # no booty


def test_bomb_trap_surface_band_8_to_127(monkeypatch):
    """On the surface (dungeon_level 0) each hit is (rnd255 & 0x77) + 8: band
    8-127, and every living member takes the same roll independently."""
    member = make_member("Fighter", dexterity=0, max_hp=1000)
    other = make_member("Cleric", dexterity=0, max_hp=1000)
    party = make_party([member, other])
    party.dungeon_level = 0

    for i in range(200):
        member.hp = 1000
        other.hp = 1000
        # Bomb roll for the opener walks 0..199; the Cleric always rolls 0x77.
        monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 2, 2, i % 200, 0x77]))
        m_hp, o_hp = member.hp, other.hp
        m_damage = (i % 200) & 0x77  # the mask folds bit-3 rolls onto others
        lines = open_chest(party, member, dungeon=False)
        assert lines == ["Bomb Trap!"]  # LW early return: no booty rolls at all
        assert member.hp == m_hp - (m_damage + 8)
        assert other.hp == o_hp - 127


def test_bomb_trap_dungeon_band_includes_level_term(monkeypatch):
    """At dungeon_level 7 the band is (0 + 64) to (0x77 + 64) = 64-183."""
    member = make_member("Fighter", dexterity=0, max_hp=1000)
    other = make_member("Cleric", dexterity=0, max_hp=1000)
    party = make_party([member, other])
    party.dungeon_level = 7

    for i in range(200):
        member.hp = 1000
        other.hp = 1000
        # Opener walks the full &0x77 spread (0..119 steps of 1 via 200 rolls
        # capped at 0x77), Cleric 0x77: both get the +64 level term.
        monkeypatch.setattr(
            chests,
            "random",
            ScriptedRNG([0, 99, 2, 2, (i * 119 // 199) & 0x77, 0x77]),
        )
        m_hp, o_hp = member.hp, other.hp
        open_chest(party, member, dungeon=True)
        m_damage = (i * 119 // 199) & 0x77
        assert member.hp == m_hp - (m_damage + 64)
        assert other.hp == o_hp - 183


def test_bomb_trap_wipes_through_apply_damage(monkeypatch):
    """A Bomb big enough to kill the whole party raises PartyDeathException
    out of open_chest through the apply_damage chokepoint (the screen layer
    catches it; DungeonScreen._finish_dungeon_chest has the try/except)."""
    member = make_member("Fighter", hp=10)
    party = make_party([member])

    # Blast at level 0: (0x77 & 0x77) + 8 = 127 > 10 hp.
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 2, 2, 0x77]))

    with pytest.raises(PartyDeathException):
        open_chest(party, member, dungeon=False)

    assert member.status == Status.DEAD
    assert member.hp == 0


def test_bomb_trap_single_death_does_not_raise(monkeypatch):
    """One member dying to the Bomb in a larger party does not raise: the
    party is not wiped. Per LW case 2's unconditional early return, the
    survivors get NO gold or item drops either — the booty path is skipped
    whenever the bomb springs, dead party or not."""
    member = make_member("Fighter", hp=10)
    other = make_member("Cleric")
    party = make_party([member, other])

    # member roll 0x77 -> 119 + 8 = 127 > 10: dead; other roll 0 -> 8: alive.
    # The script ends there: no gold or drop rolls exist after the bomb.
    monkeypatch.setattr(chests, "random", ScriptedRNG([0, 99, 2, 2, 0x77, 0]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["Bomb Trap!"]
    assert member.status == Status.DEAD
    assert other.status == Status.GOOD
    assert other.hp == 92


def test_disarmed_chest_yields_gold_and_no_trap_roll(monkeypatch):
    """A disarmed (APPAR_UNEM) chest credits gold without rolling for traps."""
    member = make_member("Fighter", dexterity=0)
    party = make_party([make_member("Cleric"), member])

    # Only the gold rolls plus the drop rolls exist in the script: the trap
    # roll never happens (both drop rolls miss — 4, 4).
    rng = ScriptedRNG([41, 200])
    monkeypatch.setattr(chests, "random", rng)

    lines = open_chest(party, member, dungeon=False, disarmed=True)

    assert lines == ["The Chest Holds: 41 Gold"]
    assert rng.rolls == []  # script fully consumed: no trap roll ever ran
    assert member.hp == 100
    assert member.status == Status.GOOD
    assert member.gold == 150 + 41


# --- Step 1: ChestNotFound ("Not Here!") ---


def test_take_chest_object_raises_when_no_chest():
    """Task 9: the G scan has no adjacency — only the exact tile matches
    (Java getChest, GameScreen.java:1041-1050: cx == x && cy == y)."""
    party = make_party([make_member("Fighter")], gold=0)
    with pytest.raises(ChestNotFound):
        chests.take_chest_object(party, 10, 10)

    party.dynamic_objects.append({"tile": "horse", "x": 10, "y": 10})
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 10})
    obj = chests.take_chest_object(party, 10, 10)
    assert obj["tile"] == "chest"
    assert party.dynamic_objects == [{"tile": "horse", "x": 10, "y": 10}]


def test_take_chest_object_checks_only_party_tile():
    party = make_party([make_member("Fighter")], gold=0)
    party.dynamic_objects.append({"tile": "chest", "x": 10, "y": 11})
    with pytest.raises(ChestNotFound):
        chests.take_chest_object(party, 10, 10)
    assert party.dynamic_objects == [{"tile": "chest", "x": 10, "y": 11}]


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
    member = make_member("Fighter", dexterity=255)
    party = make_party([member, make_member("Cleric")])
    screen = make_dungeon_screen(party)
    # Chest under the party's feet
    screen.dungeon_map.set_tile(2, 2, 0, DungeonTile.CHEST)
    moves_before = party.moves

    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 41, 200]))

    press_and_answer(screen, ["1"])

    assert not screen.text_log.is_waiting_for_input
    assert screen.dungeon_map.get_tile(2, 2, 0) == DungeonTile.NOTHING
    assert member.gold == 150 + 41
    assert party.gold == member.gold + 150  # per-member total: the opener's purse plus the untouched Cleric
    assert any("The Chest Holds: 41 Gold" in msg for msg in screen.text_log.history)
    # G consumes two turns (Java DungeonScreen.java:1011-1013 routes the G
    # press itself through finishTurn, and the member selection runs the sip
    # keyUp tail finishTurn) — but finishTurn never calls Party.endTurn in
    # dungeons, so the move counter does not tick (Party.endTurn is only
    # called from GameScreen.java:712 / CombatScreen.java:472).
    assert party.moves == moves_before


def test_dungeon_get_chest_not_here_consumes_turn(monkeypatch):
    """G on a chestless tile completes the prompt, logs 'Not Here!', consumes a turn."""
    member = make_member("Fighter", dexterity=255)
    party = make_party([member])
    screen = make_dungeon_screen(party)
    moves_before = party.moves

    press_and_answer(screen, ["1"])

    assert not screen.text_log.is_waiting_for_input
    assert any("Not Here!" in msg for msg in screen.text_log.history)
    # Turn consumed (press + selection Java fall-through) without a moves
    # increment: dungeon finishTurn never calls Party.endTurn.
    assert party.moves == moves_before


def test_dungeon_get_checks_only_party_tile(monkeypatch):
    """Only the party's own tile is checked: an adjacent chest is 'Not Here!'."""
    member = make_member("Fighter", dexterity=255)
    party = make_party([member])
    screen = make_dungeon_screen(party)
    screen.dungeon_map.set_tile(2, 1, 0, DungeonTile.CHEST)  # north of the party

    press_and_answer(screen, ["1"])

    assert any("Not Here!" in msg for msg in screen.text_log.history)
    assert screen.dungeon_map.get_tile(2, 1, 0) == DungeonTile.CHEST


# --- Step: chest item drops (LW GetChestBooty, UltimaMain.c:1736-1760) ---
#
# After gold: ~25% weapon find (index 1-7 -> DAGGER..SWORD_2H via
# list(WeaponType)), else an independent ~25% armor find (index 1-3 ->
# CLOTH..CHAIN). A capped (9) weapon stack falls straight to the armor side
# per the steal/dig stack conventions (special_commands); a granted weapon
# ends the loot there (LW's weapon-side return). Drops run on every open,
# including the disarmed (APPAR_UNEM) path — LW's trap branches all fall
# through to the same GetChestBooty rolls.


def test_weapon_drop_line_and_stack(monkeypatch):
    """Gate open (<= 63), weapon roll 0x7F, mask roll 4 -> (4 & 0x7F) & 7 = 4
    (AXE): +1 to the stack and the line logged."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 41, 0, 0x7F, 4, 0]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold", "You found a Axe!"]
    assert lines.item_lines == ["You found a Axe!"]
    assert member.weapons[WeaponType.AXE] == 1
    assert all(c == 0 for c in member.armors.values())
    assert member.gold == 150 + 41


def test_armor_drop_after_weapon_roll_misses(monkeypatch):
    """Weapon roll >= 128: the armour roll follows (0x7F, mask 3 -> CHAIN)."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 41, 0, 200, 0x7F, 3]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold", "You found a Chain!"]
    assert member.armors[ArmorType.CHAIN] == 1
    assert all(c == 0 for c in member.weapons.values())


def test_weapon_hit_skips_the_armor_side(monkeypatch):
    """A granted weapon ends the loot rolls (LW weapon-side return)."""
    member = make_member("Fighter")
    party = make_party([member])

    rng = ScriptedRNG([1, 41, 0, 0x7F, 6, 0, 0])
    monkeypatch.setattr(chests, "random", rng)

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold", "You found a Sword!"]
    assert all(c == 0 for c in member.armors.values())
    assert rng.rolls == [0, 0]


def test_zero_weapon_roll_falls_to_armor_side(monkeypatch):
    """A masked weapon roll of 0 grants no weapon; the armour roll follows."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 41, 0, 0x7F, 8, 0x7F, 1]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold", "You found a Cloth!"]
    assert member.armors[ArmorType.CLOTH] == 1


def test_closed_gate_grants_nothing(monkeypatch):
    """Gate roll > 63: gold only."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([1, 41, 64]))

    lines = open_chest(party, member, dungeon=False)

    assert lines == ["The Chest Holds: 41 Gold"]


def test_disarmed_chest_yields_item_drops_too(monkeypatch):
    """The APPAR_UNEM path opens the same booty rolls: gold + item, no trap."""
    member = make_member("Fighter")
    party = make_party([member])

    monkeypatch.setattr(chests, "random", ScriptedRNG([41, 0, 0x7F, 2]))

    lines = open_chest(party, member, dungeon=False, disarmed=True)

    assert lines == ["The Chest Holds: 41 Gold", "You found a Mace!"]
    assert not any("Trap" in line for line in lines)
    assert member.weapons[WeaponType.MACE] == 1


def test_seeded_drop_trials_lairware_shares_and_gold_band(monkeypatch):
    """Seeded trials: gold 30-100 per open; LW's masked rolls give a weapon
    about 7% of the time (1/4 * 1/2 * 37/64) and armour about 4%."""
    monkeypatch.setattr(chests, "random", random.Random(11))

    weapon_names = {w.name.capitalize() for w in list(WeaponType)[1:8]}
    armor_names = {a.name.capitalize() for a in list(ArmorType)[1:4]}
    weapon_drops = armor_drops = 0
    for _ in range(2000):
        member = make_member("Fighter", dexterity=255, gold=100)
        party = make_party([member])
        before = member.gold
        lines = open_chest(party, member, dungeon=False)
        delta = member.gold - before
        assert 30 <= delta <= 100
        assert f"The Chest Holds: {delta} Gold" in lines
        for line in lines:
            if line.startswith("You found a "):
                name = line[len("You found a ") : -1]
                assert name in weapon_names | armor_names
                if name in weapon_names:
                    weapon_drops += 1
                else:
                    armor_drops += 1

    assert 90 <= weapon_drops <= 200, weapon_drops
    assert 40 <= armor_drops <= 120, armor_drops


def test_trap_dodge_follows_lairware_steal_disarm(monkeypatch):
    """LairWare StealDisarmFail (UltimaMisc.c:510-529; user ruling
    2026-11-22): the trap goes off when RandNum(0,255) > dex (+128 Thief,
    +64 Barbarian/Illusionist/Ranger/Alchemist). A 25-DEX Thief dodges a 153
    roll that a 25-DEX Fighter does not; Java's dex+25 >= rand(100) made
    them equal and DEX 74 trap-proof."""
    from py_exodus.world import chests

    thief = Character("T", "M", profession=Profession.THIEF, dexterity=25)
    fighter = Character("F", "M", profession=Profession.FIGHTER, dexterity=25)
    assert chests.disarm_factor(thief) == 153
    assert chests.disarm_factor(fighter) == 25
    monkeypatch.setattr(chests.random, "randrange", lambda n: 153)
    assert not chests.steal_disarm_fails(thief)
    assert chests.steal_disarm_fails(fighter)
    agile = Character("F", "M", profession=Profession.FIGHTER, dexterity=74)
    monkeypatch.setattr(chests.random, "randrange", lambda n: 200)
    assert chests.steal_disarm_fails(agile)  # no DEX is trap-proof any more
