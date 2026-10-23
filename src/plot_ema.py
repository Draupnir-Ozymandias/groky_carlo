"""2025 versus 2026 log-growth for the EMA length search.

Reads results/ema_optimization.json. Requires matplotlib.

    python src/plot_ema.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "results" / "ema_optimization.json"
OUT = ROOT / "results" / "figures" / "ema_optimization.png"
NAMES = {"5m": "5-minute", "15m": "15-minute", "1h": "1-hour", "4h": "4-hour", "1d": "Daily"}


def _pair(row: dict, key: str, field: str) -> tuple[float, float]:
    block = row[key]
    return block[f"train_{field}"], block[f"test_{field}"]


def main() -> None:
    payload = json.loads(STUDY.read_text())
    rows = payload["rows"]
    plt.rcParams.update({"font.size": 10, "figure.facecolor": "white", "axes.facecolor": "white"})
    fig, axes = plt.subplots(len(rows), 1, figsize=(8.2, 2.05 * len(rows)), constrained_layout=True)
    width = 0.36
    for index, row in enumerate(rows):
        ax = axes[index]
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, axis="y", color="#e5e7eb")
        ax.set_axisbelow(True)
        name = NAMES.get(row["interval"], row["interval"])
        chosen = row["chosen"]
        if row["objective_mode"] == "windows":
            field = "window_log"
            title = f"{name} windows, n={row['train_windows']}/{row['test_windows']}"
            ylabel = "Mean log-growth"
        else:
            field = "path_log"
            title = f"{name} path, {row['train_bars']}/{row['test_bars']} bars"
            ylabel = "Log-growth"
        series = [
            _pair(row, "no_filter", field),
            _pair(row, "starting_pair", field),
            _pair(row, "chosen", field),
        ]
        labels = ["No filter", "5 / 10", f"{chosen['fast']} / {chosen['slow']}"]
        x = np.arange(len(labels))
        ax.bar(x - width / 2, [pair[0] for pair in series], width, color="#0072b2", label="2025")
        ax.bar(x + width / 2, [pair[1] for pair in series], width, color="#d55e00", label="2026")
        ax.axhline(0, color="#9ca3af", linewidth=0.8)
        ax.set_xticks(x, labels)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        if index == 0:
            ax.legend(frameon=False, loc="upper right")
    fig.suptitle(
        "BTCUSDT EMA lengths on the default book. Chosen on 2025. The third bar is the best filter in the grid.",
        fontsize=11,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140)
    print(OUT)


if __name__ == "__main__":
    main()
