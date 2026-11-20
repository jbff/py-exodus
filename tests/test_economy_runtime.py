"""Economy-critic strategy tests: yield-scored prey selection."""
from __future__ import annotations

import torch

from py_exodus.autoplay.economy_runtime import EconomyRuntime


class _StubEconomyNet:
    """Rate = creature tier: serpent-ish tiles worth more than orcs."""

    def __init__(self) -> None:
        pass

    def eval(self):
        pass

    def rate(self, feats):
        return torch.tensor([3.0])


def test_runtime_inert_without_checkpoint(tmp_path):
    rt = EconomyRuntime(checkpoint=tmp_path / "nope.pt", enabled=True)
    assert rt.active is False


def test_runtime_disabled_by_default():
    rt = EconomyRuntime(enabled=False)
    assert rt.active is False


def test_select_prey_prefers_high_yield_candidates(tmp_path, monkeypatch):
    rt = EconomyRuntime(checkpoint=tmp_path / "stub.pt", enabled=True)
    rt.model = _StubEconomyNet()

    # Give the stub a rate function driven by nearest-threat identity: the
    # feature row's nearby dict puts the prey tile at distance 0, so a real
    # net could distinguish types; for the stub, score by... we need a
    # distinguishable signal — monkeypatch score_prey instead.
    def fake_score(party, screen, tile_name, cx, cy):
        return {"orc": 1.0, "giant": 9.0, "thief": 5.0}.get(tile_name, 0.0)

    monkeypatch.setattr(rt, "score_prey", fake_score)

    candidates = [("orc", 5, 5), ("orc", 6, 5), ("giant", 8, 3), ("thief", 7, 7)]
    prey = rt.select_prey(party=None, screen=None, candidates=candidates)
    assert prey is not None
    assert (8, 3) in prey  # giant: top yield survives the cut
    assert (5, 5) not in prey and (6, 5) not in prey  # orcs: bottom half cut
    assert len(prey) == 2  # top 50% of 4


def test_select_prey_none_when_inert(tmp_path):
    rt = EconomyRuntime(checkpoint=tmp_path / "nope.pt", enabled=True)
    candidates = [("orc", 5, 5)]
    assert rt.select_prey(None, None, candidates) is None


def test_score_prey_builds_context_row(tmp_path):
    """The scoring row carries the creature-at-distance-0 context."""
    rt = EconomyRuntime(checkpoint=tmp_path / "stub.pt", enabled=True)

    seen_rows = []

    class RecordingNet:
        def eval(self):
            pass

        def rate(self, feats):
            return torch.tensor([1.0])

    import py_exodus.nn.hazard_critic as hc

    real = hc.build_features

    def spy(row):
        seen_rows.append(dict(row))
        return real(row)

    monkeypatch_spy = spy
    rt.model = RecordingNet()
    import py_exodus.autoplay.economy_runtime as er

    monkeypatch_target = er
    # Patch build_features via the module reference economy_runtime imports.
    orig = er.__dict__.get("_features_spy", None)
    # Direct: call score_prey with a minimal fake screen/party and capture
    # through a monkeypatched build_features on the hazard module.
    from types import SimpleNamespace

    fake_party = SimpleNamespace(
        members=[],
        x=5,
        y=6,
        gold=100,
        transport=type("T", (), {"value": "foot"})(),
        ship_hull=None,
        map_id=0,
    )
    fake_screen = SimpleNamespace(game_map=SimpleNamespace(id=0), creatures=(), party=fake_party)
    hc_build = hc.build_features

    import unittest.mock as mock

    with mock.patch.object(hc, "build_features", side_effect=lambda row: (seen_rows.append(dict(row)), real(row))[1]):
        rt.score_prey(fake_party, fake_screen, "giant", 8, 3)

    assert seen_rows, "scoring should build a context row"
    row = seen_rows[0]
    assert row["nearby"].get("giant") == 0
    assert row["x"] == 8 and row["y"] == 3
    assert row["goal"] == "GRIND_AND_LEVEL"
