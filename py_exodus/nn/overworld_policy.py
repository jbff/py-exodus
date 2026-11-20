"""Tactical Overworld Policy Network (8x11x11 local grid + 16-dim context, BC + PPO)."""
from __future__ import annotations

from dataclasses import dataclass
import multiprocessing as mp
from pathlib import Path
import random
import tempfile
from typing import Any

import pygame
import torch
from torch import nn
from torch.distributions import Categorical
from torch.utils.data import DataLoader, TensorDataset

from py_exodus.assets import AssetManager
from py_exodus.autoplay.controller import AutoPlayController
from py_exodus.constants import Direction, Profession, Race, Status, Transport
from py_exodus.entities.character import Character
from py_exodus.entities.party import Party
from py_exodus.nn.combat_bc import load_combat_checkpoint
from py_exodus.nn.combat_dataset import current_git_sha, validate_train_seeds
from py_exodus.nn.combat_env import encode_combat_state, index_to_action, legal_action_mask
from py_exodus.nn.macro_dataset import compute_milestone_score
from py_exodus.screens.overworld import OverworldScreen, can_move_to
from py_exodus.state_machine import StateMachine

OVERWORLD_GRID_CHANNELS = 8
OVERWORLD_PATCH_SIZE = 11
OVERWORLD_CONTEXT_DIM = 16
NUM_OVERWORLD_ACTIONS = 5
MAX_OVERWORLD_PARAMS = 5_000_000

_ACTION_DIRS: tuple[Direction | None, ...] = (
    Direction.NORTH,
    Direction.SOUTH,
    Direction.WEST,
    Direction.EAST,
    None,
)
_ACTION_TO_KEY: tuple[int, ...] = (
    pygame.K_UP,
    pygame.K_DOWN,
    pygame.K_LEFT,
    pygame.K_RIGHT,
    pygame.K_SPACE,
)
_KEY_TO_ACTION: dict[int, int] = {k: i for i, k in enumerate(_ACTION_TO_KEY)}

_STRONG_TILES = frozenset({
    "serpent", "sea_serpent", "dragon", "balron", "daemon", "pirate",
    "pirate_ship", "hydra", "liche", "man_o_war", "devourer", "gargoyle",
})


def _wrap_delta(a: int, b: int, size: int) -> int:
    d = (a - b) % size
    if d > size // 2:
        d -= size
    return d


