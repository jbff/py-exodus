"""Per-turn tick: food, starving, poison, healing and mana, per member.

LairWare AgeChars ($7470, UltimaMisc.c:1403-1468) and EatFood ($761D,
1470-1488), by the user's rulings of 2026-11-25 (ledger T-16..T-20): one tick
every Sosaria turn and every 4th turn elsewhere (Party[3] > 0); each tick
eats 40 of a member's 400 pool, takes 5 from a member with no food left,
1 from the poisoned, gives +1 MP (a Druid +2, Book of Lore) and, every 10th
tick, +1 HP to every living member. Gold is per member (Java
``objects/SaveGame.java:190-192,390-392``).
"""
from __future__ import annotations

import pygame
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
        """Sosaria: a tick every turn, 40 of the 400 pool each; the pool hits
        exactly 0 on move 10 (no reset at 0), crosses on move 11: food -1."""
        party = make_party(hero())
        hero_member = party.members[0]
        for _ in range(11):
            party.end_turn(sosaria=True)
        assert hero_member.food == hero().food - 1

    def test_town_food_decrements_on_the_11th_tick(self):
        """Towns: a tick every 4th turn (the first turn ticks), 40 each; the
        11th tick is turn 41: food -1."""
        party = make_party(hero(food=500))
        m = party.members[0]
        for _ in range(40):
            party.end_turn(sosaria=False)
        assert m.food == 500
        party.end_turn(sosaria=False)
        assert m.food == 499
        assert m.submorsels == 396 - 40  # residual carried (EatFood)

    def test_food_decrement_carries_the_residual(self):
        """LairWare EatFood (UltimaMisc.c:1472-1474, `Player[34] -= 157`):
        the borrow keeps the remainder; one food is 396 of the pool."""
        party = make_party(hero())
        party.members[0].submorsels = 5
        party.end_turn(sosaria=True)
        assert party.members[0].submorsels == 5 - 40 + 396
        assert party.members[0].food == 149

    def test_moves_increment_once_per_tick(self):
        party = make_party(hero())
        party.end_turn(sosaria=True)
        party.end_turn(sosaria=False)
        assert party.moves == 2

    def test_each_member_ticks_its_own_submorsels(self):
        """Per-member pool: one member's submorsels/food are independent."""
        party = make_party(hero(name="A"), hero(name="B"))
        party.members[0].food = 150
        party.members[1].food = 99900
        party.members[1].submorsels = 5
        for _ in range(11):
            party.end_turn(sosaria=True)
        # Member A started at 400 → crossed once on move 11.
        assert party.members[0].food == 149
        # Member B started at 5 → crossed below 0 on the very first move
        # (5 - 40 + 396 = 361); the remaining 10 moves take it to -39: a
        # second crossing on move 11 (residual carried).
        assert party.members[1].food == 99898
        assert party.members[1].submorsels == 361 - 400 + 396


