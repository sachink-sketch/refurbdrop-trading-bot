#!/usr/bin/env python3
"""
Crypto Micro-Trading Bot — powered by Claude AI
Usage:
    python crypto/main_crypto.py           # Run (paper by default)
    python crypto/main_crypto.py --demo    # Single cycle demo
    python crypto/main_crypto.py --live    # Live trading (set CRYPTO_EXCHANGE in .env)
    python crypto/main_crypto.py --cycles 5  # Run N cycles then exit
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import time
import schedule
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from crypto.crypto_config import crypto_config
from utils.logger import logger


def banner(exchange_name: str):
    rprint(Panel.fit(
        f"[bold cyan]Crypto Micro-Trading Bot[/bold cyan]\n"
        f"[dim]Claude claude-opus-5-5 | Exchange: {exchange_name}[/dim]\n"
        f"[bold yellow]PAPER MODE — ${ crypto_config.PAPER_STARTING_USDT:,.0f} virtual USDT[/bold yellow]"
        if exchange_name == "PAPER" else
        f"[bold red]LIVE TRADING — {exchange_name}[/bold red]",
        title="[bold]REFURBDROP Crypto Bot[/bold]",
        border_style="magenta",
    ))


def run(demo: bool = False, live: bool = False, cycles: int = 0):
    errors = crypto_config.validate()
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    # Auto-detect live mode: if CRYPTO_EXCHANGE is set to anything other than PAPER, go live
    if not live and crypto_config.EXCHANGE not in ("PAPER", ""):
        live = True
    if live:
        crypto_config.EXCHANGE = os.getenv("CRYPTO_EXCHANGE", "ROBINHOOD")

    from crypto.exchanges import get_exchange
    exchange = get_exchange(force_paper=not live)
    banner(exchange.__class__.__name__.replace("CryptoExchange", "").replace("Paper", "PAPER").replace("Live", live and crypto_config.EXCHANGE or "LIVE"))

    from crypto.crypto_bot import CryptoBot
    bot = CryptoBot(exchange)

    logger.info(f"Pairs: {', '.join(crypto_config.PAIRS)}")
    logger.info(f"Timeframe: {crypto_config.CANDLE_TIMEFRAME}  |  Scan every {crypto_config.SCAN_INTERVAL_SECONDS}s")
    logger.info(f"SL: {crypto_config.STOP_LOSS_PCT:.1%}  TP: {crypto_config.TAKE_PROFIT_PCT:.1%}  Min conf: {crypto_config.MIN_CONFIDENCE:.0%}")
    logger.info("")

    if demo:
        bot.run_cycle()
        return

    if cycles > 0:
        for i in range(cycles):
            bot.run_cycle()
            if i < cycles - 1:
                logger.info(f"Waiting {crypto_config.SCAN_INTERVAL_SECONDS}s...")
                time.sleep(crypto_config.SCAN_INTERVAL_SECONDS)
        return

    # Continuous mode
    def safe_cycle():
        try:
            bot.run_cycle()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[BOT] Cycle error (will retry next cycle in {crypto_config.SCAN_INTERVAL_SECONDS}s): {e}")

    safe_cycle()
    schedule.every(crypto_config.SCAN_INTERVAL_SECONDS).seconds.do(safe_cycle)
    logger.info(f"Running continuously every {crypto_config.SCAN_INTERVAL_SECONDS}s. Ctrl+C to stop.")
    while True:
        try:
            schedule.run_pending()
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Crypto bot stopped.")
            break
        except Exception as e:
            logger.error(f"[BOT] Main loop error (continuing): {e}")
            time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto micro-trading bot")
    parser.add_argument("--demo",   action="store_true", help="Single demo cycle")
    parser.add_argument("--live",   action="store_true", help="Live trading")
    parser.add_argument("--cycles", type=int, default=0, help="Run N cycles then exit")
    args = parser.parse_args()
    run(demo=args.demo, live=args.live, cycles=args.cycles)
