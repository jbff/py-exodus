"""LairWare parity, batch M (monsters outside combat).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "M - Monsters".
"""
from __future__ import annotations

import random

import pygame
import pytest

from py_exodus.aura import AuraType
from py_exodus.constants import Profession, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.world.map import MapNpc


def _member(name: str = "Hero", hp: int = 200, max_hp: int = 300) -> Character:
    return Character(
        name=name,
        profession=Profession.FIGHTER,
        hp=hp,
        max_hp=max_hp,
        mp=0,
        max_mp=0,
        food=150,
        gold=100,
        status=Status.GOOD,
    )


def _party(*members: Character) -> Party:
    party = Party()
    for m in members or (_member(),):
        party.add_member(m)
    for m in party.members:
        m.submorsels = 400  # no meal crossing inside a short test
    return party


def _key(screen, k: int) -> None:
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=""))


@pytest.fixture
def overworld(pygame_setup, asset_mgr):
    from py_exodus.screens.overworld import OverworldScreen

    def make(x: int, y: int, party: Party | None = None, encounters: bool = False,
             clear: bool = True):
        scr = OverworldScreen(
            party=party or _party(),
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=x,
            start_y=y,
            random_encounters=encounters,
        )
        scr.party.x, scr.party.y = x, y
        scr.party.objects_map_id = 0
        if clear:
            scr.creatures = []
        scr._check_moongates = lambda: None  # type: ignore[method-assign]
        return scr

    return make


class _Rolls:
    """random.randint stand-in: answers by bounds from a table of queues.

    ``table[(a, b)]`` is a list; each call pops the first value, and the last
    value repeats once the list is down to one. Unlisted bounds return ``a``.
    """

    def __init__(self, table: dict[tuple[int, int], list[int]]) -> None:
        self.table = {k: list(v) for k, v in table.items()}
        self.calls: list[tuple[int, int]] = []

    def __call__(self, a: int, b: int) -> int:
        self.calls.append((a, b))
        q = self.table.get((a, b))
        if not q:
            return a
        return q.pop(0) if len(q) > 1 else q[0]


def _monster(kind: str, x: int, y: int, **extra) -> dict:
    return {"name": kind.capitalize(), "tile_name": kind, "tile": kind, "x": x, "y": y, **extra}


def _whirlpools(scr) -> list[dict]:
    return [c for c in scr.creatures if c.get("tile_name") == "whirlpool"]


# --- M-03: spawn start terrain ----------------------------------------------


def test_spawnmonster_start_terrain_is_plain_water_or_grass_without_objects(
    overworld, monkeypatch
):
    """UltimaMisc.c:1165-1180 (SpawnMonster):

        Monsters[offset + TILEON] = MonBegin[type];
        ...
        if (GetXYVal(Monsters[offset + XMON], Monsters[offset + YMON]) != Monsters[offset + TILEON]) {
            Monsters[offset] = 0;
            goto spawn;

    MonBegin is 0 (water) for the sea types and 4 (grass) for the land types,
    and the map value must equal it exactly: a sea monster never starts on a
    snake tile, and nothing starts on a parked ship (0x2C), a horse (0x28) or
    a dropped chest (0x24), which are map values of their own in LairWare.
    """
    ow = overworld(20, 20)
    snake = ow.game_map.get_tile(10, 57)
    water = ow.game_map.get_tile(10, 56)
    rolls = _Rolls({(0, 12): [6]})  # 6 & 6 = type 6, the Sea Serpent
    monkeypatch.setattr(random, "randint", rolls)
    assert ow._pick_creature_for_tile(water) == "serpent"
    assert ow._pick_creature_for_tile(snake) is None

    # A parked frigate at (10, 56): the serpent cannot start there.
    ow.party.dynamic_objects = [{"tile": "frigate", "x": 10, "y": 56}]
    rolls = _Rolls({(0, 134): [134], (0, 63): [10, 56] * 40, (0, 12): [6], (0, 1): [0]})
    monkeypatch.setattr(random, "randint", rolls)
    ow._spawn_wandering_creature()
    assert ow.creatures == []
    # Without the frigate the same rolls place it.
    ow.party.dynamic_objects = []
    ow._spawn_wandering_creature()
    assert [(c["tile_name"], c["x"], c["y"]) for c in ow.creatures] == [("serpent", 10, 56)]


# --- M-04: monster terrain ----------------------------------------------------


