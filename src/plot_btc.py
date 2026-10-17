"""Window score versus the continuous Bitcoin path.

Reads results/btc_replay.json. Requires matplotlib.

    python src/plot_btc.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "results" / "btc_replay.json"
OUT = ROOT / "results" / "figures" / "btc_windows_vs_path.png"

LABELS = ("Equal split", "Default", "No counter", "Late trigger", "Picked on 2025")


def _pair(payload: dict, train_key: str, test_key: str, field: str) -> tuple[float, float]:
    if train_key == "best":
        return payload["best_train"][field], payload["best_test"][field]
    train = next(row["train"] for row in payload["baselines"] if row["label"] == train_key)
    test = next(row["test"] for row in payload["baselines"] if row["label"] == train_key)
    return train[field], test[field]


def main() -> None:
    payload = json.loads(STUDY.read_text())
    window_keys = ("equal_split", "default", "no_counter", "late_trigger", "best")
    path_keys = (
        ("train_equal_split", "test_equal_split"),
        ("train_default", "test_default"),
        ("train_no_counter", "test_no_counter"),
        ("train_late_trigger", "test_late_trigger"),
        ("train_best", "test_best"),
    )
    window = [_pair(payload, key, key, "mean_log_growth") for key in window_keys]
    paths = [
        (payload["full_paths"][train]["log_growth"], payload["full_paths"][test]["log_growth"])
        for train, test in path_keys
    ]
    plt.rcParams.update({"font.size": 11, "figure.facecolor": "white", "axes.facecolor": "white"})
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.4), constrained_layout=True)
    import numpy as np
    x = np.arange(len(LABELS))
    width = 0.36
    for ax, series, title, ylabel in (
        (axes[0], window, "500-bar windows, capital reset", "Mean log-growth"),
        (axes[1], paths, "One continuous path per year", "Log-growth of that path"),
    ):
        ax.bar(x - width / 2, [row[0] for row in series], width, color="#0072b2", label="2025")
        ax.bar(x + width / 2, [row[1] for row in series], width, color="#d55e00", label="2026")
        ax.axhline(0, color="#9ca3af", linewidth=0.8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, axis="y", color="#e5e7eb")
        ax.set_axisbelow(True)
        ax.set_xticks(x, LABELS, rotation=15, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
    axes[0].legend(frameon=False)
    fig.suptitle("BTCUSDT 5-minute direction, even-money lab, root at p = 0.5", fontsize=12)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140)
    print(OUT)


if __name__ == "__main__":
    main()
