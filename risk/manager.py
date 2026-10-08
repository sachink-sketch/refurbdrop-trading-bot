from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from analysis.claude_analyst import TradeSignal
from brokers.base import BaseBroker, Position
from config import config
from utils.logger import logger


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str
    adjusted_qty: float = 0.0


class RiskManager:
    def __init__(self, broker: BaseBroker):
        self._broker = broker
        self._daily_trades: list[dict] = []
        self._daily_start_value: Optional[float] = None
        self._today = date.today()

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._today:
            self._daily_trades.clear()
            self._daily_start_value = None
            self._today = today

    def _daily_start(self) -> float:
        if self._daily_start_value is None:
            self._daily_start_value = self._broker.get_portfolio_value()
        return self._daily_start_value

    def check_signal(self, signal: TradeSignal) -> RiskCheckResult:
        self._reset_if_new_day()

        # 1. Confidence gate
        if signal.confidence < config.MIN_CONFIDENCE:
            return RiskCheckResult(False, f"Confidence {signal.confidence:.0%} below threshold {config.MIN_CONFIDENCE:.0%}")

        # 2. Daily trade cap
        trades_today = len(self._daily_trades)
        if trades_today >= config.MAX_TRADES_PER_DAY:
            return RiskCheckResult(False, f"Daily trade cap reached ({trades_today}/{config.MAX_TRADES_PER_DAY})")

        # 3. Daily loss circuit-breaker
        portfolio_value = self._broker.get_portfolio_value()
        start_value = self._daily_start()
        if start_value > 0:
            daily_loss = (start_value - portfolio_value) / start_value
            if daily_loss >= config.MAX_DAILY_LOSS_PCT:
                return RiskCheckResult(
                    False,
                    f"Daily loss circuit breaker triggered: {daily_loss:.2%} >= {config.MAX_DAILY_LOSS_PCT:.2%}",
                )

        if signal.action == "HOLD":
            return RiskCheckResult(True, "HOLD — no trade needed", 0.0)

        if signal.action == "BUY":
            return self._check_buy(signal, portfolio_value)

        if signal.action == "SELL":
            return self._check_sell(signal)

        return RiskCheckResult(False, f"Unknown action: {signal.action}")

    def _check_buy(self, signal: TradeSignal, portfolio_value: float) -> RiskCheckResult:
        cash = self._broker.get_cash()
        if cash <= 0:
            return RiskCheckResult(False, "No buying power available")

        # Position size: min of (max_position_pct of portfolio, suggested_qty_pct of cash, available cash)
        max_position_value = portfolio_value * config.MAX_POSITION_PCT
        suggested_value = cash * signal.suggested_qty_pct
        alloc = min(max_position_value, suggested_value, cash * 0.95)  # keep 5% buffer

        price = self._broker.get_current_price(signal.symbol)
        if price <= 0:
            return RiskCheckResult(False, f"Cannot get price for {signal.symbol}")

        qty = alloc / price
        if qty < 0.001:
            return RiskCheckResult(False, f"Position too small (${alloc:.2f} not enough for {signal.symbol})")

        logger.info(
            f"Risk approved BUY {signal.symbol}: {qty:.4f} shares "
            f"(${alloc:.2f}, {alloc / portfolio_value:.1%} of portfolio)"
        )
        return RiskCheckResult(True, "Approved", qty)

    def _check_sell(self, signal: TradeSignal) -> RiskCheckResult:
        positions = self._broker.get_positions()
        pos = positions.get(signal.symbol)
        if not pos:
            return RiskCheckResult(False, f"No position in {signal.symbol} to sell")
        return RiskCheckResult(True, "Approved", pos.qty)

    def record_trade(self, symbol: str, action: str, qty: float, price: float):
        self._daily_trades.append({
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "price": price,
        })

    def check_stop_loss_take_profit(self, positions: dict[str, Position]) -> list[tuple[str, str, float]]:
        """Returns list of (symbol, 'SELL', qty) for positions that hit SL or TP."""
        exits = []
        for symbol, pos in positions.items():
            if pos.avg_cost <= 0:
                continue
            pnl_pct = pos.unrealized_pnl_pct
            if pnl_pct <= -config.STOP_LOSS_PCT:
                logger.warning(f"STOP LOSS triggered for {symbol}: {pnl_pct:.2%}")
                exits.append((symbol, "SELL", pos.qty))
            elif pnl_pct >= config.TAKE_PROFIT_PCT:
                logger.info(f"TAKE PROFIT triggered for {symbol}: {pnl_pct:.2%}")
                exits.append((symbol, "SELL", pos.qty))
        return exits
