"""Unit tests for Phase 1 combat state encoder, action space, and legality mask."""
from __future__ import annotations

from types import SimpleNamespace

from py_exodus.combat.arena import Action, ActionType
from py_exodus.constants import Direction, Profession, Race, Spell, Status, TileAttrib, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.combat_env import (
    COMBAT_CONTEXT_DIM,
    COMBAT_GRID_CHANNELS,
    NUM_COMBAT_ACTIONS,
    action_to_index,
    encode_combat_state,
    index_to_action,
    legal_action_mask,
)


def _stub_arena(monster_pos=(5, 4), wall_north=False):
    p = Party()
    p.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, gold=200, food=100))
    p.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, gold=200, food=100))
    p.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, gold=200, food=100))
    p.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, gold=200, food=100))
    for m in p.members:
        m.hp = m.max_hp = 200
        m.mp = m.max_mp = 50

    def _tile(x: int, y: int):
        if wall_north and (x, y) == (5, 4):
            return SimpleNamespace(name="wall", attribs=TileAttrib.UNWALKABLE)
        return SimpleNamespace(name="grass", attribs=TileAttrib.NONE)

    cmap = SimpleNamespace(width=11, height=11, get_tile=_tile)
    mon = SimpleNamespace(
        x=monster_pos[0],
        y=monster_pos[1],
        hp=40,
        max_hp=40,
        visible=True,
        is_dead=False,
        ranged=False,
        magic=False,
        poisonous=False,
        tile="orc",
        exp=10,
    )
    arena = SimpleNamespace(
        party=p,
        combat_map=cmap,
        player_positions={0: (5, 5), 1: (4, 5), 2: (6, 5), 3: (5, 6)},
        monsters=[mon],
        turn_count=3,
        magic_negated=False,
        magic_negated_turns=0,
    )
    return arena


def test_encode_combat_state_grid_shape():
    arena = _stub_arena()
    grid, _ = encode_combat_state(arena, 0)
    assert (len(grid), len(grid[0]), len(grid[0][0])) == (COMBAT_GRID_CHANNELS, 11, 11)


def test_encode_combat_state_context_dim():
    arena = _stub_arena()
    _, ctx = encode_combat_state(arena, 0)
    assert len(ctx) == COMBAT_CONTEXT_DIM


def test_legal_action_mask_blocks_unwalkable_move_and_allows_melee():
    arena = _stub_arena(monster_pos=(5, 4), wall_north=True)
    mask = legal_action_mask(arena, 0)
    assert mask[0] is False  # MOVE NORTH blocked by wall


def test_legal_action_mask_allows_adjacent_melee_attack():
    arena = _stub_arena(monster_pos=(5, 4), wall_north=False)
    mask = legal_action_mask(arena, 0)
    assert mask[4] is True  # ATTACK NORTH


def test_action_index_roundtrip_attack_east():
    arena = _stub_arena()
    idx = action_to_index(Action.attack(Direction.EAST))
    act = index_to_action(idx, arena, 0)
    assert (act.type, act.direction) == (ActionType.ATTACK, Direction.EAST)


def test_mask_heals_require_a_wounded_target():
    """Livelock regression (2026-11-20 pirate ship): engine REFUSES heals on
    a full-health target without advancing the turn, so a masked-legal heal
    on a healthy party produced an endless cast-refuse-cast loop. Heals are
    only legal when someone is actually wounded."""
    from py_exodus.nn.combat_env import SPELL_ACTION_INDEX

    arena = _stub_arena()  # everyone at full HP
    mask = legal_action_mask(arena, 2)  # SERENA, cleric with MP
    sanctu = SPELL_ACTION_INDEX[Spell.SANCTU]
    sanctu_mani = SPELL_ACTION_INDEX[Spell.SANCTU_MANI]
    assert mask[sanctu] is False and mask[sanctu_mani] is False


def test_mask_heals_allowed_when_ally_is_wounded():
    from py_exodus.nn.combat_env import SPELL_ACTION_INDEX

    arena = _stub_arena()
    arena.party.members[0].hp = 100  # 50% wounded
    mask = legal_action_mask(arena, 2)  # SERENA, cleric with MP
    sanctu = SPELL_ACTION_INDEX[Spell.SANCTU]
    sanctu_mani = SPELL_ACTION_INDEX[Spell.SANCTU_MANI]
    assert mask[sanctu] is True and mask[sanctu_mani] is True


def test_mask_cure_requires_poisoned_ally():
    from py_exodus.nn.combat_env import SPELL_ACTION_INDEX

    arena = _stub_arena()
    mask = legal_action_mask(arena, 2)
    assert mask[SPELL_ACTION_INDEX[Spell.ALCORT]] is False

    arena.party.members[1].status = Status.POISONED
    mask = legal_action_mask(arena, 2)
    assert mask[SPELL_ACTION_INDEX[Spell.ALCORT]] is True


def test_legal_action_mask_length_matches_num_actions():
    arena = _stub_arena()
    assert len(legal_action_mask(arena, 0)) == NUM_COMBAT_ACTIONS
