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
    """UltimaSpellCombat.c:202:

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
    """UltimaSpellCombat.c:209: `case 5: /* Fulgar */ Projectile(chnum, 75);`
    A fixed 75, no roll and no fire resistance."""
    arena = _board(asset_mgr)
    _randint(monkeypatch, 40)
    res = _cast(arena, Spell.FULGAR, Direction.NORTH)
    assert res.damage == 75
    assert arena.monsters[0].hp == 125


def test_spell_mentar_damage_is_the_casters_int(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:226:
    `case 7: /* Mentar */ Projectile(chnum, Player[rosNum][20]); break;`
    Player[20] is INT: the damage is exactly the caster's INT."""
    arena = _board(asset_mgr, caster=_caster(intelligence=77))
    _randint(monkeypatch, 33)
    res = _cast(arena, Spell.MENTAR, Direction.NORTH)
    assert res.damage == 77
    assert arena.monsters[0].hp == 123


@pytest.mark.parametrize("spell", [Spell.DECORP, Spell.EXCUUN])
def test_spell_decorp_excuun_damage_255_kills(asset_mgr, monkeypatch, spell):
    """UltimaSpellCombat.c:237 and 329:

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
    """UltimaSpellCombat.c:236 and 475-495:

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
    """UltimaSpellCombat.c:239:
    `case 13: /* Dag Mentar */ BigDeath(Player[rosNum][20] * 2, chnum);`
    Twice the caster's INT to each monster the 75% roll picks."""
    arena = _board(asset_mgr, count=2, caster=_caster(intelligence=40))
    _randrange(monkeypatch, [3, 0])
    _cast(arena, Spell.DAG_MENTAR)
    assert [m.hp for m in arena.monsters[:2]] == [120, 200]


# --- P-08: Repond / Pontori latches -------------------------------------------


