"""Autoplay inside dungeons (autoplay round 1, user-approved 2026-11-25):
fountains, marks for every living member, deep-mark gates and turn-back
thresholds. The canonical party only (batch.build_party)."""
from __future__ import annotations

import random

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.autoplay.batch import build_party
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import ArmorType, Status, WeaponType
from py_exodus.state_machine import StateMachine
from py_exodus.world.loader import load_map
from py_exodus.world.map import DungeonTile

FIRE = 17  # Mark of Fire and Mark of Force, both on level 8 (z 7)


@pytest.fixture(scope="module")
def am():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    mgr = AssetManager("data")
    mgr.load_all()
    yield mgr


def _party(level: int = 9, marks=(1, 0, 0, 0)):
    """The canonical party (Thief, Fighter, Cleric, Wizard), exotics, fed,
    at full HP; ``marks`` for every member."""
    party = build_party()
    for m in party.members:
        m.level = level
        m.max_hp = m.hp = level * 100 + 50
        m.marks = list(marks)
        m.cards = [0, 0, 0, 0]
        m.weapons[WeaponType.EXOTIC] = 1
        m.weapon = WeaponType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.food = 500
        m.torches = 5
    party.map_id = FIRE
    return party


def _dungeon(am, party, map_id: int, at: tuple[int, int, int]):
    from py_exodus.screens.dungeon_screen import DungeonScreen

    random.seed(7)
    dmap = load_map(map_id, am)
    sm = StateMachine(asset_mgr=am, audio=None)
    ds = DungeonScreen(party=party, dungeon_map=dmap, asset_mgr=am)
    ds.state.random_encounters_enabled = False
    ds.state.rng.seed(7)
    ds.state.x, ds.state.y, ds.state.z = at
    sm.set_screen(ds)
    return sm, ds


def _drinks(monkeypatch, ds) -> list[tuple[DungeonTile, int]]:
    """Record every drink: (fountain tile, 0-based member)."""
    calls: list[tuple[DungeonTile, int]] = []
    real = ds.state.drink_fountain

    def spy(member_index: int = 0):
        calls.append((ds.state.current_tile, member_index))
        return real(member_index)

    monkeypatch.setattr(ds.state, "drink_fountain", spy)
    return calls


# --- Item 1: fountains -------------------------------------------------------


def test_fountain_types_come_from_map_position(am):
    """Autoplay reads fountain types off the loaded map, which types them by
    x & 3 (0 poison, 1 heal, 2 acid, 3 cure; UltimaDngn.c:243)."""
    dmap = load_map(FIRE, am)
    heal = AutoPlayController._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_HEAL})
    assert (13, 5, 1) in heal and (9, 9, 4) in heal
    assert all(x & 3 == 1 for x, _y, _z in heal)
    cure = AutoPlayController._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_CURE})
    assert all(x & 3 == 3 for x, _y, _z in cure)


def test_heal_fountain_each_hurt_member_drinks_once_then_steps_off(am, monkeypatch):
    party = _party()
    party.members[1].hp = 100
    party.members[3].hp = 300
    sm, ds = _dungeon(am, party, FIRE, (13, 5, 1))  # heal fountain
    calls = _drinks(monkeypatch, ds)
    ctrl = AutoPlayController(enabled=True)
    left_at = None
    for i in range(40):
        ctrl.step(sm)
        if (ds.state.x, ds.state.y, ds.state.z) != (13, 5, 1):
            left_at = i
            break
    assert sorted(idx for _t, idx in calls) == [1, 3]
    assert all(m.hp == m.max_hp for m in party.members)
    assert left_at is not None
    assert not ds.text_log.is_waiting_for_input or "drink" not in (ds.text_log.current_prompt or "").lower()