def test_validmonsterdir_land_and_sea_terrain(overworld, asset_mgr):
    """UltimaMisc.c:263-272 (ValidMonsterDir):

        if (montype > 0x28 && montype < 0x40) {   // pirate/sea monster
            return (tile == 0) ? 0 : 255;
        } else {
            if (tile == 4 || tile == 8 || tile == 12 || tile == 32)
                return 0;

    Land monsters walk only on grass, brush, forest and floor; the serpent,
    Man-O-War and pirate only on plain water. Lava, snakes and the tiles of a
    parked ship, horse or dropped chest are closed to them.
    """
    ow = overworld(20, 20)
    orc = _monster("orc", 49, 36)
    orc_def = asset_mgr.get_creature("orc")
    assert ow._creature_can_enter(orc, orc_def, 49, 37) is False  # mountains
    assert ow._creature_can_enter(orc, orc_def, 48, 36) is True  # forest
    assert ow._creature_can_enter(orc, orc_def, 48, 35) is False  # lava
    ow.party.dynamic_objects = [{"tile": "chest", "x": 48, "y": 36}]
    assert ow._creature_can_enter(orc, orc_def, 48, 36) is False  # dropped chest

    serpent = _monster("serpent", 10, 56)
    s_def = asset_mgr.get_creature("serpent")
    assert ow._creature_can_enter(serpent, s_def, 10, 55) is True  # water
    assert ow._creature_can_enter(serpent, s_def, 10, 57) is False  # snake
    pirate = _monster("pirate", 10, 56)
    p_def = asset_mgr.get_creature("pirate")
    ow.party.dynamic_objects = [{"tile": "frigate", "x": 10, "y": 55}]
    assert ow._creature_can_enter(pirate, p_def, 10, 55) is False  # parked ship


# --- M-08: after Exodus falls new wanderers are harmless ------------------------


def test_spawnmonster_after_exodus_spawns_wanderers(overworld, monkeypatch):
    """UltimaMisc.c:1177-1184 (SpawnMonster):

        Monsters[offset + HPMON] = 0xC0;
        ...
        if (Party[16] != 0 && Monsters[offset] != 0x3C)
            Monsters[offset + HPMON] = 0x40;

    Once Exodus has fallen a new monster wanders (0x40), except the pirate
    (0x3C), which still hunts (0xC0).
    """
    ow = overworld(20, 20)
    ow.party.exodus_defeated = True
    # Orc (type 0) on grass at (49, 36).
    monkeypatch.setattr(random, "randint", _Rolls(
        {(0, 134): [134], (0, 63): [49, 36], (0, 12): [0], (0, 1): [0]}))
    ow._spawn_wandering_creature()
    assert ow.creatures[-1]["tile_name"] == "orc"
    assert ow.creatures[-1].get("wander") is True
    # Pirate (type 10) on water at (10, 56).
    monkeypatch.setattr(random, "randint", _Rolls(
        {(0, 134): [134], (0, 63): [10, 56], (0, 12): [10], (0, 1): [0]}))
    ow._spawn_wandering_creature()
    assert ow.creatures[-1]["tile_name"] == "pirate"
    assert not ow.creatures[-1].get("wander")


def test_movemonsters_wanderer_never_attacks(overworld, monkeypatch):
    """UltimaMisc.c:1280-1294, 1325-1326 and 1213-1217 (MoveMonsters):

        if (value == 0x40) {
            if (RandNum(0, 255) < 128)
                goto movemon;
            xs = MapConstrain(Monsters[offset + XMON] + GetHeading(RandNum(0, 255)));
            ...
            goto move7AAA;
        ...
        if (xpos == xs && ypos == ys)
            goto movemon;

    A wandering monster takes a random step half the turns and never steps
    onto the party, so it never starts a fight; a hunter (0xC0, any monster
    out before Exodus fell) still attacks from the next tile.
    """
    ow = overworld(49, 36, encounters=False)
    ow.party.exodus_defeated = True
    fights: list[str] = []
    monkeypatch.setattr(ow, "_trigger_combat", lambda name, c=None: fights.append(name))
    # A wanderer due east of the party; its roll would step west onto the party.
    ow.creatures = [_monster("orc", 50, 36, wander=True)]
    monkeypatch.setattr(random, "randint", _Rolls({(0, 255): [200, 200, 0]}))
    ow._update_creatures()
    assert fights == []
    assert (ow.creatures[0]["x"], ow.creatures[0]["y"]) == (50, 36)
    # The same orc as a hunter attacks.
    ow.creatures = [_monster("orc", 50, 36)]
    ow._update_creatures()
    assert fights == ["orc"]


