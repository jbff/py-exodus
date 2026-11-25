"""LairWare parity, batch C (the A-Z commands).

Each test pins one rule from the LairWare Mac port (refs/ultima3/Sources),
the rules authority; the docstring quotes the File.c:line it ports. Ledger:
docs/superpowers/plans/lw-parity-ledger.md, table "C - Commands".
"""
from __future__ import annotations

import pygame
import pytest

from py_exodus.constants import ArmorType, Profession, Race, Status, Transport, WeaponType
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.world import chests


class Script:
    """Stand-in for the ``random`` module: randrange(n) pops scripted rolls
    (an empty script answers 0); randint(a, b) likewise."""

    def __init__(self, rolls: list[int]) -> None:
        self.rolls = list(rolls)

    def randrange(self, n: int) -> int:
        v = self.rolls.pop(0) if self.rolls else 0
        assert 0 <= v < n, (v, n)
        return v

    def randint(self, a: int, b: int) -> int:
        v = self.rolls.pop(0) if self.rolls else a
        assert a <= v <= b, (v, a, b)
        return v

    def random(self) -> float:
        return 0.5


def _pm(name: str = "Hero", prof: Profession = Profession.FIGHTER, **kw) -> PartyMember:
    d = {"hp": 300, "max_hp": 300, "gold": 100, "dexterity": 15}
    d.update(kw)
    return PartyMember(Character(name, "M", Race.HUMAN, prof, **d))


def _party(*members: PartyMember) -> Party:
    party = Party(list(members) or [_pm()], transport=Transport.FOOT)
    for m in party.members:
        m.submorsels = 400
    return party


def _key(screen, k: int, uni: str = "") -> None:
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=uni))


def _type(screen, text: str) -> None:
    for ch in text:
        if ch == "\n":
            _key(screen, pygame.K_RETURN, "\r")
        else:
            _key(screen, ord(ch.lower()), ch)


# --- GetChest / GetChestBooty / AddItem -----------------------------------


def test_getchestbooty_gold_30_to_100(monkeypatch):
    """UltimaMain.c:1686-1689: ``gold = RandNum(0, 100); if (gold < 30) gold
    += 30;`` -- 0 gives 30, 29 gives 59, 30 stays 30, 100 stays 100."""
    for roll, want in ((0, 30), (29, 59), (30, 30), (100, 100)):
        m = _pm(gold=0)
        monkeypatch.setattr(chests, "random", Script([roll, 255]))
        lines = chests.open_chest(_party(m), m, disarmed=True)
        assert m.gold == want and lines.gold == want
        assert lines == [f"The Chest Holds: {want} Gold"]


def test_getchestbooty_items_behind_one_quarter_gate(monkeypatch):
    """UltimaMain.c:1699-1700: ``if (RandNum(0, 255) > 63) return;`` -- no
    armour roll follows a closed gate (the port rolled armour 25% anyway)."""
    m = _pm()
    rng = Script([50, 64, 0, 0, 0, 0])
    monkeypatch.setattr(chests, "random", rng)
    lines = chests.open_chest(_party(m), m, disarmed=True)
    assert lines.item_lines == []
    assert rng.rolls == [0, 0, 0, 0]  # nothing rolled past the gate


def test_getchestbooty_weapon_is_masked_roll(monkeypatch):
    """UltimaMain.c:1701-1712: ``wpn = RandNum(0,255); if (wpn < 128) { wpn =
    (RandNum(0,255) & wpn) & 0x07; if (wpn != 0) { ... AddItem(rosNum, 48 +
    wpn, 1); return; } }`` -- 0x05 & 0x0E & 7 = 4 (Axe)."""
    m = _pm()
    monkeypatch.setattr(chests, "random", Script([50, 63, 0x0E, 0x05]))
    lines = chests.open_chest(_party(m), m, disarmed=True)
    assert lines.item_lines == ["You found a Axe!"]
    assert m.weapons[WeaponType.AXE] == 1


def test_getchestbooty_armour_after_weapon_zero(monkeypatch):
    """UltimaMain.c:1713-1725: a high or zero weapon roll goes to ``arm =
    RandNum(0,255); if (arm < 128) { arm = (RandNum(0,255) & arm) & 0x03;``
    -- weapon roll 200 (>= 128), armour 0x03 & 0x7E = 2 (Leather)."""
    m = _pm()
    monkeypatch.setattr(chests, "random", Script([50, 0, 200, 0x7E, 0x03]))
    lines = chests.open_chest(_party(m), m, disarmed=True)
    assert lines.item_lines == ["You found a Leather!"]
    assert m.armors[ArmorType.LEATHER] == 1


def test_additem_caps_at_99(monkeypatch):
    """UltimaMisc.c:504-508 AddItem: ``Player[rosNum][item] += amount; if (>
    99) = 99`` -- a stack of 9 grows (the port capped at 9 and skipped it)."""
    m = _pm()
    m.weapons[WeaponType.MACE] = 9
    monkeypatch.setattr(chests, "random", Script([50, 0, 0x7F, 0x02]))
    chests.open_chest(_party(m), m, disarmed=True)
    assert m.weapons[WeaponType.MACE] == 10
    m.weapons[WeaponType.MACE] = 99
    monkeypatch.setattr(chests, "random", Script([50, 0, 0x7F, 0x02]))
    chests.open_chest(_party(m), m, disarmed=True)
    assert m.weapons[WeaponType.MACE] == 99


def test_getchest_acid_trap_damage_masked_no_mark_of_fire(monkeypatch):
    """UltimaMain.c:1637-1646 case 0: ``HPSubtract(rosNum, RandNum(0, 255) &
    0x37)`` -- 0-55, and the Mark of Fire gives no immunity."""
    m = _pm(dexterity=0)
    m.marks[1] = 1
    other = _pm("Other")
    # trap (0), disarm fails (255), acid (0 & 0), damage roll 0xFF & 0x37 = 55
    monkeypatch.setattr(chests, "random", Script([0, 255, 0, 0, 0xFF, 50, 255]))
    lines = chests.open_chest(_party(m, other), m)
    assert lines[0] == "Acid Trap!"
    assert m.hp == 300 - 55
    assert other.hp == 300


def test_getchest_gas_trap_spares_ashes(monkeypatch):
    """UltimaMain.c:1672-1679 case 3: ``if (CheckAlive(x) == TRUE) ...
    Player[...][17] = 'P'`` -- CheckAlive is G or P, so ashes stay ashes."""
    m = _pm(dexterity=0)
    ash = _pm("Ash")
    ash.status = Status.ASHES
    monkeypatch.setattr(chests, "random", Script([0, 255, 3, 3, 50, 255]))
    chests.open_chest(_party(m, ash), m)
    assert m.status == Status.POISONED
    assert ash.status == Status.ASHES


