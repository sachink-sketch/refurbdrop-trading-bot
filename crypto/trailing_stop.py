"""Trailing stop manager — activates after a profit threshold, then ratchets up."""
from dataclasses import dataclass, field
from utils.logger import logger


@dataclass
class TrailingStop:
    pair: str
    entry_price: float
    trail_pct: float          # how far below peak to place the stop (e.g. 0.005 = 0.5%)
    take_profit_pct: float    # hard ceiling TP
    activate_pct: float       # only start trailing after this much profit (e.g. 0.008 = 0.8%)
    highest_price: float = field(init=False)
    activated: bool = field(init=False)

    def __post_init__(self):
        self.highest_price = self.entry_price
        self.activated = False

    @property
    def current_stop(self) -> float:
        return self.highest_price * (1 - self.trail_pct)

    @property
    def hard_tp(self) -> float:
        return self.entry_price * (1 + self.take_profit_pct)

    def update(self, current_price: float) -> bool:
        """Returns True if trailing stop or hard TP was hit (time to sell)."""
        if current_price > self.highest_price:
            self.highest_price = current_price

        profit_pct = (self.highest_price - self.entry_price) / self.entry_price

        if not self.activated and profit_pct >= self.activate_pct:
            self.activated = True
            logger.info(
                f"TRAILING STOP activated {self.pair}: "
                f"peak ${self.highest_price:.4f} (+{profit_pct:.2%}), "
                f"stop floor ${self.current_stop:.4f}"
            )

        if self.activated and current_price <= self.current_stop:
            exit_pnl = (current_price - self.entry_price) / self.entry_price
            if exit_pnl > 0:
                logger.info(
                    f"TRAILING STOP hit {self.pair}: locked +{profit_pct:.2%}, exit {exit_pnl:+.2%}"
                )
            else:
                logger.warning(
                    f"TRAILING STOP hit {self.pair}: exit {exit_pnl:+.2%} (was +{profit_pct:.2%})"
                )
            return True

        if current_price >= self.hard_tp:
            logger.info(f"HARD TP hit {self.pair}: +{self.take_profit_pct:.2%}")
            return True

        return False


class TrailingStopManager:
    def __init__(self, trail_pct: float, take_profit_pct: float, activate_pct: float):
        self.trail_pct       = trail_pct
        self.take_profit_pct = take_profit_pct
        self.activate_pct    = activate_pct
        self._stops: dict[str, TrailingStop] = {}

    def is_registered(self, pair: str) -> bool:
        return pair in self._stops

    def register(
        self, pair: str, entry_price: float,
        trail_pct: float | None = None, take_profit_pct: float | None = None,
        activate_pct: float | None = None,
    ):
        trail = trail_pct if trail_pct is not None else self.trail_pct
        tp    = take_profit_pct if take_profit_pct is not None else self.take_profit_pct
        act   = activate_pct if activate_pct is not None else self.activate_pct
        self._stops[pair] = TrailingStop(pair, entry_price, trail, tp, act)
        logger.info(
            f"Trailing stop registered {pair} @ ${entry_price:.4f} | "
            f"activates at +{act:.1%} | trail {trail:.2%} below peak | TP {tp:.1%}"
        )

    def update_all(self, prices: dict[str, float]) -> list[str]:
        """Returns list of pairs to close."""
        to_close = []
        for pair, stop in list(self._stops.items()):
            price = prices.get(pair)
            if price is not None and stop.update(price):
                to_close.append(pair)
        return to_close

    def remove(self, pair: str):
        self._stops.pop(pair, None)

    def status(self) -> dict[str, dict]:
        return {
            pair: {
                "highest": s.highest_price,
                "stop": s.current_stop if s.activated else None,
                "hard_tp": s.hard_tp,
                "activated": s.activated,
            }
            for pair, s in self._stops.items()
        }