def test_moveshoot_fires_after_exodus_falls(overworld, monkeypatch):
    """UltimaMisc.c:1195-1201, 1240-1248, 1324-1328 (MoveMonsters):

        if (Party[3] == 0 && Party[16] == 0) {    // Player hasn't beaten Exodus.
        moveoutside:
        ...
        if (Monsters[offset] == 0x3C || Monsters[offset] == 0x74)
            goto moveshoot;
        ...
        if (value != 0x40 && value != 0x80)
            goto moveoutside;

    After Exodus falls a hunting monster (0xC0) still takes the moveoutside
    path, so pirates and dragons still fire; the port stopped every shot.
    """
    party = _party()
    party.transport = Transport.SHIP
    ow = overworld(20, 1, party=party, encounters=False)
    ow.party.exodus_defeated = True
    ow.creatures = [_monster("pirate", 23, 1)]
    monkeypatch.setattr(random, "randint", _Rolls({(0, 255): [0]}))
    ow._update_creatures()
    assert (ow.creatures[0]["x"], ow.creatures[0]["y"]) == (22, 1)
    assert party.members[0].hp == 200 - 8  # BombTrap: (0 & 0x77) + 8


# --- M-11: stopped time freezes town people -------------------------------------


def test_finishall_stopped_time_freezes_town_people(pygame_setup, asset_mgr):
    """UltimaMisc.c:1120-1125 (FinishAll), run from Routine6E35 in towns too:

        if (gTimeNegate != 0) {
            gTimeNegate--;
            return;
        }
        SpawnMonster();
        MoveMonsters();

    While time is stopped nobody in a town or castle moves.
    """
    from py_exodus.screens.town import TownScreen

    tw = TownScreen(party=_party(), map_id=3, asset_mgr=asset_mgr, start_x=32, start_y=32)
    gm = tw.game_map
    spot = next(
        (x, y) for y in range(2, 60) for x in range(2, 60)
        if all(gm.get_tile(x + i, y).name == "floor" for i in range(4))
    )
    x, y = spot
    tw.avatar_x, tw.avatar_y = x, y
    follower = MapNpc(tile_index=0, tile_name="cleric", x=x + 3, y=y, start_x=x + 3,
                      start_y=y, movement="FOLLOW_AVATAR")
    gm.npcs = [follower]
    tw.party.aura.set(AuraType.QUICKNESS, 10)
    tw._finish_turn(None)
    assert (follower.x, follower.y) == (x + 3, y)
    tw.party.aura.set(AuraType.NONE, 0)
    tw._finish_turn(None)
    assert (follower.x, follower.y) == (x + 2, y)


# --- M-13: one whirlpool, LairWare's drift --------------------------------------


def test_whirlpool_single_lairware_start(overworld):
    """UltimaMisc.c:913-917 (LoadUltimaMap) with the Sosaria map resource
    MAPS 420, whose four bytes after the 64x64 grid are 47, 17, 1, 1:

        WhirlX = *(*gCurrentMap + mapLength + 1);
        WhirlY = *(*gCurrentMap + mapLength + 2);
        WhirlDX = *(*gCurrentMap + mapLength + 3);
        WhirlDY = *(*gCurrentMap + mapLength + 4);

    Sosaria has one whirlpool, starting at (47, 17) heading (+1, +1); the
    port (Java) had two, at (50, 13) and (17, 48).
    """
    ow = overworld(20, 20, clear=False)
    wps = _whirlpools(ow)
    assert [(c["x"], c["y"]) for c in wps] == [(47, 17)]
    assert tuple(wps[0]["dir"]) == (1, 1)