# --- screen fixtures -------------------------------------------------------


@pytest.fixture
def overworld(pygame_setup, asset_mgr):
    from py_exodus.screens.overworld import OverworldScreen

    def make(x: int = 40, y: int = 40, party: Party | None = None, map_id: int = 0):
        scr = OverworldScreen(
            party=party or _party(), map_id=map_id, asset_mgr=asset_mgr,
            start_x=x, start_y=y, random_encounters=False,
        )
        scr.party.x, scr.party.y = x, y
        scr.party.objects_map_id = map_id
        scr.creatures = []
        scr._check_moongates = lambda: None  # type: ignore[method-assign]
        return scr

    return make


@pytest.fixture
def town(pygame_setup, asset_mgr):
    from py_exodus.screens.town import TownScreen

    def make(map_id: int = 3, x: int = 32, y: int = 32, party: Party | None = None):
        scr = TownScreen(party=party or _party(), map_id=map_id, asset_mgr=asset_mgr,
                         start_x=x, start_y=y)
        scr.avatar_x, scr.avatar_y = x, y
        return scr

    return make


def test_getchest_opener_must_be_alive(overworld):
    """UltimaMain.c:1600-1603: ``if (CheckAlive(chnum - 1) == FALSE) {
    Incap(); return; }`` -- a dead member opens nothing; the chest stays."""
    dead = _pm("Dead")
    dead.status = Status.DEAD
    scr = overworld(party=_party(dead, _pm("Live")))
    scr.party.dynamic_objects.append({"tile": "chest", "x": 40, "y": 40})
    gold = dead.gold
    _key(scr, pygame.K_g, "g")
    _key(scr, pygame.K_1, "1")
    assert dead.gold == gold
    assert any(o.get("tile") == "chest" for o in scr.party.dynamic_objects)
    assert "Incapacitated!" in scr.text_log.history[-1]


def test_getchest_town_opener_must_be_alive(town):
    """UltimaMain.c:1600-1603 (towns run the same GetChest)."""
    ash = _pm("Ash")
    ash.status = Status.ASHES
    scr = town(party=_party(ash, _pm("Live")))
    scr.party.objects_on(scr.game_map).append({"tile": "chest", "x": 32, "y": 32})
    gold = ash.gold
    _key(scr, pygame.K_g, "g")
    _key(scr, pygame.K_1, "1")
    assert ash.gold == gold
    assert "Incapacitated!" in scr.text_log.history[-1]


# --- OtherCommand: Steal, Bribe, Dig, Pray, Search ----------------------------


def _lcb(asset_mgr):
    from py_exodus.world.loader import MapLoader

    return MapLoader(asset_mgr).load_map(3)  # Lord British's town (LCB)


def test_steal_success_needs_counter_then_chest_three_away(asset_mgr):
    """UltimaMain.c:2271-2285: ``byte = GetXYVal(xs, ys); if (byte < 0x94 ||
    byte > 0xE4) goto fail; xs = xs + dx + dx; ... if (byte != 0x24) goto fail;
    PutXYVal(0x20, xs, ys); GetChest(2, chnum);`` -- a counter next to the
    thief and a chest three tiles out, which becomes floor; the booty is
    GetChestBooty's (gold 30-100)."""
    from py_exodus import special_commands as sc
    from py_exodus.constants import Direction

    gm = _lcb(asset_mgr)
    thief = _pm("Thief", Profession.THIEF, dexterity=25, gold=0)
    # steal roll 0 (<= 153, success); booty gold 50, item gate shut
    lines = sc.do_steal(_party(thief), thief, 54, 20, Direction.NORTH, gm,
                        rng=Script([0]))
    assert gm.get_tile(54, 17).name == "floor"
    assert sc.STEAL_FAILED not in lines and sc.WATCH_OUT not in lines
    assert 30 <= thief.gold <= 100


def test_steal_roll_equal_to_factor_succeeds(asset_mgr, monkeypatch):
    """UltimaMisc.c:526-527: ``if (RandNum(0, 255) > factor) result = TRUE``
    (failed) -- a roll equal to the factor (dex 25 + Thief 128 = 153) steals."""
    from py_exodus import special_commands as sc
    from py_exodus.constants import Direction

    monkeypatch.setattr(chests, "random", Script([50, 255]))
    gm = _lcb(asset_mgr)
    thief = _pm("Thief", Profession.THIEF, dexterity=25, gold=0)
    sc.do_steal(_party(thief), thief, 54, 20, Direction.NORTH, gm, rng=Script([153]))
    assert thief.gold == 50


def test_steal_fail_one_in_four_turns_guards_hostile(asset_mgr):
    """UltimaMain.c:2259-2269: on a failed roll ``if ((RandNum(0, 255) & 0x03)
    != 0) { "Failed!"; return; }`` else every guard (0x48) gets ctrl 0xC0
    (attack) and "Watch out!"."""
    from py_exodus import special_commands as sc
    from py_exodus.constants import Direction

    gm = _lcb(asset_mgr)
    guards = [n for n in gm.npcs if n.tile_name == "guard"]
    assert guards
    m = _pm(dexterity=10)
    assert sc.do_steal(_party(m), m, 54, 20, Direction.NORTH, gm, rng=Script([255, 1])) == [sc.STEAL_FAILED]
    assert all(g.movement != "ATTACK_AVATAR" for g in guards)
    assert sc.do_steal(_party(m), m, 54, 20, Direction.NORTH, gm, rng=Script([255, 4])) == [sc.WATCH_OUT]
    assert all(g.movement == "ATTACK_AVATAR" for g in guards)
    assert gm.get_tile(54, 17).name == "chest"


def test_steal_good_roll_wrong_place_still_fails(asset_mgr):
    """UltimaMain.c:2273-2274, 2278-2279: a wrong tile ``goto fail`` -- the
    same 1-in-4 alarm as a bad roll (the port answered "Nothing.")."""
    from py_exodus import special_commands as sc
    from py_exodus.constants import Direction

    gm = _lcb(asset_mgr)
    m = _pm(dexterity=10)
    assert sc.do_steal(_party(m), m, 32, 32, Direction.NORTH, gm, rng=Script([0, 0])) == [sc.WATCH_OUT]


