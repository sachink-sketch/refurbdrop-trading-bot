"""Crypto micro-trading bot — trailing stops + time exits + 5 simultaneous positions."""
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta
from crypto.exchanges.base_exchange import BaseCryptoExchange
from crypto.claude_crypto import ClaudeCryptoAnalyst
from crypto.crypto_risk import CryptoRiskManager
from crypto.crypto_config import crypto_config
from crypto.trailing_stop import TrailingStopManager
from analysis.indicators import add_indicators, summarize_indicators
from utils.logger import logger
import firebase_writer as fb


class CryptoBot:
    def __init__(self, exchange: BaseCryptoExchange):
        self.exchange = exchange
        self.analyst  = ClaudeCryptoAnalyst()
        self.risk     = CryptoRiskManager(exchange)
        self._cycle   = 0
        self._entry_times: dict[str, datetime] = {}
        self._trailing = TrailingStopManager(
            trail_pct       = crypto_config.TRAIL_PCT,
            take_profit_pct = crypto_config.TAKE_PROFIT_PCT,
            activate_pct    = crypto_config.TRAIL_ACTIVATE_PCT,
        )

    def run_cycle(self):
        self._cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n{'=' * 56}")
        logger.info(f"CRYPTO Cycle #{self._cycle} -- {now}")
        logger.info(f"{'=' * 56}")

        # 1. Fixed SL/TP check
        try:
            positions = self.exchange.get_positions()
            for pair, qty in self.risk.check_sl_tp(positions):
                self._sell(pair, qty, reason="SL/TP")
        except Exception as e:
            logger.error(f"SL/TP check error: {e}")

        # 2. Trailing stop check (once position hits +0.8% profit, replaces fixed TP)
        try:
            positions = self.exchange.get_positions()
            prices = {pair: pos.current_price for pair, pos in positions.items()}
            for pair in self._trailing.update_all(prices):
                pos = positions.get(pair)
                if pos:
                    self._sell(pair, pos.qty, reason="TRAIL")
        except Exception as e:
            logger.error(f"Trailing stop check error: {e}")

        # 3. Time-based exit — free up capital stuck in chop
        try:
            positions = self.exchange.get_positions()
            cutoff = datetime.now() - timedelta(minutes=crypto_config.TIME_EXIT_MINUTES)
            for pair, entry_time in list(self._entry_times.items()):
                if pair in positions and entry_time < cutoff:
                    mins = int((datetime.now() - entry_time).total_seconds() / 60)
                    pnl = positions[pair].unrealized_pnl_pct
                    logger.warning(
                        f"TIME EXIT {pair}: held {mins} min, P&L {pnl:+.2%} — freeing capital"
                    )
                    self._sell(pair, positions[pair].qty, reason="TIME")
        except Exception as e:
            logger.error(f"Time exit check error: {e}")

        # 4. Scan for new signals
        usdt     = self.exchange.get_usdt_balance()
        positions = self.exchange.get_positions()

        for pair in crypto_config.PAIRS:
            try:
                self._analyze_and_trade(pair, usdt, positions)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error on {pair}: {e}", exc_info=False)

        self._print_summary()

    def _analyze_and_trade(self, pair: str, usdt: float, positions: dict):
        # Skip pairs unsupported by the current exchange (e.g. BNB on Robinhood)
        if hasattr(self.exchange, "supports_pair") and not self.exchange.supports_pair(pair):
            return
        df = self.exchange.get_ohlcv(
            pair, timeframe=crypto_config.CANDLE_TIMEFRAME, limit=crypto_config.CANDLE_LIMIT
        )
        df  = add_indicators(df)
        ind = summarize_indicators(df)

        signal = self.analyst.analyze(pair, ind, usdt, {
            p: {"qty": pos.qty, "entry": pos.avg_entry, "pnl_pct": pos.unrealized_pnl_pct}
            for p, pos in positions.items()
        })

        if signal.action == "HOLD":
            return

        ok, reason = self.risk.check(signal, positions)
        if not ok:
            logger.debug(f"{pair}: blocked -- {reason}")
            return

        if signal.action == "BUY":
            self._buy(pair, signal)
        elif signal.action == "SELL":
            pos = positions.get(pair)
            if pos:
                self._sell(pair, pos.qty, signal)

    def _buy(self, pair: str, signal=None):
        try:
            order = self.exchange.buy_market(pair, signal.usdt_amount)
            self._entry_times[pair] = datetime.now()
            self._trailing.register(pair, order.price)
            if signal:
                logger.info(
                    f"  Factors: {', '.join(signal.key_factors[:3])}\n"
                    f"  SL: {signal.stop_loss_pct:.1%}  TP: {signal.take_profit_pct:.1%}"
                )
            fb.push_async(fb.push_trade_event, "BUY", pair, order.price)
        except Exception as e:
            logger.error(f"BUY {pair} failed: {e}")

    def _sell(self, pair: str, qty: float, signal=None, reason: str = ""):
        try:
            pos = self.exchange.get_positions().get(pair)
            order = self.exchange.sell_market(pair, qty)
            self._entry_times.pop(pair, None)
            self._trailing.remove(pair)
            if pos:
                pnl_pct = (order.price - pos.avg_entry) / pos.avg_entry if pos.avg_entry else 0
                tag = f"[{reason}]" if reason else ""
                logger.info(f"  CLOSED {tag} {pair}: {pnl_pct:+.2%} (${pnl_pct * pos.value_usdt:+.2f})")
                self.analyst.record_outcome(pair, "SELL", pos.avg_entry, order.price, pnl_pct)
                event_type = {"SL/TP": "STOP LOSS", "TRAIL": "TRAILING STOP", "TIME": "TIME EXIT"}.get(reason, "SELL")
                fb.push_async(fb.push_trade_event, event_type, pair, order.price, pnl_pct)
        except Exception as e:
            logger.error(f"SELL {pair} failed: {e}")

    def _print_summary(self):
        usdt      = self.exchange.get_usdt_balance()
        total     = self.exchange.get_portfolio_value()
        positions = self.exchange.get_positions()

        logger.info(f"\nPORTFOLIO  USDT: ${usdt:,.2f}  |  Total: ${total:,.2f}")
        pnl_pct, pnl_usd = 0.0, 0.0
        if hasattr(self.exchange, "_starting_usdt"):
            pnl_usd = total - self.exchange._starting_usdt
            pnl_pct = pnl_usd / self.exchange._starting_usdt
            logger.info(f"Session P&L: {pnl_pct:+.2%}  (${pnl_usd:+.2f})")

        # Push to Firebase (non-blocking)
        fb.push_async(fb.push_status, total, pnl_pct, pnl_usd, self._cycle)
        fb.push_async(fb.push_positions, positions)

        trail_status = self._trailing.status()
        if positions:
            logger.info(f"Open positions ({len(positions)}/{crypto_config.MAX_OPEN_TRADES}):")
            for pair, pos in positions.items():
                sign = "+" if pos.unrealized_pnl >= 0 else "-"
                mins_held = ""
                if pair in self._entry_times:
                    mins = int((datetime.now() - self._entry_times[pair]).total_seconds() / 60)
                    mins_held = f" {mins}m"
                trail_info = ""
                if pair in trail_status and trail_status[pair]["activated"]:
                    trail_info = f" trail>${trail_status[pair]['stop']:.2f}"
                logger.info(
                    f"  [{sign}] {pair}: {pos.qty:.6f} @ ${pos.avg_entry:.4f}"
                    f" now ${pos.current_price:.4f} ({pos.unrealized_pnl_pct:+.2%})"
                    f"{mins_held}{trail_info}"
                )
