"""Figures for the branching regime study.

Reads results/branching_study.json and writes PNG files under results/figures/.
Requires matplotlib:

    python3 -m venv .venv
    .venv/bin/pip install matplotlib
    .venv/bin/python src/plot_branching.py

Run src/study_branching.py first if the JSON is missing.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import matplotlib.pyplot as plt

from simulate import LabParams, run_branching

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
STUDY = RESULTS / "branching_study.json"

P_COLORS = {
    0.50: "#4d4d4d",
    0.55: "#0072b2",
    0.60: "#009e73",
    0.65: "#d55e00",
}
P_SHOW = (0.50, 0.55, 0.60, 0.65)
# tau values whose first fire is after 1..7 unsplit losses. See branching_regimes.md.
TAU_TO_M = {1.0: 1, 3.0: 2, 7.0: 3, 15.0: 4, 31.0: 5, 63.0: 6, 127.0: 7}


def _style() -> None:
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "legend.fontsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#374151",
            "axes.labelcolor": "#111827",
            "xtick.color": "#111827",
            "ytick.color": "#111827",
            "text.color": "#111827",
        }
    )


def _panel(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="y", color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)


def _rows(data: dict, name: str, **match) -> list[dict]:
    found = []
    for row in data[name]:
        if all(abs(row[key] - value) < 1e-9 if isinstance(value, float) else row[key] == value for key, value in match.items()):
            found.append(row)
    return found


def _alpha_figure(data: dict) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10.2, 7.4), constrained_layout=True)
    specs = (
        (axes[0, 0], "mean_log_growth", "Mean log-growth", None),
        (axes[0, 1], "median_terminal", "Median terminal cash", 1000.0),
        (axes[1, 0], "debt_frac", "Share of steps in debt", None),
        (axes[1, 1], "p95_max_drawdown", "95th percentile max drawdown", None),
    )
    for p in P_SHOW:
        rows = sorted(_rows(data, "alpha_by_p", p=p), key=lambda row: row["alpha"])
        xs = [row["alpha"] for row in rows]
        for ax, key, ylabel, href in specs:
            ax.plot(
                xs,
                [row[key] for row in rows],
                color=P_COLORS[p],
                marker="o",
                markersize=4.5,
                linewidth=1.8,
                label=f"p = {p:.2f}",
            )
    for ax, _key, ylabel, href in specs:
        _panel(ax)
        ax.axvline(0.70, color="#9ca3af", linewidth=0.9, linestyle="--")
        ax.set_xlabel("Split ratio  α")
        ax.set_ylabel(ylabel)
        ax.set_xticks([0.50, 0.60, 0.70, 0.80, 0.90, 1.00])
        if href is not None:
            ax.axhline(href, color="#9ca3af", linewidth=0.8)
    axes[1, 0].set_ylim(0, 1.05)
    axes[1, 0].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _pos: f"{v:.0%}"))
    axes[1, 1].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _pos: f"{v:.0%}"))
    axes[0, 0].legend(frameon=False, loc="upper left")
    fig.suptitle("k = 2,  τ = 8.  Dashed line is the default α = 0.70", fontsize=12)
    fig.savefig(FIGURES / "alpha_regimes.png", dpi=140)
    plt.close(fig)


def _trigger_figure(data: dict) -> None:
    tau_rows = sorted(_rows(data, "tau_by_p", p=0.55, alpha=0.70), key=lambda row: row["tau"])
    tau_rows = [row for row in tau_rows if row["tau"] in TAU_TO_M]
    k_rows = sorted(_rows(data, "k_by_p", p=0.55, alpha=0.70), key=lambda row: row["k"])
    k_rows = [row for row in k_rows if row["k"] <= 7]
    no_split = _rows(data, "alpha_by_p", p=0.55, alpha=1.0)[0]
    ms = [TAU_TO_M[row["tau"]] for row in tau_rows]

    fig, axes = plt.subplots(1, 3, figsize=(11.4, 4.0), constrained_layout=True)

    ax = axes[0]
    _panel(ax)
    ax.plot(ms, [row["mean_log_growth"] for row in tau_rows], color="#0072b2", marker="o", linewidth=1.8, label="τ sets the first split")
    ax.axhline(no_split["mean_log_growth"], color="#111827", linestyle="--", linewidth=1.1, label="α = 1, no counter stake")
    ax.axhline(0, color="#9ca3af", linewidth=0.8)
    ax.set_ylim(-0.05, 0.16)
    ax.set_xlabel("Losses before the first split")
    ax.set_ylabel("Mean log-growth")
    ax.set_xticks(ms)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, 0.62))
    ax.set_title("Growth")

    ax = axes[1]
    _panel(ax)
    ax.plot(ms, [row["debt_frac"] for row in tau_rows], color="#0072b2", marker="o", linewidth=1.8, label="Steps in debt")
    ax.plot(ms, [row["clear_rate"] for row in tau_rows], color="#009e73", marker="o", linewidth=1.8, label="Episodes that resolve")
    ax.axhline(no_split["debt_frac"], color="#0072b2", linestyle="--", linewidth=1.0)
    ax.axhline(no_split["clear_rate"], color="#009e73", linestyle="--", linewidth=1.0)
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _pos: f"{v:.0%}"))
    ax.set_xlabel("Losses before the first split")
    ax.set_ylabel("Share of the horizon")
    ax.set_xticks(ms)
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Resolution")

    ax = axes[2]
    _panel(ax)
    ax.plot(ms, [row["p95_max_drawdown"] for row in tau_rows], color="#0072b2", marker="o", linewidth=1.8, label="τ stays on")
    ax.plot([row["k"] for row in k_rows], [row["p95_max_drawdown"] for row in k_rows], color="#d55e00", marker="o", linewidth=1.8, label="Streak k only")
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _pos: f"{v:.0%}"))
    ax.set_xlabel("Losses before the first split")
    ax.set_ylabel("95th percentile max drawdown")
    ax.set_xticks(range(1, 8))
    ax.legend(frameon=False, loc="center left")
    ax.set_title("Drawdown")

    fig.suptitle("p = 0.55,  α = 0.70.  Dashed lines are α = 1", fontsize=12)
    fig.savefig(FIGURES / "when_to_branch.png", dpi=140)
    plt.close(fig)


def _trace(outcomes: list[int], alpha: float, k: int = 2, tau: float = 8.0) -> list[dict]:
    params = LabParams(p=0.55, alpha=alpha, k=k, tau=tau)
    return run_branching(outcomes, params, keep_trace=True).trace


def _path_figure() -> None:
    classroom = [0, 0] + [1] * 10
    rng = random.Random(42)
    horizon = [1 if rng.random() < 0.55 else 0 for _ in range(500)]

    fig, axes = plt.subplots(2, 2, figsize=(10.2, 7.2), constrained_layout=True)

    # Classroom: two losses, then ups. Cash and cold-side (short) debt.
    ax = axes[0, 0]
    _panel(ax)
    for alpha, color in ((0.70, "#0072b2"), (0.75, "#009e73"), (1.00, "#111827")):
        trace = _trace(classroom, alpha)
        ax.plot(
            [row["step"] for row in trace],
            [row["cash"] for row in trace],
            color=color,
            marker="o",
            markersize=3.5,
            linewidth=1.6,
            label=f"α = {alpha:.2f}",
        )
    ax.axhline(1000, color="#9ca3af", linewidth=0.8)
    ax.set_title("Two losses, then up")
    ax.set_xlabel("Step")
    ax.set_ylabel("Cash")
    ax.legend(frameon=False)

    ax = axes[0, 1]
    _panel(ax)
    for alpha, color in ((0.70, "#0072b2"), (0.75, "#009e73"), (1.00, "#111827")):
        trace = _trace(classroom, alpha)
        ax.plot(
            [row["step"] for row in trace],
            [row["short_debt"] for row in trace],
            color=color,
            marker="o",
            markersize=3.5,
            linewidth=1.6,
            label=f"α = {alpha:.2f}",
        )
    ax.set_title("Cold-side debt on that same path")
    ax.set_xlabel("Step")
    ax.set_ylabel("Short debt")
    ax.legend(frameon=False)

    ax = axes[1, 0]
    _panel(ax)
    for alpha, color, name in ((0.70, "#0072b2", "α = 0.70"), (1.00, "#111827", "α = 1")):
        trace = _trace(horizon, alpha)
        ax.plot([row["step"] for row in trace], [row["cash"] for row in trace], color=color, linewidth=1.3, label=name)
    ax.axhline(1000, color="#9ca3af", linewidth=0.8)
    ax.set_title("One paired path, seed 42")
    ax.set_xlabel("Step")
    ax.set_ylabel("Cash")
    ax.legend(frameon=False)

    ax = axes[1, 1]
    _panel(ax)
    for alpha, color, name in ((0.70, "#0072b2", "α = 0.70"), (1.00, "#111827", "α = 1")):
        trace = _trace(horizon, alpha)
        ax.plot(
            [row["step"] for row in trace],
            [row["short_debt"] for row in trace],
            color=color,
            linewidth=1.3,
            label=name,
        )
    ax.set_title("Cold-side debt on that path")
    ax.set_xlabel("Step")
    ax.set_ylabel("Short debt")
    ax.legend(frameon=False)

    fig.suptitle("p = 0.55,  k = 2,  τ = 8.  The same outcomes feed every line", fontsize=12)
    fig.savefig(FIGURES / "path_shape.png", dpi=140)
    plt.close(fig)


def main() -> None:
    if not STUDY.exists():
        raise SystemExit(f"missing {STUDY}; run python src/study_branching.py first")
    data = json.loads(STUDY.read_text())
    FIGURES.mkdir(parents=True, exist_ok=True)
    _style()
    _alpha_figure(data)
    _trigger_figure(data)
    _path_figure()
    for name in ("alpha_regimes.png", "when_to_branch.png", "path_shape.png"):
        print(FIGURES / name)


if __name__ == "__main__":
    main()
