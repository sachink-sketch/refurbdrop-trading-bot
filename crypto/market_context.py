"""Market-wide context: Crypto Fear & Greed Index (free API, cached)."""
import time
import requests
from utils.logger import logger

_CACHE = {"t": 0.0, "v": {"value": 50, "label": "Neutral"}}
_TTL = 600


def get_fear_greed() -> dict:
    if time.time() - _CACHE["t"] < _TTL:
        return _CACHE["v"]
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        e = r.json()["data"][0]
        _CACHE["v"] = {"value": int(e["value"]), "label": e["value_classification"]}
        _CACHE["t"] = time.time()
        logger.info(f"[FNG] Fear & Greed: {_CACHE['v']['value']} ({_CACHE['v']['label']})")
    except Exception as ex:
        logger.debug(f"[FNG] fetch failed: {ex}")
        _CACHE["t"] = time.time() - (_TTL - 60)  # retry in 1 min, keep last known value
    return _CACHE["v"]
