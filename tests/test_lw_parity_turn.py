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
    for _ in range(11):  # one Sosaria meal crossing (40 per tick)
        party.end_turn(sosaria=True)
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


# --- T-08 naming (user ruling Q25): a NORTH wind blows from the north ---------


def test_validtrans_north_wind_stops_sailing_north(overworld):
    """UltimaMain.c:3222-3236 (ValidTrans) with North() at 1203-1207:

        if (ValidTrans(1) == 0) { NoGo(); ...
        ...
        if ((value != WindDir) && (WindDir != 0)) { cango = TRUE; } else { cango = FALSE; }

    WindDir 1 is shown as "NORTH WIND" (MoreMessages 44), so a north wind
    blows from the north and stops a ship sailing north, as sailors name
    winds (user ruling Q25). The port stopped the opposite heading.
    """
    ow = overworld(50, 13)
    ow.party.transport = Transport.SHIP
    ow.party.wind_direction = Direction.NORTH
    _key(ow, pygame.K_UP)
    assert (ow.party.x, ow.party.y) == (50, 13)
    assert "Headwinds block thy ship!" in ow.text_log.history

    ow.party.wind_direction = Direction.SOUTH
    _key(ow, pygame.K_UP)
    assert (ow.party.x, ow.party.y) == (50, 12)


def test_validtrans_autoplay_sails_by_the_same_wind(asset_mgr):
    """Autoplay plans by the same rule (UltimaMain.c:3229): with a NORTH
    wind it never heads north, with a SOUTH wind it may."""
    from py_exodus.autoplay.nav import find_2d_step
    from py_exodus.world.loader import load_map

    sosaria = load_map(0, asset_mgr)
    assert find_2d_step(sosaria, start=(50, 13), goals=(50, 12), transport=Transport.SHIP,
                        wind_direction=Direction.NORTH) != Direction.NORTH
    assert find_2d_step(sosaria, start=(50, 13), goals=(50, 12), transport=Transport.SHIP,
                        wind_direction=Direction.SOUTH) == Direction.NORTH


def test_validtrans_old_save_keeps_its_wind(tmp_path):
    """Save compatibility for Q25: a save written before the naming change
    stored the way the wind blew to ("NORTH" stopped sailing south). It
    loads as the same wind under the new name (from the south: "SOUTH"), so
    the ship it stopped is the same; a new save round-trips unchanged."""
    from py_exodus.entities.party import headwind

    old = Party().to_dict()
    old.pop("wind_from", None)
    old["wind_direction"] = "NORTH"
    loaded = Party.from_dict(old)
    assert loaded.wind_direction == Direction.SOUTH
    assert headwind(loaded.wind_direction) == Direction.SOUTH

    p = Party(wind_direction=Direction.EAST)
    again = Party.from_dict(p.to_dict())
    assert again.wind_direction == Direction.EAST

    calm = Party.from_dict({**old, "wind_direction": None})
    assert calm.wind_direction is None


# --- AgeChars ($7470) and EatFood ($761D): user rulings 2026-11-25 ----------
#
# UltimaMisc.c:1403-1414 (AgeChars):
#
#     if (Party[3] > 0) {
#         gTime[0]--;
#         if (gTime[0] > 0)
#             return;
#         gTime[0] = 4;
#     }
#     gTime[1]--;
#     if (gTime[1] < 0)
#         gTime[1] = 9;
#
# One tick every Sosaria turn, every 4th call anywhere else (Party[3] > 0:
# towns, castles, dungeons, Ambrosia, combat); a party-wide counter for the
# +1 HP every 10th tick.


def _caster(name: str = "Mage", prof: Profession = Profession.WIZARD, intel: int = 40,
            wis: int = 40, mp: int = 0, status: Status = Status.GOOD, hp: int = 200) -> Character:
    return Character(name=name, profession=prof, intelligence=intel, wisdom=wis, hp=hp,
                     max_hp=300, mp=mp, food=150, gold=0, status=status)


def _turns(party: Party, n: int, sosaria: bool) -> None:
    for _ in range(n):
        party.end_turn(sosaria=sosaria)


# T-16


