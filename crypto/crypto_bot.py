"""Crypto micro-trading bot — multi-timeframe + sentiment gating, ATR stops, partial exits, trailing stops."""
import time
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anthropic
from datetime import datetime, timedelta
from crypto.exchanges.base_exchange import BaseCryptoExchange
from crypto.claude_crypto import ClaudeCryptoAnalyst
from crypto.crypto_risk import CryptoRiskManager
from crypto.crypto_config import crypto_config
from crypto.trailing_stop import TrailingStopManager
from crypto.market_context import get_fear_greed
from crypto.notifier import notify
from crypto.signal_tracker import SignalTracker
from analysis.indicators import add_indicators, summarize_indicators
from utils.logger import logger
import firebase_writer as fb

_ENTRY_PRICES_FILE = os.path.join(os.path.dirname(__file__), "../logs/entry_prices.json")
_META_FILE = os.path.join(os.path.dirname(__file__), "../logs/position_meta.json")
_SESSION_FILE = os.path.join(os.path.dirname(__file__), "../logs/daily_baseline.json")

_LLM_RETRY_SECONDS = 3600
_HTF_CACHE_SECONDS = 600
_PARTIAL_AT_FRACTION_OF_TP = 0.5
_MIN_PARTIAL_USD = 5.0


def _atr_levels(ind: dict) -> tuple[float, float]:
    """Volatility-scaled (stop, target): stop = 2x ATR clamped to 0.6-2.0%, target = 2.5x stop."""
    price, atr = ind.get("price") or 0, ind.get("atr") or 0
    if price <= 0 or atr <= 0:
        return crypto_config.STOP_LOSS_PCT, crypto_config.TAKE_PROFIT_PCT
    sl = min(max(2.0 * atr / price, 0.006), 0.02)
    return sl, sl * 2.5


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: str, data: dict):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"[BOT] Could not save {os.path.basename(path)}: {e}")


