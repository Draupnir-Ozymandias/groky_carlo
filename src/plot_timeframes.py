"""Window score versus the continuous path, for 15m, 1h, 4h, and 1d.

Reads results/btc_timeframes.json. Requires matplotlib.

    python src/plot_timeframes.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "results" / "btc_timeframes.json"
OUT = ROOT / "results" / "figures" / "btc_timeframes.png"

LABELS = ("Equal split", "Default", "No counter", "Late trigger", "Picked on 2025")
KEYS = ("equal_split", "default", "no_counter", "late_trigger", "picked")
NAMES = {"15m": "15-minute", "1h": "1-hour", "4h": "4-hour", "1d": "Daily"}


def _series(row: dict, prefix: str) -> list[tuple[float, float]] | None:
    if prefix == "window" and row["objective_mode"] != "windows":
        return None
    scores = row["scores"]
    return [(scores[key][f"{prefix}_log_2025"], scores[key][f"{prefix}_log_2026"]) for key in KEYS]


def main() -> None:
    payload = json.loads(STUDY.read_text())
    rows = payload["rows"]
    plt.rcParams.update({"font.size": 10, "figure.facecolor": "white", "axes.facecolor": "white"})
    fig, axes = plt.subplots(len(rows), 2, figsize=(10.6, 2.35 * len(rows)), constrained_layout=True)
    x = np.arange(len(LABELS))
    width = 0.36
    for index, row in enumerate(rows):
        name = NAMES.get(row["interval"], row["interval"])
        panels = (
            (_series(row, "window"), f"{name} windows", "Mean log-growth"),
            (_series(row, "path"), f"{name} continuous path", "Log-growth"),
        )
        for column, (series, title, ylabel) in enumerate(panels):
            ax = axes[index, column]
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            if series is None:
                ax.set_xticks([])
                ax.set_yticks([])
                for spine in ax.spines.values():
                    spine.set_visible(False)
                ax.set_ylabel("")
                ax.text(
                    0.5,
                    0.5,
                    f"{name}: 2025 has no 500-bar window\n({row['train_bars']} decisive bars)",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                    color="#374151",
                )
                ax.set_title(title)
                continue
            ax.grid(True, axis="y", color="#e5e7eb")
            ax.set_axisbelow(True)
            ax.bar(x - width / 2, [pair[0] for pair in series], width, color="#0072b2", label="2025")
            ax.bar(x + width / 2, [pair[1] for pair in series], width, color="#d55e00", label="2026")
            ax.axhline(0, color="#9ca3af", linewidth=0.8)
            ax.set_xticks(x, LABELS, rotation=15, ha="right")
            ax.set_ylabel(ylabel)
            suffix = f", n={row['train_windows']}/{row['test_windows']}" if column == 0 else ""
            ax.set_title(f"{title}{suffix}")
            if index == 0 and column == 0:
                ax.legend(frameon=False)
    fig.suptitle("BTCUSDT direction, even-money lab. Settings chosen on 2025 only.", fontsize=12)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140)
    print(OUT)


if __name__ == "__main__":
    main()