def test_never_drinks_acid_or_poison(am, monkeypatch):
    for at in ((14, 5, 1), (8, 5, 0)):  # acid, poison
        party = _party()
        party.members[1].hp = 100
        sm, ds = _dungeon(am, party, FIRE, at)
        calls = _drinks(monkeypatch, ds)
        ctrl = AutoPlayController(enabled=True)
        ds.state.fixture_due = True
        ds._run_fixture()  # the question is up, on the bad fountain
        assert "drink" in ds.text_log.current_prompt.lower()
        ctrl.step(sm)
        assert not ds.text_log.is_waiting_for_input
        for _ in range(30):
            ctrl.step(sm)
        assert not [c for c in calls if c[0] in (DungeonTile.FOUNTAIN_ACID,
                                                  DungeonTile.FOUNTAIN_POISON)]


def test_cure_fountain_cures_the_poisoned_only(am, monkeypatch):
    party = _party()
    party.members[2].status = Status.POISONED
    sm, ds = _dungeon(am, party, FIRE, (15, 5, 1))  # cure fountain
    calls = _drinks(monkeypatch, ds)
    ctrl = AutoPlayController(enabled=True)
    for _ in range(10):
        ctrl.step(sm)
    assert [idx for _t, idx in calls] == [2]
    assert party.members[2].status == Status.GOOD


def test_hurt_party_heals_at_a_fountain_before_leaving(am):
    """Hurt on level 2 (z 1) under the level's bar (276 of 950), on the way
    out: the heal fountain at (13, 5, 1) comes before the exit."""
    party = _party(marks=(1, 1, 0, 1))  # nothing wanted here: heading out
    for m in party.members:
        m.hp = 250
    sm, ds = _dungeon(am, party, FIRE, (11, 5, 1))
    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if all(m.hp == m.max_hp for m in party.members):
            break
    assert all(m.hp == m.max_hp for m in party.members)
    assert sm.current_screen is ds


def test_poisoned_member_walks_to_a_cure_fountain(am):
    party = _party(marks=(1, 1, 0, 1))
    party.members[0].status = Status.POISONED
    sm, ds = _dungeon(am, party, FIRE, (11, 5, 1))
    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if party.members[0].status == Status.GOOD:
            break
    assert party.members[0].status == Status.GOOD
    assert sm.current_screen is ds


# --- Item 2: a mark is a goal until every living member has it ----------------


def _surface(party):
    party.map_id = 0
    party.gold = 0
    for m in party.members:
        m.cards = [1, 1, 1, 1]
        m.gold = 0
    return party


def test_remaining_marks_need_every_living_member():
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    party = _surface(_party(marks=(1, 1, 1, 1)))
    party.members[2].marks[3] = 0  # the Cleric lacks Force
    assert evaluate_goal(party, 0) == Goal.GET_REMAINING_MARKS
    # A dead member's missing mark does not count.
    party.members[2].hp = 0
    party.members[2].status = Status.DEAD
    assert evaluate_goal(party, 17) != Goal.GET_REMAINING_MARKS


def test_unfixable_rod_does_not_send_the_party_in(am):
    """Loop guard: under 10 rations (and too broke for food) nobody can be
    made safe for the rod, so walking in would only walk out again."""
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    party = _surface(_party(marks=(1, 0, 0, 0)))
    for m in party.members:
        m.hp = 100  # 100 - 50 < max/2 for everyone
        m.mp = 0
        m.food = 5
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL


def test_weak_member_heals_at_a_fountain_and_comes_back_for_the_mark(am):
    """Fires of Hell level 8: the Fighter lacks Force (4, 10, 7) and would
    drop under half health; the Cleric has no MP. The heal fountain at
    (9, 7, 7) comes first, then the rod."""
    party = _party(marks=(1, 1, 0, 1))
    fighter = party.members[1]
    fighter.marks[3] = 0
    fighter.hp = 300  # of 950: 250 after the burn, under 475
    for m in party.members:
        m.mp = 0
        m.marks[2] = 1  # nothing else wanted
    sm, ds = _dungeon(am, party, FIRE, (4, 10, 7))
    ctrl = AutoPlayController(enabled=True)
    healed = False
    for _ in range(200):
        ctrl.step(sm)
        healed = healed or fighter.hp == fighter.max_hp
        if fighter.marks[3]:
            break
    assert healed and fighter.marks[3] > 0
    assert fighter.hp == fighter.max_hp - 50


