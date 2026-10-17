"""Branching-only regime study.

Answers, for the branching rule alone:

- when a branch is declared (k versus tau)
- which alpha clears a debt episode quickly
- how those answers change with p

Resolution is the share of steps a path spends with any lineage in debt,
plus the share of debt episodes that return both debts to zero.
Growth and ruin are reported beside resolution so a fast reset is not
mistaken for an edge.

    python src/study_branching.py

Writes results/branching_study.json. Does not replace summary.json.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from metrics import median, nearest_rank
from simulate import HONESTY, LabParams, run_branching, run_pure_martingale

LOG_FLOOR = 1.0

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
EPS = 1e-9

PATHS = 2000
HORIZON = 500
SEED = 42
CAPITAL = 1000.0
BASE = 1.0
D_MAX = 6
RISK_CAP = 0.25

P_GRID = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65)
ALPHA_GRID = (0.50, 0.60, 0.70, 0.75, 0.80, 0.90, 1.00)
K_GRID = (1, 2, 3, 4, 5, 6, 8)
TAU_GRID = (1.0, 3.0, 7.0, 15.0, 31.0, 63.0, 127.0)
# tau far above any stake the risk cap will still fund, so only k can fire.
TAU_OFF = 1.0e12
# k far above the longest unsplit losing run, so only tau can fire.
K_OFF = 99


def _log_growth(terminal: float, ruined: bool) -> float:
    wealth = LOG_FLOOR if ruined or terminal <= 0.0 else terminal
    return math.log(wealth / CAPITAL)


def _episodes(trace: list[dict]) -> tuple[list[tuple[int, bool, int | None]], tuple[int, bool, int | None] | None, int, int]:
    """Debt episodes from a branching trace.

    A completed episode is (length, branched, steps_to_branched_settlement).
    steps_to_branched_settlement counts the settled step of the first
    two-sided book, measured from the step debt appeared. The branch was
    declared one proposal earlier. The fourth return is steps with both debts.
    """
    done: list[tuple[int, bool, int | None]] = []
    start: int | None = None
    branch_at: int | None = None
    both_debt_steps = 0
    debt_steps = 0
    for row in trace:
        long_debt = row["long_debt"]
        short_debt = row["short_debt"]
        in_debt = long_debt > EPS or short_debt > EPS
        both_book = row["long_stake"] > EPS and row["short_stake"] > EPS
        if in_debt:
            debt_steps += 1
            if long_debt > EPS and short_debt > EPS:
                both_debt_steps += 1
        if start is None:
            if in_debt:
                start = row["step"]
                branch_at = row["step"] if both_book else None
            continue
        if both_book and branch_at is None:
            branch_at = row["step"]
        if not in_debt:
            done.append((row["step"] - start + 1, branch_at is not None, None if branch_at is None else branch_at - start + 1))
            start = None
            branch_at = None
    open_episode = None
    if start is not None and trace:
        last = trace[-1]["step"]
        open_episode = (last - start + 1, branch_at is not None, None if branch_at is None else branch_at - start + 1)
    return done, open_episode, debt_steps, both_debt_steps


def _cell(p: float, alpha: float, k: int, tau: float, paths: int, seed: int) -> dict:
    params = LabParams(
        capital=CAPITAL,
        base=BASE,
        p=p,
        alpha=alpha,
        k=k,
        tau=tau,
        d_max=D_MAX,
        risk_cap=RISK_CAP,
    )
    rng = random.Random(seed)
    terminals: list[float] = []
    drawdowns: list[float] = []
    depths: list[int] = []
    logs: list[float] = []
    ruined = 0
    above = 0
    hit_depth = 0
    clear_lengths: list[int] = []
    branched_clear_lengths: list[int] = []
    plain_clear_lengths: list[int] = []
    steps_to_branch: list[int] = []
    episodes = 0
    cleared = 0
    branched_episodes = 0
    branched_cleared = 0
    debt_steps = 0
    both_debt_steps = 0
    settled_steps = 0
    for _ in range(paths):
        outcomes = [1 if rng.random() < p else 0 for _ in range(HORIZON)]
        result = run_branching(outcomes, params, keep_trace=True)
        terminals.append(result.terminal)
        drawdowns.append(result.max_drawdown)
        depths.append(result.max_depth)
        logs.append(_log_growth(result.terminal, result.ruined))
        ruined += int(result.ruined)
        above += int(result.terminal > CAPITAL)
        hit_depth += int(result.max_depth >= D_MAX)
        done, _open, debt_n, both_n = _episodes(result.trace)
        debt_steps += debt_n
        both_debt_steps += both_n
        settled_steps += result.steps
        for length, branched, delay in done:
            episodes += 1
            cleared += 1
            clear_lengths.append(length)
            if branched:
                branched_episodes += 1
                branched_cleared += 1
                branched_clear_lengths.append(length)
                if delay is not None:
                    steps_to_branch.append(delay)
            else:
                plain_clear_lengths.append(length)
        if _open is not None:
            episodes += 1
            if _open[1]:
                branched_episodes += 1
                if _open[2] is not None:
                    steps_to_branch.append(_open[2])
    n = paths
    return {
        "p": p,
        "alpha": alpha,
        "k": k,
        "tau": tau,
        "paths": n,
        "ruin_rate": ruined / n,
        "median_terminal": median(terminals),
        "mean_terminal": sum(terminals) / n,
        "frac_above_start": above / n,
        "median_max_drawdown": median(drawdowns),
        "p95_max_drawdown": nearest_rank(drawdowns, 0.95),
        "mean_log_growth": sum(logs) / n,
        "debt_frac": debt_steps / settled_steps if settled_steps else None,
        "both_debt_frac": both_debt_steps / settled_steps if settled_steps else None,
        "episodes": episodes,
        "clear_rate": cleared / episodes if episodes else None,
        "branch_rate": branched_episodes / episodes if episodes else None,
        "branched_clear_rate": branched_cleared / branched_episodes if branched_episodes else None,
        "median_clear_steps": median(clear_lengths) if clear_lengths else None,
        "median_branched_clear_steps": median(branched_clear_lengths) if branched_clear_lengths else None,
        "median_plain_clear_steps": median(plain_clear_lengths) if plain_clear_lengths else None,
        "median_steps_to_branch": median(steps_to_branch) if steps_to_branch else None,
        "frac_hit_dmax": hit_depth / n,
        "median_max_depth": median(depths),
    }


def _martingale(p: float, paths: int, seed: int) -> dict:
    params = LabParams(capital=CAPITAL, base=BASE, p=p, risk_cap=RISK_CAP)
    rng = random.Random(seed)
    terminals: list[float] = []
    drawdowns: list[float] = []
    logs: list[float] = []
    ruined = 0
    above = 0
    for _ in range(paths):
        outcomes = [1 if rng.random() < p else 0 for _ in range(HORIZON)]
        result = run_pure_martingale(outcomes, params)
        terminals.append(result.terminal)
        drawdowns.append(result.max_drawdown)
        logs.append(_log_growth(result.terminal, result.ruined))
        ruined += int(result.ruined)
        above += int(result.terminal > CAPITAL)
    n = paths
    return {
        "p": p,
        "strategy": "pure_martingale",
        "paths": n,
        "ruin_rate": ruined / n,
        "median_terminal": median(terminals),
        "mean_terminal": sum(terminals) / n,
        "frac_above_start": above / n,
        "median_max_drawdown": median(drawdowns),
        "p95_max_drawdown": nearest_rank(drawdowns, 0.95),
        "mean_log_growth": sum(logs) / n,
    }


def _trigger_row(k: int, tau: float) -> dict:
    """First settled two-sided book on an all-loss path. Favored side is long."""
    params = LabParams(p=0.55, alpha=0.70, k=k, tau=tau, d_max=D_MAX, risk_cap=RISK_CAP)
    result = run_branching([0] * 12, params, keep_trace=True)
    for row in result.trace:
        if row["long_stake"] > EPS and row["short_stake"] > EPS:
            return {
                "k": k,
                "tau": tau,
                "settled_step": row["step"],
                "losses_before_branch": row["step"] - 1,
                "long_stake": row["long_stake"],
                "short_stake": row["short_stake"],
                "long_debt_after": row["long_debt"],
                "capped": abs(row["long_stake"] - BASE) <= 1e-6 and abs(row["short_stake"] - BASE) <= 1e-6,
            }
    return {"k": k, "tau": tau, "settled_step": None, "losses_before_branch": None, "capped": False}


def _print_table(title: str, rows: list[dict], keys: list[str]) -> None:
    print(f"\n{title}")
    head = " ".join(f"{key:>22}" for key in keys)
    print(head)
    for row in rows:
        cells = []
        for key in keys:
            value = row[key]
            if isinstance(value, float):
                cells.append(f"{value:22.4f}")
            else:
                cells.append(f"{str(value):>22}")
        print(" ".join(cells))


def main() -> None:
    started = time.perf_counter()
    triggers = [_trigger_row(k, tau) for k in K_GRID for tau in (1.0, 3.0, 7.0, 8.0, 15.0, 31.0, 63.0, TAU_OFF)]
    alpha_p = [
        _cell(p, alpha, k=2, tau=8.0 * BASE, paths=PATHS, seed=SEED)
        for p in P_GRID
        for alpha in ALPHA_GRID
    ]
    k_p = [
        _cell(p, alpha=0.70, k=k, tau=TAU_OFF, paths=PATHS, seed=SEED)
        for p in (0.45, 0.50, 0.55, 0.60)
        for k in K_GRID
    ]
    tau_p = [
        _cell(p, alpha=0.70, k=K_OFF, tau=tau, paths=PATHS, seed=SEED)
        for p in (0.45, 0.50, 0.55, 0.60)
        for tau in TAU_GRID
    ]
    alpha_k = [
        _cell(0.55, alpha, k=k, tau=TAU_OFF, paths=PATHS, seed=SEED)
        for alpha in (0.50, 0.70, 0.80, 0.90, 1.00)
        for k in (1, 2, 3, 4, 6)
    ]
    martingale = [_martingale(p, PATHS, SEED) for p in P_GRID]
    payload = {
        "note": HONESTY,
        "config": {
            "paths": PATHS,
            "horizon": HORIZON,
            "capital": CAPITAL,
            "base": BASE,
            "d_max": D_MAX,
            "risk_cap": RISK_CAP,
            "seed": SEED,
            "p_grid": list(P_GRID),
            "alpha_grid": list(ALPHA_GRID),
            "k_grid": list(K_GRID),
            "tau_grid": list(TAU_GRID),
            "tau_off": TAU_OFF,
            "k_off": K_OFF,
            "resolution": (
                "debt_frac is the share of settled steps with either debt positive. "
                "clear_rate is the share of debt episodes that return both debts to zero "
                "before the path stops. median_clear_steps is among cleared episodes only. "
                "A two-sided book is the settled step of a branch; it was declared on the previous proposal."
            ),
        },
        "triggers": triggers,
        "martingale": martingale,
        "alpha_by_p": alpha_p,
        "k_by_p": k_p,
        "tau_by_p": tau_p,
        "alpha_by_k_at_p_0_55": alpha_k,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "branching_study.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    show = [
        "p",
        "alpha",
        "k",
        "ruin_rate",
        "debt_frac",
        "both_debt_frac",
        "clear_rate",
        "median_clear_steps",
        "median_branched_clear_steps",
        "mean_log_growth",
        "median_terminal",
        "p95_max_drawdown",
        "frac_hit_dmax",
    ]
    _print_table("alpha x p at k=2, tau=8", alpha_p, ["p", "alpha", "debt_frac", "both_debt_frac", "clear_rate", "branch_rate", "branched_clear_rate", "median_clear_steps", "median_branched_clear_steps", "ruin_rate", "mean_log_growth", "median_terminal", "p95_max_drawdown", "frac_hit_dmax"])
    _print_table("k x p at alpha=0.70, tau off", k_p, ["p", "k", "debt_frac", "branch_rate", "branched_clear_rate", "clear_rate", "median_steps_to_branch", "median_branched_clear_steps", "ruin_rate", "mean_log_growth", "frac_hit_dmax"])
    _print_table("tau x p at alpha=0.70, k off", tau_p, ["p", "tau", "debt_frac", "branch_rate", "branched_clear_rate", "clear_rate", "median_steps_to_branch", "median_branched_clear_steps", "ruin_rate", "mean_log_growth", "frac_hit_dmax"])
    _print_table("alpha x k at p=0.55, tau off", alpha_k, show)
    print(f"\nwrote {out}")
    print(f"elapsed {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
