"""Main bot orchestrator — one cycle = scan watchlist + execute signals."""
import time
from datetime import datetime
from brokers.base import BaseBroker
from analysis.claude_analyst import ClaudeAnalyst
from analysis.indicators import add_indicators, summarize_indicators
from risk.manager import RiskManager
from utils.market_data import market_data
from utils.logger import logger
from config import config
import firebase_writer as fb


class TradingBot:
    def __init__(self, broker: BaseBroker, force_run: bool = False):
        self.broker = broker
        self.analyst = ClaudeAnalyst()
        self.risk = RiskManager(broker)
        self._cycle_count = 0
        self._force_run = force_run

    def run_cycle(self):
        """One full scan-and-trade cycle across the entire watchlist."""
        self._cycle_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Cycle #{self._cycle_count} — {now}")
        logger.info(f"{'=' * 60}")

        if not self._force_run and not market_data.is_market_open():
            logger.info("Market is closed. Sleeping until next cycle.")
            return

        # ---- Check stop-loss / take-profit on existing positions ----
        try:
            positions = self.broker.get_positions()
            exits = self.risk.check_stop_loss_take_profit(positions)
            for symbol, action, qty in exits:
                self._execute_exit(symbol, qty, reason="SL/TP")
        except Exception as e:
            logger.error(f"Error checking SL/TP: {e}")

        # ---- Scan watchlist for new signals ----
        portfolio_ctx = self.broker.get_portfolio_context()
        positions = self.broker.get_positions()

        for symbol in config.WATCHLIST:
            try:
                self._analyze_and_trade(symbol, portfolio_ctx, positions)
                time.sleep(1)   # Gentle rate limit between symbols
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)

        # ---- Print portfolio summary ----
        self._print_summary()

    def _analyze_and_trade(self, symbol: str, portfolio_ctx: dict, positions: dict):
        # Fetch data
        df = market_data.get_ohlcv(symbol, period="5d", interval="5m")
        df = add_indicators(df)
        indicators = summarize_indicators(df)
        news = market_data.get_news_headlines(symbol)

        # Claude AI decision
        signal = self.analyst.analyze(symbol, indicators, news, portfolio_ctx, {
            s: {"qty": p.qty, "avg_cost": p.avg_cost, "pnl_pct": p.unrealized_pnl_pct}
            for s, p in positions.items()
        })

        if signal.action == "HOLD":
            return

        # Risk check
        risk_result = self.risk.check_signal(signal)
        if not risk_result.approved:
            logger.info(f"{symbol}: Risk rejected — {risk_result.reason}")
            return

        # Execute
        if signal.action == "BUY":
            self._execute_buy(symbol, risk_result.adjusted_qty, signal)
        elif signal.action == "SELL":
            self._execute_sell(symbol, risk_result.adjusted_qty, signal)

    def _execute_buy(self, symbol: str, qty: float, signal=None):
        try:
            result = self.broker.buy_market(symbol, qty)
            self.risk.record_trade(symbol, "BUY", qty, result.price)
            fb.push_async(fb.push_trade_event, "BUY", symbol, result.price)
        except Exception as e:
            logger.error(f"Buy order failed for {symbol}: {e}")

    def _execute_sell(self, symbol: str, qty: float, signal=None):
        try:
            positions = self.broker.get_positions()
            pos = positions.get(symbol)
            result = self.broker.sell_market(symbol, qty)
            self.risk.record_trade(symbol, "SELL", qty, result.price)
            if pos and signal:
                entry = pos.avg_cost
                pnl_pct = (result.price - entry) / entry if entry else 0
                self.analyst.record_trade_outcome(symbol, "SELL", entry, result.price, pnl_pct)
                fb.push_async(fb.push_trade_event, "SELL", symbol, result.price, pnl_pct)
        except Exception as e:
            logger.error(f"Sell order failed for {symbol}: {e}")

    def _execute_exit(self, symbol: str, qty: float, reason: str = ""):
        try:
            positions = self.broker.get_positions()
            pos = positions.get(symbol)
            result = self.broker.sell_market(symbol, qty)
            self.risk.record_trade(symbol, "SELL", qty, result.price)
            if pos:
                pnl_pct = (result.price - pos.avg_cost) / pos.avg_cost if pos.avg_cost else 0
                self.analyst.record_trade_outcome(symbol, "SELL", pos.avg_cost, result.price, pnl_pct)
                fb.push_async(fb.push_trade_event, "STOP LOSS", symbol, result.price, pnl_pct)
            logger.info(f"Exit {symbol} ({reason}) complete")
        except Exception as e:
            logger.error(f"Exit order failed for {symbol}: {e}")

    def _print_summary(self):
        try:
            cash = self.broker.get_cash()
            total = self.broker.get_portfolio_value()
            positions = self.broker.get_positions()
            logger.info(f"\nPORTFOLIO SUMMARY")
            logger.info(f"  Cash:          ${cash:>12,.2f}")
            logger.info(f"  Total value:   ${total:>12,.2f}")
            logger.info(f"  Positions ({len(positions)}):")
            for symbol, pos in positions.items():
                direction = "+" if pos.unrealized_pnl >= 0 else "-"
                logger.info(
                    f"    [{direction}] {symbol}: {pos.qty:.4f} shares @ ${pos.avg_cost:.2f} "
                    f"-> ${pos.current_price:.2f} ({pos.unrealized_pnl_pct:+.2%}) "
                    f"= ${pos.unrealized_pnl:+.2f}"
                )
            # Push stock bot state to Firebase dashboard
            fb.push_async(fb.push_status, total, 0.0, 0.0, self._cycle_count)
            fb.push_async(fb.push_positions, positions)
        except Exception as e:
            logger.error(f"Error printing summary: {e}")