# --- Item 3: deep-mark gate and the mark order ----------------------------------


def test_mark_table_matches_the_maps(am):
    """planner.MARK_DUNGEON / MARK_LEVEL are the maps' own mark tiles, and
    each mark has a heal fountain within one level (item 2's fallback)."""
    from py_exodus.autoplay.planner import MARK_DUNGEON, MARK_LEVEL

    tiles = {0: DungeonTile.MARK_KINGS, 1: DungeonTile.MARK_FIRE,
             2: DungeonTile.MARK_SNAKE, 3: DungeonTile.MARK_FORCE}
    for idx, dungeon in MARK_DUNGEON.items():
        dmap = load_map(dungeon, am)
        marks = AutoPlayController._find_dungeon_tiles(dmap, {tiles[idx]})
        assert min(z for *_xy, z in marks) == MARK_LEVEL[idx]
        heals = AutoPlayController._find_dungeon_tiles(dmap, {DungeonTile.FOUNTAIN_HEAL})
        assert any(abs(hz - MARK_LEVEL[idx]) <= 1 for *_xy, hz in heals)


def test_every_deep_mark_is_on_level_8(am):
    """Fire, Force and Snake sit on level 8 (z 7) in every dungeon that has
    them, so depth can't order them (user ruling: Fire and Force, then
    Snake)."""
    deep = {DungeonTile.MARK_FIRE, DungeonTile.MARK_FORCE, DungeonTile.MARK_SNAKE}
    for dungeon in range(14, 21):
        found = AutoPlayController._find_dungeon_tiles(load_map(dungeon, am), deep)
        assert all(z == 7 for *_xy, z in found)


def test_deep_mark_gate_is_level_9_for_level_8():
    """24 average Balron hits at z 7 (37 each at 950 max HP: ceiling
    (240 / 8 + 9) | 1 = 39, / 2 rounded up + 1 + 16) plus the 50 HP flee
    line is 938: level 9 (950 HP) holds it, level 8 (850) does not."""
    from py_exodus.autoplay.planner import deep_mark_min_level, dungeon_avg_hit

    assert dungeon_avg_hit(7, 950) == 37
    assert deep_mark_min_level(7) == 9
    assert all(deep_mark_min_level(z) >= 5 for z in range(8))


def test_deep_marks_wait_for_the_weakest_member():
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    party = _surface(_party(level=9, marks=(1, 0, 0, 0)))
    assert evaluate_goal(party, 0) == Goal.GET_REMAINING_MARKS
    cleric = party.members[2]
    cleric.level, cleric.max_hp = 8, 850  # the laggard (the user's wipe: 5/5/3/5)
    cleric.hp = cleric.max_hp
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL


def test_mark_order_fire_and_force_then_snake():
    """User ruling 2026-11-25: the Fires of Hell (17) while any living
    member lacks Fire or Force, then Snake (19); an old save missing only
    Snake goes straight to 19."""
    from py_exodus.autoplay.planner import next_mark_dungeon

    party = _party(marks=(1, 0, 0, 0))
    assert next_mark_dungeon(party) == 17
    for m in party.members:
        m.marks = [1, 1, 0, 1]
    party.members[3].marks[3] = 0  # the Wizard lacks Force
    assert next_mark_dungeon(party) == 17
    party.members[3].marks[3] = 1
    assert next_mark_dungeon(party) == 19
    party.members[0].marks = [1, 0, 1, 1]  # Snake but no Fire: back to 17
    assert next_mark_dungeon(party) == 17
    for m in party.members:
        m.marks = [1, 1, 1, 1]
    assert next_mark_dungeon(party) is None


# --- Item 5: turn-back thresholds -------------------------------------------------

SNAKE = 19  # no heal fountain above level 6 (z 5)