class CryptoBot:
    def __init__(self, exchange: BaseCryptoExchange):
        self.exchange = exchange
        self.analyst  = ClaudeCryptoAnalyst()
        self.risk     = CryptoRiskManager(exchange)
        self.tracker  = SignalTracker()
        self._cycle   = 0
        self._entry_times: dict[str, datetime] = {}
        self._entry_prices: dict[str, float] = self._load_entry_prices()
        self._meta: dict[str, dict] = _load_json(_META_FILE)
        self._cycle_signals: list[dict] = []
        self._fg: dict = {"value": 50, "label": "Neutral"}
        self._htf_cache: dict[str, tuple[float, dict]] = {}
        self._quotes: dict[str, tuple[float, float]] = {}   # pair -> (bid, ask) from the latest scan
        self._llm_down_until = 0.0   # Claude scan paused (credits exhausted) until this epoch time
        self._trailing = TrailingStopManager(
            trail_pct       = crypto_config.TRAIL_PCT,
            take_profit_pct = crypto_config.TAKE_PROFIT_PCT,
            activate_pct    = crypto_config.TRAIL_ACTIVATE_PCT,
        )

    def _load_entry_prices(self) -> dict[str, float]:
        data = _load_json(_ENTRY_PRICES_FILE)
        if data:
            logger.info(f"[BOT] Loaded entry prices for {list(data.keys())}")
        return data

    def _save_entry_prices(self):
        _save_json(_ENTRY_PRICES_FILE, self._entry_prices)

    def _save_meta(self):
        _save_json(_META_FILE, self._meta)

    def _cost_basis(self, pair: str, avg_entry: float) -> float:
        """What we really paid: the real buy fill if known, else the tracked entry (legacy holdings)."""
        return self._meta.get(pair, {}).get("fill") or avg_entry

    def _exit_value(self, pair: str, pos) -> float:
        """Price we'd actually get selling now: the bid, falling back to the mark."""
        q = self._quotes.get(pair)
        return q[0] if q else pos.current_price

    def _llm_paused(self) -> bool:
        return time.time() < self._llm_down_until

    def _is_protected(self, pair: str) -> bool:
        """Long-term holdings the bot must never auto-sell (set "protected": true in position_meta.json)."""
        return bool(self._meta.get(pair, {}).get("protected"))

    def _unprotected(self, positions: dict) -> dict:
        return {p: pos for p, pos in positions.items() if not self._is_protected(p)}

    def _levels(self, pair: str) -> tuple[float, float]:
        m = self._meta.get(pair, {})
        return m.get("sl", crypto_config.STOP_LOSS_PCT), m.get("tp", crypto_config.TAKE_PROFIT_PCT)

    def _apply_entry_overrides(self, positions: dict) -> dict:
        """Patch avg_entry from our tracked prices — more reliable than Robinhood cost_bases.

        Robinhood returns no cost basis for some legacy holdings and the exchange then falls back to
        the live price, pinning P&L at 0%. Pin the first-seen price so SL/TP/trailing measure real moves.
        """
        pinned = False
        for pair, pos in positions.items():
            if pair not in self._entry_prices and pos.value_usdt >= 5.0 and pos.avg_entry > 0:
                self._entry_prices[pair] = pos.avg_entry
                pinned = True
                logger.info(f"[BOT] Pinned entry for {pair} @ ${pos.avg_entry:.4f} (no cost basis on record)")
            if pair in self._entry_prices:
                pos.avg_entry = self._entry_prices[pair]
        if pinned:
            self._save_entry_prices()
        return positions

    def _daily_baseline(self, total: float) -> float:
        """Portfolio value at the start of today; persisted so bot restarts don't reset P&L."""
        today = datetime.now().date().isoformat()
        d = _load_json(_SESSION_FILE)
        if d.get("date") != today or not d.get("value"):
            d = {"date": today, "value": total}
            _save_json(_SESSION_FILE, d)
        return d["value"]

    def run_cycle(self):
        self._cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n{'=' * 56}")
        logger.info(f"CRYPTO Cycle #{self._cycle} -- {now}")
        logger.info(f"{'=' * 56}")

        self._fg = get_fear_greed()

        # 1. Fixed/ATR SL/TP check
        try:
            positions = self._unprotected(self._apply_entry_overrides(self.exchange.get_positions()))
            levels = {p: self._levels(p) for p in positions}
            for pair, qty in self.risk.check_sl_tp(positions, levels):
                self._sell(pair, qty, reason="SL/TP")
        except Exception as e:
            logger.error(f"SL/TP check error: {e}")

        # 2. Trailing stop check (also re-arms stops for positions that survived a restart)
        try:
            positions = self._unprotected(self._apply_entry_overrides(self.exchange.get_positions()))
            for pair, pos in positions.items():
                if pos.value_usdt >= 5.0 and not self._trailing.is_registered(pair):
                    sl, tp = self._levels(pair)
                    self._trailing.register(pair, pos.avg_entry, max(sl * 0.45, 0.0025), tp, sl)
            prices = {pair: pos.current_price for pair, pos in positions.items()}
            for pair in self._trailing.update_all(prices):
                pos = positions.get(pair)
                if pos:
                    self._sell(pair, pos.qty, reason="TRAIL")
        except Exception as e:
            logger.error(f"Trailing stop check error: {e}")

        # 2b. Partial profit: bank half at 50% of the target, let the rest ride the trailing stop
        try:
            positions = self._unprotected(self._apply_entry_overrides(self.exchange.get_positions()))
            for pair, pos in positions.items():
                _, tp = self._levels(pair)
                done = self._meta.get(pair, {}).get("partial_done", False)
                if (not done and pos.value_usdt * 0.5 >= _MIN_PARTIAL_USD
                        and pos.unrealized_pnl_pct >= tp * _PARTIAL_AT_FRACTION_OF_TP):
                    self._sell_partial(pair, pos)
        except Exception as e:
            logger.error(f"Partial exit check error: {e}")

        # 3. Time-based exit — free up capital stuck in chop
        try:
            positions = self._apply_entry_overrides(self.exchange.get_positions())
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
        positions = self._apply_entry_overrides(self.exchange.get_positions())

        if self._llm_paused():
            mins = int((self._llm_down_until - time.time()) / 60) + 1
            logger.warning(f"Claude scan paused (API credits exhausted) — managing existing positions only; retry in ~{mins}m")
            for pair in positions:
                ba = self.exchange.get_bid_ask(pair)
                if ba:
                    self._quotes[pair] = ba
        else:
            for pair in crypto_config.PAIRS:
                if pair in crypto_config.EXCLUDED_PAIRS:
                    continue
                try:
                    self._analyze_and_trade(pair, usdt, positions)
                    time.sleep(0.5)
                except anthropic.BadRequestError as e:
                    if "credit balance" in str(e).lower():
                        self._llm_down_until = time.time() + _LLM_RETRY_SECONDS
                        logger.warning("Claude API credits exhausted — pausing scan for 1h (stops/trailing keep running)")
                        notify("Bot: Anthropic credits exhausted. Scanning paused; existing positions still managed.")
                        break
                    logger.error(f"Error on {pair}: {e}", exc_info=False)
                except Exception as e:
                    logger.error(f"Error on {pair}: {e}", exc_info=False)

        try:
            self._print_summary()
        except Exception as e:
            logger.error(f"[BOT] Summary error: {e}")

    def _get_higher_tf(self, pair: str) -> dict:
        cached = self._htf_cache.get(pair)
        if cached and time.time() - cached[0] < _HTF_CACHE_SECONDS:
            return cached[1]
        try:
            df = self.exchange.get_ohlcv(pair, timeframe="1h", limit=100)
            ind = summarize_indicators(add_indicators(df))
        except Exception as e:
            logger.debug(f"1H data unavailable for {pair}: {e}")
            ind = cached[1] if cached else {}
        self._htf_cache[pair] = (time.time(), ind)
        return ind

    def _apply_context(self, signal, ind: dict, ind_1h: dict, spread: float | None = None):
        """Adjust a BUY for 1H trend + market sentiment, and set ATR-scaled stop/target."""
        notes = []
        if signal.action == "BUY":
            if ind_1h:
                above50, macd = ind_1h.get("price_above_ema50"), ind_1h.get("macd_bullish")
                if not above50 and not macd:
                    signal.confidence = max(0.0, signal.confidence - 0.10)
                    notes.append("1H bearish -10%")
                elif above50 and macd:
                    signal.confidence = min(0.95, signal.confidence + 0.05)
                    notes.append("1H bullish +5%")
            fg = self._fg["value"]
            if fg < 20:
                signal.action = "HOLD"
                notes.append(f"BLOCKED: extreme fear ({fg})")
            elif (fg < 35 or fg > 80) and signal.confidence < 0.75:
                signal.action = "HOLD"
                notes.append(f"BLOCKED: F&G {fg} needs 75%+")
            elif fg < 35:
                signal.usdt_amount *= 0.5
                notes.append(f"F&G {fg}: half size")
        signal.stop_loss_pct, signal.take_profit_pct = _atr_levels(ind)
        if signal.action == "BUY" and spread is not None:
            tp, sl = signal.take_profit_pct, signal.stop_loss_pct
            if spread > crypto_config.MAX_SPREAD_PCT or tp < crypto_config.SPREAD_COST_MULT * spread:
                signal.action = "HOLD"
                notes.append(f"BLOCKED: spread {spread:.2%} too wide for {tp:.1%} target")
            else:
                breakeven = (sl + spread) / (tp + sl)
                notes.append(f"spread {spread:.2%}, breakeven win rate {breakeven:.0%}")
        if notes:
            signal.reasoning = f"[{'; '.join(notes)}] {signal.reasoning}"
            logger.info(f"  {signal.pair} context: {'; '.join(notes)}")

    def _analyze_and_trade(self, pair: str, usdt: float, positions: dict):
        # Skip pairs unsupported by the current exchange (e.g. BNB on Robinhood)
        if hasattr(self.exchange, "supports_pair") and not self.exchange.supports_pair(pair):
            return
        df = self.exchange.get_ohlcv(
            pair, timeframe=crypto_config.CANDLE_TIMEFRAME, limit=crypto_config.CANDLE_LIMIT
        )
        df  = add_indicators(df)
        ind = summarize_indicators(df)
        ind_1h = self._get_higher_tf(pair)

        signal = self.analyst.analyze(
            pair, ind, usdt,
            {p: {"qty": pos.qty, "entry": pos.avg_entry, "pnl_pct": pos.unrealized_pnl_pct}
             for p, pos in positions.items()},
            higher_tf=ind_1h,
            fear_greed=self._fg,
            calibration=self.tracker.prompt_summary(),
        )
        spread = None
        ba = self.exchange.get_bid_ask(pair)
        if ba:
            self._quotes[pair] = ba
            spread = (ba[1] - ba[0]) / ((ba[0] + ba[1]) / 2)
        self._apply_context(signal, ind, ind_1h, spread)

        self._cycle_signals.append({
            "spread_pct": round(spread * 100, 3) if spread is not None else None,
            "pair":       pair,
            "action":     signal.action,
            "confidence": round(signal.confidence * 100),
            "reason":     signal.reasoning[:120],
            "sl_pct":     round(signal.stop_loss_pct * 100, 2),
            "tp_pct":     round(signal.take_profit_pct * 100, 2),
        })

        if signal.action == "HOLD":
            return

        ok, reason = self.risk.check(signal, self._unprotected(positions))
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
            # Stops/trailing watch the mark price, so they key off the mark at entry;
            # "fill" is what we really paid and drives all reported P&L.
            trigger_entry = order.mark_price or order.price
            self._entry_times[pair] = datetime.now()
            self._entry_prices[pair] = trigger_entry
            self._save_entry_prices()
            sl, tp = signal.stop_loss_pct, signal.take_profit_pct
            self._meta[pair] = {"sl": sl, "tp": tp, "partial_done": False, "fill": order.price}
            self._save_meta()
            self._trailing.register(pair, trigger_entry, max(sl * 0.45, 0.0025), tp, sl)
            self.tracker.record_entry(pair, signal.confidence)
            logger.info(
                f"  Factors: {', '.join(signal.key_factors[:3])}\n"
                f"  SL: {sl:.1%}  TP: {tp:.1%}  (ATR-scaled)  fill ${order.price:,.4f} vs mark ${trigger_entry:,.4f}"
            )
            fb.push_async(fb.push_trade_event, "BUY", pair, order.price)
            notify(f"BUY {pair} @ ${order.price:,.4f} | conf {signal.confidence:.0%} | SL {sl:.2%} TP {tp:.2%}")
        except Exception as e:
            logger.error(f"BUY {pair} failed: {e}")

    def _sell_partial(self, pair: str, pos):
        if self._is_protected(pair):
            return
        try:
            qty = pos.qty * 0.5
            order = self.exchange.sell_market(pair, qty)
            cost = self._cost_basis(pair, pos.avg_entry)
            self._meta.setdefault(pair, {}).update(partial_done=True)
            self._save_meta()
            pnl_pct = (order.price - cost) / cost if cost else 0
            logger.info(f"  PARTIAL TP {pair}: sold half at {pnl_pct:+.2%} (real fill), rest rides trailing stop")
            fb.push_async(fb.push_trade_event, "PARTIAL TP", pair, order.price, pnl_pct)
            notify(f"PARTIAL TP {pair}: sold half @ ${order.price:,.4f} ({pnl_pct:+.2%})")
        except Exception as e:
            logger.error(f"PARTIAL sell {pair} failed: {e}")

    def _sell(self, pair: str, qty: float, signal=None, reason: str = ""):
        if self._is_protected(pair):
            logger.warning(f"SELL {pair} skipped: protected long-term holding")
            return
        try:
            positions = self._apply_entry_overrides(self.exchange.get_positions())
            pos = positions.get(pair)
            order = self.exchange.sell_market(pair, qty)
            cost = self._cost_basis(pair, pos.avg_entry) if pos else 0
            self._entry_times.pop(pair, None)
            self._entry_prices.pop(pair, None)
            self._save_entry_prices()
            self._meta.pop(pair, None)
            self._save_meta()
            self._trailing.remove(pair)
            if pos:
                pnl_pct = (order.price - cost) / cost if cost else 0
                pnl_usd = (order.price - cost) * qty
                tag = f"[{reason}]" if reason else ""
                logger.info(
                    f"  CLOSED {tag} {pair}: {pnl_pct:+.2%} (${pnl_usd:+.2f}) "
                    f"real fill ${order.price:,.4f} vs cost ${cost:,.4f}"
                )
                self.analyst.record_outcome(pair, "SELL", cost, order.price, pnl_pct)
                self.tracker.record_exit(pair, pnl_pct)
                event_type = {"SL/TP": "STOP LOSS", "TRAIL": "TRAILING STOP", "TIME": "TIME EXIT"}.get(reason, "SELL")
                fb.push_async(fb.push_trade_event, event_type, pair, order.price, pnl_pct)
                notify(f"{event_type} {pair} @ ${order.price:,.4f} ({pnl_pct:+.2%}, ${pnl_usd:+.2f})")
        except Exception as e:
            logger.error(f"SELL {pair} failed: {e}")

    def _print_summary(self):
        usdt      = self.exchange.get_usdt_balance()
        total     = self.exchange.get_portfolio_value()
        positions = self._apply_entry_overrides(self.exchange.get_positions())

        logger.info(f"\nPORTFOLIO  USDT: ${usdt:,.2f}  |  Total: ${total:,.2f}")
        # Mark value overstates what we could cash out; use the bid-based liquidation value for P&L.
        net_pnl, costs = {}, {}
        liq_positions = 0.0
        for pair, pos in positions.items():
            exit_px = self._exit_value(pair, pos)
            liq_positions += pos.qty * exit_px
            cost = self._cost_basis(pair, pos.avg_entry)
            if cost:
                net_pnl[pair] = (exit_px - cost) / cost
                costs[pair] = cost
        liquidation = usdt + liq_positions
        logger.info(f"LIQUIDATION VALUE (at bid): ${liquidation:,.2f}  (spread haircut ${total - liquidation:,.2f})")
        total = liquidation
        pnl_pct, pnl_usd = 0.0, 0.0
        base = getattr(self.exchange, "_starting_usdt", None) or self._daily_baseline(total)
        if base:
            pnl_usd = total - base
            pnl_pct = pnl_usd / base
            logger.info(f"Session P&L: {pnl_pct:+.2%}  (${pnl_usd:+.2f})")

        # Push to Firebase (non-blocking)
        fb.push_async(
            fb.push_status, total, pnl_pct, pnl_usd, self._cycle,
            self.tracker.daily_trades(), self.tracker.win_rate(), crypto_config.MAX_OPEN_TRADES,
        )
        fb.push_async(fb.push_positions, positions, net_pnl, costs)
        fb.push_async(fb.push_equity, total)
        fb.push_async(fb.push_market, self._fg, self._llm_paused())
        fb.push_async(fb.push_accuracy, self.tracker.summary())
        if self._cycle_signals:
            fb.push_async(fb.push_signals, self._cycle_signals)
            self._cycle_signals = []

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
