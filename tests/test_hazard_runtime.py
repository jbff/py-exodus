"""Strategy-layer tests: hazard critic risk costs steer the pathfinder."""
from __future__ import annotations

import pygame
import pytest

from py_exodus.autoplay.hazard_runtime import HazardRuntime
from py_exodus.autoplay.nav import find_2d_step_and_cost
from py_exodus.constants import Direction, Transport
from py_exodus.entities.party import Party

from tests.test_nav_forcefield import _Map, _Tile, _party  # reuse fixtures


def _corridor_with_detour():
    """Two routes east: a shortcut through the risky tile, or a long detour.

    (0,0) start. Shortcut row 0: floor floor. Detour rows 1-2: safe floors.
    Returns map plus the risky tile.
    """
    FLOOR = _Tile("floor", 0)
    return _Map([[FLOOR, FLOOR, FLOOR], [FLOOR, FLOOR, FLOOR], [FLOOR, FLOOR, FLOOR]]), (1, 0)


def test_hazard_costs_push_pathfinder_to_detour():
    gmap, risky = _corridor_with_detour()
    party = _party((1, 1, 1, 1))

    # Baseline: the shortcut via (1,0) is preferred (2 tiles to goal).
    d0, c0 = find_2d_step_and_cost(gmap, (0, 0), {(2, 0)}, Transport.FOOT, party=party, prefer_paths=True)
    assert (d0, c0) == (Direction.EAST, 2)

    # With a big hazard penalty on (1,0), the detour (cost 2+2 tiles = 6 +
    # small extras) must beat the penalized shortcut (2 + alpha).
    costs = {risky: 100.0}
    d1, c1 = find_2d_step_and_cost(
        gmap, (0, 0), {(2, 0)}, Transport.FOOT, party=party, prefer_paths=True,
        hazard_costs=costs, hazard_alpha=10.0,
    )
    assert d1 == Direction.SOUTH  # detour begins
    assert c1 < 2 + 10.0 * 100.0  # planner paid less than the penalized shortcut


def test_no_hazard_costs_means_no_behavior_change():
    gmap, _ = _corridor_with_detour()
    party = _party((1, 1, 1, 1))
    d, _ = find_2d_step_and_cost(
        gmap, (0, 0), {(2, 0)}, Transport.FOOT, party=party, prefer_paths=True,
        hazard_costs=None, hazard_alpha=10.0,
    )
    assert d == Direction.EAST


def test_runtime_inert_without_checkpoint(tmp_path):
    rt = HazardRuntime(checkpoint=tmp_path / "nope.pt", alpha=5.0)
    assert rt.active is False
    assert rt.hazard_costs(None, None) is None


class _StubModel:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, feats):
        import torch

        self.calls += 1
        return torch.zeros(1, 1)


def test_runtime_with_stub_model_builds_costs(tmp_path, monkeypatch):
    import torch

    from py_exodus.autoplay import hazard_runtime as hr

    rt = HazardRuntime(checkpoint=tmp_path / "stub.pt", alpha=100.0, device="cpu")

    class StubNet:
        def eval(self):
            pass

        def risk(self, feats):
            return torch.tensor([3.0])  # sigmoid(3) ~ 0.95

    rt.model = StubNet()
    monkeypatch.setattr(hr, "RISK_REGION", 3)  # small region for test speed

    gmap = _corridor_with_detour()[0]

    class _Scr:
        game_map = gmap

    party = _party((1, 1, 1, 1))
    party.x, party.y = 0, 0
    _Scr.party = party

    costs = rt.hazard_costs(party, _Scr())
    assert costs is not None
    assert costs  # nonzero risk on the region tiles
    assert all(v > 0.5 for v in costs.values())  # ~100 * 0.95 per tile
