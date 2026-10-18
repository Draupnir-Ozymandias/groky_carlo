# EMA crossover for the dominant side of the branching book.
#
# ema-fast and ema-slow are project parameters so the optimizer can vary them.
# The starting pair is 5 and 10, the same defaults as src/ema.py. The update
# is QuantConnect's EMA: SMA seed, then smoothing 2 / (length + 1).
#
# A read at this bar's close sizes the next bar. Fast above slow is an upward
# trend and the dominant side is long. Fast below slow is a downward trend and
# the dominant side is short. The lab places the fresh stake and the alpha leg
# of a split on that side.

from AlgorithmImports import *


class EmaDominantBias(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2025, 1, 1)
        self.set_end_date(2026, 9, 30)
        self.set_cash(1000)

        self.ema_fast = self._length("ema-fast", 5)
        self.ema_slow = self._length("ema-slow", 10)
        if self.ema_fast >= self.ema_slow:
            raise ValueError(
                f"ema-fast must be shorter than ema-slow, got {self.ema_fast} and {self.ema_slow}"
            )

        # Hourly BTCUSD is the feed this project can optimize on.
        # The lab replay uses Binance BTCUSDT closes with the same two lengths.
        self.symbol = self.add_crypto("BTCUSD", Resolution.HOUR).symbol
        self.fast = self.ema(self.symbol, self.ema_fast, Resolution.HOUR)
        self.slow = self.ema(self.symbol, self.ema_slow, Resolution.HOUR)
        self.set_warm_up(self.ema_slow)
        self.dominant_long = None

    def _length(self, name, default):
        raw = self.get_parameter(name)
        if raw is None or raw == "":
            return default
        length = int(raw)
        if length < 1:
            raise ValueError(f"{name} must be a positive integer, got {raw}")
        return length

    def on_data(self, data):
        if self.is_warming_up or not self.fast.is_ready or not self.slow.is_ready:
            self.dominant_long = None
            return
        if not data.contains_key(self.symbol):
            return

        fast = float(self.fast.current.value)
        slow = float(self.slow.current.value)
        self.plot("EMA", "fast", fast)
        self.plot("EMA", "slow", slow)
        if fast == slow:
            self.dominant_long = None
            return
        # Known at this close. The next stake, and a split's alpha leg, use it.
        self.dominant_long = fast > slow
        self.plot("Dominant", "long", 1 if self.dominant_long else 0)
