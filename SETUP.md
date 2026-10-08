# AI Trading Bot Setup Guide

## Quick Start (5 minutes)

### Step 1 — Install Python dependencies

```bash
cd trading_bot
pip install -r requirements.txt
```

### Step 2 — Configure your .env file

```bash
copy .env.example .env
```

Open `.env` and fill in:
1. `ANTHROPIC_API_KEY` — get one at https://console.anthropic.com
2. `BROKER` — choose `ROBINHOOD`, `WEBULL`, or `TDAMERITRADE`
3. Your broker credentials (see broker-specific sections below)

### Step 3 — Run in paper trading mode first (STRONGLY recommended)

Make sure `.env` has `PAPER_TRADING=true` then:

```bash
python main.py
```

The bot will simulate trades with $10,000 virtual cash so you can see how it behaves before using real money.

### Step 4 — Switch to live trading (when you're ready)

1. Change `PAPER_TRADING=false` in `.env`
2. Confirm your broker credentials are correct
3. Start with a small amount

```bash
python main.py --live
```

---

## Broker Setup

### Robinhood
Set in `.env`:
```
BROKER=ROBINHOOD
ROBINHOOD_USERNAME=your_email@example.com
ROBINHOOD_PASSWORD=your_password
```
If you have 2FA, temporarily disable it in Robinhood app settings, or provide `ROBINHOOD_MFA_CODE`.

### Webull
Set in `.env`:
```
BROKER=WEBULL
WEBULL_EMAIL=your_email@example.com
WEBULL_PASSWORD=your_password
WEBULL_TRADE_PIN=123456
```

### TD Ameritrade / Schwab
TD Ameritrade was acquired by Schwab. You need a Schwab developer account:
1. Go to https://developer.schwab.com
2. Create an app, get `Client ID` and `Client Secret`
3. Set Redirect URI to `https://localhost:8080`
4. Set in `.env`:
```
BROKER=TDAMERITRADE
TD_CLIENT_ID=your_client_id
TD_CLIENT_SECRET=your_client_secret
TD_REDIRECT_URI=https://localhost:8080
```
5. Run first-time auth:
```bash
python main.py --auth
```
This opens a browser for OAuth. After approving, the token is saved and auto-refreshed.

---

## Commands

| Command | Description |
|---------|-------------|
| `python main.py` | Start the bot (paper or live per .env) |
| `python main.py --paper` | Force paper trading |
| `python main.py --live` | Force live trading |
| `python main.py --once` | Run one analysis cycle and exit |
| `python main.py --status` | Show portfolio + positions |
| `python main.py --auth` | First-time TD Ameritrade/Schwab OAuth |

---

## How It Works

1. **Every N minutes** (default: 15), the bot scans your watchlist
2. **Fetches market data** — 5-day OHLCV at 5-minute intervals + news headlines
3. **Calculates indicators** — RSI, MACD, EMA, Bollinger Bands, Stochastic, ATR, OBV, volume analysis
4. **Asks Claude AI** — sends all data to Claude claude-opus-4-5 and asks for BUY/SELL/HOLD with confidence score
5. **Risk check** — validates against position limits, daily loss cap, trade cap
6. **Executes** — places market order through your broker
7. **Learns** — records trade outcomes and feeds them back to Claude on the next cycle

## Risk Management

- `MAX_POSITION_PCT=0.10` — no single stock > 10% of your portfolio
- `MAX_DAILY_LOSS_PCT=0.02` — bot stops trading if you lose 2% in a day
- `STOP_LOSS_PCT=0.03` — auto-sells if a position drops 3%
- `TAKE_PROFIT_PCT=0.06` — auto-sells when up 6%
- `MIN_CONFIDENCE=0.65` — Claude must be ≥65% confident to trade
- `MAX_TRADES_PER_DAY=10` — hard cap on daily trades

Adjust all of these in `.env`.

---

## Important Disclaimer

This bot is for educational and experimental purposes.
- It can and will lose money. All trading involves risk.
- Past performance of any strategy does not guarantee future results.
- I am not a licensed financial advisor.
- Always start with paper trading. Only use money you can afford to lose.
- Monitor the bot regularly — don't let it run unattended with large sums.
