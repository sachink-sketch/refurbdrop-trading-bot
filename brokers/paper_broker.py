"""Paper trading broker — simulates trades without touching real money."""
import uuid
from brokers.base import BaseBroker, Position, OrderResult
from utils.logger import logger
from utils.market_data import market_data


class PaperBroker(BaseBroker):
    """In-memory paper trading. Starts with $10,000 virtual cash."""

    paper_trading = True

    def __init__(self, starting_cash: float = 10_000.0):
        self._cash = starting_cash
        self._positions: dict[str, Position] = {}
        self._starting_value = starting_cash

    def login(self) -> bool:
        logger.info("[bold yellow]PAPER TRADING MODE — no real money at risk[/]")
        return True

    def get_cash(self) -> float:
        return self._cash

    def get_portfolio_value(self) -> float:
        positions_value = sum(p.market_value for p in self._positions.values())
        return self._cash + positions_value

    def get_positions(self) -> dict[str, Position]:
        # Refresh current prices
        for symbol, pos in self._positions.items():
            try:
                pos.current_price = market_data.get_current_price(symbol)
            except Exception:
                pass
        return self._positions

    def get_current_price(self, symbol: str) -> float:
        return market_data.get_current_price(symbol)

    def buy_market(self, symbol: str, qty: float) -> OrderResult:
        price = market_data.get_current_price(symbol)
        cost = price * qty
        if cost > self._cash:
            qty = self._cash / price
            cost = self._cash
        self._cash -= cost
        if symbol in self._positions:
            existing = self._positions[symbol]
            total_qty = existing.qty + qty
            avg_cost = (existing.avg_cost * existing.qty + price * qty) / total_qty
            self._positions[symbol] = Position(symbol, total_qty, avg_cost, price)
        else:
            self._positions[symbol] = Position(symbol, qty, price, price)
        result = OrderResult(str(uuid.uuid4()), symbol, "BUY", qty, price, "FILLED", paper=True)
        logger.info(f"[PAPER] BUY {qty:.4f} {symbol} @ ${price:.2f} | cash remaining: ${self._cash:,.2f}")
        return result

    def sell_market(self, symbol: str, qty: float) -> OrderResult:
        if symbol not in self._positions:
            raise ValueError(f"No position in {symbol}")
        price = market_data.get_current_price(symbol)
        pos = self._positions[symbol]
        sell_qty = min(qty, pos.qty)
        proceeds = price * sell_qty
        self._cash += proceeds
        if sell_qty >= pos.qty:
            del self._positions[symbol]
        else:
            self._positions[symbol] = Position(symbol, pos.qty - sell_qty, pos.avg_cost, price)
        result = OrderResult(str(uuid.uuid4()), symbol, "SELL", sell_qty, price, "FILLED", paper=True)
        pnl = (price - pos.avg_cost) * sell_qty
        logger.info(
            f"[PAPER] SELL {sell_qty:.4f} {symbol} @ ${price:.2f} | P&L: ${pnl:+.2f} | cash: ${self._cash:,.2f}"
        )
        return result

    def get_portfolio_context(self) -> dict:
        ctx = super().get_portfolio_context()
        ctx["daily_pnl_pct"] = (self.get_portfolio_value() - self._starting_value) / self._starting_value
        return ctx
