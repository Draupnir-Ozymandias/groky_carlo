# Monte Carlo Research Lab — Branching Long/Short Recovery

Document for Grok Build. Self-contained. Do not assume access to any prior chat.

Placement note: this environment has no `/Users/grok`. All artifacts live under the project root that contains this file (`monte_carlo/`). If a local mirror is required, copy this tree to `/Users/grok/monte_carlo`.

## Intent

Build a research lab, not a betting product. The lab exists to pressure-test a specific idea:

A classic martingale doubles a single stake after every loss and resets after a win. On a binary even-money outcome that is not exactly fair, long losing runs still dominate ruin risk. The hypothesis under test is that an **asymmetric branch** into simultaneous long and short lineages, plus a **recursive collapse** back to base stake when local debt is cleared, can reshape the path of debt without inventing edge.

The lab must make that hypothesis falsifiable. It must show, under controlled bias, capital, and depth limits, whether branching reduces ruin frequency and peak debt relative to pure martingale, and at what cost in growth.

Honesty constraint, to be visible in the UI and in this document: branching does not create positive expectancy when \(p \le 0.5\) under even money, and it does not remove the possibility of ruin under finite capital. It only changes the shape of the path.

## Objectives

1. Simulate independent binary outcomes with configurable win probability \(p\).
2. Run four strategies on identical path ensembles so comparisons are paired.
3. Implement the branching long/short recovery system with asymmetric split and recursive reset.
4. Report ruin, drawdown, terminal wealth, log-growth, reset frequency, and max depth.
5. Export single-path traces so a human can audit stake and debt updates.
6. Keep the simulation code small, commented, and separable from the UI.

Non-objectives: live trading, exchange connectivity, order routing, casino advice, or any claim that the system beats a known house edge.

## Outcome model

Each step \(t\) draws an independent binary result.

- \(P(\text{up}) = p\), configurable, default \(0.50\), sweep range \(0.40\) to \(0.65\).
- Even money. A winning stake \(s\) returns \(+s\) profit. A losing stake returns \(-s\).
- No fees in v1. A later toggle may subtract a constant fee per resolution.

“Up” settles the long lineage as a win and the short lineage as a loss. “Down” does the reverse. Exactly one side of any simultaneous pair is fulfilled.

## Strategies

All strategies share the same capital \(C_0\), base stake \(b\), horizon, and random stream (paired by path id and seed).

### 1. Pure martingale (baseline)

- Bet one side only. Default side is the favored side if \(p \neq 0.5\), else long.
- After a loss, next stake \(= 2 \times\) previous stake.
- After a win, next stake \(= b\), and the cycle profit target is \(+b\) net of the cycle’s losses.
- Stop the path on ruin (cannot fund the next stake) or at horizon.

### 2. Flat Kelly (baseline)

- If \(p > 0.5\), bet fraction \(f = \max(0, 2p - 1)\) of current capital on the favored side, optionally scaled by a Kelly fraction (default \(0.5\)).
- If \(p \le 0.5\), bet \(b\) flat on long (no claimed edge).
- No escalation after losses.

### 3. Anti-martingale / Paroli (baseline)

- Start at \(b\).
- After a win, next stake \(= 2 \times\) previous stake, capped at 3 doubles, then reset to \(b\).
- After a loss, next stake \(= b\).

### 4. Branching asymmetric recovery (system under test)

Two lineages, Long and Short. Each lineage stores:

- `stake`
- `debt` (accumulated unrecovered loss attributed to this lineage)
- `loss_streak`
- `depth`
- `active`

Root behavior:

- Open a base stake \(b\) on the favored side if \(p \neq 0.5\). If \(p = 0.5\), open \(b/2\) on each side.
- Capital is shared. A stake is placed only if cash covers it.

Bifurcation rule. After `k` consecutive losses on a lineage, or when that lineage’s debt exceeds threshold \(\tau\), the next recovery amount \(S\) is split:

\[
S_{\text{continue}} = \alpha S, \qquad S_{\text{counter}} = (1 - \alpha) S
\]

with \(\alpha \in [0.5, 1]\), default \(0.70\). Continue-side stake escalates. Counter-side stake opens or adds to the opposite lineage. Default trigger \(k = 2\). Default \(\tau = 8b\).

Depth rule. A child spawned by bifurcation has `depth = parent.depth + 1`. If `depth > d_max` (default 6), do not spawn; instead place a single reduced stake \(\min(S, b)\) on the continue side only, or skip if that would breach the risk cap.

Risk cap. Before any new stake, require

\[
\text{open stakes} + \text{proposed stake} \le r \cdot C_0
\]

with default \(r = 0.25\). If the cap binds, freeze escalation and only allow base-sized bets that fit.

Recursive collapse. After settlement, if a lineage’s marked equity (cash attributed to it, or simply `-debt` once wins have repaid debt and a one-base surplus) satisfies `debt <= 0`, collapse that lineage: set stake back to \(b\), clear streak, clear depth, mark a reset event. Surplus above the repaid debt is released to shared cash. This is the cycle-back-to-initial-state rule.