def test_bribe_pays_100_even_for_no_effect(asset_mgr):
    """UltimaMisc.c:2446-2464: no one there -> NotHere (free); under 100 gold
    -> "Not enough gold!"; else ``gold -= 100`` and a non-guard answers
    NoEffect (the port charged nothing for a non-guard)."""
    from py_exodus import special_commands as sc
    from py_exodus.constants import Direction
    from py_exodus.world.map import MapNpc

    gm = _lcb(asset_mgr)
    gm.npcs = [MapNpc(20, "fighter", 10, 9, 10, 9), MapNpc(18, "guard", 10, 11, 10, 11)]
    m = _pm(gold=250)
    assert sc.do_bribe(m, 10, 10, Direction.EAST, gm) == sc.NOT_HERE
    assert m.gold == 250
    assert sc.do_bribe(m, 10, 10, Direction.NORTH, gm) == sc.NO_EFFECT
    assert m.gold == 150 and len(gm.npcs) == 2
    assert sc.do_bribe(m, 10, 10, Direction.SOUTH, gm) == ""
    assert m.gold == 50 and [n.tile_name for n in gm.npcs] == ["fighter"]


def test_dig_sets_one_exotic(asset_mgr):
    """UltimaMisc.c:2421-2426: ``Player[rosNum][63] = 1`` / ``[47] = 1`` --
    digging again does not add a second Exotic (the port stacked to 9)."""
    from py_exodus import special_commands as sc
    from py_exodus.world.loader import MapLoader

    sos = MapLoader(asset_mgr).load_map(0)
    m = _pm()
    for _ in range(3):
        assert sc.do_dig(_party(m), m, 33, 3, sos) == sc.EXOTICS
        assert sc.do_dig(_party(m), m, 19, 44, sos) == sc.EXOTICS
    assert m.weapons[WeaponType.EXOTIC] == 1
    assert m.armors[ArmorType.EXOTIC] == 1
    assert sc.do_dig(_party(m), m, 33, 4, sos) == sc.NOT_HERE


def test_pray_only_in_yew_at_48_48():
    """UltimaMisc.c:2466-2481: ``Party[3] != 2`` (a town), ``Party[4] !=
    LocationX[4]`` (Yew, MISC 404: x 34) or not at (0x30, 0x30) -> NoEffect.
    The port also answered on the Exodus map and in a box around (48,48)."""
    from py_exodus import special_commands as sc

    assert sc.do_pray(48, 48, 4) == sc.VISION
    assert sc.do_pray(47, 48, 4) == sc.NO_EFFECT
    assert sc.do_pray(48, 48, 2) == sc.NO_EFFECT
    assert sc.do_pray(46, 46, 4) == sc.NO_EFFECT


def test_other_needs_living_member(town):
    """UltimaMisc.c:2276-2280: ``if (CheckAlive(chnum - 1) == FALSE) {
    UPrintMessage(126); ...`` -- every Other word, Search included."""
    ash = _pm("Ash")
    ash.status = Status.ASHES
    scr = town(party=_party(ash, _pm("Live")))
    _key(scr, pygame.K_o, "o")
    _type(scr, "SEARCH\n")
    _key(scr, pygame.K_1, "1")
    assert scr.text_log.history[-1] == "Incapacitated!"


# --- NegateTime / PeerGem: whose item -----------------------------------------


@pytest.mark.parametrize("where", ["overworld", "town"])
def test_negatetime_asks_whose_powder(where, request):
    """UltimaMain.c:2122-2139: ``UPrintMessage(74); chnum = GetChar(); ...
    if (Player[rosNum][39] < 1) { "None left!"; return; } Player[rosNum][39]--;
    gTimeNegate = 10;`` -- the chosen member pays (the port took the first
    member holding one)."""
    from py_exodus.aura import AuraType

    a, b = _pm("A"), _pm("B")
    a.powder, b.powder = 3, 3
    scr = request.getfixturevalue(where)(party=_party(a, b))
    _key(scr, pygame.K_n, "n")
    assert scr.text_log.is_waiting_for_input
    _key(scr, pygame.K_2, "2")
    assert (a.powder, b.powder) == (3, 2)
    assert scr.party.aura.get_type() == AuraType.QUICKNESS
    assert scr.party.aura.get_duration() >= 9  # 10, less the turn N takes
    b.powder = 0
    scr.party.aura.set(AuraType.NONE, 0)
    _key(scr, pygame.K_n, "n")
    _key(scr, pygame.K_2, "2")
    assert a.powder == 3
    assert scr.party.aura.get_type() != AuraType.QUICKNESS


@pytest.mark.parametrize("where", ["overworld", "town"])
def test_peergem_asks_whose_gem(where, request):
    """UltimaMain.c:2143-2159: ``UPrintMessage(75); chnum = GetChar(); ...
    if (Player[rosnum][37] < 1) "None left!" else { [37]--; DrawMiniMap(); }``"""
    a, b = _pm("A"), _pm("B")
    a.gems, b.gems = 2, 2
    scr = request.getfixturevalue(where)(party=_party(a, b))
    _key(scr, pygame.K_p, "p")
    assert scr.text_log.is_waiting_for_input
    _key(scr, pygame.K_2, "2")
    assert (a.gems, b.gems) == (2, 1)
    assert scr.gem_view_active


# --- Unlock --------------------------------------------------------------------


def test_unlock_refuses_north_and_south(town):
    """UltimaMain.c:2400-2408: diagonals are switched off for the prompt, and
    ``if ((ys != ypos) && (xs == xpos)) NotHere();`` -- only east or west."""
    m = _pm()
    m.keys = 2
    scr = town(map_id=9, x=28, y=13, party=_party(m))  # Montor West door (28, 12) north
    assert scr.game_map.get_tile(28, 12).name == "locked_door"
    _key(scr, pygame.K_u, "u")
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_UP)
    assert scr.game_map.get_tile(28, 12).name == "locked_door"
    assert m.keys == 2


def test_unlock_town_door_becomes_tile_west(town):
    """UltimaMain.c:2428-2433: ``value = GetXYVal(xs - 1, ys); if (value >
    0x20) value = 0x04; PutXYVal(value, xs, ys);`` -- in a town too the door
    opens straight into the tile west of it (the port left a closed door to
    Open with L)."""
    m = _pm()
    m.keys = 2
    scr = town(map_id=9, x=29, y=12, party=_party(m))  # door (28, 12), floor west
    _key(scr, pygame.K_u, "u")
    _key(scr, pygame.K_1, "1")
    _key(scr, pygame.K_LEFT)
    assert scr.game_map.get_tile(28, 12).name == "floor"
    assert m.keys == 1


# --- Exit (X) -----------------------------------------------------------------


