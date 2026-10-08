"""Read-only connection test — no trades placed."""
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()
from config import config

errors = config.validate()
if errors:
    for e in errors:
        print("CONFIG ERROR:", e)
    sys.exit(1)

print("Config OK")
print("Broker:", config.BROKER)
print("Paper mode:", config.PAPER_TRADING)
print()

import robin_stocks.robinhood as rh

print("Attempting Robinhood login...")
try:
    kwargs = {
        "username": config.ROBINHOOD_USERNAME,
        "password": config.ROBINHOOD_PASSWORD,
        "store_session": True,
    }
    if config.ROBINHOOD_MFA_CODE:
        kwargs["mfa_code"] = config.ROBINHOOD_MFA_CODE

    result = rh.login(**kwargs)
    if not result:
        print("Login returned empty — check credentials")
        sys.exit(1)

    print("LOGIN SUCCESS\n")

    profile   = rh.profiles.load_account_profile()
    portfolio = rh.profiles.load_portfolio_profile()

    buying_power = float(profile.get("buying_power", 0))
    equity       = float(portfolio.get("equity", 0))
    prev_equity  = float(portfolio.get("equity_previous_close", equity))
    daily_change = equity - prev_equity
    daily_pct    = (daily_change / prev_equity * 100) if prev_equity else 0.0

    print(f"Account equity : ${equity:,.2f}")
    print(f"Buying power   : ${buying_power:,.2f}")
    print(f"Daily change   : ${daily_change:+,.2f}  ({daily_pct:+.2f}%)")
    print()

    positions = rh.account.get_open_stock_positions()
    if positions:
        print(f"Open positions ({len(positions)}):")
        for p in positions:
            sym_data = rh.stocks.get_instrument_by_url(p["instrument"])
            sym = sym_data.get("symbol", "???")
            qty = float(p.get("quantity", 0))
            avg = float(p.get("average_buy_price", 0))
            price_list = rh.stocks.get_latest_price(sym)
            price = float(price_list[0]) if price_list else avg
            pnl_pct = (price - avg) / avg * 100 if avg else 0
            print(f"  {sym}: {qty:.4f} shares  avg ${avg:.2f}  now ${price:.2f}  ({pnl_pct:+.2f}%)")
    else:
        print("No open positions.")

    rh.logout()
    print("\nConnection test PASSED. Bot is ready.")

except Exception as e:
    import traceback
    print(f"ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
