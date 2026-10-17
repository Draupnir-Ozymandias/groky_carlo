"""Replay the branching rule on Binance BTCUSDT 5-minute bars.

Each decisive bar is one even-money outcome: up when close > open, down when
close < open. Flat bars are dropped. The lab still pays even money on that
direction. It does not earn the bar's dollar move.

2025 windows choose the settings. 2026 windows are the holdout. A window is
500 decisive bars, the lab horizon.

    python src/btc_replay.py

Writes results/btc_replay.json. Raw zips stay in data/btcusdt_5m/.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import metrics
from simulate import HONESTY, LabParams, run_branching

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
WINDOW = 500
CAPITAL = 1000.0
BASE = 1.0
LOG_FLOOR = 1.0
ALPHAS = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
KS = (1, 2, 3, 4, 6, 8)
TAUS = (8.0, 15.0, 31.0, 63.0, 127.0)
MONTHS = [(year, month) for year in (2025, 2026) for month in range(1, 13) if date(year, month, 1) <= date(2026, 10, 1)]


def _raw(interval: str) -> Path:
    return ROOT / "data" / f"btcusdt_{interval}"


def _download(interval: str = "5m") -> None:
    raw = _raw(interval)
    raw.mkdir(parents=True, exist_ok=True)
    for year, month in MONTHS:
        name = f"BTCUSDT-{interval}-{year}-{month:02d}.zip"
        dest = raw / name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/{interval}/{name}"
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"downloaded {name}")
        except urllib.error.HTTPError as exc:
            if dest.exists():
                dest.unlink()
            print(f"skip {name}: HTTP {exc.code}")


def _bars(interval: str = "5m") -> list[tuple[int, float, float]]:
    rows: list[tuple[int, float, float]] = []
    for year, month in MONTHS:
        path = _raw(interval) / f"BTCUSDT-{interval}-{year}-{month:02d}.zip"
        if not path.exists():
            continue
        with zipfile.ZipFile(path) as archive:
            inner = [info for info in archive.infolist() if info.filename.endswith(".csv")]
            if len(inner) != 1:
                raise RuntimeError(f"{path.name} has {len(inner)} csv files")
            text = io.TextIOWrapper(archive.open(inner[0]), encoding="utf-8")
            for record in csv.reader(text):
                if not record or record[0] == "open_time":
                    continue
                opened = int(record[0])
                # Binance vision switched these files to microseconds.
                if opened > 10**14:
                    opened //= 1000
                open_px = float(record[1])
                close_px = float(record[4])
                rows.append((opened, open_px, close_px))
    rows.sort()
    # Binance monthly files can repeat the boundary bar.
    deduped: list[tuple[int, float, float]] = []
    seen: set[int] = set()
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        deduped.append(row)
    return deduped


def _directions(bars: list[tuple[int, float, float]]) -> tuple[list[dict], dict]:
    decisive = []
    flat = 0
    for opened, open_px, close_px in bars:
        if close_px > open_px:
            decisive.append({"t": opened, "up": 1, "open": open_px, "close": close_px})
        elif close_px < open_px:
            decisive.append({"t": opened, "up": 0, "open": open_px, "close": close_px})
        else:
            flat += 1
    ups = sum(row["up"] for row in decisive)
    return decisive, {"bars": len(bars), "flat": flat, "decisive": len(decisive), "up_rate": ups / len(decisive)}


def _runs(bits: list[int]) -> dict:
    """Streak lengths of the same outcome, and lag-1 agreement."""
    if not bits:
        raise ValueError("empty direction series")
    lengths = []
    current = 1
    agree = 0
    for prev, bit in zip(bits, bits[1:]):
        agree += int(prev == bit)
        if bit == prev:
            current += 1
        else:
            lengths.append(current)
            current = 1
    lengths.append(current)
    n = len(bits)
    up = sum(bits) / n
    # Geometric P(L >= m) for a fair comparison with independent draws at this up rate,
    # using the favored side's loss probability. Favored is up when up >= 0.5.
    loss_p = 1.0 - up if up >= 0.5 else up
    return {
        "lag1_same": agree / (n - 1),
        "independent_lag1_same": up * up + (1.0 - up) * (1.0 - up),
        "median_run": metrics.median(lengths),
        "p95_run": metrics.nearest_rank(lengths, 0.95),
        "max_run": max(lengths),
        "loss_p_if_betting_majority": loss_p,
    }


def _log_growth(terminal: float, ruined: bool) -> float:
    wealth = LOG_FLOOR if ruined or terminal <= 0.0 else terminal
    return math.log(wealth / CAPITAL)


def _window_from(chunk: list[dict], year: int) -> dict:
    return {
        "t0": chunk[0]["t"],
        "t1": chunk[-1]["t"],
        "year": year,
        "outcomes": [row["up"] for row in chunk],
    }


def _windows(rows: list[dict]) -> list[dict]:
    """500-bar blocks along the whole series. A block is labeled by its first bar."""
    cuts = []
    for start in range(0, len(rows) - WINDOW + 1, WINDOW):
        chunk = rows[start : start + WINDOW]
        cuts.append(_window_from(chunk, _utc_year(chunk[0]["t"])))
    return cuts


def _windows_inside_year(rows: list[dict], year: int) -> list[dict]:
    """500-bar blocks that start and end in the same calendar year."""
    year_rows = [row for row in rows if _utc_year(row["t"]) == year]
    cuts = []
    for start in range(0, len(year_rows) - WINDOW + 1, WINDOW):
        cuts.append(_window_from(year_rows[start : start + WINDOW], year))
    return cuts


def _utc_year(millis: int) -> int:
    return dt.datetime.fromtimestamp(millis / 1000, dt.timezone.utc).year


def _eval(windows: list[dict], p: float, alpha: float, k: int, tau: float) -> dict:
    params = LabParams(
        capital=CAPITAL,
        base=BASE,
        p=p,
        alpha=alpha,
        k=k,
        tau=tau,
        d_max=6,
        risk_cap=0.25,
    )
    terminals = []
    drawdowns = []
    depths = []
    logs = []
    ruined = 0
    above = 0
    for window in windows:
        result = run_branching(window["outcomes"], params, keep_trace=False)
        terminals.append(result.terminal)
        drawdowns.append(result.max_drawdown)
        depths.append(result.max_depth)
        logs.append(_log_growth(result.terminal, result.ruined))
        ruined += int(result.ruined)
        above += int(result.terminal > CAPITAL)
    n = len(windows)
    return {
        "windows": n,
        "alpha": alpha,
        "k": k,
        "tau": tau,
        "p": p,
        "ruin_rate": ruined / n,
        "mean_log_growth": sum(logs) / n,
        "median_terminal": metrics.median(terminals),
        "mean_terminal": sum(terminals) / n,
        "frac_above_start": above / n,
        "median_max_drawdown": metrics.median(drawdowns),
        "p95_max_drawdown": metrics.nearest_rank(drawdowns, 0.95),
        "median_max_depth": metrics.median(depths),
    }


def _one_path(outcomes: list[int], p: float, alpha: float, k: int, tau: float) -> dict:
    params = LabParams(capital=CAPITAL, base=BASE, p=p, alpha=alpha, k=k, tau=tau, d_max=6, risk_cap=0.25)
    result = run_branching(outcomes, params, keep_trace=True)
    last = result.trace[-1]
    return {
        "steps": result.steps,
        "terminal": result.terminal,
        "ruined": result.ruined,
        "max_drawdown": result.max_drawdown,
        "max_depth": result.max_depth,
        "resets": result.resets,
        "log_growth": _log_growth(result.terminal, result.ruined),
        "end_long_debt": last["long_debt"],
        "end_short_debt": last["short_debt"],
        "end_cash": last["cash"],
    }


def _btc_return(rows: list[dict]) -> float:
    return rows[-1]["close"] / rows[0]["open"] - 1.0


def main() -> None:
    _download()
    bars = _bars()
    if not bars:
        raise SystemExit(f"no bars in {_raw('5m')}")
    decisive, coverage = _directions(bars)
    bits = [row["up"] for row in decisive]
    train = [row for row in decisive if _utc_year(row["t"]) == 2025]
    test = [row for row in decisive if _utc_year(row["t"]) == 2026]
    if not train or not test:
        raise SystemExit(f"need both years, got train {len(train)} test {len(test)}")
    p_hat = sum(row["up"] for row in train) / len(train)
    # A 5-minute close-versus-open bit this close to 1/2 is a coin flip.
    # The root opens both sides unless the 2025 up rate clears 1 percentage point.
    favored_p = p_hat if abs(p_hat - 0.5) >= 0.01 else 0.5

    windows = _windows(decisive)
    train_w = [window for window in windows if window["year"] == 2025]
    test_w = [window for window in windows if window["year"] == 2026]
    grid = []
    for alpha in ALPHAS:
        for k in KS:
            for tau in TAUS:
                # alpha 1 ignores the split. One (k, tau) cell is enough.
                if alpha == 1.0 and (k != 2 or tau != 8.0):
                    continue
                grid.append(_eval(train_w, favored_p, alpha, k, tau))
    ranked = sorted(grid, key=lambda row: (row["mean_log_growth"], -row["median_max_drawdown"]), reverse=True)
    best = ranked[0]
    holdout = _eval(test_w, favored_p, best["alpha"], best["k"], best["tau"])
    baselines = []
    for label, alpha, k, tau in (
        ("default", 0.70, 2, 8.0),
        ("equal_split", 0.50, 2, 8.0),
        ("no_counter", 1.00, 2, 8.0),
        ("late_trigger", 0.70, 8, 127.0),
    ):
        baselines.append(
            {
                "label": label,
                "train": _eval(train_w, favored_p, alpha, k, tau),
                "test": _eval(test_w, favored_p, alpha, k, tau),
            }
        )
    full = {
        "train_default": _one_path([row["up"] for row in train], favored_p, 0.70, 2, 8.0),
        "test_default": _one_path([row["up"] for row in test], favored_p, 0.70, 2, 8.0),
        "train_best": _one_path([row["up"] for row in train], favored_p, best["alpha"], best["k"], best["tau"]),
        "test_best": _one_path([row["up"] for row in test], favored_p, best["alpha"], best["k"], best["tau"]),
        "train_no_counter": _one_path([row["up"] for row in train], favored_p, 1.0, 2, 8.0),
        "test_no_counter": _one_path([row["up"] for row in test], favored_p, 1.0, 2, 8.0),
        "train_equal_split": _one_path([row["up"] for row in train], favored_p, 0.5, 2, 8.0),
        "test_equal_split": _one_path([row["up"] for row in test], favored_p, 0.5, 2, 8.0),
        "train_late_trigger": _one_path([row["up"] for row in train], favored_p, 0.70, 8, 127.0),
        "test_late_trigger": _one_path([row["up"] for row in test], favored_p, 0.70, 8, 127.0),
    }
    payload = {
        "note": HONESTY,
        "abstraction": (
            "Up means close > open on a Binance BTCUSDT 5-minute bar. "
            "The engine is paid even money on that bit. It is not paid the bitcoin return."
        ),
        "source": "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/5m/",
        "quantconnect_project": {
            "id": 37996630,
            "name": "groky_carlo",
            "state": "Cloud project is the empty Python starter. No dataset was purchased.",
        },
        "coverage": coverage,
        "first_open_ms": bars[0][0],
        "last_open_ms": bars[-1][0],
        "first_open": bars[0][1],
        "last_close": bars[-1][2],
        "btc_return_full": _btc_return([{"open": bars[0][1], "close": bars[-1][2]}]),
        "btc_return_2025": _btc_return(train),
        "btc_return_2026": _btc_return(test),
        "train_up_rate": p_hat,
        "train_up_rate_se": math.sqrt(p_hat * (1.0 - p_hat) / len(train)),
        "root_rule": "p = 0.5 when the 2025 up rate is within 1 percentage point of one half, so the root opens both sides.",
        "test_up_rate": sum(row["up"] for row in test) / len(test),
        "favored_p_used": favored_p,
        "runs_train": _runs([row["up"] for row in train]),
        "runs_test": _runs([row["up"] for row in test]),
        "window": WINDOW,
        "train_windows": len(train_w),
        "test_windows": len(test_w),
        "objective": "Maximize mean log-growth of 2025 windows. 2026 is not used to choose.",
        "best_train": best,
        "best_test": holdout,
        "baselines": baselines,
        "full_paths": full,
        "train_top10": ranked[:10],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "btc_replay.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"bars {coverage['bars']} decisive {coverage['decisive']} flat {coverage['flat']}")
    print(f"train up {p_hat:.4f} test up {payload['test_up_rate']:.4f} favored_p {favored_p:.4f}")
    print(f"btc 2025 {payload['btc_return_2025']:.3%} 2026 {payload['btc_return_2026']:.3%}")
    print(f"windows train {len(train_w)} test {len(test_w)}")
    print(
        f"best a={best['alpha']} k={best['k']} tau={best['tau']} "
        f"train_log={best['mean_log_growth']:.4f} test_log={holdout['mean_log_growth']:.4f} "
        f"train_ruin={best['ruin_rate']:.3f} test_ruin={holdout['ruin_rate']:.3f}"
    )
    for row in baselines:
        print(
            f"{row['label']}: train_log={row['train']['mean_log_growth']:.4f} "
            f"test_log={row['test']['mean_log_growth']:.4f} "
            f"train_term={row['train']['median_terminal']:.1f} test_term={row['test']['median_terminal']:.1f}"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
