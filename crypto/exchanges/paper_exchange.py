"""
Paper crypto exchange — uses Binance public API for real market data,
simulates order execution with virtual USDT. No account needed.
"""
import uuid
import ccxt
import pandas as pd
from crypto.exchanges.base_exchange import BaseCryptoExchange, CryptoPosition, CryptoOrder
from utils.logger import logger


class PaperCryptoExchange(BaseCryptoExchange):
    paper = True

    def __init__(self, starting_usdt: float = 1000.0):
        self._usdt = starting_usdt
        self._starting_usdt = starting_usdt
        self._positions: dict[str, CryptoPosition] = {}
        # Try Binance.US first (US-accessible), fall back to Kraken
        for exchange_cls in [ccxt.binanceus, ccxt.kraken]:
            try:
                ex = exchange_cls({"enableRateLimit": True})
                ex.load_markets()
                self._exchange = ex
                logger.info(f"Using {exchange_cls.__name__} for market data")
                break
            except Exception:
                continue
        else:
            raise RuntimeError("Could not connect to any exchange for market data")

    def get_ohlcv(self, pair: str, timeframe: str = "1m", limit: int = 100) -> pd.DataFrame:
        raw = self._exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_price(self, pair: str) -> float:
        ticker = self._exchange.fetch_ticker(pair)
        return float(ticker["last"])

    def get_usdt_balance(self) -> float:
        return self._usdt

    def get_positions(self) -> dict[str, CryptoPosition]:
        for pair, pos in self._positions.items():
            try:
                pos.current_price = self.get_price(pair)
            except Exception:
                pass
        return self._positions

    def buy_market(self, pair: str, usdt_amount: float) -> CryptoOrder:
        price = self.get_price(pair)
        cost = min(usdt_amount, self._usdt * 0.99)   # keep 1% buffer
        qty = cost / price
        self._usdt -= cost

        base = pair.split("/")[0]
        if pair in self._positions:
            pos = self._positions[pair]
            total_qty = pos.qty + qty
            avg = (pos.avg_entry * pos.qty + price * qty) / total_qty
            self._positions[pair] = CryptoPosition(pair, base, "USDT", total_qty, avg, price)
        else:
            self._positions[pair] = CryptoPosition(pair, base, "USDT", qty, price, price)

        order = CryptoOrder(str(uuid.uuid4()), pair, "BUY", qty, price, cost, "FILLED", paper=True)
        logger.info(f"[PAPER] BUY {qty:.6f} {base} @ ${price:,.4f} | cost ${cost:.2f} | USDT left: ${self._usdt:.2f}")
        return order

    def sell_market(self, pair: str, qty: float) -> CryptoOrder:
        if pair not in self._positions:
            raise ValueError(f"No position in {pair}")
        price = self.get_price(pair)
        pos = self._positions[pair]
        sell_qty = min(qty, pos.qty)
        proceeds = sell_qty * price
        pnl = (price - pos.avg_entry) * sell_qty
        self._usdt += proceeds

        if sell_qty >= pos.qty:
            del self._positions[pair]
        else:
            self._positions[pair] = CryptoPosition(pair, pos.base, "USDT", pos.qty - sell_qty, pos.avg_entry, price)

        order = CryptoOrder(str(uuid.uuid4()), pair, "SELL", sell_qty, price, proceeds, "FILLED", paper=True)
        logger.info(f"[PAPER] SELL {sell_qty:.6f} {pos.base} @ ${price:,.4f} | P&L: ${pnl:+.2f} | USDT: ${self._usdt:.2f}")
        return order

    @property
    def total_pnl_pct(self) -> float:
        return (self.get_portfolio_value() - self._starting_usdt) / self._starting_usdt