def test_exit_ship_at_open_sea(overworld):
    """UltimaMain.c:2523-2538: ``tileOn = GetXYVal(xpos, ypos); if (tileOn >
    4) NotHere; else { PutXYVal(Party[1] * 2, ...); Party[1] = 0x7E; }`` --
    water (0) qualifies, so a ship can be left anywhere (the port demanded a
    shoreline)."""
    scr = overworld(50, 10)
    assert scr.game_map.get_tile(50, 10).name == "water"
    scr.party.transport = Transport.SHIP
    scr._exit_transport()
    assert scr.party.transport == Transport.FOOT
    assert any(o.get("tile") == "frigate" and (o["x"], o["y"]) == (50, 10)
               for o in scr.party.dynamic_objects)


def test_exit_horse_only_on_grass(overworld, town):
    """UltimaMain.c:2523-2530: a horse is left only on grass (4) -- brush,
    forest or a town floor answer "Not here!"."""
    scr = overworld(40, 40)
    from py_exodus.assets import TileDef

    scr.game_map.set_tile(40, 40, TileDef(index=2, name="brush", rule="brush"))
    scr.party.transport = Transport.HORSE
    scr._exit_transport()
    assert scr.party.transport == Transport.HORSE
    scr.game_map.set_tile(40, 40, TileDef(index=1, name="grass", rule="grass"))
    scr._exit_transport()
    assert scr.party.transport == Transport.FOOT

    tw = town(map_id=3, x=32, y=32)
    assert tw.game_map.get_tile(32, 32).index > 1
    tw.party.transport = Transport.HORSE
    tw._exit_transport()
    assert tw.party.transport == Transport.HORSE


# --- Enter -------------------------------------------------------------------


def test_enter_town_at_1_32_castle_at_32_62(asset_mgr):
    """UltimaMain.c:1431-1452: a town is entered at ``ypos = 32; xpos = 1;``
    and a castle at ``xpos = 32; ypos = 62;`` (the port used Java's (2,32),
    (5,32) and Castle British's (32,61))."""
    from py_exodus.world.loader import MapLoader

    sos = MapLoader(asset_mgr).load_map(0)
    starts = {p.dest_map_id: (p.start_x, p.start_y) for p in sos.portals}
    for town_id in range(3, 13):
        assert starts[town_id] == (1, 32), town_id
    assert starts[1] == (32, 62)
    assert starts[2] == (32, 62)


# --- Transact: Lord British ------------------------------------------------------


def _lb_char(level: int, exp: int, kings: bool = True) -> Character:
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER, level=level, exp=exp)
    c.max_hp = level * 100 + 50
    c.hp = 40
    c.marks = [1 if kings else 0, 0, 0, 0]
    return c


def test_lord_british_one_level_per_visit_no_heal():
    """UltimaMain.c:2373-2380: ``hpmax += 100; if (hpmax > 9950) hpmax =
    9950;`` -- one step per visit, and current HP is not touched (the port
    jumped to the experience level and healed to full)."""
    c = _lb_char(1, 650)
    assert c.meet_lord_british() is True
    assert (c.level, c.max_hp, c.hp) == (2, 250, 40)
    assert c.meet_lord_british() is True
    assert c.level == 3


def test_lord_british_does_not_cure_or_raise():
    """UltimaMain.c:2373-2380 writes only the max-HP bytes (28/29)."""
    c = _lb_char(1, 650)
    c.status = Status.POISONED
    c.meet_lord_british()
    assert c.status == Status.POISONED


def test_lord_british_stops_at_25():
    """UltimaMain.c:2361-2366: ``if (hpmax >= 25 && Party[16] == 0) "NO
    MORE!"``. The after-the-fall rise is gone (user ruling 2026-11-25: the
    game ends when Exodus falls), so 25 is the top, old won saves too."""
    c = _lb_char(25, 9999)
    assert c.meet_lord_british() is False
    assert c.lord_british_refusal() == "no_more"
    assert (c.level, c.max_hp) == (25, 2550)


def test_lord_british_needs_experience_and_mark():
    """UltimaMain.c:2352-2372: ``level < hpmax`` (exp hundreds below the
    max-HP hundreds) -> "EXPERIENCE MORE"; ``hpmax > 4`` without the Mark of
    Kings -> "SEEK YE THE MARK OF KINGS"."""
    assert _lb_char(3, 299).meet_lord_british() is False
    assert _lb_char(3, 300).meet_lord_british() is True
    assert _lb_char(5, 900, kings=False).meet_lord_british() is False
    assert _lb_char(4, 900, kings=False).meet_lord_british() is True


def test_transact_needs_living_member(town):
    """UltimaMain.c:2302-2305: ``if (CheckAlive(chnum - 1) == 0) { Incap();
    return; }`` -- before the direction, for every Transact."""
    dead = _pm("Dead")
    dead.status = Status.DEAD
    scr = town(party=_party(dead, _pm("Live")))
    _key(scr, pygame.K_t, "t")
    _key(scr, pygame.K_1, "1")
    assert scr.text_log.history[-1] == "Incapacitated!"
    assert not scr.text_log.is_waiting_for_input


# --- Attack in towns -------------------------------------------------------------


def test_attack_in_town_fights_the_person(town):
    """UltimaMain.c:1329-1340: ``GetDirection(0); monNum = MonsterHere(xs, ys);
    if (monNum == 255) NotHere(); else AttackCode(monNum);`` -- town people
    are monsters too, so A starts a fight (the port refused every attack)."""
    from py_exodus.world.map import MapNpc

    scr = town(map_id=3, x=32, y=32)
    scr.game_map.npcs = [MapNpc(18, "guard", 33, 32, 33, 32)]
    _key(scr, pygame.K_a, "a")
    _key(scr, pygame.K_LEFT)
    assert not scr.is_finished
    assert scr.text_log.history[-1] == "Not Here!"
    _key(scr, pygame.K_a, "a")
    _key(scr, pygame.K_RIGHT)
    assert scr.is_finished
    assert type(scr.next_screen).__name__ == "CombatScreen"
    assert scr._combat_npc is not None and scr._combat_npc.tile_name == "guard"


# --- Yell -----------------------------------------------------------------------


