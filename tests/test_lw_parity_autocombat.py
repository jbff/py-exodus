"""LairWare parity, batch A (auto-combat): pins LairWare AutoCombat rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "A - Auto-combat".
"""
from __future__ import annotations

from py_exodus.combat.arena import ActionType, CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.constants import Profession, Race, Spell, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.map import ConflictMap


def _arena(*profs: Profession, creature: str = "orc", count: int = 1, mp: int = 0,
           grass=None) -> CombatArena:
    party = Party(transport=Transport.FOOT)
    for i, prof in enumerate(profs):
        party.add_member(Character(f"C{i}", "M", Race.HUMAN, prof, mp=mp, hp=300, max_hp=300,
                                   intelligence=50, wisdom=50))
    cmap = ConflictMap(width=11, height=11, tiles=[grass] * (11 * 11))
    arena = CombatArena(party=party, combat_map=cmap, creature_tile=creature, monster_count=count)
    for i in range(len(profs)):
        arena.player_positions[i] = (2 + 2 * i, 9)
        party.members[i].combat_x, party.members[i].combat_y = 2 + 2 * i, 9
    for j, mon in enumerate(arena.monsters):
        mon.x, mon.y = 8, 1 + j
    return arena


# --- A-02 (user ruling 2026-11-25): Repond / Pontori one try per battle ---------


def test_autocombat_repond_asked_only_while_latch_clear():
    """UltimaAutocombat.c:98-104: ``if ((gMonType == 0x30) && (g5521 == 0)
    && isWiz)`` -- asked while the battle latch is 0, by any wizard-book
    member; once any caster's try set it, no one asks again."""
    arena = _arena(Profession.WIZARD, Profession.WIZARD)
    assert choose_auto_combat_action(arena, 0).spell == Spell.REPOND
    assert choose_auto_combat_action(arena, 1).spell == Spell.REPOND
    arena.repond_latch = True
    for i in (0, 1):
        assert choose_auto_combat_action(arena, i).spell != Spell.REPOND


def test_autocombat_pontori_asked_only_while_latch_clear():
    """UltimaAutocombat.c:106-112: ``(gMonType == 0x32) && (g56E7 == 0) &&
    isCler``."""
    arena = _arena(Profession.CLERIC, Profession.PALADIN, creature="skeleton")
    assert choose_auto_combat_action(arena, 1).spell == Spell.PONTORI
    arena.pontori_latch = True
    for i in (0, 1):
        assert choose_auto_combat_action(arena, i).spell != Spell.PONTORI
