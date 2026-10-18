"""One-path engine for the branching long/short recovery lab.

Four strategies share a capital, a base stake, and one outcome sequence.
Branching does not create positive expectancy when p <= 0.5 under even money,
and it does not remove the possibility of ruin under finite capital. It only
changes the shape of the path.

See PROJECT_BRIEF.md and docs/equations.md.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

EPS = 1e-9
TARGET_MULTIPLE = 1.5

HONESTY = (
    "Branching does not create positive expectancy when p <= 0.5 under even money, "
    "and it does not remove the possibility of ruin under finite capital. "
    "It only changes the shape of the path."
)


@dataclass
class Lineage:
    stake: float = 0.0
    debt: float = 0.0
    streak: int = 0
    depth: int = 0
    active: bool = False


@dataclass
class PathResult:
    terminal: float
    ruined: bool
    ruin_step: int | None
    max_drawdown: float
    max_depth: int
    resets: int
    steps: int
    hit_target: bool
    trace: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class LabParams:
    capital: float = 1000.0
    base: float = 1.0
    p: float = 0.55
    alpha: float = 0.70
    k: int = 2
    tau: float = 8.0
    d_max: int = 6
    risk_cap: float = 0.25
    kelly_scale: float = 0.5


def make_outcomes(rng: random.Random, horizon: int, p: float) -> list[int]:
    """Independent binary draws. 1 is up (long wins), 0 is down (short wins)."""
    return [1 if rng.random() < p else 0 for _ in range(horizon)]


def _empty(cash: float, max_dd: float, max_depth: int, resets: int, steps: int, hit: bool, trace: list[dict], ruin_step: int | None) -> PathResult:
    return PathResult(cash, ruin_step is not None, ruin_step, max_dd, max_depth, resets, steps, hit, trace)


def _mark(cash: float, peak: float, max_dd: float, hit: bool, capital: float) -> tuple[float, float, bool]:
    peak = max(peak, cash)
    if peak > EPS:
        max_dd = max(max_dd, (peak - cash) / peak)
    if cash + EPS >= TARGET_MULTIPLE * capital:
        hit = True
    return peak, max_dd, hit


def _kelly_fraction(p: float, scale: float) -> float:
    """Even-money Kelly f* = 2p - 1, scaled. Non-positive when p <= 0.5."""
    return max(0.0, (2.0 * p - 1.0) * scale)


def run_pure_martingale(outcomes: list[int], params: LabParams) -> PathResult:
    """Double after a loss, reset to base after a win. One side only.

    Favored side when p != 0.5, otherwise long. A finished cycle nets +base
    if it wins before the stake can no longer be funded.
    """
    cash = params.capital
    peak = cash
    max_dd = 0.0
    hit = False
    side_long = params.p >= 0.5
    stake = params.base
    for step, up in enumerate(outcomes, start=1):
        if stake > cash + EPS:
            return _empty(cash, max_dd, 0, 0, step - 1, hit, [], step)
        won = up == 1 if side_long else up == 0
        cash += stake if won else -stake
        peak, max_dd, hit = _mark(cash, peak, max_dd, hit, params.capital)
        stake = params.base if won else stake * 2.0
    return _empty(cash, max_dd, 0, 0, len(outcomes), hit, [], None)


def run_kelly(outcomes: list[int], params: LabParams) -> PathResult:
    """Flat fractional Kelly on the favored side when p > 0.5.

    When p <= 0.5 there is no claimed edge: bet base on long, no escalation.
    """
    cash = params.capital
    peak = cash
    max_dd = 0.0
    hit = False
    fraction = _kelly_fraction(params.p, params.kelly_scale)
    for step, up in enumerate(outcomes, start=1):
        if fraction > 0.0:
            stake = min(cash * fraction, cash)
        else:
            stake = min(params.base, cash)
        # A flat base bet that cash cannot fully fund is ruin. A positive
        # Kelly fraction is always funded by construction while cash > 0.
        unfunded_flat = fraction <= 0.0 and stake + EPS < params.base
        if stake <= EPS or unfunded_flat:
            return _empty(cash, max_dd, 0, 0, step - 1, hit, [], step)
        won = up == 1  # long. Kelly never takes the short side in v1.
        cash += stake if won else -stake
        if cash < 0.0 and cash > -1e-6:
            cash = 0.0
        peak, max_dd, hit = _mark(cash, peak, max_dd, hit, params.capital)
    return _empty(cash, max_dd, 0, 0, len(outcomes), hit, [], None)


def run_paroli(outcomes: list[int], params: LabParams) -> PathResult:
    """Anti-martingale: double after wins, at most three doubles, then reset.

    Stakes in a clean win streak are b, 2b, 4b, 8b, then b again.
    A loss returns the next stake to b. Same side rule as pure martingale.
    """
    cash = params.capital
    peak = cash
    max_dd = 0.0
    hit = False
    side_long = params.p >= 0.5
    stake = params.base
    doubles = 0
    for step, up in enumerate(outcomes, start=1):
        if stake > cash + EPS:
            return _empty(cash, max_dd, 0, 0, step - 1, hit, [], step)
        won = up == 1 if side_long else up == 0
        cash += stake if won else -stake
        peak, max_dd, hit = _mark(cash, peak, max_dd, hit, params.capital)
        if won and doubles < 3:
            stake *= 2.0
            doubles += 1
        else:
            stake = params.base
            doubles = 0
    return _empty(cash, max_dd, 0, 0, len(outcomes), hit, [], None)


def fit_stakes(
    long_amt: float,
    short_amt: float,
    cash: float,
    budget: float,
    base: float,
    favor_long: bool,
) -> tuple[float, float]:
    """Fund a proposal only if cash and the risk budget cover it.

    If the escalated proposal does not fit, freeze escalation and keep only
    base-sized legs that fit, favored side first. A leg is never partial-filled
    and is never left larger than cash.
    """
    long_amt = max(0.0, long_amt)
    short_amt = max(0.0, short_amt)
    if long_amt + short_amt <= budget + EPS and long_amt + short_amt <= cash + EPS:
        return long_amt, short_amt

    order = ("long", "short") if favor_long else ("short", "long")
    raw = {"long": long_amt, "short": short_amt}
    fitted = {"long": 0.0, "short": 0.0}
    used = 0.0
    for name in order:
        if raw[name] <= EPS:
            continue
        want = min(raw[name], base)
        if used + want <= budget + EPS and used + want <= cash + EPS:
            fitted[name] = want
            used += want
    return fitted["long"], fitted["short"]


def _recovery(debt: float, base: float) -> float:
    """Stake that clears lineage debt and nets one base if it wins alone."""
    return debt + base


def _leg(
    debt: float,
    streak: int,
    prev: float,
    params: LabParams,
) -> tuple[float, float, bool]:
    """Stake on the indebted side, stake aimed at the other side, and whether this is a split.

    On a split the first amount is alpha times the recovery target. The caller
    may aim that alpha share at the dominant side instead. A stake that opens
    a clear lineage is a new generation. Adding to a lineage that already has
    debt does not advance depth.
    """
    target = _recovery(debt, params.base)
    split = streak >= params.k or debt >= params.tau
    if split:
        return params.alpha * target, (1.0 - params.alpha) * target, True
    if prev > EPS:
        # Same escalation as a martingale, but never more than the recovery target.
        return min(2.0 * prev, target), 0.0, False
    return min(target, params.base), 0.0, False


def _aim_alpha(
    indebted_amt: float,
    other_amt: float,
    is_split: bool,
    indebted_long: bool,
    dominant_long: bool | None,
) -> tuple[float, float]:
    """Put a split's alpha share on the dominant side.

    `_leg` packs alpha onto the indebted side. When the dominant side is the
    other one, the two amounts swap. An unsplit double is left where it is,
    and so is a split that has no trend read.
    """
    if not is_split or dominant_long is None or indebted_long == dominant_long:
        return indebted_amt, other_amt
    return other_amt, indebted_amt


def run_branching(
    outcomes: list[int],
    params: LabParams,
    keep_trace: bool = False,
    bias: list[int | None] | None = None,
) -> PathResult:
    """Asymmetric long/short recovery with recursive collapse.

    A lineage that is not yet branching doubles toward debt+base. After k
    consecutive losses, or once debt reaches tau, that recovery is split:
    alpha goes to the dominant side when `bias` has a read, and otherwise
    stays on the indebted side. The rest opens or adds to the other side.
    Opening a clear lineage starts a new generation; adding to a lineage
    that already has debt does not. A generation above d_max is not opened.

    `bias` aligns with `outcomes`. `1` is an upward trend (dominant long),
    `0` is a downward trend (dominant short), and None keeps the `p` rule
    for that step. The fresh stake, the side funded first under the risk
    cap, and the alpha leg of a split follow that read.
    See module docstring for the expectancy limit.
    """
    if bias is not None and len(bias) != len(outcomes):
        raise ValueError(f"bias length {len(bias)} does not match {len(outcomes)} outcomes")
    cash = params.capital
    peak = cash
    max_dd = 0.0
    hit = False
    max_depth = 0
    resets = 0
    budget = params.risk_cap * params.capital
    long = Lineage()
    short = Lineage()
    trace: list[dict] = []
    open_dominant = ""

    def dominant_at(index: int) -> bool | None:
        if bias is None or index >= len(bias) or bias[index] is None:
            return None
        side = bias[index]
        if side not in (0, 1):
            raise ValueError(f"bias entries must be 1, 0, or None, got {side!r}")
        return side == 1

    def favor_of(dominant_long: bool | None) -> bool:
        if dominant_long is None:
            return params.p >= 0.5
        return dominant_long

    def root_amounts(dominant_long: bool | None) -> tuple[float, float, int, int]:
        if dominant_long is True:
            return params.base, 0.0, 0, 0
        if dominant_long is False:
            return 0.0, params.base, 0, 0
        if abs(params.p - 0.5) <= EPS:
            return params.base / 2.0, params.base / 2.0, 0, 0
        if params.p > 0.5:
            return params.base, 0.0, 0, 0
        return 0.0, params.base, 0, 0

    def apply_book(
        long_amt: float,
        short_amt: float,
        long_depth: int,
        short_depth: int,
        dominant_long: bool | None,
    ) -> None:
        nonlocal max_depth, open_dominant
        fitted_long, fitted_short = fit_stakes(
            long_amt, short_amt, cash, budget, params.base, favor_of(dominant_long)
        )
        total = fitted_long + fitted_short
        if total > cash + 1e-6 or total > budget + 1e-6:
            raise RuntimeError(
                f"unfunded book long={fitted_long} short={fitted_short} cash={cash} budget={budget}"
            )
        long.stake = fitted_long
        short.stake = fitted_short
        long.depth = long_depth if fitted_long > EPS or long.debt > EPS else 0
        short.depth = short_depth if fitted_short > EPS or short.debt > EPS else 0
        long.active = fitted_long > EPS
        short.active = fitted_short > EPS
        max_depth = max(max_depth, long.depth, short.depth)
        if dominant_long is True:
            open_dominant = "long"
        elif dominant_long is False:
            open_dominant = "short"
        else:
            open_dominant = ""

    def propose(
        prev_long: float,
        prev_short: float,
        just_long: bool,
        just_short: bool,
        dominant_long: bool | None,
    ) -> None:
        if long.debt <= EPS and short.debt <= EPS:
            apply_book(*root_amounts(dominant_long), dominant_long)
            return

        long_amt = 0.0
        short_amt = 0.0
        long_depth = long.depth
        short_depth = short.depth
        add_long = 0.0
        add_short = 0.0
        long_counter = 0.0
        short_counter = 0.0

        if long.debt > EPS:
            stay, counter, is_split = _leg(long.debt, long.streak, prev_long, params)
            long_amt, long_counter = _aim_alpha(stay, counter, is_split, True, dominant_long)
        elif just_long:
            # Collapse returns this lineage to a base stake. A spawn may add to it.
            long_amt = params.base
            long_depth = 0

        if short.debt > EPS:
            stay, counter, is_split = _leg(short.debt, short.streak, prev_short, params)
            short_amt, short_counter = _aim_alpha(stay, counter, is_split, False, dominant_long)
        elif just_short:
            short_amt = params.base
            short_depth = 0

        # A clear opposite lineage is a new child. An indebted one just receives stake.
        if long_counter > EPS:
            if short.debt <= EPS:
                child = long.depth + 1
                if child > params.d_max:
                    long_amt = min(_recovery(long.debt, params.base), params.base)
                else:
                    add_short += long_counter
                    short_depth = child
            else:
                add_short += long_counter
        if short_counter > EPS:
            if long.debt <= EPS:
                child = short.depth + 1
                if child > params.d_max:
                    short_amt = min(_recovery(short.debt, params.base), params.base)
                else:
                    add_long += short_counter
                    long_depth = child
            else:
                add_long += short_counter

        apply_book(long_amt + add_long, short_amt + add_short, long_depth, short_depth, dominant_long)

    apply_book(*root_amounts(dominant_at(0)), dominant_at(0))
    if long.stake + short.stake <= EPS and cash + EPS < params.base:
        return _empty(cash, max_dd, max_depth, resets, 0, hit, trace, 1)

    for step, up in enumerate(outcomes, start=1):
        settled_long = long.stake
        settled_short = short.stake
        depth_long = long.depth
        depth_short = short.depth
        if settled_long + settled_short > cash + 1e-6:
            raise RuntimeError(
                f"open stake {settled_long + settled_short} exceeds cash {cash} at step {step}"
            )

        just_long = False
        just_short = False
        if settled_long > EPS or settled_short > EPS:
            if up == 1:
                cash += settled_long - settled_short
                if settled_long > EPS:
                    long.debt -= settled_long
                    if long.debt < EPS:
                        long.debt = 0.0
                    long.streak = 0
                if settled_short > EPS:
                    short.debt += settled_short
                    short.streak += 1
            else:
                cash += settled_short - settled_long
                if settled_short > EPS:
                    short.debt -= settled_short
                    if short.debt < EPS:
                        short.debt = 0.0
                    short.streak = 0
                if settled_long > EPS:
                    long.debt += settled_long
                    long.streak += 1
            if cash < 0.0 and cash > -1e-6:
                cash = 0.0
            if cash < -1e-6:
                raise RuntimeError(f"cash went negative ({cash}) at step {step}")

            # Collapse a lineage once its settled win has cleared its debt.
            reset_flag = 0
            if settled_long > EPS and long.debt <= EPS:
                long.debt = 0.0
                long.streak = 0
                long.depth = 0
                long.active = False
                just_long = True
                resets += 1
                reset_flag = 1
            if settled_short > EPS and short.debt <= EPS:
                short.debt = 0.0
                short.streak = 0
                short.depth = 0
                short.active = False
                just_short = True
                resets += 1
                reset_flag = 1
            peak, max_dd, hit = _mark(cash, peak, max_dd, hit, params.capital)
        else:
            reset_flag = 0

        settled_dominant = open_dominant
        propose(settled_long, settled_short, just_long, just_short, dominant_at(step))
        # Ruin only when another bet is still required. The horizon itself is a stop.
        cannot_continue = (
            step < len(outcomes)
            and long.stake + short.stake <= EPS
            and cash + EPS < params.base
        )
        if keep_trace:
            trace.append(
                {
                    "step": step,
                    "outcome": "up" if up == 1 else "down",
                    "cash": round(cash, 6),
                    "long_stake": round(settled_long, 6),
                    "short_stake": round(settled_short, 6),
                    "long_debt": round(long.debt, 6),
                    "short_debt": round(short.debt, 6),
                    "long_depth": depth_long,
                    "short_depth": depth_short,
                    "reset": reset_flag,
                    "ruined": 1 if cannot_continue else 0,
                    "dominant": settled_dominant,
                }
            )
        if cannot_continue:
            return _empty(cash, max_dd, max_depth, resets, step, hit, trace, step + 1)

    return _empty(cash, max_dd, max_depth, resets, len(outcomes), hit, trace, None)


def run_strategies(
    outcomes: list[int],
    params: LabParams,
    keep_trace: bool = False,
) -> dict[str, PathResult]:
    """Paired run: the same outcomes feed every strategy."""
    return {
        "pure_martingale": run_pure_martingale(outcomes, params),
        "flat_kelly": run_kelly(outcomes, params),
        "paroli": run_paroli(outcomes, params),
        "branching": run_branching(outcomes, params, keep_trace=keep_trace),
    }
