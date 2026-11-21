"""Autoplay failure atlas: summarize a directory of autoplay traces.

    uv run python scripts/autoplay_atlas.py traces/baseline [--list] [--seed-min A --seed-max B]

Reads ``trace_*.jsonl.gz`` written by ``py_exodus.autoplay.batch`` (or live
``--trace`` runs) and prints:

* outcomes (WON / WIPED / STEP_CAP / CRASHED ...)
* milestone reach: how many runs reached each progression milestone
* furthest milestone per run (where runs stall or die)
* cause-of-death classes for wipes (combat vs creature, starvation, poison)
* B/X transport oscillation and long overworld stalls
* ``--list``: one line per seed
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import zlib
from pathlib import Path

# Ordered progression milestones: (label, predicate over a state/combat row).
MILESTONES: list[tuple[str, object]] = [
    ("all lv>=5", lambda r: min(r.get("lv") or [0]) >= 5),
    ("Mark of Kings", lambda r: "K" in r.get("marks", "")),
    ("on a ship", lambda r: r.get("transport") == "ship"),
    ("8 exotics", lambda r: r.get("exo", 0) >= 8),
    ("Fire+Force", lambda r: "F" in r.get("marks", "") and "O" in r.get("marks", "")),
    ("Mark of Snake", lambda r: "S" in r.get("marks", "")),
    ("Ambrosia", lambda r: r.get("map") == 13),
    ("4 cards", lambda r: r.get("cards", "----").count("-") == 0),
    ("all lv>=25", lambda r: min(r.get("lv") or [0]) >= 25),
    ("Exodus castle", lambda r: r.get("map") == 2),
]


def read_rows(path: Path) -> list[dict]:
    """Read a (possibly truncated) gzipped JSONL trace."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        text = d.decompress(path.read_bytes()).decode("utf-8", "replace")
    except Exception:
        return []
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return out


def _seed_of(path: Path) -> int:
    m = re.search(r"(\d+)", path.name.replace(".jsonl.gz", ""))
    return int(m.group(1)) if m else -1


