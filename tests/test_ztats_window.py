"""The Ztats window (approved design C): what it shows and where it draws.

Z's flow (who is asked, the turn, the pause, the closing key, combat's pass)
is covered by the existing Ztats tests; these check the picture: a modal
window over the map pane only, stat-tile numbers from the rules code, gear
and spell chip states, and the status tag.
"""
from __future__ import annotations

import itertools

import pygame
import pytest

from py_exodus.combat.resolver import hit_chance, lw_weapon_index, player_damage_range
from py_exodus.constants import ArmorType, Profession, Race, Spell, Status, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.screens.member_prompts import show_ztats
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.ui import ztats_view as zv


@pytest.fixture(scope="module")
def pygame_setup():
    pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield


def member(prof=Profession.FIGHTER, **stats) -> Character:
    m = Character(name="Hero", sex="M", race=Race.HUMAN, profession=prof)
    for k, v in stats.items():
        setattr(m, k, v)
    return m


def cleric() -> Character:
    m = member(Profession.CLERIC, str=15, dex=22, int=5, wis=35)
    m.mp = 27
    m.weapon, m.armor = WeaponType.MACE, ArmorType.CHAIN
    m.weapons = {WeaponType.DAGGER: 2, WeaponType.MACE: 1}
    m.armors = {ArmorType.CLOTH: 1, ArmorType.CHAIN: 1}
    return m


# --- the rules the tiles read -------------------------------------------


def test_hit_chance_matches_roll_hit_odds():
    """hit_chance is roll_hit's exact odds (LW CombatAttack: half the swings
    land outright, the rest when DEX >= a 0-99 roll)."""
    for dex in (0, 5, 22, 50, 99, 120):
        hits = sum(
            1
            for a, b in itertools.product(range(256), range(100))
            if not (a < 128 and dex < b)
        )
        assert hit_chance(dex) == pytest.approx(hits / (256 * 100))


def test_damage_range_is_the_blow_formula():
    m = member(str=25, weapon=WeaponType.SWORD)
    lo = 25 // 2 + lw_weapon_index(WeaponType.SWORD) * 3 + 4
    assert player_damage_range(m) == (lo, lo + (25 | 1))
    bare = member(str=10, weapon=WeaponType.NONE)
    assert player_damage_range(bare) == (5 + 4, 5 + 4 + 11)


