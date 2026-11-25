"""Tests for Auto-Combat AI and CombatScreen integration."""
import random
from types import SimpleNamespace

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.aura import AuraType
from py_exodus.combat.arena import ActionType, CombatArena
from py_exodus.combat.auto_combat import choose_auto_combat_action
from py_exodus.constants import Direction, Profession, Race, Spell, Status, TileAttrib, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.world.loader import MapLoader
from py_exodus.world.map import ConflictMap


@pytest.fixture
def asset_mgr():
    am = AssetManager(assets_dir="src/main/resources/assets")
    am.load_tiles()
    am.load_xml_definitions()
    return am


@pytest.fixture
def conflict_map(asset_mgr):
    loader = MapLoader(asset_mgr)
    return loader.load_conflict_map("CNFLCT_A.ULT")


def _open_arena(
    weapon: WeaponType = WeaponType.SWORD,
    hp: int = 100,
    max_hp: int = 100,
    asset_mgr: AssetManager | None = None,
    monster_count: int = 1,
) -> CombatArena:
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=50, dexterity=99)
    hero.weapon = weapon
    hero.hp = hp
    hero.max_hp = max_hp
    party.add_member(hero)

    cmap = ConflictMap(width=11, height=11, tiles=[None] * (11 * 11))
    arena = CombatArena(
        party=party,
        combat_map=cmap,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=monster_count,
    )
    arena.player_positions[0] = (5, 5)
    return arena


def test_pass_when_no_visible_monsters():
    arena = _open_arena(monster_count=1)
    arena.monsters[0].visible = False
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.PASS

    arena.monsters[0].visible = True
    arena.monsters[0].hp = 0
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.PASS