def test_turn_back_bars():
    """6 maximum hits of the hardest monster at the level, capped at 2/3 of
    max HP; staying needs half. Level 9 (950 HP) at z 7: Balron ceiling
    (30 + 9) | 1 = 39, max hit 39 + 1 + 16 = 56, x 6 = 336."""
    from types import SimpleNamespace

    from py_exodus.autoplay.planner import dungeon_hp_need, dungeon_hp_stay

    m9 = SimpleNamespace(max_hp=950)
    assert dungeon_hp_need(m9, 7) == 336 and dungeon_hp_stay(m9, 7) == 168
    m1 = SimpleNamespace(max_hp=150)
    assert dungeon_hp_need(m1, 0) == 100  # the 2/3 cap
    # Every bar sits under the 70% at which the surface rests indoors.
    for level in range(1, 26):
        m = SimpleNamespace(max_hp=level * 100 + 50)
        assert all(dungeon_hp_need(m, z) * 10 < m.max_hp * 7 for z in range(8))


def test_turn_back_hysteresis():
    """Under the next level's bar: turn back. Once turned back, a few HP
    more do not send the party down again; only the mark level's bar plus
    1/20 of max HP does."""
    from py_exodus.autoplay.planner import dungeon_may_resume, dungeon_turn_back

    party = _party()
    fighter = party.members[1]
    fighter.hp = 335  # need(z 4) at 950 max HP is 336
    assert dungeon_turn_back(party, 3, 7)
    fighter.hp = 336
    assert not dungeon_turn_back(party, 3, 7)
    assert not dungeon_may_resume(party, 7)  # 336 + 47 = 383 to go back down
    fighter.hp = 383
    assert dungeon_may_resume(party, 7)
    # On the mark's own level only the stay bar (half) counts.
    fighter.hp = 168
    assert not dungeon_turn_back(party, 7, 7)
    fighter.hp = 167
    assert dungeon_turn_back(party, 7, 7)


def test_hurt_party_turns_back_and_never_climbs_down_again(am):
    """Snake dungeon level 2 (z 1), every member under the bar for level 3,
    the Cleric out of MP, no heal fountain within a level: the party heads
    up and out, and never goes down a ladder on the way."""
    party = _party(marks=(1, 1, 0, 1))
    for m in party.members:
        m.hp = 250  # need(z 2) = 300
        m.mp = 0
    party.food = 500
    sm, ds = _dungeon(am, party, SNAKE, (11, 11, 1))
    ctrl = AutoPlayController(enabled=True)
    keys = []
    for _ in range(10):
        key = ctrl.step(sm)
        keys.append(key)
        if ds.state.z == 0:
            break
    assert pygame.K_d not in keys
    assert ds.state.z == 0


def test_turning_back_heals_on_the_spot_with_mp(am):
    party = _party(marks=(1, 1, 0, 1))
    fighter = party.members[1]
    fighter.hp = 250
    party.members[2].mp = 99
    sm, ds = _dungeon(am, party, SNAKE, (11, 11, 1))
    ctrl = AutoPlayController(enabled=True)
    for _ in range(10):
        ctrl.step(sm)
        if fighter.hp > 250:
            break
    assert fighter.hp > 250 and ds.state.z == 1


def test_healer_short_of_mp_waits_on_the_ladder_down(am):
    """Snake z 0, on the ladder down at (11, 11) with the Cleric at 5 MP:
    pass (no encounter roll on a ladder) until it holds two Sanctus."""
    party = _party(marks=(1, 1, 0, 1))
    cleric = party.members[2]
    assert cleric.max_mp >= 20
    cleric.mp = 5
    sm, ds = _dungeon(am, party, SNAKE, (11, 11, 0))
    ds.state.torchtime = 255  # lit: no Ignite first
    ctrl = AutoPlayController(enabled=True)
    for _ in range(3):
        assert ctrl.step(sm) == pygame.K_SPACE and ds.state.z == 0
    cleric.mp = 20
    for _ in range(4):
        ctrl.step(sm)
    assert ds.state.z == 1


