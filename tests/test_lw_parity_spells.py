"""LairWare parity, batch P (spells): pins LairWare spell rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "P - Spells".
"""
from __future__ import annotations

import pytest

import py_exodus.combat.magic as magic
from py_exodus.combat.arena import Action, CombatArena
from py_exodus.combat.magic import cast_spell
from py_exodus.constants import Direction, Profession, Spell, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.loader import MapLoader


def _caster(profession=Profession.WIZARD, intelligence=50, wisdom=50, mp=99) -> Character:
    return Character(
        "Mage", "M", profession=profession, intelligence=intelligence,
        wisdom=wisdom, hp=900, max_hp=900, mp=mp, max_mp=99,
    )


def _board(asset_mgr, creature="orc", count=1, caster=None) -> CombatArena:
    """A fight on an all-grass arena: the caster at (5, 10), monsters lined
    up north of it on column 5 (the first one at (5, 2))."""
    party = Party(transport=Transport.FOOT)
    party.add_member(caster or _caster())
    cmap = MapLoader(asset_mgr).load_conflict_map("cnflct_g.json")
    grass = asset_mgr.tile_defs_by_name["grass"]
    for y in range(11):
        for x in range(11):
            cmap.set_tile(x, y, grass)
    arena = CombatArena(party, cmap, creature_tile=creature, asset_mgr=asset_mgr, monster_count=count)
    arena.player_positions[0] = (5, 10)
    m = party.members[0]
    m.combat_x, m.combat_y = 5, 10
    for i, mon in enumerate(arena.monsters):
        mon.x, mon.y = 5, 2 + i
        mon.hp = 200
    return arena


def _cast(arena, spell, direction=None):
    return cast_spell(spell, arena.party.members[0], target_dir=direction, arena=arena, party=arena.party)


def _randint(monkeypatch, value, calls=None):
    def fake(a, b):
        if calls is not None:
            calls.append((a, b))
        return value
    monkeypatch.setattr(magic.random, "randint", fake)


def _randrange(monkeypatch, values):
    seq = iter(values)
    monkeypatch.setattr(magic.random, "randrange", lambda n: next(seq))


# --- P-01..P-04: Projectile damage -------------------------------------------


def test_spell_mittar_damage_is_randnum_0_40_or_0x10(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:203:

        case 1: /* Mittar */ Projectile(chnum, RandNum(0, 40) | 0x10); break;

    A roll of 32 gives 32 | 16 = 48 damage (the range is 16-31 and 48-56).
    """
    arena = _board(asset_mgr)
    calls: list = []
    _randint(monkeypatch, 32, calls)
    res = _cast(arena, Spell.MITTAR, Direction.NORTH)
    assert (0, 40) in calls
    assert res.damage == 48
    assert arena.monsters[0].hp == 152


def test_spell_fulgar_damage_is_75(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:208: `case 5: /* Fulgar */ Projectile(chnum, 75);`
    A fixed 75, no roll and no fire resistance."""
    arena = _board(asset_mgr)
    _randint(monkeypatch, 40)
    res = _cast(arena, Spell.FULGAR, Direction.NORTH)
    assert res.damage == 75
    assert arena.monsters[0].hp == 125


def test_spell_mentar_damage_is_the_casters_int(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:224:
    `case 7: /* Mentar */ Projectile(chnum, Player[rosNum][20]); break;`
    Player[20] is INT: the damage is exactly the caster's INT."""
    arena = _board(asset_mgr, caster=_caster(intelligence=77))
    _randint(monkeypatch, 33)
    res = _cast(arena, Spell.MENTAR, Direction.NORTH)
    assert res.damage == 77
    assert arena.monsters[0].hp == 123


@pytest.mark.parametrize("spell", [Spell.DECORP, Spell.EXCUUN])
def test_spell_decorp_excuun_damage_255_kills(asset_mgr, monkeypatch, spell):
    """UltimaSpellCombat.c:236 and 344:

        case 11: /* Decorp */ Projectile(chnum, 255); break;
        case 28: /* Excuun */ Projectile(chnum, 255); break;

    DamageMonster (734-756) kills when `MonsterHP - damage < 1`; no monster
    holds more than 255, so a hit always kills (Excuun rolled 64-255 in Java).
    """
    arena = _board(asset_mgr, caster=_caster(Profession.CLERIC) if spell == Spell.EXCUUN else None)
    arena.monsters[0].hp = 239
    _randint(monkeypatch, 64)
    _cast(arena, spell, Direction.NORTH)
    assert arena.monsters[0].hp == 0


def test_damagemonster_spares_lord_british(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:738: `if (gMonType != 0x26) { /* not Lord British,
    har har */` - DamageMonster does nothing to Lord British, so a spell
    (Decorp's 255, BigDeath) cannot hurt him either."""
    arena = _board(asset_mgr, creature="lord_british")
    _cast(arena, Spell.DECORP, Direction.NORTH)
    assert arena.monsters[0].hp == 200
    _randrange(monkeypatch, [1] * 8)
    _cast(arena, Spell.UNSPEAKABLE)
    assert arena.monsters[0].hp == 200


# --- P-05, P-06: BigDeath -----------------------------------------------------


def test_bigdeath_noxum_75_on_three_in_four(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:233 and 475-495:

        case 10: /* Noxum */ BigDeath(75, chnum); break;
        ...
        if ((RandNum(0, 255) & 0x03) != 0) {
            if (MonsterHP[mon] != 0) { ... DamageMonster(mon, damage, chnum);

    Each living monster takes 75 on a roll whose low two bits are not 0.
    """
    arena = _board(asset_mgr, count=3)
    arena.monsters[1].hp = 75
    _randrange(monkeypatch, [1, 2, 4])  # 4 & 3 == 0: the third is missed
    _cast(arena, Spell.NOXUM)
    assert [m.hp for m in arena.monsters[:3]] == [125, 0, 200]


def test_bigdeath_dag_mentar_twice_int(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:238:
    `case 13: /* Dag Mentar */ BigDeath(Player[rosNum][20] * 2, chnum);`
    Twice the caster's INT to each monster the 75% roll picks."""
    arena = _board(asset_mgr, count=2, caster=_caster(intelligence=40))
    _randrange(monkeypatch, [3, 0])
    _cast(arena, Spell.DAG_MENTAR)
    assert [m.hp for m in arena.monsters[:2]] == [120, 200]
