"""Per-turn tick — submorsels, per-member food/gold, original-rules regen.

Java truth: ``exodus/Party.java:592-639`` (``Party.endTurn``) and
``objects/SaveGame.java:190-192,390-392`` (per-member ``food``/``gold`` and
``adjustGold`` capping a member's purse at 9999).

Original-rules regen (user-directed deviation, 2026-11-10): the meal crossing
(submorsel block) decrements food ONLY. Mana, HP, poison and starvation move
to a per-turn tick (``Party.tick_regen``) following the U3 Book of Play:
mana +1/turn on the surface, +1 every 4 turns in town/dungeon (Druids
regenerate double the local rate); poisoned members lose 1 HP per turn;
healthy members regain +1 HP per turn on the surface, +1 per 4 turns
underground when food > 0; food 0 starves 2 HP per turn.
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


class TestHpRegenTick:
    """Original-rules HP regen: +1 per turn on the surface, +1 per 4 turns
    in towns/castles/dungeons when food > 0 and not poisoned (controller
    interpretation documented in Party.tick_regen — the manual quantifies
    only mana; the NES guide says regen is slower underground)."""

    def test_surface_one_hp_per_turn(self):
        party = make_party(hero(hp=50, max_hp=100))
        for _ in range(5):
            party.tick_regen(surface=True)
        assert party.members[0].hp == 55

    def test_town_one_hp_per_four_turns(self):
        party = make_party(hero(hp=50, max_hp=100))
        m = party.members[0]
        for _ in range(4):
            party.tick_regen(surface=False)
        assert m.hp == 51

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
    def test_food_zero_is_two_damage_per_turn_no_regen(self):
        """food <= 0: 2 damage per turn (everywhere), no HP regen."""
        party = make_party(hero(hp=50, food=0))
        m = party.members[0]
        party.tick_regen(surface=True)
        assert m.hp == 48

    def test_starvation_wipe_raises_party_death(self):
        party = make_party(
            hero(hp=1, food=0),
            hero(name="B", hp=1, food=0),
        )
        with pytest.raises(PartyDeathException):
            party.tick_regen(surface=True)

    def test_meal_crossing_decrements_food_only(self):
        """The meal crossing no longer heals/poisons/regs mana — the
        per-turn tick owns those (original-rules deviation; the old
        meal-crossing regen is removed, no double regen)."""
        party = make_party(hero(hp=50, max_hp=100, mp=0, max_mp=10))
        m = party.members[0]
        m.submorsels = 5
        party.end_turn(surface=True)
        assert m.food == 149
        assert m.hp == 50  # no heal at meal crossing
        assert m.mp == 0  # no mana at meal crossing


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
    (user-directed deviation): the overworld move AND pass, the town move
    and pass, and the dungeon move/blocked-move tick. Surface for regen
    means the overworld SCREEN (Sosaria AND Ambrosia) — the map_id in
    ("0","2") 40-submorsel decision is the food rule, not the regen rule."""

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
        assert m.hp == hp_before + 5  # pass consumes a turn → regen ran each turn

    def test_move_counts_as_a_turn(self, ow, monkeypatch):
        import pygame

        m = ow.party.members[0]
        hp_before = m.hp
        ow.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode="")
        )
        assert m.hp == hp_before + 1

    def test_ambrosia_regen_runs_at_surface_rate(self, pygame_setup, asset_mgr, ow):
        """map_id 13 (Ambrosia) drains food at the 10-submorsel town
        interval but regenerates mana/HP at the SURFACE rate: original-rule
        surface means the overworld screen, not the 40-interval map set
        (user-directed deviation, 2026-11-10)."""
        m = ow.party.members[0]
        ow.map_id = 13
        ow.party.map_id = 13
        ow._load_world_map()
        for _ in range(11):
            ow.handle_event(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ")
            )
        assert m.hp == 61  # +1 per turn — surface rate
        # Ambrosia's town food interval: 11 x 10 submorsels = 110 — no
        # crossing, food unchanged (Sosaria's 40-interval would have
        # crossed on move 11 and eaten one unit).
        assert m.food == 150
        assert m.submorsels == 400 - 110
