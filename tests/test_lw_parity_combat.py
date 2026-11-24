"""LairWare parity, batch B (battle): pins LairWare batch B combat rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "B - Battle".
"""
from __future__ import annotations

import pytest

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


# --- B-04 / B-05: the party's to-hit roll and weapon damage -----------------

def _scripted(monkeypatch, values):
    """Feed resolver.random.randint the given values in order."""
    import py_exodus.combat.resolver as resolver

    seq = iter(values)
    monkeypatch.setattr(resolver.random, "randint", lambda a, b: next(seq))


def _orc(hp=255):
    from types import SimpleNamespace

    return SimpleNamespace(name="Orc", tile="orc", basehp=48, exp=3, x=0, y=0, hp=hp)


def test_combatattack_dex_check_misses(monkeypatch):
    """UltimaSpellCombat.c:1332-1337 (CombatAttack):

        if (RandNum(0, 255) < 128) {
            if (Player[rosNum][19] < RandNum(0, 99)) {
                Missed();

    Half the swings face a dexterity check: DEX below a 0-99 roll misses.
    """
    from py_exodus.combat.resolver import resolve_player_attack

    hero = Character("Hero0", "M", hp=100, max_hp=100, dexterity=50)
    _scripted(monkeypatch, [127, 51])  # checked, 50 < 51: a miss
    assert not resolve_player_attack(hero, None, _orc()).hit


def test_combatattack_dex_check_bounds(monkeypatch):
    """UltimaSpellCombat.c:1332-1337: RandNum is inclusive at both ends. A
    first roll of 128..255 skips the check (a hit); DEX equal to the second
    roll is not below it (a hit)."""
    from py_exodus.combat.resolver import resolve_player_attack

    hero = Character("Hero0", "M", hp=100, max_hp=100, dexterity=50)
    _scripted(monkeypatch, [128, 0, 0])  # no check; then damage rolls
    assert resolve_player_attack(hero, None, _orc()).hit
    _scripted(monkeypatch, [0, 50, 0])  # checked, 50 < 50 is false
    assert resolve_player_attack(hero, None, _orc()).hit
    weak = Character("Weak", "M", hp=100, max_hp=100, dexterity=0)
    _scripted(monkeypatch, [0, 1])  # DEX 0 misses any roll above 0
    assert not resolve_player_attack(weak, None, _orc()).hit


def test_combatattack_damage_formula(monkeypatch):
    """UltimaSpellCombat.c:1347-1350 (CombatAttack):

        damage = RandNum(0, (Player[rosNum][18] | 1));
        damage += Player[rosNum][18] / 2;
        damage += Player[rosNum][48] * 3;
        damage += 4;

    STR 20 with a Sword (weapon 6): 0..21 + 10 + 18 + 4 = 32..53.
    """
    from py_exodus.combat.resolver import calculate_player_damage
    from py_exodus.entities.defs import WeaponDef

    hero = Character("Hero0", "M", hp=100, max_hp=100, strength=20)
    sword = WeaponDef(type="SWORD", name="Sword", dmin=4, dmax=22)
    seen = []
    import py_exodus.combat.resolver as resolver

    monkeypatch.setattr(resolver.random, "randint", lambda a, b: seen.append((a, b)) or b)
    assert calculate_player_damage(hero, sword) == 53
    assert seen == [(0, 21)]
    monkeypatch.setattr(resolver.random, "randint", lambda a, b: a)
    assert calculate_player_damage(hero, sword) == 32
    # Hands (weapon 0), STR 15: 0..15 + 7 + 0 + 4.
    hero.str = 15
    assert calculate_player_damage(hero, None) == 11


# --- B-06: missiles fly to the board edge -----------------------------------

