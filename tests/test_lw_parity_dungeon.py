"""LairWare parity, batch D (dungeons): pins LairWare dungeon rules.

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "D - Dungeon".
"""
from __future__ import annotations

import random

import pytest

from py_exodus.constants import Direction, Profession, Race, Status
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.dungeon import DungeonEventType, DungeonState
from py_exodus.world.map import DungeonMap, DungeonTile


def _party(*members: Character) -> Party:
    p = Party(food=200, gold=0)
    for m in members or (
        Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, hp=500, max_hp=500, torches=5),
        Character("Mage", "F", Race.ELF, Profession.WIZARD, hp=400, max_hp=400, torches=0),
    ):
        p.add_member(m)
    return p


def _dmap(fill: DungeonTile = DungeonTile.NOTHING) -> DungeonMap:
    dmap = DungeonMap(id=98, name="Test", width=16, height=16, levels=8)
    dmap.tiles = [[[fill for _x in range(16)] for _y in range(16)] for _z in range(8)]
    return dmap


class SeqRNG(random.Random):
    """randint answers from a script (LairWare RandNum(a, b) is inclusive)."""

    def __init__(self, ints):
        super().__init__(0)
        self.ints = list(ints)
        self.calls: list[tuple[int, int]] = []

    def randint(self, a, b):
        self.calls.append((a, b))
        return self.ints.pop(0)


# --- D-02 RelocateDungeon, DownLevel --------------------------------------


def test_relocatedungeon_rolls_randnum_0_16_until_an_empty_tile():
    """UltimaSpellCombat.c:576-586:
        value = -1;
        while (value != 0) {
            xs = RandNum(0, 16);
            ys = RandNum(0, 16);
            value = GetXYDng(xs, ys);
        }
    GetXYDng (758-768) wraps 16 to 0. The port tried 32 uniform 0-15 picks
    and stayed put when they all missed."""
    dmap = _dmap(DungeonTile.WALL)
    dmap.set_tile(0, 3, 1, DungeonTile.NOTHING)
    # 40 misses (more than the port's 32 tries), then x=16 (wraps to 0), y=3.
    rng = SeqRNG([5, 5] * 40 + [16, 3])
    state = DungeonState(dmap, start_x=1, start_y=1, start_z=0, party=_party(), rng=rng)
    state.spell_down()
    assert (state.x, state.y, state.z) == (0, 3, 1)
    assert set(rng.calls) == {(0, 16)}


def test_downlevel_spell_down_never_steps_past_the_last_level():
    """UltimaSpellCombat.c:594-597: `if (dungeonLevel > 6) { Failed(); return; }`.
    The port's spell_down stepped z to 8, a level that does not exist."""
    state = DungeonState(_dmap(), start_x=3, start_y=3, start_z=7, party=_party())
    evt = state.spell_down()
    assert state.z == 7
    assert (state.x, state.y) == (3, 3)
    assert evt.success is False


# --- D-05 dungeonmech encounters --------------------------------------------


@pytest.mark.parametrize("roll, fights", [(127, False), (128, True)])
def test_dungeonmech_encounter_roll_on_an_empty_tile(roll, fights):
    """UltimaDngn.c:196-200: on an empty tile (GetXYDng == 0)
        if (RandNum(0, 0x82 + dungeonLevel) < 128) goto dungstart;
    so a fight comes (3 + level) times in (131 + level) per command. The
    port ran Java's wandering monsters (spawn 1 in 32 - 2 * level, at most
    two, walking toward the party)."""
    rng = SeqRNG([roll, 0])
    state = DungeonState(_dmap(), start_x=4, start_y=4, start_z=3, party=_party(), rng=rng)
    evt = state._tick_turn()
    assert rng.calls[0] == (0, 0x82 + 3)
    assert (evt is not None and evt.type == DungeonEventType.COMBAT) is fights


@pytest.mark.parametrize(
    "z, roll, tile",
    [(0, 0, "orc"), (0, 2, "giant"), (3, 4, "pincher"), (7, 6, "balron"), (7, 9, "balron")],
)
def test_dungeonmech_monster_by_level(z, roll, tile):
    """UltimaDngn.c:201-205:
        value = RandNum(0, dungeonLevel + 2);
        if (value > 6) value = 6;
        value += 0x18; gMonType = value * 2;
    Tiles 0x30..0x3C: Orc, Skeleton, Giant, Daemon, Pincher, Dragon, Balron
    (Tiles.plist 24-30). No Thief comes in a LairWare dungeon."""
    rng = SeqRNG([200, roll])
    state = DungeonState(_dmap(), start_x=4, start_y=4, start_z=z, party=_party(), rng=rng)
    evt = state._tick_turn()
    assert rng.calls[1] == (0, z + 2)
    assert evt.creature.tile == tile


