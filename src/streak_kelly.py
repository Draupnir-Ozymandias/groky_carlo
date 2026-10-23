"""Half-Kelly fade of a BTC direction streak.

The state is the exact number of consecutive decisive bars just seen on one
side. An up streak is faded by a short bet. A down streak is faded by a long
bet. The win probability is the 2025 share of streaks of that length whose
next bar reversed. 2026 does not enter that table.

Even-money Kelly is f* = 2p - 1. The stake is half of that fraction of cash,
the lab's Kelly scale. A length is used only when 2025 recorded at least 100
reversal trials and the estimated win probability is above one half. Below
that, the fraction is zero and the bar is passed.

The stake that settles on bar t uses the streak ending at bar t-1.

    python src/streak_kelly.py

Writes results/streak_kelly.json. Raw zips stay under data/.
"""

from __future__ import annotations

import json
import math

import btc_replay
from simulate import HONESTY, _kelly_fraction

# A length with fewer 2025 trials than this is not a probability to bet.
# At 100 trials a 55% estimate is about one standard error from one half.
MIN_TRIALS = 100
KELLY_SCALE = 0.5


def streak_trials(bits: list[int]) -> dict[tuple[int, int], tuple[int, int]]:
    """Count the bar that follows each exact streak.

    Key is (side, length). Side 1 is an up streak and side 0 is a down streak.
    The value is (followed by down, followed by up). The last bar has no
    follower, so it is not a trial.
    """
    counts: dict[tuple[int, int], list[int]] = {}
    side: int | None = None
    length = 0
    for bit in bits:
        if length:
            bucket = counts.setdefault((side, length), [0, 0])
            bucket[bit] += 1
        if bit == side:
            length += 1
        else:
            side = bit
            length = 1
    return {key: (down, up) for key, (down, up) in counts.items()}


def fade_table(bits: list[int]) -> dict[tuple[int, int], dict]:
    """2025-style table: p is the probability that the next bar fades the streak."""
    table = {}
    for (side, length), (followed_down, followed_up) in streak_trials(bits).items():
        trials = followed_down + followed_up
        fade_wins = followed_down if side == 1 else followed_up
        table[(side, length)] = {
            "streak_up": side == 1,
            "n": length,
            "trials": trials,
            "fade_wins": fade_wins,
            "p_hat": fade_wins / trials,
        }
    return table


def stake_fraction(edge: dict | None, scale: float, min_trials: int) -> float:
    """Half-Kelly, or whatever scale is passed, when the 2025 cell clears the gate."""
    if edge is None or edge["trials"] < min_trials or edge["p_hat"] <= 0.5:
        return 0.0
    return _kelly_fraction(edge["p_hat"], scale)


def run_streak_kelly(
    bits: list[int],
    table: dict[tuple[int, int], dict],
    *,
    capital: float = btc_replay.CAPITAL,
    scale: float = KELLY_SCALE,
    min_trials: int = MIN_TRIALS,
    score_from: int = 0,
    flat_stake: float | None = None,
    keep_equity: bool = False,
) -> dict:
    """Walk bits. Stakes before score_from build the streak and do not move cash.

    flat_stake, when set, bets that many units on each signal instead of a
    Kelly fraction. The signals are the same ones.
    """
    if score_from < 0 or score_from > len(bits):
        raise ValueError(f"score_from {score_from} is outside a series of {len(bits)}")
    cash = capital
    peak = cash
    max_dd = 0.0
    bets = 0
    wins = 0
    fraction_sum = 0.0
    ruined = False
    equity: list[float] | None = [] if keep_equity else None
    by_key: dict[tuple[int, int], list[int]] = {}
    side: int | None = None
    length = 0
    for index, bit in enumerate(bits):
        fraction = 0.0
        if length and index >= score_from and not ruined:
            edge = table.get((side, length))
            fraction = stake_fraction(edge, scale, min_trials)
            if fraction > 0.0 or (flat_stake is not None and edge is not None and stake_fraction(edge, 1.0, min_trials) > 0.0):
                if flat_stake is None:
                    stake = cash * fraction
                else:
                    stake = flat_stake
                    fraction = stake / cash if cash > 0.0 else 0.0
                if stake > cash + 1e-12 or stake <= 0.0:
                    ruined = True
                else:
                    fade_wins = bit == 0 if side == 1 else bit == 1
                    cash += stake if fade_wins else -stake
                    if cash < 0.0 and cash > -1e-9:
                        cash = 0.0
                    if cash < -1e-9:
                        raise RuntimeError(f"cash went negative ({cash}) at index {index}")
                    bets += 1
                    wins += int(fade_wins)
                    fraction_sum += fraction
                    cell = by_key.setdefault((side, length), [0, 0])
                    cell[0] += 1
                    cell[1] += int(fade_wins)
                    peak = max(peak, cash)
                    if peak > 0.0:
                        max_dd = max(max_dd, (peak - cash) / peak)
                    if cash <= 0.0:
                        ruined = True
        if bit == side:
            length += 1
        else:
            side = bit
            length = 1
        if index + 1 == score_from:
            cash = capital
            peak = cash
            max_dd = 0.0
            ruined = False
        elif equity is not None and index >= score_from:
            equity.append(cash)
    wealth = btc_replay.LOG_FLOOR if ruined or cash <= 0.0 else cash
    scored = bits[score_from:]
    result = {
        "bars": len(scored),
        "bets": bets,
        "wins": wins,
        "hit_rate": None if bets == 0 else wins / bets,
        "terminal": cash,
        "log_growth": math.log(wealth / capital),
        "max_drawdown": max_dd,
        "ruined": ruined,
        "mean_fraction": None if bets == 0 else fraction_sum / bets,
        "by_length": [
            {
                "streak_up": key[0] == 1,
                "n": key[1],
                "bets": cell[0],
                "wins": cell[1],
                "hit_rate": cell[1] / cell[0],
                "p_hat": table[key]["p_hat"],
                "trials_2025": table[key]["trials"],
                "fraction": stake_fraction(table[key], scale if flat_stake is None else 1.0, min_trials)
                if flat_stake is None
                else None,
            }
            for key, cell in sorted(by_key.items(), key=lambda item: (item[0][0], item[0][1]))
        ],
    }
    if equity is not None:
        result["equity"] = equity
    return result