def test_yell_evocare_carries_party_past_the_serpent(overworld):
    """UltimaMain.c:2557-2590: with the Mark of Snake, ``if (GetXYVal(xpos,
    ypos - 1) == 236) oy -= 3; if (GetXYVal(xpos, ypos + 1) == 232) oy += 3;
    ... ypos = oy;`` -- the party jumps three rows past the serpent, which
    stays (the port replaced the serpent tiles with water for good)."""
    m = _pm()
    m.marks[2] = 1
    scr = overworld(10, 59, party=_party(m))
    scr.party.transport = Transport.SHIP
    _key(scr, pygame.K_y, "y")
    _key(scr, pygame.K_1, "1")
    _type(scr, "EVOCARE\n")
    assert (scr.party.x, scr.party.y) == (10, 56)
    assert scr.game_map.get_tile(10, 57).name.startswith("snake")
    assert scr.game_map.get_tile(10, 58).name.startswith("snake")
    _key(scr, pygame.K_y, "y")
    _key(scr, pygame.K_1, "1")
    _type(scr, "EVOCARE\n")
    assert (scr.party.x, scr.party.y) == (10, 59)


def test_yell_evocare_needs_the_mark(overworld):
    """UltimaMain.c:2563-2567: ``if ((Player[rosNum][14] & 0x40) == 0) {
    NoEffect(); return; }``"""
    scr = overworld(10, 59)
    _key(scr, pygame.K_y, "y")
    _key(scr, pygame.K_1, "1")
    _type(scr, "EVOCARE\n")
    assert (scr.party.x, scr.party.y) == (10, 59)


def test_yell_takes_the_other_words(town):
    """UltimaMain.c:2546-2550: ``Yell(0)`` is ``OtherCommand(1)`` -- any Other
    word can be yelled (here BRIBE asks its direction)."""
    scr = town()
    _key(scr, pygame.K_y, "y")
    _key(scr, pygame.K_1, "1")
    _type(scr, "BRIBE\n")
    assert scr.text_log.is_waiting_for_input
    assert "BRIBE" in scr.text_log.current_prompt


# --- INSERT ---------------------------------------------------------------------


def _card_party():
    p = Party()
    c = Character("Hero", "M", Race.HUMAN, Profession.FIGHTER)
    c.cards = [1, 1, 1, 1]
    p.add_member(c)
    p.add_member(Character("Spare", "M", Race.HUMAN, Profession.FIGHTER))
    return p, c


def test_insert_cards_in_order_love_sol_moons_death():
    """UltimaMisc.c:2333-2343: ``if (xs != object || object != lastCard)``
    the member dies (HP 0, dead); ``lastCard++`` -- so Love, Sol, Moons,
    Death in that order (lastCard starts at 0x1E, Love, UltimaMain.c:1019).
    The port took the cards in any order."""
    from py_exodus.screens.final import FinalScreen

    p, c = _card_party()
    scr = FinalScreen(party=p)
    assert scr.insert_card("sol", member_idx=0, pos=(31, 12)) is False
    assert p.exodus_cards_status == 0
    assert c.status == Status.DEAD


def test_insert_same_card_twice_kills():
    """UltimaMisc.c:2333: a second Love finds lastCard at Sol -> death."""
    from py_exodus.screens.final import FinalScreen

    p, c = _card_party()
    c.cards[3] = 2
    scr = FinalScreen(party=p)
    assert scr.insert_card("love", member_idx=0, pos=(30, 12)) is True
    assert scr.insert_card("love", member_idx=0, pos=(30, 12)) is False
    assert c.status == Status.DEAD


# --- C-29 (user ruling 2026-11-25): Castle Exodus resets like every town -------


def test_insert_progress_clears_on_entering_exodus(town):
    """UltimaMain.c:1019 ``lastCard = 0x1E;`` -- the card order starts over;
    user ruling C-29: Castle Exodus resets on entry like every town, so
    cards inserted on an earlier visit no longer count."""
    p, c = _card_party()
    p.exodus_cards_status = 0x3  # Love and Sol in, last visit
    scr = town(map_id=2, x=32, y=62, party=p)
    scr.on_enter()
    assert p.exodus_cards_status == 0
    assert scr.game_map.get_tile(30, 11).name == "exodus"  # panel back


def test_insert_progress_clears_on_leaving_exodus(town):
    """User ruling C-29: leaving Castle Exodus drops the inserted cards."""
    p, c = _card_party()
    scr = town(map_id=2, x=32, y=62, party=p)
    p.exodus_cards_status = 0x3
    scr._exit_town()
    assert p.exodus_cards_status == 0


def test_insert_progress_kept_inside_exodus(town):
    """Back from a fight or the Book inside the castle (on_enter again) is
    the same visit: the inserted cards still count."""
    p, c = _card_party()
    scr = town(map_id=2, x=32, y=62, party=p)
    p.exodus_cards_status = 0x3
    scr.on_enter()
    assert p.exodus_cards_status == 0x3


def test_leaving_another_town_keeps_nothing_of_exodus(town):
    """Only Castle Exodus holds card progress; another town's exit does
    not touch exodus_defeated."""
    p, c = _card_party()
    p.exodus_defeated = 1
    scr = town(map_id=3, party=p)
    scr._exit_town()
    assert p.exodus_defeated == 1


def test_insert_progress_never_saved(tmp_path):
    """User ruling C-29: card progress is not written to a save; an old
    save that carries it loads as 0. ``exodus_defeated`` is still saved."""
    import json

    from py_exodus.save_system import SaveSystem

    p, c = _card_party()
    p.exodus_cards_status = 0x5
    p.exodus_defeated = 1
    assert "exodus_cards_status" not in p.to_dict()
    path = tmp_path / "party.json"
    SaveSystem.save_game(p, path)
    assert "exodus_cards_status" not in path.read_text()
    loaded = SaveSystem.load_game(path)
    assert loaded.exodus_cards_status == 0
    assert loaded.exodus_defeated == 1

    # An old save written with the field loads it as 0.
    data = json.loads(path.read_text())
    target = data.get("party", data)
    target["exodus_cards_status"] = 0x7
    path.write_text(json.dumps(data))
    assert SaveSystem.load_game(path).exodus_cards_status == 0


def test_autoplay_inserts_all_four_cards_in_one_visit(pygame_setup, asset_mgr):
    """User ruling C-29: with progress reset on entry, autoplay must still
    finish the cards in one visit: a stale 0x3 from an old visit is dropped
    and autoplay inserts Love, Sol, Moons, Death in order, nobody dying."""
    from py_exodus.autoplay import AutoPlayController
    from py_exodus.screens.final import FinalScreen
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine

    p, c = _card_party()
    p.exodus_cards_status = 0x3
    sm = StateMachine(asset_mgr=asset_mgr)
    scr = TownScreen(party=p, map_id=2, asset_mgr=asset_mgr, start_x=30, start_y=12)
    scr.avatar_x, scr.avatar_y = 30, 12
    scr.game_map.npcs = []  # insertion only, no fights
    sm.push_screen(scr)
    assert p.exodus_cards_status == 0
    ctrl = AutoPlayController(enabled=True, step_interval=0.01)
    for _ in range(200):
        if isinstance(sm.current_screen, FinalScreen):
            break
        ctrl.step(sm)
    assert isinstance(sm.current_screen, FinalScreen)
    assert p.exodus_cards_status == 0xF
    assert p.exodus_defeated == 1
    assert all(not m.is_dead() for m in p.members)