def test_dungeonmech_chest_is_left_before_the_fight():
    """UltimaDngn.c:206-207: `PutXYDng(0x40, xpos, ypos); Combat();` the
    chest goes on the party's tile before the fight, whatever its end. The
    port dropped one only after a won fight with a monster that carries one."""
    rng = SeqRNG([200, 0])
    dmap = _dmap()
    state = DungeonState(dmap, start_x=4, start_y=4, start_z=0, party=_party(), rng=rng)
    state._tick_turn()
    assert dmap.get_tile(4, 4, 0) == DungeonTile.CHEST


@pytest.mark.parametrize(
    "tile", [DungeonTile.CHEST, DungeonTile.LADDER_UP, DungeonTile.MARK, DungeonTile.FOUNTAIN_HEAL]
)
def test_dungeonmech_no_fight_on_a_tile_that_holds_something(tile):
    """UltimaDngn.c:196-198: `value = GetXYDng(xs, ys); if (value != 0)
    goto dngnotcombat;` only an empty tile rolls for a fight."""
    rng = SeqRNG([200, 0])
    dmap = _dmap()
    dmap.set_tile(4, 4, 0, tile)
    state = DungeonState(dmap, start_x=4, start_y=4, start_z=0, party=_party(), rng=rng)
    assert state._tick_turn() is None
    assert rng.calls == []


def test_dungeonmech_pit_tile_does_not_roll_a_fight_the_same_turn():
    """UltimaDngn.c:196-198, 285-294: the pass that finds the trap (value 4)
    clears it and springs it; it does not also roll for a fight."""
    rng = SeqRNG([0] * 20)
    dmap = _dmap()
    dmap.set_tile(4, 3, 0, DungeonTile.PIT_TRAP)
    state = DungeonState(dmap, start_x=4, start_y=4, start_z=0, party=_party(), rng=rng)
    evt = state.move_forward()
    assert evt.type == DungeonEventType.PIT_TRAP
    assert (0, 0x82) not in rng.calls


# --- D-03 every dungeon command ends in dungeonmech --------------------------


@pytest.mark.parametrize("turn", ["turn_left", "turn_right"])
def test_dungeonmech_turning_takes_the_turn(turn):
    """UltimaDngn.c:172-177, 183-193: Left()/Right() fall through to
    dungeonmech like every command: AgeChars, the torch burns one, and the
    encounter roll comes. The port turned for free (Java)."""
    rng = SeqRNG([200, 0])
    party = _party()
    party.members[0].submorsels = 400
    state = DungeonState(_dmap(), start_x=4, start_y=4, start_z=0, party=party, rng=rng)
    state.torchtime = 50
    evt = getattr(state, turn)()
    assert state.torchtime == 49
    assert party.members[0].submorsels == 390
    assert evt.type == DungeonEventType.COMBAT


@pytest.mark.parametrize("tile", [DungeonTile.DOOR, DungeonTile.SECRET_DOOR])
@pytest.mark.parametrize("turn", ["turn_left", "turn_right"])
def test_right_left_no_turning_in_a_doorway(tile, turn):
    """UltimaDngn.c:382-408: `if (GetXYDng(xs, ys) >= 0xA0) { NoGo(); return; }`
    a party standing on a door (0xC0) or secret door (0xA0) cannot turn."""
    dmap = _dmap()
    dmap.set_tile(4, 4, 0, tile)
    state = DungeonState(dmap, start_x=4, start_y=4, start_z=0, party=_party(),
                         start_dir=Direction.NORTH, random_encounters=False)
    evt = getattr(state, turn)()
    assert state.dir == Direction.NORTH
    assert evt.type == DungeonEventType.BLOCKED


