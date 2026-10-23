"""Choose fast and slow EMA lengths on BTCUSDT, one search per timeframe.

The book is the default branching rule: alpha 0.70, k 2, tau 8, p 0.5.
2025 chooses the pair. 2026 is held out. A candidate is a fast length and a
longer slow length. The starting pair, 5 and 10, stays in the grid as a
reference. It is not forced to win.

Windows are 500 decisive bars that start and end inside one calendar year.
Daily 2025 has fewer than 500 bars, so that timeframe is ranked by the single
continuous 2025 path.

    python src/optimize_ema.py

Writes results/ema_optimization.json. Raw zips stay under data/.
"""

from __future__ import annotations

import json
import math
import sys
import time

import btc_replay
from ema import DEFAULT_FAST_LENGTH, DEFAULT_SLOW_LENGTH, dominant_bias
from simulate import HONESTY, LabParams, run_branching

INTERVALS = ("5m", "15m", "1h", "4h", "1d")
BAR_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
# Lengths are the search space, not the EMA update. Fast must stay shorter than slow.
FAST_LENGTHS = (2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30)
SLOW_LENGTHS = (8, 10, 12, 15, 20, 26, 30, 40, 50, 60, 80, 100, 150, 200)
ALPHA = 0.70
K = 2
TAU = 8.0
P = 0.5
# Previously chosen on 2025 windows with no trend filter. Reported, not re-fit.
PICKED_BOOK = {
    "5m": (0.90, 8, 127.0),
    "15m": (0.90, 8, 127.0),
    "1h": (0.80, 1, 127.0),
    "4h": (0.80, 4, 15.0),
    "1d": (0.80, 1, 8.0),
}


def pairs() -> list[tuple[int, int]]:
    return [(fast, slow) for fast in FAST_LENGTHS for slow in SLOW_LENGTHS if fast < slow]


def _params(alpha: float, k: int, tau: float) -> LabParams:
    return LabParams(
        capital=btc_replay.CAPITAL,
        base=btc_replay.BASE,
        p=P,
        alpha=alpha,
        k=k,
        tau=tau,
        d_max=6,
        risk_cap=0.25,
    )


def _windows(rows: list[dict], year: int) -> list[dict]:
    year_rows = [row for row in rows if btc_replay._utc_year(row["t"]) == year]
    cuts = []
    width = btc_replay.WINDOW
    for start in range(0, len(year_rows) - width + 1, width):
        chunk = year_rows[start : start + width]
        cuts.append(
            {
                "year": year,
                "outcomes": [row["up"] for row in chunk],
                "bias": [row["bias"] for row in chunk],
            }
        )
    return cuts


def _score_windows(windows: list[dict], alpha: float, k: int, tau: float) -> dict | None:
    if not windows:
        return None
    params = _params(alpha, k, tau)
    terminals = []
    drawdowns = []
    logs = []
    ruined = 0
    above = 0
    for window in windows:
        result = run_branching(window["outcomes"], params, keep_trace=False, bias=window["bias"])
        terminals.append(result.terminal)
        drawdowns.append(result.max_drawdown)
        logs.append(btc_replay._log_growth(result.terminal, result.ruined))
        ruined += int(result.ruined)
        above += int(result.terminal > btc_replay.CAPITAL)
    n = len(windows)
    return {
        "windows": n,
        "mean_log_growth": sum(logs) / n,
        "median_terminal": btc_replay.metrics.median(terminals),
        "mean_terminal": sum(terminals) / n,
        "frac_above_start": above / n,
        "median_max_drawdown": btc_replay.metrics.median(drawdowns),
        "p95_max_drawdown": btc_replay.metrics.nearest_rank(drawdowns, 0.95),
        "ruin_rate": ruined / n,
    }


