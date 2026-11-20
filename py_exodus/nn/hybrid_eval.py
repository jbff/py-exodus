"""Phase 3 holdout evaluator combining MacroCriticNet + CombatPolicyNet + DisagreementLogger."""
from __future__ import annotations

import multiprocessing as mp
import random
from typing import Any

import torch

from py_exodus.assets import AssetManager
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.autoplay.features import extract_macro_features, macro_feature_vector
import py_exodus.autoplay.planner as planner_mod
from py_exodus.constants import Profession, Race
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.combat_bc import load_combat_checkpoint
from py_exodus.nn.combat_env import encode_combat_state, index_to_action, legal_action_mask
from py_exodus.nn.macro_critic import DisagreementLogger, load_macro_checkpoint
from py_exodus.nn.macro_dataset import INDEX_TO_GOAL, legal_goal_mask
from py_exodus.screens.overworld import OverworldScreen
from py_exodus.state_machine import StateMachine


def _eval_one_seed(args: tuple[int, str | None, str | None, int, float]) -> dict[str, Any]:
    seed, macro_ckpt, combat_ckpt, max_steps, residual_alpha = args
    import pygame
    pygame.init()
    torch.set_num_threads(1)

    am = AssetManager("data")
    am.load_all()
    macro_net = load_macro_checkpoint(macro_ckpt, device="cpu")[0] if macro_ckpt else None
    combat_net = load_combat_checkpoint(combat_ckpt, device="cpu")[0] if combat_ckpt else None

    random.seed(seed)
    party = Party()
    party.add_member(Character("SHADOW", "M", Race.ELF, Profession.THIEF, strength=15, dexterity=25, gold=150))
    party.add_member(Character("GRUMM", "M", Race.DWARF, Profession.FIGHTER, strength=25, dexterity=15, gold=150))
    party.add_member(Character("SERENA", "F", Race.BOBIT, Profession.CLERIC, wisdom=25, strength=15, gold=150))
    party.add_member(Character("ZIRCON", "M", Race.FUZZY, Profession.WIZARD, intelligence=25, strength=15, gold=150))
    party.x, party.y = 44, 20

    sm = StateMachine(asset_mgr=am, audio=None)
    sm.set_screen(OverworldScreen(party=party, asset_mgr=am))
    ctrl = AutoPlayController(enabled=True)
    logger = DisagreementLogger()

    orig_eval = planner_mod.evaluate_goal
    step_box = [0]
    goal_cache: dict[tuple[int, int, int, int], Any] = {}

    def _nn_goal(p: Party, map_id: int | str | None = None):
        scr = sm.current_screen
        if type(scr).__name__ not in ("OverworldScreen", "TownScreen"):
            return orig_eval(p, map_id=map_id)
        mid = getattr(getattr(scr, "game_map", None), "id", getattr(p, "map_id", 0))
        cache_key = (step_box[0], int(mid), p.x, p.y)
        if cache_key in goal_cache:
            return goal_cache[cache_key]
        sym_scores = planner_mod.score_goals(p, map_id=mid, screen=scr)
        sym_goal = max(sym_scores, key=sym_scores.__getitem__)
        feats = extract_macro_features(p, map_id=mid, screen=scr)
        vec = macro_feature_vector(feats)
        mask = legal_goal_mask(p, map_id=mid, screen=scr)
        with torch.no_grad():
            f_t = torch.tensor([vec], dtype=torch.float32)
            m_t = torch.tensor([mask], dtype=torch.bool)
            logits, _ = macro_net(f_t, m_t)
            if residual_alpha > 0.0:
                probs = torch.softmax(logits[0], dim=-1)
                combined = {
                    g: sym_scores[g] + residual_alpha * float(probs[i].item())
                    for i, g in enumerate(INDEX_TO_GOAL.values())
                    if mask[i]
                }
                nn_goal = max(combined, key=combined.__getitem__) if combined else sym_goal
            else:
                nn_goal = INDEX_TO_GOAL[int(logits.argmax(dim=-1).item())]
        logger.log(
            seed=seed,
            step=step_box[0],
            map_id=int(mid),
            pos=(p.x, p.y),
            nn_goal=nn_goal.value,
            sym_goal=sym_goal.value,
        )
        goal_cache.clear()
        goal_cache[cache_key] = nn_goal
        return nn_goal

    import py_exodus.autoplay.controller as ctrl_mod
    if macro_net is not None:
        ctrl_mod.evaluate_goal = _nn_goal

    outcome = "SURVIVED"
    final_goal = "UNKNOWN"
    final_map = 0
    try:
        for s in range(max_steps):
            step_box[0] = s
            scr = sm.current_screen
            if combat_net is not None and type(scr).__name__ == "CombatScreen" and not scr.arena.is_finished:
                arena = scr.arena
                if not arena.is_finished:
                    m_idx = arena.active_party_member_idx
                    grid, ctx = encode_combat_state(arena, m_idx, screen=scr, asset_mgr=am)
                    mask = legal_action_mask(arena, m_idx, asset_mgr=am)
                    with torch.no_grad():
                        g_t = torch.tensor([grid], dtype=torch.float32)
                        c_t = torch.tensor([ctx], dtype=torch.float32)
                        m_t = torch.tensor([mask], dtype=torch.bool)
                        logits, _ = combat_net(g_t, c_t, m_t)
                        a_idx = int(logits.argmax(dim=-1).item())
                    arena.execute_turn(index_to_action(a_idx, arena, m_idx, asset_mgr=am))
            else:
                ctrl.step(sm)
            sm.update(0.05)

            scr = sm.current_screen
            final_map = getattr(getattr(scr, "game_map", None), "id", getattr(party, "map_id", 0))
            if all(m.is_dead() for m in party.members):
                outcome = f"WIPED@{s}"
                final_goal = orig_eval(party, final_map).name
                break
            if getattr(party, "exodus_defeated", 0) > 0:
                outcome = f"WON@{s}"
                final_goal = "DONE"
                break
        else:
            final_goal = orig_eval(party, final_map).name
    finally:
        ctrl_mod.evaluate_goal = orig_eval

    logger.finalize_episode(seed, "WON" if outcome.startswith("WON") else outcome)
    return {
        "seed": seed,
        "outcome": outcome,
        "map_id": final_map,
        "pos": (party.x, party.y),
        "goal": final_goal,
        "gold": party.gold,
        "lvls": [m.level for m in party.members],
        "disagreements": len(logger.events),
        "nn_won_disagreements": len(logger.nn_won_disagreements()),
    }


def evaluate_hybrid_on_holdout(
    seeds: list[int] | tuple[int, ...],
    macro_ckpt: str | None = None,
    combat_ckpt: str | None = None,
    *,
    max_steps: int = 160_000,
    workers: int = 10,
    residual_alpha: float = 15.0,
) -> list[dict[str, Any]]:
    """Evaluate MacroCriticNet (+ optional CombatPolicyNet) across holdout seeds in parallel."""
    tasks = [(s, macro_ckpt, combat_ckpt, max_steps, residual_alpha) for s in seeds]
    with mp.get_context("fork").Pool(min(workers, len(tasks))) as pool:
        return pool.map(_eval_one_seed, tasks)