class TestManaRegenTick:
    """LairWare AgeChars mana (UltimaMisc.c:1418-1447): +1 MP a tick up to
    the class cap, the dead and ashes included; a Druid +2 to its max (user
    ruling 2026-11-25, Book of Lore). Java's exceed-max quirk is not
    reproduced."""

    def test_surface_five_turns_gains_five_mana(self):
        party = make_party(hero(mp=0, max_mp=10))
        for _ in range(5):
            party.age_chars(sosaria=True)
        assert party.members[0].mp == 5

    def test_druid_surface_gains_two_per_turn_capped_at_max(self):
        party = make_party(
            hero(name="D", mp=0, max_mp=10, profession=Profession.DRUID)
        )
        for _ in range(5):
            party.age_chars(sosaria=True)
        assert party.members[0].mp == 10  # 2 x 5, capped at max

    def test_mana_never_exceeds_max(self):
        party = make_party(
            hero(name="D", mp=9, max_mp=10, profession=Profession.DRUID)
        )
        m = party.members[0]
        party.age_chars(sosaria=True)
        assert m.mp == 10

        # Already at max: no regen.
        party.age_chars(sosaria=True)
        assert m.mp == 10

    def test_town_mana_once_every_four_turns(self):
        """Off Sosaria a tick every 4th call; LW's gTime[0] starts at 0, so
        the first call ticks."""
        party = make_party(hero(mp=0, max_mp=10))
        m = party.members[0]
        party.age_chars(sosaria=False)  # 1st call ticks
        assert m.mp == 1
        for _ in range(3):
            party.age_chars(sosaria=False)
        assert m.mp == 1
        party.age_chars(sosaria=False)  # 5th call
        assert m.mp == 2

    def test_town_druid_gains_two_in_the_same_tick(self):
        """Druids gain 2 in the same tick, not +1 every 2nd turn."""
        party = make_party(
            hero(name="D", mp=0, max_mp=10, profession=Profession.DRUID)
        )
        m = party.members[0]
        party.age_chars(sosaria=False)
        assert m.mp == 2
        for _ in range(3):
            party.age_chars(sosaria=False)
        assert m.mp == 2  # not every 2nd turn
        party.age_chars(sosaria=False)
        assert m.mp == 4

    def test_ashes_regain_mana(self):
        """UltimaMisc.c:1415-1449: the mana block runs before the status
        test, so ashes regain MP as in LairWare."""
        party = make_party(hero(mp=0, max_mp=10, status=Status.ASH))
        m = party.members[0]
        party.age_chars(sosaria=True)
        assert m.mp == 1

    def test_dead_members_regain_mana(self):
        party = make_party(hero(status=Status.DEAD, hp=0, mp=0, max_mp=10))
        m = party.members[0]
        party.age_chars(sosaria=True)
        assert m.mp == 1

    def test_age_count_carries_across_screen_hops(self):
        """The 4-call count (gTime[0]) is one party counter: Sosaria ticks
        leave it alone, the next off-Sosaria calls carry on from it."""
        party = make_party(hero(mp=0, max_mp=10))
        party.age_chars(sosaria=False)  # ticks: count back to 4
        party.age_chars(sosaria=False)  # 3
        party.age_chars(sosaria=True)  # Sosaria tick, count untouched
        assert party.members[0].mp == 2
        party.age_chars(sosaria=False)  # 2
        party.age_chars(sosaria=False)  # 1
        assert party.members[0].mp == 2
        party.age_chars(sosaria=False)  # 0: ticks
        assert party.members[0].mp == 3


class TestHealAndPoison:
    """LairWare AgeChars (UltimaMisc.c:1454-1462): POISON! -1 HP a tick;
    every 10th tick (gTime[1], one party counter) +1 HP to every member not
    dead or ashes, the poisoned and starving too. Both route through
    ``apply_damage``: a wipe raises ``PartyDeathException``."""

    def test_heal_caps_at_max_health(self):
        party = make_party(hero(hp=100, max_hp=100))
        for _ in range(10):
            party.age_chars(sosaria=True)
        assert party.members[0].hp == 100

    def test_poisoned_member_loses_one_hp_per_tick(self):
        party = make_party(hero(hp=50, status=Status.POISONED))
        m = party.members[0]
        for _ in range(5):
            party.age_chars(sosaria=True)
        assert m.hp == 45
        assert m.status == Status.POISONED  # poison persists through tick damage

    def test_poisoned_member_heals_on_the_tenth_tick_too(self):
        party = make_party(hero(hp=50, max_hp=100, status=Status.POISONED))
        for _ in range(10):
            party.age_chars(sosaria=True)
        assert party.members[0].hp == 41

    def test_no_regen_for_dead_member(self):
        party = make_party(hero(hp=0, status=Status.DEAD))
        for _ in range(10):
            party.age_chars(sosaria=True)
        assert party.members[0].hp == 0

    def test_heal_every_tenth_tick(self):
        party = make_party(hero(hp=98, max_hp=100))
        m = party.members[0]
        for _ in range(9):
            party.age_chars(sosaria=True)
        assert m.hp == 98
        party.age_chars(sosaria=True)
        assert m.hp == 99
        for _ in range(10):
            party.age_chars(sosaria=True)
        assert m.hp == 100