def test_adjacent_melee_attack(asset_mgr):
    arena = _open_arena(weapon=WeaponType.SWORD, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 4
    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.NORTH


def test_ranged_attack_clear_los_with_asset_mgr(asset_mgr):
    arena = _open_arena(weapon=WeaponType.BOW, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 8
    arena.monsters[0].y = 5
    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.EAST


def test_ranged_attack_clear_los_without_asset_mgr_fallback():
    arena = _open_arena(weapon=WeaponType.SLING, asset_mgr=None, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2
    action = choose_auto_combat_action(arena, 0, asset_mgr=None)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.NORTH


def test_ranged_attack_blocked_by_wall_does_not_fire(asset_mgr):
    arena = _open_arena(weapon=WeaponType.BOW, asset_mgr=asset_mgr, monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2
    wall = SimpleNamespace(attribs=TileAttrib.UNWALKABLE)
    arena.combat_map.set_tile(5, 4, wall)

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert not (action.type == ActionType.ATTACK and action.direction == Direction.NORTH)


def test_advance_toward_nearest_enemy(asset_mgr):
    arena = _open_arena(weapon=WeaponType.SWORD, asset_mgr=asset_mgr, monster_count=2)
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 3
    arena.monsters[1].x = 9
    arena.monsters[1].y = 9
    # (9, 9) is closer in Manhattan distance (4+1=5) than (5, 3) (0+5=5)?
    # Make monster 1 clearly farther:
    arena.monsters[1].x = 10
    arena.monsters[1].y = 10

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.NORTH


def test_advance_ranged_prefers_cardinal_alignment(asset_mgr):
    arena = _open_arena(weapon=WeaponType.BOW, asset_mgr=asset_mgr, monster_count=1)
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x = 3
    arena.monsters[0].y = 5

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.WEST


def test_low_hp_retreat_when_adjacent_enemy(asset_mgr):
    arena = _open_arena(
        weapon=WeaponType.SWORD, hp=10, max_hp=100, asset_mgr=asset_mgr, monster_count=1
    )
    # Someone else is still standing (a healer can come): retreat.
    arena.party.add_member(
        Character("Medic", "F", Race.HUMAN, Profession.CLERIC, strength=10, dexterity=10)
    )
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 4

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.SOUTH


def test_last_one_standing_fights_instead_of_retreating(asset_mgr):
    """Batch 1c7525f seed 17: the lone survivor stepped back from a Goblin,
    stepped in again, and back, from step 45,791 to the 200,000 cap."""
    arena = _open_arena(
        weapon=WeaponType.SWORD, hp=10, max_hp=100, asset_mgr=asset_mgr, monster_count=1
    )
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 4

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.ATTACK
    assert action.direction == Direction.NORTH


def test_combat_screen_toggle_tab_f2_and_escape(asset_mgr, conflict_map):
    party = Party()
    hero = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, strength=50, dexterity=99)
    party.add_member(hero)

    combat = CombatScreen(
        party=party,
        combat_map=conflict_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=1,
    )
    assert combat.auto_combat is False

    # K_TAB turns auto_combat ON
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert combat.auto_combat is True
    assert "Auto-combat ON." in combat.text_log.lines[-1]

    # K_F2 turns auto_combat OFF
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F2))
    assert combat.auto_combat is False
    assert "Auto-combat OFF." in combat.text_log.lines[-1]

    # K_TAB ON, then K_ESCAPE turns OFF
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert combat.auto_combat is True
    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert combat.auto_combat is False
    assert "Auto-combat OFF." in combat.text_log.lines[-1]


def test_combat_screen_auto_combat_full_battle_to_victory(asset_mgr, conflict_map, monkeypatch):
    rng = random.Random(1)
    monkeypatch.setattr("py_exodus.combat.resolver.random", rng)
    monkeypatch.setattr("py_exodus.combat.arena.random", rng)
    party = Party()
    for i in range(2):
        hero = Character(
            f"Hero{i}", "M", Race.HUMAN, Profession.FIGHTER, strength=99, dexterity=99
        )
        hero.weapon = WeaponType.SWORD_P4
        hero.hp = 200
        hero.max_hp = 200
        party.add_member(hero)

    combat = CombatScreen(
        party=party,
        combat_map=conflict_map,
        creature_tile="orc",
        asset_mgr=asset_mgr,
        monster_count=2,
    )
    for m in combat.arena.monsters:
        m.hp = 10

    combat.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert combat.auto_combat is True

    for _ in range(400):
        if combat.arena.is_finished:
            break
        combat.update(0.20)

    assert combat.arena.is_finished is True
    assert combat.arena.is_victory is True


def _caster_arena(
    profession: Profession,
    mp: int = 50,
    weapon: WeaponType = WeaponType.DAGGER,
    creature_tile: str = "orc",
    monster_count: int = 1,
    asset_mgr: AssetManager | None = None,
) -> CombatArena:
    party = Party()
    caster = Character("Caster", "M", Race.HUMAN, profession, intelligence=50, wisdom=50)
    caster.weapon = weapon
    caster.hp = 100
    caster.max_hp = 100
    caster.mp = mp
    party.add_member(caster)

    cmap = ConflictMap(width=11, height=11, tiles=[None] * (11 * 11))
    arena = CombatArena(
        party=party,
        combat_map=cmap,
        creature_tile=creature_tile,
        asset_mgr=asset_mgr,
        monster_count=monster_count,
    )
    arena.player_positions[0] = (5, 5)
    return arena


def test_wizard_casts_repond_against_orcs_and_respects_free_flag_and_negate():
    arena = _caster_arena(Profession.WIZARD, mp=0, creature_tile="orc", monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2

    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.REPOND

    # The battle's Repond latch is set (LW g5521) -> does not cast REPOND
    arena.repond_latch = True
    action = choose_auto_combat_action(arena, 0)
    assert action.spell != Spell.REPOND

    # Latch clear, activate NEGATE aura -> does not cast any spell
    arena.repond_latch = False
    arena.party.aura.set(AuraType.NEGATE, 5)
    action = choose_auto_combat_action(arena, 0)
    assert action.type != ActionType.CAST


def test_cleric_casts_pontori_against_skeletons():
    arena = _caster_arena(Profession.CLERIC, mp=0, creature_tile="skeleton", monster_count=1)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2

    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.PONTORI

    arena.pontori_latch = True
    action = choose_auto_combat_action(arena, 0)
    assert action.spell != Spell.PONTORI


def test_cleric_heals_lowest_hp_living_ally_with_sanctu_and_sanctu_mani():
    arena = _caster_arena(Profession.CLERIC, mp=20, creature_tile="orc", monster_count=1)
    arena.monsters[0].x = 9
    arena.monsters[0].y = 9

    dead_ally = Character("Dead", "M", Race.HUMAN, Profession.FIGHTER)
    dead_ally.hp = 0
    dead_ally.max_hp = 100
    dead_ally.status = Status.DEAD

    hurt_ally = Character("Hurt", "M", Race.HUMAN, Profession.FIGHTER)
    hurt_ally.hp = 30
    hurt_ally.max_hp = 100

    critical_ally = Character("Crit", "M", Race.HUMAN, Profession.FIGHTER)
    critical_ally.hp = 15
    critical_ally.max_hp = 100

    arena.party.add_member(dead_ally)
    arena.party.add_member(hurt_ally)
    arena.party.add_member(critical_ally)

    # With 20 MP (< 50), Cleric casts SANCTU on lowest-HP living ally
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.SANCTU
    assert action.target_member is arena.party.members[3]

    # With >= 50 MP, Cleric upgrades to SANCTU_MANI
    arena.party.members[0].mp = 50
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.SANCTU_MANI
    assert action.target_member is arena.party.members[3]


def test_wizard_casts_mittar_when_lined_up_and_skips_with_strong_weapons(asset_mgr):
    arena = _caster_arena(
        Profession.WIZARD,
        mp=10,
        weapon=WeaponType.DAGGER,
        creature_tile="orc",
        monster_count=1,
        asset_mgr=asset_mgr,
    )
    arena.repond_latch = True
    arena.monsters[0].x = 5
    arena.monsters[0].y = 1  # Distance 4 (within range 5)

    action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.MITTAR
    assert action.direction == Direction.NORTH

    # Wielding BOW_P2 or EXOTIC skips MITTAR
    for w in (WeaponType.BOW_P2, WeaponType.EXOTIC):
        arena.party.members[0].weapon = w
        action = choose_auto_combat_action(arena, 0, asset_mgr=asset_mgr)
        assert action.spell != Spell.MITTAR


def test_wizard_advances_to_cardinal_alignment_when_can_cast_mittar():
    arena = _caster_arena(
        Profession.WIZARD, mp=10, weapon=WeaponType.DAGGER, creature_tile="orc", monster_count=1
    )
    arena.repond_latch = True
    arena.player_positions[0] = (5, 8)
    arena.monsters[0].x = 3
    arena.monsters[0].y = 5

    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.MOVE
    assert action.direction == Direction.WEST


def test_high_threat_masskill_unspeakable_and_zxkuqyb():
    # Wizard: UNSPEAKABLE when >= 2 monsters and threat > 60
    wiz_arena = _caster_arena(
        Profession.WIZARD, mp=80, creature_tile="orc", monster_count=2
    )
    wiz_arena.repond_latch = True
    wiz_arena.monsters[0].x = 1
    wiz_arena.monsters[0].y = 1
    wiz_arena.monsters[0].exp = 35
    wiz_arena.monsters[1].x = 9
    wiz_arena.monsters[1].y = 9
    wiz_arena.monsters[1].exp = 35  # total threat = 70 > 60

    action = choose_auto_combat_action(wiz_arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.UNSPEAKABLE

    # Cleric: ZXKUQYB when >= 2 monsters and threat > 80 (poisonous doubles exp)
    cleric_arena = _caster_arena(
        Profession.CLERIC, mp=80, creature_tile="orc", monster_count=2
    )
    cleric_arena.monsters[0].x = 1
    cleric_arena.monsters[0].y = 1
    cleric_arena.monsters[0].exp = 25
    cleric_arena.monsters[0].poisons = True  # 50 threat
    cleric_arena.monsters[1].x = 9
    cleric_arena.monsters[1].y = 9
    cleric_arena.monsters[1].exp = 35  # total threat = 85 > 80

    action = choose_auto_combat_action(cleric_arena, 0)
    assert action.type == ActionType.CAST
    assert action.spell == Spell.ZXKUQYB

    # Only 1 monster -> does not cast masskill even with high exp
    cleric_arena.monsters[1].hp = 0
    cleric_arena.monsters[0].exp = 100
    action = choose_auto_combat_action(cleric_arena, 0)
    assert action.spell != Spell.ZXKUQYB


def test_auto_combat_never_throws_last_dagger():
    from py_exodus.assets import AssetManager

    am = AssetManager("data")
    am.load_all()

    arena = _caster_arena(Profession.WIZARD, mp=0, creature_tile="orc", monster_count=1)
    wiz = arena.party.members[0]
    arena.repond_latch = True
    wiz.weapon = WeaponType.DAGGER
    wiz.weapons = {}
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 2  # 3 tiles north (clear cardinal line of sight)

    # With only 1 Dagger (no spares), do not throw it; advance instead
    action_single = choose_auto_combat_action(arena, 0, asset_mgr=am)
    assert action_single.type == ActionType.MOVE
    assert action_single.direction == Direction.NORTH

    # With a spare Dagger (> 1 total), throwing at range is allowed
    wiz.weapons = {WeaponType.DAGGER: 1}
    action_spare = choose_auto_combat_action(arena, 0, asset_mgr=am)
    assert action_spare.type == ActionType.ATTACK
    assert action_spare.direction == Direction.NORTH


def test_combat_pathing_around_mast_for_auto_combat_and_monsters():
    """Auto-combat routes around an obstacle (e.g. ship mast) instead of
    stalling; a monster does not (LairWare FigureNewMonPosition,
    UltimaSpellCombat.c:1395-1404, tries only the diagonal, vertical and
    horizontal steps toward the member and otherwise stays)."""
    from py_exodus.assets import TileDef
    from py_exodus.constants import TileAttrib

    arena = _caster_arena(Profession.FIGHTER, mp=0, creature_tile="pirate", monster_count=1)
    # Place an impassable mast tile at (5, 4) directly between player (5, 5) and pirate (5, 3)
    mast = TileDef(index=99, name="mast", rule="none", attribs=TileAttrib.UNWALKABLE)
    arena.combat_map.set_tile(5, 4, mast)
    arena.player_positions[0] = (5, 5)
    arena.monsters[0].x = 5
    arena.monsters[0].y = 3

    # Auto-combat must step EAST or WEST around the mast instead of passing
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.MOVE
    assert action.direction in (Direction.EAST, Direction.WEST)

    target, close, step, _ = arena._figure_new_mon_position(arena.monsters[0])
    assert target is None and step is None


def test_sea_monster_advances_to_closest_water_tile_near_ship():
    """A swimming monster steps only onto water toward the member (LairWare
    CombatValidMove, UltimaSpellCombat.c:616-631); a reef straight ahead
    stops it (no path search, FigureNewMonPosition 1395-1404)."""
    from py_exodus.assets import TileDef
    from py_exodus.constants import TileAttrib

    arena = _caster_arena(Profession.FIGHTER, mp=0, creature_tile="serpent", monster_count=1)
    arena.monsters[0].definition.swims = True
    # Build a small ship deck at x in {4,5,6}, y in {4,5,6} surrounded by water
    water = TileDef(index=0, name="water", rule="water", attribs=TileAttrib.SWIMMABLE | TileAttrib.UNWALKABLE)
    deck = TileDef(index=8, name="floor", rule="floors", attribs=TileAttrib.NONE)
    for y in range(11):
        for x in range(11):
            arena.combat_map.set_tile(x, y, deck if 4 <= x <= 6 and 4 <= y <= 6 else water)

    arena.player_positions[0] = (5, 5)  # center of deck, surrounded by non-swimmable deck tiles
    arena.monsters[0].x = 1
    arena.monsters[0].y = 1
    # Place a mast/reef at (2, 1) and (1, 2) or test direct BFS when aligned at (2, 5) -> (3, 5)
    arena.monsters[0].x = 2
    arena.monsters[0].y = 5
    # Greedy toward_mask is EAST (3, 5) — check BFS fallback when (3, 5) is blocked by a reef
    reef = TileDef(index=99, name="reef", rule="none", attribs=TileAttrib.UNWALKABLE | TileAttrib.CREATUREUNWALKABLE)
    arena.combat_map.set_tile(3, 5, reef)
    target, close, step, _ = arena._figure_new_mon_position(arena.monsters[0])
    assert step is None
    arena.combat_map.set_tile(3, 5, water)
    target, close, step, _ = arena._figure_new_mon_position(arena.monsters[0])
    assert step == (3, 5)


def test_combat_screen_default_party_view_and_z_toggle():
    """CombatScreen shows party view with active member highlighted unless Z shows the active member."""
    import pygame
    from py_exodus.assets import AssetManager
    from py_exodus.screens.combat_screen import CombatScreen
    from py_exodus.world.loader import load_conflict_map

    pygame.init()
    pygame.font.init()
    am = AssetManager("data")
    am.load_all()
    party = Party()
    for name in ("A", "B"):
        party.add_member(Character(name, "M", Race.HUMAN, Profession.FIGHTER))
    cs = CombatScreen(party=party, combat_map=load_conflict_map(37, am), asset_mgr=am, monster_count=1)
    cs.arena.active_party_member_idx = 1

    surf = pygame.Surface((960, 600))
    cs.render(surf)
    assert cs.stats_panel.inspect_index is None
    assert cs.party.active_member_index == 1

    # LairWare combat Z (UltimaSpellCombat.c:1066-1069): Stats(1, chnum + 1)
    # shows the active member only; any key closes it.
    cs.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, unicode="z"))
    assert cs.stats_panel.inspect_index == 1
    cs.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, unicode="z"))
    assert cs.stats_panel.inspect_index is None


