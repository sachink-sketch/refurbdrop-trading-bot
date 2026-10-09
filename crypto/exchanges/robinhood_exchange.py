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

_NETWORK_ERRORS = (ConnectionResetError, ConnectionError, OSError, TimeoutError)

def _retry(fn, retries=3, delay=5):
    """Retry fn on transient network errors."""
    for attempt in range(retries):
        try:
            return fn()
        except _NETWORK_ERRORS as e:
            if attempt < retries - 1:
                logger.warning(f"[ROBINHOOD] Network error (retry {attempt+1}/{retries}): {e}")
                time.sleep(delay)
            else:
                raise


def _symbol(pair: str) -> str:
    """'BTC/USDT' → 'BTC'"""
    return pair.split("/")[0].upper()


class RobinhoodCryptoExchange(BaseCryptoExchange):
    paper = False

    # Robinhood-supported crypto symbols
    SUPPORTED = {"BTC", "ETH", "SOL", "DOGE", "AVAX", "LINK", "XRP", "ADA", "LTC", "ETC", "MATIC"}
    _EXCLUDED = {"SHIB"}  # permanently excluded by user

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
        quote = _retry(lambda: self._rh.crypto.get_crypto_quote(sym))
        return float(quote.get("mark_price") or quote.get("ask_price") or 0)

    def get_bid_ask(self, pair: str) -> tuple[float, float] | None:
        try:
            quote = _retry(lambda: self._rh.crypto.get_crypto_quote(_symbol(pair)))
            bid, ask = float(quote.get("bid_price") or 0), float(quote.get("ask_price") or 0)
            if bid <= 0 or ask <= 0 or ask < bid:
                return None
            return bid, ask
        except Exception as e:
            logger.debug(f"[ROBINHOOD CRYPTO] bid/ask unavailable for {pair}: {e}")
            return None

    def _fill_price(self, order_id: str, fallback: float) -> float:
        """Real average fill price. The order response right after placement has none, so poll for it."""
        for _ in range(8):
            try:
                info = self._rh.get_crypto_order_info(order_id) or {}
                avg = info.get("average_price")
                if info.get("state") == "filled" and avg:
                    return float(avg)
            except Exception as e:
                logger.debug(f"[ROBINHOOD CRYPTO] fill lookup failed: {e}")
            time.sleep(1)
        logger.warning(f"[ROBINHOOD CRYPTO] fill for order {order_id} unconfirmed — using quote ${fallback:,.4f}")
        return fallback

    def get_usdt_balance(self) -> float:
        """Returns USD buying power available in the Robinhood account."""
        profile = _retry(lambda: self._rh.profiles.load_account_profile())
        return float(profile.get("buying_power", 0) or 0)

    def get_positions(self) -> dict[str, CryptoPosition]:
        positions = {}
        try:
            raw = _retry(lambda: self._rh.crypto.get_crypto_positions())
            for pos in (raw or []):
                sym = pos.get("currency", {}).get("code", "")
                if not sym or sym in self._EXCLUDED:
                    continue
                pair = f"{sym}/USDT"
                try:
                    price = self.get_price(pair)
                    # Use quantity_available so we only count/sell what's not locked/pending
                    qty = float(pos.get("quantity_available") or pos.get("quantity") or 0)
                    if qty < 1e-8:
                        continue
                    # Robinhood crypto positions use cost_bases, not average_buy_price
                    avg_buy = float(pos.get("average_buy_price") or 0)
                    if avg_buy == 0:
                        cost_bases = pos.get("cost_bases", [])
                        if cost_bases:
                            total_cost = sum(float(cb.get("direct_cost_basis", 0)) for cb in cost_bases)
                            total_qty  = sum(float(cb.get("direct_quantity", 0)) for cb in cost_bases)
                            avg_buy = (total_cost / total_qty) if total_qty > 0 else price
                        else:
                            avg_buy = price
                    positions[pair] = CryptoPosition(pair, sym, "USD", qty, avg_buy, price)
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
        order = self._rh.order_buy_crypto_by_price(sym, usdt_amount)
        if not order or order.get("detail"):
            raise RuntimeError(f"Robinhood buy failed: {order}")
        ba = self.get_bid_ask(pair)
        filled_price = float(order.get("average_price") or 0) or self._fill_price(
            order.get("id", ""), ba[1] if ba else price
        )
        filled_qty   = float(order.get("quantity") or 0)
        if filled_qty == 0:
            filled_qty = float(order.get("rounded_executed_notional") or usdt_amount) / max(filled_price, 1e-8)
        logger.info(
            f"[LIVE ROBINHOOD] BUY {filled_qty:.6f} {sym} @ ${filled_price:,.4f} "
            f"(${usdt_amount:.2f}, mark ${price:,.4f})"
        )
        return CryptoOrder(order.get("id", "rh"), pair, "BUY", filled_qty, filled_price, usdt_amount, "closed",
                           mark_price=price)

    def sell_market(self, pair: str, qty: float) -> CryptoOrder:
        sym = _symbol(pair)
        price = self.get_price(pair)
        qty_rounded = round(qty, 6)
        order = self._rh.order_sell_crypto_by_quantity(sym, qty_rounded)
        if not order or order.get("detail"):
            # Fallback: sell by dollar amount
            proceeds = round(qty_rounded * price, 2)
            order = self._rh.order_sell_crypto_by_price(sym, proceeds)
        if not order or order.get("detail"):
            raise RuntimeError(f"Robinhood sell failed: {order}")
        ba = self.get_bid_ask(pair)
        filled_price = float(order.get("average_price") or 0) or self._fill_price(
            order.get("id", ""), ba[0] if ba else price
        )
        proceeds = filled_price * qty
        logger.info(
            f"[LIVE ROBINHOOD] SELL {qty:.6f} {sym} @ ${filled_price:,.4f} "
            f"(${proceeds:.2f}, mark ${price:,.4f})"
        )
        return CryptoOrder(order.get("id", "rh"), pair, "SELL", qty, filled_price, proceeds, "closed",
                           mark_price=price)
