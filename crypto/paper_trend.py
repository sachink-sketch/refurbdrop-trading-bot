"""Forward paper test of slow trend strategies. Fake money, public data, no broker login, never trades.

Run it as often as you like (a scheduled task runs it hourly). It is stateless: each run recomputes the strategies
from daily history and replays them from the inception date, so a day the computer was off is never lost.
Each strategy starts at 100 on the inception date and pays the same 1.9% round-trip cost as Robinhood.
"""
import sys, os, json
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
from crypto import strategy_lab as L

ROUND_TRIP_COST = 0.019
START_FILE = os.path.join(os.path.dirname(__file__), "../logs/paper_trend_start.txt")
OUT_FILE = os.path.join(os.path.dirname(__file__), "../logs/paper_trend.json")
STRATEGIES = {
    "Trend: 20/50 EMA cross": lambda data: L.weights_per_coin(L.sig_dual_ema, data),
    "Rotation: top-2 momentum": L.weights_rotation,
    "Buy & hold (benchmark)": lambda data: L.weights_per_coin(L.sig_hold, data),
}


def inception(today: pd.Timestamp) -> pd.Timestamp:
    if os.path.exists(START_FILE):
        return pd.Timestamp(open(START_FILE).read().strip())
    with open(START_FILE, "w") as f:
        f.write(str(today.date()))
    return today


def closed_daily(sym: str, today: pd.Timestamp) -> pd.DataFrame:
    d = L.load(sym, ttl=3000)          # refresh at most hourly so a new daily close is picked up promptly
    return d[d.index < today]          # drop today's unfinished candle


def replay(w: pd.DataFrame, ret: pd.DataFrame, start: pd.Timestamp):
    """Equity (start of inception day = 100) paying the round-trip cost on every trade, incl. the first buy."""
    held = w.shift(1).fillna(0.0)
    sl = held.loc[held.index >= start]
    r = ret.loc[sl.index]
    turnover = sl.diff().abs()
    turnover.iloc[0] = sl.iloc[0].abs()                      # initial purchase from cash
    port = (sl * r).sum(axis=1) - turnover.sum(axis=1) * ROUND_TRIP_COST / 2
    eq = 100 * (1 + port).cumprod()
    return eq, sl


def main():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    start = inception(today)
    data = {s: closed_daily(s, today) for s in L.PAIRS}
    idx = sorted(set.intersection(*[set(d.index) for d in data.values()]))
    data = {s: d.loc[idx] for s, d in data.items()}
    ret = pd.DataFrame({s: d["close"].pct_change() for s, d in data.items()}).fillna(0.0)
    last_closed = pd.Timestamp(idx[-1])

    out = {"started": str(start.date()), "through": str(last_closed.date()), "cost_pct": ROUND_TRIP_COST * 100,
           "updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "strategies": {}}
    for name, fn in STRATEGIES.items():
        w = fn(data)
        now_w = w.iloc[-1]
        changed = w.diff().abs().sum(axis=1) > 1e-9
        last_change = str(w.index[changed][-1].date()) if changed.any() else None
        holding = {s: round(float(v) * 100) for s, v in now_w.items() if v > 1e-9}
        entry = {"name": name, "holding": holding or {"CASH": 100}, "last_change": last_change}
        if start <= last_closed:
            # earns from the first fully closed day on/after inception
            eq, sl = replay(w, ret, start + pd.Timedelta(days=0))
            if len(eq):
                curve = pd.concat([pd.Series([100.0]), eq.reset_index(drop=True)], ignore_index=True)   # include the start
                entry.update(
                    value=round(float(eq.iloc[-1]), 2),
                    ret_pct=round(float(eq.iloc[-1] - 100), 2),
                    worst_drop_pct=round(float((curve / curve.cummax() - 1).min() * 100), 2),
                    days=int(len(eq)),
                    series={str(d.date()): round(float(v), 2) for d, v in eq.tail(120).items()},
                )
        entry.setdefault("value", 100.0)
        entry.setdefault("ret_pct", 0.0)
        entry.setdefault("worst_drop_pct", 0.0)
        entry.setdefault("days", 0)
        out["strategies"][f"s{len(out['strategies']) + 1}"] = entry    # Firebase keys can't contain "/" or "."

    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=2)
    try:
        import requests, firebase_writer as fb
        if fb._enabled:
            url = f"{fb._db_url}/paper_trend.json" + (f"?auth={fb._secret}" if fb._secret else "")
            r = requests.put(url, json=out, timeout=10)
            if r.status_code != 200:
                print(f"firebase push failed: HTTP {r.status_code} {r.text[:150]}")
    except Exception as e:
        print(f"firebase push failed: {e}")
    for e in out["strategies"].values():
        print(f"{e['name']:28s} value {e['value']:>7.2f}  return {e['ret_pct']:+.2f}%  worst drop {e['worst_drop_pct']:.2f}%  "
              f"days {e['days']}  holding {e['holding']}")


if __name__ == "__main__":
    main()
