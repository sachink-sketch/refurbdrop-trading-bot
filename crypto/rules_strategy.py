"""Rule-based swing strategy on 1-hour candles. No LLM, no API cost.

Long-only "buy the pullback in an uptrend". Built for a wide-spread venue (Robinhood ~1.9% round trip),
so targets are large and holds are hours to days. Shared by the backtest and the live paper engine.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    rsi_lo: float = 40.0
    rsi_hi: float = 58.0
    ema21_band: float = 0.015      # price must be within 1.5% of EMA21 (pullback zone)
    stop_atr_mult: float = 2.5     # stop distance = 2.5 x hourly ATR ...
    stop_min: float = 0.02         # ... clamped to 2-4%
    stop_max: float = 0.04
    target_rr: float = 2.5         # target = 2.5 x stop distance (>= 5%)
    breakeven_at_stop_mult: float = 1.0   # once +1x stop distance, lift stop to entry + 0.2x
    max_hold_hours: int = 72
    min_target_vs_spread: float = 2.5     # target must be >= 2.5x round-trip spread


DEFAULT = Params()


def entry_signal(df, i: int, p: Params = DEFAULT) -> bool:
    """True if candle i (already closed, indicators precomputed with add_indicators) is a pullback buy."""
    if i < 2:
        return False
    r, prev = df.iloc[i], df.iloc[i - 1]
    for col in ("ema_21", "ema_50", "rsi", "macd_hist", "atr"):
        if r[col] != r[col] or prev["macd_hist"] != prev["macd_hist"]:   # NaN guard
            return False
    if not (r["ema_21"] > r["ema_50"] and r["close"] > r["ema_50"]):
        return False
    if not (p.rsi_lo <= r["rsi"] <= p.rsi_hi):
        return False
    if abs(r["close"] - r["ema_21"]) / r["ema_21"] > p.ema21_band:
        return False
    return r["macd_hist"] > prev["macd_hist"]   # momentum turning up


def levels(df, i: int, p: Params = DEFAULT) -> tuple[float, float]:
    """(stop_pct, target_pct) as fractions of the entry price."""
    r = df.iloc[i]
    atr_pct = r["atr"] / r["close"] if r["close"] else 0.0
    stop = min(max(p.stop_atr_mult * atr_pct, p.stop_min), p.stop_max)
    return stop, stop * p.target_rr


def check_exit(entry: float, stop_pct: float, target_pct: float, peak: float, price: float,
               hours_held: float, p: Params = DEFAULT) -> str | None:
    """Exit reason or None. `price` is what we could sell at now (the bid). `peak` is the highest price seen."""
    stop = entry * (1 - stop_pct)
    if peak >= entry * (1 + stop_pct * p.breakeven_at_stop_mult):
        stop = max(stop, entry * (1 + 0.2 * stop_pct))
    if price <= stop:
        return "STOP" if stop < entry else "BREAKEVEN"
    if price >= entry * (1 + target_pct):
        return "TARGET"
    if hours_held >= p.max_hold_hours:
        return "TIME"
    return None