def test_shoot_flies_over_walls(asset_mgr):
    """UltimaSpellCombat.c:708-731 (Shoot): the missile steps on until a
    monster or the board edge,

        if (x < 0 || x > 10 || y < 0 || y > 10) { ... return 255; }
        ...
        if (orgval > 127) goto shoot0;

    with no terrain test, so a wall does not stop an arrow (CombatAttack
    shoots for weapons 3, 5, 9 and 13, UltimaSpellCombat.c:1302-1327)."""
    from py_exodus.combat.arena import Action
    from py_exodus.constants import Direction, WeaponType

    cmap = MapLoader(asset_mgr).load_conflict_map("CNFLCT_A.ULT")
    cmap.set_tile(3, 5, asset_mgr.tile_defs_by_name["wall"])
    party = _party(Transport.FOOT)
    hero = party.members[0]
    hero.weapon = WeaponType.BOW
    hero.dex = 99
    arena = CombatArena(party, cmap, creature_tile="orc", asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (3, 7)
    hero.x, hero.y = 3, 7
    arena.monsters[0].x, arena.monsters[0].y = 3, 2
    res = arena.execute_player_action(0, Action.attack(Direction.NORTH))
    assert (3, 2) in res.attack_res.projectile_path
    assert res.attack_res.hit


# --- B-07: the arena is picked by the party's own tile ----------------------

class _TileMap:
    def __init__(self, tiles):
        self._tiles = tiles

    def get_tile(self, x, y):
        from py_exodus.assets import TileDef

        name = self._tiles.get((x, y), "grass")
        return TileDef(index=0, name=name, rule=name)


def test_background_uses_the_partys_tile():
    """UltimaSpellCombat.c:797-810 (BackGround): a land fight's arena comes
    from the party's own tile, not the monster's,

        tile = GetXYVal(xpos, ypos) / 2;
        if (tile == 0x02) return BASERES + 4;   // grass -> G
        if (tile == 0x04) return BASERES + 1;   // brush -> B
        if (tile == 0x06) return BASERES + 3;   // forest -> F
        if (tile == 0x10) return BASERES + 2;   // floor -> C
        if (tile == 0x40) return BASERES + 2;   // energy field -> C
        if (tile == 0x42) return BASERES + 2;   // lava -> C
        return BASERES + 4;                     // anything else -> G
    """
    from py_exodus.entities.defs import CreatureDef
    from py_exodus.screens.overworld import get_combat_map_id

    orc = CreatureDef(id=10, name="Orc", tile="orc")
    for party_tile, arena in (("grass", 37), ("brush", 34), ("forest", 36), ("floor", 35),
                              ("energy_field", 35), ("lava", 35), ("towne", 37), ("castle", 37),
                              ("dungeon", 37), ("chest", 37), ("shrine", 37)):
        gm = _TileMap({(10, 10): party_tile, (11, 10): "forest"})
        assert get_combat_map_id(orc, 11, 10, 10, 10, Transport.FOOT, gm) == arena, party_tile
    gm = _TileMap({(10, 10): "grass", (11, 10): "brush"})
    assert get_combat_map_id(orc, 11, 10, 10, 10, Transport.HORSE, gm) == 37


def test_background_town_fight_uses_the_partys_tile(asset_mgr):
    """UltimaSpellCombat.c:797-810 (BackGround) runs for town fights too
    (Party[3] 2 or 3): a fight started from town grass is on the grass
    arena, from the floor on the brick floor."""
    from py_exodus.entities.defs import CreatureDef
    from py_exodus.screens.town import town_combat_map_id

    guard = CreatureDef(id=6, name="Guard", tile="guard")
    assert town_combat_map_id(guard, (5, 5), _TileMap({(5, 5): "grass"})) == 37
    assert town_combat_map_id(guard, (5, 5), _TileMap({(5, 5): "floor"})) == 35


# --- B-02: a town fight leaves a chest on the person's tile -----------------

def test_attackcode_town_person_leaves_a_chest(asset_mgr):
    """UltimaMain.c:1342-1352 (AttackCode), the same code for town people:

        tileon = Monsters[whichMon + TILEON];
        if (tileon != 0) {
            tileon = ((tileon / 4) & 0x03) + 0x24;
        }
        PutXYVal(tileon, xs, ys);

    The person's tile becomes a chest (0x24) unless it stood on water (0).
    The chest stays in that town until the visit ends (towns reset)."""
    from py_exodus.screens.town import TownScreen

    party = _party(Transport.FOOT)
    town = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)
    npc = next(n for n in town.game_map.npcs
               if town.game_map.get_tile(n.x, n.y).name != "water")
    town._combat_npc = npc
    town.end_combat(True)
    assert npc not in town.game_map.npcs
    assert town.game_map.get_tile(npc.x, npc.y).rule == "chest"
    # A fresh visit has no chest there (the town resets on entry).
    again = TownScreen(party=party, map_id=1, asset_mgr=asset_mgr, start_x=10, start_y=10)
    assert again.game_map.get_tile(npc.x, npc.y).rule != "chest"