def test_eatfood_starving_every_tick_on_sosaria():
    """UltimaMisc.c:1477-1487 (EatFood):

        if (Player[rosNum][32] > 127) {
            Player[rosNum][32] = Player[rosNum][33] = Player[rosNum][34] = 0;
            UPrintMessage(184);
            ...
            HPSubtract(rosNum, 5);

    Once the food is gone (the fraction too) every AgeChars tick underflows
    again: STARVING! and 5 HP. On Sosaria that is every turn.
    """
    m = _member()
    party = _party(m)
    m.food, m.submorsels = 0, 0
    _turns(party, 3, sosaria=True)
    assert m.hp == 200 - 15
    assert m.food == 0


def test_eatfood_starving_every_fourth_turn_off_sosaria():
    """UltimaMisc.c:1405-1410 with 1477-1487: off Sosaria (Party[3] > 0)
    AgeChars acts every 4th call, so starving takes 5 every 4th turn."""
    m = _member()
    party = _party(m)
    m.food, m.submorsels = 0, 0
    _turns(party, 8, sosaria=False)
    assert m.hp == 200 - 10


def test_eatfood_last_ration_does_not_starve():
    """UltimaMisc.c:1470-1476 (EatFood): the borrow that takes the last unit
    of food leaves a fraction (`[34] -= 157`), so that tick does no harm; the
    starving starts when the fraction runs out too."""
    m = _member(hp=300)  # at max HP: the 10th-tick heal changes nothing
    party = _party(m)
    m.food, m.submorsels = 1, 0
    _turns(party, 1, sosaria=True)
    assert (m.food, m.hp) == (0, 300)
    _turns(party, 10, sosaria=True)  # the fraction runs out
    assert m.hp == 300
    _turns(party, 1, sosaria=True)
    assert m.hp == 295


def test_agechars_quickness_does_not_stop_meals():
    """T-13, UltimaMisc.c:1357-1374 (Routine6E35): IncMoves, MoonGateUpdate
    and AgeChars run before FinishAll, the only place gTimeNegate is read
    (1120-1123): stopped time does not stop eating."""
    m = _member()
    party = _party(m)
    m.submorsels = 0
    party.aura.set(AuraType.QUICKNESS, 10)
    _turns(party, 1, sosaria=True)
    assert m.food == 149


# T-17


def test_agechars_heals_every_tenth_tick_for_every_living_member():
    """UltimaMisc.c:1412-1414 and 1461-1462 (AgeChars):

        gTime[1]--;
        if (gTime[1] < 0)
            gTime[1] = 9;
        ...
            if (gTime[1] == 0)
                HPAdd(rosNum, 1);

    One party counter: +1 HP on every 10th tick to every member not dead or
    ashes, the poisoned and the starving too.
    """
    fed = _member("Fed")
    sick = _member("Sick", status=Status.POISONED)
    hungry = _member("Hungry")
    party = _party(fed, sick, hungry)
    hungry.food, hungry.submorsels = 0, 0
    _turns(party, 9, sosaria=True)
    assert fed.hp == 200
    _turns(party, 1, sosaria=True)
    assert fed.hp == 201
    assert sick.hp == 200 - 10 + 1
    assert hungry.hp == 200 - 50 + 1


def test_agechars_heals_every_fortieth_turn_off_sosaria():
    """UltimaMisc.c:1405-1414: off Sosaria the 10th tick is the 40th turn
    (the first call ticks: gTime[0] starts at 0)."""
    m = _member()
    party = _party(m)
    _turns(party, 36, sosaria=False)  # ticks on turns 1, 5, ..., 33: nine
    assert m.hp == 200
    _turns(party, 1, sosaria=False)  # turn 37: the 10th tick
    assert m.hp == 201
    _turns(party, 39, sosaria=False)
    assert m.hp == 201
    _turns(party, 1, sosaria=False)
    assert m.hp == 202


def test_agechars_heal_caps_at_max_hp():
    """UltimaMain.c:3239-3247 (HPAdd): `if (hp > maxhp) hp = maxhp;`."""
    m = _member(hp=300)
    party = _party(m)
    _turns(party, 10, sosaria=True)
    assert m.hp == 300


