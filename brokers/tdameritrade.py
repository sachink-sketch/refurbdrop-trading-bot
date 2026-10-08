"""
TD Ameritrade / Charles Schwab broker.
TD Ameritrade was acquired by Schwab. Use the schwab-py library.
First-time auth requires a browser redirect — run `python main.py --auth` once.
"""
from brokers.base import BaseBroker, Position, OrderResult
from config import config
from utils.logger import logger


class TDAmeritradeBroker(BaseBroker):
    paper_trading = False

    def __init__(self):
        self._client = None
        self._account_number = config.TD_ACCOUNT_NUMBER

    def login(self) -> bool:
        try:
            import schwab
            self._client = schwab.auth.easy_client(
                api_key=config.TD_CLIENT_ID,
                app_secret=config.TD_CLIENT_SECRET,
                callback_url=config.TD_REDIRECT_URI,
                token_path=config.TD_TOKEN_PATH,
            )
            # Verify connection
            accounts = self._client.get_account_numbers()
            if accounts.status_code != 200:
                logger.error("TD Ameritrade / Schwab connection failed")
                return False
            account_data = accounts.json()
            if not self._account_number and account_data:
                self._account_number = account_data[0].get("hashValue", "")
            logger.info(f"TD Ameritrade / Schwab login successful | account: ...{self._account_number[-4:]}")
            return True
        except ImportError:
            logger.error("schwab-py not installed. Run: pip install schwab-py")
            return False
        except Exception as e:
            logger.error(f"TD Ameritrade login error: {e}")
            logger.info("Hint: Run 'python main.py --auth' for first-time OAuth setup")
            return False

    def _get_account_data(self) -> dict:
        resp = self._client.get_account(self._account_number, fields=[self._client.Account.Fields.POSITIONS])
        resp.raise_for_status()
        return resp.json()

    def get_cash(self) -> float:
        data = self._get_account_data()
        balance = data.get("securitiesAccount", {}).get("currentBalances", {})
        return float(balance.get("cashBalance", balance.get("availableFunds", 0)))

    def get_portfolio_value(self) -> float:
        data = self._get_account_data()
        balance = data.get("securitiesAccount", {}).get("currentBalances", {})
        return float(balance.get("liquidationValue", 0))

    def get_positions(self) -> dict[str, Position]:
        data = self._get_account_data()
        raw_positions = data.get("securitiesAccount", {}).get("positions", [])
        positions = {}
        for p in raw_positions:
            instrument = p.get("instrument", {})
            symbol = instrument.get("symbol", "")
            if not symbol or instrument.get("assetType") != "EQUITY":
                continue
            qty = float(p.get("longQuantity", 0))
            avg_cost = float(p.get("averagePrice", 0))
            price = float(p.get("marketValue", 0)) / qty if qty else avg_cost
            positions[symbol] = Position(symbol, qty, avg_cost, price)
        return positions

    def buy_market(self, symbol: str, qty: float) -> OrderResult:
        import schwab
        order = schwab.orders.equities.market_buy(symbol, int(qty))
        resp = self._client.place_order(self._account_number, order)
        order_id = resp.headers.get("Location", "").split("/")[-1] or "unknown"
        price = self.get_current_price(symbol)
        logger.info(f"[LIVE] BUY {qty} {symbol} @ ~${price:.2f} | order_id={order_id}")
        return OrderResult(order_id, symbol, "BUY", qty, price, "QUEUED")

    def sell_market(self, symbol: str, qty: float) -> OrderResult:
        import schwab
        order = schwab.orders.equities.market_sell(symbol, int(qty))
        resp = self._client.place_order(self._account_number, order)
        order_id = resp.headers.get("Location", "").split("/")[-1] or "unknown"
        price = self.get_current_price(symbol)
        logger.info(f"[LIVE] SELL {qty} {symbol} @ ~${price:.2f} | order_id={order_id}")
        return OrderResult(order_id, symbol, "SELL", qty, price, "QUEUED")

    def get_current_price(self, symbol: str) -> float:
        try:
            resp = self._client.get_quote(symbol)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get(symbol, {}).get("quote", {}).get("lastPrice", 0))
        except Exception:
            from utils.market_data import market_data
            return market_data.get_current_price(symbol)
