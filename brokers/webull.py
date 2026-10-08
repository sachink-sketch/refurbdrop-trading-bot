from brokers.base import BaseBroker, Position, OrderResult
from config import config
from utils.logger import logger


class WebullBroker(BaseBroker):
    paper_trading = False

    def __init__(self):
        self._wb = None

    def login(self) -> bool:
        try:
            from webull import webull as wb_class
            self._wb = wb_class()
            result = self._wb.login(
                username=config.WEBULL_EMAIL,
                password=config.WEBULL_PASSWORD,
                device_name="ClaudeTrader",
                save_token=True,
            )
            if not result.get("accessToken"):
                logger.error("Webull login failed — check credentials")
                return False
            # Set trading PIN
            self._wb.get_trade_token(config.WEBULL_TRADE_PIN)
            logger.info("Webull login successful")
            return True
        except ImportError:
            logger.error("webull not installed. Run: pip install webull")
            return False
        except Exception as e:
            logger.error(f"Webull login error: {e}")
            return False

    def get_cash(self) -> float:
        account = self._wb.get_account()
        for item in account.get("accountMembers", []):
            if item.get("key") == "totalCash":
                return float(item.get("value", 0))
        return 0.0

    def get_portfolio_value(self) -> float:
        account = self._wb.get_account()
        for item in account.get("accountMembers", []):
            if item.get("key") == "totalMarketValue":
                return float(item.get("value", 0)) + self.get_cash()
        return self.get_cash()

    def get_positions(self) -> dict[str, Position]:
        positions = {}
        raw = self._wb.get_positions()
        for pos in raw:
            symbol = pos.get("ticker", {}).get("symbol", "")
            if not symbol:
                continue
            qty = float(pos.get("position", 0))
            avg_cost = float(pos.get("costPrice", 0))
            price = float(pos.get("lastPrice", avg_cost))
            positions[symbol] = Position(symbol, qty, avg_cost, price)
        return positions

    def buy_market(self, symbol: str, qty: float) -> OrderResult:
        order = self._wb.place_order(
            stock=symbol,
            action="BUY",
            orderType="MKT",
            enforce="DAY",
            quant=int(qty),
        )
        order_id = str(order.get("orderId", "unknown"))
        price = self.get_current_price(symbol)
        logger.info(f"[LIVE] BUY {qty} {symbol} @ ~${price:.2f} | order_id={order_id}")
        return OrderResult(order_id, symbol, "BUY", qty, price, "QUEUED")

    def sell_market(self, symbol: str, qty: float) -> OrderResult:
        order = self._wb.place_order(
            stock=symbol,
            action="SELL",
            orderType="MKT",
            enforce="DAY",
            quant=int(qty),
        )
        order_id = str(order.get("orderId", "unknown"))
        price = self.get_current_price(symbol)
        logger.info(f"[LIVE] SELL {qty} {symbol} @ ~${price:.2f} | order_id={order_id}")
        return OrderResult(order_id, symbol, "SELL", qty, price, "QUEUED")

    def get_current_price(self, symbol: str) -> float:
        try:
            quote = self._wb.get_quote(stock=symbol)
            return float(quote.get("close", 0) or quote.get("open", 0))
        except Exception:
            from utils.market_data import market_data
            return market_data.get_current_price(symbol)
