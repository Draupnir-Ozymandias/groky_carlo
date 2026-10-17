"""Acceptance checks for the v1 recovery lab.

The printed path is the audit example: two losses, a split, a winning
settlement that cuts debt, then a collapse once that debt is back to 0.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from run_lab import execute, format_trace_csv, run_sweep  # noqa: E402
from simulate import (  # noqa: E402
    LabParams,
    fit_stakes,
    make_outcomes,
    run_branching,
    run_kelly,
    run_paroli,
    run_pure_martingale,
)


def _close(testcase: unittest.TestCase, got: float, want: float) -> None:
    testcase.assertAlmostEqual(got, want, places=6)


class FitStakeTests(unittest.TestCase):
    def test_full_proposal_when_it_fits(self) -> None:
        self.assertEqual(fit_stakes(2.8, 1.2, 1000, 250, 1, True), (2.8, 1.2))

    def test_risk_cap_freezes_to_base(self) -> None:
        self.assertEqual(fit_stakes(200, 100, 1000, 250, 1, True), (1, 1))

    def test_cash_shortfall_funds_favored_base_only(self) -> None:
        self.assertEqual(fit_stakes(500, 0, 100, 1000, 1, True), (1, 0))

    def test_skips_legs_that_do_not_fit(self) -> None:
        self.assertEqual(fit_stakes(0.4, 0.4, 0.3, 250, 1, True), (0.0, 0.0))


class StrategyTests(unittest.TestCase):
    def test_martingale_cycle_nets_one_base(self) -> None:
        params = LabParams(p=0.55)
        result = run_pure_martingale([0, 0, 1], params)
        self.assertFalse(result.ruined)
        _close(self, result.terminal, 1001.0)

    def test_martingale_ruin_is_the_unfunded_stake(self) -> None:
        params = LabParams(p=0.55)
        # Nine losses are funded (cash 489). The tenth stake, 512, is not.
        survived = run_pure_martingale([0] * 9, params)
        self.assertFalse(survived.ruined)
        _close(self, survived.terminal, 489.0)
        ruined = run_pure_martingale([0] * 12, params)
        self.assertTrue(ruined.ruined)
        self.assertEqual(ruined.ruin_step, 10)
        _close(self, ruined.terminal, 489.0)

    def test_kelly_flat_on_long_when_no_edge(self) -> None:
        params = LabParams(p=0.40)
        down = run_kelly([0], params)
        up = run_kelly([1], params)
        _close(self, down.terminal, 999.0)
        _close(self, up.terminal, 1001.0)

    def test_kelly_fraction_when_edge_is_known(self) -> None:
        params = LabParams(p=0.60, kelly_scale=0.5)
        up = run_kelly([1], params)
        down = run_kelly([0], params)
        _close(self, up.terminal, 1100.0)
        _close(self, down.terminal, 900.0)

    def test_paroli_allows_three_doubles_then_resets(self) -> None:
        params = LabParams(p=0.60)
        result = run_paroli([1, 1, 1, 1, 1], params)
        self.assertFalse(result.ruined)
        # Stakes placed: 1, 2, 4, 8, 1.
        _close(self, result.terminal, 1016.0)


class BranchingTests(unittest.TestCase):
    def test_two_losses_split_win_and_collapse(self) -> None:
        params = LabParams()
        # down, down, up, up. Favored side is long because p = 0.55.
        result = run_branching([0, 0, 1, 1, 1], params, keep_trace=True)
        rows = result.trace
        self.assertGreaterEqual(len(rows), 5)

        _close(self, rows[0]["cash"], 999.0)
        _close(self, rows[0]["long_stake"], 1.0)
        _close(self, rows[0]["short_stake"], 0.0)
        _close(self, rows[0]["long_debt"], 1.0)
        self.assertEqual(rows[0]["reset"], 0)

        # Second loss doubles. The split is the next book, settled on step 3.
        _close(self, rows[1]["long_stake"], 2.0)
        _close(self, rows[1]["short_stake"], 0.0)
        _close(self, rows[1]["long_debt"], 3.0)
        _close(self, rows[1]["cash"], 997.0)

        # Recovery target after debt 3 is 4. Split 0.70 / 0.30 -> 2.8 and 1.2.
        _close(self, rows[2]["long_stake"], 2.8)
        _close(self, rows[2]["short_stake"], 1.2)
        self.assertEqual(rows[2]["long_depth"], 0)
        self.assertEqual(rows[2]["short_depth"], 1)
        self.assertLess(rows[2]["long_debt"], rows[1]["long_debt"])
        _close(self, rows[2]["long_debt"], 0.2)
        _close(self, rows[2]["short_debt"], 1.2)
        self.assertEqual(rows[2]["reset"], 0)
        _close(self, rows[2]["cash"], 998.6)

        # The continue side's remaining debt is cleared and the lineage collapses.
        self.assertEqual(rows[3]["reset"], 1)
        _close(self, rows[3]["long_debt"], 0.0)
        _close(self, rows[3]["long_stake"], 1.2)
        _close(self, rows[3]["short_stake"], 2.2)
        _close(self, rows[3]["cash"], 997.6)
        self.assertGreater(result.resets, 0)
        # The cleared long lineage is re-opened by short, one generation deeper.
        self.assertEqual(result.max_depth, 2)
        _close(self, rows[4]["long_stake"], 2.32)
        _close(self, rows[4]["short_stake"], 3.08)
        self.assertEqual(rows[4]["long_depth"], 2)
        self.assertEqual(rows[4]["short_depth"], 1)

    def test_adding_to_a_live_lineage_does_not_ratchet_depth(self) -> None:
        params = LabParams(k=1, tau=10_000.0)
        result = run_branching([0, 0, 0, 0, 0, 0], params, keep_trace=True)
        self.assertEqual(result.max_depth, 1)
        self.assertTrue(any(row["short_stake"] > 0 for row in result.trace))

    def test_depth_cap_blocks_the_next_generation(self) -> None:
        params = LabParams(d_max=1)
        result = run_branching([0, 0, 1, 1, 1], params, keep_trace=True)
        self.assertLessEqual(result.max_depth, 1)
        _close(self, result.trace[4]["long_stake"], 1.0)
        _close(self, result.trace[4]["short_stake"], 1.0)

    def test_alpha_one_does_not_open_the_counter_leg(self) -> None:
        params = LabParams(alpha=1.0)
        result = run_branching([0, 0, 1], params, keep_trace=True)
        _close(self, result.trace[2]["long_stake"], 4.0)
        _close(self, result.trace[2]["short_stake"], 0.0)

    def test_fair_root_opens_both_sides(self) -> None:
        params = LabParams(p=0.5)
        result = run_branching([1], params, keep_trace=True)
        _close(self, result.trace[0]["long_stake"], 0.5)
        _close(self, result.trace[0]["short_stake"], 0.5)

    def test_risk_cap_freezes_escalation(self) -> None:
        params = LabParams(capital=100.0, base=10.0, tau=1000.0, risk_cap=0.25, k=2)
        result = run_branching([0, 0, 1], params, keep_trace=True)
        # Unconstrained split would be 28 and 12, above the budget of 25.
        _close(self, result.trace[2]["long_stake"], 10.0)
        _close(self, result.trace[2]["short_stake"], 10.0)
        self.assertLessEqual(
            result.trace[2]["long_stake"] + result.trace[2]["short_stake"],
            0.25 * params.capital + 1e-9,
        )

    def test_books_stay_within_cash(self) -> None:
        rng = random.Random(7)
        for p, alpha, risk in (
            (0.55, 0.70, 0.25),
            (0.50, 0.50, 1.0),
            (0.42, 1.00, 0.25),
            (0.63, 0.70, 0.10),
        ):
            params = LabParams(capital=40.0, p=p, alpha=alpha, risk_cap=risk, tau=8.0)
            for _ in range(10):
                outcomes = make_outcomes(rng, 80, p)
                result = run_branching(outcomes, params, keep_trace=True)
                self.assertGreaterEqual(result.terminal, -1e-6)
                for row in result.trace:
                    self.assertGreaterEqual(row["long_stake"], 0.0)
                    self.assertGreaterEqual(row["short_stake"], 0.0)


class EnsembleTests(unittest.TestCase):
    def test_summary_has_required_fields_and_reproduces(self) -> None:
        cfg = {
            "paths": 20,
            "horizon": 30,
            "p": 0.55,
            "capital": 1000.0,
            "base": 1.0,
            "alpha": 0.70,
            "k": 2,
            "tau": 8.0,
            "d_max": 6,
            "risk_cap": 0.25,
            "kelly_scale": 0.5,
            "seed": 42,
            "trace_paths": 2,
        }
        first, samples = execute(cfg)
        second, _ = execute(cfg)
        self.assertEqual(first, second)
        names = [row["strategy"] for row in first["strategies"]]
        self.assertEqual(names, ["pure_martingale", "flat_kelly", "paroli", "branching"])
        for row in first["strategies"]:
            for key in ("ruin_rate", "median_max_drawdown", "median_terminal"):
                self.assertIn(key, row)
        text = format_trace_csv(samples)
        self.assertTrue(
            text.startswith(
                "path_id,step,outcome,cash,long_stake,short_stake,"
                "long_debt,short_debt,long_depth,short_depth,reset,ruined\n"
            )
        )
        self.assertIn("\n0,1,", text)
        self.assertIn("\n1,1,", text)

    def test_fair_martingale_ruins_more_than_flat(self) -> None:
        params = LabParams(p=0.5, capital=1000.0, base=1.0)
        rng = random.Random(42)
        martingale_ruins = 0
        kelly_ruins = 0
        paths = 400
        for _ in range(paths):
            outcomes = make_outcomes(rng, 500, 0.5)
            if run_pure_martingale(outcomes, params).ruined:
                martingale_ruins += 1
            if run_kelly(outcomes, params).ruined:
                kelly_ruins += 1
        self.assertGreater(martingale_ruins, 0)
        self.assertEqual(kelly_ruins, 0)
        self.assertGreater(martingale_ruins, kelly_ruins)

    def test_small_sweep_grid(self) -> None:
        cfg = {
            "paths": 4,
            "horizon": 8,
            "p": 0.55,
            "capital": 1000.0,
            "base": 1.0,
            "alpha": 0.70,
            "k": 2,
            "tau": 8.0,
            "d_max": 6,
            "risk_cap": 0.25,
            "kelly_scale": 0.5,
            "seed": 1,
            "trace_paths": 0,
        }
        sweep = run_sweep(cfg)
        self.assertEqual(len(sweep["grid"]), 12)
        self.assertIn("p <= 0.5", sweep["note"])


if __name__ == "__main__":
    unittest.main()
