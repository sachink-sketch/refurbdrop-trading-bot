"""Push live bot state to Firebase Realtime Database so the web dashboard stays current."""
import os, math, threading
from datetime import datetime
from typing import Optional
from pathlib import Path

# Load .env from the project root (works whether imported from bot or run standalone)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

_db_url: Optional[str] = None
_secret: Optional[str] = None
_enabled = False

try:
    import requests as _req
    _REQUESTS = True
except ImportError:
    _REQUESTS = False


def init():
    global _db_url, _secret, _enabled
    _db_url  = os.getenv("FIREBASE_DATABASE_URL", "").rstrip("/")
    _secret  = os.getenv("FIREBASE_SECRET", "")        # Database secret (legacy) OR leave blank for rules-open DB
    if _db_url and _REQUESTS:
        _enabled = True


def _put(path: str, data: dict):
    if not _enabled:
        return
    url = f"{_db_url}/{path}.json"
    if _secret:
        url += f"?auth={_secret}"
    try:
        _req.put(url, json=data, timeout=5)
    except Exception:
        pass  # Never crash the bot over a dashboard write


def _safe(v):
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
    except TypeError:
        pass
    return v


def push_status(
    portfolio_total: float,
    session_pnl_pct: float,
    session_pnl_usd: float,
    cycle: int,
    daily_trades: int = 0,
    win_rate: Optional[float] = None,
    max_trades: int = 8,
):
    _put("status", {
        "max_trades":      max_trades,
        "portfolio_total": _safe(portfolio_total),
        "session_pnl_pct": _safe(session_pnl_pct),
        "session_pnl_usd": _safe(session_pnl_usd),
        "cycle":           cycle,
        "daily_trades":    daily_trades,
        "win_rate":        _safe(win_rate),
        "last_updated":    datetime.now().strftime("%H:%M:%S"),
    })


def push_positions(positions: dict, net_pnl: Optional[dict] = None):
    """positions: {pair -> CryptoPosition or stock Position}; net_pnl overrides P&L with the sell-now value."""
    data = {}
    for pair, pos in positions.items():
        key = pair.replace("/", "-")
        pnl = (net_pnl or {}).get(pair, getattr(pos, "unrealized_pnl_pct", None))
        entry = getattr(pos, "avg_entry", getattr(pos, "average_buy_price", None))
        current = getattr(pos, "current_price", None)
        qty = getattr(pos, "qty", getattr(pos, "quantity", None))
        data[key] = {
            "pair":     pair,
            "entry":    _safe(float(entry))    if entry    is not None else None,
            "current":  _safe(float(current))  if current  is not None else None,
            "pnl_pct":  _safe(float(pnl))      if pnl      is not None else None,
            "qty":      _safe(float(qty))       if qty      is not None else None,
            "mins_held": None,
        }
    _put("positions", data)


def push_signals(signals: list):
    """signals: list of {pair, action, confidence, reason}"""
    data = {}
    for s in signals:
        pair_key = s.get("pair", "").replace("/", "-")
        data[pair_key] = {
            "pair":       s.get("pair"),
            "action":     s.get("action"),
            "confidence": s.get("confidence"),
            "reason":     s.get("reason", "")[:100],
            "spread_pct": s.get("spread_pct"),
            "sl_pct":     s.get("sl_pct"),
            "tp_pct":     s.get("tp_pct"),
        }
    _put("signals", data)


def push_trade_event(event_type: str, pair: str, price: float, pnl_pct: Optional[float] = None):
    """Log a trade event (BUY / SELL / TAKE PROFIT / STOP LOSS / TRAILING STOP / TIME EXIT)."""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    key = ts.replace(":", "-").replace("T", "_")
    _put(f"trade_events/{key}", {
        "type":    event_type,
        "pair":    pair,
        "price":   _safe(price),
        "pnl_pct": _safe(pnl_pct),
        "time":    ts,
    })


def push_equity(total: float):
    """One equity-curve point per cycle; keys sort chronologically."""
    key = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _put(f"equity/{key}", {"t": datetime.now().strftime("%m/%d %H:%M"), "v": _safe(round(total, 2))})


def push_market(fear_greed: dict):
    _put("market", {"fng_value": fear_greed.get("value"), "fng_label": fear_greed.get("label")})


def push_accuracy(summary: dict):
    _put("accuracy", summary)


def push_async(fn, *args, **kwargs):
    """Fire-and-forget Firebase write so it never blocks the bot."""
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()


init()
