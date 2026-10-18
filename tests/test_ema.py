"""EMA crossover and the dominant-side stake rule.

Lengths are arguments. 5 and 10 are the starting pair, not constants inside
the update.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ema import (  # noqa: E402
    DEFAULT_FAST_LENGTH,
    DEFAULT_SLOW_LENGTH,
    crossover_at_close,
    dominant_bias,
    ema_values,
    smoothing_factor,
)
from simulate import LabParams, make_outcomes, run_branching  # noqa: E402


def _close(testcase: unittest.TestCase, got: float, want: float) -> None:
    testcase.assertAlmostEqual(got, want, places=6)


class EmaTests(unittest.TestCase):
    def test_seed_is_the_sma_then_the_lean_update(self) -> None:
        self.assertEqual(smoothing_factor(3), 0.5)
        values = ema_values([1.0, 2.0, 3.0, 6.0], 3)
        self.assertEqual(values[:2], [None, None])
        _close(self, values[2], 2.0)
        _close(self, values[3], 4.0)

    def test_default_lengths_are_the_starting_pair(self) -> None:
        self.assertEqual((DEFAULT_FAST_LENGTH, DEFAULT_SLOW_LENGTH), (5, 10))
        rising = [float(price) for price in range(1, 30)]
        bias = dominant_bias(rising, DEFAULT_FAST_LENGTH, DEFAULT_SLOW_LENGTH)
        self.assertEqual(bias[:DEFAULT_SLOW_LENGTH], [None] * DEFAULT_SLOW_LENGTH)
        self.assertEqual(set(bias[DEFAULT_SLOW_LENGTH:]), {1})

    def test_fast_must_be_shorter_than_slow(self) -> None:
        with self.assertRaises(ValueError):
            dominant_bias([1.0, 2.0, 3.0], 10, 5)
        with self.assertRaises(ValueError):
            ema_values([1.0], 0)

    def test_downtrend_is_short_and_the_current_close_is_not_used(self) -> None:
        closes = [float(price) for price in range(20, 0, -1)]
        fast, slow = 2, 4
        bias = dominant_bias(closes, fast, slow)
        self.assertEqual(bias[:slow], [None] * slow)
        self.assertEqual(set(bias[slow:]), {0})

        # The stake on bar i is blind to closes[i] and everything after it.
        index = slow
        changed = closes.copy()
        changed[index] = 10_000.0
        self.assertEqual(dominant_bias(changed, fast, slow)[index], bias[index])
        changed_prior = closes.copy()
        changed_prior[index - 1] = 10_000.0
        self.assertNotEqual(dominant_bias(changed_prior, fast, slow)[index], bias[index])

    def test_ready_crossover_matches_the_two_averages(self) -> None:
        closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        signal = crossover_at_close(closes, 2, 3)
        self.assertEqual(signal[:2], [None, None])
        self.assertEqual(signal[2:], [1, 1, 1, 1])
        _close(self, ema_values(closes, 2)[2], 2.5)
        _close(self, ema_values(closes, 3)[2], 2.0)


class DominantStakeTests(unittest.TestCase):
    def test_uptrend_opens_long_even_when_p_is_fair(self) -> None:
        params = LabParams(p=0.5)
        result = run_branching([1], params, keep_trace=True, bias=[1])
        _close(self, result.trace[0]["long_stake"], 1.0)
        _close(self, result.trace[0]["short_stake"], 0.0)
        self.assertEqual(result.trace[0]["dominant"], "long")

    def test_downtrend_puts_the_alpha_leg_on_short(self) -> None:
        params = LabParams()
        # Two up reads build the long debt. The split itself is a down read.
        result = run_branching([0, 0, 1], params, keep_trace=True, bias=[1, 1, 0])
        rows = result.trace
        _close(self, rows[0]["long_stake"], 1.0)
        _close(self, rows[1]["long_stake"], 2.0)
        _close(self, rows[1]["short_stake"], 0.0)
        # Recovery target 4. Alpha 2.8 goes short. 1.2 stays on the debt.
        _close(self, rows[2]["long_stake"], 1.2)
        _close(self, rows[2]["short_stake"], 2.8)
        self.assertEqual(rows[2]["dominant"], "short")
        self.assertEqual(rows[2]["short_depth"], 1)

    def test_uptrend_keeps_alpha_on_the_long_debt(self) -> None:
        params = LabParams()
        result = run_branching([0, 0, 1], params, keep_trace=True, bias=[1, 1, 1])
        _close(self, result.trace[2]["long_stake"], 2.8)
        _close(self, result.trace[2]["short_stake"], 1.2)
        self.assertEqual(result.trace[2]["dominant"], "long")

    def test_unsplit_double_stays_on_the_debt(self) -> None:
        params = LabParams()
        result = run_branching([0, 0], params, keep_trace=True, bias=[1, 0])
        _close(self, result.trace[1]["long_stake"], 2.0)
        _close(self, result.trace[1]["short_stake"], 0.0)
        self.assertEqual(result.trace[1]["dominant"], "short")

    def test_no_read_matches_the_p_rule(self) -> None:
        params = LabParams()
        outcomes = [0, 0, 1, 1, 1]
        plain = run_branching(outcomes, params, keep_trace=True)
        unread = run_branching(outcomes, params, keep_trace=True, bias=[None] * len(outcomes))
        for left, right in zip(plain.trace, unread.trace):
            self.assertEqual(left["long_stake"], right["long_stake"])
            self.assertEqual(left["short_stake"], right["short_stake"])
            self.assertEqual(left["cash"], right["cash"])
            self.assertEqual(right["dominant"], "")

    def test_risk_cap_funds_the_dominant_side_first(self) -> None:
        params = LabParams(capital=100.0, base=10.0, risk_cap=0.10, k=1, tau=10_000.0)
        result = run_branching([0, 1], params, keep_trace=True, bias=[1, 0])
        # Split wants 6 long and 14 short. Budget 10 keeps the short base and drops long.
        _close(self, result.trace[1]["long_stake"], 0.0)
        _close(self, result.trace[1]["short_stake"], 10.0)

    def test_bias_must_cover_every_outcome(self) -> None:
        with self.assertRaises(ValueError):
            run_branching([1, 0], LabParams(), bias=[1])

    def test_books_stay_within_cash(self) -> None:
        rng = random.Random(11)
        params = LabParams(capital=40.0, p=0.5, alpha=0.70, risk_cap=0.25)
        for _ in range(10):
            outcomes = make_outcomes(rng, 80, 0.5)
            bias = [rng.choice([1, 0, None]) for _ in outcomes]
            result = run_branching(outcomes, params, keep_trace=True, bias=bias)
            self.assertGreaterEqual(result.terminal, -1e-6)
            for row in result.trace:
                self.assertGreaterEqual(row["cash"], -1e-6)
                self.assertLessEqual(row["long_stake"] + row["short_stake"], 0.25 * params.capital + 1e-6)


if __name__ == "__main__":
    unittest.main()