def test_whirlpool_drifts_on_its_heading(overworld, monkeypatch):
    """UltimaMain.c:65-66, 2973-3013 (WhirlPool):

        const char WhirlXtable[8] = {0,1,1,1,0,-1,-1,-1};
        const char WhirlYtable[8] = {1,1,0,-1,-1,-1,0,1};
        byte = RandNum(0, 7);
        if (byte == 0)
            goto Whirl1;
        newx = MapConstrain(WhirlX + WhirlDX);
        newy = MapConstrain(WhirlY + WhirlDY);
        byte = GetXYVal(newx, newy);
        if (byte == 0)
            goto Whirl2;
        if (byte != 0x2C)
            goto Whirl1;
        PutXYVal(0x30, newx, newy);   (a parked ship sinks: message 110)
        ...
    Whirl1:
        byte = RandNum(0, 7);
        WhirlDX = WhirlXtable[byte];
        WhirlDY = WhirlYtable[byte];

    Seven times in eight the whirlpool moves one tile on its heading (any of
    eight directions) onto open water; one time in eight, or when the tile
    ahead is not open water, it stays and takes a new heading. It runs over
    a parked ship, which is destroyed.
    """
    ow = overworld(20, 20)
    wp = _monster("whirlpool", 47, 17, dir=[1, 1], wontattack=True)
    ow.creatures = [wp]
    # Moves on its heading.
    monkeypatch.setattr(random, "randint", _Rolls({(0, 7): [3]}))
    ow._move_whirlpool()
    assert (wp["x"], wp["y"]) == (48, 18)
    # One in eight: new heading from the table, no move.
    monkeypatch.setattr(random, "randint", _Rolls({(0, 7): [0, 5]}))
    ow._move_whirlpool()
    assert (wp["x"], wp["y"]) == (48, 18)
    assert tuple(wp["dir"]) == (-1, -1)
    # Land ahead: stays, new heading.
    wp["x"], wp["y"], wp["dir"] = 49, 19, [1, 1]  # (50, 20) is grass
    monkeypatch.setattr(random, "randint", _Rolls({(0, 7): [3, 2]}))
    ow._move_whirlpool()
    assert (wp["x"], wp["y"]) == (49, 19)
    assert tuple(wp["dir"]) == (1, 0)
    # A monster ahead also turns it.
    wp["x"], wp["y"], wp["dir"] = 47, 17, [1, 1]
    ow.creatures.append(_monster("serpent", 48, 18))
    monkeypatch.setattr(random, "randint", _Rolls({(0, 7): [3, 4]}))
    ow._move_whirlpool()
    assert (wp["x"], wp["y"]) == (47, 17)
    assert tuple(wp["dir"]) == (0, -1)
    ow.creatures.pop()
    # A parked ship ahead sinks.
    wp["dir"] = [1, 1]
    ow.party.dynamic_objects = [{"tile": "frigate", "x": 48, "y": 18}]
    monkeypatch.setattr(random, "randint", _Rolls({(0, 7): [3]}))
    ow._move_whirlpool()
    assert (wp["x"], wp["y"]) == (48, 18)
    assert ow.party.dynamic_objects == []
    assert any("ship was destroyed" in str(m) for m in ow.text_log.lines)


# --- M-14: the whirlpool is not part of FinishAll ---------------------------------


def test_whirlpool_moves_every_turn_aboard_ship_and_in_stopped_time(overworld, monkeypatch):
    """UltimaMain.c:1042-1043 (main loop) and 2959-3013 (WhirlPool):

        while (count > 0) {
            WhirlPool();

    WhirlPool runs from the key-wait loop, not from FinishAll
    (UltimaMisc.c:1112-1126), so neither the mounted every-other-turn flip
    nor stopped time holds it, and its engulf check (Whirl3) runs whenever it
    moves. The port moves it once per turn.
    """
    party = _party()
    party.transport = Transport.SHIP
    ow = overworld(20, 1, party=party)
    moves: list[int] = []
    monkeypatch.setattr(ow, "_move_whirlpool", lambda: moves.append(1))
    for _ in range(10):
        _key(ow, pygame.K_SPACE)
    assert len(moves) == 10
    ow.party.aura.set(AuraType.QUICKNESS, 10)
    for _ in range(3):
        _key(ow, pygame.K_SPACE)
    assert len(moves) == 13


def test_whirlpool_engulfs_ship_in_stopped_time_and_on_its_own_move(overworld, monkeypatch):
    """UltimaMain.c:3010-3012 (WhirlPool, Whirl3) and UltimaMisc.c:1373-1376
    (Routine6E35):

        if ((WhirlX == xpos) && (WhirlY == ypos)) { /* Whirlpool hit party */
            GoWhirlPool();
        ...
        if (temp == 48)
            GoWhirlPool();

    The whirlpool takes the ship when it drifts onto it, and stopped time
    does not stop it.
    """
    party = _party()
    party.transport = Transport.SHIP
    ow = overworld(48, 18, party=party)
    ow.creatures = [_monster("whirlpool", 47, 17, dir=[1, 1], wontattack=True)]
    ow.party.aura.set(AuraType.QUICKNESS, 10)
    monkeypatch.setattr(random, "randint", _Rolls({(0, 7): [3]}))
    ow._update_creatures()
    assert ow.map_id == 13
    assert party.whirlpool_return == (48, 18)


