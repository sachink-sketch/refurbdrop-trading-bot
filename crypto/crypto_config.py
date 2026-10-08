import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))


class CryptoConfig:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Exchange: PAPER | ROBINHOOD | BINANCE | COINBASE | KRAKEN
    EXCHANGE: str = os.getenv("CRYPTO_EXCHANGE", "PAPER").upper()

    # Exchange API keys (only needed for live trading)
    EXCHANGE_API_KEY: str    = os.getenv("CRYPTO_API_KEY", "")
    EXCHANGE_API_SECRET: str = os.getenv("CRYPTO_API_SECRET", "")
    EXCHANGE_PASSPHRASE: str = os.getenv("CRYPTO_PASSPHRASE", "")  # Coinbase needs this

    # Paper trading starting balance (USDT)
    PAPER_STARTING_USDT: float = float(os.getenv("CRYPTO_PAPER_USDT", "1000.0"))

    # Micro-trading pairs to watch
    PAIRS: list[str] = [
        p.strip().upper()
        for p in os.getenv(
            "CRYPTO_PAIRS",
            "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,DOGE/USDT,AVAX/USDT,LINK/USDT,XRP/USDT"
        ).split(",")
        if p.strip()
    ]

    # Pairs permanently excluded from trading (zero-volume on Binance.US due to USD-not-USDT
    # native liquidity; Claude correctly flags them as unreliable every cycle).
    EXCLUDED_PAIRS: set[str] = {
        p.strip().upper()
        for p in os.getenv("CRYPTO_EXCLUDED_PAIRS", "DOGE/USDT,AVAX/USDT").split(",")
        if p.strip()
    }

    # Micro-trading settings
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("CRYPTO_SCAN_SECONDS", "120"))   # 2 min — matches 5m candle cadence
    CANDLE_TIMEFRAME: str = os.getenv("CRYPTO_TIMEFRAME", "5minute")           # 5-min candles — cleaner signals
    CANDLE_LIMIT: int = int(os.getenv("CRYPTO_CANDLE_LIMIT", "200"))           # last 200 candles (~16 hrs)

    # Risk — tuned for maximum daily P&L on ~$300 account
    MAX_POSITION_PCT: float  = float(os.getenv("CRYPTO_MAX_POSITION_PCT", "0.20"))   # 20% per trade = ~$60/slot
    MAX_OPEN_TRADES: int     = int(os.getenv("CRYPTO_MAX_OPEN_TRADES", "8"))
    STOP_LOSS_PCT: float     = float(os.getenv("CRYPTO_STOP_LOSS_PCT", "0.008"))     # 0.8% SL — tight
    TAKE_PROFIT_PCT: float   = float(os.getenv("CRYPTO_TAKE_PROFIT_PCT", "0.020"))   # 2.0% TP (2.5:1 R/R)
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("CRYPTO_MAX_DAILY_LOSS_PCT", "0.04"))# 4% daily loss cap
    MIN_CONFIDENCE: float    = float(os.getenv("CRYPTO_MIN_CONFIDENCE", "0.55"))     # 55% — catches trending momentum setups

    # Trailing stop — activates at +0.8%, trails tightly to stay in winners longer
    TRAIL_ACTIVATE_PCT: float = float(os.getenv("CRYPTO_TRAIL_ACTIVATE_PCT", "0.008"))
    TRAIL_PCT: float          = float(os.getenv("CRYPTO_TRAIL_PCT", "0.0035"))       # 0.35% trail — tighter

    # Time-based exit — 15 min cuts chop losses fast, frees capital for next trade
    TIME_EXIT_MINUTES: int    = int(os.getenv("CRYPTO_TIME_EXIT_MINUTES", "15"))

    def validate(self) -> list[str]:
        errors = []
        if not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is required")
        if self.EXCHANGE not in ("PAPER", "ROBINHOOD"):
            if not self.EXCHANGE_API_KEY or not self.EXCHANGE_API_SECRET:
                errors.append(f"CRYPTO_API_KEY and CRYPTO_API_SECRET required for {self.EXCHANGE}")
        return errors


crypto_config = CryptoConfig()
