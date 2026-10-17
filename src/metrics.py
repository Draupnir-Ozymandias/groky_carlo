"""Ensemble summaries for paired strategy paths.

Drawdown is (peak equity - equity) / peak equity.
Log-growth uses natural log. Ruined paths, and any non-positive terminal,
contribute log(epsilon / C0) with epsilon = 1 currency unit.
The 95th percentile is the nearest rank: sorted[ceil(0.95 * n) - 1].
ruin_step is the 1-based index of the first stake that could not be funded.
"""

from __future__ import annotations

import math
from typing import Iterable

LOG_FLOOR = 1.0


def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of an empty sample")
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def nearest_rank(values: list[float], q: float) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("percentile of an empty sample")
    index = min(n - 1, max(0, math.ceil(q * n) - 1))
    return ordered[index]


def _log_wealth(terminal: float, ruined: bool, capital: float) -> float:
    if ruined or terminal <= 0.0:
        wealth = LOG_FLOOR
    else:
        wealth = terminal
    return math.log(wealth / capital)


def summarize(name: str, results: Iterable, capital: float) -> dict:
    rows = list(results)
    n = len(rows)
    if n == 0:
        raise ValueError(f"no paths for {name}")
    terminals = [r.terminal for r in rows]
    drawdowns = [r.max_drawdown for r in rows]
    depths = [r.max_depth for r in rows]
    ruined_steps = [r.ruin_step for r in rows if r.ruined and r.ruin_step is not None]
    depth_hist: dict[int, int] = {}
    for depth in depths:
        depth_hist[depth] = depth_hist.get(depth, 0) + 1
    return {
        "strategy": name,
        "paths": n,
        "ruin_rate": sum(1 for r in rows if r.ruined) / n,
        "median_steps_to_ruin": median(ruined_steps) if ruined_steps else None,
        "median_terminal": median(terminals),
        "mean_terminal": sum(terminals) / n,
        "frac_above_start": sum(1 for w in terminals if w > capital) / n,
        "frac_hit_1_5_c0": sum(1 for r in rows if r.hit_target) / n,
        "median_max_drawdown": median(drawdowns),
        "p95_max_drawdown": nearest_rank(drawdowns, 0.95),
        "mean_log_growth": sum(_log_wealth(r.terminal, r.ruined, capital) for r in rows) / n,
        "log_floor_unit": LOG_FLOOR,
        "frac_with_reset": sum(1 for r in rows if r.resets > 0) / n,
        "median_max_depth": median(depths),
        "max_depth_hist": {str(k): depth_hist[k] for k in sorted(depth_hist)},
    }