class TestStarvation:
    """LairWare EatFood (UltimaMisc.c:1477-1487): a member whose food (the
    fraction too) is gone starves for 5 HP every tick."""

    def test_food_zero_with_a_fraction_left_does_not_starve(self):
        party = make_party(hero(hp=50, food=0))
        m = party.members[0]
        party.end_turn(sosaria=True)  # 400 → 360: the fraction is left
        assert m.hp == 50

    def test_food_gone_takes_5(self):
        party = make_party(hero(hp=20, food=0))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(sosaria=True)
        assert m.hp == 15

    def test_starving_every_tick_once_gone(self):
        party = make_party(hero(hp=20, food=0))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(sosaria=True)  # 20 → 15, the pool stays empty
        assert (m.hp, m.submorsels) == (15, 0)
        party.end_turn(sosaria=True)
        assert m.hp == 10

    def test_starvation_wipe_raises_party_death(self):
        party = make_party(
            hero(hp=1, food=0),
            hero(name="B", hp=1, food=0),
        )
        for m in party.members:
            m.submorsels = 5
        with pytest.raises(PartyDeathException):
            party.end_turn(sosaria=True)

    def test_meal_crossing_does_not_heal(self):
        """Healing rides the 10th tick, not the meal; mana ticks every
        tick."""
        party = make_party(hero(hp=50, max_hp=100, mp=0, max_mp=10))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(sosaria=True)
        assert m.food == 149
        assert m.hp == 50
        assert m.mp == 1


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


class TestScreenTickRouting:
    """Every consumed overworld turn routes through AgeChars: every turn on
    Sosaria, every 4th on Ambrosia (Party[3] > 0)."""

    @pytest.fixture
    def ow(self, pygame_setup, asset_mgr, monkeypatch):
        from py_exodus.screens import overworld as overworld_module
        from py_exodus.screens.overworld import OverworldScreen

        party = Party()
        party.add_member(
            Character(
                name="Hero",
                profession=Profession.FIGHTER,
                hp=50,
                max_hp=100,
                mp=0,
                max_mp=10,
                food=150,
                gold=100,
                status=Status.GOOD,
            )
        )
        o = OverworldScreen(
            party=party,
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=10,
            start_y=10,
            random_encounters=False,
        )
        monkeypatch.setattr(overworld_module, "can_move_to", lambda *a, **k: True)
        o._check_moongates = lambda: None  # type: ignore[method-assign]
        o._check_random_encounter = lambda: None  # type: ignore[method-assign]
        return o

    def test_overworld_pass_counts_as_a_turn(self, ow):
        m = ow.party.members[0]
        hp_before = m.hp
        for _ in range(5):
            ow.handle_event(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ")
            )
        # Five ticks: 5 MP, no heal yet (the 10th tick), 200 of the pool.
        assert m.hp == hp_before
        assert m.mp == 5
        assert m.submorsels == 200

    def test_tenth_move_heals(self, ow):
        m = ow.party.members[0]
        hp_before = m.hp
        for _ in range(10):
            ow.handle_event(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode="")
            )
        assert m.hp == hp_before + 1

    def test_ambrosia_ticks_every_fourth_turn(self, pygame_setup, asset_mgr, ow):
        """map_id 13 (Ambrosia): Party[3] > 0, so AgeChars acts on turns 1,
        5, 9 of 11: three ticks of 40."""
        m = ow.party.members[0]
        ow.map_id = 13
        ow.party.map_id = 13
        ow._load_world_map()
        for _ in range(11):
            ow.handle_event(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ")
            )
        assert m.hp == 50
        assert m.food == 150
        assert m.submorsels == 400 - 120
        assert m.mp == 3
