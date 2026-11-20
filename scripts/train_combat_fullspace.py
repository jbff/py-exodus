"""Collect the full-battlefield combat dataset, retrain CombatPolicyNet (BC), evaluate.

Phase-1 gap fix (2026-11-20): the original combat BC/PPO nets never saw
ship-battle maps (39/40/41), boarding/sea-swimmer creatures, or counts
above 5 — causing deterministic loops in ship-vs-serpent autoplay combat.
This script enumerates EVERY reachable (creature, transport, conflict map,
monster count) cell, collects outcome-filtered symbolic teacher episodes
(train seeds 0-899 only), trains a fresh CombatPolicyNet with BC, and
evaluates the new net vs the shipped checkpoint vs the symbolic baseline
on holdout seeds 900-999 across the full space.

Usage:
  .venv/bin/python scripts/train_combat_fullspace.py            # full run
  .venv/bin/python scripts/train_combat_fullspace.py --eval-only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from py_exodus.nn.combat_bc import (
    evaluate_combat_policy_fullspace,
    load_combat_checkpoint,
    save_combat_checkpoint,
    train_combat_bc,
)
from py_exodus.nn.combat_dataset import (
    collect_battlefield_dataset,
    save_combat_dataset,
)

TRAIN_SEEDS = list(range(0, 900))
HOLDOUT_SEEDS = list(range(900, 1000))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episodes-per-cell", type=int, default=12)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent.parent / "py_exodus" / "nn" / "checkpoints"))
    ap.add_argument("--old-ckpt", default=str(Path(__file__).resolve().parent.parent / "py_exodus" / "nn" / "checkpoints" / "combat_ppo.pt"))
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--skip-collect", action="store_true")
    ap.add_argument("--ppo-iterations", type=int, default=0, help="PPO fine-tune iterations after BC (from combat_ppo_fullspace.pt)")
    ap.add_argument("--eval-episodes-per-cell", type=int, default=3)
    ap.add_argument("--new-ckpt", default=None, help="ckpt to eval in --eval-only mode (default: <out-dir>/combat_bc_fullspace.pt)")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ds_path = out_dir / "combat_dataset_fullspace.json"
    new_ckpt = Path(args.new_ckpt) if args.new_ckpt else out_dir / "combat_bc_fullspace.pt"

    if not args.eval_only and not args.skip_collect:
        t0 = time.time()
        print(f"[collect] full battlefield space, {args.episodes_per_cell} eps/cell ...", flush=True)
        samples, stats = collect_battlefield_dataset(
            TRAIN_SEEDS,
            episodes_per_cell=args.episodes_per_cell,
            max_turns=90,
        )
        print(
            f"[collect] {stats['episodes_total']} episodes, {stats['episodes_won']} won, "
            f"{len(samples)} samples in {time.time() - t0:.0f}s",
            flush=True,
        )
        print(f"[collect] teacher: ship {stats['ship_cells_won']}/{stats['ship_cells_total']} "
              f"land {stats['land_cells_won']}/{stats['land_cells_total']} cells won", flush=True)
        save_combat_dataset(ds_path, samples, stats)
        print(f"[collect] dataset -> {ds_path}", flush=True)

        print(f"[train] BC ({args.epochs} epochs) on CUDA..." , flush=True)
        t1 = time.time()
        model, meta = train_combat_bc(samples, TRAIN_SEEDS, epochs=args.epochs)
        meta["dataset_stats"] = stats
        save_combat_checkpoint(new_ckpt, model, meta)
        print(f"[train] val_acc={meta['val_acc']:.4f} in {time.time() - t1:.0f}s -> {new_ckpt}", flush=True)

    if args.ppo_iterations > 0:
        from py_exodus.nn.combat_ppo import train_combat_ppo

        ppo_ckpt = out_dir / "combat_ppo_fullspace.pt"
        print(f"[ppo] {args.ppo_iterations} iterations warm-started from {new_ckpt.name} ...", flush=True)
        t3 = time.time()
        ppo_model, ppo_meta = train_combat_ppo(
            TRAIN_SEEDS,
            init_checkpoint=new_ckpt,
            iterations=args.ppo_iterations,
        )
        save_combat_checkpoint(ppo_ckpt, ppo_model, ppo_meta)
        print(f"[ppo] meta: {json.dumps({k: v for k, v in ppo_meta.items() if k != 'dataset_stats'})[:200]}", flush=True)
        print(f"[ppo] done in {time.time() - t3:.0f}s -> {ppo_ckpt}", flush=True)
        new_ckpt = ppo_ckpt

    # --- holdout fullspace evaluation -----------------------------------
    dev = "cuda" if _torch_cuda() else "cpu"
    candidates = {"symbolic": None}
    if Path(new_ckpt).exists():
        candidates["new_bc"] = load_combat_checkpoint(new_ckpt, device=dev)[0]
    ppo_ckpt = out_dir / "combat_ppo_fullspace.pt"
    if ppo_ckpt.exists() and ppo_ckpt != new_ckpt:
        candidates["ppo"] = load_combat_checkpoint(ppo_ckpt, device=dev)[0]
    if Path(args.old_ckpt).exists():
        try:
            candidates["shipped_ppo"] = load_combat_checkpoint(args.old_ckpt, device=dev)[0]
        except RuntimeError as exc:
            # Checkpoint predates an encoder/arch change (e.g. the v3
            # 23-action space); it cannot be compared anymore.
            print(f"[eval] skipping incompatible old checkpoint: {exc}", flush=True)

    results = {}
    for name, model in candidates.items():
        t2 = time.time()
        res = evaluate_combat_policy_fullspace(
            model, HOLDOUT_SEEDS, episodes_per_cell=args.eval_episodes_per_cell
        )
        res["seconds"] = round(time.time() - t2, 1)
        results[name] = res
        print(f"[eval] {name}: overall {res['wins']}/{res['episodes']}"
              f" land {res['land']['win_rate']*100:.1f}%"
              f" ship {res['ship']['win_rate']*100:.1f}% ({res['seconds']}s)", flush=True)

    report_path = out_dir / "combat_fullspace_eval_report.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[eval] report -> {report_path}", flush=True)
    return 0


def _torch_cuda() -> bool:
    import torch

    return bool(torch.cuda.is_available())


if __name__ == "__main__":
    raise SystemExit(main())