Settlement order each step:

1. Draw outcome.
2. Settle every open stake. Winner: cash += stake, debt -= stake (floor at a small surplus, then zero). Loser: cash -= stake, debt += stake, streak += 1.
3. Apply collapse where debt <= 0.
4. Compute next stakes from the bifurcation rule, subject to cash and risk cap.
5. Record trace row.

Ruin: cash cannot fund the minimum next stake (\(b\) or the capped proposal) and no collapse is available. Record ruin step and stop the path.

## Parameters (v1)

| Name | Symbol | Default | Range / notes |
|---|---|---|---|
| Win probability | \(p\) | 0.55 | 0.40–0.65 |
| Starting capital | \(C_0\) | 1000 | currency units |
| Base stake | \(b\) | 1 | or fraction of capital |
| Asymmetry | \(\alpha\) | 0.70 | 0.50–1.00 |
| Loss trigger | \(k\) | 2 | consecutive losses |
| Debt trigger | \(\tau\) | 8b | absolute |
| Max depth | \(d_{\max}\) | 6 | |
| Risk cap | \(r\) | 0.25 | fraction of \(C_0\) |
| Paths | \(N\) | 2000 | paired across strategies |
| Horizon | \(T\) | 500 | bets, or until ruin |
| Seed | | 42 | master seed, path id offset |
| Kelly fraction | | 0.5 | baseline 2 only |

## Metrics

Per strategy, over the path ensemble:

- Risk of ruin: fraction of paths that stop because the next stake cannot be funded.
- Median and 95th percentile of max drawdown (from path peak equity).
- Median and mean terminal wealth; fraction of paths above \(C_0\).
- Mean log-growth: \(\mathbb{E}[\log(W_T / C_0)]\), paths that ruin contribute a floor (use \(\log(\epsilon)\), \(\epsilon = 1\) unit, and report the floor explicitly).
- Fraction of paths that executed at least one collapse/reset.
- Distribution of max depth reached (branching strategy only).
- Median steps to ruin, conditional on ruin.
- Optional target: fraction of paths that hit \(1.5 C_0\) before ruin.

Paired comparison: same outcome sequence applied to all four strategies. Report ruin-rate difference (branching minus pure martingale) with a simple bootstrap interval in a later pass.

## Trace schema

One row per step per path, written for sampled paths (default 25 paths), not all 2000.

```
path_id, step, outcome, cash, long_stake, short_stake, long_debt, short_debt, long_depth, short_depth, reset, ruined
```

`outcome` is `up` or `down`. `reset` is 1 if any lineage collapsed on that step.

## Project layout

```
monte_carlo/
  PROJECT_BRIEF.md          this document
  README.md                 how to run
  src/
    simulate.py             engine: one path, four strategies
    metrics.py              ensemble summaries
    run_lab.py              CLI entry: default scenario + small sweep
  results/                  csv and json written by run_lab.py
  docs/
    equations.md            stake and debt updates in symbols
```

UI is out of scope for the first code drop. The engine must be runnable as:

```
python src/run_lab.py --paths 2000 --horizon 500 --p 0.55 --alpha 0.70 --seed 42
```

A later UI (plain HTML or a small local dashboard) may read `results/summary.json` and a trace csv. Do not block the research engine on the UI.

## Acceptance for v1

- Identical seeds reproduce identical summary numbers.
- Pure martingale at \(p = 0.5\), \(C_0 = 1000\), \(b = 1\), horizon 500, shows high ruin relative to flat betting. This is a sanity check, not a tuned result.
- Branching strategy never places a stake that cash cannot fund.
- A unit test (or a printed example path) shows: two losses, a split, one side wins, debt on that side falls, and a collapse occurs once debt returns to \(\le 0\).
- Summary json includes ruin rate, median max drawdown, and median terminal wealth for all four strategies.

## Later experiments (not v1)

- Fee per resolution.
- Soft multiplier instead of pure double on the continue side (1.3–1.7).
- Unknown-bias mode: root seeds both sides and lets collapse select the survivor (separable-mixture idea).
- Sweep heatmaps of ruin vs \(p\) and \(\alpha\).
- Bootstrap confidence intervals on paired ruin differences.

## Mathematical anchors (for comments, not for the UI to overclaim)

- Optional stopping: a fair even-money martingale stopped at a bounded time has non-positive expected gain. Finite capital is a bound.
- Kelly fraction for even money is \(f^* = 2p - 1\). Flat Kelly is the growth baseline when \(p\) is known.
- Branching here is an accounting tree of recovery lineages, not a claim of arbitrage. Collapse is a reset rule, analogous to ending a martingale round when the cycle is repaid.

## Default scenario the first run must execute

Capital 1000, base 1, \(p = 0.55\), \(\alpha = 0.70\), \(k = 2\), \(\tau = 8\), \(d_{\max} = 6\), risk cap 0.25, 2000 paths, horizon 500, seed 42. Write `results/summary.json` and `results/trace_sample.csv`.