def test_dead_party_members_not_rendered_in_combat():
    """Dead party members are not drawn on the combat grid in CombatScreen._render_players."""
    from py_exodus.assets import AssetManager
    from py_exodus.constants import Status
    from py_exodus.screens.combat_screen import CombatScreen
    from py_exodus.world.loader import load_conflict_map

    pygame.init()
    pygame.font.init()
    am = AssetManager("data")
    am.load_all()
    party = Party()
    a = Character("A", "M", Race.HUMAN, Profession.FIGHTER)
    b = Character("B", "M", Race.HUMAN, Profession.FIGHTER)
    b.status = Status.DEAD
    b.hp = 0
    party.add_member(a)
    party.add_member(b)

    cmap = load_conflict_map(37, am)
    cs = CombatScreen(party=party, combat_map=cmap, asset_mgr=am, monster_count=1)
    # LairWare: the dead are off the board (no position at all); their
    # roster start tile must stay empty on screen.
    assert 1 not in cs.arena.player_positions
    bx, by = (cmap.player_starts or [(5, 9), (4, 8)])[1]
    surf = pygame.Surface((176, 176))
    surf.fill((0, 0, 0))
    cs._render_players(surf)
    assert surf.get_at((bx * 16 + 8, by * 16 + 8))[:3] == (0, 0, 0)



