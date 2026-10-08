from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd


@dataclass
class CryptoPosition:
    pair: str
    base: str          # e.g. "BTC"
    quote: str         # e.g. "USDT"
    qty: float         # amount of base held
    avg_entry: float   # entry price in USDT
    current_price: float

    @property
    def value_usdt(self) -> float:
        return self.qty * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_entry) * self.qty

    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.avg_entry) / self.avg_entry if self.avg_entry else 0.0


@dataclass
class CryptoOrder:
    order_id: str
    pair: str
    side: str          # BUY | SELL
    qty: float
    price: float
    cost_usdt: float
    status: str
    paper: bool = False


class BaseCryptoExchange(ABC):
    paper: bool = True

    @abstractmethod
    def get_ohlcv(self, pair: str, timeframe: str = "1m", limit: int = 100) -> pd.DataFrame: ...

    @abstractmethod
    def get_price(self, pair: str) -> float: ...

    @abstractmethod
    def get_usdt_balance(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> dict[str, CryptoPosition]: ...

    @abstractmethod
    def buy_market(self, pair: str, usdt_amount: float) -> CryptoOrder: ...

    @abstractmethod
    def sell_market(self, pair: str, qty: float) -> CryptoOrder: ...

    def get_portfolio_value(self) -> float:
        usdt = self.get_usdt_balance()
        positions_value = sum(p.value_usdt for p in self.get_positions().values())
        return usdt + positions_value