def test_agechars_counters_survive_a_save_and_old_saves_load():
    """gTime[0] and gTime[1] carry on across a save; a save from before
    them loads with LW's zeroed globals (the next off-Sosaria call ticks,
    the 10th tick heals)."""
    party = _party(_member())
    _turns(party, 3, sosaria=False)
    again = Party.from_dict(party.to_dict())
    assert (again.age_count, again.heal_count) == (party.age_count, party.heal_count)
    old = party.to_dict()
    old.pop("age_count")
    old.pop("heal_count")
    old["regen_turns"] = 17  # the retired per-turn regen counter
    loaded = Party.from_dict(old)
    assert (loaded.age_count, loaded.heal_count) == (0, 0)
    assert "regen_turns" not in loaded.to_dict()


# T-18


def test_agechars_poison_every_tick():
    """UltimaMisc.c:1454-1460 (AgeChars):

        if (Player[rosNum][17] == 'P') {
            HPSubtract(rosNum, 1);
            ...
            UPrintMessage(183);

    POISON! takes 1 HP a tick: every Sosaria turn, every 4th turn elsewhere.
    """
    m = _member(status=Status.POISONED)
    party = _party(m)
    _turns(party, 4, sosaria=True)
    assert m.hp == 196
    _turns(party, 4, sosaria=False)
    assert m.hp == 195


# T-20


def test_agechars_mana_every_tick_up_to_the_class_cap():
    """UltimaMisc.c:1418-1428 (AgeChars):

        // Wizard, full Int
        if (cType == careerTable[2]) {
            if (Player[rosNum][25] < Player[rosNum][20])
                Player[rosNum][25]++;
        }

    +1 MP a tick (every Sosaria turn, every 4th turn elsewhere) up to the
    class's cap (MaxMana).
    """
    wiz = _caster(intel=30, mp=0)
    party = _party(wiz)
    _turns(party, 5, sosaria=True)
    assert wiz.mp == 5
    _turns(party, 8, sosaria=False)
    assert wiz.mp == 7
    wiz.mp = 29
    _turns(party, 3, sosaria=True)
    assert wiz.mp == 30


def test_agechars_mana_for_the_dead_and_ashes_too():
    """UltimaMisc.c:1415-1449: the mana block runs for all four slots before
    the status test (`if ((temp == 'D') || (temp == 'A') ...`), so the dead
    and ashes regain MP as LairWare does."""
    dead = _caster("Dead", status=Status.DEAD, hp=0, mp=0)
    ash = _caster("Ash", status=Status.ASHES, hp=0, mp=0)
    party = _party(_member(), dead, ash)
    _turns(party, 3, sosaria=True)
    assert (dead.mp, ash.mp) == (3, 3)


def test_agechars_druid_two_a_tick_to_max_book_of_lore():
    """User ruling 2026-11-25, the Book of Lore over LairWare
    (assets/data/ultima3.txt:159,168-169: "Greater of Both Halfs. Druids
    regain their magic points faster"; "Druids regain two points per turn").
    LairWare (UltimaMisc.c:1430-1440) gives +1 per half the Druid is under;
    the port gives +2 a tick all the way to the greater half."""
    druid = _caster("Druid", prof=Profession.DRUID, intel=40, wis=20, mp=10)
    party = _party(druid)
    _turns(party, 3, sosaria=True)  # past WIS/2 = 10: LW would give +1 here
    assert druid.mp == 16
    _turns(party, 4, sosaria=False)  # one tick
    assert druid.mp == 18
    _turns(party, 5, sosaria=True)
    assert druid.mp == 20


def test_agechars_mana_above_the_cap_is_kept():
    """UltimaMisc.c:1418-1447: every gain is `if (mp < cap) mp++`, so MP
    already above the cap (a stat lowered) is not cut down."""
    wiz = _caster(intel=20, mp=25)
    party = _party(wiz)
    _turns(party, 2, sosaria=True)
    assert wiz.mp == 25


# W-03


def test_moongateupdate_only_on_sosaria():
    """UltimaMisc.c:1490-1493 (MoonGateUpdate):

        if (Party[3] != 0)
            return; /* only if on surface! */

    The moons stand still in towns, castles, dungeons and on Ambrosia, and
    turn on Sosaria while time is stopped (T-13: the check is FinishAll's)."""
    party = _party()
    phase = party.moon_phase
    _turns(party, 64, sosaria=False)
    assert party.moon_phase == phase
    party.aura.set(AuraType.QUICKNESS, 10)
    _turns(party, 4, sosaria=True)
    assert party.moon_phase == (phase + 1) % 24


