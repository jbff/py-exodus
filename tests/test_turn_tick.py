"""Task 4: per-move endTurn tick — submorsels, per-member food/gold, regen.

Java truth: ``exodus/Party.java:592-639`` (``Party.endTurn``) and
``objects/SaveGame.java:190-192,390-392`` (per-member ``food``/``gold`` and
``adjustGold`` capping a member's purse at 9999).
"""
from __future__ import annotations

import pytest

from py_exodus.constants import Profession, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyDeathException


def make_party(*members: Character) -> Party:
    party = Party()
    for m in members:
        party.add_member(m)
    return party


def hero(
    name: str = "Hero",
    hp: int = 100,
    max_hp: int = 100,
    mp: int = 0,
    max_mp: int | None = 10,
    food: int = 150,
    gold: int = 100,
    profession: Profession = Profession.FIGHTER,
    status: Status = Status.GOOD,
) -> Character:
    return Character(
        name=name,
        profession=profession,
        hp=hp,
        max_hp=max_hp,
        mp=mp,
        max_mp=max_mp,
        food=food,
        gold=gold,
        status=status,
    )


class TestSubmorselsTick:
    def test_main_map_food_decrements_on_11th_move(self):
        """Sosaria/Exodus: 40 submorsels per move; 400 pool hits exactly 0 on
        move 10 (no reset at 0), resets on move 11 → first food decrement."""
        party = make_party(hero())
        hero_member = party.members[0]
        for _ in range(11):
            party.end_turn(surface=True)
        assert hero_member.food == hero().food - 1

    def test_town_food_decrements_every_41_moves(self):
        """Towns: 10 submorsels per move; 400 pool reaches 0 on move 40,
        resets on move 41 → food -1."""
        party = make_party(hero(food=500))
        m = party.members[0]
        for _ in range(41):
            party.end_turn(surface=False)
        assert m.food == 499
        assert m.submorsels == 400

    def test_food_decrement_resets_submorsels_to_400(self):
        party = make_party(hero())
        # Drive submorsels to the crossing point and confirm reset.
        party.members[0].submorsels = 5
        party.end_turn(surface=True)
        assert party.members[0].submorsels == 400
        assert party.members[0].food == 149

    def test_moves_increment_once_per_tick(self):
        party = make_party(hero())
        party.end_turn(surface=True)
        party.end_turn(surface=False)
        assert party.moves == 2

    def test_each_member_ticks_its_own_submorsels(self):
        """Per-member pool: one member's submorsels/food are independent."""
        party = make_party(hero(name="A"), hero(name="B"))
        party.members[0].food = 150
        party.members[1].food = 99900
        party.members[1].submorsels = 5
        for _ in range(11):
            party.end_turn(surface=True)
        # Member A started at 400 → crossed once on move 11.
        assert party.members[0].food == 149
        # Member B started at 5 → crossed below 0 on the very first move,
        # then reset; the remaining 10 moves run the fresh pool down to 0
        # without another crossing.
        assert party.members[1].food == 99899
        assert party.members[1].submorsels == 0



class TestRegenTick:
    def test_poisoned_member_takes_tick_damage_instead_of_heal(self):
        party = make_party(hero(hp=50, status=Status.POISONED))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 49
        assert m.status == Status.POISONED  # poison persists through tick damage

    def test_healthy_member_heals_and_gains_mana(self):
        party = make_party(hero(hp=50, max_hp=100, mp=5, max_mp=10))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 51
        assert m.mp == 6

    def test_heal_caps_at_max_health(self):
        party = make_party(hero(hp=100, max_hp=100, mp=0, max_mp=10))
        party.end_turn(surface=True)
        assert party.members[0].hp == 100

    def test_mana_never_regens_past_max_druid_gains_two(self):
        party = make_party(hero(mp=9, max_mp=10, profession=Profession.DRUID))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        # Java checks mana < maxMana once, then adds 1 (+1 for Druid) — 9 → 11.
        assert m.mp == 11

        # Already at max: the once-per-tick guard blocks regen entirely.
        m.mp = 10
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.mp == 10

    def test_no_mana_regen_for_disabled_members(self):
        party = make_party(hero(mp=0, max_mp=10, status=Status.ASH))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        # Ash member still ticks food but never regens mana.
        assert m.mp == 0
        assert m.food == 149

    def test_dead_members_do_not_tick_at_all(self):
        party = make_party(hero(status=Status.DEAD))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.submorsels == 5
        assert m.food == 150


class TestStarvation:
    def test_food_zero_deals_two_damage_after_the_regen_line(self):
        """Java order: heal/poison first, mana second, starvation last — a
 healthy member at 50 hp heals to 51 then takes 2 damage."""
        party = make_party(hero(hp=50, food=0))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 49

    def test_starvation_wipe_raises_party_death(self):
        party = make_party(
            hero(hp=0, food=0),
            hero(name="B", hp=0, food=0),
        )
        for m in party.members:
            m.submorsels = 5
        with pytest.raises(PartyDeathException):
            party.end_turn(surface=True)


class TestPerMemberGold:
    def test_party_gold_is_derived_sum_of_members(self):
        party = make_party(hero(gold=100), hero(name="B", gold=200))
        assert party.gold == 300

    def test_party_gold_setter_distributes_to_members(self):
        party = make_party(hero(gold=100), hero(name="B", gold=200))
        party.gold -= 50
        assert party.members[0].gold == 50
        assert party.members[1].gold == 200
        assert party.gold == 250

    def test_member_gold_is_spent_not_a_pool(self):
        """Vendors (Task 8) spend from a member's purse; there is no separate pool."""
        party = make_party(hero(gold=100))
        member = party.members[0]
        member.adjust_gold(-30)
        assert member.gold == 70
        assert party.gold == 70

    def test_adjust_gold_caps_at_9999(self):
        m = hero(gold=9995)
        m.adjust_gold(10)
        assert m.gold == 9999
        m.adjust_gold(-999999)
        assert m.gold == 0

    def test_pool_gold_joins_all_gold_into_one_member(self):
        """Java Party.poolGold(index): total lands on member[index], rest zeroed."""
        party = make_party(hero(gold=100), hero(name="B", gold=200))
        assert party.pool_gold(1) == 300
        assert party.members[0].gold == 0
        assert party.members[1].gold == 300
