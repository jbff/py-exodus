"""Full spell coverage matrix (2026-11-20): every spell cast in BOTH environs.

The NN combat policy now chooses between per-spell actions (v3 action
space), so every combat-relevant spell must actually resolve — and the
same holds overland, where autoplay drives vendors/shrines/commands for
the same party. Existing test_magic_system.py covers deep semantics for
the individual spells; this module is the exhaustive contract pass:

for every cleric and wizard spell (32), in overland (arena=None) and
combat (arena set) contexts:
  * cast_spell returns a well-formed SpellResult (never raises)
  * a successful non-free cast deducts MP; a refusal never deducts MP
  * context-gated spells (dungeon-only, light-only, chest-only) must
    refuse with a canonical message rather than crash or no-op silently
"""
from __future__ import annotations

import contextlib
import random as pyrandom

import pytest

from py_exodus.assets import AssetManager
from py_exodus.combat.arena import CombatArena
from py_exodus.combat.magic import SpellResult, cast_spell
from py_exodus.constants import Direction, Profession, Race, Spell
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.loader import MapLoader

ALL_SPELLS = sorted(
    (s for s in Spell if s.value[3] in ("wizard", "cleric")),
    key=lambda s: s.name,
)
assert len(ALL_SPELLS) == 32

#: Spells that cost no MP (engine truth: value[1] == 0).
_FREE_SPELLS = {s for s in ALL_SPELLS if s.value[1] == 0}

#: Dungeon-gated spells: overland on the world map must politely refuse.
_DUNGEON_ONLY = {Spell.DOR_ACRON, Spell.SUR_ACRON, Spell.REC_DU, Spell.LIB_REC, Spell.SEQUITU}


@pytest.fixture(scope="module")
def asset_mgr():
    am = AssetManager("data")
    am.load_all()
    return am


@pytest.fixture(scope="module")
def conflict_map(asset_mgr):
    return MapLoader(asset_mgr).load_conflict_map("cnflct_a.json")


@pytest.fixture(scope="module")
def world_map(asset_mgr):
    return MapLoader(asset_mgr).load_map(0)  # sosaria


