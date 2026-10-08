"""
Resume the open positions from the demo run and watch until they close.
BNB @ $759.71  |  BTC @ $82,372.15
SL: -0.6%   TP: +1.2%
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crypto.crypto_config import crypto_config
from crypto.exchanges.paper_exchange import PaperCryptoExchange
from crypto.exchanges.base_exchange import CryptoPosition
from crypto.crypto_bot import CryptoBot
from utils.logger import logger

# ── Restore state from the demo run ──────────────────────────
crypto_config.MIN_CONFIDENCE = 0.40   # same as demo
crypto_config.STOP_LOSS_PCT   = 0.006  # 0.6%
crypto_config.TAKE_PROFIT_PCT = 0.012  # 1.2%

exchange = PaperCryptoExchange(starting_usdt=846.40)

# Re-plant the two open positions
exchange._positions = {
    "BNB/USDT": CryptoPosition("BNB/USDT", "BNB", "USDT",
                               qty=0.105303, avg_entry=759.71, current_price=759.71),
    "BTC/USDT": CryptoPosition("BTC/USDT", "BTC", "USDT",
                               qty=0.000894, avg_entry=82372.15, current_price=82372.15),
}

bot = CryptoBot(exchange)

logger.info("Watching open positions — waiting for TP (+1.2%) or SL (-0.6%) on each...")
logger.info(f"  BNB/USDT: 0.105303 @ $759.71   TP=${759.71*1.012:.2f}  SL=${759.71*0.994:.2f}")
logger.info(f"  BTC/USDT: 0.000894 @ $82372.15  TP=${82372.15*1.012:.2f}  SL=${82372.15*0.994:.2f}")
logger.info("")

cycle = 0
start_value = exchange.get_portfolio_value()

while True:
    cycle += 1
    positions_before = set(exchange._positions.keys())

    # Only run SL/TP check + existing-position management (skip new BUYs)
    from crypto.crypto_risk import CryptoRiskManager
    risk = CryptoRiskManager(exchange)
    positions = exchange.get_positions()

    exits = risk.check_sl_tp(positions)
    for pair, qty in exits:
        pos = positions[pair]
        order = exchange.sell_market(pair, qty)
        pnl_pct = (order.price - pos.avg_entry) / pos.avg_entry
        bot.analyst.record_outcome(pair, "SELL", pos.avg_entry, order.price, pnl_pct)

    positions_after = set(exchange._positions.keys())
    closed = positions_before - positions_after

    if closed:
        for pair in closed:
            logger.info(f"  Position CLOSED: {pair}")

    # Show live P&L every cycle
    current_value = exchange.get_portfolio_value()
    session_pnl   = current_value - start_value
    session_pct   = session_pnl / start_value

    open_pos = exchange.get_positions()
    if open_pos:
        pos_lines = []
        for pair, pos in open_pos.items():
            pos_lines.append(
                f"  {pair}: {pos.qty:.6f} @ ${pos.avg_entry:.2f} "
                f"now ${pos.current_price:.4f} ({pos.unrealized_pnl_pct:+.2%})"
            )
        logger.info(f"Cycle {cycle} | Total: ${current_value:.2f} | Session P&L: {session_pct:+.2%} (${session_pnl:+.2f})")
        for line in pos_lines:
            logger.info(line)
    else:
        # All positions closed — print final report
        final_value  = exchange.get_usdt_balance()
        total_pnl    = final_value - (846.40 + 80.00 + 73.60)  # vs original cost
        logger.info("")
        logger.info("=" * 56)
        logger.info("ALL POSITIONS CLOSED — FINAL P&L REPORT")
        logger.info("=" * 56)
        logger.info(f"  Starting capital (demo):  $1,000.00")
        logger.info(f"  Cost of BNB trade:           $80.00")
        logger.info(f"  Cost of BTC trade:           $73.60")
        logger.info(f"  USDT after trades:          $846.40")
        logger.info(f"  USDT after closing:       ${final_value:.2f}")
        logger.info(f"  ─────────────────────────────────────")
        net = final_value - 1000.0
        logger.info(f"  NET SESSION P&L:          ${net:+.2f}  ({net/1000*100:+.2f}%)")
        logger.info("=" * 56)
        break

    time.sleep(25)   # check every 25 seconds