def test_surface_rests_before_entering_a_mark_dungeon_under_the_bar(am, monkeypatch):
    from py_exodus.autoplay.planner import Goal
    from py_exodus.screens.overworld import OverworldScreen

    party = _surface(_party(marks=(1, 0, 0, 0)))
    party.x, party.y = 44, 20
    for m in party.members:
        m.hp = m.max_hp * 3 // 4  # over the 70% rest line ...
    party.members[1].hp = 250  # ... but the Fighter is under need(z 1) = 276
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters=False)
    ow.creatures = []
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    rested = []
    monkeypatch.setattr(ctrl, "_rest_destination",
                        lambda *_a: rested.append(1) or (None, None))
    monkeypatch.setattr(ctrl, "_evade_or_rest", lambda *_a, **_k: None)
    ctrl._step_overworld(sm, ow, party, 44, 20, Goal.GET_REMAINING_MARKS)
    assert rested


# --- Item 7: Ambrosia as soon as the gold is there ----------------------------------


def test_ambrosia_monster_table_matches_the_map(am):
    """planner.AMBROSIA_MONSTERS is the table Ambrosia loads every visit."""
    from py_exodus.autoplay.planner import AMBROSIA_MONSTERS
    from py_exodus.screens.overworld import OverworldScreen

    dmap = load_map(13, am)
    loaded = sorted(
        (OverworldScreen._AMBROSIA_MONSTER_TILES[n.tile_index], n.x, n.y)
        for n in dmap.npcs
        if getattr(n, "tile_index", -1) in OverworldScreen._AMBROSIA_MONSTER_TILES
    )
    assert loaded == sorted(AMBROSIA_MONSTERS)


def _trip_party(level: int = 6, gold: int = 6000):
    """Kings and exotics, no other mark, no card, fed, 8 keys."""
    party = _party(level=level, marks=(1, 0, 0, 0))
    party.map_id = 0
    for m in party.members:
        m.keys = 2
        m.food = 300
    party.gold = gold
    return party


def test_ambrosia_threats_follow_the_route():
    from py_exodus.autoplay.planner import ambrosia_route, ambrosia_threats

    party = _trip_party()
    route = ambrosia_route(party)
    assert route[0] == (32, 54) and route[-1] == (32, 58)
    assert {(55, 27), (45, 52), (6, 6), (4, 36)} <= set(route)
    assert {"balron", "daemon", "thief"} <= set(ambrosia_threats(route))
    # Only the Dexterity shrine (45, 52): the pincher at (38, 58) and a
    # pirate, nothing from the far side of the island.
    short = [(32, 54), (45, 52), (32, 58)]
    assert ambrosia_threats(short) == ["pincher", "thief"]


def test_ambrosia_strength_gate():
    """8 average hits on Ambrosia (+48 a hit) plus the flee line: a Balron
    on the route needs 594 max HP at level 6 (ceiling (30 + 6) | 1 = 37:
    19 + 1 + 48 = 68 a hit), so level 5 (550) waits and 6 (650) goes."""
    from py_exodus.autoplay.planner import ambrosia_hp_need, ambrosia_ready

    assert ambrosia_hp_need("balron", 650) == 594
    assert not ambrosia_ready(_trip_party(level=5))
    assert ambrosia_ready(_trip_party(level=6))


def test_ambrosia_before_the_marks_once_the_gold_is_there():
    from py_exodus.autoplay.planner import Goal, ambrosia_trip_gold, evaluate_goal

    party = _trip_party()
    assert party.gold >= ambrosia_trip_gold(party)
    assert evaluate_goal(party, 0) == Goal.SAIL_WHIRLPOOL
    # Short of the gold: the mark plan (here the level-9 grind) as before.
    party.gold = ambrosia_trip_gold(party) - 1
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
    # Keys and food first, as the card trip always did.
    party = _trip_party()
    party.members[0].keys = 0
    assert evaluate_goal(party, 0) == Goal.BUY_KEYS
    # Never out of a mark dungeon for it, and never before Kings.
    party = _trip_party()
    assert evaluate_goal(party, 17) != Goal.SAIL_WHIRLPOOL
    party.members[2].marks[0] = 0
    assert evaluate_goal(party, 0) != Goal.SAIL_WHIRLPOOL


