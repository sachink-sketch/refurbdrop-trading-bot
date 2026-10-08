#!/usr/bin/env python3
"""
AI Trading Bot — powered by Claude
Usage:
    python main.py               # Run bot (paper or live based on .env)
    python main.py --paper       # Force paper trading mode
    python main.py --live        # Force live trading (override PAPER_TRADING=true)
    python main.py --once        # Run one cycle and exit
    python main.py --auth        # First-time OAuth setup for TD Ameritrade/Schwab
    python main.py --status      # Print portfolio status and exit
"""
import argparse
import sys
import time
import os
import schedule
from pathlib import Path

# Ensure trading_bot directory is in path
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from utils.logger import logger, console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint


def banner():
    try:
        rprint(Panel.fit(
            "[bold cyan]AI Trading Bot[/bold cyan]\n"
            f"[dim]Powered by Claude claude-opus-5-5 | Broker: {config.BROKER}[/dim]\n"
            f"[{'bold yellow' if config.PAPER_TRADING else 'bold red'}]"
            f"{'PAPER TRADING MODE' if config.PAPER_TRADING else 'LIVE TRADING - REAL MONEY'}[/]",
            title="[bold]REFURBDROP Trading Bot[/bold]",
            border_style="cyan",
        ))
    except Exception:
        mode = "PAPER" if config.PAPER_TRADING else "LIVE"
        print(f"=== REFURBDROP Trading Bot | {config.BROKER} | {mode} ===")


def run_bot(paper_override: bool = False, once: bool = False, force_run: bool = False):
    banner()

    # Validate config
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error(f"Config error: {err}")
        logger.error("Fix .env file and restart. Copy trading_bot/.env.example → trading_bot/.env")
        sys.exit(1)

    if paper_override:
        config.PAPER_TRADING = True

    # Create broker
    from brokers import get_broker
    broker = get_broker()
    if not broker.login():
        logger.error("Broker login failed. Check credentials in .env")
        sys.exit(1)

    from bot import TradingBot
    bot = TradingBot(broker, force_run=force_run)

    if once or force_run:
        bot.run_cycle()
        return

    logger.info(f"Bot starting — scanning every {config.TRADE_INTERVAL_MINUTES} minute(s)")
    logger.info(f"Watchlist: {', '.join(config.WATCHLIST)}")

    # Run immediately, then schedule
    bot.run_cycle()
    schedule.every(config.TRADE_INTERVAL_MINUTES).minutes.do(bot.run_cycle)

    while True:
        try:
            schedule.run_pending()
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("\nBot stopped by user.")
            break


def show_status():
    banner()
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    from brokers import get_broker
    broker = get_broker()
    if not broker.login():
        sys.exit(1)
    cash = broker.get_cash()
    total = broker.get_portfolio_value()
    positions = broker.get_positions()

    table = Table(title="Portfolio Status", show_header=True, header_style="bold cyan")
    table.add_column("Symbol")
    table.add_column("Qty", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Mkt Value", justify="right")
    table.add_column("P&L %", justify="right")

    for symbol, pos in positions.items():
        color = "green" if pos.unrealized_pnl >= 0 else "red"
        table.add_row(
            symbol,
            f"{pos.qty:.4f}",
            f"${pos.avg_cost:.2f}",
            f"${pos.current_price:.2f}",
            f"${pos.market_value:,.2f}",
            f"[{color}]{pos.unrealized_pnl_pct:+.2%}[/]",
        )

    rprint(table)
    logger.info(f"Cash: ${cash:,.2f}  |  Total: ${total:,.2f}")


def td_auth():
    """First-time OAuth flow for TD Ameritrade / Schwab."""
    logger.info("Starting TD Ameritrade / Schwab OAuth flow...")
    try:
        import schwab
        schwab.auth.easy_client(
            api_key=config.TD_CLIENT_ID,
            app_secret=config.TD_CLIENT_SECRET,
            callback_url=config.TD_REDIRECT_URI,
            token_path=config.TD_TOKEN_PATH,
        )
        logger.info(f"Token saved to {config.TD_TOKEN_PATH}")
    except ImportError:
        logger.error("schwab-py not installed. Run: pip install schwab-py")
    except Exception as e:
        logger.error(f"Auth failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Trading Bot powered by Claude")
    parser.add_argument("--paper", action="store_true", help="Force paper trading")
    parser.add_argument("--live", action="store_true", help="Force live trading (overrides PAPER_TRADING=true)")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--demo", action="store_true", help="Run one cycle ignoring market hours (for testing)")
    parser.add_argument("--auth", action="store_true", help="TD Ameritrade first-time OAuth setup")
    parser.add_argument("--status", action="store_true", help="Print portfolio and exit")
    args = parser.parse_args()

    if args.live:
        config.PAPER_TRADING = False

    if args.auth:
        td_auth()
    elif args.status:
        show_status()
    elif args.demo:
        run_bot(paper_override=True, once=True, force_run=True)
    else:
        run_bot(paper_override=args.paper, once=args.once)
