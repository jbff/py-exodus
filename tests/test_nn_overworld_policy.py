"""Unit tests for Tactical Overworld Policy Network (BC + PPO)."""
from __future__ import annotations

from types import SimpleNamespace

import pygame
import pytest
import torch

from py_exodus.constants import Profession, Race, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.overworld_policy import (
    MAX_OVERWORLD_PARAMS,
    NUM_OVERWORLD_ACTIONS,
    OVERWORLD_CONTEXT_DIM,
    OVERWORLD_GRID_CHANNELS,
    OverworldPolicyNet,
    collect_overworld_bc_data,
    encode_overworld_state,
    legal_overworld_mask,
    save_overworld_checkpoint,
    train_overworld_bc,
    train_overworld_ppo,
)


def _make_party() -> Party:
    p = Party()
    for name, race, prof in (
        ("SHADOW", Race.ELF, Profession.THIEF),
        ("GRUMM", Race.DWARF, Profession.FIGHTER),
        ("SERENA", Race.BOBIT, Profession.CLERIC),
        ("ZIRCON", Race.FUZZY, Profession.WIZARD),
    ):
        m = Character(name, "M", race, prof, gold=150)
        m.level = 5
        m.hp = m.max_hp = 200
        p.add_member(m)
    p.x, p.y = 10, 10
    p.transport = Transport.FOOT
    return p


def test_overworld_policy_net_shape_and_param_budget():
    net = OverworldPolicyNet()
    assert net.count_parameters() <= MAX_OVERWORLD_PARAMS
    g = torch.zeros((2, OVERWORLD_GRID_CHANNELS, 11, 11))
    c = torch.zeros((2, OVERWORLD_CONTEXT_DIM))
    m = torch.tensor([[True, False, True, True, True]] * 2)
    logits, val = net(g, c, m)
    assert logits.shape == (2, NUM_OVERWORLD_ACTIONS)
    assert val.shape == (2,)
    assert logits[0, 1].item() < -1e8


def test_overworld_encoding_marks_threat_and_sym_hint(pygame_setup):
    p = _make_party()
    tile = SimpleNamespace(name="grass", swimmable=False, walkable=True, passable=True, dispelable=False)
    gmap = SimpleNamespace(id=0, width=64, height=64, border_behavior="wrap", npcs=(), portals=(), get_tile=lambda x, y: tile)
    scr = SimpleNamespace(creatures=[{"x": 10, "y": 11, "tile_name": "serpent"}])
    grid, ctx = encode_overworld_state(gmap, p, scr, sym_key=pygame.K_UP)
    assert grid[3][6][5] == 1.0  # threat at (dx=0, dy=+1)
    assert grid[4][6][5] == 1.0  # strong threat (serpent)
    assert grid[6][4][5] == 1.0  # sym_key UP at (dx=0, dy=-1)
    assert ctx[8] == 0.0 and ctx[9] == -1.0
    assert legal_overworld_mask(gmap, p) == [True, True, True, True, True]


def test_overworld_policy_rejects_holdout_seeds(tmp_path):
    ckpt = tmp_path / "ow.pt"
    save_overworld_checkpoint(ckpt, OverworldPolicyNet(), {"git_sha": "test"})
    with pytest.raises(ValueError, match="900"):
        collect_overworld_bc_data([900], max_steps=10)
    with pytest.raises(ValueError, match="905"):
        train_overworld_ppo(ckpt, [905], iterations=1, episodes_per_iter=1, max_steps=10, workers=1)


def test_overworld_bc_and_ppo_smoke(tmp_path):
    samples = collect_overworld_bc_data([0], max_steps=60, workers=1)
    assert len(samples) > 0
    bc_ckpt = tmp_path / "ow_bc.pt"
    ppo_ckpt = tmp_path / "ow_ppo.pt"
    _, bc_meta = train_overworld_bc(samples, [0], out_ckpt=bc_ckpt, epochs=1, batch_size=8, device="cpu")
    assert bc_ckpt.exists()
    assert bc_meta["transitions"] == len(samples)

    _, ppo_meta = train_overworld_ppo(
        bc_ckpt,
        [0, 1],
        out_ckpt=ppo_ckpt,
        iterations=1,
        episodes_per_iter=2,
        max_steps=40,
        workers=1,
        ppo_epochs=1,
        batch_size=8,
        device="cpu",
    )
    assert ppo_ckpt.exists()
    assert len(ppo_meta["history"]) == 1