# --- Hand -----------------------------------------------------------------------


def _hand(scr, keys: str) -> None:
    _key(scr, pygame.K_h, "h")
    _type(scr, keys)


def test_hand_food_and_gold(overworld):
    """UltimaMain.c:1790-1846: F/G ask an amount; more than the giver has is
    "Not enough!", taking the taker past 9999 is "Too much!" (the port
    handed only weapons and armour)."""
    a, b = _pm("A", food=500, gold=300), _pm("B", food=9900, gold=9990)
    scr = overworld(party=_party(a, b))
    _hand(scr, "12F50\n")
    assert (a.food, b.food) == (450, 9950)
    _hand(scr, "12F50\n")
    assert scr.text_log.history[-1] == "Too much!"
    assert (a.food, b.food) == (450, 9950)
    _hand(scr, "21G9\n")
    assert (a.gold, b.gold) == (309, 9981)
    _hand(scr, "12G400\n")
    assert scr.text_log.history[-1] == "Not enough!"


def test_hand_gems_keys_powder_torches(overworld):
    """UltimaMain.c:1847-1885: E, then G/K/P/T and a count; the taker may
    not pass 99."""
    a, b = _pm("A", keys=3, torches=5), _pm("B", torches=98)
    scr = overworld(party=_party(a, b))
    _hand(scr, "12EK2\n")
    assert (a.keys, b.keys) == (1, 2)
    _hand(scr, "12ET2\n")
    assert scr.text_log.history[-1] == "Too much!"
    assert (a.torches, b.torches) == (5, 98)


def test_hand_weapon_and_armour(town):
    """UltimaMain.c:1886-1939: W/A and the item letter; one of each goes
    over; the readied weapon or worn armour stays ("In use!") unless the
    giver has another."""
    a, b = _pm("A"), _pm("B")
    a.weapon = WeaponType.SWORD
    a.weapons[WeaponType.SWORD] = 0
    a.armors[ArmorType.CHAIN] = 1
    scr = town(party=_party(a, b))
    _hand(scr, "12WG")
    assert scr.text_log.history[-1] == "In use!"
    assert a.weapon == WeaponType.SWORD and b.weapons.get(WeaponType.SWORD, 0) == 0
    _hand(scr, "12AD")
    assert (a.armors[ArmorType.CHAIN], b.armors[ArmorType.CHAIN]) == (0, 1)
    _hand(scr, "12AD")
    assert scr.text_log.history[-1] == "None!"
    a.weapons[WeaponType.SWORD] = 1
    _hand(scr, "12WG")
    assert (a.weapons[WeaponType.SWORD], b.weapons[WeaponType.SWORD]) == (0, 1)
    assert a.weapon == WeaponType.SWORD


def test_hand_same_member_refused(overworld):
    """UltimaMain.c:1775-1778: ``if (chnum1 == chnum2) { ErrorTone(); return; }``"""
    a, b = _pm("A", food=500), _pm("B")
    scr = overworld(party=_party(a, b))
    _hand(scr, "11")
    assert not scr.text_log.is_waiting_for_input
    assert a.food == 500


# --- Every letter command takes a turn --------------------------------------------


_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _press_letter_and_escape(scr, ch: str) -> None:
    _key(scr, ord(ch), ch)
    for _ in range(6):
        if getattr(scr, "gem_view_active", False):
            _key(scr, pygame.K_ESCAPE)
        if not scr.text_log.is_waiting_for_input:
            break
        _key(scr, pygame.K_ESCAPE)


@pytest.mark.parametrize("ch", [c for c in _LETTERS if c not in "eq"])
def test_every_letter_takes_one_turn_overworld(overworld, ch):
    """UltimaMain.c:1057-1059: ``LetterCommand(gKeyPress); Routine6E35();``
    -- every letter, done, refused or cancelled, ends the turn once."""
    scr = overworld()
    before = scr.party.moves
    _press_letter_and_escape(scr, ch)
    assert scr.party.moves == before + 1, ch


@pytest.mark.parametrize("ch", [c for c in _LETTERS if c not in "e"])
def test_every_letter_takes_one_turn_town(town, ch):
    """UltimaMain.c:1057-1059, in towns too."""
    scr = town()
    scr.game_map.npcs = []
    before = scr.party.moves
    _press_letter_and_escape(scr, ch)
    assert scr.party.moves == before + 1, ch


# --- T-28 (user ruling 2026-11-25): every letter command lets monsters move ----


def _count_calls(scr, name: str) -> list[int]:
    calls = [0]
    real = getattr(scr, name)

    def wrapped(*a, **k):
        calls[0] += 1
        return real(*a, **k)

    setattr(scr, name, wrapped)
    return calls


@pytest.mark.parametrize("ch", [c for c in _LETTERS if c not in "eq"])
def test_every_letter_moves_monsters_once_overworld(overworld, ch):
    """UltimaMisc.c:1357-1401: Routine6E35 ends in ``FinishAll();``
    (1112-1130: SpawnMonster, MoveMonsters, gTimeNegate--) after every
    letter command (UltimaMain.c:1057-1059) -- once, never twice."""
    scr = overworld()
    calls = _count_calls(scr, "_update_creatures")
    _press_letter_and_escape(scr, ch)
    assert calls[0] == 1, ch


@pytest.mark.parametrize("ch", [c for c in _LETTERS if c not in "e"])
def test_every_letter_moves_people_once_town(town, ch):
    """UltimaMisc.c:1357-1401 in towns too: FinishAll once per letter."""
    scr = town()
    scr.game_map.npcs = []
    calls = _count_calls(scr, "_move_people")
    _press_letter_and_escape(scr, ch)
    assert calls[0] == 1, ch


