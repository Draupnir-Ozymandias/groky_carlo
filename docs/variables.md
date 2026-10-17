# Variables

Names used by `src/simulate.py`, `results/summary.json`, and `results/trace_sample.csv`. Stake and debt updates are in [equations.md](equations.md).

Default run: \(p = 0.55\), \(C_0 = 1000\), \(b = 1\), \(\alpha = 0.70\), \(k = 2\), \(\tau = 8b\), \(d_{\max} = 6\), \(r = 0.25\), half-Kelly, 2000 paths, horizon 500, seed 42, 25 traced paths.

## Inputs

Parameters of one run. All four strategies share them and see the same outcomes.

| Symbol | Code | Default | Meaning |
|---|---|---:|---|
| \(p\) | `p` | 0.55 | Probability the step is up. Down has probability \(1 - p\). |
| \(C_0\) | `capital` | 1000 | Starting cash, shared by every strategy. |
| \(b\) | `base` | 1 | Base stake. A finished cycle is sized to net one base. |
| \(\alpha\) | `alpha` | 0.70 | Share of a split recovery that stays on the side already in debt. The other side receives \(1 - \alpha\). Range \(0.50\)–\(1\). |
| \(k\) | `k` | 2 | Consecutive losses on one lineage that force a split. |
| \(\tau\) | `tau` | \(8b\) | Debt level that forces a split. Measured in cash, so a shorter streak still splits once debt reaches this level. |
| \(d_{\max}\) | `d_max` | 6 | Deepest generation that may be opened. |
| \(r\) | `risk_cap` | 0.25 | Open stakes may not exceed \(r \cdot C_0\). |
| | `kelly_scale` | 0.5 | Multiplier on the even-money Kelly fraction. The default is half-Kelly. Used by flat Kelly. |
| \(N\) | `paths` | 2000 | Number of paired paths. |
| \(T\) | `horizon` | 500 | Maximum bets on a path. Ruin stops the path sooner. |
| | `seed` | 42 | Master random seed. Path \(i\) continues that same stream. |
| | `trace_paths` | 25 | How many branching paths are written to the trace CSV. |

## Outcome and book

One settled step. In the engine, up is `1` and down is `0`.

\[
S = \text{debt} + b
\qquad
f^{\*}= 2p - 1
\qquad
B = r \cdot C_0
\]

\(S\) is the recovery target: a win of this size clears that lineage’s debt and nets one base. Before a split, the next stake is \(\min(2s, S)\), where \(s\) is the stake just settled. Flat Kelly bets `kelly_scale` \(\times f^{\*} \times\) current cash when \(p > 0.5\), and bets \(b\) on long when \(p \le 0.5\). If a proposed long-plus-short book exceeds \(B\) or cash, escalation freezes and only base-sized legs that fit are kept.

| Symbol | Code | Meaning |
|---|---|---|
| \(U_t\) | `outcome` | `up` or `down`. Up wins the long stake and loses the short stake. Down does the reverse. |
| \(C\) | `cash` | Cash after the step settles. |
| \(s\) | `stake` | The single stake used by martingale, Kelly, and Paroli. |
| \(S\) | recovery target | Debt plus one base, as above. |
| \(f^{\*}\) | Kelly fraction | Even-money Kelly fraction, as above. |
| \(B\) | risk budget | Cap on the sum of open stakes, as above. |

## Branching lineage

Long and short each keep the same five fields. A win on a side subtracts that side’s stake from its debt and floors the debt at 0. Any surplus stays in cash.

| Code | Meaning |
|---|---|
| `stake` | Stake open for this side on the current step. |
| `debt` | Losses on this side that a later win has not yet repaid. |
| `streak` | Consecutive losses on this side since its last win. A win sets it to 0. |
| `depth` | Generation of this side’s current life. Opening a clear side sets the child to the parent’s depth plus 1. Adding stake to a side that already has debt leaves depth unchanged. Collapse sets depth back to 0. |
| `active` | True when this side has a positive stake. |

The trace stores each field under a side prefix.

| Field | Long | Short |
|---|---|---|
| Stake | `long_stake` | `short_stake` |
| Debt | `long_debt` | `short_debt` |
| Depth | `long_depth` | `short_depth` |

## Trace row

One row per settled step, for the sampled branching paths.

```text
path_id, step, outcome, cash, long_stake, short_stake, long_debt, short_debt, long_depth, short_depth, reset, ruined
```

| Column | Meaning |
|---|---|
| `path_id` | Path index, starting at 0. |
| `step` | 1-based step number. |
| `outcome` | `up` or `down`. |
| `cash` | Cash after settlement. |
| `long_stake`, `short_stake` | Stakes that just settled. The next book is the next row. |
| `long_debt`, `short_debt` | Debt after settlement and after any collapse. |
| `long_depth`, `short_depth` | Depth of the book that just settled. |
| `reset` | 1 if either side collapsed on this step, because its debt fell to 0 or below. |
| `ruined` | 1 on the last settled step when the path cannot fund another stake. |

## Results

### One path

| Code | Meaning |
|---|---|
| `terminal` | Cash when the path stops. |
| `ruined` | True when the next stake cannot be funded. |
| `ruin_step` | 1-based index of the stake that could not be funded. Absent when the path reaches the horizon. |
| `max_drawdown` | Largest \((\text{peak cash} - \text{cash}) / \text{peak cash}\) on the path. |
| `max_depth` | Deepest generation reached on that path. |
| `resets` | How many lineage collapses occurred. |
| `hit_target` | True if cash reached \(1.5\,C_0\) at any point. |

### Ensemble

Reported once per strategy in `results/summary.json`.

| Code | Meaning |
|---|---|
| `ruin_rate` | Fraction of paths that ruin. |
| `median_steps_to_ruin` | Median `ruin_step` among ruined paths. |
| `median_terminal`, `mean_terminal` | Terminal cash across paths. |
| `frac_above_start` | Fraction of paths with terminal cash above \(C_0\). |
| `frac_hit_1_5_c0` | Fraction of paths that reached \(1.5\,C_0\). |
| `median_max_drawdown`, `p95_max_drawdown` | Median and nearest-rank 95th percentile of `max_drawdown`. |
| `mean_log_growth` | Mean of \(\ln(W / C_0)\). A ruined or non-positive terminal uses \(W = 1\). |
| `log_floor_unit` | That floor: 1 currency unit. |
| `frac_with_reset` | Fraction of paths with at least one collapse. |
| `median_max_depth`, `max_depth_hist` | Median and counts of `max_depth`. Martingale, flat Kelly, and Paroli record depth 0 on every path. |