def test_spell_repond_wrong_type_keeps_the_latch(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:191-196 and 253-261:

        if ((Party[3] != 0x80) || (gMonType != 0x30) || (g5521 != 0)) {
            Failed(); return; }
        g5521 = 0xFF;
        ...
        if (gMonType != 0x32) { Failed(); return; }
        if (g56E7 != 0) { Failed(); return; }
        g56E7 = 0xFF;

    The type test comes before the latch: Repond against skeletons fails
    without spending anything, so Pontori keeps its chance - even from the
    same Druid (LW has no per-caster free-spell flag).
    """
    arena = _board(asset_mgr, creature="skeleton", count=2, caster=_caster(Profession.DRUID))
    arena.masskill = True
    res = _cast(arena, Spell.REPOND)
    assert not res.success and res.executed
    assert arena.masskill is True
    _randrange(monkeypatch, [1, 1])
    res = _cast(arena, Spell.PONTORI)
    assert res.success
    assert all(m.hp == 0 for m in arena.monsters[:2])


# --- P-09, P-10: Altair -------------------------------------------------------


def test_spell_altair_ends_the_casters_turn(asset_mgr):
    """UltimaSpellCombat.c:238 (`case 12: /* Altair */ gTimeNegate = 20;`):
    Altair is an ordinary cast; the combat loop goes on to plrdone (1079)
    like any other command, so the caster's turn is spent (Java let the
    caster act again)."""
    arena = _board(asset_mgr)
    result = arena._handle_player_cast(0, arena.party.members[0], Action.cast(Spell.ALTAIR))
    assert result.consume_turn is True


def test_spell_altair_stops_monsters_for_20_rounds(asset_mgr):
    """UltimaSpellCombat.c:238 and 1102-1105:

        case 12: /* Altair */ gTimeNegate = 20; break;
        ...
        if (gTimeNegate != 0) {
            gTimeNegate--;
            goto combatstart;

    The count is tested before it drops, so 20 monster phases are skipped
    (the port skipped 19: it dropped the count first)."""
    arena = _board(asset_mgr)
    moved: list[int] = []
    arena._execute_single_monster_ai = lambda m: moved.append(arena.round_count)
    arena.party.aura.set(magic.AuraType.QUICKNESS, 20)
    for _ in range(21):
        arena.execute_monster_turns()
    assert moved == [21]


def test_victory_ends_stopped_time(asset_mgr):
    """UltimaSpellCombat.c:850 (Victory): `gTimeNegate = gSongCurrent =
    gSongNext = 0;` - stopped time does not outlast a won fight."""
    arena = _board(asset_mgr)
    arena.party.aura.set(magic.AuraType.QUICKNESS, 15)
    arena.monsters[0].hp = 0
    arena._handle_victory()
    assert not arena.party.aura.is_active()


# --- P-11: Dag Acron ----------------------------------------------------------


def _sosaria(asset_mgr):
    return MapLoader(asset_mgr).load_map(0)


def _first(gmap, name):
    return next((x, y) for y in range(64) for x in range(64) if gmap.get_tile(x, y).name == name)


def _surface_party(transport=Transport.FOOT, exodus_defeated=0):
    party = Party(transport=transport, exodus_defeated=exodus_defeated)
    party.add_member(_caster())
    party.x, party.y = 10, 10
    return party


def _coords(monkeypatch, pairs):
    seq = iter(v for p in pairs for v in p)
    calls: list = []

    def fake(a, b):
        calls.append((a, b))
        return next(seq)
    monkeypatch.setattr(magic.random, "randint", fake)
    return calls


def test_spell_dag_acron_lands_on_random_grass(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:210-225:

        int matchValue = (Party[1] == 0x16) ? 0 : 4;
        value = -1;
        while (value != matchValue) {
            xs = RandNum(0, gCurMapSize - 1);
            ys = RandNum(0, gCurMapSize - 1);
            value = GetXYVal(xs, ys);
        }
        xpos = xs; ypos = ys;

    Random tiles anywhere on the 64x64 map until one is grass (value 4);
    the party lands there (Java's 16-tile directional blink is gone).
    """
    gmap = _sosaria(asset_mgr)
    party = _surface_party()
    water, grass = _first(gmap, "water"), _first(gmap, "grass")
    calls = _coords(monkeypatch, [water, grass])
    res = cast_spell(Spell.DAG_ACRON, party.members[0], world_map=gmap, party=party)
    assert res.executed
    assert (party.x, party.y) == grass
    assert calls == [(0, 63)] * 4


def test_spell_dag_acron_skips_a_monsters_tile(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:221: GetXYVal reads the map, where LW keeps its
    monsters (a monster's grass is not value 4), so the party never lands on
    one; the port passes its own monsters in as ``occupied``."""
    gmap = _sosaria(asset_mgr)
    party = _surface_party()
    grass = [(x, y) for y in range(64) for x in range(64) if gmap.get_tile(x, y).name == "grass"][:2]
    _coords(monkeypatch, grass)
    cast_spell(Spell.DAG_ACRON, party.members[0], world_map=gmap, party=party,
               occupied=lambda x, y: (x, y) == grass[0])
    assert (party.x, party.y) == grass[1]


def test_spell_dag_acron_aboard_ship_before_exodus_is_refused(asset_mgr):
    """UltimaSpellCombat.c:212: `if ((Party[3] != 0) || (Party[1] == 0x16 &&
    Party[16] == 0)) { Failed(); return; }` - no Dag Acron aboard ship while
    Exodus stands. Refused at the attempt (user ruling 3): no MP spent."""
    gmap = _sosaria(asset_mgr)
    party = _surface_party(Transport.SHIP)
    res = cast_spell(Spell.DAG_ACRON, party.members[0], world_map=gmap, party=party)
    assert not res.executed and res.message == "Not Here!"
    assert party.members[0].mp == 99 and (party.x, party.y) == (10, 10)


def test_spell_dag_acron_aboard_ship_after_exodus_lands_on_water(asset_mgr, monkeypatch):
    """UltimaSpellCombat.c:216: `matchValue = (Party[1] == 0x16) ? 0 : 4;` -
    once Exodus has fallen the ship jumps to random open water (value 0)."""
    gmap = _sosaria(asset_mgr)
    party = _surface_party(Transport.SHIP, exodus_defeated=1)
    water, grass = _first(gmap, "water"), _first(gmap, "grass")
    _coords(monkeypatch, [grass, water])
    cast_spell(Spell.DAG_ACRON, party.members[0], world_map=gmap, party=party)
    assert (party.x, party.y) == water


def test_spell_dag_acron_overworld_marks_monsters_and_objects(asset_mgr):
    """UltimaSpellCombat.c:217-222 (GetXYVal sees LW's map-held monsters and
    parked ships): the overworld hands DAG ACRON its creatures and parked
    objects as taken tiles."""
    from py_exodus.screens.overworld import OverworldScreen

    party = _surface_party()
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=4, start_y=2,
                         random_encounters=False)
    ow.creatures = [{"tile": "orc", "tile_name": "orc", "x": 20, "y": 21}]
    party.objects_map_id = 0
    party.dynamic_objects = [{"tile": "horse", "x": 30, "y": 31}]
    assert ow._dag_acron_taken(20, 21) and ow._dag_acron_taken(30, 31)
    assert not ow._dag_acron_taken(20, 22)


# --- P-12: who may cast what --------------------------------------------------


@pytest.mark.parametrize("spell", [Spell.DAG_LORUM, Spell.FAL_DIVI, Spell.SOMINAE])
def test_cast_ranger_may_cast_up_to_its_mp(spell):
    """UltimaSpellCombat.c:55-86 and 89-118 (Cast, ProcessMagic): a Ranger
    (careerTable[10]) chooses from either book (EitherChoose) and the only
    test is `magicreq > Player[rosNum][25]`; there is no per-class spell
    list. A Ranger's MP (the lesser of INT/2 and WIS/2, MaxMana) reaches 49,
    so wizard I/J (40, 45) and cleric J (45) are open to it."""
    assert spell.can_cast(Profession.RANGER)
    ranger = _caster(Profession.RANGER, intelligence=99, wisdom=99, mp=49)
    res = cast_spell(spell, ranger)
    assert "cannot cast" not in res.message
    assert ranger.mp == 49 - spell.cost


# --- P-13: Surmandum and Anju Sermani outside combat only ---------------------


@pytest.mark.parametrize("letter", ["N", "P"])
def test_spell_surmandum_anju_refused_in_combat(letter):
    """UltimaSpellCombat.c:330-335 and 356-361:

        case 29: /* Surmandum */
            if (Party[3] == 0x80) { Failed(); return; }
        case 31: /* Anju Sermani */
            if (Party[3] == 0x80) { Failed(); return; }

    Neither works in combat; refused at the attempt (user ruling 3)."""
    from py_exodus.spell_menu import letter_resolution, spell_menu_entries

    found, refusal = letter_resolution(spell_menu_entries("cleric"), letter, "combat")
    assert found is None and refusal == "Not Here!"
    found, refusal = letter_resolution(spell_menu_entries("cleric"), letter, "world")
    assert refusal is None


# --- P-14: Dor Acron / Rec Du at the bottom -----------------------------------


@pytest.mark.parametrize("spell", [Spell.DOR_ACRON, Spell.REC_DU])
def test_downlevel_refused_on_the_deepest_level(spell):
    """UltimaSpellCombat.c:588-599 (DownLevel):

        if (dungeonLevel > 6) { Failed(); return; }
        dungeonLevel++;

    On the eighth level (index 7) the spell fails and the party stays; here
    refused at the attempt (user ruling 3), no MP spent. The port used to
    step to a ninth level that does not exist."""
    from py_exodus.world.dungeon import DungeonState
    from py_exodus.world.map import DungeonMap

    dmap = DungeonMap(id=1, name="D", width=16, height=16, levels=8)
    state = DungeonState(dmap, start_x=1, start_y=1, start_z=7)
    caster = _caster(Profession.DRUID)
    res = cast_spell(spell, caster, world_map=state)
    assert not res.executed and res.message == "Not Here!"
    assert state.z == 7 and caster.mp == 99


def test_autoplay_druid_cast_answers_wizard_or_cleric(pygame_setup, asset_mgr):
    """User ruling Q56 (fix it). LairWare's Cast asks a Druid (and any
    two-discipline caster) which book to cast from before the spell letter
    (UltimaSpellCombat.c:73-76, 125-136):

        if (classType == careerTable[8])
            spellnum = EitherChoose();
        ...
        if (value == 'W') result = WizardChoose();
        if (value == 'C') result = ClericChoose();

    (the port's prompt is "Spell Type? [W]izard or [C]leric"). ALCORT, SURMANDUM, ANJU SERMANI, SANCTU and APPAR UNEM are
    cleric spells, so autoplay must answer C before the letter; without it the
    letter lands on the type prompt and the cast fails.
    """
    from py_exodus.autoplay.controller import AutoPlayController
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    party = Party(transport=Transport.FOOT)
    party.add_member(Character("Fight", "M", profession=Profession.FIGHTER,
                               hp=300, max_hp=300, food=500, gold=500))
    druid = Character("Druid", "M", profession=Profession.DRUID,
                      intelligence=50, wisdom=50, hp=300, max_hp=300,
                      food=500, gold=500, mp=60, max_mp=60)
    party.add_member(druid)
    party.members[0].status = Status.POISONED
    sm = StateMachine(asset_mgr=asset_mgr, audio=None)
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, random_encounters=False)
    sm.set_screen(ow)
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.step(sm) == pygame_key("c")
    for _ in range(6):
        if not ctrl._key_queue:
            break
        ctrl.step(sm)
    assert party.members[0].status == Status.GOOD
    assert druid.mp < 60


def pygame_key(ch: str) -> int:
    import pygame

    return getattr(pygame, f"K_{ch}")


def test_spell_wizard_i_is_dag_lorum():
    """UltimaSpellCombat.c:227-230 (Spell), user ruling Q21 (follow LairWare):

        case 8: /* Dag Lorum */
            gTorch = 250;
            Flashriek();
            break;

    Wizard spell I (spellnum 8, 8 * 5 = 40 MP, ProcessMagic :92) is Dag
    Lorum, a long light: the torch count becomes 250. ProcessMagic has no
    place test, so it casts anywhere, and in a fight it spends the turn like
    any cast. The port's I was Java's PABULUM (5-9 food a member).
    """
    from py_exodus.combat.magic import NO_TURN_SPELLS
    from py_exodus.world.dungeon import DungeonState
    from py_exodus.world.map import DungeonMap

    spell = Spell["DAG_LORUM"]
    assert spell.code == "I" and spell.spell_type == "wizard" and spell.cost == 40
    assert "PABULUM" not in Spell.__members__
    assert spell not in NO_TURN_SPELLS

    dmap = DungeonMap(id=1, name="D", width=16, height=16, levels=8)
    state = DungeonState(dmap, start_x=1, start_y=1, start_z=0)
    state.torchtime = 0
    caster = _caster(mp=99)
    food = caster.food
    res = cast_spell(spell, caster, world_map=state)
    assert res.success
    assert state.torchtime == 250
    assert caster.mp == 59 and caster.food == food

    # Anywhere: on the surface it casts too (no light to keep there).
    from py_exodus.spell_menu import letter_resolution, spell_menu_entries

    entries = spell_menu_entries("wizard")
    for context in ("world", "city", "dungeon", "combat"):
        found, refusal = letter_resolution(entries, "I", context)
        assert found is spell and refusal is None, context


@pytest.mark.parametrize("spell,before", [(Spell.SURMANDUM, Status.DEAD), (Spell.ANJU_SERMANI, Status.ASHES)])
def test_spell_raise_leaves_hp_as_it_was(monkeypatch, spell, before):
    """UltimaSpellCombat.c:353 and 374-375 (Surmandum, Anju Sermani), user
    ruling Q19 (follow LairWare):

        Player[Party[6 + value]][17] = 'G';            // Surmandum
        ...
        Player[Party[6 + value]][17] = 'G';            // Anju Sermani
        Player[Party[6 + chnum]][21] -= 5; /* Caster's wisdom-5 */

    Only the status byte changes; the raised member keeps the HP they had
    (0 after a death), as the healer's resurrection does (S-06). The port
    set 1 HP. The caster's WIS still stops at 0 (LW's byte wrap below 5 WIS
    is left out by the same ruling)."""
    monkeypatch.setattr(magic.random, "random", lambda: 0.0)  # Surmandum works
    caster = _caster(Profession.CLERIC, wisdom=3, mp=99)
    target = Character("Dead", "M", profession=Profession.FIGHTER, hp=0, max_hp=300, status=before)
    party = Party()
    party.add_member(caster)
    party.add_member(target)
    cast_spell(spell, party.members[0], party=party, target_member=party.members[1])
    assert target.status == Status.GOOD
    assert target.hp == 0
    if spell == Spell.ANJU_SERMANI:
        assert caster.wis == 0
