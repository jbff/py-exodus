"""Tests for NN combat policy wired into AutoPlayController (neural-net branch)."""
from __future__ import annotations

import pygame
import pytest

from py_exodus.assets import AssetManager
from py_exodus.autoplay import AutoPlayController
from py_exodus.autoplay.nn_policy import CombatNNPolicy, resolve_device
from py_exodus.screens.combat_screen import CombatScreen
from py_exodus.state_machine import StateMachine

from py_exodus.world.loader import load_conflict_map

from tests.test_autoplay import _make_party


# --- resolve_device -------------------------------------------------------


def test_resolve_device_auto_cpu(monkeypatch):
    import py_exodus.autoplay.nn_policy as np_mod

    monkeypatch.setattr(np_mod, "_cuda_available", lambda: False)
    assert resolve_device("auto") == "cpu"


def test_resolve_device_auto_cuda(monkeypatch):
    import py_exodus.autoplay.nn_policy as np_mod

    monkeypatch.setattr(np_mod, "_cuda_available", lambda: True)
    assert resolve_device("auto") == "cuda"


def test_resolve_device_explicit_cuda_unavailable_falls_back(monkeypatch):
    import py_exodus.autoplay.nn_policy as np_mod

    monkeypatch.setattr(np_mod, "_cuda_available", lambda: False)
    assert resolve_device("cuda") == "cpu"


def test_resolve_device_explicit_cpu(monkeypatch):
    assert resolve_device("cpu") == "cpu"


# --- CombatNNPolicy -------------------------------------------------------


def test_policy_missing_checkpoint_raises(tmp_path):
    with pytest.raises(RuntimeError, match="checkpoint missing"):
        CombatNNPolicy(checkpoint=tmp_path / "does_not_exist.pt", device="cpu")


def test_policy_default_checkpoint_loads():
    """The shipped combat_ppo.pt checkpoint must load on the default path."""
    policy = CombatNNPolicy(device="cpu")
    assert policy.available is True
    assert isinstance(policy.meta, dict)


# --- controller wiring ---------------------------------------------------


@pytest.fixture(scope="module")
def asset_mgr():
    am = AssetManager("data")
    am.load_all()
    return am


def _combat_screen(asset_mgr, party=None):
    party = party or _make_party(level=5, exp=500)
    combat_map = load_conflict_map("cnflct_a.json", asset_mgr)
    return CombatScreen(
        party=party,
        combat_map=combat_map,
        asset_mgr=asset_mgr,
        encounter_type="goblin",
    )


def test_controller_default_has_no_nn_policy():
    ctrl = AutoPlayController(enabled=True)
    assert ctrl.nn_combat_policy is None


def test_controller_nn_missing_checkpoint_raises(monkeypatch, tmp_path):
    # No symbolic fallback on the NN branch: a broken NN setup must error
    # out at construction, before any gameplay.
    import py_exodus.autoplay.nn_policy as np_mod

    monkeypatch.setattr(np_mod, "DEFAULT_CHECKPOINT", tmp_path / "nope.pt")
    with pytest.raises(RuntimeError, match="checkpoint missing"):
        AutoPlayController(enabled=True, nn_combat=True, nn_device="cpu")


def test_nn_inference_error_propagates(pygame_setup, asset_mgr):
    """No fallback on the NN branch: a failing net must raise, loudly."""
    ctrl = AutoPlayController(enabled=True, nn_combat=True, nn_device="cpu")
    if not ctrl.nn_combat_policy.available:
        pytest.skip("combat checkpoint/torch unavailable")
    ctrl.nn_combat_policy.model = object()  # not a net: chooser will raise
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)
    with pytest.raises(TypeError):
        ctrl.step(sm)


def test_real_policy_executes_turns_without_crash(pygame_setup, asset_mgr):
    """Smoke: the shipped net drives a real arena past several turns."""
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)

    ctrl = AutoPlayController(enabled=True, step_interval=0.05, nn_combat=True)
    if not ctrl.nn_combat_policy.available:  # torch or checkpoint missing
        pytest.skip("combat checkpoint/torch unavailable")
    for _ in range(240):
        ctrl.step(sm)
        sm.update(0.05)
        if combat.arena.is_finished:
            break
    assert combat.arena.log_messages or combat.text_log.lines, (
        "NN policy should have executed combat actions"
    )


def test_sm_scales_dt_for_combat_screen_in_autoplay(pygame_setup, asset_mgr, monkeypatch):
    """Autoplay accelerates combat FX like symbolic auto-combat does.

    Regression: NN autoplay combat ran FX at manual pacing (0.35s per hit)
    because the screen's fx_dt acceleration gate only fires with
    auto_combat on; the state machine must scale dt the same way.
    """
    ctrl = AutoPlayController(enabled=True, step_interval=0.02, nn_combat=True)
    if not ctrl.nn_combat_policy.available:
        pytest.skip("combat checkpoint/torch unavailable")
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)
    ctrl.step(sm)  # sets autoplay_enabled + autoplay_step_interval
    assert sm.autoplay_enabled is True

    seen = []
    monkeypatch.setattr(combat, "update", lambda dt: seen.append(dt))
    sm.update(0.05)
    assert seen, "combat screen should receive update(dt)"
    # Symbolic rule: interval < 0.12 -> dt * (0.12 / interval); 0.05 * 6
    assert seen[0] == pytest.approx(0.05 * (0.12 / 0.02))

    # Outside autoplay (or with screen auto-combat on, which already
    # accelerates internally) there must be no extra scaling.
    monkeypatch.setattr(combat, "update", lambda dt: seen.append(dt))
    sm.autoplay_enabled = False
    seen.clear()
    sm.update(0.05)
    assert seen[0] == pytest.approx(0.05)

    sm.autoplay_enabled = True
    combat.auto_combat = True
    seen.clear()
    sm.update(0.05)
    assert seen[0] == pytest.approx(0.05)
