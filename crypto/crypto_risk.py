from datetime import date
from crypto.exchanges.base_exchange import BaseCryptoExchange, CryptoPosition
from crypto.claude_crypto import CryptoSignal
from crypto.crypto_config import crypto_config
from utils.logger import logger


class CryptoRiskManager:
    def __init__(self, exchange: BaseCryptoExchange):
        self._exchange = exchange
        self._daily_start_value: float | None = None
        self._today = date.today()

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._today:
            self._daily_start_value = None
            self._today = today

    def _daily_start(self) -> float:
        if self._daily_start_value is None:
            self._daily_start_value = self._exchange.get_portfolio_value()
        return self._daily_start_value

    def check(self, signal: CryptoSignal, positions: dict) -> tuple[bool, str]:
        self._reset_if_new_day()

        if signal.action == "HOLD":
            return True, "HOLD"

        # Confidence gate
        if signal.confidence < crypto_config.MIN_CONFIDENCE:
            return False, f"Confidence {signal.confidence:.0%} < {crypto_config.MIN_CONFIDENCE:.0%}"

        # Daily loss circuit breaker
        portfolio = self._exchange.get_portfolio_value()
        start = self._daily_start()
        if start > 0:
            daily_loss = (start - portfolio) / start
            if daily_loss >= crypto_config.MAX_DAILY_LOSS_PCT:
                return False, f"Daily loss limit hit: {daily_loss:.2%}"

        # Max open trades
        if signal.action == "BUY" and len(positions) >= crypto_config.MAX_OPEN_TRADES:
            return False, f"Max open trades reached ({crypto_config.MAX_OPEN_TRADES})"

        # Don't double-buy same pair
        if signal.action == "BUY" and signal.pair in positions:
            return False, f"Already holding {signal.pair}"

        # Can't sell what we don't have
        if signal.action == "SELL" and signal.pair not in positions:
            return False, f"No position in {signal.pair}"

        # Minimum trade size
        usdt = self._exchange.get_usdt_balance()
        if signal.action == "BUY":
            max_allowed = min(
                usdt * crypto_config.MAX_POSITION_PCT,
                signal.usdt_amount,
            )
            if max_allowed < 1.0:
                return False, f"Trade too small: ${max_allowed:.2f}"
            signal.usdt_amount = max_allowed

        return True, "Approved"

    def check_sl_tp(self, positions: dict[str, CryptoPosition]) -> list[tuple[str, float]]:
        """Returns list of (pair, qty) to sell for SL or TP hits."""
        exits = []
        for pair, pos in positions.items():
            pnl = pos.unrealized_pnl_pct
            if pnl <= -crypto_config.STOP_LOSS_PCT:
                logger.warning(f"STOP LOSS {pair}: {pnl:.3%}")
                exits.append((pair, pos.qty))
            elif pnl >= crypto_config.TAKE_PROFIT_PCT:
                logger.info(f"TAKE PROFIT {pair}: {pnl:.3%}")
                exits.append((pair, pos.qty))
        return exits