# --- B-08: monster turns (FigureNewMonPosition and the Combat monster loop) -

def _board(asset_mgr, creature="orc", members=1, arena_file="cnflct_g.json"):
    """A fight on an all-grass arena, the members parked in the corners."""
    party = Party(transport=Transport.FOOT)
    for i in range(members):
        party.add_member(Character(f"Hero{i}", "M", hp=900, max_hp=900))
    cmap = MapLoader(asset_mgr).load_conflict_map(arena_file)
    grass = asset_mgr.tile_defs_by_name["grass"]
    for y in range(11):
        for x in range(11):
            cmap.set_tile(x, y, grass)
    arena = CombatArena(party, cmap, creature_tile=creature, asset_mgr=asset_mgr, monster_count=1)
    for i, m in enumerate(party.members):
        _place(arena, i, (10 - i, 10))
    return arena


def _place(arena, idx, pos):
    arena.player_positions[idx] = pos
    m = arena.party.members[idx]
    m.combat_x, m.combat_y = pos
    m.x, m.y = pos


def _rolls(monkeypatch, values):
    """Script every random.randint call (LairWare RandNum) in order."""
    import random as _random

    seq = iter(values)
    monkeypatch.setattr(_random, "randint", lambda a, b: next(seq))


def test_figurenewmonposition_attacks_a_diagonal_neighbour(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:1381-1382, 1407-1411 and 1117-1118: a member within
    one step on BOTH axes is close (`zp[0xD2] < 2 && zp[0xD1] < 2`), so
    zp[0xD0] = 0 and the monster attacks it (`goto afternext`), diagonals
    included."""
    arena = _board(asset_mgr)
    _place(arena, 0, (5, 5))
    orc = arena.monsters[0]
    orc.x, orc.y = 4, 4
    import py_exodus.combat.resolver as resolver

    monkeypatch.setattr(resolver, "lw_monster_hits", lambda *a, **k: True)
    res = arena._execute_single_monster_ai(orc)
    assert res.action_type == "attack" and (orc.x, orc.y) == (4, 4)
    assert arena.party.members[0].hp < 900


def test_figurenewmonposition_steps_diagonally_to_the_nearest(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:1384-1406: the nearest member by |dx| + |dy| is the
    target (a tie keeps the first, `>= zp[0xD0]` skips), and the monster
    steps on both axes at once: (MonsterX + GetHeading(dx), MonsterY +
    GetHeading(dy))."""
    arena = _board(asset_mgr, members=2)
    _place(arena, 0, (7, 6))   # distance 2 + 4 = 6
    _place(arena, 1, (3, 6))   # distance 2 + 4 = 6, later: loses the tie
    orc = arena.monsters[0]
    orc.x, orc.y = 5, 2
    _rolls(monkeypatch, [0, 0, 0])  # no magic for an orc; no rolls needed
    res = arena._execute_single_monster_ai(orc)
    assert res.action_type == "advance"
    assert (orc.x, orc.y) == (6, 3)


def test_figurenewmonposition_blocked_diagonal_tries_vertical_then_horizontal(asset_mgr):
    """UltimaSpellCombat.c:1395-1404: a blocked diagonal tries (MonsterX,
    MonsterY + dy), then (MonsterX + dx, MonsterY)."""
    arena = _board(asset_mgr)
    _place(arena, 0, (8, 8))
    orc = arena.monsters[0]
    orc.x, orc.y = 5, 5
    wall = arena.asset_mgr.tile_defs_by_name["wall"]
    arena.combat_map.set_tile(6, 6, wall)
    arena._execute_single_monster_ai(orc)
    assert (orc.x, orc.y) == (5, 6)
    arena.combat_map.set_tile(6, 6, arena.asset_mgr.tile_defs_by_name["grass"])
    arena.combat_map.set_tile(6, 7, wall)
    arena.combat_map.set_tile(5, 7, wall)
    arena._execute_single_monster_ai(orc)
    assert (orc.x, orc.y) == (6, 6)


def test_combatvalidmove_monsters_are_never_slowed(asset_mgr):
    """UltimaSpellCombat.c:616-631 (CombatValidMove): a land monster may
    enter grass, brush, forest or floor (2, 4, 6, 0x10) and is never slowed;
    Java's slowedByTile roll is gone. Twenty steps into forest all land."""
    forest = asset_mgr.tile_defs_by_name["forest"]
    for _ in range(20):
        arena = _board(asset_mgr)
        _place(arena, 0, (5, 9))
        orc = arena.monsters[0]
        orc.x, orc.y = 5, 5
        arena.combat_map.set_tile(5, 6, forest)
        arena._execute_single_monster_ai(orc)
        assert (orc.x, orc.y) == (5, 6)


def test_combatvalidmove_land_and_sea(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:616-631: a sea monster (0x16 <= gMonType < 0x20:
    serpent, Man-O-War) moves only onto water (0); a land monster never
    does. With every way forward blocked, the member is not a target and the
    monster stays (UltimaSpellCombat.c:1397-1404, `goto nextPlrTarget`)."""
    import random as _random

    monkeypatch.setattr(_random, "randrange", lambda *a: 0)  # no serpent magic
    water = asset_mgr.tile_defs_by_name["water"]
    for creature, expect in (("orc", (5, 5)), ("serpent", (5, 6))):
        arena = _board(asset_mgr, creature=creature)
        _place(arena, 0, (5, 9))
        mon = arena.monsters[0]
        mon.x, mon.y = 5, 5
        arena.combat_map.set_tile(5, 6, water)
        arena._execute_single_monster_ai(mon)
        assert (mon.x, mon.y) == expect, creature
        # The serpent can go no further: grass all round.
        arena._execute_single_monster_ai(mon)
        assert (mon.x, mon.y) == expect, creature


def test_combat_only_dragons_shoot(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:1119-1140: only the dragon (0x3A) shoots
    (`monshoot`); a wizard out of reach either casts (monmagic, a RandNum(0,
    0xC0) > 127 roll) or steps closer. Java's 34% bolt for every ranged
    creature is gone."""
    arena = _board(asset_mgr, creature="wizard")
    _place(arena, 0, (5, 9))
    wiz = arena.monsters[0]
    wiz.x, wiz.y = 5, 2
    import random as _random

    monkeypatch.setattr(_random, "randrange", lambda *a: 0)  # the magic draw fails
    res = arena._execute_single_monster_ai(wiz)
    assert res.action_type == "advance" and (wiz.x, wiz.y) == (5, 3)


def test_monshoot_dragon_fire_hits_the_first_member_in_line(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:1119-1124 and 1165-1194 (monshoot): on RandNum(0,
    255) < 128 a dragon fires along its heading (zp[0xF5], zp[0xF6]) to the
    board edge; the first member on that line takes the damage roll with no
    armour check (`goto c8777`)."""
    arena = _board(asset_mgr, creature="dragon", members=2)
    _place(arena, 0, (5, 9))
    _place(arena, 1, (5, 6))  # in the line of fire, before the target
    dragon = arena.monsters[0]
    dragon.x, dragon.y = 5, 2
    import py_exodus.combat.resolver as resolver

    monkeypatch.setattr(resolver, "lw_armor_roll", lambda *a: pytest.fail("no armour roll"))
    _rolls(monkeypatch, [127, 3])  # fire; damage roll 3
    res = arena._execute_single_monster_ai(dragon)
    assert res.action_type == "ranged"
    assert (dragon.x, dragon.y) == (5, 2)
    assert arena.party.members[1].hp < 900
    assert arena.party.members[0].hp == 900


def test_monshoot_dragon_holds_fire_on_128(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:1119-1140: `RandNum(0, 255) < 128` - a roll of
    128 does not fire; the dragon goes on to the magic roll and the move."""
    arena = _board(asset_mgr, creature="dragon")
    _place(arena, 0, (5, 9))
    dragon = arena.monsters[0]
    dragon.x, dragon.y = 5, 2
    import random as _random

    monkeypatch.setattr(_random, "randrange", lambda *a: 0)  # the magic draw fails
    _rolls(monkeypatch, [128])
    res = arena._execute_single_monster_ai(dragon)
    assert res.action_type == "advance" and (dragon.x, dragon.y) == (5, 3)
