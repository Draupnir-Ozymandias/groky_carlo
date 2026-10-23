"""Flat unit profit and half-Kelly cash for the streak fade.

Reads nothing from disk except the Binance zips. Requires matplotlib.

    python src/plot_streak_kelly.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import btc_replay
from streak_kelly import KELLY_SCALE, MIN_TRIALS, fade_table, run_streak_kelly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "figures" / "streak_kelly.png"
INTERVALS = ("5m", "15m", "1h", "4h")
COLORS = {"5m": "#0072b2", "15m": "#d55e00", "1h": "#009e73", "4h": "#cc79a7"}
NAMES = {"5m": "5-minute", "15m": "15-minute", "1h": "1-hour", "4h": "4-hour"}


def _paths(interval: str) -> tuple[list[float], list[float]]:
    btc_replay._download(interval)
    bars = btc_replay._bars(interval)
    decisive, _ = btc_replay._directions(bars)
    train = [row["up"] for row in decisive if btc_replay._utc_year(row["t"]) == 2025]
    full = [row["up"] for row in decisive]
    table = fade_table(train)
    kelly = run_streak_kelly(full, table, score_from=len(train), keep_equity=True)
    flat = run_streak_kelly(
        full,
        table,
        score_from=len(train),
        flat_stake=btc_replay.BASE,
        keep_equity=True,
    )
    return flat["equity"], kelly["equity"]


def main() -> None:
    plt.rcParams.update({"font.size": 10, "figure.facecolor": "white", "axes.facecolor": "white"})
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.4), constrained_layout=True)
    for interval in INTERVALS:
        flat, kelly = _paths(interval)
        color = COLORS[interval]
        name = NAMES[interval]
        x = np.linspace(0.0, 1.0, len(flat))
        axes[0].plot(x, [cash - btc_replay.CAPITAL for cash in flat], color=color, linewidth=1.1, label=name)
        axes[1].plot(x, kelly, color=color, linewidth=1.1, label=name)
    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, axis="y", color="#e5e7eb")
        ax.set_axisbelow(True)
        ax.set_xlabel("Share of 2026 bars")
    fig.legend(
        axes[1].lines,
        [line.get_label() for line in axes[1].lines],
        frameon=False,
        ncol=4,
        loc="outside lower center",
    )
    axes[0].axhline(0, color="#9ca3af", linewidth=0.8)
    axes[0].set_ylabel("Cumulative even-money profit")
    axes[0].set_title("Flat stake of 1 on each signal")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("Cash")
    axes[1].set_title(f"Half-Kelly, scale {KELLY_SCALE:g}")
    fig.suptitle(
        f"2026 BTCUSDT direction fade. Probabilities frozen on 2025. Lengths under {MIN_TRIALS} trials are passed.",
        fontsize=11,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140)
    print(OUT)


if __name__ == "__main__":
    main()