def test_moongateupdate_frozen_on_ambrosia(overworld, asset_mgr):
    """UltimaMisc.c:1490-1493: Ambrosia (Party[3] > 0) has no moon turn,
    and its AgeChars acts every 4th turn."""
    ow = overworld(10, 10)
    ow.map_id = 13
    ow.game_map.id = 13
    m = ow.party.members[0]
    m.status = Status.POISONED
    phase = ow.party.moon_phase
    for _ in range(8):
        ow._finish_turn(None)
    assert ow.party.moon_phase == phase
    assert m.hp == 198


# T-13


def test_negatetime_counts_down_only_when_monsters_would_move(overworld):
    """UltimaMain.c:2138 `gTimeNegate = 10;` and UltimaMisc.c:1115-1123
    (FinishAll): the count drops only on turns past the mounted flip, so
    stopped time lasts 10 turns on foot and 20 on horse or ship."""
    ow = overworld(10, 10)
    ow.party.aura.set(AuraType.QUICKNESS, 10)
    for _ in range(9):
        ow._consume_pass_turn()
    assert ow.party.aura.get_type() == AuraType.QUICKNESS
    ow._consume_pass_turn()
    assert ow.party.aura.get_type() == AuraType.NONE

    ow.party.transport = Transport.HORSE
    ow.party.aura.set(AuraType.QUICKNESS, 10)
    for _ in range(18):  # nine counted turns of the 18 (the flip's phase)
        ow._consume_pass_turn()
    assert ow.party.aura.get_type() == AuraType.QUICKNESS
    for _ in range(2):
        ow._consume_pass_turn()
    assert ow.party.aura.get_type() == AuraType.NONE


def test_negatetime_counts_down_in_towns(town):
    """UltimaMisc.c:1120-1123: FinishAll runs from Routine6E35 in towns too,
    so stopped time drops a turn there while the townsfolk stand still."""
    scr = town(1, 10, 10)
    scr.party.aura.set(AuraType.QUICKNESS, 3)
    for _ in range(3):
        scr._finish_turn(None)
    assert scr.party.aura.get_type() == AuraType.NONE


# --- T-05: the force field (user ruling 2026-11-25) --------------------------


def _forcefield_party(*marked: bool, ashes_first: bool = False) -> Party:
    party = _party(*(_member(f"M{i}", hp=200) for i in range(len(marked))))
    for m, mk in zip(party.members, marked):
        m.marks[3] = 1 if mk else 0
    return party


def test_validdir_forcefield_strikes_only_the_first_unmarked(asset_mgr):
    """UltimaMain.c:3178-3192 (ValidDir):

        for (byte = 0; byte < 4; byte++) {
            if (!(Player[Party[byte + 7]][14] & 0x10)) {
                HPSubtract(Party[byte + 7], 99);
                ...
                byte = 5;

    The first member without the Mark of Force takes 99 and the loop stops
    (`byte = 5`). User ruling: the party is blocked unless every living
    member is marked (LW's never-cleared GoodPlace, which lets a marked
    leader pull the unmarked through, is not ported).
    """
    from py_exodus.world import tile_effects

    energy = asset_mgr.get_tile_by_name("energy_field")
    party = _forcefield_party(True, False, False)
    lines: list[str] = []
    assert tile_effects.apply_force_field_strike(party, energy, lines.append)
    assert [m.hp for m in party.members] == [200, 101, 200]
    assert not tile_effects.all_members_mark_of_force(party)


def test_validdir_forcefield_ignores_the_dead_and_ashes(asset_mgr):
    """User ruling 2026-11-25: dead and ashes members neither block the
    marked party nor take the strike; the first unmarked LIVING one does."""
    from py_exodus.world import tile_effects

    energy = asset_mgr.get_tile_by_name("energy_field")
    party = _forcefield_party(False, True, False)
    party.members[0].status, party.members[0].hp = Status.ASHES, 0
    party.members[2].status, party.members[2].hp = Status.DEAD, 0
    assert tile_effects.all_members_mark_of_force(party)
    assert not tile_effects.apply_force_field_strike(party, energy)

    party.members[2].status, party.members[2].hp = Status.GOOD, 200
    party.members[1].marks[3] = 0
    assert tile_effects.apply_force_field_strike(party, energy)
    assert [m.hp for m in party.members] == [0, 101, 200]