def test_dungeon_screen_z_and_m_take_the_turn(asset_mgr):
    """UltimaDngn.c:146, 159, 161: M (ModifyOrder) and Z (Stats) go to
    dungeonmech too. The port's dungeon Z and M were free (Java)."""
    import pygame

    from py_exodus.screens.dungeon_screen import DungeonScreen

    pygame.init()
    party = _party()
    screen = DungeonScreen(party=party, dungeon_map=_dmap(), asset_mgr=asset_mgr)
    screen.state.random_encounters_enabled = False
    screen.state.torchtime = 50
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z))
    assert screen.state.torchtime == 49
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m))
    screen.text_log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1"))
    screen.text_log.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2, unicode="2"))
    assert screen.state.torchtime == 48


# --- D-06 entering --------------------------------------------------------------


def test_enter_dungeon_faces_east(asset_mgr):
    """UltimaMain.c:1430-1433: `dungeonLevel = 0; xpos = 1; ypos = 1;
    heading = 1;` (HeadX/HeadY 72: heading 1 is east). The port faced north."""
    import pygame

    from py_exodus.screens.dungeon_screen import DungeonScreen

    pygame.init()
    screen = DungeonScreen(party=_party(), dungeon_map=_dmap(), asset_mgr=asset_mgr)
    assert (screen.state.x, screen.state.y, screen.state.z) == (1, 1, 0)
    assert screen.state.dir == Direction.EAST


def test_autoplay_route_does_not_turn_in_a_doorway():
    """Autoplay follows D-04 (UltimaDngn.c:386, 400): standing on a door it
    steps back out with DOWN rather than pressing a turn that is refused."""
    import pygame

    from py_exodus.autoplay.nav import find_dungeon_step

    dmap = _dmap(DungeonTile.WALL)
    for y in range(3, 7):
        dmap.set_tile(4, y, 0, DungeonTile.NOTHING)
    dmap.set_tile(4, 4, 0, DungeonTile.DOOR)
    dmap.set_tile(4, 3, 0, DungeonTile.WALL)
    key = find_dungeon_step(dmap, 4, 4, 0, Direction.NORTH, {(4, 6, 0)})
    assert key == pygame.K_DOWN


# --- D-07 fountains: CheckAlive ---------------------------------------------------


@pytest.mark.parametrize("tile", [DungeonTile.FOUNTAIN_HEAL, DungeonTile.FOUNTAIN_CURE])
@pytest.mark.parametrize("status", [Status.DEAD, Status.ASHES])
def test_fountain_drinker_must_be_alive(tile, status):
    """UltimaDngn.c:237-241: `if (CheckAlive(chnum - 1) == FALSE) {
    UPrintMessage(153); ...}` ("Can't"): the dead and ashes cannot drink.
    The port healed a dead drinker to full HP and the cure fountain set a
    dead one back to Good."""
    party = _party()
    m = party.members[0]
    m.status = status
    m.hp = 0
    dmap = _dmap()
    dmap.set_tile(4, 4, 0, tile)
    state = DungeonState(dmap, start_x=4, start_y=4, start_z=0, party=party)
    evt = state.drink_fountain(0)
    assert m.status == status
    assert m.hp == 0
    assert evt.success is False
    assert evt.message == "Can't"


# --- D-19 dungeon chests: CheckAlive -------------------------------------------


@pytest.mark.parametrize("status", [Status.DEAD, Status.ASHES])
def test_getchest_dungeon_opener_must_be_alive(status, asset_mgr):
    """UltimaMain.c:1601-1604: `if (CheckAlive(chnum - 1) == FALSE) {
    Incap(); return; }` before the tile is even looked at, in the dungeon
    as on the surface. The port's dungeon G opened it for a dead member."""
    import pygame

    from py_exodus.screens.dungeon_screen import DungeonScreen

    pygame.init()
    party = _party()
    party.members[0].status = status
    dmap = _dmap()
    dmap.set_tile(1, 1, 0, DungeonTile.CHEST)
    screen = DungeonScreen(party=party, dungeon_map=dmap, asset_mgr=asset_mgr)
    screen.state.random_encounters_enabled = False
    gold = party.members[0].gold
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g))
    screen.text_log.submit_input("1")
    assert dmap.get_tile(1, 1, 0) == DungeonTile.CHEST
    assert party.members[0].gold == gold
    assert any("Incapacitated" in line for line in screen.text_log.history)