def _year_bits(rows: list[dict], year: int) -> list[int]:
    return [row["up"] for row in rows if btc_replay._utc_year(row["t"]) == year]


def run_interval(interval: str) -> dict:
    print(f"=== {interval} ===", flush=True)
    btc_replay._download(interval)
    bars = btc_replay._bars(interval)
    decisive, coverage = btc_replay._directions(bars)
    train = _year_bits(decisive, 2025)
    test = _year_bits(decisive, 2026)
    if not train or not test:
        raise SystemExit(f"{interval}: need both years")
    table = fade_table(train)
    playable = [
        row
        for row in table.values()
        if row["trials"] >= MIN_TRIALS and row["p_hat"] > 0.5
    ]
    playable.sort(key=lambda row: (not row["streak_up"], row["n"]))
    full = [row["up"] for row in decisive]
    payload = {
        "interval": interval,
        "coverage": coverage,
        "train_bars": len(train),
        "test_bars": len(test),
        "min_trials": MIN_TRIALS,
        "kelly_scale": KELLY_SCALE,
        "edges_2025": sorted(table.values(), key=lambda row: (not row["streak_up"], row["n"])),
        "playable_2025": playable,
        "train_kelly": run_streak_kelly(train, table),
        "test_kelly": run_streak_kelly(full, table, score_from=len(train)),
        "test_flat": run_streak_kelly(full, table, score_from=len(train), flat_stake=btc_replay.BASE),
    }
    chosen = ", ".join(
        f"{'up' if row['streak_up'] else 'down'} n={row['n']} p={row['p_hat']:.3f} ({row['trials']})"
        for row in playable
    )
    hold = payload["test_kelly"]
    print(
        f"  playable [{chosen}] holdout bets {hold['bets']} "
        f"hit {hold['hit_rate']} cash {hold['terminal']:.2f}",
        flush=True,
    )
    return payload


def main() -> None:
    rows = [run_interval(interval) for interval in ("5m", "15m", "1h", "4h", "1d")]
    payload = {
        "note": HONESTY,
        "abstraction": (
            "Up means close > open. The engine is paid even money on that bit. "
            "Kelly sizes the fade. It is not paid the bitcoin return, and it "
            "does not create an edge the probability table does not have."
        ),
        "rule": (
            "Fade the exact streak. Probability from 2025 only. "
            f"Bet when trials >= {MIN_TRIALS} and p_hat > 0.5. "
            f"Stake is {KELLY_SCALE} * (2p - 1) of cash. "
            "The streak is carried into 2026. Cash for the holdout starts at 1000."
        ),
        "rows": rows,
    }
    btc_replay.RESULTS.mkdir(parents=True, exist_ok=True)
    out = btc_replay.RESULTS / "streak_kelly.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
