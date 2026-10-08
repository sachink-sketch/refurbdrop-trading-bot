"""Live crypto exchange via ccxt — supports Binance, Coinbase, Kraken."""
import ccxt
import pandas as pd
from crypto.exchanges.base_exchange import BaseCryptoExchange, CryptoPosition, CryptoOrder
from utils.logger import logger


EXCHANGE_MAP = {
    "BINANCE":    ccxt.binance,
    "BINANCEUS":  ccxt.binanceus,
    "COINBASE":   ccxt.coinbase,
    "KRAKEN":     ccxt.kraken,
}


class LiveCryptoExchange(BaseCryptoExchange):
    paper = False

    def __init__(self, exchange_id: str, api_key: str, api_secret: str, passphrase: str = ""):
        cls = EXCHANGE_MAP.get(exchange_id.upper())
        if not cls:
            raise ValueError(f"Unsupported exchange: {exchange_id}. Use BINANCE, COINBASE, or KRAKEN.")
        params = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
        if passphrase:
            params["password"] = passphrase
        self._exchange = cls(params)
        self._exchange_id = exchange_id.upper()
        logger.info(f"Connected to {self._exchange_id}")

    def get_ohlcv(self, pair: str, timeframe: str = "1m", limit: int = 100) -> pd.DataFrame:
        raw = self._exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_price(self, pair: str) -> float:
        return float(self._exchange.fetch_ticker(pair)["last"])

    def get_usdt_balance(self) -> float:
        balance = self._exchange.fetch_balance()
        return float(balance.get("USDT", {}).get("free", 0))

    def get_positions(self) -> dict[str, CryptoPosition]:
        balance = self._exchange.fetch_balance()
        positions = {}
        for coin, amounts in balance.get("total", {}).items():
            qty = float(amounts) if isinstance(amounts, (int, float)) else 0.0
            if qty < 1e-8 or coin == "USDT":
                continue
            pair = f"{coin}/USDT"
            try:
                price = self.get_price(pair)
                positions[pair] = CryptoPosition(pair, coin, "USDT", qty, price, price)
            except Exception:
                pass
        return positions

    def buy_market(self, pair: str, usdt_amount: float) -> CryptoOrder:
        price = self.get_price(pair)
        qty = usdt_amount / price
        order = self._exchange.create_market_buy_order(pair, qty)
        filled_price = float(order.get("average") or order.get("price") or price)
        filled_qty = float(order.get("filled") or qty)
        cost = float(order.get("cost") or usdt_amount)
        logger.info(f"[LIVE] BUY {filled_qty:.6f} {pair.split('/')[0]} @ ${filled_price:,.4f}")
        return CryptoOrder(order["id"], pair, "BUY", filled_qty, filled_price, cost, order.get("status", "closed"))

    def sell_market(self, pair: str, qty: float) -> CryptoOrder:
        price = self.get_price(pair)
        order = self._exchange.create_market_sell_order(pair, qty)
        filled_price = float(order.get("average") or order.get("price") or price)
        filled_qty = float(order.get("filled") or qty)
        proceeds = float(order.get("cost") or filled_qty * filled_price)
        logger.info(f"[LIVE] SELL {filled_qty:.6f} {pair.split('/')[0]} @ ${filled_price:,.4f}")
        return CryptoOrder(order["id"], pair, "SELL", filled_qty, filled_price, proceeds, order.get("status", "closed"))
