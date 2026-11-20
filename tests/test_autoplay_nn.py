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


def test_controller_nn_combat_drives_arena(pygame_setup, asset_mgr):
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)

    ctrl = AutoPlayController(enabled=True, step_interval=0.05, nn_combat=True)
    assert ctrl.nn_combat_policy is not None

    calls = []

    class StubPolicy:
        available = True

        def step_combat(self, state_machine, screen):
            calls.append((state_machine, screen))
            return None

    ctrl.nn_combat_policy = StubPolicy()
    ctrl.step(sm)
    assert len(calls) == 1
    # NN mode must NOT toggle the symbolic auto-combat.
    assert combat.auto_combat is False


def test_controller_nn_inference_error_propagates(pygame_setup, asset_mgr):
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)

    class BrokenPolicy:
        def step_combat(self, state_machine, screen):
            raise ValueError("cuda exploded")

    ctrl = AutoPlayController(enabled=True, step_interval=0.05, nn_combat=True)
    ctrl.nn_combat_policy = BrokenPolicy()
    with pytest.raises(ValueError, match="cuda exploded"):
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
        sm.update(0.05)  # progress FX so animations complete and logs flush
        if combat.arena.is_finished:
            break
    assert combat.arena.log_messages, "NN policy should have executed combat actions"


def test_real_policy_drives_screen_pipeline(pygame_setup, asset_mgr):
    """NN turns must go through the screen so FX plays and the travelogue logs.

    Regression: driving arena.execute_turn directly bypassed
    CombatScreen._execute_action, leaving zero animations and an empty
    travelogue during NN autoplay.
    """
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)

    ctrl = AutoPlayController(enabled=True, step_interval=0.05, nn_combat=True)
    if not ctrl.nn_combat_policy.available:
        pytest.skip("combat checkpoint/torch unavailable")
    initial = list(combat.text_log.lines)  # e.g. "SHADOW's turn." from init
    for _ in range(240):
        ctrl.step(sm)
        sm.update(0.05)  # progress FX so animations complete and logs flush
        if combat.arena.is_finished:
            break
    new_lines = [
        line
        for line in combat.text_log.lines[len(initial):]
        if not line.endswith("turn.")  # ignore per-turn markers
    ]
    assert new_lines, (
        "travelogue should log NN combat actions beyond turn markers"
    )


def test_policy_waits_for_in_flight_animation(pygame_setup, asset_mgr):
    """While the screen animates, the policy must not execute another turn."""
    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)

    policy = CombatNNPolicy(device="cpu")
    if not policy.available:
        pytest.skip("combat checkpoint/torch unavailable")

    combat._anim_stage = "projectile"
    before = len(combat.arena.log_messages)
    policy.step_combat(sm, combat)
    assert len(combat.arena.log_messages) == before, "should not act mid-animation"
    assert combat._anim_stage == "projectile"  # untouched


def test_policy_handles_party_death_exception(pygame_setup, asset_mgr, monkeypatch):
    """A wipe mid-NN-action routes through the screen's death check."""
    from py_exodus.entities.party import PartyDeathException

    sm = StateMachine(asset_mgr=asset_mgr)
    combat = _combat_screen(asset_mgr)
    sm.push_screen(combat)

    policy = CombatNNPolicy(device="cpu")
    if not policy.available:
        pytest.skip("combat checkpoint/torch unavailable")

    called = []
    monkeypatch.setattr(
        combat, "_execute_action", lambda action: (_ for _ in ()).throw(
            PartyDeathException("wipe")
        )
    )
    monkeypatch.setattr(combat, "check_party_death", lambda: called.append(True))
    policy.step_combat(sm, combat)
    assert called == [True]
