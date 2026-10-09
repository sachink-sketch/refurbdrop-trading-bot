"""Tracks how Claude's BUY signals actually perform, bucketed by confidence."""
import json
import os

_FILE = os.path.join(os.path.dirname(__file__), "../logs/signal_stats.json")
_BUCKETS = [("<65%", 0.0, 0.65), ("65-74%", 0.65, 0.75), ("75%+", 0.75, 1.01)]


class SignalTracker:
    def __init__(self):
        self._open: dict[str, float] = {}
        self._closed: list[dict] = []
        try:
            with open(_FILE) as f:
                d = json.load(f)
            self._open = d.get("open", {})
            self._closed = d.get("closed", [])[-300:]
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(_FILE), exist_ok=True)
            with open(_FILE, "w") as f:
                json.dump({"open": self._open, "closed": self._closed[-300:]}, f)
        except Exception:
            pass

    def record_entry(self, pair: str, confidence: float):
        self._open[pair] = confidence
        self._save()

    def record_exit(self, pair: str, pnl_pct: float):
        conf = self._open.pop(pair, None)
        if conf is not None:
            self._closed.append({"pair": pair, "conf": conf, "pnl": pnl_pct})
        self._save()

    def summary(self) -> dict:
        out = {}
        for label, lo, hi in _BUCKETS:
            rows = [t for t in self._closed if lo <= t["conf"] < hi]
            wins = sum(1 for t in rows if t["pnl"] > 0)
            out[label] = {
                "trades": len(rows),
                "wins": wins,
                "avg_pnl": round(sum(t["pnl"] for t in rows) / len(rows) * 100, 3) if rows else 0.0,
            }
        return out

    def prompt_summary(self) -> str:
        s = self.summary()
        if sum(v["trades"] for v in s.values()) < 5:
            return ""
        parts = [
            f"{k}: {v['wins']}/{v['trades']} wins, avg {v['avg_pnl']:+.2f}%"
            for k, v in s.items() if v["trades"]
        ]
        return "YOUR BUY ACCURACY BY CONFIDENCE: " + " | ".join(parts)
