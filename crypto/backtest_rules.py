"""Backtest the rule-based swing strategy on public 1h history. Usage: python crypto/backtest_rules.py [days]"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import requests
import pandas as pd
from analysis.indicators import add_indicators
from crypto import rules_strategy as rs

PAIRS = ["BTC/USDT", "ETH/USDT", "LINK/USDT", "XRP/USDT", "LTC/USDT", "ADA/USDT"]
SPREADS = [0.0, 0.004, 0.019]


def fetch(pair: str, days: int) -> pd.DataFrame:
    """Public Binance.US klines (no key, no ccxt needed)."""
    since = int((time.time() - days * 86400) * 1000)
    rows = []
    while True:
        r = requests.get(
            "https://api.binance.us/api/v3/klines",
            params={"symbol": pair.replace("/", ""), "interval": "1h", "startTime": since, "limit": 1000},
            timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows += [b[:6] for b in batch]
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        time.sleep(0.3)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df.drop_duplicates("timestamp").set_index("timestamp")


def simulate(df: pd.DataFrame, spread: float, p: rs.Params = rs.DEFAULT) -> list[float]:
    """Net return per trade (fraction), buying at ask and selling at bid (half spread each side)."""
    trades, i, n = [], 2, len(df)
    while i < n - 1:
        if not rs.entry_signal(df, i, p):
            i += 1
            continue
        stop_pct, target_pct = rs.levels(df, i, p)
        entry = df["close"].iloc[i] * (1 + spread / 2)
        peak, exit_px, j = entry, None, i + 1
        while j < n:
            bar = df.iloc[j]
            stop = entry * (1 - stop_pct)
            if peak >= entry * (1 + stop_pct * p.breakeven_at_stop_mult):
                stop = max(stop, entry * (1 + 0.2 * stop_pct))
            if bar["low"] <= stop:
                exit_px = min(bar["open"], stop)
                break
            if bar["high"] >= entry * (1 + target_pct):
                exit_px = max(bar["open"], entry * (1 + target_pct))
                break
            peak = max(peak, bar["high"])
            if j - i >= p.max_hold_hours:
                exit_px = bar["close"]
                break
            j += 1
        if exit_px is None:
            break   # still open at end of data
        trades.append(exit_px * (1 - spread / 2) / entry - 1)
        i = j + 1
    return trades


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    data = {}
    for pair in PAIRS:
        df = add_indicators(fetch(pair, days))
        data[pair] = df
        bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
        print(f"{pair}: {len(df)} bars, buy&hold {bh:+.1%}")
    print()
    for spread in SPREADS:
        print(f"=== round-trip spread {spread:.1%} ===")
        all_t = []
        for pair in PAIRS:
            t = simulate(data[pair], spread)
            all_t += t
            if t:
                w = sum(1 for x in t if x > 0)
                print(f"  {pair:10s} trades {len(t):3d}  win {w/len(t):4.0%}  avg {sum(t)/len(t):+.2%}  sum {sum(t):+.1%}")
            else:
                print(f"  {pair:10s} no trades")
        if all_t:
            wins = [x for x in all_t if x > 0]
            losses = [x for x in all_t if x <= 0]
            pf = (sum(wins) / -sum(losses)) if losses and sum(losses) else float("inf")
            print(f"  ALL: trades {len(all_t)}  win {len(wins)/len(all_t):.0%}  avg {sum(all_t)/len(all_t):+.2%}  "
                  f"profit factor {pf:.2f}  total {sum(all_t):+.1%}")
        print()


if __name__ == "__main__":
    main()