def encode_overworld_state(
    gmap,
    party: Party,
    screen,
    *,
    sym_key: int | None = None,
) -> tuple[list[list[list[float]]], list[float]]:
    """Encode local 11x11 overworld patch (8ch) and 16-dim tactical context."""
    half = OVERWORLD_PATCH_SIZE // 2
    grid = [[[0.0 for _ in range(OVERWORLD_PATCH_SIZE)] for _ in range(OVERWORLD_PATCH_SIZE)] for _ in range(OVERWORLD_GRID_CHANNELS)]

    px, py = party.x, party.y
    w = getattr(gmap, "width", 64)
    h = getattr(gmap, "height", 64)
    portals = {(getattr(pt, "x", -1), getattr(pt, "y", -1)) for pt in getattr(gmap, "portals", ())}

    for gy in range(OVERWORLD_PATCH_SIZE):
        wy = (py + gy - half) % h
        for gx in range(OVERWORLD_PATCH_SIZE):
            wx = (px + gx - half) % w
            tile = gmap.get_tile(wx, wy) if gmap is not None else None
            if tile is not None:
                if can_move_to(gmap, wx, wy, transport=Transport.FOOT, party=party):
                    grid[0][gy][gx] = 1.0
                if getattr(tile, "swimmable", False):
                    grid[1][gy][gx] = 1.0
                tname = str(getattr(tile, "name", "")).lower()
                if (wx, wy) in portals or any(k in tname for k in ("town", "castle", "dungeon", "shrine")):
                    grid[2][gy][gx] = 1.0

    nearest_dist = 999.0
    nearest_dx = 0.0
    nearest_dy = 0.0
    for c in getattr(screen, "creatures", ()):
        if "x" not in c or "y" not in c:
            continue
        dx = _wrap_delta(c["x"], px, w)
        dy = _wrap_delta(c["y"], py, h)
        tname = str(c.get("tile_name") or c.get("tile") or "").lower()
        dist = abs(dx) + abs(dy)
        if abs(dx) <= half and abs(dy) <= half:
            gx, gy = half + dx, half + dy
            if tname == "whirlpool":
                grid[5][gy][gx] = 1.0
            else:
                grid[3][gy][gx] = 1.0
                if any(s in tname for s in _STRONG_TILES):
                    grid[4][gy][gx] = 1.0
        if tname != "whirlpool" and dist < nearest_dist:
            nearest_dist = float(dist)
            nearest_dx = float(max(-1, min(1, dx)))
            nearest_dy = float(max(-1, min(1, dy)))

    sym_dx, sym_dy = 0.0, 0.0
    if sym_key in _KEY_TO_ACTION:
        d = _ACTION_DIRS[_KEY_TO_ACTION[sym_key]]
        if d is not None:
            sym_dx, sym_dy = float(d.dx), float(d.dy)
            grid[6][half + d.dy][half + d.dx] = 1.0
    grid[7][half][half] = 1.0

    living = [m for m in party.members if not m.is_dead()]
    n_mem = max(1, len(party.members))
    living_ratio = len(living) / n_mem
    min_hp = min((m.hp / max(1, m.max_hp) for m in living), default=0.0)
    avg_hp = sum((m.hp / max(1, m.max_hp) for m in living)) / max(1, len(living))
    min_food = min((m.food for m in living), default=0) / 500.0
    poisoned = sum(1 for m in living if m.status == Status.POISONED) / max(1, len(living))
    min_lvl = min((m.level for m in living), default=1) / 25.0
    on_ship = 1.0 if party.transport == Transport.SHIP else 0.0
    ship_hull = getattr(party, "ship_hull", 0) / 100.0
    wind = getattr(screen, "wind_direction", Direction.NORTH)
    wind_val = (list(Direction).index(wind) / 4.0) if wind in Direction else 0.0

    ctx = [
        living_ratio,
        min_hp,
        avg_hp,
        min(2.0, min_food),
        poisoned,
        min(1.0, min_lvl),
        on_ship,
        ship_hull,
        sym_dx,
        sym_dy,
        min(1.0, nearest_dist / 12.0) if nearest_dist < 999.0 else 1.0,
        nearest_dx,
        nearest_dy,
        float(getattr(party, "trammel_phase", 0)) / 8.0,
        float(getattr(party, "felucca_phase", 0)) / 8.0,
        wind_val,
    ]
    return grid, ctx


def legal_overworld_mask(gmap, party: Party) -> list[bool]:
    """Return 5-element boolean mask for (N, S, W, E, SPACE)."""
    if gmap is None:
        return [True, True, True, True, True]
    w, h = getattr(gmap, "width", 64), getattr(gmap, "height", 64)
    mask: list[bool] = []
    for d in _ACTION_DIRS:
        if d is None:
            mask.append(True)
        else:
            nx, ny = (party.x + d.dx) % w, (party.y + d.dy) % h
            mask.append(bool(can_move_to(gmap, nx, ny, transport=party.transport, party=party)))
    if not any(mask[:4]):
        mask[4] = True
    return mask