# --- M-15: Sosaria's monsters wait out the Ambrosia trip ---------------------------


def test_pushsosaria_keeps_monsters_and_whirlpool_through_ambrosia(overworld):
    """UltimaMain.c:3041-3053, 3080-3093 (GoWhirlPool) and UltimaMisc.c:923-968
    (PushSosaria/PullSosaria):

        WhirlX = 2;
        WhirlY = 0x3E;
        Party[1] = 0x16; /* frigate */
        PushSosaria();
        ...
        PullSosaria();

    The engulfing whirlpool is moved to (2, 62) and the Sosaria map, with
    its monsters and the whirlpool, is put aside and brought back on the
    return. The port re-seeded fresh wanderers and Java's whirlpools.
    """
    from py_exodus.world import portal_entry

    party = _party()
    party.transport = Transport.SHIP
    ow = overworld(30, 1, party=party)
    orc = _monster("orc", 49, 36)
    ow.creatures = [_monster("whirlpool", 30, 1, dir=[0, 1], wontattack=True), orc]
    ow._check_whirlpool_engulf()
    assert ow.map_id == 13
    assert portal_entry.step_in_whirlpool_portal(ow, 32, 58)
    assert ow.map_id == 0
    kept = sorted((c["tile_name"], c["x"], c["y"]) for c in ow.creatures)
    assert kept == [("orc", 49, 36), ("whirlpool", 2, 62)]


# --- M-16: the save keeps every monster ------------------------------------------


def test_putsosaria_saves_every_monster(overworld, monkeypatch, tmp_path):
    """UltimaMisc.c:839-857 (PutSosaria):

        *(*gCurrentMap + mapLength + 1) = (unsigned char)(WhirlX & 0xFF);
        ...
        for (mark = 0; mark < 256; mark++) {
            *(*gCurrentMon + mark) = Monsters[mark];

    The whole 32-slot monster table and the whirlpool (place and heading)
    are saved; the port (Java) kept only the first 8 creatures.
    """
    from py_exodus import save_system

    ow = overworld(20, 20)
    ow.creatures = [_monster("whirlpool", 47, 17, dir=[-1, 0], wontattack=True)]
    ow.creatures += [_monster("orc", 30 + i, 40, variant=1) for i in range(11)]
    ow.creatures.append(_monster("thief", 5, 5, wander=True))
    saved: dict = {}
    monkeypatch.setattr(save_system.SaveSystem, "save_game",
                        staticmethod(lambda party, path, extra=None: saved.update(extra or {})))
    ow._save_game()
    block = saved["overworld"]["monsters"]
    assert len(block) == 13
    assert block[0]["dir"] == [-1, 0]
    assert block[-1]["wander"] is True

    ow2 = overworld(20, 20, clear=False)
    ow2._restore_world_state({"monsters": block})
    assert len(ow2.creatures) == 13
    assert tuple(_whirlpools(ow2)[0]["dir"]) == (-1, 0)
    assert ow2.creatures[-1].get("wander") is True


def test_restore_old_save_block_with_two_java_whirlpools(overworld):
    """Old saves (before batch M) hold Java's two whirlpools without a
    heading and no ``wander`` flags. They still load: the first whirlpool is
    LairWare's one (heading (+1, +1), the map resource's), the second is
    dropped, and every monster hunts (0xC0, as LairWare's monsters out
    before Exodus fell)."""
    block = [
        {"name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool", "x": 50, "y": 13},
        {"name": "Whirlpool", "tile_name": "whirlpool", "tile": "whirlpool", "x": 17, "y": 48},
        {"name": "Orc", "tile_name": "orc", "tile": "orc", "x": 49, "y": 36, "hp": 12},
    ]
    ow = overworld(20, 20, clear=False)
    ow._restore_world_state({"monsters": block})
    wps = _whirlpools(ow)
    assert [(c["x"], c["y"]) for c in wps] == [(50, 13)]
    assert tuple(wps[0]["dir"]) == (1, 1)
    orc = next(c for c in ow.creatures if c["tile_name"] == "orc")
    assert not orc.get("wander") and orc["hp"] == 12
    # A block with no whirlpool gets LairWare's start one.
    ow._restore_world_state({"monsters": block[2:]})
    assert [(c["x"], c["y"]) for c in _whirlpools(ow)] == [(47, 17)]
