"""Time-of-day study: does crypto behave differently overnight (Asia open) than during US hours, and is there an
edge in selling at night? Analysis only - never trades.

Usage: python crypto/timeofday.py [days]     (default 730 days of hourly bars)

Inputs: public hourly history (6 coins, equal-weight basket), plus logs/quotes_log.csv (Robinhood's real
bid/ask, recorded by the bot every ~2 minutes) once enough hours have been collected.
Times are shown in US Eastern. Costs: Robinhood round trip is ~1.9% (measured).
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd
from crypto.backtest_rules import fetch

TZ = "America/New_York"
COINS = ["BTC", "ETH", "LINK", "XRP", "LTC", "ADA"]
COST = 0.019
CACHE = os.path.join(os.path.dirname(__file__), "../logs/lab_cache")
QUOTES = os.path.join(os.path.dirname(__file__), "../logs/quotes_log.csv")
SESSIONS = [("Asia night   20:00-03:00 ET", [20, 21, 22, 23, 0, 1, 2]),
            ("Europe morn  03:00-09:00 ET", [3, 4, 5, 6, 7, 8]),
            ("US day       09:00-16:00 ET", [9, 10, 11, 12, 13, 14, 15]),
            ("US evening   16:00-20:00 ET", [16, 17, 18, 19])]


def hourly(sym: str, days: int) -> pd.DataFrame:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{sym}_1h_{days}.csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 6 * 3600:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    df = fetch(f"{sym}/USDT", days)
    df.to_csv(path)
    return df


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std() / np.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else 0.0


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 730
    frames = {s: hourly(s, days) for s in COINS}
    ret = pd.DataFrame({s: d["close"] / d["open"] - 1 for s, d in frames.items()}).dropna()
    vol = pd.DataFrame({s: d["volume"] for s, d in frames.items()}).reindex(ret.index)
    loc = ret.index.tz_localize("UTC").tz_convert(TZ)
    df = pd.DataFrame({"r": ret.mean(axis=1).values, "lh": loc.hour, "ld": loc.date}, index=ret.index)
    df["volshare"] = (vol.div(vol.groupby(df["ld"].values).transform("sum")).mean(axis=1)).values
    df["P"] = (1 + df["r"]).cumprod()
    out = [f"TIME-OF-DAY STUDY | {len(df):,} hourly bars, {df.index[0].date()} to {df.index[-1].date()} | equal-weight basket of "
           f"{', '.join(COINS)} | times in US Eastern | round-trip cost {COST:.1%}", ""]

    # 1. hour-by-hour behavior
    g = df.groupby("lh")
    tbl = pd.DataFrame({"mean_bps": g["r"].mean() * 1e4, "t": g["r"].apply(tstat), "up": g["r"].apply(lambda x: (x > 0).mean()),
                        "move_bps": g["r"].apply(lambda x: x.abs().mean() * 1e4), "vol": g["volshare"].mean() * 100})
    out.append("1) HOUR BY HOUR (ET): average hourly return, how often up, typical size of a move, share of the day's volume")
    out.append(f"   {'hour':>5} {'avg ret':>9} {'t-stat':>7} {'% up':>6} {'avg move':>9} {'volume':>7}")
    for h, r in tbl.iterrows():
        out.append(f"   {h:02d}:00 {r.mean_bps:>+7.1f}bp {r.t:>7.1f} {r.up:>6.0%} {r.move_bps:>7.0f}bp {r.vol:>6.1f}%")
    out.append("   (a t-stat needs to be beyond about +/-3 to mean anything when 24 hours are compared)")
    out.append("")

    # 2. sessions
    out.append("2) SESSIONS: average return PER HOUR inside each window, and how big the swings are")
    for name, hrs in SESSIONS:
        x = df[df["lh"].isin(hrs)]["r"]
        out.append(f"   {name}: {x.mean()*1e4:>+5.1f} bp/hour  t={tstat(x):>5.1f}  avg move {x.abs().mean()*1e4:>4.0f} bp  "
                   f"=> about {x.mean()*1e4*len(hrs):>+5.0f} bp per window per day")
    out.append("")

    # 3. typical shape of the day: where price tends to sit relative to its own daily average
    rel = df["P"] / df.groupby("ld")["P"].transform("mean") - 1
    shape = rel.groupby(df["lh"]).mean() * 100
    hi, lo = shape.sort_values(ascending=False).head(3), shape.sort_values().head(3)
    out.append("3) PRICE LEVEL BY HOUR: typical price vs. that day's average")
    out.append("   highest hours: " + ", ".join(f"{h:02d}:00 ({v:+.2f}%)" for h, v in hi.items()))
    out.append("   lowest hours:  " + ", ".join(f"{h:02d}:00 ({v:+.2f}%)" for h, v in lo.items()))
    out.append(f"   gap between typical high and low hour: {shape.max()-shape.min():.2f}%  vs. {COST:.1%} cost of buying and selling")
    out.append("")

    # 4. buy at hour X, sell K hours later
    lr = np.log1p(df["r"])
    half = df.index[len(df) // 2]
    out.append("4) BUY AT ONE HOUR, SELL K HOURS LATER (before costs). Best and worst start hours; one sample per day")
    for k in (8, 12):
        fwd = np.expm1(lr.rolling(k).sum().shift(-(k - 1)))
        rows = []
        for h in range(24):
            s = fwd[df["lh"] == h].dropna()
            a, b = s[s.index < half], s[s.index >= half]
            rows.append((h, s.mean() * 100, tstat(s), (s > 0).mean(), a.mean() * 100, b.mean() * 100))
        rows.sort(key=lambda r: r[1])
        out.append(f"   hold {k} hours:   start hour | avg gain | t-stat | days up | 1st half | 2nd half")
        for tag, sel in (("best ", rows[-3:][::-1]), ("worst", rows[:3])):
            for h, m, t, up, m1, m2 in sel:
                out.append(f"     {tag} {h:02d}:00 -> {(h+k)%24:02d}:00 | {m:>+6.2f}% | {t:>6.1f} | {up:>6.0%} | {m1:>+6.2f}% | {m2:>+6.2f}%")
    out.append(f"   to be worth doing, a window must average well above {COST:.1%}, and the 1st and 2nd halves must agree")
    out.append("")

    # 5. night vs day accrual
    night = [20, 21, 22, 23, 0, 1, 2, 3]
    d_r = np.log1p(df["r"]).groupby(df["lh"].isin(night)).sum() / df["ld"].nunique()
    out.append("5) WHERE THE RETURN COMES FROM, per day on average (sum of hourly returns)")
    out.append(f"   night 20:00-04:00 ET: {np.expm1(d_r.get(True, 0))*100:+.3f}% per day | day 04:00-20:00 ET: {np.expm1(d_r.get(False, 0))*100:+.3f}% per day")
    out.append("")

    # 6. live Robinhood spread by hour (real data collected by the bot)
    out.append("6) ROBINHOOD'S REAL BID/ASK SPREAD BY HOUR (from the bot's own quote log)")
    if os.path.exists(QUOTES):
        q = pd.read_csv(QUOTES, parse_dates=["utc"])
        q["spread"] = (q["ask"] - q["bid"]) / ((q["ask"] + q["bid"]) / 2)
        hours = (q["utc"].max() - q["utc"].min()).total_seconds() / 3600
        q["lh"] = q["utc"].dt.tz_localize("UTC").dt.tz_convert(TZ).dt.hour
        out.append(f"   collected {len(q):,} quotes over {hours:.1f} hours (since {q['utc'].min()} UTC)")
        if hours >= 1:
            sp = q.groupby("lh")["spread"].agg(["mean", "count"])
            out.append("   hour(ET): " + "  ".join(f"{h:02d}:{r['mean']*100:.2f}%" for h, r in sp.iterrows()))
            out.append(f"   overall spread {q['spread'].mean():.2%}; lowest hour {sp['mean'].idxmin():02d}:00 ({sp['mean'].min():.2%}), "
                       f"highest hour {sp['mean'].idxmax():02d}:00 ({sp['mean'].max():.2%})")
        if hours < 48:
            out.append(f"   NOT ENOUGH DATA YET: only {hours:.0f} of the 48+ hours needed. No conclusions about spread timing.")
    else:
        out.append("   no quote log yet")
    text = "\n".join(out)
    print(text)
    with open(os.path.join(os.path.dirname(__file__), "../logs/timeofday_report.txt"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
