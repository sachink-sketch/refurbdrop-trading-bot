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

    # Micro-trading settings
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("CRYPTO_SCAN_SECONDS", "120"))   # 2 min
    CANDLE_TIMEFRAME: str = os.getenv("CRYPTO_TIMEFRAME", "1m")                # 1-minute candles
    CANDLE_LIMIT: int = int(os.getenv("CRYPTO_CANDLE_LIMIT", "250"))           # last 250 candles (needs 200+ for SMA200)

    # Risk — tighter for micro trading
    MAX_POSITION_PCT: float  = float(os.getenv("CRYPTO_MAX_POSITION_PCT", "0.08"))   # 8% per trade
    MAX_OPEN_TRADES: int     = int(os.getenv("CRYPTO_MAX_OPEN_TRADES", "5"))         # up from 3
    STOP_LOSS_PCT: float     = float(os.getenv("CRYPTO_STOP_LOSS_PCT", "0.008"))     # 0.8%
    TAKE_PROFIT_PCT: float   = float(os.getenv("CRYPTO_TAKE_PROFIT_PCT", "0.016"))   # 1.6%  (2:1 R/R)
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("CRYPTO_MAX_DAILY_LOSS_PCT", "0.03"))# 3%
    MIN_CONFIDENCE: float    = float(os.getenv("CRYPTO_MIN_CONFIDENCE", "0.60"))     # lowered for more signals

    # Trailing stop — activates once position is +0.8% in profit
    TRAIL_ACTIVATE_PCT: float = float(os.getenv("CRYPTO_TRAIL_ACTIVATE_PCT", "0.008"))
    TRAIL_PCT: float          = float(os.getenv("CRYPTO_TRAIL_PCT", "0.005"))        # trail 0.5% below peak

    # Time-based exit — close position if still open after this many minutes
    TIME_EXIT_MINUTES: int    = int(os.getenv("CRYPTO_TIME_EXIT_MINUTES", "30"))

    def validate(self) -> list[str]:
        errors = []
        if not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is required")
        if self.EXCHANGE not in ("PAPER", "ROBINHOOD"):
            if not self.EXCHANGE_API_KEY or not self.EXCHANGE_API_SECRET:
                errors.append(f"CRYPTO_API_KEY and CRYPTO_API_SECRET required for {self.EXCHANGE}")
        return errors


crypto_config = CryptoConfig()
