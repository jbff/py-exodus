"""Batch 1 bugs at bdbd73a (seeds 1-10): a member starving while the others
have food (seed 3), the shop prompt loop with an incapacitated buyer (seed
3) and the capture stall on the Death Gulch strip (seeds 8 and 2).

The canonical party only (batch.build_party)."""
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

FIRE = 17


@pytest.fixture(scope="module")
def am():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    mgr = AssetManager("data")
    mgr.load_all()
    yield mgr


def _party(level: int = 14, food=(100, 100, 100, 100), gold: int = 1300):
    party = build_party()
    for m, f in zip(party.members, food):
        m.level = level
        m.max_hp = m.hp = level * 100 + 50
        m.marks = [1, 1, 0, 1]
        m.cards = [0, 0, 0, 0]
        m.weapons[WeaponType.EXOTIC] = 1
        m.weapon = WeaponType.EXOTIC
        m.armors[ArmorType.EXOTIC] = 1
        m.armor = ArmorType.EXOTIC
        m.food = f
        m.gold = gold
        m.torches = 5
    return party


# --- Item 1: one member starves while the others have food ----------------


def test_food_hand_off_feeds_the_member_at_zero():
    """LairWare HandEquip 'F' (UltimaMain.c:1791-1814) moves food between any
    two members: the one at 0 gets half the difference from the fullest."""
    party = _party(food=(100, 0, 100, 100))
    assert food_hand_off(party) == (1, 2, 50)


def test_food_hand_off_feeds_a_dead_member_before_resurrection():
    """HandEquip checks only that both slots hold a character
    (``Player[..][17]``, UltimaMain.c:1757-1783), so the dead take food too:
    a member raised at 0 food and 0 HP dies again on the next food tick
    (EatFood, UltimaMisc.c:1468-1486; seed 3 died ~30 times that way)."""
    party = _party(food=(87, 0, 87, 395))
    party.members[1].status = Status.DEAD
    party.members[1].hp = 0
    assert food_hand_off(party) == (4, 2, 197)


def test_food_hand_off_living_first_and_no_ping_pong():
    party = _party(food=(30, 0, 5, 30))
    party.members[1].status = Status.DEAD
    # The living Cleric at 5 is fed before the dead Fighter.
    assert food_hand_off(party) == (1, 3, 12)
    party = _party(food=(10, 10, 10, 10))
    assert food_hand_off(party) is None
    party = _party(food=(15, 0, 0, 0))  # not enough to spare: no hand-off
    assert food_hand_off(party) is None


def test_dungeon_starving_member_is_fed_before_anything_else(am):
    """Seed 3, step 39,491: in the Fires of Hell on GET_REMAINING_MARKS with
    food [100, 0, 100, 0]. The Fighter and the Wizard are fed by H at once."""
    from py_exodus.screens.dungeon_screen import DungeonScreen

    random.seed(7)
    party = _party(food=(100, 0, 100, 0))
    party.map_id = FIRE
    dmap = load_map(FIRE, am)
    sm = StateMachine(asset_mgr=am, audio=None)
    ds = DungeonScreen(party=party, dungeon_map=dmap, asset_mgr=am, map_id=FIRE)
    ds.state.random_encounters_enabled = False
    ds.state.rng.seed(7)
    ds.state.x, ds.state.y, ds.state.z = 1, 9, 0
    sm.set_screen(ds)

    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame.K_h
    for _ in range(30):
        if all(m.food > 0 for m in party.members):
            break
        ctrl.step(sm)
    assert all(m.food >= 10 for m in party.members)
    assert sum(m.food for m in party.members) == 200


def test_dead_member_is_fed_before_the_healer_raises_them(am):
    """Seed 3, step 40,255: Castle British's healer with the Fighter dead at
    0 food. Fed first, the raised Fighter survives the next moves."""
    from py_exodus.screens.town import TownScreen

    random.seed(3)
    party = _party(food=(87, 0, 87, 395))
    fighter = party.members[1]
    fighter.status = Status.DEAD
    fighter.hp = 0
    party.map_id = 1
    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=1, start_x=44, start_y=26)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    raised_at = None
    for i in range(200):
        ctrl.step(sm)
        if raised_at is None and fighter.status != Status.DEAD:
            raised_at = i
        if raised_at is not None and i - raised_at > 40:
            break
    assert raised_at is not None
    assert fighter.status != Status.DEAD
    assert fighter.food > 0


def food_hand_off(party):
    from py_exodus.autoplay.equipment import food_hand_off as f

    return f(party)


# --- Item 2: the shop prompt loop with an incapacitated buyer -------------


def test_food_buyer_is_never_an_incapacitated_member(am):
    """Seed 3, step 92,735: at Britain's grocer with the Fighter in ashes
    and 0 food. The cheapest-fed member was picked to buy, but LairWare
    Transact talks only through a living member (UltimaMain.c:2302-2305,
    "Incapacitated!"): Talk, the Fighter, refused, ~44,000 steps, starved."""
    from py_exodus.screens.town import TownScreen

    random.seed(3)
    party = _party(food=(15, 0, 15, 15), gold=128)
    party.members[1].status = Status.ASH
    party.members[1].hp = 0
    party.map_id = 3
    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=3, start_x=44, start_y=47)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    for _ in range(80):
        ctrl.step(sm)
        if any(m.food > 15 for m in party.members if not m.is_disabled()):
            break
    assert any(m.food > 15 for m in party.members if not m.is_disabled())
    history = " ".join(str(x) for x in getattr(ts.text_log, "history", ()) or ())
    assert "Incapacitated" not in history


