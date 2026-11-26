"""Autoplay tracer, headless batch runner and atlas."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from py_exodus.autoplay import batch
from py_exodus.autoplay.tracer import RunTracer

_ATLAS = Path(__file__).resolve().parent.parent / "scripts" / "autoplay_atlas.py"


def _atlas():
    spec = importlib.util.spec_from_file_location("autoplay_atlas", _ATLAS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_batch_run_seed_writes_a_readable_trace(tmp_path):
    res = batch.run_seed(3, tmp_path, max_steps=400)
    assert res["outcome"] == "STEP_CAP@400"
    rows = _atlas().read_rows(tmp_path / "trace_3.jsonl.gz")
    assert rows[0]["t"] == "start" and rows[0]["seed"] == 3
    assert rows[-1]["t"] == "end" and rows[-1]["outcome"] == "STEP_CAP@400"
    states = [r for r in rows if r["t"] == "s"]
    assert states and all(r["goal"] for r in states)
    assert {"hp", "st", "food", "marks", "cards", "exo", "transport"} <= set(states[0])


def test_batch_is_seed_reproducible(tmp_path):
    a = batch.run_seed(5, tmp_path / "a", max_steps=600)
    b = batch.run_seed(5, tmp_path / "b", max_steps=600)
    assert (a["lv"], a["gold"]) == (b["lv"], b["gold"])


def test_tracer_is_inert_until_activated(tmp_path):
    t = RunTracer(enabled=False, seed=1, out_dir=tmp_path)
    t.record_step(None, None)  # never touches the state machine while inert
    t.end("QUIT")
    assert t.path is None and not list(tmp_path.iterdir())


def test_atlas_classifies_wipe_in_combat_and_oscillation():
    atlas = _atlas()
    base = {"lv": [5, 5, 5, 5], "marks": "K---", "cards": "----", "exo": 0, "st": "GGGG",
            "food": [100] * 4, "scr": "Overworld", "map": 0, "x": 1, "y": 1, "goal": "GRIND_AND_LEVEL"}
    rows = [{"t": "start", "seed": 9}]
    for i, tr in enumerate(["foot", "ship", "foot", "ship", "foot", "ship", "foot", "ship"]):
        rows.append({**base, "t": "s", "step": 10 + i, "transport": tr})
    rows.append({**base, "t": "combat_start", "step": 30, "creatures": ["pirate"], "transport": "ship"})
    rows.append({"t": "end", "outcome": "WIPED@40", **base})
    a = atlas.analyze(rows)
    assert a["kind"] == "WIPED"
    assert a["cause"] == "combat:pirate@sea"
    assert a["flips"] >= 5
    assert a["furthest"] == "on a ship"


def test_snapshot_logs_each_members_marks():
    from py_exodus.autoplay.tracer import party_snapshot

    p = batch.build_party()
    for m in p.members:
        m.marks = [1, 1, 0, 1]
    p.members[2].marks = [1, 0, 0, 1]
    snap = party_snapshot(p)
    assert snap["marks"] == "KF-O"
    assert snap["mk"] == ["KF-O", "KF-O", "K--O", "KF-O"]


def test_combat_start_logs_the_map_fought_on(tmp_path):
    from types import SimpleNamespace

    p = batch.build_party()
    t = RunTracer(enabled=True, seed=1, out_dir=tmp_path)
    rows = []
    t._emit = rows.append
    dungeon = type("DungeonScreen", (), {})()
    dungeon.party, dungeon.state = p, SimpleNamespace(x=3, y=4, z=2, dmap=SimpleNamespace(id=17))
    combat = type("CombatScreen", (), {})()
    combat.party, combat.game_map, combat.arena = p, SimpleNamespace(id=0), SimpleNamespace(monsters=[])
    for scr in (dungeon, combat):
        t.record_step(SimpleNamespace(current_screen=scr), key=None, goal="X")
    assert [r["map"] for r in rows if r["t"] == "combat_start"] == [17]


def test_standing_still_writes_repeat_rows(tmp_path):
    """A stall is visible: on the same tile, an 'r' row with the key and
    why whenever they change, then every 100 repeats."""
    from types import SimpleNamespace

    p = batch.build_party()
    t = RunTracer(enabled=True, seed=1, out_dir=tmp_path)
    rows = []
    t._emit = rows.append
    ow = type("OverworldScreen", (), {})()
    ow.party, ow.game_map = p, SimpleNamespace(id=13)
    sm = SimpleNamespace(current_screen=ow)
    for _ in range(201):
        t.record_step(sm, key=32, goal="X", why="pass")
    t.record_step(sm, key=1, goal="X", why="other")
    reps = [(r["n"], r["key"]) for r in rows if r["t"] == "r"]
    assert reps == [(1, 32), (100, 32), (200, 32), (1, 1)]


def test_state_and_still_rows_carry_the_game_turn(tmp_path):
    """User reports name turns (party.moves); trace_20261125-184644 had no
    turn field, so its stalls could only be matched by estimate. Every 's'
    and 'r' row carries ``moves``."""
    res = batch.run_seed(3, tmp_path, max_steps=400)
    assert res["outcome"] == "STEP_CAP@400"
    rows = _atlas().read_rows(tmp_path / "trace_3.jsonl.gz")
    for kind in ("s", "r"):
        sel = [r for r in rows if r["t"] == kind]
        assert sel, kind
        assert all(isinstance(r.get("moves"), int) for r in sel), kind
    moves = [r["moves"] for r in rows if r["t"] in ("s", "r")]
    assert moves == sorted(moves) and moves[-1] > moves[0]
