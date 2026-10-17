"""Same branching replay on Binance BTCUSDT 15m, 1h, 4h, and 1d bars.

Each decisive bar is one even-money outcome: up when close > open, down when
close < open. Flat bars are dropped. The lab pays even money on that bit.
It does not earn the bar's dollar move.

2025 chooses the settings. 2026 is the holdout. A window is 500 decisive bars
that start and end inside one calendar year. Daily 2025 has fewer than 500
bars, so that timeframe is ranked by the single continuous 2025 path.

    python src/btc_timeframes.py
    python src/btc_timeframes.py 15m 1h

Writes results/btc_replay_<interval>.json and results/btc_timeframes.json.
Raw zips stay in data/btcusdt_<interval>/.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone

import btc_replay
from simulate import HONESTY

INTERVALS = ("15m", "1h", "4h", "1d")
BASELINES = (
    ("equal_split", 0.50, 2, 8.0),
    ("default", 0.70, 2, 8.0),
    ("no_counter", 1.00, 2, 8.0),
    ("late_trigger", 0.70, 8, 127.0),
)
PATH_KEYS = {
    "equal_split": ("train_equal_split", "test_equal_split"),
    "default": ("train_default", "test_default"),
    "no_counter": ("train_no_counter", "test_no_counter"),
    "late_trigger": ("train_late_trigger", "test_late_trigger"),
    "picked": ("train_best", "test_best"),
}


def _cells() -> list[tuple[float, int, float]]:
    cells = []
    for alpha in btc_replay.ALPHAS:
        for k in btc_replay.KS:
            for tau in btc_replay.TAUS:
                # alpha 1 ignores the split. One (k, tau) cell is enough.
                if alpha == 1.0 and (k != 2 or tau != 8.0):
                    continue
                cells.append((alpha, k, tau))
    return cells


def _iso(millis: int) -> str:
    return datetime.fromtimestamp(millis / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _root_label(p: float) -> str:
    if abs(p - 0.5) <= 1e-9:
        return "both sides, half the base stake on each"
    if p > 0.5:
        return "long only"
    return "short only"


def _score_path(outcomes: list[int], p: float, alpha: float, k: int, tau: float) -> dict:
    path = btc_replay._one_path(outcomes, p, alpha, k, tau)
    path["alpha"] = alpha
    path["k"] = k
    path["tau"] = tau
    path["p"] = p
    path["windows"] = 0
    return path


def _compact_score(label: str, spec: tuple[float, int, float], train_w, test_w, train_path, test_path) -> dict:
    alpha, k, tau = spec
    row = {
        "label": label,
        "alpha": alpha,
        "k": k,
        "tau": tau,
        "window_log_2025": None if train_w is None else train_w["mean_log_growth"],
        "window_log_2026": None if test_w is None else test_w["mean_log_growth"],
        "window_terminal_2025": None if train_w is None else train_w["median_terminal"],
        "window_terminal_2026": None if test_w is None else test_w["median_terminal"],
        "window_p95_drawdown_2026": None if test_w is None else test_w["p95_max_drawdown"],
        "window_ruin_2025": None if train_w is None else train_w["ruin_rate"],
        "window_ruin_2026": None if test_w is None else test_w["ruin_rate"],
        "window_above_2025": None if train_w is None else train_w["frac_above_start"],
        "window_above_2026": None if test_w is None else test_w["frac_above_start"],
        "path_log_2025": train_path["log_growth"],
        "path_log_2026": test_path["log_growth"],
        "path_cash_2025": train_path["terminal"],
        "path_cash_2026": test_path["terminal"],
        "path_drawdown_2025": train_path["max_drawdown"],
        "path_drawdown_2026": test_path["max_drawdown"],
        "path_ruined_2025": train_path["ruined"],
        "path_ruined_2026": test_path["ruined"],
        "debt_long_2025": train_path["end_long_debt"],
        "debt_short_2025": train_path["end_short_debt"],
        "debt_long_2026": test_path["end_long_debt"],
        "debt_short_2026": test_path["end_short_debt"],
    }
    return row


def run_interval(interval: str) -> dict:
    started = time.perf_counter()
    print(f"=== {interval} ===", flush=True)
    btc_replay._download(interval)
    bars = btc_replay._bars(interval)
    if not bars:
        raise SystemExit(f"no bars for {interval}")
    decisive, coverage = btc_replay._directions(bars)
    train = [row for row in decisive if btc_replay._utc_year(row["t"]) == 2025]
    test = [row for row in decisive if btc_replay._utc_year(row["t"]) == 2026]
    if not train or not test:
        raise SystemExit(f"{interval}: need both years, got train {len(train)} test {len(test)}")
    train_w = btc_replay._windows_inside_year(decisive, 2025)
    test_w = btc_replay._windows_inside_year(decisive, 2026)
    for window in train_w + test_w:
        if len(window["outcomes"]) != btc_replay.WINDOW:
            raise RuntimeError(f"{interval}: window length {len(window['outcomes'])}")
        if btc_replay._utc_year(window["t0"]) != window["year"] or btc_replay._utc_year(window["t1"]) != window["year"]:
            raise RuntimeError(f"{interval}: window crosses a calendar year")

    p_hat = sum(row["up"] for row in train) / len(train)
    favored_p = p_hat if abs(p_hat - 0.5) >= 0.01 else 0.5
    train_bits = [row["up"] for row in train]
    test_bits = [row["up"] for row in test]
    cells = _cells()
    mode = "windows" if train_w else "continuous_path"
    print(
        f"  bars {coverage['bars']} decisive {coverage['decisive']} "
        f"windows {len(train_w)}/{len(test_w)} mode {mode} up {p_hat:.4f}",
        flush=True,
    )

    if mode == "windows":
        ranked = []
        for index, (alpha, k, tau) in enumerate(cells, start=1):
            ranked.append(btc_replay._eval(train_w, favored_p, alpha, k, tau))
            if index % 25 == 0 or index == len(cells):
                print(f"  {interval} grid {index}/{len(cells)}", flush=True)
        ranked.sort(key=lambda row: (row["mean_log_growth"], -row["median_max_drawdown"]), reverse=True)
        best = ranked[0]
        holdout = btc_replay._eval(test_w, favored_p, best["alpha"], best["k"], best["tau"]) if test_w else None
        objective = (
            "Maximize mean log-growth of 500-bar windows that start and end inside 2025. "
            "2026 is not used to choose."
        )
    else:
        ranked = []
        for index, (alpha, k, tau) in enumerate(cells, start=1):
            ranked.append(_score_path(train_bits, favored_p, alpha, k, tau))
            if index % 25 == 0 or index == len(cells):
                print(f"  {interval} grid {index}/{len(cells)}", flush=True)
        ranked.sort(key=lambda row: (row["log_growth"], -row["max_drawdown"]), reverse=True)
        best = ranked[0]
        holdout = _score_path(test_bits, favored_p, best["alpha"], best["k"], best["tau"])
        objective = (
            "2025 has fewer than 500 decisive bars, so the grid is ranked by log-growth "
            "of the single continuous 2025 path. That ranking is one path, not a sample. "
            "2026 is not used to choose."
        )

    baseline_rows = []
    for label, alpha, k, tau in BASELINES:
        baseline_rows.append(
            {
                "label": label,
                "alpha": alpha,
                "k": k,
                "tau": tau,
                "train": btc_replay._eval(train_w, favored_p, alpha, k, tau) if train_w else None,
                "test": btc_replay._eval(test_w, favored_p, alpha, k, tau) if test_w else None,
            }
        )

    full = {}
    named = list(BASELINES) + [("best", best["alpha"], best["k"], best["tau"])]
    for label, alpha, k, tau in named:
        full[f"train_{label}"] = _score_path(train_bits, favored_p, alpha, k, tau)
        full[f"test_{label}"] = _score_path(test_bits, favored_p, alpha, k, tau)

    payload = {
        "note": HONESTY,
        "interval": interval,
        "abstraction": (
            f"Up means close > open on a Binance BTCUSDT {interval} bar. "
            "The engine is paid even money on that bit. It is not paid the bitcoin return."
        ),
        "source": f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/{interval}/",
        "quantconnect_project": {
            "id": 37996630,
            "name": "groky_carlo",
            "state": "Cloud project is the empty Python starter. No dataset was purchased.",
        },
        "coverage": coverage,
        "first_open_ms": bars[0][0],
        "last_open_ms": bars[-1][0],
        "first_time": _iso(bars[0][0]),
        "last_time": _iso(bars[-1][0]),
        "first_open": bars[0][1],
        "last_close": bars[-1][2],
        "btc_return_full": bars[-1][2] / bars[0][1] - 1.0,
        "btc_return_2025": btc_replay._btc_return(train),
        "btc_return_2026": btc_replay._btc_return(test),
        "train_bars": len(train),
        "test_bars": len(test),
        "train_stub_bars": len(train) - btc_replay.WINDOW * len(train_w),
        "test_stub_bars": len(test) - btc_replay.WINDOW * len(test_w),
        "train_up_rate": p_hat,
        "train_up_rate_se": math.sqrt(p_hat * (1.0 - p_hat) / len(train)),
        "root_rule": (
            "p = 0.5 when the 2025 up rate is within 1 percentage point of one half, "
            "so the root opens both sides."
        ),
        "root": _root_label(favored_p),
        "test_up_rate": sum(test_bits) / len(test_bits),
        "favored_p_used": favored_p,
        "runs_train": btc_replay._runs(train_bits),
        "runs_test": btc_replay._runs(test_bits),
        "window": btc_replay.WINDOW,
        "window_rule": "500 decisive bars that start and end in the same calendar year.",
        "train_windows": len(train_w),
        "test_windows": len(test_w),
        "objective_mode": mode,
        "objective": objective,
        "grid_cells": len(cells),
        "best_train": best,
        "best_test": holdout,
        "baselines": baseline_rows,
        "full_paths": full,
        "train_top10": ranked[:10],
        "elapsed_sec": round(time.perf_counter() - started, 1),
    }
    btc_replay.RESULTS.mkdir(parents=True, exist_ok=True)
    out = btc_replay.RESULTS / f"btc_replay_{interval}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"  best a={best['alpha']} k={best['k']} tau={best['tau']} "
        f"elapsed {payload['elapsed_sec']}s -> {out.name}",
        flush=True,
    )
    return payload


def _compact(payload: dict) -> dict:
    scores = {}
    for label, alpha, k, tau in BASELINES:
        base = next(row for row in payload["baselines"] if row["label"] == label)
        train_key, test_key = PATH_KEYS[label]
        scores[label] = _compact_score(
            label,
            (alpha, k, tau),
            base["train"],
            base["test"],
            payload["full_paths"][train_key],
            payload["full_paths"][test_key],
        )
    scores["picked"] = _compact_score(
        "picked",
        (payload["best_train"]["alpha"], payload["best_train"]["k"], payload["best_train"]["tau"]),
        payload["best_train"] if payload["objective_mode"] == "windows" else None,
        payload["best_test"] if payload["objective_mode"] == "windows" else None,
        payload["full_paths"]["train_best"],
        payload["full_paths"]["test_best"],
    )
    return {
        "interval": payload["interval"],
        "objective_mode": payload["objective_mode"],
        "objective": payload["objective"],
        "first_time": payload["first_time"],
        "last_time": payload["last_time"],
        "first_open": payload["first_open"],
        "last_close": payload["last_close"],
        "bars": payload["coverage"]["bars"],
        "flat": payload["coverage"]["flat"],
        "decisive": payload["coverage"]["decisive"],
        "train_bars": payload["train_bars"],
        "test_bars": payload["test_bars"],
        "train_windows": payload["train_windows"],
        "test_windows": payload["test_windows"],
        "train_stub_bars": payload["train_stub_bars"],
        "test_stub_bars": payload["test_stub_bars"],
        "up_2025": payload["train_up_rate"],
        "up_2025_se": payload["train_up_rate_se"],
        "up_2026": payload["test_up_rate"],
        "favored_p": payload["favored_p_used"],
        "root": payload["root"],
        "btc_2025": payload["btc_return_2025"],
        "btc_2026": payload["btc_return_2026"],
        "btc_full": payload["btc_return_full"],
        "runs_2025": payload["runs_train"],
        "runs_2026": payload["runs_test"],
        "picked": {
            "alpha": payload["best_train"]["alpha"],
            "k": payload["best_train"]["k"],
            "tau": payload["best_train"]["tau"],
        },
        "scores": scores,
    }


def main(argv: list[str]) -> None:
    wanted = tuple(argv) or INTERVALS
    unknown = [name for name in wanted if name not in INTERVALS]
    if unknown:
        raise SystemExit(f"unknown interval: {', '.join(unknown)}")
    rows = []
    for interval in wanted:
        rows.append(_compact(run_interval(interval)))
    # Keep intervals that were not rerun in this process.
    comparison_path = btc_replay.RESULTS / "btc_timeframes.json"
    existing = {}
    if comparison_path.exists() and wanted != INTERVALS:
        prior = json.loads(comparison_path.read_text())
        existing = {row["interval"]: row for row in prior.get("rows", [])}
    for row in rows:
        existing[row["interval"]] = row
    ordered = [existing[name] for name in INTERVALS if name in existing]
    comparison = {
        "note": HONESTY,
        "abstraction": (
            "Up means close > open. The engine is paid even money on that bit. "
            "It is not paid the bitcoin return."
        ),
        "window": btc_replay.WINDOW,
        "intervals": [row["interval"] for row in ordered],
        "rows": ordered,
    }
    comparison_path.write_text(json.dumps(comparison, indent=2) + "\n")
    print(f"wrote {comparison_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
