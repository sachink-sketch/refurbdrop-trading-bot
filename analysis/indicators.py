import pandas as pd
import numpy as np


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add a comprehensive set of technical indicators to an OHLCV dataframe."""
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # --- Trend ---
    df["ema_9"] = close.ewm(span=9, adjust=False).mean()
    df["ema_21"] = close.ewm(span=21, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()
    df["sma_200"] = close.rolling(200).mean()

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # --- Momentum ---
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Stochastic %K/%D
    lowest_low = low.rolling(14).min()
    highest_high = high.rolling(14).max()
    df["stoch_k"] = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    # --- Volatility ---
    df["bb_mid"] = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * std20
    df["bb_lower"] = df["bb_mid"] - 2 * std20
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)

    # ATR
    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low - close.shift()).abs()
    df["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()

    # --- Volume ---
    df["vol_sma_20"] = volume.rolling(20).mean()
    df["vol_ratio"] = volume / df["vol_sma_20"].replace(0, np.nan)

    # OBV
    obv = [0]
    for i in range(1, len(df)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv.append(obv[-1] + volume.iloc[i])
        elif close.iloc[i] < close.iloc[i - 1]:
            obv.append(obv[-1] - volume.iloc[i])
        else:
            obv.append(obv[-1])
    df["obv"] = obv

    # --- Signals ---
    df["trend_up"] = (df["ema_9"] > df["ema_21"]) & (df["ema_21"] > df["ema_50"])
    df["trend_down"] = (df["ema_9"] < df["ema_21"]) & (df["ema_21"] < df["ema_50"])
    df["macd_bullish"] = (df["macd"] > df["macd_signal"]) & (df["macd_hist"] > 0)
    df["rsi_oversold"] = df["rsi"] < 30
    df["rsi_overbought"] = df["rsi"] > 70

    return df


def summarize_indicators(df: pd.DataFrame) -> dict:
    """Return a concise snapshot of the latest indicator values. NaN-safe."""
    import math

    def safe(val, default):
        try:
            v = float(val)
            return default if math.isnan(v) or math.isinf(v) else v
        except Exception:
            return default

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    price = safe(latest["close"], 0)
    prev_price = safe(prev["close"], price)
    change_pct = ((price - prev_price) / prev_price * 100) if prev_price else 0.0

    ema_9  = safe(latest.get("ema_9"),  0)
    ema_21 = safe(latest.get("ema_21"), 0)
    ema_50 = safe(latest.get("ema_50"), 0)

    return {
        "price": round(price, 6),
        "change_pct": round(change_pct, 3),
        "rsi": round(safe(latest.get("rsi"), 50), 2),
        "macd": round(safe(latest.get("macd"), 0), 6),
        "macd_signal": round(safe(latest.get("macd_signal"), 0), 6),
        "macd_bullish": bool(latest.get("macd_bullish", False)),
        "ema_9": round(ema_9, 6),
        "ema_21": round(ema_21, 6),
        "ema_50": round(ema_50, 6),
        # Whether price itself is above each EMA (more useful for scalping than EMA stacking)
        "price_above_ema9":  price > ema_9  if ema_9  else False,
        "price_above_ema21": price > ema_21 if ema_21 else False,
        "price_above_ema50": price > ema_50 if ema_50 else False,
        "bb_pct": round(safe(latest.get("bb_pct"), 0.5), 4),
        "bb_width": round(safe(latest.get("bb_width"), 0), 4),
        "atr": round(safe(latest.get("atr"), 0), 6),
        "vol_ratio": round(safe(latest.get("vol_ratio"), 1), 3),
        "stoch_k": round(safe(latest.get("stoch_k"), 50), 2),
        "stoch_d": round(safe(latest.get("stoch_d"), 50), 2),
        "trend_up": bool(latest.get("trend_up", False)),    # strict EMA stack (ema9>ema21>ema50)
        "trend_down": bool(latest.get("trend_down", False)),
        "obv_rising": bool(safe(latest.get("obv"), 0) > safe(prev.get("obv"), 0)),
    }
