from brokers.base import BaseBroker, Position, OrderResult
from config import config
from utils.logger import logger


class RobinhoodBroker(BaseBroker):
    paper_trading = False

    def __init__(self):
        self._rh = None

    def login(self) -> bool:
        try:
            import robin_stocks.robinhood as rh
            self._rh = rh
            kwargs = {
                "username": config.ROBINHOOD_USERNAME,
                "password": config.ROBINHOOD_PASSWORD,
                "store_session": True,
            }
            if config.ROBINHOOD_MFA_CODE:
                kwargs["mfa_code"] = config.ROBINHOOD_MFA_CODE
            result = rh.login(**kwargs)
            if result:
                logger.info("Robinhood login successful")
                return True
            logger.error("Robinhood login failed — check credentials")
            return False
        except ImportError:
            logger.error("robin-stocks not installed. Run: pip install robin-stocks")
            return False
        except Exception as e:
            logger.error(f"Robinhood login error: {e}")
            return False

    def get_cash(self) -> float:
        profile = self._rh.profiles.load_account_profile()
        return float(profile.get("buying_power", 0))

    def get_portfolio_value(self) -> float:
        portfolio = self._rh.profiles.load_portfolio_profile()
        return float(portfolio.get("equity", 0))

    def get_positions(self) -> dict[str, Position]:
        positions = {}
        raw = self._rh.account.get_open_stock_positions()
        for pos in raw:
            instrument_url = pos["instrument"]
            symbol_data = self._rh.stocks.get_instrument_by_url(instrument_url)
            symbol = symbol_data.get("symbol", "")
            if not symbol:
                continue
            qty = float(pos["quantity"])
            avg_cost = float(pos["average_buy_price"])
            price = self.get_current_price(symbol)
            positions[symbol] = Position(symbol, qty, avg_cost, price)
        return positions

    def buy_market(self, symbol: str, qty: float) -> OrderResult:
        order = self._rh.orders.order_buy_market(symbol, qty)
        order_id = order.get("id", "unknown")
        price = self.get_current_price(symbol)
        logger.info(f"[LIVE] BUY {qty:.4f} {symbol} @ ~${price:.2f} | order_id={order_id}")
        return OrderResult(order_id, symbol, "BUY", qty, price, order.get("state", "queued"))

    def sell_market(self, symbol: str, qty: float) -> OrderResult:
        order = self._rh.orders.order_sell_market(symbol, qty)
        order_id = order.get("id", "unknown")
        price = self.get_current_price(symbol)
        logger.info(f"[LIVE] SELL {qty:.4f} {symbol} @ ~${price:.2f} | order_id={order_id}")
        return OrderResult(order_id, symbol, "SELL", qty, price, order.get("state", "queued"))

    def get_current_price(self, symbol: str) -> float:
        quote = self._rh.stocks.get_latest_price(symbol)
        return float(quote[0]) if quote else 0.0

    def get_portfolio_context(self) -> dict:
        ctx = super().get_portfolio_context()
        try:
            portfolio = self._rh.profiles.load_portfolio_profile()
            equity = float(portfolio.get("equity", 0))
            prev_equity = float(portfolio.get("equity_previous_close", equity))
            if prev_equity > 0:
                ctx["daily_pnl_pct"] = (equity - prev_equity) / prev_equity
        except Exception:
            pass
        return ctx
