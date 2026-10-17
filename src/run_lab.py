"""CLI entry: default scenario and an optional small sweep.

Default command (PROJECT_BRIEF acceptance run):

    python src/run_lab.py --paths 2000 --horizon 500 --p 0.55 --alpha 0.70 --seed 42

Writes results/summary.json and results/trace_sample.csv.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import metrics
from simulate import HONESTY, LabParams, PathResult, make_outcomes, run_strategies

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TRACE_HEADER = (
    "path_id,step,outcome,cash,long_stake,short_stake,"
    "long_debt,short_debt,long_depth,short_depth,reset,ruined"
)
SWEEP_P = (0.45, 0.50, 0.55, 0.60)
SWEEP_ALPHA = (0.50, 0.70, 1.00)


def _check(cfg: dict) -> None:
    if not 0.0 < cfg["p"] < 1.0:
        raise ValueError(f"p must be in (0, 1), got {cfg['p']}")
    if not 0.5 <= cfg["alpha"] <= 1.0:
        raise ValueError(f"alpha must be in [0.5, 1], got {cfg['alpha']}")
    if cfg["paths"] < 1 or cfg["horizon"] < 1:
        raise ValueError("paths and horizon must be positive")
    if cfg["capital"] <= 0 or cfg["base"] <= 0:
        raise ValueError("capital and base must be positive")
    if cfg["risk_cap"] <= 0:
        raise ValueError("risk_cap must be positive")
    if cfg["k"] < 1 or cfg["d_max"] < 0:
        raise ValueError("k must be >= 1 and d_max must be >= 0")
    if cfg["kelly_scale"] < 0:
        raise ValueError("kelly_scale must be >= 0")
    if cfg["tau"] < 0:
        raise ValueError("tau must be >= 0")
    if cfg["trace_paths"] < 0:
        raise ValueError("trace_paths must be >= 0")


def _params(cfg: dict) -> LabParams:
    return LabParams(
        capital=cfg["capital"],
        base=cfg["base"],
        p=cfg["p"],
        alpha=cfg["alpha"],
        k=cfg["k"],
        tau=cfg["tau"],
        d_max=cfg["d_max"],
        risk_cap=cfg["risk_cap"],
        kelly_scale=cfg["kelly_scale"],
    )


def execute(cfg: dict) -> tuple[dict, list[tuple[int, PathResult]]]:
    """Paired ensemble. Trace samples are the first `trace_paths` path ids."""
    _check(cfg)
    params = _params(cfg)
    rng = random.Random(cfg["seed"])
    ensembles: dict[str, list[PathResult]] = {
        "pure_martingale": [],
        "flat_kelly": [],
        "paroli": [],
        "branching": [],
    }
    samples: list[tuple[int, PathResult]] = []
    trace_n = min(cfg["trace_paths"], cfg["paths"])
    for path_id in range(cfg["paths"]):
        outcomes = make_outcomes(rng, cfg["horizon"], cfg["p"])
        keep = path_id < trace_n
        results = run_strategies(outcomes, params, keep_trace=keep)
        for name, result in results.items():
            ensembles[name].append(result)
        if keep:
            samples.append((path_id, results["branching"]))
    summary = {
        "config": {
            "paths": cfg["paths"],
            "horizon": cfg["horizon"],
            "p": cfg["p"],
            "capital": cfg["capital"],
            "base": cfg["base"],
            "alpha": cfg["alpha"],
            "k": cfg["k"],
            "tau": cfg["tau"],
            "d_max": cfg["d_max"],
            "risk_cap": cfg["risk_cap"],
            "kelly_scale": cfg["kelly_scale"],
            "seed": cfg["seed"],
            "trace_paths": cfg["trace_paths"],
        },
        "note": HONESTY,
        "definitions": {
            "drawdown": "(peak_equity - equity) / peak_equity",
            "percentile": "nearest-rank, sorted[ceil(q * n) - 1]",
            "log_growth": "mean ln(W/C0); ruined or non-positive W uses ln(1/C0)",
            "log_floor_unit": metrics.LOG_FLOOR,
            "ruin_step": "1-based index of the first stake that could not be funded",
            "trace": (
                "One row per settled step. Stake and depth columns are the book "
                "that just settled. Debt is post-settlement. reset is 1 if a "
                "lineage collapsed on that step."
            ),
            "paired": True,
        },
        "strategies": [
            metrics.summarize(name, rows, cfg["capital"]) for name, rows in ensembles.items()
        ],
    }
    return summary, samples


def format_trace_csv(samples: list[tuple[int, PathResult]]) -> str:
    lines = [TRACE_HEADER]
    for path_id, result in samples:
        for row in result.trace:
            lines.append(
                f"{path_id},{row['step']},{row['outcome']},{row['cash']},"
                f"{row['long_stake']},{row['short_stake']},{row['long_debt']},{row['short_debt']},"
                f"{row['long_depth']},{row['short_depth']},{row['reset']},{row['ruined']}"
            )
    return "\n".join(lines) + "\n"


def run_sweep(cfg: dict) -> dict:
    """Small p x alpha grid. Uses sweep_paths / sweep_horizon when present."""
    rows = []
    for p in SWEEP_P:
        for alpha in SWEEP_ALPHA:
            grid_cfg = dict(cfg)
            grid_cfg["p"] = p
            grid_cfg["alpha"] = alpha
            grid_cfg["trace_paths"] = 0
            summary, _ = execute(grid_cfg)
            rows.append(
                {
                    "p": p,
                    "alpha": alpha,
                    "strategies": [
                        {
                            "strategy": item["strategy"],
                            "ruin_rate": item["ruin_rate"],
                            "median_terminal": item["median_terminal"],
                            "median_max_drawdown": item["median_max_drawdown"],
                            "mean_log_growth": item["mean_log_growth"],
                        }
                        for item in summary["strategies"]
                    ],
                }
            )
    return {
        "note": HONESTY,
        "config": {
            "paths": cfg["paths"],
            "horizon": cfg["horizon"],
            "capital": cfg["capital"],
            "base": cfg["base"],
            "k": cfg["k"],
            "tau": cfg["tau"],
            "d_max": cfg["d_max"],
            "risk_cap": cfg["risk_cap"],
            "kelly_scale": cfg["kelly_scale"],
            "seed": cfg["seed"],
            "p_grid": list(SWEEP_P),
            "alpha_grid": list(SWEEP_ALPHA),
        },
        "grid": rows,
    }


def _cfg_from_args(args: argparse.Namespace, tau: float) -> dict:
    return {
        "paths": args.paths,
        "horizon": args.horizon,
        "p": args.p,
        "capital": args.capital,
        "base": args.base,
        "alpha": args.alpha,
        "k": args.k,
        "tau": tau,
        "d_max": args.d_max,
        "risk_cap": args.risk_cap,
        "kelly_scale": args.kelly_scale,
        "seed": args.seed,
        "trace_paths": args.trace_paths,
    }


def _print_summary(summary: dict) -> None:
    print(summary["note"])
    for row in summary["strategies"]:
        print(
            f"{row['strategy']}: ruin={row['ruin_rate']:.4f} "
            f"median_terminal={row['median_terminal']:.4f} "
            f"median_max_dd={row['median_max_drawdown']:.4f} "
            f"mean_log_growth={row['mean_log_growth']:.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Branching recovery Monte Carlo lab")
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--horizon", type=int, default=500)
    parser.add_argument("--p", type=float, default=0.55)
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--base", type=float, default=1.0)
    parser.add_argument("--alpha", type=float, default=0.70)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument(
        "--tau",
        type=float,
        default=None,
        help="Absolute debt trigger. Default is 8 * base.",
    )
    parser.add_argument("--d-max", type=int, default=6)
    parser.add_argument("--risk-cap", type=float, default=0.25)
    parser.add_argument("--kelly-scale", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--trace-paths", type=int, default=25)
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run a small p x alpha grid (200 paths, horizon 200) into results/sweep.json.",
    )
    args = parser.parse_args()
    tau = args.base * 8.0 if args.tau is None else args.tau
    cfg = _cfg_from_args(args, tau)
    try:
        _check(cfg)
    except ValueError as exc:
        parser.error(str(exc))

    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.sweep:
        sweep_cfg = dict(cfg)
        sweep_cfg["paths"] = 200
        sweep_cfg["horizon"] = 200
        sweep_cfg["trace_paths"] = 0
        sweep = run_sweep(sweep_cfg)
        out = RESULTS / "sweep.json"
        out.write_text(json.dumps(sweep, indent=2) + "\n")
        print(sweep["note"])
        print(f"wrote {out}")
        return

    summary, samples = execute(cfg)
    summary_path = RESULTS / "summary.json"
    trace_path = RESULTS / "trace_sample.csv"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    trace_path.write_text(format_trace_csv(samples))
    _print_summary(summary)
    print(f"wrote {summary_path}")
    print(f"wrote {trace_path}")


if __name__ == "__main__":
    main()
