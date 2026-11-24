"""LairWare parity, batch B (battle): pins LairWare batch B combat rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "B - Battle".
"""
from __future__ import annotations

from py_exodus.combat.arena import CombatArena
from py_exodus.constants import Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.ui.renderer import can_move_to
from py_exodus.world.loader import MapLoader


def _party(transport: Transport) -> Party:
    party = Party(transport=transport)
    party.add_member(Character("Hero0", "M", hp=100, max_hp=100))
    party.x, party.y = 44, 20
    party.dynamic_objects.clear()
    return party


def _beat_pirate(asset_mgr, transport: Transport, x: int = 21, y: int = 7) -> Party:
    party = _party(transport)
    arena = CombatArena(
        party, MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT"),
        creature_tile="pirate", asset_mgr=asset_mgr, monster_count=1,
        encounter_x=x, encounter_y=y, encounter_tile_walkable=False,
    )
    arena.monsters[0].hp = 0
    arena._handle_victory()
    return party


def _frigates(party: Party) -> list[dict]:
    return [o for o in party.dynamic_objects if o.get("tile") == "frigate"]


def test_pirate_beaten_aboard_ship_leaves_no_frigate(asset_mgr):
    """UltimaMain.c:1354-1357 (AttackCode):

        if (gMonType == 0x1E) { /* Pirate */
            if (Party[1] != 0x16)
                PutXYVal(0x2C, xs, ys);
        }

    0x16 is the party's ship: a pirate fought from the party's own ship
    leaves no frigate; the tile stays open water.
    """
    party = _beat_pirate(asset_mgr, Transport.SHIP)
    assert _frigates(party) == []


def test_pirate_beaten_on_foot_leaves_a_frigate(asset_mgr):
    """UltimaMain.c:1354-1357 (AttackCode): `if (Party[1] != 0x16)
    PutXYVal(0x2C, xs, ys);` - a pirate fought from land (any transport but
    the ship) leaves a frigate (0x2C) on its tile.
    """
    party = _beat_pirate(asset_mgr, Transport.FOOT)
    frigate = _frigates(party)
    assert len(frigate) == 1 and (frigate[0]["x"], frigate[0]["y"]) == (21, 7)


def test_ship_sails_onto_beaten_pirates_water_tile(asset_mgr):
    """UltimaMain.c:1354-1357 (AttackCode) with ValidDir 3174-3176: a pirate
    beaten from the ship leaves no frigate, so the ship can sail onto the
    pirate's former tile. (A frigate there would seal a one-tile channel,
    the Ambrosia south water at (39, 61).)
    """
    from py_exodus.screens.overworld import OverworldScreen

    party = _party(Transport.SHIP)
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=4, start_y=2,
                         random_encounters=False)
    party.objects_map_id = 0
    water = next(
        (x, y)
        for y in range(ow.game_map.height)
        for x in range(ow.game_map.width)
        if can_move_to(ow.game_map, x, y, transport=Transport.SHIP, party=party)
    )
    arena = CombatArena(
        party, MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT"),
        creature_tile="pirate", asset_mgr=asset_mgr, monster_count=1,
        encounter_x=water[0], encounter_y=water[1], encounter_tile_walkable=False,
        context_map_id=0,
    )
    arena.monsters[0].hp = 0
    arena._handle_victory()
    assert can_move_to(ow.game_map, water[0], water[1], transport=Transport.SHIP, party=party)


# --- R-19: experience cap ---------------------------------------------------

def test_addexp_caps_experience_at_9899():
    """UltimaMisc.c:475-477 (AddExp):

        experience += amount;
        if (experience > 9899)
            experience = 9899;

    The record holds hundreds and units (Player[30] * 100 + Player[31]), and
    LairWare stops at 9899, not 9999.
    """
    hero = Character("Hero0", "M", hp=100, max_hp=100)
    hero.exp = 9898
    hero.award_xp(5)
    assert hero.exp == 9899
    hero.award_xp(1)
    assert hero.exp == 9899


def test_addexp_cap_on_a_combat_kill():
    """UltimaSpellCombat.c:734-752 (DamageMonster) pays Experience[] through
    AddExp, so a kill at 9898 experience stops at 9899 (UltimaMisc.c:476-477).
    The fallback for a record without award_xp caps the same way."""
    from types import SimpleNamespace

    from py_exodus.combat.resolver import resolve_player_attack

    bare = SimpleNamespace(str=99, dex=99, exp=9898)  # no award_xp
    orc = SimpleNamespace(name="Orc", tile="orc", basehp=48, exp=30, x=0, y=0, hp=1)
    res = resolve_player_attack(bare, None, orc)
    assert res.killed
    assert bare.exp == 9899


def test_old_save_experience_above_9899_loads_unchanged():
    """A record saved before the 9899 cap keeps its experience on load (the
    cap applies only when experience is added, UltimaMisc.c:475-477)."""
    hero = Character("Hero0", "M", hp=100, max_hp=100)
    data = hero.to_dict()
    data["exp"] = 9950
    loaded = Character.from_dict(data)
    assert loaded.exp == 9950
    loaded.award_xp(1)
    assert loaded.exp == 9899
