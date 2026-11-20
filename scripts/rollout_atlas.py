"""Rollout failure atlas: aggregates recorded symbolic autoplay rollouts.

Usage: .venv/bin/python scripts/rollout_atlas.py [--rollout-dir DIR]

Reads py_exodus/nn/data/rollouts/rollout_*.jsonl.gz (rollout_recorder
output) and prints the failure analysis used to steer autoplay work:
outcomes, wipe-timing buckets, death regions, goal-at-death, resource
profiles, and the voyage-death finding (deaths during supply journeys
while wounded).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path


def _rows(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    lines = opener(path, "rt").read().splitlines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break  # truncated tail (mid-write when the recorder was stopped)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rollout-dir", default="py_exodus/nn/data/rollouts")
    args = ap.parse_args()
    base = Path(args.rollout_dir)

    outcomes: collections.Counter = collections.Counter()
    wipe_steps: collections.Counter = collections.Counter()
    death_rows: list[dict] = []
    wins: list[dict] = []
    n_files = 0

    for f in sorted(base.glob("rollout_*")):
        rows = _rows(f)
        if not rows:
            continue
        n_files += 1
        for r in rows:
            if r.get("t") == "end":
                o = str(r["outcome"])
                outcomes[o.split("@")[0]] += 1
                if o.startswith("WIPED"):
                    wipe_steps[min(int(o.split("@")[1]) // 10000, 15)] += 1
                if o.startswith("WON"):
                    wins.append(r)
        states = [r for r in rows if r.get("t") == "s"]
        if rows[-1].get("outcome", "").startswith("WIPED") and states:
            death_rows.append(states[-1])

    print(f"rollouts: {n_files}")
    print(f"outcomes: {dict(outcomes)}")
    print("wipe timing:")
    for k, v in sorted(wipe_steps.items()):
        if v:
            print(f"  {k * 10}k-{k * 10 + 9}k steps: {v}")

    print("\ndeath regions (map, 8x8 bucket) top 10:")
    regions = collections.Counter(
        (r.get("map"), (r["x"] // 8) * 8, (r["y"] // 8) * 8) for r in death_rows
    )
    for (m, x, y), n in regions.most_common(10):
        print(f"  map {m} around ({x},{y}): {n}")

    goals = collections.Counter(r.get("goal") for r in death_rows)
    print("\ngoal at death:", dict(goals.most_common(6)))

    starved = sum(1 for r in death_rows if r.get("food", 1) == 0)
    broke = sum(1 for r in death_rows if r.get("gold", 0) < 30)
    hurt = sum(1 for r in death_rows if r.get("min_hp_frac", 1.0) < 0.35)
    print(f"\ndeath resource profile: total={len(death_rows)} food0={starved} "
          f"gold<30={broke} min_hp<35%={hurt}")

    threats: collections.Counter = collections.Counter()
    for r in death_rows:
        for t in (r.get("nearby") or {}):
            threats[t] += 1
    print("threat tiles near death:", dict(threats.most_common(8)))

    if wins:
        print("\nwinning seeds (teaching examples):")
        for w in wins:
            res = w.get("result", {})
            print(f"  seed {w.get('seed')}: gold={res.get('gold')} "
                  f"levels={res.get('levels')} map={res.get('map')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