def test_mp_parts_agree_with_max_mp_for_every_class():
    legacy = {
        Profession.WIZARD: lambda i, w: i,
        Profession.CLERIC: lambda i, w: w,
        Profession.ALCHEMIST: lambda i, w: i // 2,
        Profession.LARK: lambda i, w: i // 2,
        Profession.PALADIN: lambda i, w: w // 2,
        Profession.ILLUSIONIST: lambda i, w: w // 2,
        Profession.DRUID: lambda i, w: max(i // 2, w // 2),
        Profession.RANGER: lambda i, w: min(i // 2, w // 2),
    }
    for prof in Profession:
        m = member(prof, int=31, wis=18)
        assert m.compute_max_mp() == legacy.get(prof, lambda i, w: 0)(31, 18), prof


@pytest.mark.parametrize(
    "prof, stats, expect",
    [
        (Profession.FIGHTER, dict(str=25, dex=15, int=5, wis=5, weapon=WeaponType.SWORD),
         ("-", "-")),
        (Profession.CLERIC, dict(str=15, dex=22, int=5, wis=35, weapon=WeaponType.MACE),
         ("-", "MP max 35")),
        (Profession.WIZARD, dict(str=10, dex=20, int=40, wis=5, weapon=WeaponType.DAGGER),
         ("MP max 40", "-")),
        (Profession.DRUID, dict(str=10, dex=20, int=30, wis=24, weapon=WeaponType.DAGGER),
         ("MP max 15, higher", "MP max 12, higher")),
        (Profession.RANGER, dict(str=10, dex=20, int=30, wis=24, weapon=WeaponType.BOW),
         ("MP max 15, lower", "MP max 12, lower")),
    ],
)
def test_stat_tiles_match_the_rules(prof, stats, expect):
    m = member(prof, **stats)
    tiles = zv.stat_tiles(m)
    assert [t[0] for t in tiles] == ["STR", "DEX", "INT", "WIS"]
    assert [t[1] for t in tiles] == [m.str, m.dex, m.int, m.wis]
    lo, hi = player_damage_range(m)
    assert tiles[0][2] == f"dmg {lo}–{hi}"
    assert tiles[1][2] == f"hit {round(100 * hit_chance(m.dex))}%"
    assert (tiles[2][2], tiles[3][2]) == expect


# --- chips and tags --------------------------------------------------------


def test_gear_chips_gold_for_readied_and_worn_with_counts():
    m = cleric()
    names = {"DAGGER": "Dagger", "MACE": "Mace", "NONE": "Hands"}
    assert zv.gear_chips(m.weapons, WeaponType, names, m.weapon) == [
        ("Dagger ×2", False), ("Mace", True),
    ]
    arm = zv.gear_chips(m.armors, ArmorType, {"CLOTH": "Cloth", "CHAIN": "Chain"}, m.armor)
    assert arm == [("Cloth", False), ("Chain", True)]
    # Bare hands are the readied chip; a readied weapon with no spare shows.
    assert zv.gear_chips({}, WeaponType, names, WeaponType.NONE) == [("Hands", True)]
    assert zv.gear_chips({}, WeaponType, names, WeaponType.DAGGER) == [("Dagger", True)]


def test_spell_chips_lit_dim_and_off():
    m = cleric()  # MP 27 of 35
    (discipline, spells), = zv.spell_books(m)
    assert discipline == "cleric"
    state = {s: st for s, st in spells}
    assert state[Spell.PONTORI] == "lit"  # 0
    assert state[Spell.REC_DU] == "lit"  # 25
    assert state[Spell.LIB_REC] == "dim"  # 30: within max, needs MP
    assert state[Spell.ALCORT] == "dim"  # 35
    assert state[Spell.SEQUITU] == "off"  # 40: past the MP max
    assert [s.code for s, _ in spells] == list("ABCDEFGHIJKLMNOP")


def test_spell_books_by_class():
    assert zv.spell_books(member(Profession.FIGHTER)) == []
    druid = member(Profession.DRUID, int=30, wis=24)
    assert [d for d, _ in zv.spell_books(druid)] == ["wizard", "cleric"]


def test_status_tags():
    m = member()
    assert zv.status_tag(m) is None
    m.status = Status.DEAD
    assert zv.status_tag(m) == "DEAD"
    m.status = Status.ASH
    assert zv.status_tag(m) == "ASHES"
    m.status = Status.POISONED
    assert zv.status_tag(m) == "POISONED"


# --- drawing ---------------------------------------------------------------


@pytest.mark.parametrize("size, pane", [((960, 600), 528), ((320, 200), 176)])
@pytest.mark.parametrize("status", [Status.GOOD, Status.DEAD, Status.ASH])
def test_window_draws_inside_the_map_pane_only(pygame_setup, size, pane, status):
    surf = pygame.Surface(size)
    surf.fill((7, 77, 177))
    m = cleric()
    m.status = status
    rect = pygame.Rect(0, 0, pane, pane)
    win = zv.render_ztats(surf, rect, m, 3)
    assert rect.contains(win)
    outside = [
        (x, y)
        for x in range(0, size[0], 4)
        for y in range(0, size[1], 4)
        if not rect.collidepoint(x, y)
    ]
    assert all(surf.get_at(p)[:3] == (7, 77, 177) for p in outside)
    assert surf.get_at(win.center)[:3] != (7, 77, 177)


def overworld(asset_mgr) -> OverworldScreen:
    party = Party(members=[], x=44, y=20, map_id=0, food=400, transport=Transport.FOOT)
    for prof in (Profession.FIGHTER, Profession.CLERIC, Profession.WIZARD, Profession.DRUID):
        party.add_member(Character(name=prof.name, sex="M", race=Race.HUMAN, profession=prof))
    return OverworldScreen(party=party, asset_mgr=asset_mgr)


@pytest.mark.parametrize("size", [(960, 600), (320, 200)])
def test_screen_keeps_panel_and_log_while_ztats_is_up(pygame_setup, asset_mgr, size):
    """Ztats changes only the map pane: the party panel stays the party
    panel (no inspect listing) and the log gets the one Zstats line."""
    screen = overworld(asset_mgr)
    before = pygame.Surface(size)
    screen.render(before)
    logged: list[str] = []
    screen.text_log.add_message = logged.append  # keep the log's picture
    show_ztats(screen.text_log, screen.stats_panel, screen.party, 1)
    assert logged == ["Zstats: CLERIC (CLERIC)"]
    after = pygame.Surface(size)
    screen.render(after)
    pane = 176 * (3 if size[0] >= 640 else 1)
    changed = [
        (x, y)
        for x in range(0, size[0], 3)
        for y in range(0, size[1], 3)
        if before.get_at((x, y)) != after.get_at((x, y))
    ]
    assert changed
    assert all(x < pane and y < pane for x, y in changed)


def _town(asset_mgr, party):
    from py_exodus.screens.town import TownScreen

    return TownScreen(party=party, asset_mgr=asset_mgr, map_id=1, start_x=44, start_y=26)


def _dungeon(asset_mgr, party):
    from py_exodus.screens.dungeon_screen import DungeonScreen
    from py_exodus.world.loader import load_map

    return DungeonScreen(party=party, dungeon_map=load_map(15, asset_mgr),
                         asset_mgr=asset_mgr, map_id=15)


def _combat(asset_mgr, party):
    from py_exodus.screens.combat_screen import CombatScreen
    from py_exodus.world.loader import load_conflict_map

    return CombatScreen(party=party, combat_map=load_conflict_map(37, asset_mgr),
                        asset_mgr=asset_mgr, monster_count=1)


@pytest.mark.parametrize("make", [_town, _dungeon, _combat])
def test_window_on_town_dungeon_and_combat(pygame_setup, asset_mgr, make):
    """Towns, dungeons and combat (the arena is its map pane) draw the
    window over the map pane only, like Sosaria."""
    screen = make(asset_mgr, overworld(asset_mgr).party)
    screen.text_log.add_message = lambda msg: None
    before = pygame.Surface((960, 600))
    screen.render(before)
    show_ztats(screen.text_log, screen.stats_panel, screen.party, 2)
    after = pygame.Surface((960, 600))
    screen.render(after)
    changed = [
        (x, y)
        for x in range(0, 960, 4)
        for y in range(0, 600, 4)
        if before.get_at((x, y)) != after.get_at((x, y))
    ]
    assert len(changed) > 1000
    assert all(x < 528 and y < 528 for x, y in changed)
