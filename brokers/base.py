from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    symbol: str
    qty: float
    avg_cost: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.qty * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_cost) * self.qty

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_cost == 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str        # BUY | SELL
    qty: float
    price: float
    status: str
    paper: bool = False


class BaseBroker(ABC):
    """Abstract interface — every broker must implement these methods."""

    paper_trading: bool = True

    @abstractmethod
    def login(self) -> bool: ...

    @abstractmethod
    def get_cash(self) -> float: ...

    @abstractmethod
    def get_portfolio_value(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]: ...

    @abstractmethod
    def buy_market(self, symbol: str, qty: float) -> OrderResult: ...

    @abstractmethod
    def sell_market(self, symbol: str, qty: float) -> OrderResult: ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> float: ...

    def get_portfolio_context(self) -> dict:
        cash = self.get_cash()
        total = self.get_portfolio_value()
        positions = self.get_positions()
        return {
            "cash": cash,
            "total_value": total,
            "num_positions": len(positions),
            "daily_pnl_pct": 0.0,   # brokers override this if available
        }
