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
