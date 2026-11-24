"""LairWare parity, batch T (the turn: movement, food, aging, healing).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "T - Turn".
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.aura import AuraType
from py_exodus.constants import Direction, Profession, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.ui.renderer import can_move_to


def _member(name: str = "Hero", hp: int = 200, status: Status = Status.GOOD) -> Character:
    return Character(
        name=name,
        profession=Profession.FIGHTER,
        hp=hp,
        max_hp=300,
        mp=0,
        max_mp=0,
        food=150,
        gold=100,
        status=status,
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

    def make(x: int, y: int, party: Party | None = None, encounters: bool = False):
        scr = OverworldScreen(
            party=party or _party(),
            map_id=0,
            asset_mgr=asset_mgr,
            start_x=x,
            start_y=y,
            random_encounters=encounters,
        )
        scr.party.x, scr.party.y = x, y
        scr.creatures = []
        scr._check_moongates = lambda: None  # type: ignore[method-assign]
        return scr

    return make


@pytest.fixture
def town(pygame_setup, asset_mgr):
    from py_exodus.screens.town import TownScreen

    def make(map_id: int, x: int, y: int, party: Party | None = None):
        scr = TownScreen(
            party=party or _party(),
            map_id=map_id,
            asset_mgr=asset_mgr,
            start_x=x,
            start_y=y,
        )
        scr.game_map.npcs = []
        return scr

    return make


# --- T-03: a refused step still costs the turn -------------------------------


def test_nogo_blocked_step_still_takes_the_turn(overworld, town):
    """UltimaMain.c:1203-1215 (North) and 1057-1091 (main loop):

        if (ValidDir(GetXYVal(xpos, ypos - 1)) == 0) {
            NoGo();
        ...
            case 30: North(); break;
        ...
        Routine6E35();

    A refused step prints INVALID MOVE! and the main loop still runs
    Routine6E35 (IncMoves, AgeChars, FinishAll): the turn passes, on the
    surface and in towns alike.
    """
    ow = overworld(12, 6)  # mountains at (12, 5)
    _key(ow, pygame.K_UP)
    assert (ow.party.x, ow.party.y) == (12, 6)
    assert ow.party.moves == 1
    assert ow.party.members[0].submorsels == 400 - 40

    tw = town(3, 1, 1)
    # Wall the party in on the north side.
    blocked = next(
        (x, y)
        for y in range(2, 63)
        for x in range(1, 63)
        if tw.game_map.get_tile(x, y - 1).name == "wall"
        and tw.game_map.get_tile(x, y).walkable
    )
    tw.avatar_x, tw.avatar_y = blocked
    _key(tw, pygame.K_UP)
    assert (tw.avatar_x, tw.avatar_y) == blocked
    assert tw.party.moves == 1


def test_validtrans_wind_refusal_still_takes_the_turn(overworld):
    """UltimaMain.c:3222-3236 (ValidTrans) and 1203-1207 (North):

        if (ValidTrans(1) == 0) {
            NoGo();

    A ship that the wind will not let sail is refused through the same NoGo,
    and the main loop's Routine6E35 still passes the turn.
    """
    ow = overworld(4, 1)
    ow.party.transport = Transport.SHIP
    ow.party.wind_direction = None  # becalmed
    _key(ow, pygame.K_UP)
    assert (ow.party.x, ow.party.y) == (4, 1)
    assert ow.party.moves == 1


# --- T-06: lava burns on the step onto it ------------------------------------


def test_validdir_lava_burns_on_entry_not_while_standing(overworld):
    """UltimaMain.c:3194-3207 (ValidDir):

        if (value == 132) { /* Lava */
            GoodPlace = TRUE;
            ...
                if (!(Player[byte2][14] & 0x20)) {
                    if ((Player[byte2][17] == 'G') || (Player[byte2][17] == 'P')) {
                        HPSubtract(Party[byte + 7], 50);

    Lava hurts when the party steps onto it (ValidDir checks the tile being
    entered); nothing hurts a party that stands or passes on it.
    """
    marked = _member("Marked")
    marked.marks[1] = 1  # Mark of Fire
    party = _party(_member("Bare"), marked)
    ow = overworld(49, 35, party)  # lava at (50, 35)
    bare = party.members[0]

    _key(ow, pygame.K_RIGHT)
    assert (ow.party.x, ow.party.y) == (50, 35)
    assert bare.hp == 150  # 50 on the step itself
    assert party.members[1].hp == 200  # the Mark of Fire

    _key(ow, pygame.K_SPACE)
    assert bare.hp == 150  # standing on lava does nothing

    _key(ow, pygame.K_LEFT)  # stepping off onto grass
    assert bare.hp == 150


# --- T-10: towns are left on reaching row or column 0 -------------------------


def test_routine6e35_town_exit_on_row_or_column_zero(town):
    """UltimaMisc.c:1365-1369 (Routine6E35):

        if (Party[3] > 1) { /* Town or castle, IOW */
            if (xpos == 0 || ypos == 0) {
                Routine6E6B();

    In a town the party leaves as soon as the step lands it on column 0 or
    row 0, not one step later.
    """
    for start, k in (((1, 32), pygame.K_LEFT), ((32, 1), pygame.K_UP)):
        tw = town(3, *start)
        left: list[bool] = []
        tw._exit_town = lambda: left.append(True)  # type: ignore[method-assign]
        _key(tw, k)
        assert left == [True], start
        assert tw.party.moves == 1  # the exit step is a turn (Routine6E35)


# --- T-11: monsters move every other turn on horse and ship ------------------


def test_finishall_runs_every_other_turn_on_horse_or_ship(overworld):
    """UltimaMisc.c:1112-1126 (FinishAll):

        if (Party[1] == 0x14 || Party[1] == 0x16) {
            zp[0xCD] = 255 - zp[0xCD];
            if (zp[0xCD] < 128)
                return;
        }
        ...
        SpawnMonster();
        MoveMonsters();

    On horseback (0x14) or aboard ship (0x16), spawning and monster moves run
    on every other turn; on foot, every turn.
    """
    for transport, expected in (
        (Transport.FOOT, 10),
        (Transport.HORSE, 5),
        (Transport.SHIP, 5),
    ):
        ow = overworld(10, 10, encounters=True)
        ow.party.transport = transport
        calls: list[int] = []
        ow._spawn_wandering_creature = lambda: calls.append(1)  # type: ignore[method-assign]
        for _ in range(10):
            _key(ow, pygame.K_SPACE)
        assert len(calls) == expected, transport


# --- T-12: stopped time stops spawning too -----------------------------------


def test_finishall_negated_time_skips_spawn(overworld):
    """UltimaMisc.c:1120-1125 (FinishAll):

        if (gTimeNegate != 0) {
            gTimeNegate--;
            return;
        }
        SpawnMonster();
        MoveMonsters();

    While time is stopped neither the spawn nor the monster moves run.
    """
    ow = overworld(10, 10, encounters=True)
    calls: list[int] = []
    ow._spawn_wandering_creature = lambda: calls.append(1)  # type: ignore[method-assign]
    ow.party.aura.set(AuraType.QUICKNESS, 10)
    for _ in range(3):
        _key(ow, pygame.K_SPACE)
    assert calls == []


# --- T-19: ashes neither eat nor sicken --------------------------------------


def test_agechars_skips_dead_and_ashes(monkeypatch):
    """UltimaMisc.c:1449-1452 (AgeChars):

        temp = Player[rosNum][17];
        if ((temp == 'D') || (temp == 'A') || (temp == 0)) {
        } else {
            EatFood(x, 10);

    Dead members and ashes eat nothing (and take no poison or regen).
    """
    ash = _member("Ash", hp=0, status=Status.ASHES)
    party = _party(_member("Live"), ash)
    for _ in range(11):  # one surface meal crossing (40 per turn)
        party.end_turn(surface=True)
    assert party.members[0].food == 149
    assert ash.food == 150
    assert ash.submorsels == 400


# --- T-22: ashes are not alive -----------------------------------------------


def test_checkalive_ashes_are_not_alive():
    """UltimaMain.c:2895-2903 (CheckAlive) and 2786-2798 (CheckAllDead):

        if (Player[rosNum][17] == 'G')
            return TRUE;
        if (Player[rosNum][17] == 'P')
            return TRUE;
        return FALSE;

    Only Good or Poisoned members are alive; a party of the dead and ashes is
    "ALL PLAYERS OUT!".
    """
    party = _party(
        _member("Ash", hp=0, status=Status.ASHES),
        _member("Dead", hp=0, status=Status.DEAD),
    )
    assert not party.is_anyone_alive()
    assert party.is_party_dead()
    party.members[1].status = Status.POISONED
    party.members[1].hp = 5
    assert party.is_anyone_alive()
