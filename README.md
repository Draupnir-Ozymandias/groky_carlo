# Monte Carlo research lab

Self-contained brief: [PROJECT_BRIEF.md](PROJECT_BRIEF.md).

This directory is the project root. Stake and debt updates are in [docs/equations.md](docs/equations.md). Variable names are in [docs/variables.md](docs/variables.md). When a branch resolves, and when it does not, is in [docs/branching_regimes.md](docs/branching_regimes.md). The Bitcoin 5-minute replay is in [docs/btc_replay.md](docs/btc_replay.md). The same replay on 15-minute, 1-hour, 4-hour, and daily bars is in [docs/btc_timeframes.md](docs/btc_timeframes.md).

Branching does not create positive expectancy when \(p \le 0.5\) under even money, and it does not remove the possibility of ruin under finite capital. It only changes the shape of the path.

## Run

```bash
python src/run_lab.py --paths 2000 --horizon 500 --p 0.55 --alpha 0.70 --seed 42
```

Writes `results/summary.json` and `results/trace_sample.csv`.

Default scenario: capital 1000, base 1, \(p = 0.55\), \(\alpha = 0.70\), \(k = 2\), \(\tau = 8\), depth cap 6, risk cap 0.25, Kelly scale 0.5, seed 42. The debt trigger defaults to \(8 \times\) base when `--tau` is omitted.

The engine runs pure martingale, half-Kelly, Paroli, and the branching long/short recovery rule on the same outcome paths. Trace rows are the first 25 branching paths. Each row's stake columns are the book that just settled.

## Tests

```bash
python -m unittest tests.test_branching
```

## Small sweep

```bash
python src/run_lab.py --sweep
```

Writes `results/sweep.json` for \(p \in \{0.45, 0.50, 0.55, 0.60\}\) and \(\alpha \in \{0.50, 0.70, 1.00\}\) at 200 paths and horizon 200. The sweep does not replace the default scenario file.
