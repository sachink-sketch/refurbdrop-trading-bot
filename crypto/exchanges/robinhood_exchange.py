"""
Live crypto exchange via Robinhood (robin_stocks).
Uses the same Robinhood account credentials as the stock bot.
Pair format: BTC/USDT → internally uses 'BTC' vs USD.
Robinhood-supported coins: BTC, ETH, SOL, DOGE, AVAX, LINK, XRP, ADA, LTC, ETC.
"""
import time
import pandas as pd
from crypto.exchanges.base_exchange import BaseCryptoExchange, CryptoPosition, CryptoOrder
from utils.logger import logger


def _symbol(pair: str) -> str:
    """'BTC/USDT' → 'BTC'"""
    return pair.split("/")[0].upper()


class RobinhoodCryptoExchange(BaseCryptoExchange):
    paper = False

    # Robinhood-supported crypto symbols
    SUPPORTED = {"BTC", "ETH", "SOL", "DOGE", "AVAX", "LINK", "XRP", "ADA", "LTC", "ETC", "SHIB", "MATIC"}

    def __init__(self):
        from config import config
        import robin_stocks.robinhood as rh
        self._rh = rh
        kwargs = {"username": config.ROBINHOOD_USERNAME, "password": config.ROBINHOOD_PASSWORD, "store_session": True}
        if config.ROBINHOOD_MFA_CODE:
            kwargs["mfa_code"] = config.ROBINHOOD_MFA_CODE
        result = rh.login(**kwargs)
        if not result:
            raise RuntimeError("Robinhood login failed — check ROBINHOOD_USERNAME / PASSWORD in .env")
        logger.info("[ROBINHOOD CRYPTO] Logged in — using live USD account")

    def supports_pair(self, pair: str) -> bool:
        return _symbol(pair) in self.SUPPORTED

    def get_ohlcv(self, pair: str, timeframe: str = "1m", limit: int = 100) -> pd.DataFrame:
        sym = _symbol(pair)
        # Map bot timeframe → Robinhood interval/span
        rh_interval = "5minute"
        rh_span = "day"
        if timeframe in ("1h", "60m"):
            rh_interval = "hour"
            rh_span = "week"

        try:
            raw = self._rh.crypto.get_crypto_historicals(
                sym, interval=rh_interval, span=rh_span, bounds="24_7"
            )
            if not raw:
                raise ValueError(f"No historicals for {sym}")
            df = pd.DataFrame(raw)
            df["timestamp"] = pd.to_datetime(df["begins_at"])
            df = df.rename(columns={
                "open_price": "open", "high_price": "high",
                "low_price": "low", "close_price": "close",
                "volume": "volume",
            })
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
            return df.tail(limit)
        except Exception as e:
            logger.warning(f"[ROBINHOOD CRYPTO] OHLCV failed for {sym}: {e}")
            raise

    def get_price(self, pair: str) -> float:
        sym = _symbol(pair)
        quote = self._rh.crypto.get_crypto_quote(sym)
        return float(quote.get("mark_price") or quote.get("ask_price") or 0)

    def get_usdt_balance(self) -> float:
        """Returns USD buying power available in the Robinhood account."""
        profile = self._rh.profiles.load_account_profile()
        return float(profile.get("buying_power", 0) or 0)

    def get_positions(self) -> dict[str, CryptoPosition]:
        positions = {}
        try:
            raw = self._rh.crypto.get_crypto_positions()
            for pos in (raw or []):
                qty = float(pos.get("quantity") or 0)
                if qty < 1e-8:
                    continue
                sym = pos.get("currency", {}).get("code", "")
                if not sym:
                    continue
                pair = f"{sym}/USDT"
                try:
                    price = self.get_price(pair)
                    avg_cost = float(pos.get("average_buy_price") or price)
                    positions[pair] = CryptoPosition(pair, sym, "USD", qty, avg_cost, price)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[ROBINHOOD CRYPTO] get_positions error: {e}")
        return positions

    def buy_market(self, pair: str, usdt_amount: float) -> CryptoOrder:
        sym = _symbol(pair)
        if sym not in self.SUPPORTED:
            raise ValueError(f"{sym} not supported on Robinhood")
        price = self.get_price(pair)
        order = self._rh.crypto.order_buy_crypto_by_price(sym, usdt_amount)
        if not order or order.get("detail"):
            raise RuntimeError(f"Robinhood buy failed: {order}")
        filled_price = float(order.get("average_price") or price)
        filled_qty = float(order.get("rounded_executed_notional") or usdt_amount) / filled_price
        logger.info(f"[LIVE ROBINHOOD] BUY {filled_qty:.6f} {sym} @ ${filled_price:,.4f} (${usdt_amount:.2f})")
        time.sleep(1)  # brief pause after order
        return CryptoOrder(order.get("id", "rh"), pair, "BUY", filled_qty, filled_price, usdt_amount, "closed")

    def sell_market(self, pair: str, qty: float) -> CryptoOrder:
        sym = _symbol(pair)
        price = self.get_price(pair)
        order = self._rh.crypto.order_sell_crypto_by_quantity(sym, qty)
        if not order or order.get("detail"):
            raise RuntimeError(f"Robinhood sell failed: {order}")
        filled_price = float(order.get("average_price") or price)
        proceeds = filled_price * qty
        logger.info(f"[LIVE ROBINHOOD] SELL {qty:.6f} {sym} @ ${filled_price:,.4f} (${proceeds:.2f})")
        time.sleep(1)
        return CryptoOrder(order.get("id", "rh"), pair, "SELL", qty, filled_price, proceeds, "closed")
