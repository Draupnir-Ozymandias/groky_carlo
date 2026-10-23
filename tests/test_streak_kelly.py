"""Streak fade sized by even-money Kelly.

The probability table is an argument. A test series does not get to rewrite it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from streak_kelly import (  # noqa: E402
    MIN_TRIALS,
    run_streak_kelly,
    stake_fraction,
    streak_trials,
)


def _edge(p_hat: float, trials: int = 200, n: int = 1, streak_up: bool = True) -> dict:
    return {
        "streak_up": streak_up,
        "n": n,
        "trials": trials,
        "fade_wins": int(round(p_hat * trials)),
        "p_hat": p_hat,
    }


class StreakKellyTest(unittest.TestCase):
    def test_a_follower_is_counted_once_at_the_exact_length(self) -> None:
        # Up, up, down. The second up continues a streak of 1. The down fades a streak of 2.
        counts = streak_trials([1, 1, 0])
        self.assertEqual(counts[(1, 1)], (0, 1))
        self.assertEqual(counts[(1, 2)], (1, 0))
        self.assertNotIn((0, 1), counts)

    def test_half_kelly_sits_out_without_an_edge_or_a_sample(self) -> None:
        self.assertAlmostEqual(stake_fraction(_edge(0.60), 0.5, MIN_TRIALS), 0.10)
        self.assertEqual(stake_fraction(_edge(0.50), 0.5, MIN_TRIALS), 0.0)
        self.assertEqual(stake_fraction(_edge(0.40), 0.5, MIN_TRIALS), 0.0)
        self.assertEqual(stake_fraction(_edge(0.60, trials=99), 0.5, MIN_TRIALS), 0.0)
        self.assertEqual(stake_fraction(None, 0.5, MIN_TRIALS), 0.0)

    def test_the_stake_uses_the_streak_before_the_bar(self) -> None:
        table = {(1, 1): _edge(0.60, n=1)}
        # Full Kelly so the cash change is 0.2 of the bankroll. Bar 0 has no streak.
        won = run_streak_kelly([1, 0], table, capital=1000, scale=1.0, min_trials=100)
        self.assertEqual(won["bets"], 1)
        self.assertEqual(won["wins"], 1)
        self.assertAlmostEqual(won["terminal"], 1200.0)
        lost = run_streak_kelly([1, 1], table, capital=1000, scale=1.0, min_trials=100)
        self.assertEqual(lost["wins"], 0)
        self.assertAlmostEqual(lost["terminal"], 800.0)

    def test_holdout_cash_starts_over_and_keeps_the_prefix_streak(self) -> None:
        table = {(1, 2): _edge(0.60, n=2)}
        # Prefix builds an up streak of 2. The scored bar is down, so the fade wins.
        result = run_streak_kelly(
            [1, 1, 0],
            table,
            capital=1000,
            scale=1.0,
            min_trials=100,
            score_from=2,
        )
        self.assertEqual(result["bars"], 1)
        self.assertEqual(result["bets"], 1)
        self.assertAlmostEqual(result["terminal"], 1200.0)

    def test_the_walk_uses_the_table_it_was_given(self) -> None:
        # Each second up continues the streak. The passed table still says the
        # fade wins 90% of the time, and the walk keeps betting that side.
        table = {(1, 1): _edge(0.90, trials=200, n=1)}
        result = run_streak_kelly([1, 1, 0, 1, 1, 0, 1, 1], table, capital=1000, scale=1.0, min_trials=100)
        self.assertEqual(result["bets"], 3)
        self.assertEqual(result["wins"], 0)
        self.assertAlmostEqual(result["by_length"][0]["p_hat"], 0.90)
        self.assertAlmostEqual(result["terminal"], 8.0)

    def test_flat_unit_uses_the_same_signal(self) -> None:
        table = {(1, 1): _edge(0.60, n=1)}
        result = run_streak_kelly([1, 0], table, capital=1000, flat_stake=1.0, min_trials=100)
        self.assertEqual(result["bets"], 1)
        self.assertAlmostEqual(result["terminal"], 1001.0)


if __name__ == "__main__":
    unittest.main()
