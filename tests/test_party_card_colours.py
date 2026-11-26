"""Party cards carry colour in their values (option A, user 2026-11-26)."""
import pygame

from py_exodus.constants import Profession, Race, Sex
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party, PartyMember
from py_exodus.ui import party_panel as pp


def test_health_colours_by_fraction():
    assert pp.health_colours(1.0)[0] == (70, 200, 90)
    assert pp.health_colours(0.5)[0] == (230, 190, 40)
    assert pp.health_colours(0.2)[0] == pp.HP_RED


def _drawn(monkeypatch, food=150, hp=150):
    seen = []
    real = pp._Flow.text

    def spy(self, font, text, color, tight=False):
        seen.append((text, tuple(color)))
        return real(self, font, text, color, tight)

    monkeypatch.setattr(pp._Flow, "text", spy)
    c = Character("A", Sex.MALE, Race.HUMAN, Profession.FIGHTER, hp=hp, max_hp=150, food=food)
    party = Party([PartyMember(c)])
    pp.PartyPanel().render(pygame.Surface((432, 600)), party, pygame.Rect(0, 0, 432, 600))
    first = {}
    for text, col in seen:  # the member card comes before the PARTY supplies
        first.setdefault(text, col)
    return first


def test_values_are_coloured_and_labels_quiet(pygame_setup, monkeypatch):
    drawn = _drawn(monkeypatch)
    assert drawn["HP"] == pp.LABEL and drawn["Food"] == pp.LABEL
    assert drawn["150/150"] == pp.health_colours(1.0)[1]
    assert drawn["S"] == pp.STAT_LETTER["S"] and drawn["W"] == pp.STAT_LETTER["W"]
    assert drawn["MP —"] == pp.NO_MP


def test_low_food_turns_red_and_low_hp_turns_red(pygame_setup, monkeypatch):
    drawn = _drawn(monkeypatch, food=64, hp=30)
    assert drawn["64"] == pp.FOOD_LOW
    assert drawn["30/150"] == pp.health_colours(0.2)[1]