def _score_path(rows: list[dict], alpha: float, k: int, tau: float, with_debts: bool) -> dict:
    params = _params(alpha, k, tau)
    outcomes = [row["up"] for row in rows]
    bias = [row["bias"] for row in rows]
    result = run_branching(outcomes, params, keep_trace=with_debts, bias=bias)
    scored = {
        "steps": result.steps,
        "terminal": result.terminal,
        "ruined": result.ruined,
        "max_drawdown": result.max_drawdown,
        "max_depth": result.max_depth,
        "log_growth": btc_replay._log_growth(result.terminal, result.ruined),
    }
    if with_debts:
        last = result.trace[-1]
        scored["end_long_debt"] = last["long_debt"]
        scored["end_short_debt"] = last["short_debt"]
    return scored


def _separation(rows: list[dict]) -> dict:
    long_n = short_n = unread = long_up = short_up = 0
    for row in rows:
        side = row["bias"]
        if side is None:
            unread += 1
        elif side == 1:
            long_n += 1
            long_up += row["up"]
        else:
            short_n += 1
            short_up += row["up"]
    return {
        "bars": len(rows),
        "unread": unread,
        "long_bars": long_n,
        "short_bars": short_n,
        "up_when_long": None if long_n == 0 else long_up / long_n,
        "up_when_short": None if short_n == 0 else short_up / short_n,
    }


def _attach(rows: list[dict], closes: list[float], fast: int, slow: int) -> None:
    bias = dominant_bias(closes, fast, slow)
    for row, side in zip(rows, bias):
        row["bias"] = side


def _clear_bias(rows: list[dict]) -> None:
    for row in rows:
        row["bias"] = None


def _record(
    fast: int | None,
    slow: int | None,
    train_rows: list[dict],
    test_rows: list[dict],
    train_w: list[dict],
    test_w: list[dict],
    alpha: float,
    k: int,
    tau: float,
    with_debts: bool,
) -> dict:
    train_sep = _separation(train_rows)
    test_sep = _separation(test_rows)
    train_window = _score_windows(train_w, alpha, k, tau)
    test_window = _score_windows(test_w, alpha, k, tau)
    train_path = _score_path(train_rows, alpha, k, tau, with_debts)
    test_path = _score_path(test_rows, alpha, k, tau, with_debts)
    return {
        "fast": fast,
        "slow": slow,
        "alpha": alpha,
        "k": k,
        "tau": tau,
        "train_reads": train_sep,
        "test_reads": test_sep,
        "train_window": train_window,
        "test_window": test_window,
        "train_path": train_path,
        "test_path": test_path,
    }


def _rank_key(row: dict, mode: str) -> tuple[float, float]:
    if mode == "windows":
        window = row["train_window"]
        return (window["mean_log_growth"], -window["median_max_drawdown"])
    path = row["train_path"]
    return (path["log_growth"], -path["max_drawdown"])


def _compact(row: dict) -> dict:
    train_w = row["train_window"]
    test_w = row["test_window"]
    return {
        "fast": row["fast"],
        "slow": row["slow"],
        "train_unread": row["train_reads"]["unread"],
        "test_unread": row["test_reads"]["unread"],
        "train_long_bars": row["train_reads"]["long_bars"],
        "train_short_bars": row["train_reads"]["short_bars"],
        "train_up_when_long": row["train_reads"]["up_when_long"],
        "train_up_when_short": row["train_reads"]["up_when_short"],
        "test_up_when_long": row["test_reads"]["up_when_long"],
        "test_up_when_short": row["test_reads"]["up_when_short"],
        "train_window_log": None if train_w is None else train_w["mean_log_growth"],
        "test_window_log": None if test_w is None else test_w["mean_log_growth"],
        "train_window_terminal": None if train_w is None else train_w["median_terminal"],
        "test_window_terminal": None if test_w is None else test_w["median_terminal"],
        "train_window_mean_terminal": None if train_w is None else train_w["mean_terminal"],
        "test_window_mean_terminal": None if test_w is None else test_w["mean_terminal"],
        "train_window_p95dd": None if train_w is None else train_w["p95_max_drawdown"],
        "test_window_p95dd": None if test_w is None else test_w["p95_max_drawdown"],
        "train_window_median_dd": None if train_w is None else train_w["median_max_drawdown"],
        "test_window_median_dd": None if test_w is None else test_w["median_max_drawdown"],
        "train_window_ruin": None if train_w is None else train_w["ruin_rate"],
        "test_window_ruin": None if test_w is None else test_w["ruin_rate"],
        "train_window_above": None if train_w is None else train_w["frac_above_start"],
        "test_window_above": None if test_w is None else test_w["frac_above_start"],
        "train_path_log": row["train_path"]["log_growth"],
        "test_path_log": row["test_path"]["log_growth"],
        "train_path_cash": row["train_path"]["terminal"],
        "test_path_cash": row["test_path"]["terminal"],
        "train_path_dd": row["train_path"]["max_drawdown"],
        "test_path_dd": row["test_path"]["max_drawdown"],
        "train_path_ruined": row["train_path"]["ruined"],
        "test_path_ruined": row["test_path"]["ruined"],
        "train_debt_long": row["train_path"].get("end_long_debt"),
        "train_debt_short": row["train_path"].get("end_short_debt"),
        "test_debt_long": row["test_path"].get("end_long_debt"),
        "test_debt_short": row["test_path"].get("end_short_debt"),
    }


