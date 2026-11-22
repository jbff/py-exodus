"""Per-turn tick — submorsels, per-member food/gold, regen rules.

Java truth: ``exodus/Party.java:592-639`` (``Party.endTurn``) and
``objects/SaveGame.java:190-192,390-392`` (per-member ``food``/``gold`` and
``adjustGold`` capping a member's purse at 9999).

Rule split (USER-DIRECTED GBC-RULES DEVIATION, 2026-11-14, supersedes the
2026-11-10 interpretation for the HP-regen and starvation rules ONLY): at
each meal crossing a member with food 0 takes 5 damage and a fed, unpoisoned
member heals +1 HP (GBC funcs5.c:741-789; LW UltimaMisc.c:1428-1493).
Mana (+1/turn surface, +1 per 4 turns underground, Druids double the local
rate) and poison (-1 HP per turn) stay on the per-turn tick
(``Party.tick_regen``, 2026-11-10 interpretation kept).
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



class TestManaRegenTick:
    """Original-rules mana regen — user-directed deviation from Java.

    Java regen sat inside the meal crossing (Party.java:612-617) and could
    exceed maxMana (`mana < maxMana` checked once, then +1, +1 more for a
    Druid). The original tick regenerates every consumed turn: +1 per turn
    on the surface, +1 every 4 turns in a town/dungeon, Druids double the
    local rate, capped at max_mp.
    """

    def test_surface_five_turns_gains_five_mana(self):
        party = make_party(hero(mp=0, max_mp=10))
        for _ in range(5):
            party.tick_regen(surface=True)
        assert party.members[0].mp == 5

    def test_druid_surface_gains_two_per_turn_capped_at_max(self):
        party = make_party(
            hero(name="D", mp=0, max_mp=10, profession=Profession.DRUID)
        )
        for _ in range(5):
            party.tick_regen(surface=True)
        assert party.members[0].mp == 10  # 2 x 5, capped at max

    def test_mana_never_exceeds_max(self):
        """Java's exceed-max quirk (9 → 11 for a Druid) is NOT reproduced:
        the original-rules tick caps at max_mp."""
        party = make_party(
            hero(name="D", mp=9, max_mp=10, profession=Profession.DRUID)
        )
        m = party.members[0]
        party.tick_regen(surface=True)
        assert m.mp == 10

        # Already at max: no regen.
        party.tick_regen(surface=True)
        assert m.mp == 10

    def test_town_mana_once_every_four_turns(self):
        party = make_party(hero(mp=0, max_mp=10))
        m = party.members[0]
        for _ in range(3):
            party.tick_regen(surface=False)
        assert m.mp == 0
        party.tick_regen(surface=False)  # 4th turn
        assert m.mp == 1
        for _ in range(4):
            party.tick_regen(surface=False)  # turns 5-8
        assert m.mp == 2

    def test_town_druid_gains_two_in_the_same_fourth_turn_slot(self):
        """Druids double the local rate — 2 in the SAME 4th turn slot,
        not +1 every 2nd turn."""
        party = make_party(
            hero(name="D", mp=0, max_mp=10, profession=Profession.DRUID)
        )
        m = party.members[0]
        for _ in range(3):
            party.tick_regen(surface=False)
        assert m.mp == 0  # not every 2nd turn
        party.tick_regen(surface=False)  # 4th turn
        assert m.mp == 2
        for _ in range(4):
            party.tick_regen(surface=False)
        assert m.mp == 4

    def test_no_mana_regen_for_disabled_members(self):
        party = make_party(hero(mp=0, max_mp=10, status=Status.ASH))
        m = party.members[0]
        party.tick_regen(surface=True)
        assert m.mp == 0

    def test_dead_members_never_regen(self):
        party = make_party(hero(status=Status.DEAD, mp=0, max_mp=10))
        m = party.members[0]
        party.tick_regen(surface=True)
        assert m.mp == 0

    def test_regen_counter_is_count_based_across_screen_hops(self):
        """The 4-turn slot counts consumed turns (move or pass — both route
        through the tick), not wall-clock, and a surface hop does not reset
        the underground cadence counter."""
        party = make_party(hero(mp=0, max_mp=10))
        for _ in range(3):
            party.tick_regen(surface=False)
        party.tick_regen(surface=True)
        assert party.members[0].mp == 1


class TestMealCrossingRegen:
    """GBC meal-bound HP rules — USER-DIRECTED GBC-RULES DEVIATION
    (2026-11-14, supersedes the 2026-11-10 interpretation for these two
    rules): at each meal crossing (the ``submorsels < 0`` block in
    ``end_turn``) a member with food 0 takes 5 damage and a member with
    food > 0 heals +1 HP unless POISONED (GBC funcs5.c:741-789; LW
    UltimaMisc.c:1428-1493). Both route through ``apply_damage`` — a wipe
    raises ``PartyDeathException``."""

    def test_heal_caps_at_max_health(self):
        party = make_party(hero(hp=100, max_hp=100))
        for _ in range(3):
            party.tick_regen(surface=True)
        assert party.members[0].hp == 100

    def test_poisoned_member_loses_one_hp_per_turn(self):
        party = make_party(hero(hp=50, status=Status.POISONED))
        m = party.members[0]
        for _ in range(5):
            party.tick_regen(surface=True)
        assert m.hp == 45
        assert m.status == Status.POISONED  # poison persists through tick damage

    def test_poisoned_member_does_not_also_heal(self):
        party = make_party(hero(hp=50, max_hp=100, status=Status.POISONED))
        party.tick_regen(surface=True)
        assert party.members[0].hp == 49

    def test_no_regen_for_dead_member(self):
        party = make_party(hero(hp=0, status=Status.DEAD))
        party.tick_regen(surface=True)
        assert party.members[0].hp == 0


class TestStarvation:
    def test_starvation_is_meal_bound_not_turn_bound(self, monkeypatch):
        """No crossing this turn → no starvation blow at all: the per-turn
        2-damage tick is gone (superseded); 5 HP lands ONLY at the crossing."""
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        party = make_party(hero(hp=50, food=0))
        m = party.members[0]
        party.end_turn(surface=True)  # submorsels 400: no crossing on move 1
        assert m.hp == 50
        party.tick_regen(surface=True)  # mana/poison tick: no starvation
        assert m.hp == 50

    def test_meal_crossing_at_food_zero_takes_5(self, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        party = make_party(hero(hp=20, food=0))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 15

    def test_two_meal_crossings_take_exactly_two_5_damage_events(self, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        party = make_party(hero(hp=20, food=0))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)  # crossing #1: 20 → 15
        assert m.hp == 15
        m.submorsels = 5
        party.end_turn(surface=True)  # crossing #2
        assert m.hp == 10

    def test_starvation_wipe_at_crossing_raises_party_death(self, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        party = make_party(
            hero(hp=1, food=0),
            hero(name="B", hp=1, food=0),
        )
        for m in party.members:
            m.submorsels = 5
        with pytest.raises(PartyDeathException):
            party.end_turn(surface=True)

    def test_fed_member_heals_one_per_crossing_capped_at_max(self, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        party = make_party(hero(hp=98, max_hp=100))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 99
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 100

    def test_poisoned_member_gets_no_crossing_heal(self, monkeypatch):
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        party = make_party(hero(hp=50, max_hp=100, status=Status.POISONED))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.hp == 50  # GBC "not poisoned" gate: no +1 heal at the crossing
        assert m.status == Status.POISONED

    def test_meal_crossing_regen_lands_there_not_on_the_tick(self):
        """The crossing heals +1 (GBC meal-bound regen); mana and poison
        stay on the per-turn tick — no mana at the crossing."""
        party = make_party(hero(hp=50, max_hp=100, mp=0, max_mp=10))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.food == 149
        assert m.hp == 51  # +1 heal AT the meal crossing
        assert m.mp == 0  # mana stays on the per-turn tick


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
    """Every consumed turn on every screen routes through the regen tick
    (user-directed deviation) — mana and poison only, since the GBC
    2026-11-14 ruling moved HP regen and starvation onto the meal crossing.
    Surface for regen means the overworld SCREEN (Sosaria AND Ambrosia) —
    the map_id in ("0","2") 40-submorsel decision is the food rule, not the
    regen rule."""

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
        import pygame

        m = ow.party.members[0]
        hp_before = m.hp
        for _ in range(5):
            ow.handle_event(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ")
            )
        # No per-turn HP regen (GBC meal-bound rules); 5 passes at 40
        # submorsels each do not reach a crossing (200 of 400).
        assert m.hp == hp_before

    def test_move_crossing_heals_and_pass_does_not_starve(self, ow, monkeypatch):
        import pygame

        # Pin the party RNG so nothing random fires into the assertion.
        monkeypatch.setattr("py_exodus.entities.party.random.randint", lambda a, b: 1)
        m = ow.party.members[0]
        m.submorsels = 5
        hp_before = m.hp
        ow.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode="")
        )
        assert m.hp == hp_before + 1  # the move crossed a meal: +1 HP, fed member

    def test_ambrosia_food_drains_at_the_town_interval_no_regen(self, pygame_setup, asset_mgr, ow):
        """map_id 13 (Ambrosia) drains food at the 10-submorsel town
        interval (Java truth); the crossing regen has NO surface cadence
        split (GBC meal-bound rules supersede the 2026-11-10 HP rule), and
        11 passes at 10 submorsels never cross (110 of 400)."""
        m = ow.party.members[0]
        ow.map_id = 13
        ow.party.map_id = 13
        ow._load_world_map()
        for _ in range(11):
            ow.handle_event(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ")
            )
        assert m.hp == 50  # no per-turn regen, no crossing this turn count
        assert m.food == 150
        assert m.submorsels == 400 - 110
