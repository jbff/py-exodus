"""APPAR UNEM in a town opens the chest under the avatar (LairWare: the
spell works in towns). The town avatar lives at avatar_x/avatar_y; the
party's x/y keep the overworld tile the town was entered from."""
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from py_exodus.autoplay import batch
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine
from py_exodus.world import portal_entry


def _key(screen, k, ch):
    screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode=ch, mod=0))


def test_appar_unem_opens_the_chest_under_the_town_avatar(monkeypatch):
    pygame.init()
    random.seed(1)
    am = batch._assets()
    party = batch.build_party()
    for m in party.members:
        m.mp = m.max_mp
    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=party, asset_mgr=am))
    party.x, party.y = 56, 31  # Death Gulch entrance
    assert portal_entry.enter_portal(sm.current_screen, 56, 31)
    sm.update(batch.FRAME_DT)
    town = sm.current_screen
    town.avatar_x, town.avatar_y = 15, 8  # a chest tile
    assert town.game_map.get_tile(15, 8).name == "chest"
    gold = party.gold
    monkeypatch.setattr(random, "randrange", lambda *a: 1)  # no fizzle
    cleric = 3
    _key(town, pygame.K_c, "c")
    _key(town, getattr(pygame, f"K_{cleric}"), str(cleric))
    _key(town, pygame.K_b, "b")
    assert town.game_map.get_tile(15, 8).name != "chest"
    assert party.gold > gold