def test_lagging_caster_trains_with_area_spells_once_a_fighter_is_25():
    """User idea 2026-11-22: kills pay the killer, so with a fighter at 25 a
    lagging Cleric opens a 2+ monster fight with ZXKUQYB even when the
    threat is low; at 25 itself it is back to the threat rule."""
    arena = _caster_arena(Profession.CLERIC, mp=70, creature_tile="orc", monster_count=2)
    arena.party.members[0].level = 13
    fighter = Character("Fighter", "M", Race.HUMAN, Profession.FIGHTER)
    fighter.level = 25
    fighter.hp = fighter.max_hp = 2550
    arena.party.add_member(fighter)
    arena.repond_latch = True
    for m, (x, y) in zip(arena.monsters, ((1, 1), (9, 9))):
        m.x, m.y = x, y
        m.exp = 5  # threat 10: far below the 80 bar
    action = choose_auto_combat_action(arena, 0)
    assert action.type == ActionType.CAST and action.spell == Spell.ZXKUQYB

    arena.party.members[0].level = 25
    action = choose_auto_combat_action(arena, 0)
    assert getattr(action, "spell", None) != Spell.ZXKUQYB


def _cleric_arena(asset_mgr, level: int, hp: int = 150):
    """Hero the Fighter at (5,5), a Cleric at (5,8), one orc."""
    arena = _open_arena(weapon=WeaponType.SWORD, asset_mgr=asset_mgr, monster_count=1)
    cleric = Character("Cleric", "F", Race.HUMAN, Profession.CLERIC, strength=20, dexterity=20)
    cleric.weapon = WeaponType.MACE
    cleric.level = level
    cleric.max_hp = 150 + 100 * (level - 1)
    cleric.hp = hp
    cleric.mp = 0  # no spell to cast
    arena.party.add_member(cleric)
    arena.player_positions[1] = (5, 8)
    return arena, cleric


def test_a_low_level_cleric_steps_away_at_half_hp(asset_mgr):
    arena, _ = _cleric_arena(asset_mgr, level=2, hp=120)  # of 250
    arena.monsters[0].x, arena.monsters[0].y = 6, 8
    action = choose_auto_combat_action(arena, 1, asset_mgr=asset_mgr)
    assert action.type == ActionType.MOVE and action.direction != Direction.EAST