def test_dungeon_open_chest_opener_must_be_alive():
    """UltimaMain.c:1601-1604 (CheckAlive) on the search path's chest too."""
    party = _party()
    party.members[0].status = Status.DEAD
    dmap = _dmap()
    dmap.set_tile(4, 4, 0, DungeonTile.CHEST)
    state = DungeonState(dmap, start_x=4, start_y=4, start_z=0, party=party)
    evt = state.open_chest(0)
    assert dmap.get_tile(4, 4, 0) == DungeonTile.CHEST
    assert evt.success is False


# --- D-08 the dungeon map's bytes decide, not the 2015 labels ----------------


def _load_dungeon(asset_mgr, map_id):
    from py_exodus.world.loader import MapLoader

    return MapLoader(asset_mgr).load_map(map_id)


def test_getxydng_writing_stays_writing(asset_mgr):
    """UltimaDngn.c:196, 334-338: GetXYDng decides; byte 8 is Misty Writing
    ("Don't drink!" on the Snake dungeon's fifth level). The port's
    maps.xml label FOUNTAIN_POISON turned (9, 9, 4) into a poison fountain."""
    dmap = _load_dungeon(asset_mgr, 19)
    assert dmap.get_tile(9, 9, 4) == DungeonTile.MISTY_WRITINGS


def test_mark_kind_follows_xpos_and_3(asset_mgr):
    """UltimaDngn.c:311: `Player[rosNum][14] |= bits[(xpos & 3) + 4];` the
    mark is x & 3 (0 Force, 1 Fire, 2 Snake, 3 Kings) for every mark tile.
    The Time dungeon's (11, 15, 7) is labelled MARK_FIRE; 11 & 3 is Kings."""
    dmap = _load_dungeon(asset_mgr, 20)
    assert dmap.get_tile(11, 15, 7) == DungeonTile.MARK_KINGS
    kinds = (DungeonTile.MARK_FORCE, DungeonTile.MARK_FIRE,
             DungeonTile.MARK_SNAKE, DungeonTile.MARK_KINGS)
    for map_id in range(14, 21):
        dmap = _load_dungeon(asset_mgr, map_id)
        for z in range(8):
            for y in range(16):
                for x in range(16):
                    tile = dmap.get_tile(x, y, z)
                    if tile in kinds or tile == DungeonTile.MARK:
                        assert tile == kinds[x & 3], (map_id, x, y, z)


# --- D-14 Ignite --------------------------------------------------------------------


def _torch_screen(asset_mgr, party):
    import pygame

    from py_exodus.screens.dungeon_screen import DungeonScreen

    pygame.init()
    screen = DungeonScreen(party=party, dungeon_map=_dmap(), asset_mgr=asset_mgr)
    screen.state.random_encounters_enabled = False
    return screen


def _press_i(screen, who: str) -> None:
    import pygame

    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i))
    screen.text_log.submit_input(who)


def test_ignite_asks_whose_torch(asset_mgr):
    """UltimaMain.c:1962-1973: "Whose torch-", GetChar, that member's torch
    (byte 15) goes: `Player[rosNum][15]--; gTorch = 255;`. The port burned
    the first member's torch without asking."""
    party = _party()
    party.members[0].torches = 3
    party.members[1].torches = 2
    screen = _torch_screen(asset_mgr, party)
    _press_i(screen, "2")
    assert (party.members[0].torches, party.members[1].torches) == (3, 1)
    assert screen.state.torchtime == 254  # 255, then dungeonmech burns one


def test_ignite_none_left(asset_mgr):
    """UltimaMain.c:1967-1970: `if (Player[rosNum][15] < 1) { UPrintMessage(67);
    return; }` ("None left!"): nothing lit, even if another member has one."""
    party = _party()
    party.members[0].torches = 3
    party.members[1].torches = 0
    screen = _torch_screen(asset_mgr, party)
    _press_i(screen, "2")
    assert screen.state.torchtime == 0
    assert party.members[0].torches == 3
    assert any("None left" in line for line in screen.text_log.history)


def test_ignite_while_lit_lights_a_fresh_torch(asset_mgr):
    """UltimaMain.c:1955-1974: Ignite never puts a torch out; another torch
    sets gTorch back to 255. The port's I put a lit torch out (Java toggle)."""
    party = _party()
    party.members[0].torches = 3
    screen = _torch_screen(asset_mgr, party)
    screen.state.torchtime = 40
    _press_i(screen, "1")
    assert screen.state.torchtime == 254
    assert party.members[0].torches == 2
