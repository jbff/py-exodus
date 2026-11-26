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