def analyze(rows: list[dict]) -> dict:
    # After a wipe the game emits post-death rows (living == 0, goal SETUP_PARTY);
    # drop them so cause/goal-at-death describe the moment BEFORE the party died.
    end_row = next((r for r in reversed(rows) if r.get("t") == "end"), None)
    body = [r for r in rows if r.get("t") != "end"]
    while body and body[-1].get("living", 1) == 0:
        body.pop()
    rows = body + ([end_row] if end_row else [])
    states = [r for r in rows if r.get("t") in ("s", "combat_start", "combat_end", "end")]
    end = next((r for r in reversed(rows) if r.get("t") == "end"), None)
    outcome = str(end.get("outcome")) if end else "INCOMPLETE"
    reached: dict[str, int] = {}
    for r in states:
        for label, pred in MILESTONES:
            if label not in reached:
                try:
                    if pred(r):
                        reached[label] = int(r.get("step", 0))
                except Exception:
                    pass
    if outcome.startswith("WON"):
        reached["WON"] = int(outcome.split("@")[1])
    furthest = "start"
    for label, _ in MILESTONES + [("WON", None)]:
        if label in reached:
            furthest = label

    s_rows = [r for r in rows if r.get("t") == "s"]
    last = s_rows[-1] if s_rows else {}
    cause = None
    if outcome.startswith("WIPED"):
        tail = [r for r in rows if r.get("t") in ("s", "combat_start", "combat_end")]
        in_combat = bool(tail) and tail[-1].get("t") == "combat_start"
        ref = end or last
        food = [f for f, st in zip(ref.get("food", []), ref.get("st", "")) if st != "D"] or ref.get("food", [0])
        poisoned = last.get("st", "").count("P")
        if in_combat:
            cause = "combat:" + "+".join(tail[-1].get("creatures") or ["?"])
            if tail[-1].get("transport") == "ship":
                cause += "@sea"
        elif (last.get("near") or {}).get("pirate", 99) <= 4:
            # No combat screen but a pirate ship in cannon range: shot dead on
            # a shore, or the ship was sunk (hull 0 kills the party).
            cause = "cannon:pirate@" + ("sea" if last.get("transport") == "ship" else "shore")
        elif max(last.get("food") or [0]) == 0:
            cause = "starved"
        elif poisoned:
            cause = "poison"
        else:
            cause = "other"
        _ = food

    # Transport oscillation: foot<->ship flips within 6 steps of each other.
    flips = 0
    prev_t, prev_step, prev_flip = None, 0, -100
    for r in s_rows:
        t = r.get("transport")
        if prev_t is not None and t != prev_t:
            if int(r.get("step", 0)) - prev_flip <= 6:
                flips += 1
            prev_flip = int(r.get("step", 0))
        prev_t = t

    # Longest overworld dwell (steps between consecutive state rows on map 0/13).
    dwell = (0, None)
    for a, b in zip(s_rows, s_rows[1:]):
        if a.get("scr") != "Overworld":
            continue
        gap = int(b.get("step", 0)) - int(a.get("step", 0))
        if gap > dwell[0]:
            dwell = (gap, a)

    goals = collections.Counter()
    for a, b in zip(s_rows, s_rows[1:]):
        goals[a.get("goal")] += int(b.get("step", 0)) - int(a.get("step", 0))

    combats = sum(1 for r in rows if r.get("t") == "combat_start")
    return {
        "outcome": outcome,
        "kind": outcome.split("@")[0],
        "reached": reached,
        "furthest": furthest,
        "cause": cause,
        "last": last,
        "flips": flips,
        "dwell": dwell,
        "goal_steps": goals,
        "combats": combats,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace_dir", nargs="?", default="traces/batch")
    ap.add_argument("--seed-min", type=int)
    ap.add_argument("--seed-max", type=int)
    ap.add_argument("--list", action="store_true", help="one line per seed")
    args = ap.parse_args(argv)

    files = sorted(Path(args.trace_dir).glob("trace_*.jsonl.gz"), key=_seed_of)
    results = []
    for f in files:
        s = _seed_of(f)
        if args.seed_min is not None and s < args.seed_min:
            continue
        if args.seed_max is not None and s > args.seed_max:
            continue
        rows = read_rows(f)
        if rows:
            results.append((s, analyze(rows)))
    n = len(results)
    if not n:
        print("no traces")
        return 1

    kinds = collections.Counter(a["kind"] for _, a in results)
    print(f"runs: {n}   outcomes: {dict(kinds.most_common())}")
    wins = [(s, a) for s, a in results if a["kind"] == "WON"]
    if wins:
        print("wins: " + ", ".join(f"{s}@{a['outcome'].split('@')[1]}" for s, a in wins))

    print("\nmilestone reach (runs that ever got there, median step):")
    for label, _ in MILESTONES + [("WON", None)]:
        steps = sorted(a["reached"][label] for _, a in results if label in a["reached"])
        med = steps[len(steps) // 2] if steps else "-"
        print(f"  {label:<14} {len(steps):>4}/{n}   median step {med}")

    print("\nfurthest milestone (where runs ended):")
    furthest = collections.Counter(a["furthest"] for _, a in results)
    for label in ["start"] + [m for m, _ in MILESTONES] + ["WON"]:
        if furthest.get(label):
            print(f"  {label:<14} {furthest[label]}")

    wiped = [(s, a) for s, a in results if a["kind"] == "WIPED"]
    if wiped:
        print(f"\ncause of wipe ({len(wiped)}):")
        causes = collections.Counter(
            re.sub(r"\+.*?(@sea)?$", lambda m: "+..." + (m.group(1) or ""), a["cause"] or "?") for _, a in wiped
        )
        for c, k in causes.most_common(12):
            print(f"  {c:<28} {k}")
        goals = collections.Counter(a["last"].get("goal") for _, a in wiped)
        print("  goal at wipe:", dict(goals.most_common(8)))

    osc = [(s, a["flips"]) for s, a in results if a["flips"] >= 5]
    print(f"\nB/X oscillation (>=5 rapid foot<->ship flips): {len(osc)} runs"
          + (": " + ", ".join(f"{s}({k})" for s, k in sorted(osc, key=lambda t: -t[1])[:12]) if osc else ""))
    stalls = sorted(((s, a["dwell"]) for s, a in results if a["dwell"][0] >= 2000), key=lambda t: -t[1][0])
    print(f"overworld stalls (>=2000 steps at one tile): {len(stalls)}")
    for s, (gap, r) in stalls[:10]:
        print(f"  seed {s}: {gap} steps at map {r.get('map')} ({r.get('x')},{r.get('y')}) goal={r.get('goal')} "
              f"transport={r.get('transport')} food={r.get('food')} gold={r.get('gold')}")

    total_goal = collections.Counter()
    for _, a in results:
        total_goal.update(a["goal_steps"])
    tot = sum(total_goal.values()) or 1
    print("\nshare of steps by goal (incl. combat):",
          ", ".join(f"{g}={100 * v // tot}%" for g, v in total_goal.most_common(10)))

    if args.list:
        print("\nseed  outcome            furthest        cause                    lv            gold  marks cards exo")
        for s, a in results:
            r = a["last"]
            print(f"{s:>4}  {a['outcome']:<18} {a['furthest']:<15} {str(a['cause'] or ''):<24} "
                  f"{str(r.get('lv')):<13} {r.get('gold', ''):>5}  {r.get('marks', '')} {r.get('cards', '')} {r.get('exo', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