def test_get_chest_lets_monsters_move(overworld):
    """T-28: Get (screens/overworld.py _get_chest) took its turn through
    ``_finish_turn`` alone, so monsters stood still and Negate Time did not
    count down (FinishAll, UltimaMisc.c:1120-1125)."""
    from py_exodus.aura import AuraType

    m = _pm()
    scr = overworld(party=_party(m))
    scr.party.dynamic_objects.append({"tile": "chest", "x": 40, "y": 40})
    scr.party.aura.set(AuraType.QUICKNESS, 5)
    calls = _count_calls(scr, "_update_creatures")
    _key(scr, pygame.K_g, "g")
    _key(scr, pygame.K_1, "1")
    assert calls[0] == 1
    assert scr.party.aura.get_duration() == 4


@pytest.mark.parametrize("keys", ["g1", "gx"])
def test_get_variants_move_monsters_once(overworld, keys):
    """Every Get outcome (opened, Not Here!, a bad member) moves monsters
    once."""
    scr = overworld()
    calls = _count_calls(scr, "_update_creatures")
    _key(scr, pygame.K_g, "g")
    _key(scr, ord(keys[1]), keys[1])
    assert calls[0] == 1


@pytest.mark.parametrize(
    "level, exp, kings, exodus, reason, text",
    [
        (3, 299, True, False, "experience", "Experience more!"),
        (3, 299, True, True, "experience", "Experience more!"),
        (25, 9999, True, False, "no_more", "No more!"),
        (25, 9999, True, True, "no_more", "No more!"),
        (5, 900, False, False, "mark", "Seek ye, the mark of kings!"),
    ],
)
def test_lord_british_refusal_messages(town, level, exp, kings, exodus, reason, text):
    """UltimaMain.c:2357-2380: each refusal has its own message -- 91
    "Experience more!", 92 "No more!" at 25, 93 "Seek ye, the mark of
    kings!" past level 4 without the Mark. LW's after-the-fall 263 "Sosaria
    thanks you!" is gone (user ruling 2026-11-25: the game ends when Exodus
    falls); an old won save (``exodus``) gets the same answers."""
    c = _lb_char(level, exp, kings)
    assert c.lord_british_refusal() == reason
    m = PartyMember(c)
    scr = town(map_id=1, party=_party(m))
    scr.party.exodus_defeated = 1 if exodus else 0
    scr._interact_lord_british(m)
    assert text.lower() in scr.text_log.history[-1].lower()
    assert c.level == level


def _stack_combats(sm) -> int:
    return sum(type(s).__name__ == "CombatScreen" for s in sm.screen_stack)


def test_attack_with_two_adjacent_attackers_starts_one_fight(pygame_setup, asset_mgr):
    """UltimaMain.c:1057-1059: Routine6E35 runs after LetterCommand returns,
    i.e. after the fight; the letter's turn must not run while the combat
    screen is up (it moved the other orc in, which pushed a second fight)."""
    from py_exodus.screens.overworld import OverworldScreen
    from py_exodus.state_machine import StateMachine

    party = _party(_pm("A"), _pm("B"))
    ow = OverworldScreen(party=party, map_id=0, asset_mgr=asset_mgr,
                         start_x=40, start_y=40, random_encounters=False)
    party.x, party.y = 40, 40
    sm = StateMachine(asset_mgr=asset_mgr, audio=None)
    sm.set_screen(ow)
    ow._check_moongates = lambda: None  # type: ignore[method-assign]
    ow.creatures = [
        {"tile_name": "orc", "x": 41, "y": 40, "movement": "ATTACK_AVATAR"},
        {"tile_name": "orc", "x": 39, "y": 40, "movement": "ATTACK_AVATAR"},
    ]
    sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a"))
    sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, unicode="e"))
    assert _stack_combats(sm) == 1


def test_town_attack_takes_no_turn_under_the_fight(pygame_setup, asset_mgr):
    """Same order in towns: no turn while the combat screen is pushed."""
    from py_exodus.screens.town import TownScreen
    from py_exodus.state_machine import StateMachine
    from py_exodus.world.map import MapNpc

    party = _party(_pm("A"), _pm("B"))
    ts = TownScreen(party=party, map_id=3, asset_mgr=asset_mgr, start_x=32, start_y=32)
    ts.avatar_x, ts.avatar_y = 32, 32
    sm = StateMachine(asset_mgr=asset_mgr, audio=None)
    sm.set_screen(ts)
    ts.game_map.npcs = [
        MapNpc(18, "guard", 33, 32, 33, 32),
        MapNpc(18, "guard", 31, 32, 31, 32, movement="ATTACK_AVATAR"),
    ]
    before = party.moves
    sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a"))
    sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
    assert _stack_combats(sm) == 1
    assert party.moves == before


def test_steal_alchemist_gets_the_disarm_bonus(asset_mgr):
    """UltimaMisc.c:521-523 (StealDisarmFail):

        // Alchemists now get steal&disarm bonus also. Apple II version does not.
        if (classType == careerTable[9])
            factor += 0x40;

    User ruling 2026-11-25 (ledger C-27), by the Book of Lore (Alchemist
    "Half Int., some S&D", assets/data/ultima3.txt:160): the Alchemist's
    steal factor is DEX + 64, as for disarming. A roll of DEX + 64 steals.
    """
    from py_exodus import special_commands as sc
    from py_exodus.constants import Direction

    gm = _lcb(asset_mgr)
    alch = _pm("Alch", Profession.ALCHEMIST, dexterity=25, gold=0)
    sc.do_steal(_party(alch), alch, 54, 20, Direction.NORTH, gm, rng=Script([25 + 64]))
    assert gm.get_tile(54, 17).name == "floor"
    assert chests.disarm_factor(alch) == 25 + 64


# --- C-23 LetterCommand S and L (user ruling 2026-11-25) --------------------


def test_lettercommand_s_is_steal_on_the_surface(overworld):
    """UltimaMain.c:1186 (LetterCommand): ``case 'S': Steal(); break;``.
    Steal (2248-2259) asks who (``UPrintMessage(84); chnum = GetChar();``)
    and then a direction. The port's S was Java's Search."""
    scr = overworld()
    _key(scr, pygame.K_s, "s")
    assert scr.text_log.is_waiting_for_input
    assert "STEAL" in scr.text_log.current_prompt
    _key(scr, pygame.K_1, "1")
    assert scr.text_log.is_waiting_for_input
    assert "Direction" in scr.text_log.current_prompt


def test_lettercommand_s_is_steal_in_town(town):
    """UltimaMain.c:1186: towns run the same LetterCommand, so S steals."""
    scr = town()
    _key(scr, pygame.K_s, "s")
    assert "STEAL" in scr.text_log.current_prompt


