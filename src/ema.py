"""EMA crossover used as a dominant-side filter.

The lengths are arguments. QuantConnect optimization varies the same two
parameters. The update matches Lean's ExponentialMovingAverage: the first
ready value is the simple moving average of the first `length` prices, and
later values use smoothing 2 / (length + 1).

A read at the close of bar t is allowed to size the stake that settles on
bar t+1. It is not allowed to size the stake that settles on bar t, because
that stake's outcome is bar t's own close versus open.
"""

from __future__ import annotations

# Starting lengths for a crossover. Callers and the QuantConnect project
# parameters pass these in; the update itself does not mention them.
DEFAULT_FAST_LENGTH = 5
DEFAULT_SLOW_LENGTH = 10


def smoothing_factor(length: int) -> float:
    """Lean's default EMA smoothing, 2 / (length + 1)."""
    _check_length(length)
    return 2.0 / (1 + length)


def _check_length(length: int) -> None:
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError(f"EMA length must be a positive integer, got {length!r}")


def check_lengths(fast: int, slow: int) -> None:
    """Fast must be the shorter average. A crossover is not defined otherwise."""
    _check_length(fast)
    _check_length(slow)
    if fast >= slow:
        raise ValueError(f"fast EMA length must be shorter than slow, got {fast} and {slow}")


def ema_values(prices: list[float], length: int) -> list[float | None]:
    """EMA aligned with `prices`. Entries before the seed are None.

    Index `length - 1` is the SMA of `prices[:length]`. Each later value is
    `price * k + previous * (1 - k)`.
    """
    _check_length(length)
    out: list[float | None] = [None] * len(prices)
    if len(prices) < length:
        return out
    k = smoothing_factor(length)
    previous = sum(prices[:length]) / length
    out[length - 1] = previous
    for index in range(length, len(prices)):
        previous = prices[index] * k + previous * (1.0 - k)
        out[index] = previous
    return out


def crossover_at_close(prices: list[float], fast: int, slow: int) -> list[int | None]:
    """Crossover known at each close.

    `1` when the fast EMA is above the slow EMA, `-1` when it is below,
    `0` when they are equal, and None until both averages are ready.
    """
    check_lengths(fast, slow)
    fast_ema = ema_values(prices, fast)
    slow_ema = ema_values(prices, slow)
    signal: list[int | None] = []
    for fast_value, slow_value in zip(fast_ema, slow_ema):
        if fast_value is None or slow_value is None:
            signal.append(None)
        elif fast_value > slow_value:
            signal.append(1)
        elif fast_value < slow_value:
            signal.append(-1)
        else:
            signal.append(0)
    return signal


def dominant_bias(closes: list[float], fast: int, slow: int) -> list[int | None]:
    """Dominant side for the stake that settles on each bar.

    `1` is long, `0` is short, None leaves the book on the `p` rule.
    The value at index i uses closes strictly before i. The first `slow`
    bars stay None, because the slow average is not ready until that many
    closes have printed.
    """
    signal = crossover_at_close(closes, fast, slow)
    bias: list[int | None] = []
    for index in range(len(closes)):
        if index == 0:
            bias.append(None)
            continue
        previous = signal[index - 1]
        if previous is None or previous == 0:
            bias.append(None)
        else:
            bias.append(1 if previous > 0 else 0)
    return bias