def run_interval(interval: str, grid: list[tuple[int, int]]) -> dict:
    started = time.perf_counter()
    print(f"=== {interval} ===", flush=True)
    btc_replay._download(interval)
    bars = btc_replay._bars(interval)
    if not bars:
        raise SystemExit(f"no bars for {interval}")
    decisive, coverage = btc_replay._directions(bars)
    closes = [row["close"] for row in decisive]
    train_rows = [row for row in decisive if btc_replay._utc_year(row["t"]) == 2025]
    test_rows = [row for row in decisive if btc_replay._utc_year(row["t"]) == 2026]
    if not train_rows or not test_rows:
        raise SystemExit(f"{interval}: need both years")

    _clear_bias(decisive)
    # Windows are cut after the bias is attached, so each slice keeps the
    # crossover computed on the whole tape, not a fresh average per window.
    bare_train_w = _windows(decisive, 2025)
    bare_test_w = _windows(decisive, 2026)
    mode = "windows" if bare_train_w else "continuous_path"
    print(
        f"  decisive {coverage['decisive']} windows {len(bare_train_w)}/{len(bare_test_w)} "
        f"mode {mode} pairs {len(grid)}",
        flush=True,
    )

    ranked = []
    for index, (fast, slow) in enumerate(grid, start=1):
        _attach(decisive, closes, fast, slow)
        train_w = _windows(decisive, 2025)
        test_w = _windows(decisive, 2026)
        ranked.append(
            _record(fast, slow, train_rows, test_rows, train_w, test_w, ALPHA, K, TAU, with_debts=False)
        )
        if index % 25 == 0 or index == len(grid):
            print(f"  {interval} pair {index}/{len(grid)}", flush=True)
    ranked.sort(key=lambda row: _rank_key(row, mode), reverse=True)
    best = ranked[0]

    _clear_bias(decisive)
    none_row = _record(None, None, train_rows, test_rows, _windows(decisive, 2025), _windows(decisive, 2026), ALPHA, K, TAU, True)
    _attach(decisive, closes, DEFAULT_FAST_LENGTH, DEFAULT_SLOW_LENGTH)
    start_row = _record(
        DEFAULT_FAST_LENGTH,
        DEFAULT_SLOW_LENGTH,
        train_rows,
        test_rows,
        _windows(decisive, 2025),
        _windows(decisive, 2026),
        ALPHA,
        K,
        TAU,
        True,
    )
    _attach(decisive, closes, best["fast"], best["slow"])
    chosen_row = _record(
        best["fast"],
        best["slow"],
        train_rows,
        test_rows,
        _windows(decisive, 2025),
        _windows(decisive, 2026),
        ALPHA,
        K,
        TAU,
        True,
    )

    picked_alpha, picked_k, picked_tau = PICKED_BOOK[interval]
    picked = {}
    for label, fast, slow in (
        ("no_filter", None, None),
        ("starting_pair", DEFAULT_FAST_LENGTH, DEFAULT_SLOW_LENGTH),
        ("chosen_on_default_book", best["fast"], best["slow"]),
    ):
        if fast is None:
            _clear_bias(decisive)
        else:
            _attach(decisive, closes, fast, slow)
        picked[label] = _compact(
            _record(
                fast,
                slow,
                train_rows,
                test_rows,
                _windows(decisive, 2025),
                _windows(decisive, 2026),
                picked_alpha,
                picked_k,
                picked_tau,
                True,
            )
        )

    p_hat = sum(row["up"] for row in train_rows) / len(train_rows)
    objective = (
        "Maximize mean log-growth of 500-bar windows that start and end inside 2025. "
        "2026 is not used to choose."
        if mode == "windows"
        else (
            "2025 has fewer than 500 decisive bars, so the grid is ranked by log-growth "
            "of the single continuous 2025 path. That ranking is one path, not a sample. "
            "2026 is not used to choose."
        )
    )
    payload = {
        "interval": interval,
        "bar_minutes": BAR_MINUTES[interval],
        "objective_mode": mode,
        "objective": objective,
        "book": {"alpha": ALPHA, "k": K, "tau": TAU, "p": P},
        "picked_book_parameters": {"alpha": picked_alpha, "k": picked_k, "tau": picked_tau},
        "coverage": coverage,
        "first_open": bars[0][1],
        "last_close": bars[-1][2],
        "btc_2025": btc_replay._btc_return(train_rows),
        "btc_2026": btc_replay._btc_return(test_rows),
        "train_bars": len(train_rows),
        "test_bars": len(test_rows),
        "train_windows": len(bare_train_w),
        "test_windows": len(bare_test_w),
        "train_up_rate": p_hat,
        "train_up_rate_se": math.sqrt(p_hat * (1.0 - p_hat) / len(train_rows)),
        "test_up_rate": sum(row["up"] for row in test_rows) / len(test_rows),
        "grid_pairs": len(grid),
        "chosen": _compact(chosen_row),
        "no_filter": _compact(none_row),
        "starting_pair": _compact(start_row),
        "picked_book": picked,
        "train_top10": [_compact(row) for row in ranked[:10]],
        "grid": [
            {
                "fast": row["fast"],
                "slow": row["slow"],
                "train_window_log": None if row["train_window"] is None else row["train_window"]["mean_log_growth"],
                "test_window_log": None if row["test_window"] is None else row["test_window"]["mean_log_growth"],
                "train_path_log": row["train_path"]["log_growth"],
                "test_path_log": row["test_path"]["log_growth"],
                "train_up_when_long": row["train_reads"]["up_when_long"],
                "train_up_when_short": row["train_reads"]["up_when_short"],
                "train_long_bars": row["train_reads"]["long_bars"],
                "train_short_bars": row["train_reads"]["short_bars"],
            }
            for row in ranked
        ],
        "elapsed_sec": round(time.perf_counter() - started, 1),
    }
    out = btc_replay.RESULTS / f"ema_opt_{interval}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    chosen = payload["chosen"]
    print(
        f"  chosen fast={chosen['fast']} slow={chosen['slow']} "
        f"elapsed {payload['elapsed_sec']}s -> {out.name}",
        flush=True,
    )
    return payload


def main(argv: list[str]) -> None:
    wanted = tuple(argv) or INTERVALS
    unknown = [name for name in wanted if name not in INTERVALS]
    if unknown:
        raise SystemExit(f"unknown interval: {', '.join(unknown)}")
    grid = pairs()
    rows = [run_interval(interval, grid) for interval in wanted]
    comparison_path = btc_replay.RESULTS / "ema_optimization.json"
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
            "The EMA chooses the dominant side of the fresh stake and of the alpha leg. "
            "It is not paid the bitcoin return."
        ),
        "fast_lengths": list(FAST_LENGTHS),
        "slow_lengths": list(SLOW_LENGTHS),
        "pairs": len(grid),
        "book": {"alpha": ALPHA, "k": K, "tau": TAU, "p": P},
        "starting_pair": {"fast": DEFAULT_FAST_LENGTH, "slow": DEFAULT_SLOW_LENGTH},
        "intervals": [row["interval"] for row in ordered],
        "rows": ordered,
    }
    comparison_path.write_text(json.dumps(comparison, indent=2) + "\n")
    print(f"wrote {comparison_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