def test_last_living_member_buys_food_beside_the_ashes(am):
    """Seed 3, step 134,766: the Thief alone alive with 15 food and 15 gold,
    the Fighter in ashes, the others dead. The Fighter (0 food) was still
    picked to Transact, so the Thief starved beside the grocer."""
    from py_exodus.screens.town import TownScreen

    random.seed(3)
    party = _party(food=(15, 0, 0, 0), gold=0)
    party.members[0].gold = 15
    party.members[1].status = Status.ASH
    for m in party.members[1:]:
        m.hp = 0
    for m in party.members[2:]:
        m.status = Status.DEAD
    party.map_id = 3
    sm = StateMachine(asset_mgr=am, audio=None)
    ts = TownScreen(party=party, asset_mgr=am, map_id=3, start_x=44, start_y=47)
    sm.set_screen(ts)

    ctrl = AutoPlayController(enabled=True)
    # The trace's goal was GRIND_AND_LEVEL; the grocer visit ran on the
    # target its last BUY_FOOD had set, still standing.
    ctrl._food_shop_target = 150
    for _ in range(80):
        ctrl.step(sm)
        if party.members[0].food > 15:
            break
    assert party.members[0].food > 15


# --- Item 3: stranded on Death Gulch's strip --------------------------------


def _strip_party(food: int):
    party = _party(level=25, food=(food,) * 4, gold=1244)
    for m in party.members:
        m.max_hp = m.hp = 2550
        m.marks = [1, 1, 1, 1]
        m.cards = [1, 1, 1, 1]
        m.keys = 5
    party.x, party.y = 58, 40
    return party


def test_stranded_on_death_gulchs_strip_buys_food_in_death_gulch(am):
    """Seed 8 at bdbd73a: back out of Death Gulch at (56, 31) with no ship
    (the one parked at (59, 40) was gone). The strip (55-58, 31-40) is
    walled by water and mountains; its gate (58, 31) sits in a mountain
    pocket with a dungeon, so the only way off is a captured ship. The
    capture waited ~3,000 turns for a pirate that never came (LairWare's
    MoveMonsters steps greedily and a pirate snags on the coast) and the
    party starved with 4,976 gold, Death Gulch's grocer (52, 35) a few
    steps away. BUY_FOOD from the strip now goes there."""
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.town import TownScreen

    random.seed(8)
    party = _strip_party(food=60)
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = []
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    entered = None
    for _ in range(400):
        ctrl.step(sm)
        scr = sm.current_screen
        if isinstance(scr, TownScreen) and entered is None:
            entered = getattr(scr, "map_id", None)
        if min(m.food for m in party.members) >= 150:
            break
    assert entered == 10
    assert min(m.food for m in party.members) >= 150


def test_mainland_food_runs_never_pick_death_gulch(am):
    """Only a party on the strip shops there: from Britain the grocer is
    Britain's or Yew's, as before."""
    from py_exodus.screens.overworld import OverworldScreen

    party = _strip_party(food=60)
    party.x, party.y = 44, 20
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = []
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    ctrl.step(sm)
    assert ctrl._trip is not None
    assert (56, 31) not in ctrl._trip.dest.tiles


def test_capture_never_waits_for_a_snagged_pirate(am):
    """Seed 8 at bdbd73a, step 78,613: on the strip at (58, 40), BUY_KEYS,
    the only way off a captured ship. A pirate south of the strip snags at
    (58, 48) (LairWare MoveMonsters tries the diagonal, vertical and then
    horizontal step toward the party and stays put when all are land,
    UltimaMisc.c:1191-1236). The hunt saw it stall and tried to dash, but
    no foot route reaches a tile beside it, so it fell through to "it is
    coming" and passed turns, ~3,000 of them, until the party starved.
    A stalled hunt with no dash leaves that pirate alone for a while and
    patrols the coast, which also changes the pirate's heading."""
    from py_exodus.screens.overworld import OverworldScreen

    random.seed(8)
    party = _strip_party(food=300)
    for m in party.members:
        m.keys = 0
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = [{"x": 58, "y": 48, "tile_name": "pirate"}]
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    run = longest = 0
    seen = set()
    for _ in range(120):
        key = ctrl.step(sm)
        seen.add((party.x, party.y))
        if key == pygame.K_SPACE:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    assert longest <= 10, longest
    assert len(seen) >= 4


@pytest.mark.parametrize("keys", [0, 1])
def test_strip_food_run_without_two_keys_never_loops_through_the_gate(am, keys):
    """Review of 0bf9623 (Critical 1): with under 2 keys the Death Gulch
    way stops at its first locked door, the party walks out, BUY_FOOD
    sends it back to the gate, and the town resets: 745 entries in 1,500
    steps with 0 keys, 377 in 800 with 1. Death Gulch is the strip's food
    run only with 2 keys (its two doors) and the bribe gold."""
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.screens.town import TownScreen

    random.seed(8)
    party = _strip_party(food=60)
    for m in party.members:
        m.keys = 0
    party.members[0].keys = keys
    sm = StateMachine(asset_mgr=am, audio=None)
    ow = OverworldScreen(party=party, asset_mgr=am, random_encounters_enabled=False)
    ow.creatures = []
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    entries = 0
    was_town = False
    for _ in range(400):
        ctrl.step(sm)
        is_town = isinstance(sm.current_screen, TownScreen)
        if is_town and not was_town:
            entries += 1
        was_town = is_town
    assert entries <= 1, entries

