"""Strategy lab: test simple, well-known strategies on ~2.7y of daily crypto data at several trading costs.

Usage: python crypto/strategy_lab.py

Honesty rules baked in:
- Parameters are fixed in advance (textbook values), never tuned to the results.
- Signals use only data up to the close of day t and earn day t+1 (no lookahead).
- Every strategy is shown at several round-trip costs, plus a first-half / second-half split.
- Cash earns 0. Costs = round-trip (spread + fees), charged half on each side of every trade.
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd
import requests

PAIRS = ["BTC", "ETH", "LINK", "XRP", "LTC", "ADA"]
COSTS = [0.0, 0.003, 0.006, 0.010, 0.019]       # round-trip: 0%, 0.3%, 0.6%, 1.0%, 1.9% (Robinhood-like)
CACHE = os.path.join(os.path.dirname(__file__), "../logs/lab_cache")


def load(sym: str, ttl: int = 86400) -> pd.DataFrame:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{sym}_1d.csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    r = requests.get(
        "https://api.binance.us/api/v3/klines",
        params={"symbol": f"{sym}USDT", "interval": "1d", "limit": 1000}, timeout=20,
    )
    r.raise_for_status()
    df = pd.DataFrame([b[:6] for b in r.json()], columns=["t", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("t"), unit="ms").dt.normalize()
    df = df.astype(float)
    df.to_csv(path)
    return df


# ---- signals: each returns a Series of 0/1 (decided at the close of day t) ----
def sig_hold(d):            return pd.Series(1.0, index=d.index)
def sig_ema(d, n=50):       return (d["close"] > d["close"].ewm(span=n, adjust=False).mean()).astype(float)
def sig_sma200(d):          return (d["close"] > d["close"].rolling(200).mean()).astype(float)
def sig_dual_ema(d):        return (d["close"].ewm(span=20, adjust=False).mean() > d["close"].ewm(span=50, adjust=False).mean()).astype(float)


def sig_donchian(d, enter=20, exit_=10):
    up = d["high"].rolling(enter).max().shift(1)
    dn = d["low"].rolling(exit_).min().shift(1)
    state, out = 0.0, []
    for c, u, l in zip(d["close"], up, dn):
        if state == 0.0 and u == u and c > u:
            state = 1.0
        elif state == 1.0 and l == l and c < l:
            state = 0.0
        out.append(state)
    return pd.Series(out, index=d.index)


def weights_per_coin(sig_fn, data):
    sigs = pd.DataFrame({s: sig_fn(d) for s, d in data.items()})
    return sigs / len(data)                      # equal weight, remainder in cash


def weights_rotation(data, top=2, look=30, trend=100, every=7):
    close = pd.DataFrame({s: d["close"] for s, d in data.items()})
    mom = close.pct_change(look)
    ok = close > close.rolling(trend).mean()
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    cur = pd.Series(0.0, index=close.columns)
    for i, day in enumerate(close.index):
        if i % every == 0:
            ranked = mom.loc[day].where(ok.loc[day] & (mom.loc[day] > 0)).dropna().nlargest(top)
            cur = pd.Series(0.0, index=close.columns)
            if len(ranked):
                cur[ranked.index] = 1.0 / top
        w.loc[day] = cur
    return w


STRATEGIES = {
    "Buy & hold (equal weight)":        lambda data: weights_per_coin(sig_hold, data),
    "Trend: price > 50-day EMA":        lambda data: weights_per_coin(sig_ema, data),
    "Trend: price > 200-day SMA":       lambda data: weights_per_coin(sig_sma200, data),
    "Trend: 20/50 EMA cross":           lambda data: weights_per_coin(sig_dual_ema, data),
    "Breakout: 20-day high / 10-day low": lambda data: weights_per_coin(sig_donchian, data),
    "Rotation: top-2 momentum, weekly": weights_rotation,
}


def backtest(w: pd.DataFrame, ret: pd.DataFrame, cost: float, mask=None):
    held = w.shift(1).fillna(0.0)                                   # decided yesterday, earns today
    turnover = held.diff().abs().fillna(held.abs())
    port = (held * ret).sum(axis=1) - turnover.sum(axis=1) * cost / 2
    if mask is not None:
        port, held, turnover = port[mask], held[mask], turnover[mask]
    eq = (1 + port).cumprod()
    days = len(port)
    total = eq.iloc[-1] - 1
    cagr = eq.iloc[-1] ** (365 / days) - 1
    dd = (eq / eq.cummax() - 1).min()
    entries = int((held.diff() > 1e-9).sum().sum())
    return dict(total=total, cagr=cagr, maxdd=dd, entries=entries, exposure=held.sum(axis=1).mean())


def main():
    data = {s: load(s) for s in PAIRS}
    idx = sorted(set.intersection(*[set(d.index) for d in data.values()]))
    data = {s: d.loc[idx] for s, d in data.items()}
    ret = pd.DataFrame({s: d["close"].pct_change() for s, d in data.items()}).fillna(0.0)
    warm = 200                                                        # same start for all (SMA200 warm-up)
    first, last = idx[warm], idx[-1]
    mask = pd.Series(ret.index >= first, index=ret.index)
    half = idx[warm + (len(idx) - warm) // 2]
    h1 = pd.Series((ret.index >= first) & (ret.index < half), index=ret.index)
    h2 = pd.Series(ret.index >= half, index=ret.index)

    lines = [f"Data: {len(PAIRS)} coins {', '.join(PAIRS)} | {first.date()} to {last.date()} ({(last-first).days} days) | cash earns 0%",
             f"Coin basket moved: {', '.join(f'{s} {data[s]['close'].loc[last]/data[s]['close'].loc[first]-1:+.0%}' for s in PAIRS)}", ""]
    for name, fn in STRATEGIES.items():
        w = fn(data)
        lines.append(f"== {name}")
        lines.append(f"   {'round-trip cost':>16} {'total':>9} {'per year':>9} {'worst drop':>11} {'1st half':>9} {'2nd half':>9} {'entries':>8} {'in market':>10}")
        for c in COSTS:
            a = backtest(w, ret, c, mask)
            b1 = backtest(w, ret, c, h1)
            b2 = backtest(w, ret, c, h2)
            lines.append(f"   {c:>15.1%} {a['total']:>+9.0%} {a['cagr']:>+9.0%} {a['maxdd']:>11.0%} {b1['total']:>+9.0%} {b2['total']:>+9.0%} {a['entries']:>8d} {a['exposure']:>10.0%}")
        lines.append("")
    out = "\n".join(lines)
    print(out)
    with open(os.path.join(os.path.dirname(__file__), "../logs/strategy_lab_results.txt"), "w", encoding="utf-8") as f:
        f.write(out)


if __name__ == "__main__":
    main()