class OverworldPolicyNet(nn.Module):
    """CNN + Context MLP actor-critic (~1.3M params) for OverworldScreen movement."""

    def __init__(self) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(OVERWORLD_GRID_CHANNELS, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(128, 128, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        self.ctx_mlp = nn.Sequential(
            nn.Linear(OVERWORLD_CONTEXT_DIM, 64),
            nn.ReLU(),
        )
        flat_dim = 128 * OVERWORLD_PATCH_SIZE * OVERWORLD_PATCH_SIZE + 64
        self.trunk = nn.Sequential(
            nn.Linear(flat_dim, 80),
            nn.ReLU(),
            nn.Linear(80, 128),
            nn.ReLU(),
        )
        self.policy_head = nn.Linear(128, NUM_OVERWORLD_ACTIONS)
        self.value_head = nn.Linear(128, 1)

    def forward(
        self,
        grid: torch.Tensor,
        ctx: torch.Tensor,
        legal_mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        h = torch.cat([self.conv(grid), self.ctx_mlp(ctx)], dim=-1)
        h = self.trunk(h)
        logits = self.policy_head(h)
        if legal_mask is not None:
            logits = logits.masked_fill(~legal_mask.bool(), -1e9)
        return logits, self.value_head(h).squeeze(-1)

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


def save_overworld_checkpoint(path: str | Path, model: OverworldPolicyNet, meta: dict[str, Any]) -> None:
    torch.save({"meta": dict(meta), "state_dict": model.state_dict()}, Path(path))


def load_overworld_checkpoint(path: str | Path, *, device: str = "cpu") -> tuple[OverworldPolicyNet, dict[str, Any]]:
    ckpt = torch.load(Path(path), map_location=device, weights_only=False)
    model = OverworldPolicyNet().to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model, dict(ckpt["meta"])


@dataclass
class OverworldSample:
    grid: list[list[list[float]]]
    ctx: list[float]
    mask: list[bool]
    action_idx: int


def _collect_bc_one_seed(args: tuple[int, int]) -> list[OverworldSample]:
    seed, max_steps = args
    pygame.init()
    am = AssetManager("data")
    am.load_all()
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
    samples: list[OverworldSample] = []

    for s in range(max_steps):
        scr = sm.current_screen
        is_ow = (
            type(scr).__name__ == "OverworldScreen"
            and getattr(getattr(scr, "game_map", None), "id", 0) == 0
            and not getattr(getattr(scr, "text_log", None), "is_waiting_for_input", False)
        )
        if is_ow:
            gmap = scr.game_map
            grid, ctx = encode_overworld_state(gmap, party, scr, sym_key=None)
            mask = legal_overworld_mask(gmap, party)
            key = ctrl.step(sm)
            if key in _KEY_TO_ACTION:
                a_idx = _KEY_TO_ACTION[key]
                if mask[a_idx] and (s % 2 == 0 or len(samples) < 2000):
                    # Re-encode with sym_key so BC sees the target direction hint
                    grid, ctx = encode_overworld_state(gmap, party, scr, sym_key=key)
                    samples.append(OverworldSample(grid=grid, ctx=ctx, mask=mask, action_idx=a_idx))
        else:
            ctrl.step(sm)
        sm.update(0.05)
        if all(m.is_dead() for m in party.members) or getattr(party, "exodus_defeated", 0) > 0:
            break
    return samples


def collect_overworld_bc_data(
    train_seeds: list[int] | tuple[int, ...],
    *,
    max_steps: int = 120_000,
    workers: int = 1,
) -> list[OverworldSample]:
    validate_train_seeds(train_seeds)
    tasks = [(int(s), max_steps) for s in train_seeds]
    if workers <= 1 or len(tasks) <= 1:
        batches = [_collect_bc_one_seed(t) for t in tasks]
    else:
        with mp.Pool(processes=min(workers, len(tasks))) as pool:
            batches = pool.map(_collect_bc_one_seed, tasks)
    out: list[OverworldSample] = []
    for b in batches:
        out.extend(b)
    return out


def train_overworld_bc(
    samples: list[OverworldSample],
    train_seeds: list[int] | tuple[int, ...],
    *,
    out_ckpt: str | Path | None = None,
    epochs: int = 8,
    batch_size: int = 256,
    lr: float = 1e-3,
    device: str | None = None,
) -> tuple[OverworldPolicyNet, dict[str, Any]]:
    validate_train_seeds(train_seeds)
    if not samples:
        raise ValueError("Cannot train OverworldPolicyNet on empty samples.")
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    grids = torch.tensor([s.grid for s in samples], dtype=torch.float32)
    ctxs = torch.tensor([s.ctx for s in samples], dtype=torch.float32)
    masks = torch.tensor([s.mask for s in samples], dtype=torch.bool)
    acts = torch.tensor([s.action_idx for s in samples], dtype=torch.long)

    n_total = len(samples)
    n_val = max(1, int(n_total * 0.15)) if n_total >= 5 else 0
    n_train = n_total - n_val
    perm = torch.randperm(n_total, generator=torch.Generator().manual_seed(42))
    tr, va = perm[:n_train], (perm[n_train:] if n_val > 0 else perm[:n_train])

    model = OverworldPolicyNet().to(device)
    param_count = model.count_parameters()
    if param_count > MAX_OVERWORLD_PARAMS:
        raise RuntimeError(f"OverworldPolicyNet exceeds {MAX_OVERWORLD_PARAMS} params: {param_count}")

    loader = DataLoader(TensorDataset(grids[tr], ctxs[tr], masks[tr], acts[tr]), batch_size=min(batch_size, max(1, n_train)), shuffle=True)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    ce = nn.CrossEntropyLoss()

    model.train()
    for _ in range(epochs):
        for bg, bc, bm, ba in loader:
            bg, bc, bm, ba = bg.to(device), bc.to(device), bm.to(device), ba.to(device)
            opt.zero_grad()
            logits, _ = model(bg, bc, bm)
            loss = ce(logits, ba)
            loss.backward()
            opt.step()

    model.eval()
    with torch.no_grad():
        v_logits, _ = model(grids[va].to(device), ctxs[va].to(device), masks[va].to(device))
        val_acc = float((v_logits.argmax(dim=-1) == acts[va].to(device)).float().mean().item())

    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(train_seeds),
        "param_count": param_count,
        "transitions": n_total,
        "val_acc": val_acc,
        "device": device,
    }
    if out_ckpt is not None:
        save_overworld_checkpoint(out_ckpt, model.to("cpu"), meta)
        model.to(device)
    return model, meta


@dataclass
class OverworldTransition:
    grid: list[list[list[float]]]
    ctx: list[float]
    mask: list[bool]
    action_idx: int
    log_prob: float
    reward: float
    value: float
    done: bool


def _ppo_rollout_one_seed(args: tuple[int, str, str | None, int]) -> dict[str, Any]:
    seed, ow_ckpt, combat_ckpt, max_steps = args
    pygame.init()
    torch.set_num_threads(1)

    am = AssetManager("data")
    am.load_all()
    ow_net = load_overworld_checkpoint(ow_ckpt, device="cpu")[0]
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

    transitions: list[OverworldTransition] = []
    prev_milestone = compute_milestone_score(party)
    prev_levels = sum(m.level for m in party.members)
    prev_living = sum(1 for m in party.members if not m.is_dead())
    prev_action: int | None = None

    def _nearest_threat_dist(scr, gmap) -> int:
        if gmap is None:
            return 999
        w, h = getattr(gmap, "width", 64), getattr(gmap, "height", 64)
        best = 999
        for c in getattr(scr, "creatures", ()):
            if "x" not in c or "y" not in c:
                continue
            if str(c.get("tile_name") or c.get("tile") or "").lower() == "whirlpool":
                continue
            d = abs(_wrap_delta(c["x"], party.x, w)) + abs(_wrap_delta(c["y"], party.y, h))
            if d < best:
                best = d
        return best

    outcome = "SURVIVED"
    for s in range(max_steps):
        scr = sm.current_screen
        sname = type(scr).__name__
        if combat_net is not None and sname == "CombatScreen" and not scr.arena.is_finished:
            arena = scr.arena
            if not arena.is_finished:
                m_idx = arena.active_party_member_idx
                grid, ctx = encode_combat_state(arena, m_idx, screen=scr, asset_mgr=am)
                mask = legal_action_mask(arena, m_idx, asset_mgr=am)
                with torch.no_grad():
                    logits, _ = combat_net(
                        torch.tensor([grid], dtype=torch.float32),
                        torch.tensor([ctx], dtype=torch.float32),
                        torch.tensor([mask], dtype=torch.bool),
                    )
                    a_idx = int(logits.argmax(dim=-1).item())
                arena.execute_turn(index_to_action(a_idx, arena, m_idx, asset_mgr=am))
        elif (
            sname == "OverworldScreen"
            and getattr(getattr(scr, "game_map", None), "id", 0) == 0
            and not getattr(getattr(scr, "text_log", None), "is_waiting_for_input", False)
        ):
            gmap = scr.game_map
            # Peek AutoPlayController's intended action without mutating screen via dry-run?
            # Actually, we only override directional movement if ctrl emits a direction key;
            # non-directional keys (K_e enter, K_b board, K_c cast, K_d dig) execute as-is.
            old_x, old_y = party.x, party.y
            pre_threat = _nearest_threat_dist(scr, gmap)
            sym_key = ctrl.step(sm)
            if sym_key in _KEY_TO_ACTION:
                # Undo the controller's step position change? No—better: let OverworldPolicyNet
                # choose BEFORE ctrl.step when ctrl has no queued text; if we need sym_key,
                # we can query ctrl._step_overworld or simply pass prev sym_key!
                # Even simpler: undo simple 1-tile move by restoring (old_x, old_y) and
                # letting OverworldPolicyNet's chosen key execute via sm.handle_event!
                party.x, party.y = old_x, old_y
                grid, ctx = encode_overworld_state(gmap, party, scr, sym_key=sym_key)
                mask = legal_overworld_mask(gmap, party)
                with torch.no_grad():
                    g_t = torch.tensor([grid], dtype=torch.float32)
                    c_t = torch.tensor([ctx], dtype=torch.float32)
                    m_t = torch.tensor([mask], dtype=torch.bool)
                    logits, val = ow_net(g_t, c_t, m_t)
                    dist = Categorical(logits=logits)
                    idx_t = dist.sample()
                    a_idx = int(idx_t.item())
                    lp = float(dist.log_prob(idx_t).item())
                    v = float(val.item())
                chosen_key = _ACTION_TO_KEY[a_idx]
                sm.handle_event(pygame.event.Event(pygame.KEYDOWN, key=chosen_key, unicode=""))
                # Anti-oscillation & tactical survival shaping
                step_r = 0.002 if a_idx == _KEY_TO_ACTION[sym_key] else 0.0
                if prev_action is not None and (prev_action ^ 1) == a_idx and prev_action < 4 and a_idx < 4:
                    step_r -= 0.015
                post_threat = _nearest_threat_dist(scr, gmap)
                living = [m for m in party.members if not m.is_dead()]
                min_hp = min((m.hp / max(1, m.max_hp) for m in living), default=0.0)
                min_lvl = min((m.level for m in living), default=1)
                low_hull = party.transport == Transport.SHIP and getattr(party, "ship_hull", 100) <= 35
                if (len(living) <= 2 or min_hp < 0.35 or min_lvl < 5 or low_hull) and pre_threat <= 3:
                    if post_threat > pre_threat:
                        step_r += 0.08
                    elif post_threat < pre_threat:
                        step_r -= 0.08
                if low_hull:
                    step_r -= 0.03
                prev_action = a_idx
                transitions.append(
                    OverworldTransition(
                        grid=grid,
                        ctx=ctx,
                        mask=mask,
                        action_idx=a_idx,
                        log_prob=lp,
                        reward=step_r,
                        value=v,
                        done=False,
                    )
                )
        else:
            ctrl.step(sm)

        sm.update(0.05)

        if transitions:
            cur_milestone = compute_milestone_score(party)
            cur_levels = sum(m.level for m in party.members)
            cur_living = sum(1 for m in party.members if not m.is_dead())
            transitions[-1].reward += 2.0 * max(0.0, cur_milestone - prev_milestone)
            transitions[-1].reward += 0.1 * max(0, cur_levels - prev_levels)
            if cur_living < prev_living:
                transitions[-1].reward -= 0.5 * (prev_living - cur_living)
            prev_milestone, prev_levels, prev_living = cur_milestone, cur_levels, cur_living

        if all(m.is_dead() for m in party.members):
            outcome = f"WIPED@{s}"
            if transitions:
                transitions[-1].reward -= 5.0
                transitions[-1].done = True
            break
        if getattr(party, "exodus_defeated", 0) > 0:
            outcome = f"WON@{s}"
            if transitions:
                transitions[-1].reward += 15.0
                transitions[-1].done = True
            break
    else:
        if transitions:
            transitions[-1].done = True

    return {
        "seed": seed,
        "outcome": outcome,
        "transitions": transitions,
        "ep_return": sum(t.reward for t in transitions),
    }


def train_overworld_ppo(
    ow_ckpt: str | Path,
    train_seeds: list[int] | tuple[int, ...],
    *,
    combat_ckpt: str | Path | None = None,
    out_ckpt: str | Path | None = None,
    curriculum_seeds: list[int] | tuple[int, ...] | None = None,
    iterations: int = 3,
    episodes_per_iter: int = 20,
    max_steps: int = 80_000,
    workers: int = 10,
    lr: float = 3e-5,
    clip_eps: float = 0.15,
    kl_coef: float = 0.05,
    ent_coef: float = 0.005,
    value_coef: float = 0.5,
    ppo_epochs: int = 4,
    batch_size: int = 256,
    device: str | None = None,
) -> tuple[OverworldPolicyNet, dict[str, Any]]:
    """Fine-tune OverworldPolicyNet with KL-anchored PPO on training seeds only."""
    validate_train_seeds(train_seeds)
    if curriculum_seeds:
        validate_train_seeds(curriculum_seeds)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model, bc_meta = load_overworld_checkpoint(ow_ckpt, device=device)
    ref_model, _ = load_overworld_checkpoint(ow_ckpt, device=device)
    ref_model.eval()
    for p in ref_model.parameters():
        p.requires_grad_(False)

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    rng = random.Random(42)
    history: list[dict[str, Any]] = []
    total_transitions = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for it in range(iterations):
            tmp_ckpt = Path(tmpdir) / f"ow_iter_{it}.pt"
            save_overworld_checkpoint(tmp_ckpt, model.to("cpu"), bc_meta)
            model.to(device)

            if curriculum_seeds:
                n_cur = episodes_per_iter // 2
                batch_seeds = [rng.choice(curriculum_seeds) for _ in range(n_cur)] + [
                    rng.choice(train_seeds) for _ in range(episodes_per_iter - n_cur)
                ]
            else:
                batch_seeds = [rng.choice(train_seeds) for _ in range(episodes_per_iter)]

            tasks = [(int(s), str(tmp_ckpt), str(combat_ckpt) if combat_ckpt else None, max_steps) for s in batch_seeds]
            if workers <= 1 or len(tasks) <= 1:
                episodes = [_ppo_rollout_one_seed(t) for t in tasks]
            else:
                with mp.Pool(processes=min(workers, len(tasks))) as pool:
                    episodes = pool.map(_ppo_rollout_one_seed, tasks)

            transitions: list[OverworldTransition] = []
            for ep in episodes:
                transitions.extend(ep["transitions"])
            if not transitions:
                continue

            total_transitions += len(transitions)
            n = len(transitions)
            adv = torch.zeros(n, dtype=torch.float32)
            ret = torch.zeros(n, dtype=torch.float32)
            gae, next_v = 0.0, 0.0
            for i in range(n - 1, -1, -1):
                t = transitions[i]
                m = 0.0 if t.done else 1.0
                delta = t.reward + 0.995 * next_v * m - t.value
                gae = delta + 0.995 * 0.95 * m * gae
                adv[i] = gae
                ret[i] = gae + t.value
                next_v = t.value
            adv = (adv - adv.mean()) / adv.std().clamp(min=1e-6)

            grids = torch.tensor([t.grid for t in transitions], dtype=torch.float32)
            ctxs = torch.tensor([t.ctx for t in transitions], dtype=torch.float32)
            masks = torch.tensor([t.mask for t in transitions], dtype=torch.bool)
            acts = torch.tensor([t.action_idx for t in transitions], dtype=torch.long)
            old_lp = torch.tensor([t.log_prob for t in transitions], dtype=torch.float32)

            loader = DataLoader(TensorDataset(grids, ctxs, masks, acts, old_lp, adv, ret), batch_size=min(batch_size, n), shuffle=True)
            model.train()
            for _ in range(ppo_epochs):
                for bg, bc, bm, ba, bolp, badv, bret in loader:
                    bg, bc, bm = bg.to(device), bc.to(device), bm.to(device)
                    ba, bolp, badv, bret = ba.to(device), bolp.to(device), badv.to(device), bret.to(device)
                    logits, vals = model(bg, bc, bm)
                    dist = Categorical(logits=logits)
                    new_lp = dist.log_prob(ba)
                    ratio = torch.exp(new_lp - bolp)
                    pol_loss = -torch.min(ratio * badv, torch.clamp(ratio, 1.0 - clip_eps, 1.0 + clip_eps) * badv).mean()
                    val_loss = nn.functional.mse_loss(vals, bret)
                    ent_loss = -dist.entropy().mean()
                    with torch.no_grad():
                        ref_logits, _ = ref_model(bg, bc, bm)
                    ref_p = torch.softmax(ref_logits, dim=-1)
                    kl_loss = (ref_p * (torch.log(ref_p.clamp(min=1e-8)) - torch.log_softmax(logits, dim=-1))).sum(dim=-1).mean()
                    loss = pol_loss + value_coef * val_loss + ent_coef * ent_loss + kl_coef * kl_loss
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step()

            model.eval()
            wins = sum(1 for ep in episodes if ep["outcome"].startswith("WON"))
            wipes = sum(1 for ep in episodes if ep["outcome"].startswith("WIPED"))
            avg_ret = sum(ep["ep_return"] for ep in episodes) / max(1, len(episodes))
            history.append({"iter": it, "episodes": len(episodes), "wins": wins, "wipes": wipes, "transitions": n, "avg_return": avg_ret})

    peak_vram_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2) if device == "cuda" else 0.0
    meta = {
        "git_sha": current_git_sha(),
        "train_seeds": list(train_seeds),
        "param_count": model.count_parameters(),
        "transitions": total_transitions,
        "iterations": iterations,
        "history": history,
        "peak_vram_mb": peak_vram_mb,
        "device": device,
    }
    if out_ckpt is not None:
        save_overworld_checkpoint(out_ckpt, model.to("cpu"), meta)
        model.to(device)
    return model, meta