def test_steal_is_not_an_other_word(town):
    """UltimaMisc.c:2286-2508 (OtherCommand): no STEAL word; an unknown word
    is NoEffect (2507). Stealing is the S letter command."""
    scr = town()
    _key(scr, pygame.K_o, "o")
    scr.text_log.submit_input("STEAL")
    assert not scr.text_log.is_waiting_for_input
    assert "STEAL" not in (scr.text_log.current_prompt or "")


def test_search_gives_no_label_items_or_experience(asset_mgr):
    """UltimaMain.c:1160-1195: there is no Search letter command; S is Steal.
    LW's only search is the Other word (UltimaMisc.c:2445-2453), the shrine
    cards. Java's S (map labels: Exotics, cards, +100 XP) is gone: S on
    Ambrosia's Card of Death label grants nothing."""
    from py_exodus.screens.overworld import OverworldScreen

    party = _party(_pm())
    party.x, party.y = 55, 27
    scr = OverworldScreen(party=party, map_id=13, asset_mgr=asset_mgr,
                          start_x=55, start_y=27, random_encounters=False)
    scr.party.x, scr.party.y = 55, 27
    m = party.members[0]
    xp = m.exp
    _key(scr, pygame.K_s, "s")
    _key(scr, pygame.K_1, "1")
    scr.text_log.cancel_prompt()
    assert m.cards[0] == 0
    assert m.exp == xp


def test_look_names_the_tile(overworld, asset_mgr):
    """UltimaMain.c:2063-2071 (Look): ``UPrintMessage(69); GetDirection(0);
    ... temp = GetXYVal(xs, ys); mon = MonsterHere(xs, ys); if (mon == 255)
    { PrintTile(temp / 4, false);`` -- the tile's name (Tiles.plist)."""
    scr = overworld()
    scr.game_map.set_tile(40, 39, asset_mgr.get_tile_by_name("forest"))
    _key(scr, pygame.K_l, "l")
    assert scr.text_log.is_waiting_for_input
    assert "Look" in scr.text_log.current_prompt
    _key(scr, pygame.K_UP)
    assert "Forest" in scr.text_log.history[-1]


def test_look_names_a_monster_plural_outside_towns(overworld):
    """UltimaMain.c:2090-2091: ``} else { // plural if not in town or castle.
    PrintMonster(Monsters[mon] / 2, (Party[3] != 2 && Party[3] != 3),
    Monsters[mon + VARMON]);`` -- on Sosaria an orc group reads "Orcs", a
    variant 1 orc "Goblins"."""
    scr = overworld()
    scr.creatures = [{"tile_name": "orc", "tile": "orc", "x": 41, "y": 40, "variant": 0},
                     {"tile_name": "orc", "tile": "orc", "x": 39, "y": 40, "variant": 1}]
    _key(scr, pygame.K_l, "l")
    _key(scr, pygame.K_RIGHT)
    assert "Orcs" in scr.text_log.history[-1]
    _key(scr, pygame.K_l, "l")
    _key(scr, pygame.K_LEFT)
    assert "Goblins" in scr.text_log.history[-1]


def test_look_names_a_town_person_singular(town):
    """UltimaMain.c:2090-2091: in a town or castle (Party[3] 2 or 3) the
    monster's name is singular: a guard is "Guard"."""
    from py_exodus.world.map import MapNpc

    scr = town()
    scr.game_map.npcs = [MapNpc(18, "guard", 33, 32, 33, 32)]
    _key(scr, pygame.K_l, "l")
    _key(scr, pygame.K_RIGHT)
    assert "Guard" in scr.text_log.history[-1]
    assert "Guards" not in scr.text_log.history[-1]


def test_look_does_not_open_a_door(town, asset_mgr):
    """UltimaMain.c:1179: ``case 'L': Look(); break;`` -- L only looks.
    The port's L was Java's Open."""
    scr = town()
    door = asset_mgr.get_tile_by_name("locked_door")
    scr.game_map.set_tile(33, 32, door)
    _key(scr, pygame.K_l, "l")
    _key(scr, pygame.K_RIGHT)
    assert scr.game_map.get_tile(33, 32).name == "locked_door"


def test_look_takes_the_turn(overworld):
    """UltimaMain.c:1057-1059: ``LetterCommand(); Routine6E35();`` -- Look,
    like every letter, ends the turn."""
    scr = overworld()
    moves = scr.party.moves
    _key(scr, pygame.K_l, "l")
    _key(scr, pygame.K_UP)
    assert scr.party.moves == moves + 1


# --- Doors open only by Unlock (user 2026-11-25, C-07 addendum) ------------


def test_unlock_needs_a_members_key(town, asset_mgr):
    """UltimaMain.c:2418-2433 (Unlock): ``UPrintMessage(96); chnum =
    GetChar(); ... if (Player[rosNum][38] < 1) { UPrintMessage(67); } else
    { Player[rosNum][38]--; ...`` -- a door opens only for a member's key.
    The port kept Java's keyless unlock (``member=None``), which left a
    closed "door" tile that Java's Open (old L) then removed."""
    from py_exodus.world import doors

    scr = town()
    scr.game_map.set_tile(33, 32, asset_mgr.get_tile_by_name("locked_door"))
    assert doors.unlock_door(scr.game_map, 33, 32) is False
    assert scr.game_map.get_tile(33, 32).name == "locked_door"


def test_there_is_no_open_command(town):
    """UltimaMain.c:1160-1195: LetterCommand has no Open; only tile 184 is
    a door and Unlock (2398-2437) is the one way through. Java's
    BaseMap.openDoor (the old L) is gone."""
    from py_exodus.world import doors

    assert not hasattr(doors, "open_door")
    scr = town()
    assert not hasattr(scr, "_open")


@pytest.mark.parametrize("which", ["town", "overworld"])
def test_walking_into_a_door_does_not_open_it(which, town, overworld, asset_mgr):
    """UltimaMain.c:3169-3212 (ValidDir): ``if ((value < 48) && (value !=
    0) && (value != 16)) GoodPlace = TRUE;`` -- a door (184) is no place to
    step, and nothing opens it on a bump."""
    scr = town() if which == "town" else overworld()
    scr.game_map.set_tile(33 if which == "town" else 41, 32 if which == "town" else 40,
                          asset_mgr.get_tile_by_name("locked_door"))
    before = (scr.avatar_x, scr.avatar_y) if which == "town" else (scr.party.x, scr.party.y)
    _key(scr, pygame.K_RIGHT)
    after = (scr.avatar_x, scr.avatar_y) if which == "town" else (scr.party.x, scr.party.y)
    assert after == before
    tx, ty = (33, 32) if which == "town" else (41, 40)
    assert scr.game_map.get_tile(tx, ty).name == "locked_door"
