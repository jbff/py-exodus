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


# --- T-07: a ship cannot sail onto a parked frigate --------------------------


def test_validdir_ship_sails_only_open_water(asset_mgr, pygame_setup):
    """UltimaMain.c:3174-3176 (ValidDir):

        if (Party[1] == 0x16) { /* Ship */
            if ((value == 00) || (value == 48))
                GoodPlace = TRUE; /* Water or whirlpool OK */

    A ship enters only water (or the whirlpool); a parked frigate is a map
    tile of its own (0x2C) in LairWare, so another ship cannot sail onto it.
    """
    from py_exodus.screens.overworld import OverworldScreen

    party = _party()
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr, start_x=4, start_y=2,
                         random_encounters=False)
    party.objects_map_id = 0
    party.dynamic_objects = [{"tile": "frigate", "x": 4, "y": 1}]
    assert can_move_to(ow.game_map, 5, 1, transport=Transport.SHIP, party=party)
    assert not can_move_to(ow.game_map, 4, 1, transport=Transport.SHIP, party=party)
    # On foot the parked frigate is still boardable (walkable on foot).
    assert can_move_to(ow.game_map, 4, 1, transport=Transport.FOOT, party=party)


# --- T-27: Castle Exodus throws fireballs ------------------------------------


class _Rolls:
    """random.randint stand-in: every roll lands on ``value``; records bounds."""

    def __init__(self, value: int) -> None:
        self.value = value
        self.bounds: list[tuple[int, int]] = []

    def __call__(self, a: int, b: int) -> int:
        self.bounds.append((a, b))
        return max(a, min(b, self.value))


def test_routine6e35_castle_exodus_bomb(town, monkeypatch):
    """UltimaMisc.c:1379-1388 (Routine6E35) and UltimaMain.c:1728-1740 (BombTrap):

        if (ExodusCastle() == 0) {
            gTimeNegate = 0;
            xs = RandNum(0, 11);
            ys = RandNum(0, 11);
            ...
            if (xs == 5 && ys == 5) {
                ...
                BombTrap();

        HPSubtract(Party[7 + chnum], RandNum(0, 255) & 0x77);
        HPSubtract(Party[7 + chnum], (zp[0x13] + 1) * 8);

    Each turn in Castle Exodus (until Exodus falls) a ball lands on one of
    the 12x12 view tiles; on the party's (5,5) every living member loses
    (RandNum(0,255) & 0x77) + 8. Time stop is cancelled there each turn.
    """
    from py_exodus.screens import town as town_module

    rolls = _Rolls(5)
    monkeypatch.setattr(town_module.random, "randint", rolls)
    tw = town(2, 32, 60)
    tw.party.aura.set(AuraType.QUICKNESS, 10)
    hp = [m.hp for m in tw.party.members]
    _key(tw, pygame.K_SPACE)
    assert (0, 11) in rolls.bounds
    assert (0, 255) in rolls.bounds
    assert [m.hp for m in tw.party.members] == [h - ((5 & 0x77) + 8) for h in hp]
    assert tw.party.aura.get_type() != AuraType.QUICKNESS

    # A miss (any tile but the party's) does nothing.
    rolls.value = 4
    hp = [m.hp for m in tw.party.members]
    _key(tw, pygame.K_SPACE)
    assert [m.hp for m in tw.party.members] == hp

    # No balls once Exodus is beaten, nor in another castle.
    rolls.value = 5
    tw.party.exodus_defeated = 1
    _key(tw, pygame.K_SPACE)
    assert [m.hp for m in tw.party.members] == hp
    lb = town(1, 32, 60, party=tw.party)
    tw.party.exodus_defeated = 0
    _key(lb, pygame.K_SPACE)
    assert [m.hp for m in tw.party.members] == hp


# --- T-06 (fix round 1): lava spares ashes -----------------------------------


def test_validdir_lava_spares_ashes(overworld):
    """UltimaMain.c:3197-3199 (ValidDir lava):

        if (!(Player[byte2][14] & 0x20)) {
            if ((Player[byte2][17] == 'G') || (Player[byte2][17] == 'P')) {
                HPSubtract(Party[byte + 7], 50);

    Only Good or Poisoned members burn; ashes stay ashes at 0 HP (they are
    not turned into the cheaper-to-raise dead).
    """
    ash = _member("Ash", status=Status.ASHES)
    ash.hp = 0
    party = _party(_member("Live"), ash)
    ow = overworld(49, 35, party)  # lava at (50, 35)
    _key(ow, pygame.K_RIGHT)
    assert (ow.party.x, ow.party.y) == (50, 35)
    assert party.members[0].hp == 150
    assert ash.status == Status.ASHES
    assert ash.hp == 0


def test_hpsubtract_exactly_zero_hp_is_dead():
    """UltimaMain.c:3250-3258 (HPSubtract), user ruling Q18 (follow LairWare):

        hp -= amount;
        if (hp < 1) {
            Player[rosNum][26] = 0;
            Player[rosNum][27] = 0;
            Player[rosNum][17] = 'D';

    A blow that leaves a member at exactly 0 HP kills them (the port, after
    Java, killed only below 0). One that leaves 1 HP does not. Both the
    party chokepoint and the combat fallback for bare characters follow it.
    """
    from py_exodus.combat.resolver import _deal_monster_damage_to_member

    party = Party()
    party.add_member(_member("A", hp=20))
    party.add_member(_member("B", hp=20))
    a, b = party.members
    a.apply_damage(20, True)
    assert a.hp == 0 and a.status == Status.DEAD
    b.apply_damage(19, True)
    assert b.hp == 1 and b.status == Status.GOOD

    bare = _member("C", hp=7)
    _deal_monster_damage_to_member(bare, 7)
    assert bare.hp == 0 and bare.status == Status.DEAD


def test_hpsubtract_raised_member_at_zero_hp_lives_until_hit():
    """UltimaMisc.c:1766-1767 (healer resurrection) and
    UltimaSpellCombat.c:353 (Surmandum) set only 'D' -> 'G': the member
    is raised with the 0 HP they died with and counts as alive (CheckAlive
    reads the status byte), so they can walk, act and be healed. The next
    HPSubtract on them, even for 0, finds ``hp < 1`` and kills them again
    (UltimaMain.c:3254-3258)."""
    party = Party()
    party.add_member(_member("A", hp=0, status=Status.DEAD))
    party.add_member(_member("B", hp=50))
    a = party.members[0]
    assert a.heal("RESURRECT")
    assert a.status == Status.GOOD and a.hp == 0
    assert not a.is_dead() and not a.is_disabled()
    assert party.is_anyone_alive()
    a.apply_damage(0, True)
    assert a.status == Status.DEAD