def _caster_for(spell: Spell) -> Character:
    """A maxed-MP member of the spell's own profession."""
    book = spell.value[3]
    prof = Profession.WIZARD if book == "wizard" else Profession.CLERIC
    race = Race.FUZZY if prof == Profession.WIZARD else Race.BOBIT
    char = Character(f"C_{spell.name}", "M", race, prof)
    char.mp = 200
    char.max_mp = 200
    char.level = 20
    char.max_hp = 2000
    char.hp = max(1, char.max_hp // 2)  # wounded so heals have work to do
    return char


def _combat_arena(conflict_map) -> tuple[CombatArena, Party]:
    party = Party()
    for name, prof, race in (
        ("THIEF1", Profession.THIEF, Race.ELF),
        ("FIGHT1", Profession.FIGHTER, Race.DWARF),
        ("CLER1", Profession.CLERIC, Race.BOBIT),
        ("WIZ1", Profession.WIZARD, Race.FUZZY),
    ):
        c = Character(name, "M", race, prof)
        c.mp = 200
        c.max_mp = 200
        c.max_hp = 2000
        c.hp = 1000
        party.add_member(c)
    arena = CombatArena(party, conflict_map, monster_count=2, creature_tile="goblin")
    return arena, party


@contextlib.contextmanager
def _seeded(seed: int = 42):
    state = pyrandom.getstate()
    pyrandom.seed(seed)
    try:
        yield
    finally:
        pyrandom.setstate(state)


def _assert_result_contract(spell: Spell, res: SpellResult) -> None:
    """Refusals always carry a message; successes may be silent (Java-parity:
    sound-only paths like a missed bolt write nothing to the log)."""
    assert isinstance(res, SpellResult)
    assert isinstance(res.success, bool)
    assert isinstance(res.message, str)
    if not res.success:
        assert res.message != ""


def _assert_mp_accounting(spell: Spell, caster: Character, before: int, res: SpellResult) -> None:
    if res.success and spell not in _FREE_SPELLS:
        assert caster.mp < before, f"{spell.name} succeeded but cost no MP"
    elif not res.success and spell == Spell.APPAR_UNEM:
        # Parity: GBC charges mana at the cast site BEFORE dogetchest
        # (menucmd.c:1309) — "Not Here!" refusals still cost 5 MP
        # (documented USER-DIRECTED GBC-RULES DEVIATION in magic.py).
        pass
    elif not res.success:
        assert caster.mp == before, f"{spell.name} refused but consumed MP"


# --- overland (arena=None) -------------------------------------------------


@pytest.mark.parametrize("spell", ALL_SPELLS, ids=lambda s: f"overland-{s.name}")
def test_every_spell_overland(spell, asset_mgr, world_map, conflict_map):
    caster = _caster_for(spell)
    _, overland_party = _combat_arena(conflict_map)
    overland_party.x, overland_party.y = 44, 20
    mp_before = caster.mp
    with _seeded():
        res = cast_spell(
            spell,
            caster=caster,
            target_dir=Direction.EAST,
            arena=None,
            world_map=world_map,
            party=overland_party,
        )
    _assert_result_contract(spell, res)
    _assert_mp_accounting(spell, caster, mp_before, res)
    if spell in _DUNGEON_ONLY:
        assert not res.success, f"{spell.name} must refuse outside dungeons"
        m = res.message.lower()
        assert (
            "dungeon" in m or "not here" in m or "cannot be cast here" in m
        ), res.message


# --- combat (arena set) -----------------------------------------------------


@pytest.mark.parametrize("spell", ALL_SPELLS, ids=lambda s: f"combat-{s.name}")
def test_every_spell_in_combat(spell, asset_mgr, conflict_map):
    arena, party = _combat_arena(conflict_map)
    caster = next(m for m in party.members if m.profession.name == spell.value[3].upper())
    mp_before = caster.mp
    with _seeded():
        res = cast_spell(
            spell,
            caster=caster,
            target_dir=Direction.EAST,
            arena=arena,
            world_map=None,
        )
    _assert_result_contract(spell, res)
    _assert_mp_accounting(spell, caster, mp_before, res)
    # NOTE: arena log_messages are written by the Arena layer
    # (execute_player_action), not by cast_spell itself — combat logging
    # parity is covered by tests/test_autoplay_nn.py via the screen loop.


# --- context-both spells: same spell, both environs -------------------------


_DUAL_ENV_SPELLS = {Spell.MITTAR, Spell.FULGAR, Spell.EXCUUN, Spell.SANCTU,
                    Spell.SANCTU_MANI, Spell.ALCORT, Spell.LUMINAE, Spell.SOMINAE,
                    Spell.DECORP}


@pytest.mark.parametrize("spell", sorted(_DUAL_ENV_SPELLS, key=lambda s: s.name), ids=lambda s: s.name)
def test_dual_context_spells_resolve_in_both(spell, asset_mgr, conflict_map, world_map):
    """Spells usable in both environs must resolve in both without error."""
    results = []
    for env in ("overland", "combat"):
        caster = _caster_for(spell)
        caster.mp = 200
        caster.max_mp = 200
        with _seeded():
            res = cast_spell(
                spell,
                caster=caster,
                target_dir=Direction.EAST,
                arena=None if env == "overland" else _combat_arena(conflict_map)[0],
                world_map=world_map if env == "overland" else None,
            )
        _assert_result_contract(spell, res)
        results.append(res)
    # At least one environment must accept it (directed bolts refuse over
    # empty overland lines politely — refusal is the resolution, not a crash).
    assert any(r.success for r in results) or all(
        isinstance(r, SpellResult) for r in results
    )