def test_ambrosia_waits_for_the_weakest_member():
    from py_exodus.autoplay.planner import Goal, evaluate_goal

    party = _trip_party()
    cleric = party.members[2]
    cleric.level, cleric.max_hp = 4, 450
    cleric.hp = 450
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL


def test_a_second_ambrosia_trip_after_the_first():
    """Back from a first trip (all cards, part of the stats bought, gold
    spent): the mark plan resumes; with the gold again, a second trip."""
    from py_exodus.autoplay.planner import Goal, ambrosia_trip_gold, evaluate_goal

    party = _trip_party(gold=400)
    for m in party.members:
        m.cards = [1, 1, 1, 1]
    party.members[2].wisdom = 60  # the plan's first steps are not all done
    assert evaluate_goal(party, 0) == Goal.GRIND_AND_LEVEL
    party.gold = ambrosia_trip_gold(party)
    assert evaluate_goal(party, 0) == Goal.SAIL_WHIRLPOOL
    # The plan done (every return-trip step met): no trip, whatever the gold.
    from tests.test_autoplay import _max_shrine_stats

    _max_shrine_stats(party)
    party.gold = 9000
    assert evaluate_goal(party, 0) != Goal.SAIL_WHIRLPOOL


def test_a_slightly_hurt_party_does_not_detour_to_a_heal_fountain(am):
    """A few HP short (90%) is no real need: no detour to (13, 5, 1)."""
    party = _party(marks=(1, 1, 0, 1))
    for m in party.members:
        m.hp = m.max_hp * 9 // 10
    sm, ds = _dungeon(am, party, FIRE, (11, 5, 1))
    ds.state.torchtime = 255
    ctrl = AutoPlayController(enabled=True)
    for _ in range(30):
        ctrl.step(sm)
        assert (ds.state.x, ds.state.y, ds.state.z) != (13, 5, 1)


def test_poisoned_party_cures_instead_of_pacing_to_a_heal_fountain(am):
    """Live trace 2026-11-25 (trace_20261125-173226, ~5,000 steps): Fires of
    Hell z 4, the whole party poisoned at ~97% HP, the Cleric at 4 MP, Fire
    held and Force wanted. It walked to the heal fountain (1, 1, 4), drank,
    walked toward the mark, lost a few HP to poison and went back. Now it
    goes to the nearest cure fountain (any level) and never paces."""
    party = _party(marks=(1, 1, 0, 0))
    for m in party.members:
        m.status = Status.POISONED
        m.hp = m.max_hp - 34  # 916 of 950, as in the trace
        m.mp = 0
    party.members[2].mp = 4
    sm, ds = _dungeon(am, party, FIRE, (1, 4, 4))
    ds.state.torchtime = 255
    ctrl = AutoPlayController(enabled=True)
    visits, was_on = 0, False
    for _ in range(600):
        ctrl.step(sm)
        for m in party.members:  # poison and the fights on the way (trace)
            if m.status == Status.POISONED:
                m.hp -= 2
        on = (ds.state.x, ds.state.y, ds.state.z) == (1, 1, 4)
        visits += on and not was_on
        was_on = on
        if all(m.status == Status.GOOD for m in party.members):
            break
    assert visits <= 1
    assert all(m.status == Status.GOOD for m in party.members)


def test_poison_cured_by_alcort_when_the_cleric_has_35_mp(am):
    party = _party(marks=(1, 1, 0, 0))
    party.members[0].status = Status.POISONED
    party.members[2].mp = 35
    sm, ds = _dungeon(am, party, FIRE, (1, 4, 4))
    ds.state.torchtime = 255
    ctrl = AutoPlayController(enabled=True)
    for _ in range(6):
        ctrl.step(sm)
        if party.members[0].status == Status.GOOD:
            break
    assert party.members[0].status == Status.GOOD
