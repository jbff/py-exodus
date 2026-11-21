"""Rollout failure atlas: aggregates recorded symbolic autoplay rollouts.

Usage: .venv/bin/python scripts/rollout_atlas.py [--rollout-dir DIR]
       [--seed-min N] [--seed-max N]

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
import re
import zlib
from pathlib import Path


def _rows(path: Path) -> list[dict]:
    if path.suffix == ".gz":
        # Streaming decompress: a recorder killed mid-write leaves a
        # truncated gzip tail that gzip.open raises EOFError on.
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            text = d.decompress(path.read_bytes()).decode("utf-8", "replace")
        except Exception:
            return []
        lines = text.splitlines()
    else:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
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
    ap.add_argument("--seed-min", type=int, default=None)
    ap.add_argument("--seed-max", type=int, default=None)
    args = ap.parse_args()
    base = Path(args.rollout_dir)

    def _seed(path: Path) -> int:
        m = re.search(r"rollout_(\d+)", path.name)
        return int(m.group(1)) if m else -1

    def _selected(path: Path) -> bool:
        s = _seed(path)
        if args.seed_min is not None and s < args.seed_min:
            return False
        if args.seed_max is not None and s > args.seed_max:
            return False
        return True

    outcomes: collections.Counter = collections.Counter()
    wipe_steps: collections.Counter = collections.Counter()
    death_rows: list[dict] = []
    wins: list[dict] = []
    n_files = 0

    dwell_sites: list[tuple[int, int, dict]] = []
    one_survivor = 0
    in_town_deaths = 0

    for f in sorted(base.glob("rollout_*"), key=_seed):
        if not _selected(f):
            continue
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
            if states[-1].get("living") == 1:
                one_survivor += 1
            if states[-1].get("map") not in (0, 13):
                in_town_deaths += 1

        # Dwell: the recorder writes a state row only when position,
        # transport or screen changes, and rows carry the loop step, so the
        # gap between consecutive rows is how long the party stood at the
        # earlier spot. A huge gap at one tile is a stall, not travel.
        best = (0, None)
        for a, b in zip(states, states[1:]):
            gap = int(b.get("step", 0)) - int(a.get("step", 0))
            if gap > best[0]:
                best = (gap, a)
        # Only the overworld maps carry live party coordinates: inside a
        # town party.x/y stay on the entry portal, so a town visit shows one
        # long gap that means "time spent in town", not "stood still".
        if (
            best[0] >= 2000
            and best[1] is not None
            and best[1].get("map") in (0, 13)
        ):
            dwell_sites.append((_seed(f), best[0], best[1]))

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
    print(f"non-starvation deaths: food>100={sum(1 for r in death_rows if r.get('food', 0) > 100)} "
          f"inside-town={in_town_deaths} one-survivor={one_survivor}")

    if dwell_sites:
        dwell_sites.sort(key=lambda t: -t[1])
        print(f"\nmax-dwell stalls (>=2000 ticks at one overworld tile): {len(dwell_sites)}")
        for seed, gap, r in dwell_sites[:12]:
            nbr = ",".join(sorted((r.get("nearby") or {}))[:3])
            print(f"  seed {seed}: {gap} ticks at map {r.get('map')} "
                  f"({r.get('x')},{r.get('y')}) goal={r.get('goal')} "
                  f"transport={r.get('transport')} food={r.get('food')} "
                  f"gold={r.get('gold')} living={r.get('living')} near=[{nbr}]")

    if wins:
        print("\nwinning seeds (teaching examples):")
        for w in wins:
            res = w.get("result", {})
            print(f"  seed {w.get('seed')}: gold={res.get('gold')} "
                  f"levels={res.get('levels')} map={res.get('map')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
